from django import template
from django.template.loader import render_to_string

from forum.utils import analytics

register = template.Library()


@register.simple_tag(takes_context=True)
def analytics_consent(context):
    """The Google Analytics consent banner and osqa.analytics.js, when a GA4
    measurement ID is set (forum/utils/analytics.py)."""
    measurement_id = analytics.measurement_id()
    if not measurement_id:
        return ''
    return render_to_string('display/analytics_consent.html', {
        'measurement_id': measurement_id, 'cookie': analytics.COOKIE,
        'csp_nonce': context.get('csp_nonce', ''),
    })


@register.inclusion_tag('display/analytics_settings_link.html')
def analytics_settings_link():
    """The footer's "Analytics cookies" button, which shows the banner again."""
    return {'show': analytics.measurement_id() != ''}
