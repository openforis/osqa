"""UI robustness: the layout holds up at the edges.

- Reflow (WCAG 1.4.10): key pages at 320px wide and at 1280px zoomed to 200%
  don't scroll sideways, and their main button can be scrolled into view,
  fully on screen and not covered.
- Tablet (768px) and wide (1920px) screens: the header parts don't overlap,
  the sidebar sits beside or below the content without covering it.
- Long content (a 200-character title without spaces, a 60-character
  username, ten long tags, a huge table, an unbroken URL and long comments)
  stays inside the content column on a desktop and on a phone.
- Keyboard only: Tab reaches "Skip to content" first, then the search box,
  the navigation and the main action, each with a visible focus indicator;
  the dialogs of commands (report, close, delete) keep focus inside, close
  on Escape and give focus back.
- prefers-reduced-motion: no animations or transitions longer than 0.01s,
  and jQuery effects finish at once.
- Print: the question and its answers without the header, navigation,
  sidebar and forms.

Every page is also checked as in all browser tests (no server or JavaScript
errors, no console errors)."""
from forum.actions import AcceptAnswerAction

from .base import E2ETestCase, WIDER_THAN_SCREEN

LONG_TITLE = 'Unbroken' + 'x' * 184 + 'TitleEnd'                      # 200 characters, no spaces
LONG_USERNAME = 'a_very_long_username_of_sixty_characters_for_the_layout_ok60'  # 60 characters
LONG_TAGS = ' '.join('long-tag-name-number-%02d-for-the-layout' % n for n in range(10))
LONG_URL = 'https://example.org/' + 'path-segment/' * 12 + '?query=' + 'x' * 80
LONG_BODY = '''A question with wide content.

%s

| %s |
|%s|
| %s |

```
%s
```
''' % (LONG_URL, ' | '.join('Column header %d' % n for n in range(16)), '---|' * 16,
       ' | '.join('cell_value_%d_without_spaces' % n for n in range(16)), 'x = "%s"' % ('y' * 300))
LONG_COMMENT = 'A long comment with an unbroken word: ' + 'z' * 220 + ' and ' + LONG_URL

# Elements inside `selector` that stick out of it (not inside something
# that scrolls or clips by itself, such as a code block or a table wrapper).
OUTSIDE = '''(selector) => {
    const box = document.querySelector(selector).getBoundingClientRect(), container = document.querySelector(selector);
    const found = [];
    for (const el of container.querySelectorAll('*')) {
        const b = el.getBoundingClientRect();
        if (b.width === 0 || b.height === 0) continue;
        if (b.right <= box.right + 1 && b.left >= box.left - 1) continue;
        let parent = el.parentElement, contained = false;
        for (; parent && parent !== container; parent = parent.parentElement) {
            if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowX)) { contained = true; break; }
        }
        if (contained || found.some(f => f.contains(el))) continue;
        found.push(el);
    }
    // Text overflowing its own element (white-space: nowrap, a long word).
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT), range = document.createRange();
    while (walker.nextNode()) {
        range.selectNodeContents(walker.currentNode);
        const b = range.getBoundingClientRect(), el = walker.currentNode.parentElement;
        if (b.width === 0 || (b.right <= box.right + 1 && b.left >= box.left - 1) || found.some(f => f.contains(el))) continue;
        let parent = el, contained = false;
        for (; parent && parent !== container; parent = parent.parentElement) {
            if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowX)) { contained = true; break; }
        }
        if (!contained) found.push(el);
    }
    return found.slice(0, 5).map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : '') +
        ' (' + Math.round(el.getBoundingClientRect().left) + '..' + Math.round(el.getBoundingClientRect().right) +
        'px in ' + Math.round(box.left) + '..' + Math.round(box.right) + ')');
}'''

# Whether the element is on screen and not covered at its centre.
ON_SCREEN = '''(el) => {
    const b = el.getBoundingClientRect(), w = document.documentElement.clientWidth, h = window.innerHeight;
    const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return {left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: w, height: h,
            covered: !(hit && (hit === el || el.contains(hit) || hit.contains(el))),
            coveredBy: hit ? hit.tagName.toLowerCase() + (hit.id ? '#' + hit.id : '') + (hit.className ? '.' + hit.className : '') : null};
}'''

# What makes focus visible: compared before and while focused.
FOCUS_STYLE = '''(el) => {
    const parts = [el, el.parentElement, el.parentElement && el.parentElement.parentElement].filter(Boolean);
    return parts.map(p => { const s = getComputedStyle(p);
        return [s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 ? s.outlineStyle + s.outlineWidth + s.outlineColor : '',
                s.boxShadow, s.borderTopColor + s.borderBottomColor, s.backgroundColor, s.textDecorationLine].join('|'); });
}'''

DESCRIBE = '''(el) => el === document.body || !el ? 'body' : el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : '')'''

# Animations and transitions longer than 10ms anywhere on the page.
SLOW_MOTION = '''() => {
    const seconds = v => v.split(',').map(t => t.trim().endsWith('ms') ? parseFloat(t) / 1000 : parseFloat(t) || 0);
    const slow = [];
    for (const el of document.querySelectorAll('*')) {
        const s = getComputedStyle(el);
        const transition = Math.max(...seconds(s.transitionDuration).map((d, i) => d + Math.max(0, seconds(s.transitionDelay)[i] || 0)));
        const animation = s.animationName !== 'none' ? Math.max(...seconds(s.animationDuration)) : 0;
        if (transition > 0.011 || animation > 0.011)
            slow.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ' transition ' + transition + 's animation ' + animation + 's');
    }
    return slow.slice(0, 10);
}'''

HEADER_PARTS = ('#logo', '#searchBar', '#top', '#nav')


def intersect(a, b):
    return (a['x'] < b['x'] + b['width'] - 1 and b['x'] < a['x'] + a['width'] - 1 and
            a['y'] < b['y'] + b['height'] - 1 and b['y'] < a['y'] + a['height'] - 1)


class RobustnessTestCase(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=600)
        self.bob = self.create_user('bob', reputation=1300)
        self.mod = self.create_user('moderator', reputation=5000, is_staff=True)
        self.question = self.create_question(self.alice, 'How do I export Collect survey data to CSV?',
                                             tags='collect export')
        self.answer = self.create_answer(self.bob, self.question,
                                         'Use the **CSV export**:\n\n```\nFile > Export > CSV\n```')
        self.create_comment(self.alice, self.answer, 'Thanks, that worked.')
        self._as_request(self.alice)
        AcceptAnswerAction(user=self.alice, node=self.answer, ip='127.0.0.1').save()

    def overflow(self, page):
        return page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')

    def assert_no_sideways_scroll(self, page, where):
        overflow = self.overflow(page)
        if overflow > 1:
            self.fail('%s scrolls sideways by %dpx at %dpx wide; too wide: %s' % (
                where, overflow, page.viewport_size['width'], ', '.join(page.evaluate(WIDER_THAN_SCREEN))))

    def assert_reachable(self, page, selector, where):
        """The element can be scrolled into view, entirely on screen and not covered."""
        element = page.locator(selector).first
        self.assertTrue(element.count(), '%s: no %s' % (where, selector))
        element.scroll_into_view_if_needed()
        box = element.evaluate(ON_SCREEN)
        self.assertGreaterEqual(box['left'], -1, '%s: %s starts off screen (%s)' % (where, selector, box))
        self.assertLessEqual(box['right'], box['width'] + 1, '%s: %s is clipped on the right (%s)' % (where, selector, box))
        self.assertGreaterEqual(box['top'], -1, '%s: %s is above the screen (%s)' % (where, selector, box))
        self.assertLessEqual(box['bottom'], box['height'] + 1, '%s: %s is below the screen (%s)' % (where, selector, box))
        self.assertFalse(box['covered'], '%s: %s is covered by %s' % (where, selector, box['coveredBy']))


class ReflowTest(RobustnessTestCase):
    # (path, user, main action)
    def pages(self):
        return [
            ('/', None, '.app-bar-ask'),
            (self.question.get_absolute_url(), None, '.answer-card .accepted-badge'),
            (self.question.get_absolute_url(), 'alice', '#fmanswer input.submit'),
            ('/questions/ask/', 'alice', '[name=ask][type=submit]'),
            ('/account/signin/', None, '#blogin'),
            ('/account/local/register/', None, '#bnewaccount'),
            ('/tags/', None, '.app-bar-ask'),
            ('/users/', None, '.app-bar-ask'),
            (self.alice.get_profile_url(), None, '.app-bar-ask'),
            ('/search/?q=export', None, '#keywords'),
        ]

    def check_reflow(self, device, **options):
        pages = {}
        for path, username, action in self.pages():
            if username not in pages:
                pages[username] = self.open(getattr(self, username) if username else None, device=device, **options)
            page = pages[username]
            where = '%s (%s)' % (path, username or 'anonymous')
            with self.subTest(page=where):
                self.visit(page, path)
                self.assert_no_sideways_scroll(page, where)
                self.assert_reachable(page, action, where)

    def test_320px_wide(self):
        self.check_reflow('mobile', viewport={'width': 320, 'height': 640})

    def test_1280px_at_200_percent_zoom(self):
        # 200% zoom of a 1280x900 window lays the page out in 640x450 CSS pixels.
        self.check_reflow('desktop', viewport={'width': 640, 'height': 450}, device_scale_factor=2)


class BreakpointTest(RobustnessTestCase):
    PATHS = ('/', 'question', '/tags/', '/users/', 'profile')

    def check_layout(self, width, sidebar_beside):
        page = self.open(self.alice, viewport={'width': width, 'height': 1000})
        for path in self.PATHS:
            path = {'question': self.question.get_absolute_url(), 'profile': self.alice.get_profile_url()}.get(path, path)
            with self.subTest(path=path, width=width):
                self.visit(page, path)
                self.assert_no_sideways_scroll(page, path)
                boxes = {}
                for selector in HEADER_PARTS:
                    locator = page.locator(selector)
                    if locator.count() and locator.is_visible():
                        boxes[selector] = locator.bounding_box()
                self.assertIn('#nav', boxes)
                self.assertIn('#searchBar', boxes)
                parts = sorted(boxes)
                for i, a in enumerate(parts):
                    for b in parts[i + 1:]:
                        self.assertFalse(intersect(boxes[a], boxes[b]), '%s at %dpx: %s %s overlaps %s %s' % (
                            path, width, a, boxes[a], b, boxes[b]))
                for box in boxes.values():
                    self.assertLessEqual(box['x'] + box['width'], width + 1)
                main, sidebar = page.locator('#CALeft'), page.locator('#CARight')
                if main.count() and sidebar.count() and sidebar.is_visible() and sidebar.bounding_box()['height'] > 0:
                    m, s = main.bounding_box(), sidebar.bounding_box()
                    self.assertFalse(intersect(m, s), '%s at %dpx: the sidebar %s covers the content %s' % (
                        path, width, s, m))
                    if sidebar_beside:
                        self.assertGreaterEqual(s['x'], m['x'] + m['width'] - 1,
                                                '%s at %dpx: the sidebar should be right of the content' % (path, width))
                        self.assertLess(s['y'], m['y'] + m['height'])
                    elif s['x'] < m['x'] + m['width'] - 1:
                        self.assertGreaterEqual(s['y'], m['y'] + m['height'] - 1,
                                                '%s at %dpx: the sidebar should be below the content' % (path, width))

    def test_tablet_768px(self):
        self.check_layout(768, sidebar_beside=False)

    def test_wide_1920px(self):
        self.check_layout(1920, sidebar_beside=True)
        # The content keeps a readable width, centred.
        page = self.open(viewport={'width': 1920, 'height': 1000})
        self.visit(page, self.question.get_absolute_url())
        room = page.locator('#room').bounding_box()
        self.assertLessEqual(room['width'], 1400)
        self.assertAlmostEqual(room['x'], 1920 - room['x'] - room['width'], delta=40)


class LongContentTest(RobustnessTestCase):
    def setUp(self):
        super().setUp()
        self.longname = self.create_user(LONG_USERNAME, reputation=150)
        self.long_question = self.create_question(self.longname, LONG_TITLE, tags=LONG_TAGS, body=LONG_BODY)
        self.create_answer(self.alice, self.long_question, 'See ' + LONG_URL + '\n\n' + 'w' * 250)
        self.create_comment(self.longname, self.long_question, LONG_COMMENT)

    def check_columns(self, page, path):
        self.visit(page, path)
        self.assert_no_sideways_scroll(page, path)
        columns = [c for c in ('#CALeft', '#CARight') if page.locator(c).count() and page.locator(c).is_visible()]
        for column in columns or ['#wrapper']:
            outside = page.evaluate(OUTSIDE, column)
            self.assertEqual(outside, [], '%s (%s): content sticks out of %s' % (path, page.device, column))

    def test_long_content_stays_in_its_column(self):
        paths = [self.long_question.get_absolute_url(), '/', '/questions/', '/tags/', '/users/',
                 self.longname.get_profile_url(), '/search/?q=Unbroken']
        for device in ('desktop', 'mobile'):
            page = self.open(self.alice, device=device)
            for path in paths:
                with self.subTest(path=path, device=device):
                    self.check_columns(page, path)
            # The title is all there (wrapped, not cut).
            self.visit(page, self.long_question.get_absolute_url())
            title = page.locator('h1').first
            self.assertIn('TitleEnd', title.inner_text())
            box = title.bounding_box()
            self.assertLessEqual(box['x'] + box['width'], page.viewport_size['width'])


class KeyboardTest(RobustnessTestCase):
    def tab_until(self, page, wanted, limit=60):
        """Presses Tab until each selector in `wanted` had focus. Returns the
        focused elements in order, each with its focus styles."""
        page.evaluate('''() => { window.__unfocused = new Map();
            for (const el of document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]'))
                window.__unfocused.set(el, (%s)(el)); }''' % FOCUS_STYLE)
        reached, steps = {}, []
        for _ in range(limit):
            page.keyboard.press('Tab')
            info = page.evaluate('''() => { const el = document.activeElement;
                return {name: (%s)(el), focused: (%s)(el), before: window.__unfocused.get(el) || null,
                        matches: %s.filter(s => el.matches(s))}; }''' % (DESCRIBE, FOCUS_STYLE, list(wanted)))
            steps.append(info)
            for selector in info['matches']:
                reached.setdefault(selector, len(steps))
            if len(reached) == len(wanted):
                break
        missing = [s for s in wanted if s not in reached]
        self.assertEqual(missing, [], 'Tab never reached %s; it went through %s' % (
            missing, ', '.join(s['name'] for s in steps)))
        return reached, steps

    def assert_focus_visible(self, steps, where):
        invisible = [s['name'] for s in steps if s['before'] is not None and s['before'] == s['focused']]
        self.assertEqual(invisible, [], '%s: no visible focus indicator on %s' % (where, invisible))

    def test_tab_order_and_focus_visible(self):
        for device in ('desktop', 'mobile'):
            page = self.open(device=device)
            self.visit(page, '/')
            # On a phone the tab bar replaces the header's tabs; it comes last, after the footer.
            ask = '#nav_ask' if device == 'desktop' else '.app-bar-ask'
            tabs = '#nav a:not(#nav_ask)' if device == 'desktop' else '#app-more'
            reached, steps = self.tab_until(page, ['.skip-link', '#keywords', tabs, ask], limit=200)
            self.assertEqual(reached['.skip-link'], 1, 'Skip to content is not the first focusable element')
            self.assertLess(reached['#keywords'], reached[ask])
            self.assert_focus_visible(steps, '/ (%s)' % device)

        # The skip link is shown when focused and moves focus to the content.
        page = self.open()
        self.visit(page, self.question.get_absolute_url())
        page.keyboard.press('Tab')
        skip = page.locator('.skip-link')
        self.assertEqual(page.evaluate('document.activeElement.className'), 'skip-link')
        self.assertEqual(skip.inner_text(), 'Skip to content')
        box = skip.bounding_box()
        self.assertTrue(box['y'] >= 0 and box['height'] > 10, 'the focused skip link is off screen: %s' % box)
        page.keyboard.press('Enter')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'wrapper')
        page.keyboard.press('Tab')
        self.assertTrue(page.evaluate('document.getElementById("wrapper").contains(document.activeElement)'),
                        'Tab after the skip link left the content')
        self.assertFalse(page.evaluate('document.getElementById("roof").contains(document.activeElement)'))
        # Not visible until focused.
        page.keyboard.press('Shift+Tab')
        page.evaluate('document.activeElement.blur()')
        box = skip.bounding_box()
        self.assertLess(box['y'] + box['height'], 1, 'the skip link shows without focus: %s' % box)
        self.check_page(page)

    def test_focus_visible_on_the_question_page(self):
        page = self.open(self.alice)
        self.visit(page, self.question.get_absolute_url())
        _, steps = self.tab_until(page, ['#editor', '#fmanswer input.submit'], limit=120)
        self.assert_focus_visible(steps, 'question page')
        self.check_page(page)

    def open_command_dialog(self, page, link_selector, in_menu):
        """Opens a command's dialog from the keyboard; returns the selector of
        the element focus should come back to."""
        if in_menu:
            trigger = '#node-%d-menu-trigger' % self.answer.id
            page.focus(trigger)
            page.keyboard.press('Enter')
            page.wait_for_selector('#node-%d-menu-trigger[aria-expanded=true]' % self.answer.id)
            page.locator(link_selector).focus()
            back = trigger
        else:
            page.focus(link_selector)
            back = link_selector
        page.keyboard.press('Enter')
        page.wait_for_selector('.dialog .dialog-yes')
        page.wait_for_function('() => document.querySelector(".dialog").contains(document.activeElement)')
        return back

    def check_dialog(self, page, link_selector, in_menu=False):
        back = self.open_command_dialog(page, link_selector, in_menu)
        dialog = page.locator('.dialog')
        self.assertEqual(dialog.get_attribute('role'), 'dialog')
        self.assertEqual(dialog.get_attribute('aria-modal'), 'true')
        for key in ['Tab'] * 6 + ['Shift+Tab'] * 6:
            page.keyboard.press(key)
            self.assertTrue(page.evaluate('() => document.querySelector(".dialog").contains(document.activeElement)'),
                            '%s: %s took focus out of the dialog' % (link_selector, key))
        page.keyboard.press('Escape')
        page.wait_for_selector('.dialog', state='detached')
        page.wait_for_function('s => document.activeElement === document.querySelector(s)', arg=back)
        self.check_page(page)

    def test_command_dialogs(self):
        page = self.open(self.mod)
        self.visit(page, self.question.get_absolute_url())
        # Close (a form), delete (a confirmation), report (in the post menu).
        self.check_dialog(page, '#question-controls a[href$="/close/"]')
        self.check_dialog(page, '#answer-container-%d a[href^="/delete/"]' % self.answer.id)
        self.check_dialog(page, '#answer-container-%d .context-menu-dropdown a[href^="/flag/"]' % self.answer.id,
                          in_menu=True)
        # Nothing was done.
        self.assertFalse(self.question.__class__.objects.get(id=self.question.id).nis.closed)


class ReducedMotionTest(RobustnessTestCase):
    def test_no_motion(self):
        page = self.open(self.mod, reduced_motion='reduce')
        for path in ('/', self.question.get_absolute_url(), '/account/signin/'):
            with self.subTest(path=path):
                self.visit(page, path)
                self.assertEqual(page.evaluate(SLOW_MOTION), [], '%s: motion despite prefers-reduced-motion' % path)
        # Interactions: the post menu and a dialog appear at once, with no
        # jQuery animation running.
        self.visit(page, self.question.get_absolute_url())
        page.click('#node-%d-menu-trigger' % self.answer.id)
        self.assertEqual(page.evaluate('jQuery(":animated").length'), 0)
        self.assertTrue(page.locator('#node-%d-menu-dropdown' % self.answer.id).is_visible())
        self.assertEqual(page.evaluate(SLOW_MOTION), [])
        page.keyboard.press('Escape')
        page.click('#answer-container-%d a[href^="/delete/"]' % self.answer.id)
        page.wait_for_selector('.dialog .dialog-yes')
        page.wait_for_timeout(50)
        self.assertEqual(page.evaluate('jQuery(":animated").length'), 0)
        self.assertEqual(page.evaluate(SLOW_MOTION), [])
        page.keyboard.press('Escape')
        page.wait_for_selector('.dialog', state='detached')
        page.locator('#keywords').fill('coll')
        page.wait_for_selector('#searchbox-listbox [role=option]')
        self.assertEqual(page.evaluate(SLOW_MOTION), [])
        self.check_page(page)


class PrintTest(RobustnessTestCase):
    def test_question_page_prints_the_content_only(self):
        page = self.open(self.alice)
        self.visit(page, self.question.get_absolute_url())
        page.emulate_media(media='print')
        for selector in ('#roof', '#nav', '#searchBar', '#CARight', '#ground', '#fmanswer', '.post-controls',
                         '.post-votes', '.comment-tools', '.answer-sort', '.skip-link'):
            locator = page.locator(selector)
            for i in range(locator.count()):
                self.assertFalse(locator.nth(i).is_visible(), '%s is printed' % selector)
        for selector in ('h1', '.question-body', '.answer-body', '.comment', '.accepted-badge'):
            self.assertTrue(page.locator(selector).first.is_visible(), '%s is not printed' % selector)
        # Black on white, over the whole width of the paper.
        colours = page.evaluate('''() => { const s = getComputedStyle(document.querySelector('.question-body'));
            return [s.color, getComputedStyle(document.body).backgroundColor]; }''')
        self.assertEqual(colours, ['rgb(0, 0, 0)', 'rgb(255, 255, 255)'])
        main = page.locator('#CALeft').bounding_box()
        self.assertGreater(main['width'], page.viewport_size['width'] * 0.9)
        # Dark mode doesn't print white on black.
        page.emulate_media(media='print', color_scheme='dark')
        self.assertEqual(page.evaluate('getComputedStyle(document.querySelector(".question-body")).color'),
                         'rgb(0, 0, 0)')
        page.pdf()  # renders without error
        self.check_page(page)
