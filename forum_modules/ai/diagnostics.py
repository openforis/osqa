"""Admin > AI assistance: the connection section's panel (status_panel: the
knowledge index and "Test connection") and the test (run_test), which tries
the values in the form without saving them and explains every failure.

run_test() checks, in order: the google-genai library, that a connection is
set (and where each value comes from), Google Cloud credentials (Vertex AI),
one JSON answer from the text model with the request settings the features
use (client.json_config) and one embedding. Each check is a dict
{'name', 'state': 'ok' | 'warn' | 'fail' | 'skip', 'summary', 'hints',
'detail'}; API keys never appear in them (redact()).
"""
import json
import socket
import time
from datetime import datetime

from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from . import client
from .settings import (AI_PROVIDER, GEMINI_API_KEY, AI_VERTEX_PROJECT, AI_VERTEX_LOCATION, AI_MODEL,
                       AI_EMBEDDING_MODEL)

# The form fields the test reads; everything else in the form is ignored.
CONNECTION_SETTINGS = (AI_PROVIDER, GEMINI_API_KEY, AI_VERTEX_PROJECT, AI_VERTEX_LOCATION, AI_MODEL,
                       AI_EMBEDDING_MODEL)
TIMEOUT = 30  # seconds per request
TEST_SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'],
               'additionalProperties': False}
CLOUD_SCOPE = 'https://www.googleapis.com/auth/cloud-platform'


def form_values(post):
    """The connection values posted with the settings form, by setting name."""
    return {s.name: post[s.name] for s in CONNECTION_SETTINGS if s.name in post}


def mask(key):
    return (key[:4] + '…' + key[-4:]) if len(key) > 12 else '…'


def redact(text, found):
    key = found['key'][0]
    text = str(text)
    return text.replace(key, mask(key)) if key else text


def source_label(source):
    if source == 'setting':
        return _("this page")
    if source == 'default':
        return _("the default")
    return _("the %(name)s environment variable") % {'name': source}


def host(target):
    if target[0] == 'gemini':
        return 'generativelanguage.googleapis.com'
    return 'aiplatform.googleapis.com' if target[2] == 'global' else '%s-aiplatform.googleapis.com' % target[2]


def describe(found, target):
    """One sentence on what the AI features connect with."""
    if target is None:
        return _("Not configured: the AI features are off.")
    if target[0] == 'vertex':
        project, project_source = found['project']
        location, location_source = found['location']
        return _("Vertex AI in project %(project)s (from %(project_from)s), location %(location)s "
                 "(from %(location_from)s).") % {
            'project': project, 'project_from': source_label(project_source),
            'location': location, 'location_from': source_label(location_source)}
    key, key_source = found['key']
    return _("Gemini API with the key %(key)s (from %(key_from)s).") % {
        'key': mask(key), 'key_from': source_label(key_source)}


def check(name, state, summary, hints=(), detail=''):
    return {'name': name, 'state': state, 'summary': summary, 'hints': list(hints), 'detail': detail}


# ---- the test ----------------------------------------------------------------

def run_test(values=None):
    """{'ok': bool, 'connection': sentence, 'checks': [check, ...]}."""
    found = client.resolve(values)
    target = client.connection(values)
    result = {'connection': describe(found, target), 'checks': []}
    checks = result['checks']

    if client.genai is None:
        checks.append(check(_("Library"), 'fail', _("The google-genai package is not installed on the server."),
                            [_("Install the requirements: pip install -r requirements.txt, then restart the site.")]))
        result['ok'] = False
        return result

    checks.extend(_connection_checks(found, target))
    if target is None or any(c['state'] == 'fail' for c in checks):
        result['ok'] = False
        return result

    if target[0] == 'vertex':
        credentials = _credentials_check(target)
        checks.append(credentials)
        if credentials['state'] == 'fail':
            result['ok'] = False
            return result

    try:
        api = client.build_client(target, timeout=TIMEOUT)
    except Exception as e:
        checks.append(_failure(_("Connection"), e, found, target, None))
        result['ok'] = False
        return result

    text = _text_check(api, found, target)
    checks.append(text)
    if text['state'] == 'fail' and text.get('connection_problem'):
        checks.append(check(_("Embedding model"), 'skip', _("Not tested: fix the problem above first.")))
    else:
        checks.append(_embedding_check(api, found, target))
    result['ok'] = all(c['state'] in ('ok', 'warn') for c in checks)
    return result


def _connection_checks(found, target):
    provider = found['provider']
    key, project = found['key'][0], found['project'][0]
    if target is None:
        if provider == 'gemini':
            hints = [_("Enter a Gemini API key, or set GEMINI_API_KEY on the server. Create one at "
                       "aistudio.google.com/apikey.")]
        elif provider == 'vertex':
            hints = [_("Enter the Google Cloud project ID under \"Vertex AI project\", or set "
                       "GOOGLE_CLOUD_PROJECT on the server.")]
        else:
            hints = [_("The simplest is a Gemini API key from aistudio.google.com/apikey."),
                     _("Or use Vertex AI: enter your Google Cloud project ID.")]
        return [check(_("Connection"), 'fail', _("No API key or Vertex AI project is set."), hints)]

    checks = [check(_("Connection"), 'ok', describe(found, target))]
    if target[0] == 'vertex' and key and provider == 'auto':
        checks.append(check(_("Connection"), 'warn',
                            _("A Vertex AI project is set, so the Gemini API key is not used."),
                            [_("To use the key instead, choose \"Gemini API key\" under \"Connect through\".")]))
    if target[0] == 'gemini' and not key.startswith('AIza'):
        checks.append(check(_("API key"), 'warn', _("Gemini API keys usually start with AIza."),
                            [_("Check that you copied the whole key from Google AI Studio, without spaces.")]))
    if target[0] == 'vertex' and (' ' in project or project != project.lower()):
        checks.append(check(_("Vertex AI project"), 'warn',
                            _("\"%(project)s\" doesn't look like a project ID.") % {'project': project},
                            [_("Use the project ID shown in the Google Cloud console's project picker "
                               "(lowercase letters, digits and dashes), not the project's display name.")]))
    for name, (value, _source) in ((_("Gemini model"), found['model']),
                                   (_("Embedding model"), found['embedding_model'])):
        if not value:
            checks.append(check(name, 'fail', _("No model is set."), [_("Enter a model ID, e.g. the default.")]))
    return checks


def _credentials_check(target):
    try:
        import google.auth
        from google.auth import exceptions as auth_errors
    except ImportError:
        return check(_("Google Cloud credentials"), 'fail', _("The google-auth package is missing."),
                     [_("Install the requirements: pip install -r requirements.txt.")])
    try:
        credentials, default_project = google.auth.default(scopes=[CLOUD_SCOPE])
    except auth_errors.DefaultCredentialsError as e:
        return check(_("Google Cloud credentials"), 'fail',
                     _("The server has no Google Cloud credentials (Application Default Credentials)."),
                     _no_credentials_hints(), str(e))
    except Exception as e:
        return check(_("Google Cloud credentials"), 'fail', _("Google Cloud credentials could not be loaded."),
                     _no_credentials_hints(), '%s: %s' % (type(e).__name__, e))
    account = getattr(credentials, 'service_account_email', None)
    if account and account != 'default':
        summary = _("Signed in as the service account %(account)s.") % {'account': account}
    else:
        summary = _("Signed in with %(kind)s credentials.") % {'kind': type(credentials).__name__}
    if default_project and default_project != target[1]:
        summary += ' ' + _("(The credentials' own project is %(project)s; requests go to %(target)s.)") % {
            'project': default_project, 'target': target[1]}
    return check(_("Google Cloud credentials"), 'ok', summary)


def _no_credentials_hints():
    return [_("On Google Cloud (Compute Engine, Cloud Run, GKE): attach a service account to the instance or "
              "service."),
            _("Elsewhere: create a service account key and point GOOGLE_APPLICATION_CREDENTIALS at the JSON file, "
              "or run gcloud auth application-default login as the user the site runs as."),
            _("The account needs the Vertex AI User role in the project. Restart the site after changing "
              "credentials.")]


def _text_check(api, found, target):
    name = _("Gemini model")
    model = found['model'][0]
    started = time.monotonic()
    try:
        response = api.models.generate_content(
            model=model, contents='Reply with {"ok": true}.',
            config=client.json_config('You check that the connection works. Answer with the JSON asked for.',
                                      TEST_SCHEMA))
    except Exception as e:
        return _failure(name, e, found, target, model, api=api, kind='text')
    seconds = time.monotonic() - started

    candidate = response.candidates[0] if response.candidates else None
    reason = candidate.finish_reason if candidate is not None else None
    if reason != client.types.FinishReason.STOP:
        return check(name, 'fail', _("%(model)s answered but did not finish (%(reason)s).") % {
            'model': model, 'reason': reason},
            [_("Try again; if it keeps happening, choose another model.")])
    try:
        answer = json.loads(response.text)
    except (TypeError, ValueError):
        answer = None
    if not isinstance(answer, dict) or answer.get('ok') is not True:
        return check(name, 'fail', _("%(model)s answered, but not with the JSON it was asked for.") % {'model': model},
                     [_("Choose a model that supports JSON output, e.g. the default.")],
                     redact(response.text, found)[:500])
    return check(name, 'ok', _("%(model)s answered in %(seconds).1f s.") % {'model': model, 'seconds': seconds})


def _embedding_check(api, found, target):
    name = _("Embedding model")
    model = found['embedding_model'][0]
    started = time.monotonic()
    try:
        response = api.models.embed_content(
            model=model, contents=['connection test'],
            config=client.types.EmbedContentConfig(output_dimensionality=client.EMBEDDING_DIMENSIONS))
    except Exception as e:
        return _failure(name, e, found, target, model, api=api, kind='embedding')
    seconds = time.monotonic() - started
    vectors = [list(e.values or []) for e in (response.embeddings or [])]
    if len(vectors) != 1 or len(vectors[0]) != client.EMBEDDING_DIMENSIONS:
        return check(name, 'fail', _("%(model)s did not return a vector of %(size)d numbers.") % {
            'model': model, 'size': client.EMBEDDING_DIMENSIONS},
            [_("Choose an embedding model that supports output_dimensionality, e.g. gemini-embedding-2.")])
    return check(name, 'ok', _("%(model)s answered in %(seconds).1f s.") % {'model': model, 'seconds': seconds})


# ---- explaining failures -------------------------------------------------------

def _reasons(error):
    """The ErrorInfo reasons and metadata of a Google API error."""
    body = getattr(error, 'details', None)
    details = body.get('error', {}).get('details', []) if isinstance(body, dict) else []
    reasons, metadata = [], {}
    for item in details if isinstance(details, list) else []:
        if isinstance(item, dict) and item.get('reason'):
            reasons.append(item['reason'])
            metadata.update(item.get('metadata') or {})
    return reasons, metadata


def _failure(name, error, found, target, model, api=None, kind='text'):
    """A failed check explaining `error` in plain words, with what to do."""
    summary, hints, connection_problem = explain(error, found, target, model, api=api, kind=kind)
    result = check(name, 'fail', summary, hints, redact('%s: %s' % (type(error).__name__, error), found)[:2000])
    result['connection_problem'] = connection_problem
    return result


def explain(error, found, target, model, api=None, kind='text'):
    """(summary, hints, is_a_connection_problem) for an exception of a request."""
    errors = client.errors
    vertex = target[0] == 'vertex'
    project = target[1] if vertex else ''
    if isinstance(error, errors.APIError):
        code, status = error.code, (error.status or '')
        message = str(error.message or '')
        lowered = message.lower()
        reasons, metadata = _reasons(error)

        if 'API_KEY_INVALID' in reasons or 'api key not valid' in lowered or 'api key expired' in lowered:
            return (_("Google doesn't accept this API key."),
                    [_("Copy the key again from aistudio.google.com/apikey (the whole key, without spaces) and test "
                       "again."),
                     _("Keys of deleted projects, and keys that were rotated or expired, stop working.")], True)
        if any(r.startswith('API_KEY_') and r.endswith('_BLOCKED') for r in reasons) or 'are blocked' in lowered:
            return (_("The API key's restrictions don't allow this request."),
                    [_("In the Google Cloud console > APIs & Services > Credentials, open the key: under "
                       "\"API restrictions\" allow the Generative Language API."),
                     _("Under \"Application restrictions\" choose None or IP addresses (with this server's address): "
                       "website (HTTP referrer) restrictions block requests from a server.")], True)
        if 'SERVICE_DISABLED' in reasons or 'has not been used in project' in lowered or 'is disabled' in lowered:
            url = metadata.get('activationUrl') or (
                'https://console.cloud.google.com/apis/library/aiplatform.googleapis.com?project=%s' % project
                if vertex else 'https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com')
            api_name = _("Vertex AI API") if vertex else _("Generative Language API")
            return (_("The %(api)s is not enabled in the Google Cloud project.") % {'api': api_name},
                    [_("Enable it at %(url)s, wait a few minutes and test again.") % {'url': url}], True)
        if 'BILLING_DISABLED' in reasons or 'billing' in lowered:
            return (_("Billing is not enabled for the Google Cloud project."),
                    [_("Link a billing account in the Google Cloud console > Billing, then test again.")], True)
        if 'location is not supported' in lowered or ('user location' in lowered and not vertex):
            return (_("The Gemini API is not available from the country this server is in."),
                    [_("Use Vertex AI instead: choose \"Vertex AI\" and enter a Google Cloud project.")], True)
        if code == 401 or status == 'UNAUTHENTICATED':
            hints = ([_("The credentials were refused or have expired: run gcloud auth application-default login "
                        "again, or check the service account key.")] if vertex else
                     [_("Copy the API key again from aistudio.google.com/apikey.")])
            return (_("Google couldn't confirm who is calling (HTTP 401)."), hints, True)
        if code == 403 or status == 'PERMISSION_DENIED':
            if vertex:
                return (_("The server's Google Cloud account may not use Vertex AI in project %(project)s.") % {
                    'project': project},
                        [_("Check that %(project)s is the project ID (a wrong ID gives this error too).") % {
                            'project': project},
                         _("Give the account the Vertex AI User role (roles/aiplatform.user) in Google Cloud console "
                           "> IAM, then test again.")], True)
            return (_("Google refused the request (HTTP 403)."),
                    [_("Check that the key belongs to a project with the Generative Language API enabled, and that "
                       "its restrictions allow it.")], True)
        if code == 404 or status == 'NOT_FOUND':
            hints = [_("Check the spelling of the model ID; models are retired after a while.")]
            if vertex and target[2] != 'global':
                hints.append(_("Not every model is offered in %(location)s: try the location global.") % {
                    'location': target[2]})
            available = available_models(api, kind)
            if available:
                hints.append(_("Models this connection offers include: %(models)s.") % {
                    'models': ', '.join(available)})
            return (_("The model %(model)s was not found.") % {'model': model}, hints, False)
        if code == 429 or status == 'RESOURCE_EXHAUSTED':
            return (_("Google's quota for this key or project is used up for now (HTTP 429)."),
                    [_("Wait a minute and test again; free-tier limits are per minute and per day."),
                     _("For more, enable billing or ask for a higher quota in the Google Cloud console > Quotas.")],
                    False)
        if code == 400 and 'thinking' in lowered:
            return (_("%(model)s doesn't support the thinking setting the AI features use.") % {'model': model},
                    [_("Choose a Gemini 3 model, e.g. the default.")], False)
        if code == 400 and ('json' in lowered or 'schema' in lowered or 'mime' in lowered):
            return (_("%(model)s doesn't support the JSON answers the AI features need.") % {'model': model},
                    [_("Choose another model, e.g. the default.")], False)
        if code == 400 and 'dimensionality' in lowered:
            return (_("%(model)s can't make vectors of %(size)d numbers.") % {
                'model': model, 'size': client.EMBEDDING_DIMENSIONS},
                    [_("Choose gemini-embedding-2 or another model that supports output_dimensionality.")], False)
        if code == 400 and vertex and 'location' in lowered:
            return (_("Vertex AI doesn't know the location %(location)s.") % {'location': target[2]},
                    [_("Use global, or a region such as europe-west1 or us-central1.")], True)
        if code is not None and code >= 500:
            return (_("Google's servers had a problem (HTTP %(code)s); it is usually temporary.") % {'code': code},
                    [_("Test again in a few minutes.")], False)
        return (_("Google refused the request (HTTP %(code)s %(status)s).") % {'code': code, 'status': status},
                [_("Google's message below says why.")], code in (400, 401, 403))

    try:
        from google.auth import exceptions as auth_errors
    except ImportError:
        auth_errors = None
    if auth_errors is not None and isinstance(error, auth_errors.DefaultCredentialsError):
        return (_("The server has no Google Cloud credentials (Application Default Credentials)."),
                _no_credentials_hints(), True)
    if auth_errors is not None and isinstance(error, auth_errors.RefreshError):
        return (_("The Google Cloud credentials could not be renewed."),
                [_("They may have been revoked or expired: run gcloud auth application-default login again, or "
                   "create a new service account key."),
                 _("The server must also reach oauth2.googleapis.com over HTTPS.")], True)

    name = type(error).__name__
    if 'Timeout' in name or isinstance(error, (socket.timeout, TimeoutError)):
        return (_("%(host)s didn't answer within %(seconds)d seconds.") % {'host': host(target), 'seconds': TIMEOUT},
                [_("Test again; if it keeps happening, check the server's network and any proxy.")], False)
    if 'Connect' in name or isinstance(error, (ConnectionError, socket.gaierror, OSError)):
        return (_("The server can't reach %(host)s.") % {'host': host(target)},
                [_("Allow outgoing HTTPS (port 443) from this server to %(host)s in its firewall.") % {
                    'host': host(target)},
                 _("Behind a proxy, set HTTPS_PROXY for the site's process and restart it."),
                 _("Check that the server can resolve the name (DNS).")], True)
    return (_("The request failed: %(error)s") % {'error': redact(error, found)[:300]},
            [_("Google's message below may say why.")], False)


def available_models(api, kind='text', limit=8):
    """A few model IDs this connection offers (for "not found"); [] if unknown."""
    if api is None:
        return []
    try:
        names = []
        for item in api.models.list(config={'page_size': 200}):
            name = str(getattr(item, 'name', '') or '').rsplit('/', 1)[-1]
            if not name.startswith('gemini'):
                continue
            if ('embedding' in name) == (kind == 'embedding'):
                names.append(name)
    except Exception:
        return []
    return sorted(set(names))[:limit]


# ---- the status panel ----------------------------------------------------------

def knowledge_status():
    """Chunks per source, when the index was last built and with which model."""
    from forum.models import KnowledgeChunk
    from forum.utils import cron
    from .knowledge import index_model
    counts = {source: KnowledgeChunk.objects.filter(source=source).count() for source in ('forum', 'web')}
    runs = cron.last_runs()
    when = lambda name: datetime.fromtimestamp(runs[name]['success']) if runs.get(name, {}).get('success') else None
    model = str(AI_EMBEDDING_MODEL).strip()
    stale = sorted({index_model(source) for source in counts if counts[source]} - {None, model})
    return {'forum': counts['forum'], 'web': counts['web'], 'built': when('build_knowledge_index'),
            'suggested': when('suggest_answers'), 'stale_models': stale, 'model': model}


def status_panel(request):
    """HTML after the connection settings: the knowledge index and the test
    button (the section's status line says which connection is in use)."""
    return render_to_string('modules/ai/status.html', {'knowledge': knowledge_status()}, request=request)
