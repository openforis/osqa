from django import template

from forum.notifications import unread_count

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notifications(context):
    """The member's unread notifications, counted once per request (the
    header's bell and the phone's tab bar both show it)."""
    user = context.get('user')
    if user is None:
        return 0
    request = context.get('request')
    cached = getattr(request, '_osqa_unread', None)
    if cached is not None and cached[0] == user.pk:
        return cached[1]
    count = unread_count(user)
    if request is not None:
        request._osqa_unread = (user.pk, count)
    return count
