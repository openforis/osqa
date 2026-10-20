"""The assistant's knowledge: forum threads and crawled documentation, split
into chunks with Gemini embeddings (KnowledgeChunk), and semantic search
over them. Rebuilt incrementally by manage.py build_knowledge_index."""
import hashlib
import logging
import threading
from datetime import datetime

import numpy as np

from forum.models import Question, Answer, KnowledgeChunk, KeyValue
from forum.utils import similar

from .client import embed_texts, is_configured
from .crawler import crawl
from .settings import AI_KNOWLEDGE_SEEDS, AI_KNOWLEDGE_MAX_PAGES, AI_EMBEDDING_MODEL

log = logging.getLogger(__name__)

CHUNK_CHARS = 2500
CHUNK_OVERLAP = 300
MAX_THREAD_CHARS = 8000


def document_text(title, text):
    # gemini-embedding-2 takes the task as an instruction in the text.
    return 'title: %s | text: %s' % (title or 'none', text)


def query_text(query):
    return 'task: question answering | query: %s' % query


def split_text(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Chunks of about `size` characters, cut at paragraph (or line) breaks."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind('\n\n', start + size // 2, end), text.rfind('\n', start + size // 2, end))
            end = cut if cut > start else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _source(node):
    revision = node.active_revision
    return (revision.body if revision else node.body).strip()


def thread_document(question):
    """(text, quality) of an answered question, or None. Best answers first."""
    answers = list(Answer.objects.filter(parent=question).public().order_by('-score', 'added_at'))
    answers.sort(key=lambda a: not a.nis.accepted)
    if not answers:
        return None
    parts = ['Question (tags: %s): %s' % (', '.join(question.tagname_list()), _source(question))]
    for answer in answers:
        label = 'Accepted answer' if answer.nis.accepted else 'Answer (score %d)' % answer.score
        parts.append('%s, %s: %s' % (label, answer.added_at.strftime('%Y-%m'), _source(answer)))
    accepted = any(a.nis.accepted for a in answers)
    best = max(a.score for a in answers)
    quality = 1.0 + (0.5 if accepted else 0) + 0.05 * max(min(best, 10), -10)
    return '\n\n'.join(parts)[:MAX_THREAD_CHARS], quality


def forum_documents():
    for question in Question.objects.public().order_by('id').iterator():
        if question.duplicate_of:
            continue  # the original holds the answers
        document = thread_document(question)
        if document:
            text, quality = document
            yield dict(url=question.get_absolute_url(), position=0, title=question.title, text=text,
                       node=question, quality=quality)


def web_documents(seeds=None, max_pages=None, fetcher=None):
    seeds = [s.strip() for s in str(AI_KNOWLEDGE_SEEDS if seeds is None else seeds).splitlines() if s.strip()]
    max_pages = int(AI_KNOWLEDGE_MAX_PAGES) if max_pages is None else max_pages
    robots, seen = {}, set()
    for seed in seeds:
        kwargs = dict(robots_cache=robots)
        if fetcher is not None:
            kwargs.update(fetcher=fetcher, delay=0)
        for url, title, text in crawl(seed, max_pages, **kwargs):
            if url in seen:
                continue
            seen.add(url)
            for position, chunk in enumerate(split_text(text)):
                yield dict(url=url, position=position, title=title[:300], text=chunk, node=None, quality=1.0)


# The embedding model each source's vectors come from: vectors of another
# model can't be compared, so a new model re-embeds every chunk.
MODEL_KEY = 'ai.knowledge.embedding_model.%s'


def index_model(source):
    """The embedding model `source`'s chunks were embedded with, or None."""
    try:
        return KeyValue.objects.get(key=MODEL_KEY % source).value
    except KeyValue.DoesNotExist:
        return None


def _remember_model(source, model):
    try:
        kv = KeyValue.objects.get(key=MODEL_KEY % source)
    except KeyValue.DoesNotExist:
        kv = KeyValue(key=MODEL_KEY % source)
    kv.value = model
    kv.save()


def sync(source, documents, stdout=None):
    """Stores `documents` as the chunks of `source`: unchanged chunks are kept,
    changed or new ones embedded, chunks no longer produced removed; all of
    them when the embedding model changed. Returns (kept, embedded, removed)."""
    existing = {(c.url, c.position): c for c in KnowledgeChunk.objects.filter(source=source).defer('embedding')}
    model = str(AI_EMBEDDING_MODEL).strip()
    # An index from before the model was recorded is taken to be the current model's.
    previous = index_model(source)
    new_model = previous is not None and previous != model
    seen, pending = set(), []
    kept = 0
    for doc in documents:
        key = (doc['url'][:500], doc['position'])
        seen.add(key)
        digest = hashlib.sha1(('%s\n%s' % (doc['title'], doc['text'])).encode('utf-8')).hexdigest()
        chunk = existing.get(key)
        if chunk is not None and chunk.content_hash == digest and not new_model:
            if abs(chunk.quality - doc['quality']) > 1e-6:
                KnowledgeChunk.objects.filter(id=chunk.id).update(quality=doc['quality'])
            kept += 1
            continue
        chunk = chunk or KnowledgeChunk(source=source, url=key[0], position=key[1])
        chunk.title, chunk.text, chunk.node, chunk.quality, chunk.content_hash = \
            doc['title'][:300], doc['text'], doc['node'], doc['quality'], digest
        pending.append(chunk)

    embedded = 0
    for start in range(0, len(pending), 50):
        batch = pending[start:start + 50]
        vectors = embed_texts([document_text(c.title, c.text) for c in batch])
        if vectors is None:
            raise RuntimeError('embedding failed; the index was left as it was')
        for chunk, vector in zip(batch, vectors):
            chunk.embedding = np.asarray(vector, dtype=np.float32).tobytes()
            chunk.updated_at = datetime.now()
            chunk.save()
            embedded += 1

    stale = [c.id for key, c in existing.items() if key not in seen]
    KnowledgeChunk.objects.filter(id__in=stale).delete()
    if previous != model:
        _remember_model(source, model)
    _matrix_cache.clear()
    return kept, embedded, len(stale)


# ---- search ------------------------------------------------------------

_matrix_cache = {}
_matrix_lock = threading.Lock()


def _matrix():
    """(ids, normalised embedding matrix) of all chunks, cached per process
    until the index changes."""
    latest = KnowledgeChunk.objects.order_by('-updated_at').values_list('updated_at', flat=True).first()
    key = (KnowledgeChunk.objects.count(), latest)
    with _matrix_lock:
        if _matrix_cache.get('key') != key:
            rows = list(KnowledgeChunk.objects.exclude(embedding=None).values_list('id', 'embedding'))
            ids = [row[0] for row in rows]
            matrix = np.array([np.frombuffer(bytes(row[1]), dtype=np.float32) for row in rows]) if rows else np.zeros((0, 1))
            if len(matrix):
                matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
            _matrix_cache.update(key=key, ids=ids, matrix=matrix)
        return _matrix_cache['ids'], _matrix_cache['matrix']


def search(query, limit=8, source=None, min_score=0.2, spread=0.2):
    """The KnowledgeChunks most similar to `query`, best first, each with a
    .similarity attribute. Quality (accepted, voted answers) breaks near-ties.

    Results must reach `min_score` and lie within `spread` of the best match;
    whether they really answer the question is left to the model."""
    if not is_configured() or not query.strip():
        return []
    ids, matrix = _matrix()
    if not ids:
        return []
    vectors = embed_texts([query_text(query)])
    if not vectors:
        return []
    q = np.asarray(vectors[0], dtype=np.float32)
    q /= np.linalg.norm(q) + 1e-9
    scores = matrix @ q
    order = np.argsort(-scores)[:max(limit * 4, 20)]
    floor = max(min_score, float(scores[order[0]]) - spread)
    chunks = KnowledgeChunk.objects.in_bulk([ids[i] for i in order])
    results = []
    for i in order:
        chunk = chunks.get(ids[i])
        if chunk is None or (source and chunk.source != source) or scores[i] < floor:
            continue
        chunk.similarity = float(scores[i])
        results.append(chunk)
    results.sort(key=lambda c: -(c.similarity + 0.03 * (c.quality - 1.0)))
    return results[:limit]


def similar_questions(query, limit=10):
    """Questions whose threads are semantically closest to `query`."""
    questions = []
    for chunk in search(query, limit=limit, source='forum'):
        if chunk.node_id and chunk.node_id not in [q.id for q in questions]:
            question = Question.objects.filter(id=chunk.node_id).first()
            if question is not None and not question.nis.deleted and not question.nis.pending_review:
                questions.append(question)
    return questions


similar.SEARCH_PROVIDERS.append(similar_questions)
