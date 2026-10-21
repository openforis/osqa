"""The ask and edit pages (templates/ask.html, question_edit.html,
answer_edit.html, compose/*.html; osqa.compose.js, osqa.tagchips.js,
osqa.ask.js, the ask section of osqa.css): tags as chips, the "Similar questions" panel, the
Write/Preview tabs on a phone, the draft kept in the browser, Ctrl+Enter, the
unsaved-changes guard, the error summary, the edit page's revision picker and
summary, and screenshots (tmp/e2e/ask-page-*.png) on a desktop and a phone,
light and dark."""
import os

from django.urls import reverse

from forum.models import Question

from .base import ARTIFACTS, E2ETestCase

BODY = 'I have a survey with 200 plots and need the data as CSV files for R.'


class AskPageTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=500)

    def chips(self, page):
        return page.locator('.tag-chip .tag-chip-name').all_inner_texts()

    def tags_value(self, page):
        return page.input_value('#id_tags_value')

    def test_tag_chips(self):
        self.create_question(self.bob, 'Exporting Collect survey data to CSV', tags='collect export csv')
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        tags = page.locator('#id_tags')
        # the server's field keeps its id and label; its name moved to the hidden value
        self.assertIsNone(tags.get_attribute('name'))
        self.assertEqual(page.get_attribute('#id_tags_value', 'name'), 'tags')
        self.assertEqual(page.locator('label[for=id_tags]').inner_text(), 'Tags')
        self.assertIn('id_tags-help', tags.get_attribute('aria-describedby'))

        tags.press_sequentially('Collect')
        tags.press('Enter')
        tags.press_sequentially('export,')
        tags.press_sequentially('sepal ')
        self.assertEqual(self.chips(page), ['collect', 'export', 'sepal'])
        self.assertEqual(self.tags_value(page), 'collect export sepal')
        self.assertEqual(tags.input_value(), '')
        page.wait_for_function("() => /sepal/.test(document.querySelector('#compose-tags [role=status]').textContent)")

        # Backspace in the empty box removes the last chip; the x button removes any
        tags.press('Backspace')
        self.assertEqual(self.chips(page), ['collect', 'export'])
        remove = page.get_by_role('button', name='Remove tag collect')
        remove.click()
        self.assertEqual(self.chips(page), ['export'])
        self.assertEqual(page.evaluate('document.activeElement.id'), 'id_tags')

        # a suggestion becomes a chip
        tags.press_sequentially('cs', delay=50)
        suggestion = page.locator('.osqa-autocomplete li:has-text("csv")')
        suggestion.first.wait_for()
        suggestion.first.click()
        self.assertEqual(self.chips(page), ['export', 'csv'])
        self.assertEqual(tags.input_value(), '')

        # a word left in the box is added when posting
        tags.press_sequentially('r-lang')
        self.assertEqual(tags.input_value(), 'r-lang')
        self.assertEqual(self.tags_value(page), 'export csv r-lang')  # sent even if never made a chip
        # the "Similar questions" panel opens as the title is typed: wait for it, so the
        # click on the button isn't moved by the layout changing
        with page.expect_response(lambda r: '/questions/related_questions/' in r.url):
            page.fill('#id_title', 'Exporting plot data from Collect for use in R')
        page.fill('#editor', BODY)
        self.assertEqual(self.tags_value(page), 'export csv r-lang')
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        question = Question.objects.get(title='Exporting plot data from Collect for use in R')
        self.assertEqual(question.tagnames, 'export csv r-lang')

    def test_similar_questions(self):
        answered = self.create_question(self.bob, 'Exporting Collect survey data to CSV', tags='collect export')
        answer = self.create_answer(self.alice, answered)
        from forum.actions import AcceptAnswerAction
        self._as_request(self.bob)
        AcceptAnswerAction(user=self.bob, node=answer, ip='127.0.0.1').save()
        self.create_question(self.bob, 'Exporting Collect survey plots as KML', tags='collect')

        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        panel = page.locator('#ask-related-questions')
        self.assertTrue(panel.is_hidden())
        with page.expect_response(lambda r: '/questions/related_questions/' in r.url):
            page.locator('#id_title').press_sequentially('export Collect survey', delay=20)
        page.wait_for_selector('#ask-related-questions .similar-item')
        self.assertIn('Similar questions', panel.locator('summary').inner_text())
        items = panel.locator('.similar-item')
        self.assertEqual(items.count(), 2)
        accepted = items.filter(has_text='Exporting Collect survey data to CSV')
        self.assertEqual(accepted.locator('.similar-status').inner_text(), 'accepted answer')
        self.assertEqual(accepted.locator('a').get_attribute('target'), '_blank')
        self.assertEqual(items.filter(has_text='KML').locator('.similar-status').inner_text(), 'unanswered')

        # the panel folds away and stays folded as the title changes
        panel.locator('summary').click()
        self.assertTrue(items.first.is_hidden())
        page.locator('#id_title').press_sequentially(' data', delay=20)
        page.wait_for_timeout(800)
        self.wait_for_ajax(page)
        self.assertFalse(panel.locator('details').evaluate('d => d.open'))

        # cleared title: no panel
        page.fill('#id_title', '')
        page.wait_for_selector('#ask-related-questions', state='hidden')
        self.check_page(page)

    def test_preview_tabs_on_a_phone(self):
        page = self.open(self.alice, device='mobile', dark=True)
        self.visit(page, '/questions/ask/')
        write, preview = page.get_by_role('tab', name='Write'), page.get_by_role('tab', name='Preview')
        self.assertEqual(write.get_attribute('aria-selected'), 'true')
        self.assertTrue(page.locator('#compose-preview').is_hidden())
        self.assertEqual(page.get_attribute('#compose-write', 'role'), 'tabpanel')
        page.fill('#editor', 'Testing the **preview** on a phone.')
        preview.click()
        page.wait_for_selector('#previewer strong:has-text("preview")')
        self.assertTrue(page.locator('#editor').is_hidden())
        self.assertEqual(preview.get_attribute('aria-selected'), 'true')
        # arrow keys move between the tabs
        preview.press('ArrowLeft')
        self.assertEqual(write.get_attribute('aria-selected'), 'true')
        self.assertTrue(page.locator('#editor').is_visible())
        self.assertEqual(page.evaluate('document.activeElement.id'), 'compose-tab-write')
        self.check_page(page)

    def test_preview_below_the_editor_on_a_desktop(self):
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        self.assertTrue(page.locator('.compose-tabs').is_hidden())
        page.fill('#editor', 'Testing the **preview** first.')
        page.wait_for_selector('#previewer strong:has-text("preview")')
        toggle = page.locator('#pre-collapse')
        toggle.click()
        self.assertTrue(page.locator('#previewer').is_hidden())
        self.assertEqual((toggle.inner_text(), toggle.get_attribute('aria-expanded')), ('Show preview', 'false'))
        toggle.click()
        self.assertTrue(page.locator('#previewer').is_visible())
        self.check_page(page)

    def test_draft_restored_and_discarded(self):
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        page.fill('#id_title', 'Can Collect Earth run offline?')
        page.fill('#editor', BODY)
        page.locator('#id_tags').press_sequentially('collect-earth offline ')
        page.wait_for_function("() => (localStorage.getItem('osqa-draft:ask') || '').includes('offline')")

        self.visit(page, '/questions/ask/')
        notice = page.locator('.draft-notice')
        notice.wait_for()
        self.assertIn('Your unsent draft was restored.', notice.inner_text())
        self.assertEqual(page.input_value('#id_title'), 'Can Collect Earth run offline?')
        self.assertEqual(page.input_value('#editor'), BODY)
        self.assertEqual(self.chips(page), ['collect-earth', 'offline'])
        page.wait_for_selector('#previewer:has-text("200 plots")')

        notice.get_by_role('button', name='Discard').click()
        self.assertEqual(notice.count(), 0)
        self.assertEqual((page.input_value('#id_title'), page.input_value('#editor')), ('', ''))
        self.assertEqual(self.chips(page), [])
        self.assertIsNone(page.evaluate("localStorage.getItem('osqa-draft:ask')"))
        self.visit(page, '/questions/ask/')
        self.assertEqual(page.locator('.draft-notice').count(), 0)

        # posting removes the draft
        page.fill('#id_title', 'Can Collect Earth run without a connection?')
        page.fill('#editor', BODY)
        page.locator('#id_tags').press_sequentially('collect-earth ')
        page.wait_for_function("() => !!localStorage.getItem('osqa-draft:ask')")
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        self.assertTrue(Question.objects.filter(title='Can Collect Earth run without a connection?').exists())
        self.assertIsNone(page.evaluate("localStorage.getItem('osqa-draft:ask')"))

    def test_ctrl_enter_posts_without_the_leave_warning(self):
        page = self.open(self.alice)
        dialogs = []
        page.on('dialog', lambda dialog: dialogs.append(dialog.type))
        self.visit(page, '/questions/ask/')
        page.fill('#id_title', 'How do I export Collect survey data to CSV?')
        # Enter in the title doesn't post
        page.locator('#id_title').press('Enter')
        page.wait_for_timeout(300)
        self.assertIn('/questions/ask/', page.url)

        # leaving with something typed asks first (the test accepts)
        with page.expect_navigation():
            page.locator('#nav a').first.click()
        self.assertEqual(dialogs, ['beforeunload'])
        dialogs.clear()

        self.visit(page, '/questions/ask/')
        page.fill('#id_title', 'How do I export Collect survey data to CSV?')
        page.fill('#editor', BODY)
        page.locator('#id_tags').press_sequentially('collect export')
        with page.expect_navigation():
            page.locator('#editor').press('Control+Enter')
        self.check_page(page)
        question = Question.objects.get(title='How do I export Collect survey data to CSV?')
        self.assertEqual(question.tagnames, 'collect export')
        self.assertEqual(dialogs, [])  # no "you will lose your changes" after posting

    def test_errors_summary_keeps_the_values(self):
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        page.fill('#id_title', 'Help')
        page.fill('#editor', 'short')
        page.locator('#id_tags').press_sequentially('collect ')
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        summary = page.locator('#form-errors')
        self.assertEqual(summary.get_attribute('role'), 'alert')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'form-errors')
        self.assertIn("Your question isn't posted yet", summary.inner_text())
        self.assertIn('title must be at least', summary.locator('a[href="#id_title"]').inner_text())
        self.assertEqual(summary.locator('a[href="#editor"]').count(), 1)
        # inline messages, linked to their fields
        title = page.locator('#id_title')
        self.assertIn('title must be at least', page.inner_text('#id_title-error'))
        self.assertEqual(title.get_attribute('aria-invalid'), 'true')
        self.assertEqual(title.get_attribute('aria-describedby'), 'id_title-error id_title-help title-min-hint')
        self.assertIn('content must be at least', page.inner_text('#id_text-error'))
        # what was typed is kept
        self.assertEqual(title.input_value(), 'Help')
        self.assertEqual(page.input_value('#editor'), 'short')
        self.assertEqual(self.chips(page), ['collect'])
        # a link in the summary leads to the field
        summary.locator('a[href="#id_title"]').click()
        self.assertEqual(page.evaluate('document.activeElement.id'), 'id_title')

        # fixed: posted
        title.fill('How do I export Collect survey data to CSV?')
        page.fill('#editor', BODY)
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        self.assertEqual(Question.objects.get(title='How do I export Collect survey data to CSV?').tagnames, 'collect')

    def test_edit_someone_elses_question(self):
        question = self.create_question(self.alice, 'Exporting data from Collect', tags='collect')
        self.bob.reputation = 2500  # may edit others' posts
        self.bob.save()
        page = self.open(self.bob)
        dialogs = []
        page.on('dialog', lambda dialog: dialogs.append(dialog.type))
        self.visit(page, reverse('edit_question', kwargs={'id': question.id}))
        self.assertIn('You are editing a post by alice', page.locator('.compose-note').inner_text())
        self.assertEqual(page.locator('label[for=id_revision]').inner_text(), 'Revision')
        self.assertTrue(page.locator('#select_revision').is_hidden())
        self.assertEqual(self.chips(page), ['collect'])
        self.assertEqual(page.locator('label[for=id_summary]').inner_text(), 'Edit summary')

        page.fill('#id_title', 'Exporting survey data from Collect to CSV')
        page.locator('#id_tags').press_sequentially('csv ')
        page.fill('#id_summary', 'clearer title, csv tag')
        page.locator('#id_summary').press('Enter')  # doesn't send the form
        page.wait_for_timeout(300)
        self.assertIn('/edit/', page.url)
        with page.expect_navigation():
            page.get_by_role('button', name='Save edits').click()
        self.check_page(page)
        self.assertEqual(dialogs, [])
        question = Question.objects.get(id=question.id)
        self.assertEqual((question.title, question.tagnames), ('Exporting survey data from Collect to CSV', 'collect csv'))
        self.assertEqual(question.active_revision.summary, 'clearer title, csv tag')

        # the revision picker reloads the form with an earlier version
        self.visit(page, reverse('edit_question', kwargs={'id': question.id}))
        self.assertEqual(page.locator('#id_revision option').count(), 2)
        with page.expect_navigation():
            page.select_option('#id_revision', '1')
        self.check_page(page)
        self.assertEqual(page.input_value('#id_title'), 'Exporting data from Collect')
        self.assertEqual(self.chips(page), ['collect'])

    def test_edit_own_answer(self):
        question = self.create_question(self.alice, 'Exporting data from Collect')
        answer = self.create_answer(self.bob, question, 'Use the CSV export in the designer menu.')
        page = self.open(self.bob)
        self.visit(page, reverse('edit_answer', kwargs={'id': answer.id}))
        self.assertEqual(page.locator('.compose-note').count(), 0)  # their own answer
        self.assertEqual(page.locator('#compose-tags').count(), 0)
        page.fill('#editor', 'Use the CSV export in the designer menu: File > Export > CSV.')
        page.fill('#id_summary', 'menu path')
        with page.expect_navigation():
            page.locator('#editor').press('Control+Enter')
        self.check_page(page)
        from forum.models import Answer
        self.assertEqual(Answer.objects.get(id=answer.id).active_revision.summary, 'menu path')

    def test_screenshots(self):
        """Desktop and phone, light and dark: the ask page with chips, similar
        questions and the preview; the ask page with errors; the edit page."""
        answered = self.create_question(self.bob, 'Exporting Collect survey data to CSV', tags='collect export')
        self.create_answer(self.alice, answered)
        self.create_question(self.bob, 'Exporting Collect survey plots as KML files', tags='collect')
        question = self.create_question(self.bob, 'Exporting data from Collect', tags='collect')
        self.editor = self.create_user('carol', reputation=2500)  # may edit others' posts
        os.makedirs(ARTIFACTS, exist_ok=True)
        shots = []
        for device, dark in (('desktop', False), ('desktop', True), ('mobile', False), ('mobile', True)):
            name = '%s-%s' % (device, 'dark' if dark else 'light')
            page = self.open(self.alice, device=device, dark=dark)
            self.visit(page, '/questions/ask/')
            with page.expect_response(lambda r: '/questions/related_questions/' in r.url):
                page.locator('#id_title').press_sequentially('export Collect survey', delay=10)
            page.wait_for_selector('#ask-related-questions .similar-item')
            page.fill('#editor', 'I have a survey with **200 plots**:\n\n- one CSV per plot\n- in `UTF-8`\n\nHow do I export them?')
            page.wait_for_selector('#previewer strong', state='attached')  # behind the Preview tab on a phone
            page.locator('#id_tags').press_sequentially('collect export csv ')
            page.locator('#id_tags').blur()
            self.check_page(page)
            path = os.path.join(ARTIFACTS, 'ask-page-%s.png' % name)
            page.screenshot(path=path, full_page=True)
            shots.append(path)
            if device == 'mobile':
                page.get_by_role('tab', name='Preview').click()
                page.locator('#compose-body').scroll_into_view_if_needed()
                path = os.path.join(ARTIFACTS, 'ask-page-preview-%s.png' % name)
                page.screenshot(path=path)
                shots.append(path)

            page.evaluate("localStorage.clear()")
            self.visit(page, '/questions/ask/')
            page.fill('#id_title', 'Help')
            with page.expect_navigation():
                page.click('#fmask input[name=ask]')
            self.check_page(page)
            path = os.path.join(ARTIFACTS, 'ask-page-errors-%s.png' % name)
            page.screenshot(path=path, full_page=True)
            shots.append(path)

            editor = self.open(self.editor, device=device, dark=dark)
            self.visit(editor, reverse('edit_question', kwargs={'id': question.id}))
            editor.fill('#id_summary', 'clearer title')
            path = os.path.join(ARTIFACTS, 'ask-page-edit-%s.png' % name)
            editor.screenshot(path=path, full_page=True)
            shots.append(path)

            # alice may retag others' questions, not edit them
            self.visit(page, reverse('edit_question', kwargs={'id': question.id}))
            path = os.path.join(ARTIFACTS, 'ask-page-retag-%s.png' % name)
            page.screenshot(path=path, full_page=True)
            shots.append(path)
        for path in shots:
            self.assertTrue(os.path.getsize(path) > 0, path)
