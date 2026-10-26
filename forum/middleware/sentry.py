import sentry_sdk

from forum.utils.sentry import ensure_admin_client, set_visitor, reset_visitor


class SentryUserMiddleware:
    """Tags server errors with the signed-in user's id (no name, email or IP),
    so reports can be matched to a person who writes in about a problem, and
    tells the per-visitor event limit who the request is for. Also starts this
    process's client when the DSN is set in the admin (ensure_admin_client)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ensure_admin_client()
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            sentry_sdk.set_user({'id': str(user.id)})
        token = set_visitor(request)
        try:
            return self.get_response(request)
        finally:
            reset_visitor(token)
