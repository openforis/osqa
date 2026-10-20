"""Tags for the administration layout (osqaadmin/base.html) and its pages."""
import html
import textwrap

from django import template
from django.template.loader import get_template
from django.template.loader_tags import BLOCK_CONTEXT_KEY
from django.utils.html import strip_tags

register = template.Library()


@register.simple_tag(takes_context=True)
def block_text(context, name):
    """The text of block `name` as the page defines it, rendered again: the
    page heading repeats the `subtitle` block of the <title> (a template
    can't use a block twice), so admin pages and module templates that only
    define `subtitle` get a heading too."""
    block_context = context.render_context.get(BLOCK_CONTEXT_KEY)
    block = block_context.get_block(name) if block_context else None
    if block is None:
        return ''
    # Plain text (escaped again by simple_tag), not HTML: it's a heading.
    return ' '.join(html.unescape(strip_tags(block.nodelist.render(context))).split())


class ExampleNode(template.Node):
    def __init__(self, nodelist, example_id, title):
        self.nodelist, self.example_id, self.title = nodelist, example_id, title

    def render(self, context):
        # The code as written (variables such as {{ app_url }} filled in, not
        # escaped twice), without the template's indentation.
        autoescape, context.autoescape = context.autoescape, False
        try:
            code = self.nodelist.render(context)
        finally:
            context.autoescape = autoescape
        return get_template('osqaadmin/guides/_example.html').render({
            'id': self.example_id.resolve(context), 'title': self.title.resolve(context),
            'code': textwrap.dedent(code.strip('\n')).rstrip(),
        })


@register.tag
def example(parser, token):
    """A code example with a copy button, for the settings pages' guides
    (osqaadmin/guides/*.html):

        {% example "css-logo" _("A bigger logo") %}
            #logo img { max-height: 56px; }
        {% endexample %}
    """
    bits = token.split_contents()
    if len(bits) != 3:
        raise template.TemplateSyntaxError('%s takes an id and a title' % bits[0])
    nodelist = parser.parse(('endexample',))
    parser.delete_first_token()
    return ExampleNode(nodelist, parser.compile_filter(bits[1]), parser.compile_filter(bits[2]))
