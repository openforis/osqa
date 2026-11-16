"""Visual regression tests: key pages in a fixed state, screenshotted on a
desktop in light mode and on a phone in dark mode (and on a desktop in dark
mode for the home, question and sign-in pages), compared with the baselines
in e2e/visual/baselines/ (see e2e/visual/__init__.py and e2e/README.md).

    E2E_UPDATE_BASELINES=1   rewrite the baselines from this run

A missing baseline skips that screenshot (with a message) instead of failing.

Determinism: the data is fixed and every date in the database is moved to a
fixed point in 2021, with "now" frozen for the relative dates (diff_date);
question views aren't counted; animations, transitions, the caret and jQuery
effects are off; Gravatar images are a local grey square and every other
outside request is refused; screenshots wait for fonts, network and
animations to settle and are clipped to a maximum height."""
import datetime
import types
from unittest import mock

from django.apps import apps
from django.core.cache import cache
from django.db import models

from forum.actions import AcceptAnswerAction, VoteUpAction

from . import visual
from .base import E2ETestCase
from .test_accessibility import FINISHED_ANIMATING
from .test_question_page import ANSWER_BODY, QUESTION_BODY

FROZEN_NOW = datetime.datetime(2024, 6, 14, 12, 0)
DATES_FROM = datetime.datetime(2021, 3, 1, 9, 0)

# Phones at device scale 1 keep the baselines small; layout is the same.
VARIANTS = {
    'desktop-light': dict(device='desktop', dark=False),
    'desktop-dark': dict(device='desktop', dark=True),
    'phone-dark': dict(device='mobile', dark=True, device_scale_factor=1),
}
DEFAULT_VARIANTS = ('desktop-light', 'phone-dark')
KEY_VARIANTS = ('desktop-light', 'desktop-dark', 'phone-dark')
MAX_HEIGHT = {'desktop': 1500, 'mobile': 2200}


class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz is None else FROZEN_NOW.replace(tzinfo=tz)


class VisualTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        frozen = types.ModuleType('datetime')
        frozen.__dict__.update(datetime.__dict__)
        frozen.datetime = FrozenDateTime
        self._patch(mock.patch('forum.templatetags.extra_tags.datetime', frozen))
        self._patch(mock.patch('forum.views.readers.update_question_view_times', lambda request, question: None))
        self.create_content()
        self.fix_dates()
        self._environment_checked = False

    def create_content(self):
        self.admin = self.create_user('admin', reputation=4200, is_staff=True, is_superuser=True)
        self.alice = self.create_user('alice', reputation=512, real_name='Alice Martin', website='https://example.org',
                                      location='Rome', about='Forest inventory with **Collect**.')
        self.bob = self.create_user('bob', reputation=1234)
        self.carol = self.create_user('carol', reputation=310)
        self.create_user('collector', reputation=20)
        # Tags made in a fixed order: a question's tags are a set, made in hash
        # order, and the sidebar lists the most recently made tags first.
        from forum.models import Tag
        for name in ('collect', 'export', 'r', 'sepal', 'sentinel', 'earthmap', 'raster', 'gps'):
            Tag.objects.create(name=name, created_by=self.admin)
        self.question = self.create_question(self.alice, 'How do I read Collect CSV dates as dates in R?',
                                             tags='collect export r', body=QUESTION_BODY)
        self.accepted = self.create_answer(self.bob, self.question, ANSWER_BODY)
        self.create_answer(self.carol, self.question, 'The `lubridate` package also works: `ymd(data$survey_date)`.')
        self.create_comment(self.carol, self.question, 'Which version of Collect do you use, @alice?')
        self.create_comment(self.alice, self.question, 'Collect 4.1 with R 4.3 on Windows.')
        self.create_comment(self.alice, self.accepted, 'Thanks @bob, colClasses did it.')
        self._as_request(self.carol)
        VoteUpAction(user=self.carol, node=self.accepted, ip='127.0.0.1').save()
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=self.accepted, ip='127.0.0.1').save()
        other = self.create_question(self.bob, 'Can SEPAL process Sentinel-2 time series?', tags='sepal sentinel')
        self.create_answer(self.alice, other, 'Yes: use the time series recipe and pick Sentinel-2 as the source.')
        self.create_question(self.carol, 'Exporting a Collect survey to Excel', tags='collect export')
        self.create_question(self.alice, 'Earth Map raster layers do not show up', tags='earthmap raster')
        self.create_question(self.bob, 'Collect survey with a GPS field', tags='collect gps')

    def fix_dates(self):
        """Moves every date in the database to a fixed time in 2021, in the
        order the rows were made (so lists keep their order)."""
        for model in list(apps.get_app_config('forum').get_models()) + list(apps.get_app_config('auth').get_models()):
            if model._meta.proxy:
                continue
            fields = [f.attname for f in model._meta.local_concrete_fields if isinstance(f, models.DateTimeField)]
            if not fields:
                continue
            # By rank, not by id: ids carry on from earlier tests.
            for rank, row in enumerate(model._base_manager.order_by('pk').values('pk', *fields), start=1):
                pk = row.pop('pk')
                values = {name: DATES_FROM + datetime.timedelta(hours=7 * rank)
                          for name, value in row.items() if value is not None}
                if values:
                    model._base_manager.filter(pk=pk).update(**values)
        cache.clear()

    # -- screenshots --------------------------------------------------------

    def open_frozen(self, user, variant):
        options = dict(VARIANTS[variant])
        page = self.open(user, **options)
        avatar = visual.placeholder_avatar()
        live = self.live_server_url

        def route(route):
            url = route.request.url
            if url.startswith(live):
                return route.continue_()
            if 'gravatar.com/' in url:
                return route.fulfill(status=200, content_type='image/png', body=avatar)
            return route.abort()
        page.context.route('**/*', route)
        page.context.add_init_script(visual.FREEZE_SCRIPT)
        return page

    def settle_for_screenshot(self, page):
        page.wait_for_load_state('networkidle')
        page.evaluate('document.fonts.ready.then(() => true)')
        page.wait_for_function(FINISHED_ANIMATING)
        page.evaluate('window.scrollTo(0, 0)')

    def check_environment(self, page):
        """Once per test: None, or why the baselines can't be compared here."""
        if self._environment_checked:
            return self._environment_problem
        self._environment_checked = True
        self._environment_problem = None
        env = visual.environment(self.browser, page)
        if visual.updating():
            visual.save_environment(env)
            return None
        recorded = visual.recorded_environment()
        if recorded is not None and recorded != env and not visual.strict():
            self._environment_problem = (
                'the baselines were made on another environment (%s; this one is %s): fonts and rendering '
                'differ. Regenerate them here with E2E_UPDATE_BASELINES=1, or compare anyway with '
                'E2E_VISUAL_STRICT=1.' % (recorded, env))
        return self._environment_problem

    def snapshot(self, name, page, mask=()):
        """Screenshots the page (from the top, at most MAX_HEIGHT high) and
        compares it with the baseline `name`."""
        self.settle_for_screenshot(page)
        self.check_page(page)
        width = page.viewport_size['width']
        height = min(page.evaluate('document.documentElement.scrollHeight'), MAX_HEIGHT[page.device])
        png = page.screenshot(full_page=True, clip={'x': 0, 'y': 0, 'width': width, 'height': height},
                              animations='disabled', caret='hide', scale='css',
                              mask=[page.locator(selector) for selector in mask], mask_color='#ff00ff')
        if visual.updating():
            visual.save_baseline(name, png)
            return
        if not visual.os.path.exists(visual.baseline_path(name)):
            self.skipTest('no baseline for %s (e2e/visual/baselines/%s.png): make it with E2E_UPDATE_BASELINES=1'
                          % (name, name))
        problem = visual.compare(name, png)
        if problem:
            self.fail(problem)

    def shoot(self, page_name, path, user=None, variants=DEFAULT_VARIANTS, prepare=None, mask=()):
        for variant in variants:
            name = '%s-%s' % (page_name, variant)
            with self.subTest(screenshot=name):
                page = self.open_frozen(user, variant)
                self.visit(page, path)
                problem = self.check_environment(page)
                if problem:
                    page.context.close()
                    self.skipTest(problem)
                if prepare:
                    prepare(page)
                self.snapshot(name, page, mask)
                page.context.close()

    # -- pages --------------------------------------------------------------

    def test_home(self):
        self.shoot('home', '/', variants=KEY_VARIANTS)

    def test_question_page(self):
        self.shoot('question', self.question.get_absolute_url(), user=self.carol, variants=KEY_VARIANTS)

    def test_ask_page(self):
        self.shoot('ask', '/questions/ask/', user=self.alice)

    def test_sign_in(self):
        self.shoot('signin', '/account/signin/', variants=KEY_VARIANTS)

    def test_sign_up_with_errors(self):
        def submit_bad_form(page):
            page.fill('#id_username', 'alice')  # taken
            page.fill('#id_email', 'not-an-address')
            page.fill('#id_password1', 'short')
            page.fill('#id_password2', 'short')
            with page.expect_navigation():
                page.click('#bnewaccount')
            page.wait_for_selector('#form-errors')
            page.evaluate('document.activeElement && document.activeElement.blur()')
        self.shoot('signup-errors', '/account/local/register/', prepare=submit_bad_form)

    def test_search_with_suggestions(self):
        def open_suggestions(page):
            self.search_field(page).fill('coll')
            page.wait_for_selector('#searchbox-listbox [role=option]')
            self.wait_for_ajax(page)
            page.locator('#keywords').press('ArrowDown')
        self.shoot('search-suggestions', '/search/?q=export', prepare=open_suggestions)

    def test_user_profile(self):
        self.shoot('profile', self.alice.get_profile_url())

    def test_tags_index(self):
        self.shoot('tags', '/tags/')

    def test_admin_dashboard(self):
        self.shoot('admin-dashboard', '/admin/', user=self.admin)
