"""The post editor (osqa.editor.js, osqa.paste.js, osqa.htmltomd.js): the
toolbar (buttons, pressed states, roving tab stop, tooltips), keyboard
shortcuts, undo/redo, code blocks with a language, tables, Tab indentation
and Escape-then-Tab, images dropped or pasted (several at once, placeholder,
errors), HTML pasted from other programs converted to Markdown, plain paste,
@mention suggestions, the count and minimum length, the answer form, a phone
in dark mode and axe on the toolbar, menu and dialogs."""
import base64
import os
import shutil
import tempfile

from forum import settings

from .base import E2ETestCase
from . import test_accessibility
from .test_editing import tiny_png

ASK = '/questions/ask/'

SET_TEXT = '''([text, start, end]) => {
    const editor = document.getElementById('editor');
    editor.focus();
    editor.value = text;
    editor.setSelectionRange(start === null ? text.length : start, end === null ? (start === null ? text.length : start) : end);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
}'''

SELECTION = '''() => { const e = document.getElementById('editor'); return [e.selectionStart, e.selectionEnd]; }'''

# Dispatches a paste event with these clipboard types; returns whether the editor handled it.
PASTE = '''([types, files]) => {
    const editor = document.getElementById('editor');
    editor.focus();
    const data = new DataTransfer();
    for (const [type, value] of Object.entries(types)) data.setData(type, value);
    for (const [name, b64] of files || []) {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        data.items.add(new File([bytes], name, {type: 'image/png'}));
    }
    const event = new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true});
    editor.dispatchEvent(event);
    return event.defaultPrevented;
}'''

DROP = '''(files) => {
    const editor = document.getElementById('editor');
    const data = new DataTransfer();
    for (const [name, b64, type] of files) {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        data.items.add(new File([bytes], name, {type: type || 'image/png'}));
    }
    editor.dispatchEvent(new DragEvent('dragover', {dataTransfer: data, bubbles: true, cancelable: true}));
    const hovering = editor.classList.contains('drop-target');
    editor.dispatchEvent(new DragEvent('drop', {dataTransfer: data, bubbles: true, cancelable: true}));
    return hovering;
}'''

RICH_HTML = '''<html><body><!--StartFragment-->
<h2>Exporting <em>plots</em></h2>
<p>Use the <b>CSV export</b> of <a href="https://example.org/collect" title="Collect">Collect</a>, not <i>Excel</i>.
<script>alert(1)</script><span onclick="x()">Then</span> run <code>read.csv()</code>.</p>
<ul><li>one <strong>plot</strong></li><li>two<ul><li>nested</li></ul></li></ul>
<ol start="3"><li>third</li><li>fourth</li></ol>
<pre><code class="language-python">print("a < b")
</code></pre>
<table><tr><th>Plot</th><th>Trees</th></tr><tr><td>A1</td><td>12 | 13</td></tr></table>
<blockquote><p>Quoted text</p></blockquote>
<p><img src="data:image/png;base64,AAAA" alt="inline"><img src="https://example.org/map.png" alt="Map"></p>
<p><a href="javascript:alert(1)">bad link</a> and 2 * 3 &lt;tag&gt;</p>
<!--EndFragment--></body></html>'''

RICH_MARKDOWN = '''## Exporting *plots*

Use the **CSV export** of [Collect](https://example.org/collect "Collect"), not *Excel*. Then run `read.csv()`.

- one **plot**
- two
    - nested

3. third
4. fourth

```python
print("a < b")
```

| Plot | Trees |
| --- | --- |
| A1 | 12 \\| 13 |

> Quoted text

![Map](https://example.org/map.png)

bad link and 2 \\* 3 &lt;tag>'''

# Google Docs: everything in <b style="font-weight:normal">, formatting in span styles.
GOOGLE_DOCS_HTML = ('<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1">'
                    '<p dir="ltr"><span style="font-weight:400;">Plain, </span>'
                    '<span style="font-weight:700;">bold</span><span style="font-weight:400;"> and </span>'
                    '<span style="font-style:italic;font-weight:400;">italic</span></p></b>')

# Word: list items are paragraphs with mso-list styles and the bullet in a span.
WORD_HTML = ('<html xmlns:o="urn:schemas-microsoft-com:office:office"><body>'
             '<p class="MsoNormal">Steps:<o:p></o:p></p>'
             '<p class="MsoListParagraphCxSpFirst" style="mso-list:l0 level1 lfo1">'
             '<span style="mso-list:Ignore">1.<span>&nbsp;&nbsp;</span></span>Open the survey<o:p></o:p></p>'
             '<p class="MsoListParagraphCxSpLast" style="mso-list:l0 level1 lfo1">'
             '<span style="mso-list:Ignore">2.<span>&nbsp;&nbsp;</span></span>Export it<o:p></o:p></p>'
             '</body></html>')


def png_b64():
    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, 'x.png')
        tiny_png(path)
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    finally:
        shutil.rmtree(folder)


# Closes the dialog and moves the focus at once, as a member who presses
# Escape and goes straight on does: the dialog's close event comes after, and
# must not pull the focus back to where the dialog was opened.
CLOSE_AND_MOVE_ON = '''([dialog, target]) => {
    document.querySelector(dialog).close();
    document.querySelector(target).focus();
    return new Promise(resolve => setTimeout(resolve, 100));
}'''

class EditorTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user('alice', reputation=500)
        self.bobby = self.create_user('bobby', reputation=50)
        self.question = self.create_question(self.bobby, 'How do I export Collect survey data to CSV?')

    # -- helpers ------------------------------------------------------------

    def ask_page(self, user=None, **options):
        page = self.open(user or self.alice, **options)
        self.visit(page, ASK)
        page.wait_for_function('() => !!document.getElementById("editor").osqaEditor')
        return page

    def set_text(self, page, text, start=None, end=None):
        page.evaluate(SET_TEXT, [text, start, end])

    def value(self, page):
        return page.input_value('#editor')

    def button(self, page, command):
        return page.locator('.editor-toolbar [data-command="%s"]' % command)

    def pressed(self, page, command):
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        return self.button(page, command).get_attribute('aria-pressed') == 'true'

    def upload_folder(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        self.set_setting(settings.UPFILES_FOLDER, folder)
        return folder

    # -- toolbar and shortcuts ---------------------------------------------------

    def test_toolbar_buttons(self):
        page = self.ask_page()
        toolbar = page.locator('.editor-toolbar')
        self.assertEqual(toolbar.get_attribute('role'), 'toolbar')
        commands = toolbar.locator('.editor-button').evaluate_all('els => els.map(e => e.dataset.command)')
        self.assertEqual(commands, ['bold', 'italic', 'link', 'quote', 'code', 'codeblock', 'ulist', 'olist',
                                    'heading', 'table', 'image', 'undo', 'redo', 'help'])

        # Bold on a selection, pressed, and off again.
        self.set_text(page, 'Export the plots now', 11, 16)
        self.button(page, 'bold').click()
        self.assertEqual(self.value(page), 'Export the **plots** now')
        self.assertEqual(page.evaluate(SELECTION), [13, 18])
        self.assertTrue(self.pressed(page, 'bold'))
        self.assertEqual(page.evaluate('document.activeElement.id'), 'editor')  # a click keeps the focus in the text
        self.button(page, 'bold').click()
        self.assertEqual(self.value(page), 'Export the plots now')
        self.assertFalse(self.pressed(page, 'bold'))

        # Italic and inline code with nothing selected insert a selected placeholder.
        self.set_text(page, 'Say ')
        self.button(page, 'italic').click()
        self.assertEqual(self.value(page), 'Say *italic text*')
        page.keyboard.type('hello')
        self.assertEqual(self.value(page), 'Say *hello*')
        self.assertTrue(self.pressed(page, 'italic'))
        self.set_text(page, 'Run read.csv', 4, 12)
        self.button(page, 'code').click()
        self.assertEqual(self.value(page), 'Run `read.csv`')
        self.assertTrue(self.pressed(page, 'code'))

        # Lists and quotes on the selected lines; a blank line is added before the list.
        self.set_text(page, 'Steps:\none\ntwo', 7, 14)
        self.button(page, 'ulist').click()
        self.assertEqual(self.value(page), 'Steps:\n\n- one\n- two')
        self.assertTrue(self.pressed(page, 'ulist'))
        self.set_text(page, 'one\ntwo', 0, 7)
        self.button(page, 'olist').click()
        self.assertEqual(self.value(page), '1. one\n2. two')
        self.button(page, 'olist').click()
        self.assertEqual(self.value(page), 'one\ntwo')
        self.button(page, 'quote').click()
        self.assertEqual(self.value(page), '> one\n> two')
        self.assertTrue(self.pressed(page, 'quote'))

        # Heading: ## then ### then plain text.
        self.set_text(page, 'Results')
        for expected in ('## Results', '### Results', 'Results'):
            self.button(page, 'heading').click()
            self.assertEqual(self.value(page), expected)

        # Enter continues a numbered list; Enter on the empty item ends it.
        self.set_text(page, '1. one')
        page.keyboard.press('Enter')
        self.assertEqual(self.value(page), '1. one\n2. ')
        page.keyboard.press('Enter')
        self.assertEqual(self.value(page), '1. one\n')

        # The preview is the server's rendering.
        self.set_text(page, 'Some **bold** words')
        page.wait_for_selector('#previewer strong:has-text("bold")')
        self.check_page(page)

    def test_keyboard_shortcuts_and_undo(self):
        page = self.ask_page()
        editor = page.locator('#editor')
        self.set_text(page, 'plots', 0, 5)
        editor.press('Control+b')
        self.assertEqual(self.value(page), '**plots**')
        editor.press('Control+i')
        self.assertEqual(self.value(page), '***plots***')
        editor.press('Control+z')
        self.assertEqual(self.value(page), '**plots**')
        editor.press('Control+z')
        self.assertEqual(self.value(page), 'plots')
        self.assertEqual(page.evaluate(SELECTION), [0, 5])
        editor.press('Control+y')
        self.assertEqual(self.value(page), '**plots**')
        editor.press('Control+Shift+z')
        self.assertEqual(self.value(page), '***plots***')
        self.assertEqual(self.button(page, 'redo').get_attribute('aria-disabled'), 'true')
        self.button(page, 'undo').click()
        self.assertEqual(self.value(page), '**plots**')
        self.assertEqual(self.button(page, 'redo').get_attribute('aria-disabled'), 'false')

        # Typing is undone in steps, not one character at a time.
        self.set_text(page, '')
        editor.press_sequentially('Hello world', delay=5)
        page.wait_for_timeout(800)
        editor.press_sequentially(' again', delay=5)
        editor.press('Control+z')
        self.assertEqual(self.value(page), 'Hello world')

        # Ctrl+E: inline code; Ctrl+K: the link dialog, with the selection as its text.
        self.set_text(page, 'see the docs', 8, 12)
        editor.press('Control+e')
        self.assertEqual(self.value(page), 'see the `docs`')
        self.set_text(page, 'see the docs', 8, 12)
        editor.press('Control+k')
        dialog = page.locator('#editor-link-dialog')
        dialog.wait_for()
        self.assertEqual(page.input_value('#editor-link-text'), 'docs')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'editor-link-url')
        page.keyboard.press('Enter')  # no address yet
        self.assertIn('web address', dialog.locator('.editor-dialog-error').text_content())
        page.fill('#editor-link-url', 'example.org/help (draft)')
        page.keyboard.press('Enter')
        dialog.wait_for(state='hidden')
        self.assertEqual(self.value(page), 'see the [docs](https://example.org/help%20%28draft%29)')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'editor')
        # Ctrl+K inside a link edits it; Escape closes without a change.
        page.evaluate('() => document.getElementById("editor").setSelectionRange(10, 10)')
        editor.press('Control+k')
        dialog.wait_for()
        self.assertEqual(page.input_value('#editor-link-url'), 'https://example.org/help%20%28draft%29')
        page.keyboard.press('Escape')
        dialog.wait_for(state='hidden')
        self.assertEqual(self.value(page), 'see the [docs](https://example.org/help%20%28draft%29)')
        # Ctrl+Enter still posts (osqa.compose.js) and is not taken by the editor.
        self.check_page(page)

    def test_toolbar_keyboard_navigation_and_tooltips(self):
        page = self.ask_page()
        buttons = page.locator('.editor-toolbar .editor-button')
        self.assertEqual(buttons.evaluate_all('els => els.filter(e => e.tabIndex === 0).length'), 1)
        page.focus('#id_title')
        # One Tab from the text box before it reaches the toolbar's single stop.
        for _ in range(12):
            page.keyboard.press('Tab')
            if page.evaluate('document.activeElement.closest(".editor-toolbar") !== null'):
                break
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'bold')
        tooltip = page.locator('#editor-tooltip')
        tooltip.wait_for()
        self.assertEqual(tooltip.text_content(), 'Bold (Ctrl+B)')
        self.assertEqual(self.button(page, 'bold').get_attribute('aria-keyshortcuts'), 'Control+B')
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'italic')
        self.assertEqual(buttons.evaluate_all('els => els.filter(e => e.tabIndex === 0).map(e => e.dataset.command)'),
                         ['italic'])
        page.keyboard.press('End')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'help')
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'bold')
        page.keyboard.press('ArrowLeft')
        page.keyboard.press('Home')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'bold')
        # Activated from the keyboard: the focus stays on the button, which shows its state.
        self.set_text(page, 'word', 0, 4)
        page.focus('.editor-toolbar [data-command=bold]')
        page.keyboard.press('Enter')
        self.assertEqual(self.value(page), '**word**')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'bold')
        self.assertTrue(self.pressed(page, 'bold'))
        # The next Tab leaves the toolbar for the text box.
        page.keyboard.press('Tab')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'editor')
        # Hovering shows the tooltip too.
        self.button(page, 'table').hover()
        page.wait_for_function('() => document.getElementById("editor-tooltip").textContent === "Table"')
        self.check_page(page)

    def test_code_block_with_language(self):
        page = self.ask_page()
        self.set_text(page, 'Try this:')
        self.button(page, 'codeblock').click()
        menu = page.locator('#editor-languages')
        menu.wait_for()
        self.assertEqual(self.button(page, 'codeblock').get_attribute('aria-expanded'), 'true')
        menu.get_by_role('menuitem', name='Python').click()
        menu.wait_for(state='hidden')
        self.assertEqual(self.value(page), 'Try this:\n\n```python\ncode\n```\n')
        page.keyboard.type('print("a < b")')
        self.assertEqual(self.value(page), 'Try this:\n\n```python\nprint("a < b")\n```\n')
        page.wait_for_selector('#previewer pre code.language-python.hljs')
        # Inside the block the menu changes its language, from the keyboard.
        page.focus('.editor-toolbar [data-command=codeblock]')
        page.keyboard.press('ArrowDown')
        self.assertEqual(page.evaluate('document.activeElement.dataset.language'), 'python')  # the current one
        page.keyboard.press('Home')
        page.keyboard.press('r')
        self.assertEqual(page.evaluate('document.activeElement.textContent'), 'R')
        page.keyboard.press('Enter')
        menu.wait_for(state='hidden')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'codeblock')
        self.assertIn('```r\nprint("a < b")\n```', self.value(page))
        # Escape closes the menu and returns to its button.
        page.keyboard.press('ArrowDown')
        menu.wait_for()
        page.keyboard.press('Escape')
        menu.wait_for(state='hidden')
        self.assertEqual(page.evaluate('document.activeElement.dataset.command'), 'codeblock')
        # Selected lines become the code of a plain block.
        self.set_text(page, 'a = 1\nb = 2', 0, 11)
        self.button(page, 'codeblock').click()
        menu.get_by_role('menuitem', name='Plain text').click()
        self.assertEqual(self.value(page), '```\na = 1\nb = 2\n```\n')
        self.check_page(page)

    def test_table(self):
        page = self.ask_page()
        self.set_text(page, 'Counts per plot:')
        self.button(page, 'table').click()
        self.assertEqual(self.value(page), 'Counts per plot:\n\n'
                                           '| Column 1 | Column 2 |\n'
                                           '| -------- | -------- |\n'
                                           '| Cell     | Cell     |\n')
        self.assertEqual(page.evaluate("() => { const e = document.getElementById('editor'); "
                                       "return e.value.slice(e.selectionStart, e.selectionEnd); }"), 'Column 1')
        page.keyboard.type('Plot')
        page.wait_for_selector('#previewer table th:has-text("Plot")')
        self.assertEqual(page.locator('#previewer table td').count(), 2)
        self.check_page(page)

    def test_tab_indents_lists_and_code_and_escape_leaves(self):
        page = self.ask_page()
        editor = page.locator('#editor')
        self.set_text(page, '- one\n- two')
        editor.press('Tab')
        self.assertEqual(self.value(page), '- one\n    - two')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'editor')
        editor.press('Shift+Tab')
        self.assertEqual(self.value(page), '- one\n- two')
        # In a code block Tab inserts spaces.
        self.set_text(page, '```\nif x:\n```', 9, 9)
        editor.press('Tab')
        self.assertEqual(self.value(page), '```\nif x:    \n```')
        # Several lines are indented together.
        self.set_text(page, 'a\nb', 0, 3)
        editor.press('Tab')
        self.assertEqual(self.value(page), '    a\n    b')
        # Escape, then Tab, leaves the text box even in a list.
        self.set_text(page, '- one')
        editor.press('Escape')
        editor.press('Tab')
        self.assertEqual(self.value(page), '- one')
        self.assertNotEqual(page.evaluate('document.activeElement.id'), 'editor')
        # In plain text Tab leaves it at once.
        page.focus('#editor')
        self.set_text(page, 'Just text')
        editor.press('Tab')
        self.assertNotEqual(page.evaluate('document.activeElement.id'), 'editor')
        self.assertEqual(self.value(page), 'Just text')
        # The keys are described to screen readers.
        described = editor.get_attribute('aria-describedby').split()
        self.assertIn('editor-keys-hint', described)
        self.assertIn('Escape, then Tab', page.text_content('#editor-keys-hint'))

    # -- images -------------------------------------------------------------------

    def test_drop_and_paste_images(self):
        folder = self.upload_folder()
        page = self.ask_page()
        png = png_b64()
        # Uploads wait until the test lets them through, to see the placeholders.
        page.evaluate('''() => {
            const send = window.fetch;
            window.releaseUploads = null;
            const gate = new Promise(r => { window.releaseUploads = r; });
            window.fetch = function(url, options) {
                if (String(url).endsWith('/upload/')) return gate.then(() => send(url, options));
                return send(url, options);
            };
        }''')
        self.set_text(page, 'My plots:')
        self.assertTrue(page.evaluate(DROP, [['plot-map.png', png], ['plot-map.png', png]]))
        self.assertEqual(self.value(page),
                         'My plots:\n\n![Uploading plot-map.png\u2026]()\n\n![Uploading plot-map.png (2)\u2026]()\n')
        self.assertFalse(page.evaluate("document.getElementById('editor').classList.contains('drop-target')"))
        # A pasted screenshot too.
        self.assertTrue(page.evaluate(PASTE, [{}, [['image.png', png]]]))
        self.assertIn('![Uploading image.png\u2026]()', self.value(page))
        page.evaluate('window.releaseUploads()')
        page.wait_for_function("() => !/Uploading/.test(document.getElementById('editor').value)")
        value = self.value(page)
        self.assertRegex(value, r'^My plots:\n\n!\[plot map\]\(/upfiles/[^)]+\.png\)\n\n'
                                r'!\[plot map\]\(/upfiles/[^)]+\.png\)\n\n!\[image\]\(/upfiles/[^)]+\.png\)\n$')
        # Three uploads; their AVIF/WebP copies are in _variants/ (forum/utils/images.py).
        self.assertEqual(len([name for name in os.listdir(folder) if name != '_variants']), 3)
        page.wait_for_selector('#previewer img[alt="plot map"]')
        # Each finished upload is an undo step of its own.
        page.locator('#editor').press('Control+z')
        self.assertEqual(self.value(page).count('Uploading'), 1)
        page.locator('#editor').press('Control+y')
        self.assertEqual(self.value(page), value)
        self.check_page(page)

    def test_refused_and_wrong_files(self):
        self.upload_folder()
        self.set_setting(settings.ALLOW_MAX_FILE_SIZE, 0.0001)  # about 100 bytes: every image is too big
        page = self.ask_page()
        png = png_b64()
        self.set_text(page, 'Text')
        with page.expect_response(lambda r: r.url.endswith('/upload/')) as upload:
            page.evaluate(DROP, [['huge.png', base64.b64encode(base64.b64decode(png) + b'\0' * 400).decode()]])
        self.assertEqual(upload.value.status, 413)
        error = page.locator('.upload-errors .upload-error')
        error.wait_for()
        self.assertIn('huge.png: ', error.text_content())
        self.assertIn('maximum upload file size', error.text_content())
        self.assertEqual(page.locator('.upload-errors').get_attribute('role'), 'alert')
        page.wait_for_function("() => document.getElementById('editor').value === 'Text\\n'")
        # A dropped file that isn't an image is not sent.
        page.evaluate(DROP, [['notes.txt', base64.b64encode(b'hello').decode(), 'text/plain']])
        page.wait_for_selector('.upload-error:has-text("Only images")')
        self.assertEqual([p for p in page.problems if '413' not in p], [])
        page.problems.clear()
        self.check_page(page)

    # -- pasting text ---------------------------------------------------------------

    def test_html_paste_becomes_markdown(self):
        page = self.ask_page()
        self.set_text(page, '')
        self.assertTrue(page.evaluate(PASTE, [{'text/html': RICH_HTML, 'text/plain': 'plain version'}]))
        self.assertEqual(self.value(page), RICH_MARKDOWN)
        self.assertNotIn('<', self.value(page).replace('a < b', ''))
        page.wait_for_selector('#previewer table th:has-text("Trees")')
        self.assertEqual(page.locator('#previewer script, #previewer [onclick]').count(), 0)
        self.assertEqual(page.locator('#previewer a[href="https://example.org/collect"]').count(), 1)

        # Google Docs and Word.
        self.set_text(page, '')
        page.evaluate(PASTE, [{'text/html': GOOGLE_DOCS_HTML, 'text/plain': 'Plain, bold and italic'}])
        self.assertEqual(self.value(page), 'Plain, **bold** and *italic*')
        self.set_text(page, '')
        page.evaluate(PASTE, [{'text/html': WORD_HTML, 'text/plain': 'Steps'}])
        self.assertEqual(self.value(page), 'Steps:\n\n1. Open the survey\n1. Export it')

        # Inline HTML pasted in a sentence stays inline, and is one undo step.
        self.set_text(page, 'Use  now', 4, 4)
        page.evaluate(PASTE, [{'text/html': '<span>the <b>export</b> menu</span>', 'text/plain': 'the export menu'}])
        self.assertEqual(self.value(page), 'Use the **export** menu now')
        page.locator('#editor').press('Control+z')
        self.assertEqual(self.value(page), 'Use  now')
        self.check_page(page)

    def test_plain_paste(self):
        page = self.ask_page()
        html = {'text/html': '<p>A <b>bold</b> word</p>', 'text/plain': 'A bold word'}
        # Ctrl+Shift+V: the browser pastes the plain text (the editor leaves the event alone).
        self.set_text(page, '')
        page.evaluate('''() => document.getElementById('editor').dispatchEvent(new KeyboardEvent('keydown',
            {key: 'V', ctrlKey: true, shiftKey: true, bubbles: true}))''')
        self.assertFalse(page.evaluate(PASTE, [html]))
        # The next paste converts again.
        self.assertTrue(page.evaluate(PASTE, [html]))
        self.assertEqual(self.value(page), 'A **bold** word')
        # HTML with nothing to keep (a code editor's coloured spans) and pastes inside code are plain.
        self.set_text(page, '')
        self.assertFalse(page.evaluate(PASTE, [{'text/html': '<div style="white-space: pre;"><span style="color:red">x = 1</span></div>',
                                                'text/plain': 'x = 1'}]))
        self.set_text(page, '```\n\n```', 4, 4)
        self.assertFalse(page.evaluate(PASTE, [html]))
        self.set_text(page, 'see `', 5, 5)
        self.assertFalse(page.evaluate(PASTE, [html]))
        self.check_page(page)

    # -- mentions, count ---------------------------------------------------------------

    def test_mentions_in_the_editor(self):
        page = self.ask_page()
        editor = page.locator('#editor')
        self.set_text(page, 'Thanks ')
        editor.press_sequentially('@bob', delay=30)
        option = page.locator('.mention-suggestions [role=option]').first
        option.wait_for()
        self.assertEqual(option.get_attribute('aria-selected'), 'true')
        self.assertEqual(editor.get_attribute('aria-controls'), 'mention-suggestions')
        self.assertEqual(editor.get_attribute('aria-activedescendant'), option.get_attribute('id'))
        self.assertEqual(page.locator('#mention-suggestions').get_attribute('aria-label'), 'People to mention')
        editor.press('Enter')
        self.assertEqual(self.value(page), 'Thanks @bobby ')
        self.assertEqual(page.locator('.mention-suggestions').count(), 0)
        self.assertIsNone(editor.get_attribute('aria-activedescendant'))
        # Escape closes the list without inserting.
        editor.press_sequentially('and @bo', delay=30)
        page.locator('.mention-suggestions').wait_for()
        editor.press('Escape')
        self.assertEqual(page.locator('.mention-suggestions').count(), 0)
        self.assertEqual(self.value(page), 'Thanks @bobby and @bo')
        page.wait_for_selector('#previewer a.mention:has-text("@bobby")')
        self.check_page(page)

    def test_count_and_minimum_length(self):
        self.set_setting(settings.FORM_MIN_QUESTION_BODY, 20)
        page = self.ask_page()
        hint = page.locator('#editor-min-hint')
        self.assertEqual(hint.text_content(), 'At least 20 characters')
        self.assertIn('editor-min-hint', page.get_attribute('#editor', 'aria-describedby'))
        page.locator('#editor').press_sequentially('Too short', delay=5)
        self.assertEqual(page.text_content('#editor-metrics'), '9 characters \u00b7 2 words')
        self.assertIn('is-short', hint.get_attribute('class'))
        page.locator('#editor').press_sequentially(' but now **long** enough', delay=5)
        self.assertEqual(page.text_content('#editor-metrics'), '33 characters \u00b7 6 words')
        self.assertIn('is-met', hint.get_attribute('class'))
        self.assertNotIn('is-short', hint.get_attribute('class'))

    def test_title_count_and_minimum_length(self):
        self.set_setting(settings.FORM_MIN_QUESTION_TITLE, 15)
        page = self.ask_page()
        hint = page.locator('#title-min-hint')
        self.assertEqual(hint.text_content(), 'At least 15 characters')
        self.assertIn('title-min-hint', page.get_attribute('#id_title', 'aria-describedby'))
        self.assertEqual(page.text_content('#title-metrics'), '0 characters')
        page.locator('#id_title').press_sequentially('Too short', delay=5)
        self.assertEqual(page.text_content('#title-metrics'), '9 characters')
        self.assertIn('is-short', hint.get_attribute('class'))
        page.locator('#id_title').press_sequentially(' but now long', delay=5)
        self.assertEqual(page.text_content('#title-metrics'), '22 characters')
        self.assertIn('is-met', hint.get_attribute('class'))
        self.assertNotIn('is-short', hint.get_attribute('class'))
        self.check_page(page)

    # -- other editor pages ------------------------------------------------------------

    def test_answer_form_and_edit_page(self):
        page = self.open(self.alice)
        self.visit(page, self.question.get_absolute_url())
        page.wait_for_function('() => !!document.getElementById("editor").osqaEditor')
        self.set_text(page, 'Use the CSV export', 8, 18)
        page.locator('#fmanswer .editor-toolbar [data-command=bold]').click()
        self.assertEqual(self.value(page), 'Use the **CSV export**')
        page.wait_for_selector('#previewer strong')
        page.click('#pre-collapse')  # the answer form's own preview toggle still works
        self.assertTrue(page.locator('#previewer').is_hidden())
        page.locator('#editor').press('End')
        page.locator('#editor').press_sequentially(' of Collect, in the designer menu.', delay=2)
        with page.expect_navigation():
            page.locator('#fmanswer input.submit').click()
        self.check_page(page)
        answer = self.question.answers.get()
        self.assertIn('<strong>CSV export</strong>', answer.body)

        from django.urls import reverse
        self.visit(page, reverse('edit_answer', kwargs={'id': answer.id}))
        page.wait_for_function('() => !!document.getElementById("editor").osqaEditor')
        self.assertTrue(self.button(page, 'undo').get_attribute('aria-disabled') == 'true')
        page.locator('#editor').press('Control+End')
        self.button(page, 'table').click()
        page.locator('#editor').press('Control+z')
        self.assertEqual(self.value(page), answer.active_revision.body)

    # -- phone, dark mode, accessibility ---------------------------------------------------

    def test_phone_dark_layout(self):
        page = self.ask_page(device='mobile', dark=True)
        toolbar = page.locator('.editor-toolbar')
        # The toolbar scrolls sideways inside itself; the page does not.
        size = toolbar.evaluate('t => [t.scrollWidth, t.clientWidth, getComputedStyle(t).overflowX]')
        self.assertGreater(size[0], size[1])
        self.assertEqual(size[2], 'auto')
        box = self.button(page, 'bold').bounding_box()
        self.assertGreaterEqual(box['width'], 40)
        self.assertGreaterEqual(box['height'], 40)
        colours = page.evaluate('''() => [getComputedStyle(document.querySelector('.editor-toolbar')).backgroundColor,
                                          getComputedStyle(document.querySelector('[data-command=bold]')).color]''')
        self.assertNotEqual(colours[0], 'rgb(245, 247, 250)')  # the dark background, not the light one
        page.locator('.editor-toolbar [data-command=image]').scroll_into_view_if_needed()
        self.button(page, 'image').tap()
        dialog = page.locator('#editor-image-dialog')
        dialog.wait_for()
        width = dialog.evaluate('d => d.getBoundingClientRect().width')
        self.assertLessEqual(width, 390 - 32 + 1)
        self.check_page(page)
        page.screenshot(path=os.path.join(self.artifacts(), 'editor-phone-dark-image-dialog.png'))
        dialog.locator('[data-dialog-cancel]').tap()
        dialog.wait_for(state='hidden')
        self.button(page, 'codeblock').scroll_into_view_if_needed()
        self.button(page, 'codeblock').tap()
        page.locator('#editor-languages').wait_for()
        self.check_page(page)
        page.screenshot(path=os.path.join(self.artifacts(), 'editor-phone-dark-languages.png'))

    def artifacts(self):
        folder = os.environ.get('E2E_ARTIFACTS') or os.path.join('tmp', 'e2e')
        os.makedirs(folder, exist_ok=True)
        return folder

    def test_closing_a_dialog_leaves_a_focus_that_moved_on_alone(self):
        page = self.ask_page()
        self.button(page, 'link').click()
        page.locator('#editor-link-dialog').wait_for()
        page.evaluate(CLOSE_AND_MOVE_ON, ['#editor-link-dialog', '#id_title'])
        self.assertEqual(page.evaluate('() => document.activeElement.id'), 'id_title')
        # The dialog still opens and closes as before.
        self.button(page, 'link').click()
        page.locator('#editor-link-dialog').wait_for()
        page.keyboard.press('Escape')
        page.locator('#editor-link-dialog').wait_for(state='hidden')
        self.check_page(page)

    def test_accessibility_of_the_toolbar_menu_and_dialogs(self):
        failures = []
        for device, dark in (('desktop', False), ('mobile', True)):
            page = self.ask_page(device=device, dark=dark)
            self.set_text(page, '**bold** text', 3, 3)
            page.wait_for_function('() => document.querySelector("[data-command=bold]").getAttribute("aria-pressed") === "true"')
            failures += ['%s: %s' % (device, v) for v in test_accessibility.AccessibilityTest.axe(self, page)]
            self.button(page, 'codeblock').click()
            page.locator('#editor-languages').wait_for()
            failures += ['%s, language menu: %s' % (device, v) for v in test_accessibility.AccessibilityTest.axe(self, page)]
            page.keyboard.press('Escape')
            for command, dialog in (('link', '#editor-link-dialog'), ('image', '#editor-image-dialog')):
                self.button(page, command).click()
                page.locator(dialog).wait_for()
                failures += ['%s, %s dialog: %s' % (device, command, v) for v in test_accessibility.AccessibilityTest.axe(self, page)]
                page.keyboard.press('Escape')
                page.locator(dialog).wait_for(state='hidden')
        if failures:
            self.fail('accessibility violations:\n' + '\n'.join(failures))
