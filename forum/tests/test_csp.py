"""Content-Security-Policy with a per-response nonce: inline scripts run only
when they carry the response's nonce, and templates use no inline event
handlers or javascript: URLs (the policy blocks those)."""
import glob
import os
import re

from django.conf import settings as djsettings
from django.test import override_settings
from django.urls import reverse

from forum import settings
from forum.models import Question

from .base import OSQATestCase
from .test_hardening import SettingMixin

ROOT = djsettings.SITE_SRC_ROOT

SCRIPT_TAG = re.compile(r'<script\b([^>]*)>', re.IGNORECASE)
# Data blocks: the browser doesn't run them, so the policy doesn't apply.
DATA_TYPES = ('text/html', 'application/ld+json', 'application/json')
# Attributes the policy blocks: inline event handlers and javascript: URLs.
INLINE_HANDLER = re.compile(r'''<[a-zA-Z][^>]*?\son[a-z]+\s*=\s*["'{]|\b(?:href|src|action)\s*=\s*["']\s*javascript:''',
                            re.IGNORECASE | re.DOTALL)


def directives(policy):
    return {part.split()[0]: part.split()[1:] for part in policy.split('; ')}


def nonce_of(response):
    return re.search(r"'nonce-([^']+)'", response['Content-Security-Policy']).group(1)


def inline_scripts(html):
    """The attributes of every inline (no src) script the browser would run."""
    found = []
    for match in SCRIPT_TAG.finditer(html):
        attrs = match.group(1)
        type_ = re.search(r'''\btype\s*=\s*["']([^"']+)''', attrs)
        if re.search(r'\bsrc\s*=', attrs) or (type_ and type_.group(1).lower() in DATA_TYPES):
            continue
        found.append(attrs)
    return found


class NoncePolicyTest(SettingMixin, OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True, reputation=5000)

    def assertScriptsHaveNonce(self, response):
        """Every inline script on the page has the nonce the header names."""
        self.assertEqual(response.status_code, 200, response)
        nonce = nonce_of(response)
        html = response.content.decode('utf-8')
        scripts = inline_scripts(html)
        for attrs in scripts:
            self.assertIn('nonce="%s"' % nonce, attrs, '%s: inline script without the nonce' % response.request['PATH_INFO'])
        self.assertIsNone(INLINE_HANDLER.search(html),
                          '%s: inline event handler or javascript: URL' % response.request['PATH_INFO'])
        return scripts

    def test_policy(self):
        response = self.client.get('/')
        policy = directives(response['Content-Security-Policy'])
        script_src = policy['script-src']
        self.assertEqual(script_src[:2], ["'self'", "'nonce-%s'" % nonce_of(response)])
        self.assertNotIn("'unsafe-inline'", script_src)
        self.assertNotIn("'unsafe-eval'", script_src)
        self.assertNotIn("'strict-dynamic'", script_src)
        self.assertGreaterEqual(len(nonce_of(response)), 22)  # 18 random bytes
        # reCAPTCHA: api.js from www.google.com loads its other scripts from
        # www.gstatic.com and shows its challenge in a frame from www.google.com.
        for source in ('https://www.google.com', 'https://www.gstatic.com'):
            self.assertIn(source, script_src)
            self.assertIn(source, policy['frame-src'])
        self.assertIn("'unsafe-inline'", policy['style-src'])  # style="" attributes, for now
        self.assertEqual(policy['object-src'], ["'none'"])
        self.assertEqual(policy['base-uri'], ["'self'"])
        self.assertEqual(policy['form-action'], ["'self'"])
        self.assertEqual(policy['frame-ancestors'], ["'self'"])
        self.assertNotIn('require-trusted-types-for', policy)

        self.set(settings.CSP_EXTRA_SOURCES, 'https://plausible.io')
        policy = directives(self.client.get('/')['Content-Security-Policy'])
        self.assertEqual(policy['script-src'][-1], 'https://plausible.io')
        self.assertEqual(policy['form-action'], ["'self'", 'https://plausible.io'])

    def test_nonce_changes_on_every_response(self):
        nonces = {nonce_of(self.client.get('/')) for _ in range(5)}
        self.assertEqual(len(nonces), 5)

    def test_inline_scripts_carry_the_nonce(self):
        response = self.client.get('/')
        scripts = self.assertScriptsHaveNonce(response)
        self.assertTrue(scripts)  # base_content.html's messages
        self.assertIn('nonce="%s"' % nonce_of(response), response.content.decode())

    def test_pages_have_no_script_without_nonce(self):
        question = Question(author=self.admin, title='A question about nonces', body='<p>Body text</p>', tagnames='csp')
        question.save()
        self.set(settings.GOOGLE_ANALYTICS_KEY, 'G-TEST1234')  # the consent banner's inline script
        anonymous = ['/', question.get_absolute_url(), '/users/', '/tags/', '/account/signin/',
                     '/account/local/register/', '/does-not-exist/']
        for url in anonymous:
            response = self.client.get(url)
            if url == '/does-not-exist/':
                self.assertEqual(response.status_code, 404)
                response.status_code = 200
            self.assertScriptsHaveNonce(response)

        self.login(self.admin)
        for url in [question.get_absolute_url(), '/questions/ask/', self.admin.get_profile_url(),
                    '/admin/', '/admin/statistics/', '/admin/settings/email/', '/admin/settings/basic/',
                    '/admin/static_pages/', '/admin/support/', '/admin/flagged_posts/',
                    '/admin/tools/nodeman/', '/admin/maintenance/']:
            self.assertScriptsHaveNonce(self.client.get(url))

    def test_django_admin_needs_no_inline_scripts(self):
        """Django's model admin (/nimda/) runs only script files, so it gets
        the same policy as the rest of the site."""
        self.login(self.admin)
        for url in ('/nimda/', '/nimda/auth/user/', '/nimda/auth/user/%d/change/' % self.admin.id):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertEqual(inline_scripts(response.content.decode()), [], url)
            self.assertIn("'nonce-", response['Content-Security-Policy'])

    def test_prompt_dialogs_bring_no_scripts(self):
        """Dialog contents loaded with AJAX come from another response, with
        another nonce, so their behaviour lives in osqa.main.js."""
        question = Question(author=self.admin, title='A question to report', body='<p>Body text</p>', tagnames='csp')
        question.save()
        from forum.models import Answer
        other = self.create_user('other', reputation=5000)
        answer = Answer(author=other, parent=question, body='<p>An answer body</p>')
        answer.save()
        self.login(self.admin)
        for url in (reverse('close', kwargs={'id': question.id}), reverse('flag_post', kwargs={'id': question.id}),
                    reverse('answer_permanent_link', kwargs={'id': answer.id}),
                    reverse('award_points', kwargs={'user_id': other.id, 'answer_id': answer.id})):
            response = self.client.get(url, **self.AJAX)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotIn('<script', response.content.decode(), url)

    def test_custom_head_scripts_get_the_nonce(self):
        self.set(settings.USE_CUSTOM_HEAD, True)
        self.set(settings.CUSTOM_HEAD, '<script>window.analytics = 1;</script>'
                                       '<script async src="https://plausible.io/js/script.js"></script>')
        response = self.client.get('/')
        nonce = nonce_of(response)
        self.assertContains(response, '<script nonce="%s">window.analytics = 1;</script>' % nonce)
        self.assertScriptsHaveNonce(response)

    def test_not_modified_keeps_the_stored_policy(self):
        """A 304 carries no policy: the browser keeps the one stored with its
        copy, whose nonce matches the copy's scripts."""
        question = Question(author=self.admin, title='A cached question', body='<p>Body text</p>', tagnames='csp')
        question.save()
        self.client.get(question.get_absolute_url())  # the first view is counted and gets no ETag
        first = self.client.get(question.get_absolute_url())
        self.assertTrue(first.has_header('ETag'))
        self.assertTrue(first.has_header('Content-Security-Policy'))
        again = self.client.get(question.get_absolute_url(), HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(again.status_code, 304)
        self.assertFalse(again.has_header('Content-Security-Policy'))

    def test_configured_policy_gets_the_nonce(self):
        with override_settings(CONTENT_SECURITY_POLICY="script-src 'self' 'nonce-{nonce}'"):
            response = self.client.get('/')
        self.assertEqual(response['Content-Security-Policy'], "script-src 'self' 'nonce-%s'" % nonce_of(response))
        self.assertScriptsHaveNonce(response)


class TemplatesTest(OSQATestCase):
    """Template files and the HTML that Python and JavaScript code builds."""

    def files(self, *patterns):
        for pattern in patterns:
            for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
                unix_path = path.replace(os.sep, '/')  # glob returns backslashes on Windows
                if '/vendor/' not in unix_path and '/tests/' not in unix_path:
                    yield path

    def test_no_inline_event_handlers(self):
        offenders = []
        for path in self.files('forum/skins/**/*.html', 'forum_modules/**/templates/**/*.html',
                               'forum/**/*.py', 'forum_modules/**/*.py',
                               'forum/skins/**/media/js/**/*.js'):
            with open(path, encoding='utf-8', errors='replace') as source:
                text = source.read()
            for match in INLINE_HANDLER.finditer(text):  # tags may span lines
                number = text.count('\n', 0, match.start()) + 1
                offenders.append('%s:%d: %s' % (os.path.relpath(path, ROOT), number, match.group(0)[:120]))
        self.assertEqual(offenders, [], 'inline event handlers or javascript: URLs (blocked by the CSP); '
                                        'use osqa.behaviors.js data attributes or a JavaScript file')

    def test_inline_scripts_in_templates_have_the_nonce(self):
        offenders = []
        for path in self.files('forum/skins/**/*.html', 'forum_modules/**/templates/**/*.html'):
            with open(path, encoding='utf-8') as source:
                html = source.read()
            for attrs in inline_scripts(html):
                if 'nonce="{{ csp_nonce }}"' not in attrs:
                    offenders.append('%s: <script%s>' % (os.path.relpath(path, ROOT), attrs))
        self.assertEqual(offenders, [])
