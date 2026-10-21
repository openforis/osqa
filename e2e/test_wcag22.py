"""WCAG 2.2 AA checks that axe-core can't make by itself, measured in the
browser on the main pages and the newer interface (post editor, search
filters, live banner, suggested edits, theme and shortcuts, two-step
verification, account pages, API pages, health dashboard, push switch,
moderation inbox), on a desktop and a phone, in light and dark mode:

- 2.5.8 Target Size (Minimum): every control is at least 24 x 24 CSS px, or
  far enough from the others (the 24 px circle test of the spacing
  exception); links in a sentence are exempt;
- 2.4.11 Focus Not Obscured and 2.4.7 Focus Visible: Tab through the page;
  each focused element is not entirely covered (fixed banners, sticky bars)
  and looks different when focused, an outline having 3:1 contrast against
  what is behind it (1.4.11);
- 1.4.10 Reflow: no sideways scrolling at 320 CSS px wide (a 1280 px window
  at 400%) nor at 640 px (200%);
- 1.4.12 Text Spacing: with the spacing of the criterion forced on every
  element, no text is newly clipped and phones still don't scroll sideways;
- dialogs and menus: the focus goes in, Escape closes them and the focus
  comes back to the control that opened them; Show in the live banner moves
  the focus to the new post;
- 2.5.7 Dragging Movements: images dropped on the editor can also be chosen
  with a button; nothing on the pages needs dragging;
- 3.3.7 Redundant Entry, 3.3.8 Accessible Authentication: what was typed
  stays after an error, sign-in fields allow pasting and password managers,
  codes take one-time-code autofill;
- 3.2.6 Consistent Help: the help links are in the same order everywhere;
- 2.3.3 / reduced motion: with prefers-reduced-motion nothing animates;
- axe-core with its WCAG 2.2 rules, and one h1 per page.
"""
import re

from django.test import override_settings
from django.urls import reverse

from forum.utils import push

from .base import E2ETestCase, PASSWORD
from . import test_accessibility  # not its class: the test runner would run its tests here too

PUBLIC_KEY, PRIVATE_KEY = push.generate_keys()
VIEWS = (('desktop', False), ('desktop', True), ('mobile', False), ('mobile', True))

# Every control a pointer can hit, as the target size criterion counts them.
TARGETS = '''() => {
    const SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], ' +
        '[role=tab], [role=menuitem], [role=menuitemradio], [role=option], [role=switch], [role=checkbox], ' +
        '[role=radio], [role=link], [tabindex="0"]';
    const describe = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '') +
        ' "' + (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().slice(0, 30) + '"';
    const words = /[\\p{L}\\p{N}]{2,}/u;
    // A link in a sentence: its block has words outside the links and buttons.
    const inSentence = el => {
        if (el.tagName !== 'A' || !getComputedStyle(el).display.startsWith('inline')) return false;
        let block = el.parentElement;
        while (block && getComputedStyle(block).display.startsWith('inline')) block = block.parentElement;
        if (!block) return false;
        const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (node.parentElement.closest('a, button, [role=button]') || !words.test(node.textContent)) continue;
            if (node.parentElement.checkVisibility()) return true;
        }
        return false;
    };
    const area = el => {
        // A checkbox or radio button is also hit through its label.
        let r = el.getBoundingClientRect();
        let box = {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
        if (el.labels && /^(checkbox|radio)$/.test(el.type)) {
            for (const label of el.labels) {
                const l = label.getBoundingClientRect();
                if (!l.width) continue;
                box = {left: Math.min(box.left, l.left), top: Math.min(box.top, l.top),
                       right: Math.max(box.right, l.right), bottom: Math.max(box.bottom, l.bottom)};
            }
        }
        return box;
    };
    const targets = [];
    const modal = document.querySelector('dialog:modal');  // the rest of the page is inert
    for (const el of document.querySelectorAll(SELECTOR)) {
        if (modal && !modal.contains(el)) continue;
        if (el.disabled || el.closest('[inert], [aria-hidden=true], .visually-hidden, .post-text, .wmd-preview')) continue;
        if (!el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2 || r.bottom + scrollY < 0 || r.right + scrollX < 0) continue;
        if (inSentence(el)) continue;
        const box = area(el);
        targets.push({el, box, small: box.right - box.left < 23.5 || box.bottom - box.top < 23.5});
    }
    const centre = b => [(b.left + b.right) / 2, (b.top + b.bottom) / 2];
    const distance = (p, b) => Math.hypot(Math.max(b.left - p[0], 0, p[0] - b.right), Math.max(b.top - p[1], 0, p[1] - b.bottom));
    const problems = [];
    for (const t of targets.filter(t => t.small)) {
        const c = centre(t.box);
        const near = targets.find(o => o !== t && !o.el.contains(t.el) && !t.el.contains(o.el) &&
            (distance(c, o.box) < 11.99 || (o.small && Math.hypot(c[0] - centre(o.box)[0], c[1] - centre(o.box)[1]) < 23.99)));
        if (near) problems.push(describe(t.el) + ' ' + Math.round(t.box.right - t.box.left) + 'x' +
            Math.round(t.box.bottom - t.box.top) + ', too close to ' + describe(near.el));
    }
    return problems;
}'''

# The focused element: whether something else covers all of it, and its look.
FOCUSED = '''() => {
    const el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return null;
    window.__wcagFocused = window.__wcagFocused || [];
    const describe = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
        (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).join('.') : '') +
        ' "' + (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 30) + '"';
    let shown = el;
    let r = el.getBoundingClientRect();
    if ((r.width < 2 || r.height < 2) && el.labels && el.labels.length) {
        shown = el.labels[0];
        r = shown.getBoundingClientRect();
    }
    const x1 = Math.max(r.left, 0), y1 = Math.max(r.top, 0);
    const x2 = Math.min(r.right, innerWidth), y2 = Math.min(r.bottom, innerHeight);
    const result = {what: describe(el), index: window.__wcagFocused.length};
    window.__wcagFocused.push(el);
    if (r.width < 2 || r.height < 2 || x2 <= x1 || y2 <= y1) {
        result.unseen = true;
        return result;
    }
    let free = 0, cover = null;
    for (let i = 1; i < 6; i++) for (let j = 1; j < 4; j++) {
        const x = x1 + (x2 - x1) * i / 6, y = y1 + (y2 - y1) * j / 4;
        const hit = document.elementFromPoint(x, y);
        if (!hit || hit === shown || shown.contains(hit) || hit.contains(shown) || el.contains(hit)) free++;
        else cover = cover || hit;
    }
    if (!free) result.coveredBy = describe(cover.closest('[id]') || cover);
    return result;
}'''

STYLE_OF = '''(el) => {
    const parts = [];
    for (let e = el, n = 0; e && n < 3; e = e.parentElement, n++) {
        const s = getComputedStyle(e);
        parts.push([s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderTopColor,
                    s.borderBottomColor, s.borderBottomWidth, s.backgroundColor, s.color, s.textDecorationLine].join('|'));
    }
    for (const label of el.labels || []) {
        const s = getComputedStyle(label);
        parts.push([s.outlineStyle, s.outlineWidth, s.boxShadow, s.backgroundColor].join('|'));
    }
    return parts.join('/');
}'''

# The focus indicator: the outline of the focused element (its colour
# blended over what is behind it) or, when that is faint, its border (a
# field's border turning blue), each against the colour behind it.
OUTLINE = '''(el) => {
    const s = getComputedStyle(el);
    if (s.outlineStyle === 'none' || parseFloat(s.outlineWidth) === 0) return null;
    const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return m.length > 3 ? m : m.concat([1]); };
    let behind = null;
    const inside = parseFloat(s.outlineOffset) + parseFloat(s.outlineWidth) <= 0;
    for (let e = inside ? el : el.parentElement; e; e = e.parentElement) {
        const c = parse(getComputedStyle(e).backgroundColor);
        if (c[3] > 0.5) { behind = c; break; }
    }
    if (!behind) behind = parse(getComputedStyle(document.body).backgroundColor);
    const over = c => c.slice(0, 3).map((v, i) => v * c[3] + behind[i] * (1 - c[3]));
    const lum = c => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
                       return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
    const ratio = c => { const a = lum(over(parse(c))), b = lum(behind.slice(0, 3));
                         return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); };
    return {ratio: Math.max(ratio(s.outlineColor), /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && parseFloat(s.borderBottomWidth) >= 1 ? ratio(s.borderBottomColor) : 0),
            color: s.outlineColor, behind: 'rgb(' + behind.slice(0, 3).map(Math.round).join(', ') + ')'};
}'''

# Elements that hide part of their text (overflow hidden or clip).
CLIPPED = '''(mark) => {
    const found = [];
    for (const el of document.querySelectorAll('body *')) {
        const s = getComputedStyle(el);
        const hidesX = /hidden|clip/.test(s.overflowX), hidesY = /hidden|clip/.test(s.overflowY);
        if (!hidesX && !hidesY) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 3 || r.height < 3 || !el.checkVisibility() || !(el.innerText || '').trim()) continue;
        if (s.webkitLineClamp && s.webkitLineClamp !== 'none') continue;  // an excerpt, cut on purpose
        const clips = (hidesY && el.scrollHeight > el.clientHeight + 2) || (hidesX && el.scrollWidth > el.clientWidth + 2);
        if (!clips) continue;
        if (mark) { el.setAttribute('data-wcag-clipped', ''); continue; }
        if (el.hasAttribute('data-wcag-clipped')) continue;
        found.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
            (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '') +
            ' "' + el.innerText.trim().slice(0, 40) + '" (' + el.scrollWidth + 'x' + el.scrollHeight + ' in ' +
            el.clientWidth + 'x' + el.clientHeight + ')');
    }
    return found;
}'''

# The text spacing of 1.4.12, on every element.
TEXT_SPACING = '''* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p { margin-bottom: 2em !important; }'''

MOVING = '''() => [...document.querySelectorAll('body *')].filter(el => {
    const s = getComputedStyle(el);
    return (s.animationName !== 'none' && parseFloat(s.animationDuration) > 0) ||
        s.transitionDuration.split(',').some(d => parseFloat(d) > 0);
}).slice(0, 5).map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).trim())'''


@override_settings(VAPID_PUBLIC_KEY=PUBLIC_KEY, VAPID_PRIVATE_KEY=PRIVATE_KEY, VAPID_SUBJECT='mailto:admin@example.org')
class Wcag22Test(E2ETestCase):
    def setUp(self):
        super().setUp()
        from forum.actions import AcceptAnswerAction, FlagAction, ReportAction
        from forum.models import ModerationReport, Question
        from forum.utils import suggested_edits
        self.admin = self.create_user('admin', reputation=1000, is_staff=True, is_superuser=True)
        self.alice = self.create_user('alice', reputation=500)
        self.bob = self.create_user('bob', reputation=150)
        self.sam = self.create_user('sam', reputation=40)
        self.rita = self.create_user('rita', reputation=2500)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?',
                                             tags='collect export csv')
        self.answer = self.create_answer(self.bob, self.question,
                                         'Use the **CSV export** in the Collect designer:\n\n```\nFile > Export\n```')
        self.create_comment(self.alice, self.answer, 'Thanks, @bob, that worked for me.')
        self.create_comment(self.bob, self.question, 'Which version of Collect do you use?')
        # Versions (forum/utils/post_versions.py): chips, the outdated notice and, on
        # alice's own answer, "Still works in 4.1".
        from forum.models import NodeVersion, Tag
        from forum.utils import tags as tagtools
        collect = Tag.objects.get(name='collect')
        old = tagtools.add_version(collect, '3.26', self.admin, '127.0.0.1')
        tagtools.add_version(collect, '4.1', self.admin, '127.0.0.1', current=True)
        own = self.create_answer(self.alice, self.question, 'For Collect 3.26: use **Tools > Export data**.')
        for answer in (self.answer, own):
            NodeVersion.objects.create(node=answer, tag=collect, version=old)
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=self.answer, ip='127.0.0.1').save()
        for i in range(12):
            Question(author=self.bob, title='Filler question number %d about export' % i,
                     body='Body of filler question %d, long enough.' % i, tagnames='export').save()
        # "Questions for you": alice answers well in export, one filler question was suggested to her.
        from forum.models import AnswerRequest, Tag, TagExpertise
        TagExpertise.objects.create(user=self.alice, tag=Tag.objects.get(name='export'), score=9, answers=3)
        AnswerRequest.objects.create(question=Question.objects.get(title='Filler question number 0 about export'),
                                     user=self.alice, tag_name='export', tag_answers=3, score=9)
        suggested_edits.create(self.sam, self.answer, {'summary': 'Added the menu path',
                                                       'text': self.answer.body + '\n\nThen choose CSV.'})
        FlagAction(user=self.alice, node=self.answer, extra='Advertising', ip='127.0.0.1').save()
        self._as_request(self.bob)
        ReportAction(user=self.bob, ip='127.0.0.1').save(data={'reported': self.sam, 'publicmsg': 'Spam links'})
        ModerationReport.objects.create(node=self.question, source='ai', verdict='spam', confidence=0.9,
                                        reason='Advertises a product.')

    # -- the pages -------------------------------------------------------------

    def public_pages(self):
        return ['/', '/questions/', self.question.get_absolute_url(), '/tags/', '/users/', '/badges/',
                self.alice.get_profile_url(), '/search/?q=export&tags=collect', '/api/', '/account/signin/',
                '/account/local/register/', '/account/tempsignin/', reverse('markdown_help')]

    def member_pages(self, user):
        return [self.question.get_absolute_url(), '/questions/ask/', '/search/?q=export&tags=collect&status=answered',
                reverse('notifications'), reverse('questions_for_you'), user.get_user_subscriptions_url(),
                reverse('user_preferences', kwargs={'id': user.id, 'slug': user.username}),
                reverse('edit_user', kwargs={'id': user.id, 'slug': user.username}),
                reverse('user_authsettings', kwargs={'id': user.id}),
                reverse('user_security', kwargs={'id': user.id}), reverse('two_factor_setup'),
                reverse('user_account_data', kwargs={'id': user.id}),
                reverse('user_api_tokens', kwargs={'id': user.id}), '/logout/',
                reverse('auth_confirm_identity') + '?next=' + reverse('user_security', kwargs={'id': user.id})]

    def staff_pages(self):
        return [reverse('admin_index'), reverse('admin_moderation'), reverse('suggested_edits'),
                reverse('admin_support'), '/admin/settings/basic/', '/admin/settings/extkeys/',
                '/admin/settings/appearance/', '/admin/search/?q=logo', reverse('tag_edit', kwargs={'tag': 'collect'})]

    def all_pages(self):
        return ([(None, p) for p in self.public_pages()] + [(self.alice, p) for p in self.member_pages(self.alice)] +
                [(self.admin, p) for p in self.staff_pages()])

    def each_page(self, views=VIEWS, pages=None, **options):
        """Yields (page, path, where) for every page as its user, in every view."""
        for device, dark in views:
            browsers = {}
            for user, path in pages or self.all_pages():
                if user not in browsers:
                    browsers[user] = self.open(user, device=device, dark=dark, **options)
                page = browsers[user]
                self.visit(page, path)
                yield page, path, '%s (%s%s)' % (path, device, ', dark' if dark else '')

    def axe22(self, page):
        return test_accessibility.AccessibilityTest.axe(self, page, tags=test_accessibility.WCAG_TAGS + ['wcag22a', 'wcag22aa'])

    def report(self, failures, what):
        if failures:
            self.fail('%d %s:\n\n%s' % (len(failures), what, '\n'.join(failures)))

    # -- 2.5.8 Target Size (Minimum) ---------------------------------------------

    def test_target_size(self):
        failures = []
        for page, path, where in self.each_page(views=(('desktop', False), ('mobile', True))):
            failures += ['%s: %s' % (where, p) for p in page.evaluate(TARGETS)]
        self.report(failures, 'targets smaller than 24x24 px without the spacing (WCAG 2.5.8)')

    def test_target_size_of_open_widgets(self):
        """The editor's language menu and a mention list, the tag chips,
        the phone's search filters and the post menu."""
        failures = []
        for device, dark in (('desktop', False), ('mobile', True)):
            where = '(%s)' % device
            page = self.open(self.alice, device=device, dark=dark)
            self.visit(page, '/questions/ask/')
            page.locator('#id_tags').press_sequentially('collect export ')
            page.click('.editor-button[data-command=codeblock]')
            page.wait_for_selector('#editor-languages:not([hidden])')
            failures += ['ask, language menu %s: %s' % (where, p) for p in page.evaluate(TARGETS)]
            page.keyboard.press('Escape')
            page.locator('#editor').press_sequentially('Hello @bo')
            page.wait_for_selector('#mention-suggestions [role=option]')
            failures += ['ask, mentions %s: %s' % (where, p) for p in page.evaluate(TARGETS)]
            self.visit(page, self.question.get_absolute_url())
            page.click('#node-%d-menu-trigger' % self.answer.id)
            failures += ['question, post menu %s: %s' % (where, p) for p in page.evaluate(TARGETS)]
            if device == 'mobile':
                self.visit(page, '/search/?q=export&tags=collect')
                page.click('.search-filters-toggle')
                page.wait_for_selector('#search-filters-dialog[open]')
                failures += ['search, filters dialog %s: %s' % (where, p) for p in page.evaluate(TARGETS)]
        self.report(failures, 'targets smaller than 24x24 px without the spacing (WCAG 2.5.8)')

    # -- 2.4.11 Focus Not Obscured, 2.4.7 Focus Visible ----------------------------

    def tab_through(self, page, where, limit=90):
        """Tabs from the top of the page and checks each focused element."""
        failures = []
        page.evaluate('() => { window.__wcagFocused = []; document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); }')
        seen = []
        styles = []
        for _ in range(limit):
            page.keyboard.press('Tab')
            info = page.evaluate(FOCUSED)
            if info is None:
                break
            if info['what'] in seen[:1] or (seen and info['what'] == seen[-1] and len(seen) > 3):
                break
            seen.append(info['what'])
            handle = page.evaluate_handle('() => document.activeElement')
            styles.append((info, page.evaluate(STYLE_OF, handle), page.evaluate(OUTLINE, handle)))
            if info.get('unseen'):
                failures.append('%s: %s is focused but not on the screen' % (where, info['what']))
            elif info.get('coveredBy'):
                failures.append('%s: %s is focused but covered by %s' % (where, info['what'], info['coveredBy']))
        page.evaluate('() => document.activeElement && document.activeElement.blur()')
        page.mouse.move(0, 0)
        for info, focused, outline in styles:
            handle = page.evaluate_handle('i => window.__wcagFocused[i]', info['index'])
            if not page.evaluate('el => el.isConnected', handle):
                continue
            if page.evaluate(STYLE_OF, handle) == focused and not info.get('unseen'):
                failures.append('%s: %s looks the same with and without the focus' % (where, info['what']))
            elif outline and outline['ratio'] < 3:
                failures.append('%s: the focus outline of %s (%s on %s) has a contrast of %.1f:1' % (
                    where, info['what'], outline['color'], outline['behind'], outline['ratio']))
        return failures

    def focus_at_edge(self, page, where, scope='#room', edge='bottom'):
        """The worst case for a bar at an edge of the screen (or of a scrolling
        dialog): each control scrolled to that edge (by the mouse wheel, say),
        then focused as Tab would (scrolled only if the browser thinks it's
        hidden)."""
        failures = []
        controls = 'a[href], button, input:not([type=hidden]), select, textarea, summary'
        count = page.evaluate('([scope, controls]) => document.querySelector(scope).querySelectorAll(controls).length',
                              [scope, controls])
        for index in range(0, count, max(1, count // 40)):
            placed = page.evaluate('''([scope, controls, i, edge]) => {
                const el = document.querySelector(scope).querySelectorAll(controls)[i];
                if (!el.checkVisibility() || el.getBoundingClientRect().height < 2) return false;
                let box = el.parentElement;
                while (box && !(/(auto|scroll)/.test(getComputedStyle(box).overflowY) && box.scrollHeight > box.clientHeight)) {
                    box = box.parentElement;
                }
                const r = el.getBoundingClientRect();
                if (box && box !== document.documentElement && box !== document.body) {
                    const b = box.getBoundingClientRect();
                    box.scrollTop += edge === 'top' ? r.top - b.top - 2 : r.bottom - b.bottom + 2;
                } else {
                    window.scrollBy(0, edge === 'top' ? r.top - 2 : r.bottom - innerHeight + 2);
                }
                el.focus();
                return document.activeElement === el;
            }''', [scope, controls, index, edge])
            if not placed:
                continue
            info = page.evaluate(FOCUSED)
            if info and info.get('coveredBy'):
                failures.append('%s: %s at the %s of the screen is focused but covered by %s' % (
                    where, info['what'], edge, info['coveredBy']))
        return failures

    def test_focus_visible_and_not_obscured(self):
        failures = []
        for page, path, where in self.each_page():
            failures += self.tab_through(page, where)
        self.report(failures, 'focus problems (WCAG 2.4.7, 2.4.11, 1.4.11)')

    def test_focus_not_hidden_by_the_live_banner_or_messages(self):
        """With the "1 new answer · Show" banner at the bottom of the screen,
        and on a phone with the message bar at the bottom, Tab never leaves
        the focus under them; Show moves the focus to the new answer."""
        failures = []
        for device, dark in (('desktop', False), ('mobile', True)):
            where = 'question page with the live banner (%s)' % device
            reader = self.open(self.rita, device=device, dark=dark)
            reader.add_init_script('window.osqaLiveInterval = 0.3;')
            self.visit(reader, self.question.get_absolute_url())
            answer = self.create_answer(self.sam, self.question, 'Another way: the export button on the data page.')
            reader.wait_for_selector('#live-banner .live-show')
            failures += self.tab_through(reader, where, limit=140)
            failures += self.focus_at_edge(reader, where)
            reader.click('#live-banner .live-show')
            reader.wait_for_selector('#answer-container-%d' % answer.id)
            reader.wait_for_function('id => document.activeElement && document.activeElement.id === "answer-container-" + id',
                                     arg=answer.id)
            self.check_page(reader)
            # A message at the bottom of a phone screen (the sticky bar).
            page = self.open(self.alice, device=device, dark=dark)
            self.visit(page, self.question.get_absolute_url())
            page.evaluate("""() => { jQuery('.notify').prepend('<p class="darkred">A message for the test</p>');
                                     notify.show(); }""")
            page.wait_for_function("() => !jQuery(':animated').length")
            failures += self.tab_through(page, 'question page with a message (%s)' % device, limit=140)
            failures += self.focus_at_edge(page, 'question page with a message (%s)' % device)
            self.check_page(page)
        self.report(failures, 'focus problems (WCAG 2.4.11)')

    # -- 1.4.10 Reflow, 1.4.12 Text Spacing -----------------------------------------

    def test_reflow_at_320_and_640_px(self):
        failures = []
        for width, height, device in ((320, 640, 'mobile'), (640, 450, 'desktop')):
            for page, path, where in self.each_page(views=((device, False),), viewport={'width': width, 'height': height}):
                overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
                if overflow > 1:
                    from .base import WIDER_THAN_SCREEN
                    failures.append('%s at %dpx scrolls sideways by %dpx: %s' % (
                        path, width, overflow, ', '.join(page.evaluate(WIDER_THAN_SCREEN))))
        self.report(failures, 'pages that need scrolling in two directions (WCAG 1.4.10)')

    def test_text_spacing(self):
        failures = []
        for page, path, where in self.each_page(views=(('desktop', False), ('mobile', False))):
            page.evaluate(CLIPPED, True)
            page.add_style_tag(content=TEXT_SPACING)
            page.wait_for_timeout(50)
            failures += ['%s: %s' % (where, p) for p in page.evaluate(CLIPPED, False)]
            if page.device == 'mobile':
                overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
                if overflow > 1:
                    failures.append('%s scrolls sideways by %dpx with the text spacing' % (where, overflow))
        self.report(failures, 'texts cut off with more text spacing (WCAG 1.4.12)')

    # -- dialogs, menus and the live banner ------------------------------------------

    def assert_closes_with_escape(self, page, opener, is_open, where):
        """Opens with `opener` (a selector to click, or a function), checks the
        focus went in, closes with Escape and checks it came back."""
        if callable(opener):
            opener()
        else:
            page.locator(opener).focus()
            page.keyboard.press('Enter')
        page.wait_for_function(is_open)
        inside = page.evaluate('''() => { const d = document.activeElement;
            return !!(d && d.closest('dialog[open], [role=menu]:not([hidden]), details[open]')); }''')
        self.assertTrue(inside, '%s: the focus did not move into it' % where)
        before = None if callable(opener) else opener
        page.keyboard.press('Escape')
        page.wait_for_function('(f) => !(%s)()' % is_open, arg=None)
        if before:
            self.assertTrue(page.evaluate('s => document.activeElement === document.querySelector(s)', before),
                            '%s: the focus did not come back to %s but went to %s' % (
                                where, before, page.evaluate('() => document.activeElement.outerHTML.slice(0, 120)')))

    def test_dialogs_and_menus_close_with_escape_and_return_the_focus(self):
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(self.alice, device=device, dark=dark)
            self.visit(page, '/questions/ask/')
            self.assert_closes_with_escape(page, '.editor-button[data-command=link]',
                                           '() => document.getElementById("editor-link-dialog").matches(":modal")',
                                           'link dialog')
            self.assert_closes_with_escape(page, '.editor-button[data-command=image]',
                                           '() => document.getElementById("editor-image-dialog").open', 'image dialog')
            self.assert_closes_with_escape(page, '.editor-button[data-command=codeblock]',
                                           '() => !document.getElementById("editor-languages").hidden', 'language menu')
            # The mention list: Escape closes it, the focus stays in the text.
            page.locator('#editor').press_sequentially('Hello @bo')
            page.wait_for_selector('#mention-suggestions [role=option]')
            self.assertEqual(page.locator('#editor').get_attribute('aria-controls'), 'mention-suggestions')
            page.keyboard.press('Escape')
            self.assertEqual(page.locator('#mention-suggestions').count(), 0)
            self.assertEqual(page.evaluate('() => document.activeElement.id'), 'editor')

            # The keyboard shortcuts list, opened with "?" from a link.
            self.visit(page, '/questions/')
            page.locator('#nav_questions').focus()
            self.assert_closes_with_escape(page, lambda page=page: page.keyboard.press('?'),
                                           '() => document.getElementById("shortcuts-dialog").open', 'shortcuts')
            self.assertEqual(page.evaluate('() => document.activeElement.id'), 'nav_questions')

            # The theme menu in the header.
            self.assert_closes_with_escape(page, '.theme-menu > summary',
                                           '() => document.querySelector(".theme-menu").open', 'theme menu')

            if device == 'mobile':
                self.visit(page, '/search/?q=export&tags=collect')
                self.assert_closes_with_escape(page, '.search-filters-toggle',
                                               '() => document.getElementById("search-filters-dialog").open',
                                               'search filters')
                # Nothing in it hides under its sticky heading.
                page.click('.search-filters-toggle')
                page.wait_for_selector('#search-filters-dialog[open]')
                problems = self.focus_at_edge(page, 'search filters dialog', '#search-filters-dialog', 'top')
                self.assertEqual(problems, [], '\n'.join(problems))
                page.keyboard.press('Escape')
                # Its close button gives the focus back too.
                page.click('.search-filters-toggle')
                page.wait_for_selector('#search-filters-dialog[open]')
                page.locator('#search-filters-dialog .search-filters-close').click()
                self.assertTrue(page.evaluate('() => document.activeElement.classList.contains("search-filters-toggle")'))

            moderator = self.open(self.admin, device=device, dark=dark)
            self.visit(moderator, reverse('admin_moderation'))
            button = moderator.locator('[data-spam-dialog]').first
            button.evaluate('b => b.id = b.id || "wcag-spam-opener"')
            selector = '#' + button.get_attribute('id')
            self.assert_closes_with_escape(moderator, selector, '() => !!document.querySelector("dialog.mod-dialog[open]")',
                                           'spam dialog')
            self.check_page(page)
            self.check_page(moderator)

    def test_editor_tooltips_stay_on_hover_and_close_with_escape(self):
        """1.4.13 Content on Hover or Focus: the pointer can move onto a
        toolbar tip, and Escape hides it while the focus stays in the text."""
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        page.locator('#editor').focus()
        page.hover('.editor-button[data-command=bold]')
        tip = page.locator('#editor-tooltip')
        tip.wait_for(state='visible')
        box = tip.bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=8)
        self.assertTrue(tip.is_visible(), 'the tip disappears when the pointer moves onto it')
        page.keyboard.press('Escape')
        self.assertFalse(tip.is_visible())
        self.assertEqual(page.evaluate('() => document.activeElement.id'), 'editor')
        self.check_page(page)

    def test_choices_made_with_the_keyboard_dont_reload_the_page(self):
        """3.2.2 On Input: going through the search filters and the footer's
        language list with the arrow keys doesn't submit at each step; the
        pointer still applies a choice at once."""
        page = self.open(self.alice)
        self.visit(page, '/search/?q=export')
        url = page.url
        page.locator('#search-filters input[name=status]').first.focus()
        page.keyboard.press('ArrowDown')
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(300)
        self.assertEqual(page.url, url)
        self.assertTrue(page.locator('#search-filters input[name=status]').nth(2).is_checked())
        with page.expect_navigation():
            page.get_by_role('button', name='Apply filters').click()
        self.assertIn('status=', page.url)
        self.check_page(page)
        with page.expect_navigation():
            page.locator('#search-filters label.search-filter-option').first.click()
        self.check_page(page)

        language = page.locator('#language-select')
        language.focus()
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate('document.documentElement.lang'), 'en')
        with page.expect_navigation():
            page.keyboard.press('Enter')
        self.assertNotEqual(page.evaluate('document.documentElement.lang'), 'en')
        self.check_page(page)

    # -- 2.5.7 Dragging Movements ------------------------------------------------------

    def test_no_dragging_needed(self):
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        # Images can be dropped on the text, or chosen in the image dialog.
        page.click('.editor-button[data-command=image]')
        self.assertTrue(page.locator('#editor-image-dialog input[type=file]').is_visible())
        page.keyboard.press('Escape')
        for user, path in self.all_pages():
            browser = self.open(user)
            self.visit(browser, path)
            self.assertEqual(browser.locator('[draggable=true]').count(), 0, path)

    # -- 3.3.7 Redundant Entry, 3.3.8 Accessible Authentication -------------------------

    def test_authentication_fields_allow_paste_and_autofill(self):
        pages = [(None, '/account/signin/'), (None, '/account/local/register/'), (None, '/account/tempsignin/'),
                 (self.alice, reverse('user_authsettings', kwargs={'id': self.alice.id})),
                 (self.alice, reverse('user_security', kwargs={'id': self.alice.id})),
                 (self.alice, reverse('two_factor_setup')),
                 (self.alice, reverse('user_account_data', kwargs={'id': self.alice.id})),
                 (self.alice, reverse('auth_confirm_identity') + '?next=/')]
        failures = []
        for page, path, where in self.each_page(views=(('desktop', False),), pages=pages):
            page.evaluate('() => document.querySelectorAll("details").forEach(d => d.open = true)')
            for field in page.evaluate('''() => [...document.querySelectorAll(
                    'input[type=password], input[name=code], input[name=username], input[type=email], input[autocomplete=one-time-code]')]
                    .filter(i => i.checkVisibility()).map(i => {
                const event = new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: new DataTransfer()});
                i.dispatchEvent(event);
                return {name: i.name || i.id, type: i.type, autocomplete: i.getAttribute('autocomplete') || '',
                        pasteBlocked: event.defaultPrevented};
            })'''):
                if field['pasteBlocked']:
                    failures.append('%s: pasting into %s is blocked' % (where, field['name']))
                expected = {'password': ('current-password', 'new-password'), 'code': ('one-time-code',),
                            'username': ('username',), 'email': ('email', 'username')}
                kind = 'password' if field['type'] == 'password' else (
                    'code' if field['name'] == 'code' or field['autocomplete'] == 'one-time-code' else
                    ('email' if field['type'] == 'email' else 'username'))
                # "username webauthn": the passkey suggestions of the sign-in page.
                if not set(field['autocomplete'].split()) & set(expected[kind]):
                    failures.append('%s: %s has autocomplete="%s", not %s' % (
                        where, field['name'], field['autocomplete'], ' or '.join(expected[kind])))
        self.report(failures, 'sign-in fields that get in the way (WCAG 3.3.8)')

    def test_two_step_code_page(self):
        """The code page after the password: one-time-code autofill, paste,
        and the username isn't asked again."""
        from forum.models import TOTPDevice
        from forum.utils import two_factor
        TOTPDevice.objects.create(user=self.bob, secret=two_factor.encrypt_secret(two_factor.new_secret()),
                                  confirmed_at='2026-01-01 00:00')
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.open(device=device, dark=dark)
            self.visit(page, '/account/signin/')
            page.fill('#id_username', 'bob')
            page.fill('#id_password', PASSWORD)
            page.click('#blogin')
            page.wait_for_url('**/account/two-step/')
            self.check_page(page)
            code = page.locator('#id_code')
            self.assertEqual(code.get_attribute('autocomplete'), 'one-time-code')
            self.assertFalse(code.evaluate('''i => { const e = new ClipboardEvent('paste', {bubbles: true, cancelable: true,
                clipboardData: new DataTransfer()}); i.dispatchEvent(e); return e.defaultPrevented; }'''))
            self.assertEqual(page.locator('input[name=username]:visible, input[type=password]:visible').count(), 0)
            failures = self.axe22(page)
            failures += self.tab_through(page, 'two-step page (%s)' % device)
            failures += page.evaluate(TARGETS)
            self.report(failures, 'problems on the two-step page')

    def test_what_was_typed_stays_after_an_error(self):
        page = self.open()
        self.visit(page, '/account/local/register/')
        page.fill('#id_username', 'newcomer')
        page.fill('#id_email', 'newcomer@example.com')
        page.fill('#id_password1', 'green-tree-river-7')
        page.fill('#id_password2', 'green-tree-river-8')
        with page.expect_navigation():
            page.click('#bnewaccount')
        self.check_page(page)
        self.assertEqual(page.input_value('#id_username'), 'newcomer')
        self.assertEqual(page.input_value('#id_email'), 'newcomer@example.com')

        # The ask form keeps the title, text and tags after an error.
        page = self.open(self.alice)
        self.visit(page, '/questions/ask/')
        page.fill('#id_title', 'Help')
        page.fill('#editor', 'Some **bold** text.')
        page.locator('#id_tags').press_sequentially('collect ')
        with page.expect_navigation():
            page.click('#fmask input[name=ask]')
        self.check_page(page)
        self.assertEqual(page.input_value('#id_title'), 'Help')
        self.assertIn('Some **bold** text.', page.input_value('#editor'))
        self.assertIn('collect', page.input_value('#id_tags_value'))  # the chips' value

    # -- 3.2.6 Consistent Help -------------------------------------------------------

    def test_help_links_in_the_same_order(self):
        help_words = re.compile(r'^(faq|about|contact|support|help|privacy|api)$', re.I)
        orders = {}
        for page, path, where in self.each_page(views=(('desktop', False), ('mobile', False))):
            if path.startswith('/admin/') or path.startswith('/review/'):
                continue  # the administration has its own layout
            links = [t.strip() for t in page.locator('#roof a, #ground a').all_inner_texts()]
            orders.setdefault(page.device, {})[where] = [t.lower() for t in links if help_words.match(t.strip())]
        failures = []
        for device, found in orders.items():
            first_where, first = next(iter(found.items()))
            self.assertTrue(first, 'no help links on %s' % first_where)
            for where, links in found.items():
                if links != first:
                    failures.append('%s: %s, but %s on %s' % (where, links, first, first_where))
        self.report(failures, 'pages with the help links elsewhere (WCAG 3.2.6)')

    # -- reduced motion, axe-core WCAG 2.2, headings --------------------------------------

    def test_nothing_moves_with_reduced_motion(self):
        failures = []
        for page, path, where in self.each_page(views=(('desktop', False),), reduced_motion='reduce'):
            moving = page.evaluate(MOVING)
            if moving:
                failures.append('%s: %s' % (where, ', '.join(moving)))
        self.report(failures, 'pages that animate with prefers-reduced-motion')

    def test_axe_wcag22_and_headings(self):
        failures = []
        for page, path, where in self.each_page():
            failures += ['%s:\n%s' % (where, v) for v in self.axe22(page)]
            h1 = page.locator('h1:visible').count()
            if h1 != 1:
                failures.append('%s: %d visible h1 headings' % (where, h1))
        self.report(failures, 'accessibility violations (WCAG 2.2 A/AA, axe-core) and heading problems')
