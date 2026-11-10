"""The email layout and wording: every kind of email renders an HTML and a
plain text part with its call-to-action link, preview line and footer
(unsubscribe links and the List-Unsubscribe header for notifications), user
content is escaped in the HTML part and plain in the text part, @mention
emails quote the sentence, and the admin's email previews."""
import re

from django.urls import reverse

from forum import settings
from forum.models import Comment, Node, Question
from forum.templatetags import email_tags
from forum.utils import email_samples

from .base import OSQATestCase

# kind -> (button label, a part of the button's URL)
CTA = {
    # The sample's reader asked the question: they are asked to accept the answer.
    'new-answer': ('Review and accept the answer', '/questions/990010/how-do-i-export-survey-data-to-csv/990011'),
    'new-comment': ('View the comment', '/questions/990010/how-do-i-export-survey-data-to-csv#990012'),
    'answer-accepted': ('View the answer', '/questions/990010/how-do-i-export-survey-data-to-csv/990011'),
    'mention': ('View the comment', '/questions/990010/how-do-i-export-survey-data-to-csv#990013'),
    'new-question': ('View the question', '/questions/990010/how-do-i-export-survey-data-to-csv'),
    'new-member': ('View their profile', '/users/990003/dana'),
    'digest': ('See all new questions', '/questions/?sort=latest'),
    'summary': ('See all your notifications', '/notifications/'),
    'post-reviewed': ('View your post', '/questions/990010/how-do-i-export-survey-data-to-csv/990011'),
    'accept-reminder': ('Review the answers', '/questions/990010/how-do-i-export-survey-data-to-csv'),
    'answer-request': ('Answer the question', '/questions/990010/how-do-i-export-survey-data-to-csv'),
    'suggested-edit': ('View the post', '/questions/990010/how-do-i-export-survey-data-to-csv/990011'),
    'feedback': ('Reply by email', 'mailto:carol@example.com'),
    'user-reported': ("Review bob's profile", '/users/990001/bob'),
    'welcome': ('Confirm your email', '/account/validate/%(id)d/sample-validation-code/'),
    'password-reset': ('Choose a new password', '/account/tempsignin/%(id)d/sample-reset-code/'),
    'confirm-email': ('Confirm your email', '/account/validate/%(id)d/sample-validation-code/'),
    'password-changed': ('Reset your password', '/account/tempsignin/'),
    'new-sign-in': ('Reset your password', '/account/tempsignin/'),
    'email-change-confirm': ('Confirm new address', '/account/email/confirm/%(id)d/sample-confirm-code/'),
    'email-change-notice': ('Cancel the change', '/account/email/cancel/%(id)d/sample-cancel-code/'),
    'email-changed-by-admin': (None, None),
    'account-deleted': (None, None),
    'account-exists': ('Sign in', '/account/signin/'),
    'passkey-added': ('Open your security page', '/account/%(id)d/security/'),
    'two-step-on': ('Open your security page', '/account/%(id)d/security/'),
    'two-step-off': ('Open your security page', '/account/%(id)d/security/'),
    'recovery-codes': ('Open your security page', '/account/%(id)d/security/'),
    'api-token-created': ('Open your security page', '/account/%(id)d/security/'),
    'confirm-its-you': ('Confirm and continue', '/account/confirm/%(id)d/sample-confirm-code/'),
    'test-email': (None, None),
}
NOTIFICATIONS = {'new-answer', 'new-comment', 'answer-accepted', 'mention', 'new-question', 'new-member', 'digest',
                 'summary', 'accept-reminder', 'suggested-edit', 'answer-request'}


def button(html):
    """(href, label) of each call-to-action button in an HTML email."""
    return re.findall(r'<td align="center" bgcolor="[^"]+" style="[^"]*"><a href="([^"]+)" target="_blank" '
                      r'style="[^"]*">([^<]+)</a>', html)


class EveryEmailKindTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True, email_isvalid=True)

    def test_every_kind_renders_both_parts(self):
        self.assertEqual(set(CTA), set(email_samples.KINDS))
        nodes = Node.objects.count()
        for kind in email_samples.KINDS:
            with self.subTest(kind=kind):
                email = email_samples.render(kind, self.admin)
                html, text, subject = email['html'], email['text'], email['subject']
                self.assertTrue(subject)
                self.assertNotIn('\n', subject)
                # The layout: a full document with the color-scheme meta tags, a preview
                # line, the logo by absolute URL with alt text, and no leftover template code.
                self.assertTrue(html.startswith('<!DOCTYPE html>'), html[:80])
                self.assertIn('<meta name="color-scheme" content="light dark">', html)
                self.assertIn('@media (prefers-color-scheme: dark)', html)
                self.assertIn('max-width:600px', html)
                self.assertIn('class="em-preheader"', html)
                self.assertIn('<img class="em-logo" src="http://testserver/upfiles/logo.png"', html)
                self.assertRegex(html, r'<img class="em-logo"[^>]* alt="[^"]+"')
                self.assertIn('<title>%s</title>' % subject.replace("'", '&#x27;').replace('"', '&quot;'), html)
                for part in (html, text, subject):
                    self.assertNotIn('{{', part)
                    self.assertNotIn('{%', part)
                    self.assertNotIn('None', part)
                self.assertNotIn('&amp;', text)
                self.assertNotIn('&lt;', text)
                self.assertNotIn('&#x27;', text)
                self.assertFalse(re.search(r'^[ \t]+\S', text, re.M), 'indented text: %r' % text)

                label, url = CTA[kind]
                if label:
                    url = url % {'id': self.admin.id}
                    full = url if url.startswith('mailto:') else 'http://testserver' + url
                    self.assertEqual(button(html), [(full, label)])
                    if not url.startswith('mailto:'):
                        # The text part has the same link on a line of its own, after the label.
                        self.assertIn('%s:\n%s\n' % (label, full), text + '\n')
                else:
                    self.assertEqual(button(html), [])

                if kind in NOTIFICATIONS:
                    self.assertRegex(email['headers']['List-Unsubscribe'], r'^<http://testserver/unsubscribe/[^>]+/>$')
                    self.assertEqual(email['headers']['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
                    self.assertIn('Hi admin,', html)
                    self.assertIn('Hi admin,\n', text)
                    for words in ('You receive this email because', 'Choose which emails you get',
                                  'Unsubscribe from all emails', 'How email notifications work'):
                        self.assertIn(words, html)
                        self.assertIn(words, text)
                    self.assertIn('Unsubscribe from all emails: http://testserver/unsubscribe/', text)
                    self.assertIn('href="http://testserver/unsubscribe/', html)
                else:
                    self.assertEqual(email['headers'], {})
                    self.assertNotIn('/unsubscribe/', html + text)
        self.assertEqual(Node.objects.count(), nodes)  # previews save nothing
        self.assertEqual(self.sent_mail, [])  # and send nothing

    def test_subjects(self):
        subjects = {kind: email_samples.render(kind, self.admin)['subject'] for kind in email_samples.KINDS}
        self.assertEqual(subjects['new-answer'], 'New answer to: How do I export survey data to CSV?')
        self.assertEqual(subjects['new-comment'], 'New comment on: How do I export survey data to CSV?')
        self.assertEqual(subjects['answer-accepted'], 'Answer accepted: How do I export survey data to CSV?')
        self.assertEqual(subjects['mention'], 'carol mentioned you in: How do I export survey data to CSV?')
        self.assertEqual(subjects['new-question'], 'New question: How do I export survey data to CSV?')
        self.assertEqual(subjects['new-member'], 'dana joined OSQA')
        self.assertEqual(subjects['digest'], 'Daily digest: 12 new questions')
        self.assertEqual(subjects['summary'], 'Your weekly summary: 7 updates')
        self.assertEqual(subjects['accept-reminder'], 'Did an answer solve "How do I export survey data to CSV?"?')
        self.assertEqual(subjects['feedback'], 'Feedback from carol')
        self.assertEqual(subjects['user-reported'], 'User reported: bob by carol')
        self.assertEqual(subjects['welcome'], 'Welcome to OSQA: please confirm your email')
        self.assertEqual(subjects['password-reset'], 'Reset your password for OSQA')
        self.assertEqual(subjects['confirm-email'], 'Confirm your email address for OSQA')
        self.assertEqual(subjects['password-changed'], 'Your OSQA password was changed')
        self.assertEqual(subjects['new-sign-in'], 'New sign-in to your OSQA account')
        self.assertEqual(subjects['email-change-confirm'], 'Confirm your new email address for OSQA')
        self.assertEqual(subjects['email-change-notice'], 'Your OSQA email address is being changed')
        self.assertEqual(subjects['account-deleted'], 'Your OSQA account has been deleted')
        self.assertEqual(subjects['account-exists'], 'You already have an account on OSQA')

    def test_subject_prefix(self):
        settings.EMAIL_SUBJECT_PREFIX.set_value('[Forum]')
        self.addCleanup(setattr, settings.EMAIL_SUBJECT_PREFIX, '_temp', None)
        self.assertEqual(email_samples.render('new-member', self.admin)['subject'], '[Forum] dana joined OSQA')

    def test_account_emails_say_why_they_were_sent(self):
        text = email_samples.render('welcome', self.admin)['text']
        self.assertIn('You receive this email because someone signed up at OSQA with this address.', text)
        self.assertIn('The link works once, for 48 hours.', text)
        html = email_samples.render('password-reset', self.admin)['html']
        self.assertIn('a password reset was requested for your account', html)
        self.assertIn('These notices are always sent.', email_samples.render('password-changed', self.admin)['text'])
        self.assertIn('Button not working? Copy this link into your browser:', html)

    def test_digest_moderator_section_only_for_superusers(self):
        self.assertIn('2 posts were flagged in the last day.', email_samples.render('digest', self.admin)['text'])
        member = self.create_user('member')
        self.assertNotIn('flagged', email_samples.render('digest', member)['text'])

    def test_admin_styles_are_added_and_old_defaults_ignored(self):
        p_style = email_tags.email_styles()['p_style']
        self.assertIn('font-size:16px', p_style)
        self.assertNotIn('font-size:14px', p_style)  # the old default setting is not applied
        settings.EMAIL_PARAGRAPH_STYLE.set_value('color:#004400')
        self.addCleanup(setattr, settings.EMAIL_PARAGRAPH_STYLE, '_temp', None)
        self.assertTrue(email_tags.email_styles()['p_style'].endswith('color:#004400;'))
        html = email_samples.render('new-member', self.admin)['html']
        self.assertIn('color:#004400;', html)

    def test_without_a_logo_the_site_name_is_shown(self):
        settings.APP_LOGO.set_value('')
        self.addCleanup(setattr, settings.APP_LOGO, '_temp', None)
        html = email_samples.render('new-member', self.admin)['html']
        self.assertNotIn('<img', html)
        self.assertIn('class="em-site"', html)


class EscapingTest(OSQATestCase):
    """Titles, names and post text are escaped in the HTML part and plain in the text part."""
    TITLE = 'Why is <b>bold</b> & "quoted" text shown?'

    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', email_isvalid=True)
        self.bob = self.create_user('bob', email_isvalid=True, reputation=100)
        self.login(self.alice)
        self.client.post(reverse('ask'), {'title': 'Why is bold text shown?', 'text': 'A question body that is long enough.',
                                          'tags': 'collect'})
        # Asking strips tags from titles; older or imported questions may still have them.
        self.question = Question.objects.get(title='Why is bold text shown?')
        self.question.title = self.TITLE
        self.question.save()
        self.sent_mail.clear()

    def check(self, mail):
        recipient, subject, html, text, media, headers = mail
        self.assertIn(self.TITLE, subject)
        self.assertIn(self.TITLE, text)
        self.assertNotIn('<b>bold</b>', html)
        self.assertIn('Why is &lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot; text shown?', html)
        self.assertNotIn('<script', html)
        return html, text

    def test_answer_email(self):
        self.login(self.bob)
        self.client.post(reverse('answer', args=[self.question.id]),
                         {'text': 'Write `<script>alert(1)</script>` in the field and save it again.'})
        mails = [m for m in self.sent_mail if m[0] == self.alice]
        self.assertEqual(len(mails), 1)
        html, text = self.check(mails[0])
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('> Write <script>alert(1)</script> in the field and save it again.', text)
        self.assertIn('bob answered "%s":' % self.TITLE, text)
        self.assertIn('href="http://testserver%s"' % self.question.answers.get().get_absolute_url(), html)

    def test_comment_email_with_html_in_the_comment(self):
        self.login(self.bob)
        reply = self.command(reverse('comment', args=[self.question.id]),
                             {'comment': 'Does <img src=x onerror=alert(1)> break the `<i>` tag here?'})
        self.assertTrue(reply['success'], reply)
        mails = [m for m in self.sent_mail if m[0] == self.alice]
        self.assertEqual(len(mails), 1)
        html, text = self.check(mails[0])
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<i>', html)
        self.assertIn('&lt;i&gt;', html)
        self.assertIn('bob commented on your question "%s":' % self.TITLE, text)
        self.assertIn('the `<i>` tag here?'.replace('`', ''), text)

    def test_long_posts_are_shortened(self):
        self.login(self.bob)
        words = ' '.join('word%d' % i for i in range(300))
        self.client.post(reverse('answer', args=[self.question.id]), {'text': words})
        html, text = self.check([m for m in self.sent_mail if m[0] == self.alice][0])
        quote = re.search(r'^> (.*)$', text, re.M).group(1)
        self.assertLessEqual(len(quote), 401)
        self.assertTrue(quote.endswith('\u2026'))
        self.assertNotIn('word299', html + text)


class MentionEmailTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', email_isvalid=True)
        self.bob = self.create_user('bob', email_isvalid=True)
        self.login(self.alice)
        self.client.post(reverse('ask'), {'title': 'How do I reproject a shapefile?',
                                          'text': 'A question body that is long enough.', 'tags': 'gis'})
        self.question = Question.objects.get(title='How do I reproject a shapefile?')
        self.sent_mail.clear()

    def test_the_sentence_with_the_mention_is_quoted(self):
        self.command(reverse('comment', args=[self.question.id]), {
            'comment': 'I tried the usual tools first. Then @bob could you check the projection settings? '
                       'They look wrong to me.'})
        recipient, subject, html, text, media, headers = [m for m in self.sent_mail if m[0] == self.bob][0]
        self.assertEqual(subject, 'alice mentioned you in: How do I reproject a shapefile?')
        self.assertIn('alice mentioned you in a comment on "How do I reproject a shapefile?":', text)
        self.assertIn('> Then @bob could you check the projection settings?\n', text)
        self.assertNotIn('I tried the usual tools first', text)
        self.assertIn('Then <strong>@bob</strong> could you check the projection settings?', html)
        comment = Comment.objects.latest('id')
        self.assertIn('View the comment:\nhttp://testserver%s\n' % comment.get_absolute_url(), text)
        self.assertIn('You receive this email because someone mentioned you.', text)

    def test_mention_in_an_answer(self):
        self.login(self.alice)
        self.client.post(reverse('answer', args=[self.question.id]),
                         {'text': 'Answering myself, but @bob knows this better than me.'})
        recipient, subject, html, text, media, headers = [m for m in self.sent_mail if m[0] == self.bob][0]
        self.assertIn('alice mentioned you in an answer to "How do I reproject a shapefile?":', text)
        self.assertIn('View the answer:', text)

    def test_mention_context_filter(self):
        body = '<p>One. Two @Bob three.</p><p>Four.</p>'
        self.assertEqual(email_tags.mention_context(body, 'bob'), 'Two @Bob three.')
        self.assertEqual(email_tags.mention_context('<p>No mention here.</p>', 'bob'), 'No mention here.')
        self.assertEqual(str(email_tags.highlight_mention('<x> @bob', 'bob')), '&lt;x&gt; <strong>@bob</strong>')
        self.assertEqual(email_tags.email_snippet('<p>a&amp;b</p><p>c</p>'), 'a&b c')


class EmailPreviewPageTest(OSQATestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user('admin', is_superuser=True, is_staff=True)

    def test_staff_only(self):
        url = reverse('admin_email_previews')
        one = reverse('admin_email_preview', kwargs={'kind': 'new-answer'})
        member = self.create_user('member')
        for path in (url, one, one + '?format=html', one + '?format=text'):
            self.client.logout()
            self.assertEqual(self.client.get(path).status_code, 401, path)
            self.login(member)
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.login(self.create_user('moderator', is_staff=True))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(one).status_code, 200)

    def test_lists_and_renders_every_kind(self):
        self.login(self.admin)
        page = self.client.get(reverse('admin_email_previews'))
        self.assertContains(page, 'Email previews')
        self.assertContains(page, 'href="%s"' % reverse('admin_email_previews'))  # in the admin menu
        for kind, (name, audience, template, sample) in email_samples.KINDS.items():
            with self.subTest(kind=kind):
                url = reverse('admin_email_preview', kwargs={'kind': kind})
                self.assertContains(page, 'href="%s"' % url)
                self.assertContains(page, str(name))
                preview = self.client.get(url)
                email = email_samples.render(kind, self.admin)
                self.assertContains(preview, '<iframe class="email-preview-frame" src="?format=html"')
                self.assertContains(preview, template)
                self.assertContains(preview, 'email-preview-subject')
                html = self.client.get(url + '?format=html')
                self.assertEqual(html['Content-Type'], 'text/html; charset=utf-8')
                self.assertTrue(html.content.decode().startswith('<!DOCTYPE html>'))
                self.assertEqual(button(html.content.decode()), button(email['html']))
                text = self.client.get(url + '?format=text')
                self.assertEqual(text['Content-Type'], 'text/plain; charset=utf-8')
                # Unsubscribe tokens are signed with the current second; compare without them.
                no_tokens = lambda body: re.sub(r'/unsubscribe/[\w:.-]+/', '/unsubscribe/TOKEN/', body)
                self.assertEqual(no_tokens(text.content.decode()), no_tokens(email['text']))
        self.assertEqual(self.sent_mail, [])

    def test_unknown_kind(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse('admin_email_preview', kwargs={'kind': 'nope'})).status_code, 404)
