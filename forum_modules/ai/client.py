"""The one place that talks to the model (Google Gemini, via the Gemini API or Vertex AI).

Every AI feature asks for a JSON answer that matches a schema; when the
module is not configured, the API fails or the answer is blocked, the
caller gets None (or BLOCKED) and carries on without AI, so posting is
never blocked by it.
"""
import json
import logging
import os

try:
    from google import genai
    from google.genai import errors, types
except ImportError:  # pip install -r requirements.txt
    genai = None

from .settings import GEMINI_API_KEY, AI_PROVIDER, AI_VERTEX_PROJECT, AI_VERTEX_LOCATION, AI_MODEL, AI_EMBEDDING_MODEL

log = logging.getLogger(__name__)

# Returned instead of an answer when Gemini's safety filters refused the
# request: for moderation that is itself a reason for a human to look.
BLOCKED = object()

_client = {}


def _first(*candidates):
    """(value, source) of the first non-empty (value, source) candidate;
    sources are 'setting', an environment variable's name or 'default'."""
    for value, source in candidates:
        value = str(value or '').strip()
        if value:
            return value, source
    return '', None


def resolve(values=None):
    """Where each connection value comes from: {'provider': 'auto' | 'gemini' |
    'vertex', and for key, project, location, model, embedding_model a
    (value, source) pair}. `values` (by setting name) replaces saved settings:
    the admin tests the form before saving it."""
    values = values or {}
    saved = lambda setting: values.get(setting.name, setting.value)
    env = os.environ.get
    return {
        'provider': str(saved(AI_PROVIDER) or '').strip() or 'auto',
        'key': _first((saved(GEMINI_API_KEY), 'setting'), (env('GEMINI_API_KEY'), 'GEMINI_API_KEY'),
                      (env('GOOGLE_API_KEY'), 'GOOGLE_API_KEY')),
        'project': _first((saved(AI_VERTEX_PROJECT), 'setting'), (env('GOOGLE_CLOUD_PROJECT'), 'GOOGLE_CLOUD_PROJECT')),
        'location': _first((saved(AI_VERTEX_LOCATION), 'setting'),
                           (env('GOOGLE_CLOUD_LOCATION'), 'GOOGLE_CLOUD_LOCATION'), ('global', 'default')),
        'model': _first((saved(AI_MODEL), 'setting')),
        'embedding_model': _first((saved(AI_EMBEDDING_MODEL), 'setting')),
    }


def connection(values=None):
    """('vertex', project, location), ('gemini', api_key) or None. "Connect
    through" picks one; Automatic prefers Vertex AI when a project is set."""
    found = resolve(values)
    provider, project, key = found['provider'], found['project'][0], found['key'][0]
    if project and provider in ('auto', 'vertex'):
        return ('vertex', project, found['location'][0])
    if key and provider in ('auto', 'gemini'):
        return ('gemini', key)
    return None


def is_configured():
    return genai is not None and connection() is not None


def build_client(target, timeout=None):
    """A google.genai client for a connection() target; `timeout` in seconds."""
    options = {'http_options': types.HttpOptions(timeout=int(timeout * 1000))} if timeout else {}
    if target[0] == 'vertex':
        # Credentials come from Application Default Credentials (the
        # server's service account, or `gcloud auth application-default login`).
        return genai.Client(vertexai=True, project=target[1], location=target[2], **options)
    return genai.Client(api_key=target[1], **options)


def get_client():
    target = connection()
    if _client.get('target') != target:
        _client.update(target=target, client=build_client(target))
    return _client['client']


def json_config(system, schema, thinking='low'):
    """The request settings of every JSON answer (ask_model, the admin's test)."""
    return types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type='application/json',
        response_json_schema=schema,
        # Classification work: little thinking keeps it fast and cheap; the
        # assistant's fact check asks for more.
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[thinking.upper()]),
        # The posts being classified may well be abusive; the filters must not
        # stop the model from reading them (PROHIBITED_CONTENT still applies).
        safety_settings=[types.SafetySetting(category=category, threshold=types.HarmBlockThreshold.OFF)
                         for category in (types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                                          types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                                          types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                                          types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT)],
    )


def ask_model(system, content, schema, thinking='low'):
    """The model's answer to `content` as a dict matching the JSON `schema`;
    None if there is no usable answer, BLOCKED if the safety filters refused."""
    if not is_configured():
        return None

    model = str(AI_MODEL).strip()
    config = json_config(system, schema, thinking)

    try:
        response = get_client().models.generate_content(model=model, contents=content, config=config)
    except errors.ClientError as e:
        log.error("AI request rejected (HTTP %s; check the key, project and model '%s'): %s", e.code, model, e.message)
        return None
    except errors.APIError as e:
        log.warning("AI request failed with HTTP %s: %s", e.code, e.message)
        return None
    except Exception as e:  # network errors, missing Google Cloud credentials, ...
        log.warning("AI request failed: %s", e)
        return None

    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason:
        log.info("AI request blocked: %s", feedback.block_reason)
        return BLOCKED

    candidate = response.candidates[0] if response.candidates else None
    reason = candidate.finish_reason if candidate is not None else None
    if reason in (types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT,
                  types.FinishReason.BLOCKLIST, types.FinishReason.SPII):
        log.info("AI answer blocked: %s", reason)
        return BLOCKED
    if reason != types.FinishReason.STOP:
        log.info("AI request ended with finish_reason=%s", reason)
        return None

    try:
        return json.loads(response.text)
    except (TypeError, ValueError):
        log.warning("AI response was not valid JSON")
        return None


EMBEDDING_DIMENSIONS = 768
EMBEDDING_BATCH = 50


def embed_texts(texts):
    """Embedding vectors (lists of floats) for `texts`, or None on failure.
    gemini-embedding-2 takes the task as part of the text, see knowledge.py."""
    if not is_configured():
        return None
    vectors = []
    try:
        for start in range(0, len(texts), EMBEDDING_BATCH):
            response = get_client().models.embed_content(
                model=str(AI_EMBEDDING_MODEL).strip(), contents=texts[start:start + EMBEDDING_BATCH],
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS))
            vectors += [list(embedding.values) for embedding in response.embeddings]
    except errors.APIError as e:
        log.warning("Embedding request failed with HTTP %s: %s", e.code, e.message)
        return None
    except Exception as e:
        log.warning("Embedding request failed: %s", e)
        return None
    return vectors if len(vectors) == len(texts) else None


def write_text(system, content):
    """A free-text (Markdown) answer; None if there is no usable answer,
    BLOCKED if the safety filters refused."""
    if not is_configured():
        return None
    config = types.GenerateContentConfig(system_instruction=system)
    try:
        response = get_client().models.generate_content(model=str(AI_MODEL).strip(), contents=content, config=config)
    except errors.APIError as e:
        log.warning("AI answer request failed with HTTP %s: %s", e.code, e.message)
        return None
    except Exception as e:
        log.warning("AI answer request failed: %s", e)
        return None

    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason:
        return BLOCKED
    candidate = response.candidates[0] if response.candidates else None
    reason = candidate.finish_reason if candidate is not None else None
    if reason in (types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT,
                  types.FinishReason.BLOCKLIST, types.FinishReason.SPII):
        return BLOCKED
    if reason != types.FinishReason.STOP or not response.text:
        log.info("AI answer request ended with finish_reason=%s", reason)
        return None
    return response.text.strip()
