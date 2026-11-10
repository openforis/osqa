"""Browser push UI: the "Get notifications on this device" switch and the
device settings of the email settings page. Both render nothing unless VAPID
keys are configured (forum/utils/push.py)."""
from django import template

from forum.models import PushSubscription
from forum.utils import push

register = template.Library()


def _switch_context(user):
    devices = list(PushSubscription.objects.filter(user=user))
    return {
        'push_on': True,
        'user': user,
        'public_key': push.public_key(),
        'devices': devices,
        # The switch is on only if this browser's subscription is one of these.
        'endpoint_hashes': ' '.join(d.endpoint_hash for d in devices),
    }


@register.inclusion_tag('push/switch.html', takes_context=True)
def push_switch(context):
    user = context.get('user')
    if not push.enabled() or user is None or not user.is_authenticated:
        return {'push_on': False}
    return dict(_switch_context(user), compact=True)


@register.inclusion_tag('push/settings.html', takes_context=True)
def push_settings(context, view_user):
    """On someone's email settings page, for themselves only (a device is
    the browser of whoever looks at the page)."""
    user = context.get('user')
    if not push.enabled() or user is None or not user.is_authenticated or view_user.pk != user.pk:
        return {'push_on': False}
    chosen = push.kinds_for(user)
    request = context.get('request')
    return dict(_switch_context(user),
                kinds=[(key, label, key in chosen) for key, label, default in push.PUSH_KINDS],
                next=request.get_full_path() if request is not None else '')


@register.inclusion_tag('push/ask_prompt.html', takes_context=True)
def push_prompt(context, question):
    """Under the asker's own question while it has no answers: "Get a
    notification when someone answers", with the switch. A nonce'd script
    shows it before the first paint unless this browser can't do it, has it
    on already, or "Not now" was pressed in the last 30 days."""
    user = context.get('user')
    if (not push.enabled() or user is None or not user.is_authenticated or question.author_id != user.pk
            or question.nis.closed or question.answer_count):
        return {'push_on': False}
    return dict(_switch_context(user), compact=True, csp_nonce=context.get('csp_nonce'))
