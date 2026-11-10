"""The account lifecycle: confirming the email address of new members (double
opt-in), changing the address, password resets and changes, sessions (sign
out everywhere, "keep me signed in", recent sign-in) and new-browser sign-in
emails. Views in forum/views/auth.py and forum/views/account.py.

- New members who sign up with an email address get `User.email_confirmation_required`;
  until they confirm, EMAIL_CONFIRMATION_MODE decides whether they may sign
  in ('signin', the default: no; 'post': yes, but not ask/answer/comment;
  'off': only the legacy REQUIRE_EMAIL_VALIDATION_TO list applies). Staff never need it.
- Links are ValidationHash tokens (HMAC-SHA256, stored as digests, single use,
  expiring): 'email' (confirm, 48 h), 'newemail' / 'emailcancel' (email change,
  48 h), 'pwreset' (password reset, 60 min, bound to the password hash and the
  last sign-in so it dies when either changes).
- Account emails are sent with send_template_email() without an email kind:
  they ignore notification settings and unsubscribes, and never contain a
  password. The number a person or IP address may request is limited by the
  PASSWORD_RESETS_PER_HOUR setting.
- Each session stores the account's `session_epoch` at sign-in; raising it
  (sign out everywhere, password reset, cancelled email change) ends every
  other session (checked by forum.middleware.extended_user).
"""
import copy
import datetime
import hashlib
import logging
import secrets

from django.conf import settings as djsettings
from django.core import signing
from django.utils.translation import gettext as _

from forum import settings
from forum.utils import security_log, throttle

CONFIRM_HOURS = 48
EMAIL_CHANGE_HOURS = 48
RESET_MINUTES = 60
RECENT_AUTH_MINUTES = 15

EPOCH_SESSION_KEY = 'osqa_epoch'
AUTH_TIME_SESSION_KEY = 'osqa_auth_time'
REMEMBER_SESSION_KEY = 'osqa_remember'

DEVICE_COOKIE = 'osqa_device'
DEVICE_SALT = 'forum.accounts.device'
DEVICE_COOKIE_AGE = 2 * 365 * 24 * 3600
MAX_DEVICES = 20

POSTING = ('ask', 'answer', 'comment')
MODES = ('signin', 'post', 'off')
DEFAULT_MODE = 'signin'


def _now():
    return datetime.datetime.now()


def recipient(user, email=None):
    """`user` as an email recipient, optionally at another address (the new
    address of an email change, or the address of an account being deleted)."""
    copy_ = copy.copy(user)
    if email is not None:
        copy_.email = email
    return copy_


def send(users, template, context):
    from forum.utils.mail import send_template_email
    return send_template_email(list(users), template, dict(context))


def mask_email(email):
    """"n•••@example.com": enough for the owner to recognise, not to read."""
    local, _sep, domain = str(email or '').partition('@')
    if not domain:
        return '•••'
    return '%s•••@%s' % (local[:1], domain)


def over_limit(request, name, value):
    """Counts one account email for `value` (an account or address) and the
    visitor's IP address; True when either is over the hourly limit."""
    limit = int(settings.PASSWORD_RESETS_PER_HOUR)
    if limit <= 0:
        return False
    over_value = throttle.hit(name, value, 3600) > limit
    over_ip = throttle.hit(name + '-ip', throttle.client_ip(request), 3600) > limit * 4
    return over_value or over_ip


# -- confirming the email address --------------------------------------------------

def confirmation_mode():
    mode = str(settings.EMAIL_CONFIRMATION_MODE or DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def needs_confirmation(user):
    """Whether this member signed up and still has to confirm their address."""
    if not getattr(user, 'pk', None) or not getattr(user, 'email_confirmation_required', False):
        return False
    if user.email_isvalid or user.is_staff or user.is_superuser:
        return False
    return confirmation_mode() != 'off'


def must_confirm_to_sign_in(user):
    return needs_confirmation(user) and confirmation_mode() == 'signin'


def validation_required(user, item):
    """Whether `user` can't do `item` ('ask', 'answer', 'comment', 'flag')
    until their address is confirmed."""
    if getattr(user, 'email_isvalid', False):
        return False
    if item in list(settings.REQUIRE_EMAIL_VALIDATION_TO or []):
        return True
    return item in POSTING and needs_confirmation(user)


def shows_banner(user):
    """The "confirm your email address" banner: for members who can't post
    (or do something else) until they confirm."""
    return bool(getattr(user, 'is_authenticated', False)) and any(
        validation_required(user, item) for item in POSTING + ('flag',))


def send_confirmation(user, welcome=False):
    """A fresh confirmation link (the previous one stops working)."""
    from forum.models import ValidationHash
    ValidationHash.objects.filter(user=user, type='email').delete()
    code = ValidationHash.objects.create_new(user, 'email', [user.email],
                                             expiration=_now() + datetime.timedelta(hours=CONFIRM_HOURS))
    template = 'auth/welcome_email.html' if welcome else 'auth/mail_validation.html'
    send([user], template, {'validation_code': code, 'link_hours': CONFIRM_HOURS,
                            'must_confirm_to_sign_in': must_confirm_to_sign_in(user)})


def resend_confirmation(request, user):
    """Sends a new link unless the limit is reached; returns False when limited."""
    if over_limit(request, 'confirm', user.pk):
        security_log.event('confirmation_limited', request, logging.WARNING, account=user)
        return False
    send_confirmation(user)
    security_log.event('confirmation_sent', request, account=user)
    return True


def confirm_email(request, user, code):
    """Uses a confirmation link: 'confirmed', 'already' (the address is already
    confirmed) or 'invalid' (wrong, used or expired)."""
    from forum.actions import EmailValidationAction
    from forum.models import ValidationHash
    if ValidationHash.objects.validate(code, user, 'email', [user.email]):
        if not user.email_isvalid:
            EmailValidationAction(user=user, ip=request.META.get('REMOTE_ADDR', '')).save()
        if user.email_confirmation_required or not user.email_isvalid:
            user.email_isvalid = True
            user.email_confirmation_required = False
            user.save()
        security_log.event('email_confirmed', request, account=user)
        return 'confirmed'
    return 'already' if user.email_isvalid else 'invalid'


# -- changing the email address -----------------------------------------------------

PENDING_EMAIL_PROP = 'pending_email'


def pending_email(user):
    data = getattr(user.prop, PENDING_EMAIL_PROP)
    return data.get('email') if isinstance(data, dict) else None


def request_email_change(request, user, new_email):
    """Keeps the current address and emails a confirmation link to the new one,
    and a notice with a cancel link to the current one (if it was confirmed).
    Returns False when the hourly limit is reached."""
    from forum.models import ValidationHash
    if over_limit(request, 'email-change', user.pk):
        security_log.event('email_change_limited', request, logging.WARNING, account=user)
        return False
    ValidationHash.objects.filter(user=user, type__in=('newemail', 'emailcancel')).delete()
    setattr(user.prop, PENDING_EMAIL_PROP, {'email': new_email, 'requested': _now().isoformat()})
    expires = _now() + datetime.timedelta(hours=EMAIL_CHANGE_HOURS)
    code = ValidationHash.objects.create_new(user, 'newemail', [new_email], expiration=expires)
    send([recipient(user, new_email)], 'auth/email_change_confirm_email.html', {
        'confirm_code': code, 'new_email': new_email, 'link_hours': EMAIL_CHANGE_HOURS})
    if user.email and user.email_isvalid:
        cancel = ValidationHash.objects.create_new(user, 'emailcancel', [new_email], expiration=expires)
        send([user], 'auth/email_change_notice_email.html', {
            'cancel_code': cancel, 'new_email_masked': mask_email(new_email), 'link_hours': EMAIL_CHANGE_HOURS})
    security_log.event('email_change_requested', request, account=user)
    return True


def clear_pending_email(user):
    from forum.models import ValidationHash
    setattr(user.prop, PENDING_EMAIL_PROP, None)
    ValidationHash.objects.filter(user=user, type__in=('newemail', 'emailcancel')).delete()


def confirm_email_change(request, user, code):
    """Uses the link sent to the new address: 'changed', 'taken' (another
    account has it now) or 'invalid'."""
    from forum.actions import EmailValidationAction
    from forum.models import User, ValidationHash
    new_email = pending_email(user)
    if not new_email or not ValidationHash.objects.validate(code, user, 'newemail', [new_email]):
        return 'invalid'
    if settings.EMAIL_UNIQUE and User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        clear_pending_email(user)
        return 'taken'
    was_valid = user.email_isvalid
    user.email = new_email
    user.email_isvalid = True
    user.email_confirmation_required = False
    user.save()
    clear_pending_email(user)
    # Links sent to the old address stop working, password resets included.
    ValidationHash.objects.filter(user=user, type__in=('email', 'pwreset', 'templogin')).delete()
    if not was_valid:
        EmailValidationAction(user=user, ip=request.META.get('REMOTE_ADDR', '')).save()
    security_log.event('email_changed', request, account=user)
    return 'changed'


def cancel_email_change(request, user, code):
    """Uses the cancel link sent to the old address: the change is dropped and
    every session of the account is signed out. False if the link is invalid."""
    from forum.models import ValidationHash
    new_email = pending_email(user)
    if not new_email or not ValidationHash.objects.validate(code, user, 'emailcancel', [new_email]):
        return False
    clear_pending_email(user)
    sign_out_everywhere(user)
    # Whoever asked for the change may have made API tokens with the session: they are signed out too.
    from forum.models import ApiToken
    revoked = ApiToken.objects.filter(user=user).delete()[0]
    security_log.event('email_change_cancelled', request, logging.WARNING, account=user, tokens_revoked=revoked)
    return True


def notify_email_changed_by_admin(request, user, old_email):
    """An administrator changed the address: the old one is told."""
    if old_email:
        send([recipient(user, old_email)], 'auth/email_changed_by_admin_email.html', {
            'new_email_masked': mask_email(user.email)})


# -- passwords ------------------------------------------------------------------------

def _reset_data(user):
    last = user.last_login.replace(microsecond=0, tzinfo=None).isoformat() if user.last_login else ''
    return [user.pk, user.password, last]


def send_password_reset(user):
    from forum.models import ValidationHash
    ValidationHash.objects.filter(user=user, type__in=('pwreset', 'templogin')).delete()
    code = ValidationHash.objects.create_new(user, 'pwreset', _reset_data(user),
                                             expiration=_now() + datetime.timedelta(minutes=RESET_MINUTES))
    send([user], 'auth/password_reset_email.html', {'reset_code': code, 'link_minutes': RESET_MINUTES})


def check_reset_link(user, code, consume=False):
    from forum.models import ValidationHash
    return ValidationHash.objects.validate(code, user, 'pwreset', _reset_data(user), consume=consume)


def request_password_reset(request, email):
    """Emails a reset link to the accounts with this address. The answer
    is the same whether or not there are any; returns False when limited."""
    from forum.models import User
    if over_limit(request, 'reset', str(email).lower()):
        security_log.event('password_reset_limited', request, logging.WARNING, email=email)
        return False
    for user in User.objects.filter(email__iexact=email, is_active=True):
        send_password_reset(user)
        security_log.event('password_reset_requested', request, account=user)
    return True


def password_changed(request, user, how):
    """After a new password is saved (`how`: 'changed', 'reset', 'set' or
    'admin'): every other session ends and the member gets an email."""
    from forum.models import ValidationHash
    ValidationHash.objects.filter(user=user, type__in=('pwreset', 'templogin')).delete()
    throttle.reset('login-user', login_counter(user=user))
    current = getattr(request, 'user', None)
    if how != 'reset' and current is not None and current.pk == user.pk:
        # This session stays signed in (the password hash in it is renewed).
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, user)
        sign_out_everywhere(user, request, keep_current=True)
    else:
        sign_out_everywhere(user)
    revoked = 0
    if how in ('reset', 'admin'):
        # Whoever had the account may have made API tokens with it: a password
        # reset (or one set by an administrator) revokes them.
        from forum.models import ApiToken
        revoked = ApiToken.objects.filter(user=user).delete()[0]
    security_log.event({'changed': 'password_changed', 'reset': 'password_reset', 'set': 'password_set',
                        'admin': 'password_set_by_admin'}[how], request, account=user, tokens_revoked=revoked)
    send([user], 'auth/password_changed_email.html', {
        'how': how, 'when': _now(), 'browser': browser_summary(request), 'ip': throttle.client_ip(request)})


# -- sign-in lockout -----------------------------------------------------------------

def _account_pk(username):
    from forum.models import User
    return User.objects.filter(username=username).values_list('pk', flat=True).first()


def login_counter(username=None, user=None):
    """What the per-account sign-in lockout (throttle 'login-user') counts
    against: the account the typed name signs in to, so spellings the
    database takes for the same name (case and accents on MySQL) share one
    counter; the name itself when it is nobody's."""
    pk = user.pk if user is not None else _account_pk(username)
    return 'user:%d' % pk if pk else 'name:%s' % username


# -- sessions ---------------------------------------------------------------------------

def sign_out_everywhere(user, request=None, keep_current=False):
    """Ends every session of `user` (but the current one with `keep_current`)
    and stops browser push on all their devices: a lost phone or a shared
    computer must not keep showing their notifications. The member turns it
    on again where they want it."""
    from forum.models import PushSubscription
    user.session_epoch = (user.session_epoch or 0) + 1
    user.save()
    PushSubscription.objects.filter(user=user).delete()
    if request is not None and keep_current:
        request.session[EPOCH_SESSION_KEY] = user.session_epoch


def session_valid(request, user):
    return int(request.session.get(EPOCH_SESSION_KEY, 0) or 0) == int(user.session_epoch or 0)


def remember_choice(request, remember):
    """Remembers "Keep me signed in" between the sign-in form and the sign-in
    (which may wait for a two-step code)."""
    request.session[REMEMBER_SESSION_KEY] = bool(remember)


def signed_in(request, user):
    """After django.contrib.auth.login(): the session's epoch, when it signed
    in, and how long it lasts."""
    request.session[EPOCH_SESSION_KEY] = int(user.session_epoch or 0)
    request.session[AUTH_TIME_SESSION_KEY] = _now().isoformat()
    if not request.session.pop(REMEMBER_SESSION_KEY, True):
        request.session.set_expiry(0)  # ends when the browser closes


def reauth_minutes():
    """How long a sign-in (or a "Confirm it's you") counts as recent: the REAUTH_MINUTES setting."""
    try:
        return max(1, int(settings.REAUTH_MINUTES))
    except (TypeError, ValueError):
        return RECENT_AUTH_MINUTES


def recently_signed_in(request, minutes=None):
    """Whether this session signed in or confirmed it's the member (forum/utils/sudo.py)
    within the last `minutes` (default: the REAUTH_MINUTES setting)."""
    try:
        when = datetime.datetime.fromisoformat(request.session.get(AUTH_TIME_SESSION_KEY) or '')
    except (ValueError, TypeError):
        return False
    return _now() - when < datetime.timedelta(minutes=minutes or reauth_minutes())


def mark_reauthenticated(request, method):
    """The member has just proved it's them again (password, code, passkey or emailed link)."""
    request.session[AUTH_TIME_SESSION_KEY] = _now().isoformat()
    security_log.event('reauthenticated', request, account=request.user, method=method)


# -- security notices ----------------------------------------------------------------------

SECURITY_CHANGES = ('passkey_added', 'two_factor_on', 'two_factor_off', 'recovery_codes', 'api_token', 'sign_in_added')


def security_notice(request, user, change, name='', by_admin=False):
    """Emails `user` that `change` (SECURITY_CHANGES) was made to their account
    (always sent, like the other account emails), with where to check and undo it."""
    if not user.email:
        return
    send([user], 'auth/security_change_email.html', {
        'change': change, 'name': name, 'by_admin': by_admin, 'when': _now(), 'browser': browser_summary(request),
        'ip': throttle.client_ip(request)})


# -- sign-ins from new browsers -----------------------------------------------------------

def browser_summary(request):
    """"Firefox on Windows": a rough description of the visitor's browser."""
    agent = request.META.get('HTTP_USER_AGENT', '') if request is not None else ''
    browser = next((name for token, name in (('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'),
                                              ('Chrome/', 'Chrome'), ('Safari/', 'Safari')) if token in agent),
                   _('an unknown browser'))
    system = next((name for token, name in (('Windows', 'Windows'), ('Android', 'Android'), ('iPhone', 'iPhone'),
                                             ('iPad', 'iPad'), ('Mac OS X', 'macOS'), ('CrOS', 'ChromeOS'),
                                             ('Linux', 'Linux')) if token in agent), None)
    return _('%(browser)s on %(system)s') % {'browser': browser, 'system': system} if system else browser


def _device_id(request):
    try:
        value = signing.loads(request.COOKIES.get(DEVICE_COOKIE, ''), salt=DEVICE_SALT)
    except signing.BadSignature:
        return None
    return value if isinstance(value, str) and value else None


def note_device(request, response, user):
    """With NEW_DEVICE_SIGNIN_EMAIL on: emails the member when they sign in
    from a browser that hasn't signed in to their account before (the first
    browser ever is only remembered). Browsers are told apart by a random id
    in a long-lived cookie; the account keeps hashes of its last 20."""
    if not bool(settings.NEW_DEVICE_SIGNIN_EMAIL) or response is None:
        return
    device = _device_id(request)
    if device is None:
        device = secrets.token_urlsafe(18)
        response.set_cookie(DEVICE_COOKIE, signing.dumps(device, salt=DEVICE_SALT), max_age=DEVICE_COOKIE_AGE,
                            httponly=True, secure=bool(getattr(djsettings, 'SESSION_COOKIE_SECURE', False)),
                            samesite='Lax')
    key = hashlib.sha256(('%s:%s' % (user.pk, device)).encode('utf-8')).hexdigest()[:32]
    known = [k for k in (user.prop.known_devices or []) if isinstance(k, str)]
    if key in known:
        return
    if known and user.email:
        send([user], 'auth/new_signin_email.html', {
            'when': _now(), 'browser': browser_summary(request), 'ip': throttle.client_ip(request)})
        security_log.event('new_device_signin', request, account=user)
    user.prop.known_devices = ([key] + known)[:MAX_DEVICES]
