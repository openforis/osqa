import json
import re
import zlib
from io import StringIO
from types import SimpleNamespace
from unittest import mock
from urllib.robotparser import RobotFileParser

from django.core.management import call_command
from django.core.management.base import CommandError

from forum.actions import AcceptAnswerAction, DeleteAction
from forum.models import Question, Answer, KnowledgeChunk

from .test_ai import AITestCase, FakeGemini

STOP = {'the', 'a', 'to', 'of', 'and', 'in', 'how', 'do', 'i', 'my', 'is', 'it', 'title', 'text', 'task', 'query',
        'question', 'answering', 'none', 'answer', 'accepted', 'tags', 'score'}


def fake_vector(text):
    """Bag of words hashed into 768 dimensions: shared words, similar vectors."""
    vector = [0.0] * 768
    for word in re.findall(r'[a-z]+', text.lower()):
        if word not in STOP and len(word) > 2:
            vector[zlib.crc32(word.encode()) % 768] += 1.0
    return vector


class FakeGeminiWithEmbeddings(FakeGemini):
    def __init__(self, *answers, **kwargs):
        super().__init__(*answers, **kwargs)
        self.embedded = []
        self.models.embed_content = self.embed_content

    def embed_content(self, model, contents, config):
        self.embedded += list(contents)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=fake_vector(t)) for t in contents])


def allow_all(base, cache):
    parser = RobotFileParser()
    parser.parse(['User-agent: *', 'Disallow: /docs/private/'])
    return parser


PAGES = {
    'https://docs.example.org/docs/': ('<html><head><title>Docs home</title></head><body><nav>Menu Login</nav>'
                                       '<h1>Collect documentation</h1><p>%s</p><a href="install.html">Install</a>'
                                       '<a href="private/secret.html">Secret</a><a href="/blog/news.html">Blog</a>'
                                       '<a href="https://elsewhere.example/x">Elsewhere</a><a href="manual.pdf">PDF</a>'
                                       '<footer>Copyright</footer></body></html>' % ('Welcome to Collect. ' * 20)),
    'https://docs.example.org/docs/install.html': ('<html><head><title>Installing Collect</title></head><body>'
                                                   '<p>%s</p></body></html>' % ('Install Java then run the Collect installer. ' * 15)),
    'https://docs.example.org/docs/private/secret.html': '<html><body><p>%s</p></body></html>' % ('secret ' * 100),
    'https://docs.example.org/blog/news.html': '<html><body><p>%s</p></body></html>' % ('news ' * 100),
}


def fake_fetch(url):
    return (url, PAGES[url]) if url in PAGES else None


class KnowledgeIndexTest(AITestCase):
    def setUp(self):
        super().setUp()
        self.fake = self.gemini_embeddings()
        patcher = mock.patch('forum_modules.ai.crawler._robots', allow_all)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.alice = self.create_user('alice')
        self.bob = self.create_user('bob')
        self.export = self.question('How do I export survey data to CSV?', 'collect export')
        self.answer = Answer(author=self.bob, parent=self.export, body='Use the CSV export in the Collect designer.')
        self.answer.save()
        AcceptAnswerAction(user=self.alice, node=self.answer, ip='127.0.0.1').save()
        self.landsat = self.question('Landsat cloud masking in Earth Map', 'earthmap')
        Answer(author=self.bob, parent=self.landsat, body='Enable the cloud mask layer before computing NDVI.').save()
        self.unanswered = self.question('Unanswered thing about plots', 'collect')

    def gemini_embeddings(self, *answers):
        fake = FakeGeminiWithEmbeddings(*answers or ({},))
        patcher = mock.patch('forum_modules.ai.client.get_client', return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def question(self, title, tags):
        question = Question(author=self.alice, title=title, tagnames=tags, body='Body of: %s, long enough.' % title)
        question.save()
        return question

    def sync_forum(self):
        from forum_modules.ai import knowledge
        return knowledge.sync('forum', knowledge.forum_documents())

    def test_forum_threads_are_indexed_incrementally(self):
        self.assertEqual(self.sync_forum(), (0, 2, 0))
        chunk = KnowledgeChunk.objects.get(node=self.export)
        self.assertIn('Accepted answer', chunk.text)
        self.assertIn('Use the CSV export', chunk.text)
        self.assertGreater(chunk.quality, KnowledgeChunk.objects.get(node=self.landsat).quality)
        self.assertFalse(KnowledgeChunk.objects.filter(node=self.unanswered).exists())

        self.fake.embedded.clear()
        self.assertEqual(self.sync_forum(), (2, 0, 0))
        self.assertEqual(self.fake.embedded, [])

        DeleteAction(user=self.alice, node=self.landsat, ip='127.0.0.1').save()
        self.assertEqual(self.sync_forum(), (1, 0, 1))

    def test_a_new_embedding_model_embeds_everything_again(self):
        from forum_modules.ai import knowledge
        self.assertEqual(self.sync_forum(), (0, 2, 0))
        self.assertEqual(knowledge.index_model('forum'), 'gemini-embedding-2')
        self.set(self.ai.AI_EMBEDDING_MODEL, 'gemini-embedding-3')
        self.assertEqual(self.sync_forum(), (0, 2, 0))
        self.assertEqual(knowledge.index_model('forum'), 'gemini-embedding-3')
        self.assertEqual(self.sync_forum(), (2, 0, 0))

    def test_an_index_from_before_the_model_was_recorded_is_kept(self):
        from forum.models import KeyValue
        from forum_modules.ai import knowledge
        self.sync_forum()
        KeyValue.objects.filter(key=knowledge.MODEL_KEY % 'forum').delete()
        self.assertEqual(self.sync_forum(), (2, 0, 0))
        self.assertEqual(knowledge.index_model('forum'), 'gemini-embedding-2')

    def test_documentation_crawl(self):
        from forum_modules.ai import knowledge
        documents = list(knowledge.web_documents(seeds='https://docs.example.org/docs/', max_pages=10, fetcher=fake_fetch))
        urls = {d['url'] for d in documents}
        self.assertEqual(urls, {'https://docs.example.org/docs/', 'https://docs.example.org/docs/install.html'})
        home = next(d for d in documents if d['url'] == 'https://docs.example.org/docs/')
        self.assertEqual(home['title'], 'Docs home')
        self.assertIn('Collect documentation', home['text'])
        self.assertNotIn('Menu Login', home['text'])
        self.assertNotIn('Copyright', home['text'])

    def test_crawler_skips_the_forum_itself(self):
        from forum_modules.ai import knowledge
        from forum import settings
        with mock.patch.object(settings, 'APP_URL', 'https://docs.example.org'):
            self.assertEqual(list(knowledge.web_documents(seeds='https://docs.example.org/docs/', fetcher=fake_fetch)), [])

    def test_long_pages_are_split(self):
        from forum_modules.ai.knowledge import split_text
        text = '\n\n'.join('Paragraph %d. ' % i + 'word ' * 100 for i in range(20))
        chunks = split_text(text)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 2500 for c in chunks))
        self.assertTrue(chunks[1].startswith('Paragraph') or 'Paragraph' in chunks[1][:400])

    def test_semantic_search(self):
        self.sync_forum()
        from forum_modules.ai import knowledge
        results = knowledge.search('cloud mask NDVI landsat imagery')
        self.assertEqual(results[0].node_id, self.landsat.id)
        self.assertEqual([q.id for q in knowledge.similar_questions('export survey data csv')][:1], [self.export.id])

    def test_mcp_search_uses_the_index(self):
        self.sync_forum()
        response = self.client.post('/mcp', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'search_forum', 'arguments': {'query': 'cloud mask NDVI'}}}), content_type='application/json')
        hits = json.loads(response.json()['result']['content'][0]['text'])['results']
        self.assertEqual(hits[0]['id'], self.landsat.id)

    def test_duplicate_check_adds_semantic_candidates(self):
        from forum_modules.ai import duplicates
        with mock.patch('forum_modules.ai.knowledge.similar_questions', return_value=[self.landsat]):
            fake = self.gemini_embeddings({'duplicates': [{'id': self.landsat.id, 'reason': 'Same masking problem.'}]})
            found = duplicates.find_duplicates('Removing clouds from satellite images')
        self.assertEqual(found, [(self.landsat, 'Same masking problem.')])
        self.assertIn('<question id="%d">' % self.landsat.id, fake.prompt)

    def test_command(self):
        out = StringIO()
        with mock.patch('forum_modules.ai.crawler.fetch', fake_fetch), \
                mock.patch('forum_modules.ai.crawler.time.sleep'):
            self.set(self.ai.AI_KNOWLEDGE_SEEDS, 'https://docs.example.org/docs/')
            call_command('build_knowledge_index', stdout=out)
            self.assertIn('Forum threads: 0 unchanged, 2 indexed', out.getvalue())
            self.assertIn('Documentation chunks: 0 unchanged, 2 indexed', out.getvalue())

        out = StringIO()
        with mock.patch('forum_modules.ai.crawler.fetch', return_value=None), \
                mock.patch('forum_modules.ai.crawler.time.sleep'):
            call_command('build_knowledge_index', '--web-only', stdout=out)
        self.assertIn('indexed pages were kept', out.getvalue())
        self.assertEqual(KnowledgeChunk.objects.filter(source='web').count(), 2)

        self.set(self.ai.GEMINI_API_KEY, '')
        with self.assertRaises(CommandError):
            call_command('build_knowledge_index', stdout=StringIO())
