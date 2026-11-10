import time
import os
import posixpath
import datetime
import math
import re
import logging
import random
from django import template
from django.utils.html import escape
from django.utils.encoding import smart_str, force_str
from django.utils.safestring import mark_safe
from django.utils import dateformat
from forum.models import Question, Answer, QuestionRevision, AnswerRevision, NodeRevision
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from forum import settings
from django.template.defaulttags import url as default_url
from forum import skins
from forum.utils import html
from forum.utils import static_files
from .extra_filters import decorated_int
from django.urls import reverse

register = template.Library()

# Sized (no layout shift), lazy, and twice the pixels on high-density screens.
GRAVATAR_TEMPLATE = ('<img class="gravatar" width="%(size)s" height="%(size)s" '
'src="https://secure.gravatar.com/avatar/%(gravatar_hash)s'
'?s=%(size)s&amp;d=%(default)s&amp;r=%(rating)s" '
'srcset="https://secure.gravatar.com/avatar/%(gravatar_hash)s'
'?s=%(size2x)s&amp;d=%(default)s&amp;r=%(rating)s 2x" '
'alt="%(username)s" loading="lazy" decoding="async" />')

@register.simple_tag
def gravatar(user, size):
    try:
        gravatar = user['gravatar']
        username = user['username']
    except (TypeError, AttributeError, KeyError):
        gravatar = user.gravatar
        username = user.username
    try:
        size2x = int(size) * 2
    except (TypeError, ValueError):
        size2x = size
    return mark_safe(GRAVATAR_TEMPLATE % {
    'size': size,
    'size2x': size2x,
    'gravatar_hash': gravatar,
    'default': settings.GRAVATAR_DEFAULT_IMAGE,
    'rating': settings.GRAVATAR_ALLOWED_RATING,
    'username': escape(username),
    })


_logo_sizes = {}


@register.simple_tag
def logo_size():
    """width="..." height="..." of the APP_LOGO file (uploaded or bundled), so
    the header keeps its space while the logo loads; nothing for an outside
    URL or an unreadable file. Read once per file version."""
    logo = str(settings.APP_LOGO or '').split('?')[0]
    alias = str(settings.UPFILES_ALIAS)
    if not logo.startswith(alias):
        return ''
    relative = logo[len(alias):]
    bundled = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'upfiles')
    for root in (str(settings.UPFILES_FOLDER), bundled):
        root = os.path.realpath(root)
        path = os.path.realpath(os.path.join(root, relative))
        if path.startswith(root + os.sep) and os.path.isfile(path):
            break
    else:
        return ''
    key = (path, os.path.getmtime(path))
    if key not in _logo_sizes:
        try:
            from PIL import Image
            with Image.open(path) as image:
                size = mark_safe('width="%d" height="%d"' % image.size)
        except Exception:
            size = ''
        if len(_logo_sizes) > 8:
            _logo_sizes.clear()
        _logo_sizes[key] = size
    return _logo_sizes[key]


@register.simple_tag
def get_score_badge(user):
    return _get_score_badge(user)

def _get_score_badge(user):
    if user.is_suspended():
        return _("(suspended)")

    repstr = decorated_int(user.reputation, "")

    BADGE_TEMPLATE = '<span class="score" title="%(reputation)s %(reputationword)s">%(repstr)s</span>'
    if user.gold > 0 :
        BADGE_TEMPLATE = '%s%s' % (BADGE_TEMPLATE, '<span title="%(gold)s %(badgesword)s">'
        '<span class="badge1">&#9679;</span>'
        '<span class="badgecount">%(gold)s</span>'
        '</span>')
    if user.silver > 0:
        BADGE_TEMPLATE = '%s%s' % (BADGE_TEMPLATE, '<span title="%(silver)s %(badgesword)s">'
        '<span class="silver">&#9679;</span>'
        '<span class="badgecount">%(silver)s</span>'
        '</span>')
    if user.bronze > 0:
        BADGE_TEMPLATE = '%s%s' % (BADGE_TEMPLATE, '<span title="%(bronze)s %(badgesword)s">'
        '<span class="bronze">&#9679;</span>'
        '<span class="badgecount">%(bronze)s</span>'
        '</span>')
    BADGE_TEMPLATE = smart_str(BADGE_TEMPLATE, encoding='utf-8', strings_only=False, errors='strict')
    return mark_safe(BADGE_TEMPLATE % {
    'reputation' : user.reputation,
    'repstr': repstr,
    'gold' : user.gold,
    'silver' : user.silver,
    'bronze' : user.bronze,
    'badgesword' : _('badges'),
    'reputationword' : _('reputation points'),
    })

# Usage: {% get_accept_rate node.author %}
@register.simple_tag
def get_accept_rate(user):
    # If the Show Accept Rate feature is not activated this tag should return a blank string
    if not settings.SHOW_USER_ACCEPT_RATE:
        return ""

    # Freeze accept rate for users
    freeze_accept_rate_for_users_users = settings.FREEZE_ACCEPT_RATE_FOR.value
    if user.username in list(freeze_accept_rate_for_users_users):
        freeze = True
    else:
        freeze = False

    # The number of all the user's answers and of the accepted ones, in one
    # query kept in the query cache.
    from django.db.models import Count, Q
    counts = Answer.objects.filter(author=user).cached_aggregate(
        total=Count('id'), accepted=Count('id', filter=Q(state_string__contains="(accepted)")))
    total_answers_count = counts['total'] or 0
    accepted_answers_count = counts['accepted'] or 0

    # In order to represent the accept rate in percentages we divide the number of the accepted answers to the
    # total answers count and make a hundred multiplication.
    try:
        accept_rate = (float(accepted_answers_count) / float(total_answers_count) * 100)
    except ZeroDivisionError:
        accept_rate = 0

    # If the user has more than one accepted answers the rate title will be in plural.
    if accepted_answers_count > 1:
        accept_rate_number_title = _('%(user)s has %(count)d accepted answers') % {
            'user' :  smart_str(user.username),
            'count' : int(accepted_answers_count)
        }
    # If the user has one accepted answer we'll be using singular.
    elif accepted_answers_count == 1:
        accept_rate_number_title = _('%s has one accepted answer') % smart_str(user.username)
    # This are the only options. Otherwise there are no accepted answers at all.
    else:
        if freeze:
            accept_rate_number_title = ""
        else:
            accept_rate_number_title = _('%s has no accepted answers') % smart_str(user.username)

    html_output = """
    <span title="%(accept_rate_title)s" class="accept_rate">%(accept_rate_label)s:</span>
    <span title="%(accept_rate_number_title)s">%(accept_rate)d&#37;</span>
    """ % {
        'accept_rate_label' : _('accept rate'),
        'accept_rate_title' : _('Rate of the user\'s accepted answers'),
        'accept_rate' : 100 if freeze else int(accept_rate),
        'accept_rate_number_title' : u'%s' % accept_rate_number_title,
    }

    return mark_safe(html_output)

@register.simple_tag
def get_age(birthday):
    current_time = datetime.datetime(*time.localtime()[0:6])
    year = birthday.year
    month = birthday.month
    day = birthday.day
    diff = current_time - datetime.datetime(year, month, day, 0, 0, 0)
    return diff.days // 365

@register.simple_tag
def diff_date(date, limen=2):
    if not date:
        return _('unknown')

    now = datetime.datetime.now()
    diff = now - date
    days = diff.days
    hours = int(diff.seconds/3600)
    minutes = int(diff.seconds/60)

    if date.year != now.year:
        return dateformat.format(date, 'd M \'y, H:i')
    elif days > 2:
        return dateformat.format(date, 'd M, H:i')

    elif days == 2:
        return _('2 days ago')
    elif days == 1:
        return _('yesterday')
    elif minutes >= 60:
        return ngettext('%(hr)d ' + _("hour ago"), '%(hr)d ' + _("hours ago"), hours) % {'hr':hours}
    elif diff.seconds >= 60:
        return ngettext('%(min)d ' + _("min ago"), '%(min)d ' + _("mins ago"), minutes) % {'min':minutes}
    else:
        return ngettext('%(sec)d ' + _("sec ago"), '%(sec)d ' + _("secs ago"), diff.seconds) % {'sec':diff.seconds}

_media_urls = {}


@register.simple_tag
def media(url):
    """URL of a skin media file, with its version token (?v=<content hash>) so
    it can be cached for a year (see forum.utils.static_files). Worked out
    once per file and process (on every call with DEBUG on)."""
    from django.conf import settings as django_settings
    known = _media_urls.get(url)
    if known is not None and not django_settings.DEBUG:
        return known
    source = skins.find_media_source(url)
    if source:
        # Create the URL prefix, with duplicate forward slashes replaced by one.
        url_prefix = re.sub("/+", "/", settings.FORCE_SCRIPT_NAME + '/m/')
        result = static_files.versioned(url_prefix + source, os.path.join(skins.SKINS_FOLDER, source))
        _media_urls[url] = result
        return result

@register.simple_tag
def get_tag_font_size(tag):
    # Django 4.2/Python 3: Ensure numeric value for math operations
    occurrences_of_current_tag = int(tag.used_count) if tag.used_count else 1

    # Occurrences count settings
    min_occurs = int(settings.TAGS_CLOUD_MIN_OCCURS)
    max_occurs = int(settings.TAGS_CLOUD_MAX_OCCURS)

    # Font size settings
    min_font_size = int(settings.TAGS_CLOUD_MIN_FONT_SIZE)
    max_font_size = int(settings.TAGS_CLOUD_MAX_FONT_SIZE)

    # Calculate the font size of the tag according to the occurrences count
    weight = (math.log(occurrences_of_current_tag)-math.log(min_occurs))/(math.log(max_occurs)-math.log(min_occurs))
    font_size_of_current_tag = min_font_size + int(math.floor((max_font_size-min_font_size)*weight))

    return font_size_of_current_tag

class ItemSeparatorNode(template.Node):
    def __init__(self, separator):
        sep = separator.strip()
        if sep[0] == sep[-1] and sep[0] in ('\'', '"'):
            sep = sep[1:-1]
        else:
            raise template.TemplateSyntaxError('separator in joinitems tag must be quoted')
        self.content = sep

    def render(self, context):
        return self.content

class BlockMediaUrlNode(template.Node):
    def __init__(self, nodelist):
        self.items = nodelist

    def render(self, context):
        prefix = settings.APP_URL + 'm/'
        url = ''
        if self.items:
            url += '/'
        for item in self.items:
            url += item.render(context)

        url = skins.find_media_source(url.replace(' ', ''))
        if not url:
            return ''
        return static_files.versioned(prefix + url, os.path.join(skins.SKINS_FOLDER, url))

@register.tag(name='blockmedia')
def blockmedia(parser, token):
    try:
        tagname = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError("blockmedia tag does not use arguments")
    nodelist = []
    while True:
        nodelist.append(parser.parse(('endblockmedia')))
        next = parser.next_token()
        if next.contents == 'endblockmedia':
            break
    return BlockMediaUrlNode(nodelist)


@register.simple_tag
def fullmedia(url):
    domain = settings.APP_BASE_URL
    #protocol = getattr(settings, "PROTOCOL", "http")
    path = media(url)
    return "%s%s" % (domain, path)


class SimpleVarNode(template.Node):
    def __init__(self, name, value):
        self.name = name
        self.value = template.Variable(value)

    def render(self, context):
        context[self.name] = self.value.resolve(context)
        return ''

class BlockVarNode(template.Node):
    def __init__(self, name, block):
        self.name = name
        self.block = block

    def render(self, context):
        source = self.block.render(context)
        context[self.name] = source.strip()
        return ''


@register.tag(name='var')
def do_var(parser, token):
    tokens = token.split_contents()[1:]

    if not len(tokens) or not re.match(r'^\w+$', tokens[0]):
        raise template.TemplateSyntaxError("Expected variable name")

    if len(tokens) == 1:
        nodelist = parser.parse(('endvar',))
        parser.delete_first_token()
        return BlockVarNode(tokens[0], nodelist)
    elif len(tokens) == 3:
        return SimpleVarNode(tokens[0], tokens[2])

    raise template.TemplateSyntaxError("Invalid number of arguments")

class DeclareNode(template.Node):
    dec_re = re.compile(r'^\s*(\w+)\s*(:?=)\s*(.*)$')

    def __init__(self, block):
        self.block = block

    def render(self, context):
        source = self.block.render(context)

        for line in source.splitlines():
            m = self.dec_re.search(line)
            if m:
                clist = list(context)
                clist.reverse()
                d = {}
                d['_'] = _
                d['os'] = os
                d['html'] = html
                d['reverse'] = reverse
                d['settings'] = settings
                d['smart_str'] = smart_str
                d['force_str'] = force_str
                for c in clist:
                    d.update(c)
                try:
                    command = m.group(3).strip()
                    context[m.group(1).strip()] = eval(command, d)
                except Exception as e:
                    logging.error("Error in declare tag, when evaluating: %s" % m.group(3).strip())
        return ''

@register.tag(name='declare')
def do_declare(parser, token):
    nodelist = parser.parse(('enddeclare',))
    parser.delete_first_token()
    # The block is evaluated as Python: only literal text, so no value from a
    # template variable (user data) can ever become code.
    if any(not isinstance(node, template.base.TextNode) for node in nodelist):
        raise template.TemplateSyntaxError("declare blocks take only plain text: no {{ variables }} or {% tags %}")
    return DeclareNode(nodelist)

# Usage: {% random 1 999 %}
# Generates random number in the template
class RandomNumberNode(template.Node):
    # We get the limiting numbers
    def __init__(self, int_from, int_to):
        self.int_from = int(int_from)
        self.int_to = int(int_to)

    # We generate the random number using the standard python interface
    def render(self, context):
        return str(random.randint(self.int_from, self.int_to))

@register.tag(name="random")
def random_number(parser, token):
    # Try to get the limiting numbers from the token
    try:
        tag_name, int_from, int_to = token.split_contents()
    except ValueError:
        # If we had no success -- raise an exception
        raise template.TemplateSyntaxError("%r tag requires exactly two arguments" % token.contents.split()[0])

    # Call the random Node
    return RandomNumberNode(int_from, int_to)
