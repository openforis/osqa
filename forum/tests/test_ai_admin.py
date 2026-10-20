"""Admin > AI assistance: the reorganised settings, the "In use now" panel and
"Test connection" (forum_modules/ai/diagnostics.py), which tries the values
in the form without saving them and explains each failure."""
from types import SimpleNamespace
from unittest import mock

from django.urls import reverse
from google.genai import errors, types

from .test_ai import AITestCase

KEY = 'AIzaTestKey0123456789abcdef'


def api_error(cls, code, message, status, reason=None, metadata=None):
    details = [{'@type': 'type.googleapis.com/google.rpc.ErrorInfo', 'reason': reason,
                'metadata': metadata or {}}] if reason else []
    return cls(code, {'error': {'code': code, 'message': message, 'status': status, 'details': details}})


class FakeApi:
    """Stands in for google.genai.Client in the test: one answer per request kind."""

    def __init__(self, text_error=None, embed_error=None, text='{"ok": true}', dimensions=768, models=()):
        self.text_error, self.embed_error, self.text, self.dimensions = text_error, embed_error, text, dimensions
        self.listed = [SimpleNamespace(name='models/%s' % m) for m in models]
        self.requests = []
        self.models = SimpleNamespace(generate_content=self.generate_content, embed_content=self.embed_content,
                                      list=self.list)

    def generate_content(self, model, contents, config):
        self.requests.append(('text', model, config))
        if self.text_error:
            raise self.text_error
        return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)], text=self.text)

    def embed_content(self, model, contents, config):
        self.requests.append(('embedding', model, config))
        if self.embed_error:
            raise self.embed_error
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * self.dimensions)])

    def list(self, config=None):
        return iter(self.listed)


class AIConnectionTestCase(AITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)
        self.login(self.admin)
        self.targets = []

    def api(self, **kwargs):
        fake = FakeApi(**kwargs)

        def build(target, timeout=None):
            self.targets.append(target)
            return fake
        patcher = mock.patch('forum_modules.ai.client.build_client', side_effect=build)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def run_test(self, **values):
        data = dict({'AI_PROVIDER': 'auto', 'GEMINI_API_KEY': KEY, 'AI_VERTEX_PROJECT': '',
                     'AI_VERTEX_LOCATION': 'global', 'AI_MODEL': 'gemini-3.8-flash',
                     'AI_EMBEDDING_MODEL': 'gemini-embedding-2'}, **values)
        response = self.client.post(reverse('ai_test_connection'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def vertex_credentials(self, account='osqa@my-project.iam.gserviceaccount.com'):
        credentials = SimpleNamespace(service_account_email=account)
        patcher = mock.patch('google.auth.default', return_value=(credentials, 'my-project'))
        patcher.start()
        self.addCleanup(patcher.stop)


class SettingsPageTest(AIConnectionTestCase):
    def test_connection_settings_status_and_button(self):
        self.set(self.ai.GEMINI_API_KEY, KEY)
        html = self.client.get(reverse('admin_set', args=['ai'])).content.decode('utf-8')
        for text in ('Connection to Google Gemini', 'Duplicates and moderation', 'name="AI_PROVIDER"',
                     'name="GEMINI_API_KEY"', 'Gemini API with the key AIza…cdef (from this page).',
                     'data-ai-test="/admin/ai/test/"', 'Knowledge index: 0 forum and 0 documentation passages.'):
            self.assertIn(text, html)
        # The panel follows the connection settings, before the features.
        self.assertLess(html.index('name="AI_EMBEDDING_MODEL"'), html.index('id="ai-test-button"'))
        self.assertLess(html.index('id="ai-test-button"'), html.index('id="section-moderation"'))
        # The key moved here from External Keys.
        external = self.client.get(reverse('admin_set', args=['extkeys'])).content.decode('utf-8')
        self.assertNotIn('name="GEMINI_API_KEY"', external)

    def test_not_configured(self):
        self.set(self.ai.GEMINI_API_KEY, '')
        html = self.client.get(reverse('admin_set', args=['ai'])).content.decode('utf-8')
        self.assertIn('admin-status-off', html)
        self.assertIn('Needs the connection above.', html)
        self.set(self.ai.GEMINI_API_KEY, 'not-a-gemini-key')
        html = self.client.get(reverse('admin_set', args=['ai'])).content.decode('utf-8')
        self.assertIn('Gemini API keys start with AIza', html)

    def test_numbers_are_checked(self):
        response = self.client.get(reverse('admin_set', args=['ai']))
        form = response.context['form']
        data = {name: form.initial.get(name) for name in form.fields}
        data = {name: ('on' if value is True else value) for name, value in data.items() if value not in (False, None)}
        data.update(AI_MODERATION_MIN_CONFIDENCE='1.5', submit='Save')
        response = self.client.post(reverse('admin_set', args=['ai']), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('AI_MODERATION_MIN_CONFIDENCE', response.context['form'].errors)
        self.assertEqual(float(self.ai.AI_MODERATION_MIN_CONFIDENCE), 0.7)

    def test_provider_choice(self):
        from forum_modules.ai import client
        self.set(self.ai.AI_VERTEX_PROJECT, 'my-project')
        self.assertEqual(client.connection()[0], 'vertex')
        self.set(self.ai.AI_PROVIDER, 'gemini')
        self.assertEqual(client.connection(), ('gemini', 'test-gemini-key'))
        self.set(self.ai.AI_PROVIDER, 'vertex')
        self.set(self.ai.AI_VERTEX_PROJECT, '')
        self.assertIsNone(client.connection())


class ConnectionTestTest(AIConnectionTestCase):
    def test_only_superusers(self):
        moderator = self.create_user('moderator', is_staff=True)
        self.login(moderator)
        response = self.client.post(reverse('ai_test_connection'), {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertNotEqual(response.status_code, 200)
        self.client.logout()
        response = self.client.post(reverse('ai_test_connection'), {})
        self.assertNotEqual(response.status_code, 200)

    def test_get_goes_back_to_the_settings(self):
        response = self.client.get(reverse('ai_test_connection'))
        self.assertRedirects(response, reverse('admin_set', args=['ai']))

    def test_working_connection_with_unsaved_values(self):
        fake = self.api()
        html = self.run_test(AI_MODEL='gemini-3.5-flash-lite')
        self.assertIn('The connection works', html)
        self.assertEqual(html.count('>OK<'), 3)  # connection, text model, embedding model
        self.assertIn('gemini-3.5-flash-lite answered in', html)
        self.assertEqual(self.targets, [('gemini', KEY)])
        # The same request settings as the features (JSON schema, thinking level).
        kind, model, config = fake.requests[0]
        self.assertEqual((kind, model), ('text', 'gemini-3.5-flash-lite'))
        self.assertEqual(config.response_mime_type, 'application/json')
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.LOW)
        self.assertEqual(fake.requests[1][2].output_dimensionality, 768)
        # Nothing was saved.
        self.assertEqual(str(self.ai.GEMINI_API_KEY), 'test-gemini-key')
        self.assertEqual(str(self.ai.AI_MODEL), 'gemini-3.8-flash')

    def test_without_javascript_the_result_is_a_page(self):
        self.api()
        response = self.client.post(reverse('ai_test_connection'), {'GEMINI_API_KEY': KEY})
        self.assertContains(response, 'The connection works')
        self.assertContains(response, 'Back to AI assistance')

    def test_nothing_set(self):
        self.set(self.ai.GEMINI_API_KEY, '')
        html = self.run_test(GEMINI_API_KEY='')
        self.assertIn('No API key or Vertex AI project is set.', html)
        self.assertIn('aistudio.google.com/apikey', html)

    def test_invalid_key_is_explained_and_never_shown(self):
        self.api(text_error=api_error(errors.ClientError, 400, 'API key not valid: %s' % KEY, 'INVALID_ARGUMENT',
                                      'API_KEY_INVALID'))
        html = self.run_test()
        self.assertIn('Google doesn&#x27;t accept this API key.', html)
        self.assertIn('Not tested: fix the problem above first.', html)
        self.assertIn('Error reported by Google', html)
        self.assertNotIn(KEY, html)
        self.assertIn('AIza…cdef', html)

    def test_key_restrictions(self):
        self.api(text_error=api_error(errors.ClientError, 403, 'Requests from referer <empty> are blocked.',
                                      'PERMISSION_DENIED', 'API_KEY_HTTP_REFERRER_BLOCKED'))
        self.assertIn('restrictions don&#x27;t allow this request', self.run_test())

    def test_unknown_model_lists_the_available_ones(self):
        self.api(text_error=api_error(errors.ClientError, 404, 'models/gemini-9 is not found', 'NOT_FOUND'),
                 models=('gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-embedding-2', 'imagen-4'))
        html = self.run_test(AI_MODEL='gemini-9')
        self.assertIn('The model gemini-9 was not found.', html)
        self.assertIn('gemini-3.5-flash-lite, gemini-3.8-flash', html)
        self.assertNotIn('imagen-4', html)
        # A missing model isn't a connection problem: the embedding model is still tried.
        self.assertIn('gemini-embedding-2 answered in', html)

    def test_quota(self):
        self.api(embed_error=api_error(errors.ClientError, 429, 'Quota exceeded', 'RESOURCE_EXHAUSTED'))
        html = self.run_test()
        self.assertIn('quota for this key or project is used up', html)
        self.assertIn('The test found a problem', html)

    def test_model_without_thinking_levels(self):
        self.api(text_error=api_error(errors.ClientError, 400, 'thinking_level is not supported by this model.',
                                      'INVALID_ARGUMENT'))
        self.assertIn('doesn&#x27;t support the thinking setting', self.run_test(AI_MODEL='gemini-1.5-flash'))

    def test_wrong_json_answer(self):
        self.api(text='{"something": "else"}')
        self.assertIn('not with the JSON it was asked for', self.run_test())

    def test_network_problem(self):
        self.api(text_error=OSError('Name or service not known'))
        html = self.run_test()
        self.assertIn('The server can&#x27;t reach generativelanguage.googleapis.com.', html)
        self.assertIn('HTTPS_PROXY', html)

    def test_server_error(self):
        self.api(text_error=api_error(errors.ServerError, 503, 'The model is overloaded.', 'UNAVAILABLE'))
        self.assertIn('usually temporary', self.run_test())

    def test_vertex_api_not_enabled(self):
        self.vertex_credentials()
        url = 'https://console.developers.google.com/apis/api/aiplatform.googleapis.com/overview?project=my-project'
        self.api(text_error=api_error(errors.ClientError, 403, 'Vertex AI API has not been used in project my-project',
                                      'PERMISSION_DENIED', 'SERVICE_DISABLED', {'activationUrl': url}))
        html = self.run_test(AI_VERTEX_PROJECT='my-project')
        self.assertIn('Vertex AI in project my-project (from this page), location global', html)
        self.assertIn('Signed in as the service account osqa@my-project.iam.gserviceaccount.com.', html)
        self.assertIn('A Vertex AI project is set, so the Gemini API key is not used.', html)
        self.assertIn('The Vertex AI API is not enabled', html)
        self.assertIn('href="%s"' % url.replace('&', '&amp;'), html)
        self.assertEqual(self.targets, [('vertex', 'my-project', 'global')])

    def test_vertex_permission(self):
        self.vertex_credentials()
        self.api(text_error=api_error(errors.ClientError, 403, 'Permission denied on resource project my-project.',
                                      'PERMISSION_DENIED'))
        html = self.run_test(AI_PROVIDER='vertex', AI_VERTEX_PROJECT='my-project')
        self.assertIn('roles/aiplatform.user', html)
        self.assertNotIn('Gemini API key is not used', html)

    def test_vertex_without_credentials(self):
        from google.auth import exceptions as auth_errors
        fake = self.api()
        with mock.patch('google.auth.default', side_effect=auth_errors.DefaultCredentialsError('none found')):
            html = self.run_test(AI_PROVIDER='vertex', AI_VERTEX_PROJECT='my-project')
        self.assertIn('The server has no Google Cloud credentials', html)
        self.assertIn('GOOGLE_APPLICATION_CREDENTIALS', html)
        self.assertEqual(fake.requests, [])

    def test_project_name_instead_of_id(self):
        self.vertex_credentials()
        self.api()
        html = self.run_test(AI_PROVIDER='vertex', AI_VERTEX_PROJECT='My Project')
        self.assertIn('doesn&#x27;t look like a project ID', html)

    def test_environment_values_are_named(self):
        self.set(self.ai.GEMINI_API_KEY, '')
        self.api()
        with mock.patch.dict('os.environ', {'GEMINI_API_KEY': KEY}):
            html = self.run_test(GEMINI_API_KEY='')
        self.assertIn('(from the GEMINI_API_KEY environment variable)', html)
