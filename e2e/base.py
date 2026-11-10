"""Base class for the browser tests.

Each test runs against Django's live test server (a fresh test database, the
real middleware, templates and JavaScript) and drives Chromium with
Playwright. Every page a test opens is watched: a test fails when a page
answers with a server error, throws a JavaScript error, logs a console error
(including Content-Security-Policy blocks), or, on the phone viewport,
scrolls sideways.

Environment variables:
    E2E_HEADED=1             show the browser window
    E2E_SLOWMO=250           pause (ms) between browser actions
    E2E_CHROMIUM_PATH=...    use this Chromium instead of Playwright's own
    E2E_ARTIFACTS=dir        where screenshots of failed tests go (tmp/e2e)
    E2E_CSS_COVERAGE=1       record which style sheet rules the pages use (e2e/css_coverage.py)
"""
import datetime
import os
import sys

# Playwright's sync API runs an event loop in this thread; Django's ORM is
# only used synchronously here.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from unittest import mock

from django.conf import settings as djsettings
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import LiveServerTestCase

from forum import settings
from forum.models import Answer, Comment, Question, User
from forum.models.action import Action

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ARTIFACTS = os.environ.get('E2E_ARTIFACTS') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                            'tmp', 'e2e')
DEVICES = {
    'desktop': dict(viewport={'width': 1280, 'height': 900}),
    'mobile': dict(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2),
}
PASSWORD = 'e2e-Secret-pass-1'

# The outermost elements that stick out to the right of the screen.
WIDER_THAN_SCREEN = '''() => {
    const width = document.documentElement.clientWidth, found = [];
    for (const el of document.querySelectorAll('body *')) {
        const box = el.getBoundingClientRect();
        if (box.right <= width + 1 || box.width === 0 || found.some(f => f.contains(el))) continue;
        // Inside a container that scrolls by itself (e.g. a tab bar): fine.
        let parent = el.parentElement, scrolls = false;
        for (; parent && parent !== document.body; parent = parent.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(parent).overflowX)) { scrolls = true; break; }
        }
        if (!scrolls) found.push(el);
    }
    // Text that overflows its own element (e.g. white-space: nowrap) leaves the element's box alone.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), range = document.createRange();
    while (!found.length && walker.nextNode()) {
        range.selectNodeContents(walker.currentNode);
        const box = range.getBoundingClientRect(), el = walker.currentNode.parentElement;
        if (box.right <= width + 1 || box.width === 0 || found.includes(el)) continue;
        let parent = el, scrolls = false;
        for (; parent && parent !== document.body; parent = parent.parentElement) {
            if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowX)) { scrolls = true; break; }
        }
        if (!scrolls) found.push(el);
    }
    return found.slice(0, 5).map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : '') +
        ' (' + Math.round(el.getBoundingClientRect().width) + 'px)');
}'''



# The last keys, clicks, focus moves and dialog calls of each page, printed
# with the page's state when a test fails (CI keeps only the log).
TRACE = """(() => {
    const trace = window.__e2eTrace = [];
    const name = (el) => !el || !el.tagName ? String(el) :
        el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (el.getAttribute && el.getAttribute('data-command') ? '[' + el.getAttribute('data-command') + ']' : '');
    const add = (text) => { trace.push(Math.round(performance.now()) + 'ms ' + text); if (trace.length > 60) trace.shift(); };
    ['keydown', 'click', 'focusin', 'close', 'cancel'].forEach((type) => document.addEventListener(type, (e) =>
        add(type + ' ' + (e.key ? e.key + (e.ctrlKey ? '+ctrl' : '') + ' ' : '') + name(e.target) +
            (e.defaultPrevented ? ' (prevented)' : '')), true));
    ['showModal', 'show', 'close'].forEach((method) => {
        const real = HTMLDialogElement.prototype[method];
        HTMLDialogElement.prototype[method] = function () {
            add('dialog.' + method + ' ' + name(this) + (this.open ? ' (was open)' : ''));
            try { return real.apply(this, arguments); }
            catch (err) { add('  threw ' + err); throw err; }
        };
    });
})();"""

TRACE_DUMP = """() => (window.__e2eTrace || []).concat([
    'now: focus ' + (document.activeElement ? document.activeElement.outerHTML.slice(0, 100) : '-'),
    'open dialogs: ' + [...document.querySelectorAll('dialog[open]')].map(d => d.id + (d.matches(':modal') ? ' (modal)' : '')).join(', ')])"""

class _ServeEverythingWithDjango:
    """The live server would serve STATIC_URL itself from STATIC_ROOT; OSQA
    serves those files through its own views, as in production."""
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        return self.application(environ, start_response)


class E2ETestCase(LiveServerTestCase):
    """Live server + browser. Use self.open() to get a page as a given user."""

    static_handler = _ServeEverythingWithDjango

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise RuntimeError('Playwright is not installed: pip install -r requirements-dev.txt && '
                               'python -m playwright install chromium')
        super().setUpClass()
        cls._playwright = sync_playwright().start()
        options = dict(headless=os.environ.get('E2E_HEADED') != '1', slow_mo=int(os.environ.get('E2E_SLOWMO', 0)))
        if os.environ.get('E2E_CHROMIUM_PATH'):
            options['executable_path'] = os.environ['E2E_CHROMIUM_PATH']
        cls.browser = cls._playwright.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        cache.clear()
        from forum.settings.base import Setting
        Setting.forget_values()
        # Action hooks (notifications, emails, badges) run in a thread in
        # production; inline here so tests can check their results.
        trigger_hooks = Action.trigger_hooks
        self._patch(mock.patch.object(Action, 'trigger_hooks',
                                      lambda action, threaded, new=True: trigger_hooks(action, False, new)))
        self.sent_mail = []
        self._patch(mock.patch('forum.templatetags.email_tags.create_and_send_mail_messages',
                               lambda messages, **kwargs: self.sent_mail.extend(messages)))
        # People fill in the sign-up form faster in a test than the bot trap allows.
        self.set_setting(settings.SIGNUP_MIN_SECONDS, 0)
        self._contexts = []
        self._pages = []
        self._requested = set()

    def tearDown(self):
        failed = self._failed()
        for index, page in enumerate(self._pages):
            if failed and not page.is_closed():
                os.makedirs(ARTIFACTS, exist_ok=True)
                name = '%s-%d.png' % (self.id().split('.', 1)[-1], index)
                try:
                    page.screenshot(path=os.path.join(ARTIFACTS, name), full_page=True)
                except Exception:
                    pass
                # What the page logged often explains a timeout (CI only keeps the log).
                try:
                    trace = page.evaluate(TRACE_DUMP)
                except Exception:
                    trace = []
                if page.problems or trace:
                    sys.stderr.write('\n%s, page %d (%s):\n  %s\n' % (
                        self.id(), index, page.url, '\n  '.join(page.problems + trace)))
        leftovers = [] if failed else [p for page in self._pages for p in page.problems]
        if os.environ.get('E2E_CSS_COVERAGE'):
            from . import css_coverage
            css_coverage.flush(self._pages)
        for context in self._contexts:
            context.close()
        if os.environ.get('E2E_RECORD') and self._requested:
            with open(os.environ['E2E_RECORD'], 'a') as record:
                record.write(''.join(line + '\n' for line in sorted(self._requested)))
        cache.clear()
        super().tearDown()
        self.assertEqual(leftovers, [], 'page problems not checked by the test')

    def _failed(self):
        result = getattr(getattr(self, '_outcome', None), 'result', None)
        return bool(result) and any(test is self for test, _ in result.errors + result.failures)

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_setting(self, setting, value):
        setting.set_value(value)
        self.addCleanup(setattr, setting, '_temp', None)

    # -- data -------------------------------------------------------------

    def create_user(self, username, reputation=1, password=PASSWORD, **fields):
        fields.setdefault('email_isvalid', True)
        user = User(username=username, email='%s@example.com' % username, reputation=reputation, **fields)
        user.set_password(password)
        user.save()
        return user

    # Posts go through the forum's actions, so subscriptions, notifications,
    # emails and badges happen as they would for a real post.

    def _as_request(self, user):
        """Actions show messages to the current request's user; give them one."""
        import forum
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        request = RequestFactory().post('/')
        request.user = user
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        forum.REQUEST_HOLDER.request = request
        self.addCleanup(setattr, forum.REQUEST_HOLDER, 'request', None)

    def create_question(self, author, title, tags='collect', body=None, days_ago=0):
        from forum.actions import AskAction
        self._as_request(author)
        action = AskAction(user=author, ip='127.0.0.1').save(data=dict(
            title=title, tags=tags,
            text=body or 'Details of "%s", long enough to be a valid question body.' % title))
        if days_ago:
            Question.objects.filter(id=action.node.id).update(
                added_at=datetime.datetime.now() - datetime.timedelta(days=days_ago))
        return Question.objects.get(id=action.node.id)

    def create_answer(self, author, question, body='An answer with enough text to be posted.'):
        from forum.actions import AnswerAction
        self._as_request(author)
        return Answer.objects.get(id=AnswerAction(user=author, ip='127.0.0.1').save(
            data=dict(question=question, text=body)).node.id)

    def create_comment(self, author, post, body='A comment that is long enough.'):
        from forum.actions import CommentAction
        self._as_request(author)
        return Comment.objects.get(id=CommentAction(user=author, ip='127.0.0.1').save(
            data=dict(text=body, parent=post)).node.id)

    # -- browser ----------------------------------------------------------

    def url(self, path):
        return self.live_server_url + path

    def open(self, user=None, device='desktop', dark=False, locale='en-US', recent=True, **options):
        """A new browser page, signed in as `user` (or anonymous); like a real
        sign-in it counts as recent for "Confirm it's you" unless `recent` is
        False. Other keyword arguments are browser context options (viewport,
        reduced_motion...) that override the device's."""
        context = self.browser.new_context(**dict(DEVICES[device], color_scheme='dark' if dark else 'light',
                                                  locale=locale, **options))
        self._contexts.append(context)
        if user is not None:
            session = SessionStore()
            session['_auth_user_id'] = str(user.pk)
            session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
            session['_auth_user_hash'] = user.get_session_auth_hash()
            session['osqa_epoch'] = int(user.session_epoch or 0)  # as accounts.signed_in() does
            if recent:
                session['osqa_auth_time'] = datetime.datetime.now().isoformat()
            session.create()
            context.add_cookies([{'name': djsettings.SESSION_COOKIE_NAME, 'value': session.session_key,
                                  'url': self.live_server_url}])
        context.add_init_script(TRACE)
        page = context.new_page()
        if os.environ.get('E2E_CSS_COVERAGE'):
            from . import css_coverage
            css_coverage.track(page, self.live_server_url)
        page.set_default_timeout(int(os.environ.get('E2E_TIMEOUT', 10000)))
        page.problems = []
        page.device = device
        page.on('pageerror', lambda error: page.problems.append('JavaScript error: %s\n%s' % (
            error, '\n'.join((error.stack or '').splitlines()[1:4]))))
        page.on('console', lambda message: self._console(page, message))
        page.on('request', lambda request: self._record(request))
        page.on('response', lambda response: page.problems.append('HTTP %d for %s' % (response.status, response.url))
                if response.status >= 500 and response.url.startswith(self.live_server_url) else None)
        # confirm() dialogs ("You will lose your changes…") are accepted.
        page.on('dialog', lambda dialog: dialog.accept())
        self._pages.append(page)
        return page

    def _record(self, request):
        """Remembers the forum URLs the browser asked for (for e2e/coverage.py)."""
        if request.url.startswith(self.live_server_url) and request.resource_type in ('document', 'xhr', 'fetch'):
            path = request.url[len(self.live_server_url):].split('?')[0].split('#')[0]
            self._requested.add('%s %s' % (request.method, path))

    def _console(self, page, message):
        if message.type != 'error':
            return
        text = message.text
        source = (message.location or {}).get('url', '')
        # Images and scripts from other sites (Gravatar, Google) may be unreachable
        # where the tests run; only this site's resources must load.
        if text.startswith('Failed to load resource') and source and not source.startswith(self.live_server_url):
            return
        # The CSS coverage hooks inject scripts into every frame; the email
        # preview's sandboxed frame (no allow-scripts) refuses them.
        if os.environ.get('E2E_CSS_COVERAGE') and text.startswith('Blocked script execution') and 'sandboxed' in text:
            return
        page.problems.append('console error: %s (%s)' % (text, source))

    def visit(self, page, path, status=200):
        """Opens `path` and checks the page is healthy."""
        response = page.goto(self.url(path))
        self.assertEqual(response.status, status, 'GET %s' % path)
        self.check_page(page, path)
        return response

    def check_page(self, page, where=''):
        """No server/JavaScript/console errors so far, and no sideways scrolling on phones."""
        page.wait_for_load_state('load')
        if page.device == 'mobile':
            overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
            if overflow > 1:
                self.fail('%s scrolls sideways on a phone by %dpx; too wide: %s' % (
                    where or page.url, overflow, ', '.join(page.evaluate(WIDER_THAN_SCREEN))))
        problems, page.problems[:] = list(page.problems), []
        self.assertEqual(problems, [], 'problems on %s' % (where or page.url))

    def wait_for_ajax(self, page):
        """Waits until the jQuery requests started by a click are answered."""
        page.wait_for_function("() => (!window.jQuery || jQuery.active === 0) && !document.getElementById('command-loader')")

    def settle(self, page):
        """After an AJAX command: waits for its answer and for the page reload
        some commands (accept, close, delete, permissions) trigger."""
        self.wait_for_ajax(page)
        try:
            page.wait_for_event('load', timeout=1500)
        except Exception:
            pass  # no reload
        page.wait_for_load_state('load')
        self.wait_for_ajax(page)

    def click_command(self, page, selector):
        """Clicks an AJAX command link (vote, accept, favourite…) and checks the page."""
        page.click(selector)
        self.settle(page)
        self.check_page(page)

    def confirm_dialog(self, page, fill=None):
        """Fills and confirms the dialog of a command that asks first (close, report, delete…)."""
        page.wait_for_selector('.dialog .dialog-yes')
        for selector, value in (fill or {}).items():
            page.fill('.dialog ' + selector, value)
        page.click('.dialog .dialog-yes')
        self.settle(page)
        self.check_page(page)

    def mail_to(self, user):
        return [m for m in self.sent_mail if m[0] == user]
