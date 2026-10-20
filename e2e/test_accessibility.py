"""Accessibility: the main pages meet WCAG 2.0/2.1 levels A and AA, as
checked by axe-core (e2e/vendor/axe.min.js, used by the tests only), for
anonymous visitors, members and administrators, on a desktop in light mode
and on a phone in dark mode (the dark colours have their own contrast)."""
import os

from django.urls import reverse

from .base import E2ETestCase

AXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor', 'axe.min.js')
WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

# Parts of the page axe leaves out, each with the reason. Keep this short:
# fix the page instead whenever the markup is ours.
EXCLUDE = []

RUN_AXE = '''async ([tags, exclude]) => {
    const result = await axe.run({include: [document], exclude: exclude},
                                 {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']});
    return result.violations.map(v => ({
        id: v.id, impact: v.impact, help: v.help,
        // The selector, and the first reason axe gives (contrast figures, missing label...).
        nodes: v.nodes.map(n => n.target.join(' ') + ': ' + ((n.failureSummary || '').split('\\n')[1] || '').trim()),
    }));
}'''

FINISHED_ANIMATING = '''() => !(window.jQuery && jQuery(':animated').length) &&
    document.getAnimations().every(a => a.playState !== 'running' || a.effect.getComputedTiming().iterations === Infinity)'''

VIEWS = (('desktop', False), ('mobile', True))


class AccessibilityTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=150)
        self.admin = self.create_user('admin', reputation=1000, is_staff=True, is_superuser=True)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?',
                                             tags='collect export')
        self.answer = self.create_answer(self.bob, self.question,
                                         'Use the **CSV export** in the Collect designer:\n\n```\nFile > Export\n```')
        self.create_comment(self.alice, self.answer, 'Thanks, @bob, that worked for me.')
        self.create_comment(self.bob, self.question, 'Which version of Collect do you use?')
        self.create_question(self.bob, 'Can SEPAL process Sentinel-2 time series?', tags='sepal')
        # The question page with an accepted answer, and a question closed as a duplicate.
        from forum.actions import AcceptAnswerAction, CloseAction
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=self.answer, ip='127.0.0.1').save()
        self.closed = self.create_question(self.alice, 'Exporting Collect data as CSV files', tags='collect')
        self._as_request(self.admin)
        CloseAction(user=self.admin, node=self.closed, extra='duplicate', ip='127.0.0.1').save(
            data=dict(duplicate_of=self.question))

    def public_pages(self):
        return ['/', '/questions/', self.question.get_absolute_url(), '/questions/ask/', '/tags/', '/users/',
                self.alice.get_profile_url(), '/search/?q=export']

    def check_pages(self, user, paths, views=VIEWS):
        """Opens each page in each view and reports every violation together.
        A (path, selector) entry opens the page and clicks the selector (a menu) first."""
        failures = []
        for device, dark in views:
            page = self.open(user, device=device, dark=dark)
            for path in paths:
                path, click = path if isinstance(path, tuple) else (path, None)
                self.visit(page, path)
                if click:
                    page.click(click)
                    path = '%s, after clicking %s' % (path, click)
                failures += ['%s (%s%s):\n%s' % (path, device, ', dark' if dark else '', violation)
                             for violation in self.axe(page)]
        if failures:
            self.fail('%d accessibility violations (WCAG 2.1 A/AA, axe-core):\n\n%s' % (
                len(failures), '\n'.join(failures)))

    def axe(self, page, tags=WCAG_TAGS):
        # Messages fade in: check the colours they end with, not a frame of the fade.
        page.wait_for_function(FINISHED_ANIMATING)
        if not page.evaluate('() => !!window.axe'):
            # Evaluated through the DevTools protocol: an injected <script>
            # element has no nonce, so the page's CSP would block it.
            with open(AXE, encoding='utf-8') as source:
                page.evaluate('() => { %s\n}' % source.read())
            page.wait_for_function('() => !!window.axe')
        # axe reads the page's style sheets itself (for css-orientation-lock)
        # and requests the targets of @import rules relative to the page
        # instead of to the style sheet (Django admin's forms.css imports
        # widgets.css): its own failed requests aren't the page's problems.
        fetched = []
        listener = lambda request: fetched.append(request.url) if request.resource_type in ('xhr', 'fetch') else None
        page.on('request', listener)
        try:
            violations = page.evaluate(RUN_AXE, [tags, EXCLUDE])
        finally:
            page.remove_listener('request', listener)
        page.problems[:] = [p for p in page.problems if not any(url in p for url in fetched)]
        self.check_page(page)
        return ['  %s [%s] %s\n%s' % (v['id'], v['impact'], v['help'], ''.join(
            '    - %s\n' % node for node in v['nodes'][:5]) + (
            '    (+%d more)\n' % (len(v['nodes']) - 5) if len(v['nodes']) > 5 else ''))
            for v in violations]

    def test_anonymous_pages(self):
        self.check_pages(None, self.public_pages() + ['/account/signin/', '/account/local/register/', self.closed_url()])

    def test_member_pages(self):
        self.check_pages(self.alice, self.public_pages() + [
            reverse('notifications'), self.alice.get_user_subscriptions_url(),
            (self.alice.get_profile_url(), '#user-menu'),
            (self.question.get_absolute_url(), '#node-%d-menu-trigger' % self.answer.id),
            (self.question.get_absolute_url(), '#comment-tools-%d .add-comment-link' % self.answer.id),
            self.closed_url()])

    def closed_url(self):
        from forum.models import Question
        return Question.objects.get(id=self.closed.id).get_absolute_url()

    def test_search_suggestions_open(self):
        """The header search box with its suggestions open, an option active."""
        self.create_user('collector', reputation=20)
        failures = []
        for device, dark in VIEWS:
            page = self.open(device=device, dark=dark)
            self.visit(page, '/')
            page.locator('#keywords').fill('coll')
            page.wait_for_selector('#searchbox-listbox [role=option]')
            page.locator('#keywords').press('ArrowDown')
            self.assertEqual(page.locator('#searchbox-listbox [aria-selected=true]').count(), 1)
            self.assertEqual(page.locator('#searchbox-listbox [role=group] .searchbox-group-label').all_inner_texts(),
                             ['QUESTIONS', 'TAGS', 'PEOPLE'])
            failures += ['/ with search suggestions (%s%s):\n%s' % (device, ', dark' if dark else '', violation)
                         for violation in self.axe(page)]
        if failures:
            self.fail('%d accessibility violations (WCAG 2.1 A/AA, axe-core):\n\n%s' % (
                len(failures), '\n'.join(failures)))

    def test_list_pages(self):
        """Question lists with pagination, a tag page with the member's interesting
        and ignored tags marked, an empty list, and the tags and users indexes
        filtered, with and without results."""
        from forum.models import MarkedTag, Question, Tag
        for i in range(15):
            Question(author=self.bob, title='Filler question number %d about plots' % i,
                     body='Body of filler question %d, long enough.' % i, tagnames='plots').save()
        member = self.create_user('carol', reputation=100)
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='collect'), reason='good')
        MarkedTag.objects.create(user=member, tag=Tag.objects.get(name='export'), reason='bad')
        # Ignores every tag: nothing left on the question list.
        hermit = self.create_user('hermit', reputation=100)
        for tag in Tag.objects.all():
            MarkedTag.objects.create(user=hermit, tag=tag, reason='bad')
        self.check_pages(member, ['/questions/?pagesize=15', '/questions/?sort=newest&page=2', '/tags/collect/',
                                  '/tags/?q=col', '/tags/?q=nothing-matches', '/users/?q=ali', '/users/?q=nobody'])
        self.check_pages(hermit, ['/questions/'])

    def test_profile_pages(self):
        """Profiles: her own (settings menu open), someone else's, the reputation
        tab with its graph, the settings pages, and the empty profile of a newcomer."""
        def tab(name, user):
            return reverse(name, kwargs={'id': user.id, 'slug': user.username})
        self.check_pages(self.alice, [
            (self.alice.get_profile_url(), '#user-menu'), self.bob.get_profile_url(),
            tab('user_reputation', self.alice), tab('user_recent', self.alice), tab('user_votes', self.alice),
            tab('edit_user', self.alice), self.alice.get_user_subscriptions_url(),
            self.alice.get_user_subscriptions_url() + '?tab=manage', tab('user_preferences', self.alice),
            reverse('user_authsettings', kwargs={'id': self.alice.id}),
            reverse('user_account_data', kwargs={'id': self.alice.id})])
        dana = self.create_user('dana')
        self.check_pages(dana, [dana.get_profile_url(), tab('user_favorites', dana), tab('user_reputation', dana)])

    def test_tag_management_pages(self):
        """A tag page with its description and synonyms as a moderator, the tag's
        management page with a history, the merge confirmation page, the
        synonyms list and the tags index with its "Synonyms" link."""
        from forum.models import Tag
        from forum.utils import tags as tagtools
        collect = Tag.objects.get(name='collect')
        tagtools.edit_description(collect, 'Questions about **Collect**, the survey designer. ' * 4, self.admin, '127.0.0.1')
        tagtools.add_synonym(collect, 'collect-survey', self.admin, '127.0.0.1')
        tagtools.add_synonym(Tag.objects.get(name='export'), 'csv', self.admin, '127.0.0.1')
        self.check_pages(self.admin, ['/tags/collect/', ('/tags/collect/', '.tag-wiki-more summary'),
                                      reverse('tag_edit', kwargs={'tag': 'collect'}),
                                      reverse('tag_merge', kwargs={'tag': 'sepal'}) + '?into=collect',
                                      reverse('tag_synonyms'), '/tags/'])

    def test_administrator_pages(self):
        self.check_pages(self.admin, [self.question.get_absolute_url(), reverse('admin_index'),
                                      '/admin/settings/basic/', '/admin/settings/extkeys/',
                                      '/admin/settings/appearance/', '/admin/settings/api/', '/admin/search/?q=logo',
                                      '/admin/support/', '/admin/statistics/',
                                      '/admin/static_pages/new/', '/admin/email-previews/new-answer/',
                                      '/admin/tools/createuser/', '/admin/tools/nodeman/'])
        self.check_pages(self.admin, [(reverse('admin_index'), '#admin-menu > summary')], views=[('mobile', True)])

    def test_post_forms(self):
        """The ask page with similar questions open, tags as chips and a preview,
        the ask page with errors, the edit question page (someone else's post)
        and the retag page."""
        from forum import settings
        self.set_setting(settings.REP_TO_RETAG, 500)
        self.set_setting(settings.REP_TO_EDIT_OTHERS, 2000)
        failures = []
        for device, dark in VIEWS:
            page = self.open(self.bob, device=device, dark=dark)
            self.visit(page, '/questions/ask/')
            page.locator('#id_title').press_sequentially('export Collect survey', delay=10)
            page.wait_for_selector('#ask-related-questions .similar-item')
            page.fill('#editor', 'Some **bold** text and `code`.')
            page.wait_for_selector('#previewer strong', state='attached')  # behind the Preview tab on a phone
            page.locator('#id_tags').press_sequentially('collect export ')
            failures += self.axe_failures(page, '/questions/ask/ with similar questions and chips', device, dark)
            if device == 'mobile':
                page.get_by_role('tab', name='Preview').click()
                failures += self.axe_failures(page, '/questions/ask/ preview tab', device, dark)

            page.evaluate('localStorage.clear()')
            self.visit(page, '/questions/ask/')
            page.fill('#id_title', 'Help')
            with page.expect_navigation():
                page.click('#fmask input[name=ask]')
            self.check_page(page)
            failures += self.axe_failures(page, '/questions/ask/ with errors', device, dark)

            path = reverse('edit_answer', kwargs={'id': self.answer.id})  # bob's own answer
            self.visit(page, path)
            failures += self.axe_failures(page, path, device, dark)

            # an administrator editing alice's question ("you are editing a post by alice")
            editor = self.open(self.admin, device=device, dark=dark)
            path = reverse('edit_question', kwargs={'id': self.question.id})
            self.visit(editor, path)
            failures += self.axe_failures(editor, path, device, dark)

            # retagging only (no rights to edit others' posts)
            retagger = self.open(self.create_user('tagger-%s' % device, reputation=600), device=device, dark=dark)
            self.visit(retagger, path)
            retagger.wait_for_selector('#fmretag')
            failures += self.axe_failures(retagger, path + ' (retag)', device, dark)
        if failures:
            self.fail('%d accessibility violations (WCAG 2.1 A/AA, axe-core):\n\n%s' % (
                len(failures), '\n'.join(failures)))

    def axe_failures(self, page, where, device, dark):
        return ['%s (%s%s):\n%s' % (where, device, ', dark' if dark else '', violation) for violation in self.axe(page)]

    def test_moderation_inbox(self):
        """The moderation inbox with an item of every kind (the admin menu and
        the "Delete as spam" dialog open), and a post waiting for review as its
        author and a moderator see it."""
        from forum import settings
        from forum.actions import FlagAction, ReportAction
        from forum.models import ModerationReport
        newcomer = self.create_user('newcomer', reputation=60)
        self.set_setting(settings.FIRST_POSTS_MODERATION, 'before')
        held = self.create_answer(newcomer, self.question, 'A first answer by a newcomer, waiting for review.')
        FlagAction(user=self.alice, node=self.answer, extra='Advertising', ip='127.0.0.1').save()
        self._as_request(self.bob)
        ReportAction(user=self.bob, ip='127.0.0.1').save(data={'reported': newcomer, 'publicmsg': 'Spam links'})
        ModerationReport.objects.create(node=self.question, source='ai', verdict='spam', confidence=0.9,
                                        reason='Advertises a product.')
        moderator = self.create_user('moderator', reputation=10, is_staff=True)
        failures = []
        for device, dark in VIEWS:
            page = self.open(moderator, device=device, dark=dark)
            where = 'inbox'
            self.visit(page, reverse('admin_moderation'))
            failures += self.axe_failures(page, where, device, dark)
            if device == 'mobile':
                page.click('#admin-menu > summary')
                failures += self.axe_failures(page, where + ' with the menu open', device, dark)
            page.locator('#review-%d' % held.id).get_by_role('button', name='Delete as spam').click()
            page.wait_for_selector('#spam-review-%d[open]' % held.id)
            failures += self.axe_failures(page, where + ' with the spam dialog', device, dark)
        for user in (newcomer, moderator):
            failures += ['%s:\n%s' % (path, v) for path in [self.question.get_absolute_url()]
                         for v in self._axe_path(user, path)]
        if failures:
            self.fail('%d accessibility violations (WCAG 2.1 A/AA, axe-core):\n\n%s' % (
                len(failures), '\n'.join(failures)))

    def _axe_path(self, user, path):
        violations = []
        for device, dark in VIEWS:
            page = self.open(user, device=device, dark=dark)
            self.visit(page, path)
            self.assertEqual(page.locator('.review-notice').count(), 1)
            violations += self.axe(page)
        return violations
