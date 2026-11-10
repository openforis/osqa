# -*- coding: utf-8 -*-

import datetime
import logging
import urllib.parse
from urllib.parse import urlparse

from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from forum.utils.urls import root_relative_reverse
from django.http import HttpResponseRedirect, Http404
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.encoding import smart_str
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth import login, logout
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.utils.text import slugify

from django.contrib import messages

from .writers import manage_pending_data

from forum.utils import html
from forum.forms import PublicRegistrationForm, TemporaryLoginRequestForm, ChangePasswordForm, SetPasswordForm
from forum.forms.general import DescribedFieldsMixin
from forum.forms.general import clean_next, username_for_signin
from forum.http_responses import HttpResponseUnauthorized
from forum.utils.redact import redact_meta
from forum.authentication.base import InvalidAuthentication
from forum.authentication import AUTH_PROVIDERS
from forum.models import User, AuthKeyUserAssociation, ValidationHash
from forum.actions import UserJoinsAction, UserLoginAction
from forum.utils.antispam import signup_limit_reached, count_signup
from forum.utils import accounts, security_log, sudo, throttle, two_factor
from forum import settings

from .vars import ON_SIGNIN_SESSION_ATTR, PENDING_SUBMISSION_SESSION_ATTR

SIGNIN_USERNAME_SESSION_ATTR = 'auth_username'


def signin_providers(request):
    """The enabled sign-in methods the visitor can use, by how the sign-in page shows them."""
    # Providers that need configuration (e.g. OAuth client keys) define is_enabled().
    all_providers = [provider.context for provider in AUTH_PROVIDERS.values()
                     if provider.context and getattr(provider.context, 'is_enabled', lambda: True)()]
    can_show = lambda c: not request.user.is_authenticated or c.show_to_logged_in_user
    by_mode = lambda *modes: sorted([c for c in all_providers if c.mode in modes and can_show(c)],
                                    key=lambda c: c.weight)
    return {
        'all_providers': all_providers,
        # Buttons ("Continue with Google"), then the forms (username and password).
        'button_providers': by_mode('BIGICON', 'SMALLICON'),
        'top_stackitem_providers': by_mode('TOP_STACK_ITEM'),
        'stackitem_providers': by_mode('STACK_ITEM'),
    }


def signin_page(request):
    referer = request.META.get('HTTP_REFERER', '/')

    # Where to go after signing in: the page given by ?next=, or else the page
    # the visitor came from. The referer is sent by the browser and may point
    # to another site; it is only used when it is on this site, and not when
    # it is one of the sign-in pages (e.g. after a failed attempt, or coming
    # back from the sign-up page).
    on_this_site = url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure())
    account_pages = reverse('auth_signin')[:-len('signin/')]

    if request.GET.get('next'):
        request.session[ON_SIGNIN_SESSION_ATTR] = clean_next(request.GET['next'])
    elif on_this_site and not urlparse(referer).path.startswith(account_pages):
        request.session[ON_SIGNIN_SESSION_ATTR] = referer

    context = signin_providers(request)
    context['msg'] = request.session.pop('auth_error', None)
    # What was typed in "Username or email" before a failed attempt.
    context['username'] = request.session.pop(SIGNIN_USERNAME_SESSION_ATTR, '')
    context['can_register'] = 'local' in AUTH_PROVIDERS and not request.user.is_authenticated
    return render(request, 'auth/signin.html', context)

def login_paused(request, username):
    limit = int(settings.LOGIN_FAILURES_LIMIT)
    return limit > 0 and (throttle.count('login-user', accounts.login_counter(username)) >= limit or
                          throttle.count('login-ip', throttle.client_ip(request)) >= limit * 4)


def count_login_failure(request, username):
    seconds = int(settings.LOGIN_LOCKOUT_MINUTES) * 60
    throttle.hit('login-user', accounts.login_counter(username), seconds)
    throttle.hit('login-ip', throttle.client_ip(request), seconds)


def prepare_provider_signin(request, provider):
    # Signed in, this links another way to sign in to the account: only after
    # "Confirm it's you" (a stolen session must not add the thief's login).
    if request.user.is_authenticated:
        refused = sudo.require_recent_auth(request, reverse('user_add_external_provider'))
        if refused:
            return refused
    if provider in AUTH_PROVIDERS:
        provider_class = AUTH_PROVIDERS[provider].consumer

        try:
            request_url = provider_class.prepare_authentication_request(request,
                                                                        root_relative_reverse('auth_provider_done',
                                                                                kwargs={'provider': provider}))

            return HttpResponseRedirect(request_url)
        except NotImplementedError as e:
            return process_provider_signin(request, provider)
        except InvalidAuthentication as e:
            request.session['auth_error'] = e.message

        return HttpResponseRedirect(reverse('auth_signin'))
    else:
        raise Http404()


def process_provider_signin(request, provider):
    if provider in AUTH_PROVIDERS:
        provider_class = AUTH_PROVIDERS[provider].consumer

        # Password sign-ins (local, LDAP) are paused after too many failures.
        typed = request.POST.get('username', '').strip() if request.method == 'POST' and \
            'password' in request.POST else None
        # Local accounts also sign in with their email address: count failures
        # against the account, whichever of the two was typed.
        username = username_for_signin(typed) if provider == 'local' else typed
        if typed is not None:
            accounts.remember_choice(request, request.POST.get('remember') == '1')
        if username and login_paused(request, username):
            security_log.event('login_paused', request, logging.WARNING, provider=provider, username=username)
            request.session['auth_error'] = _(
                "Too many failed sign-in attempts. Wait %(minutes)s minutes and try again, or use \"Forgot your "
                "password?\" to choose a new password.") % {'minutes': int(settings.LOGIN_LOCKOUT_MINUTES)}
            request.session[SIGNIN_USERNAME_SESSION_ATTR] = typed
            return HttpResponseRedirect(reverse('auth_signin'))

        try:
            assoc_key = provider_class.process_authentication_request(request)
        except InvalidAuthentication as e:
            suspended = username and suspended_account(username, request.POST.get('password', ''))
            if suspended:
                throttle.reset('login-user', accounts.login_counter(username))
                return login_and_forward(request, suspended)
            if username:
                count_login_failure(request, username)
                security_log.event('login_failed', request, logging.WARNING, provider=provider, username=username)
                request.session[SIGNIN_USERNAME_SESSION_ATTR] = typed
            request.session['auth_error'] = e.message
            return HttpResponseRedirect(reverse('auth_signin'))

        if username:
            throttle.reset('login-user', accounts.login_counter(username))

        if request.user.is_authenticated:
            if isinstance(assoc_key, (type, User)):
                if request.user != assoc_key:
                    request.session['auth_error'] = _(
                            "Sorry, these login credentials belong to anoother user. Plese terminate your current session and try again."
                            )
                else:
                    request.session['auth_error'] = _("You are already logged in with that user.")
            else:
                try:
                    assoc = AuthKeyUserAssociation.objects.get(key=assoc_key)
                    if assoc.user == request.user:
                        request.session['auth_error'] = _(
                                "These login credentials are already associated with your account.")
                    else:
                        request.session['auth_error'] = _(
                                "Sorry, these login credentials belong to anoother user. Plese terminate your current session and try again."
                                )
                except AuthKeyUserAssociation.DoesNotExist:
                    refused = sudo.require_recent_auth(request, reverse('user_add_external_provider'))
                    if refused:
                        return refused
                    uassoc = AuthKeyUserAssociation(user=request.user, key=assoc_key, provider=provider)
                    uassoc.save()
                    accounts.security_notice(request, request.user, 'sign_in_added',
                                             name=getattr(AUTH_PROVIDERS[provider].context, 'human_name', '') or provider)
                    security_log.event('sign_in_added', request, account=request.user, provider=provider)
                    messages.info(request, _('The new credentials are now associated with your account'))
                    return HttpResponseRedirect(reverse('user_authsettings', args=[request.user.id]))

            return HttpResponseRedirect(reverse('auth_signin'))
        else:
            if isinstance(assoc_key, User):
                return login_and_forward(request, assoc_key)

        try:
            assoc = AuthKeyUserAssociation.objects.get(key=assoc_key)
            user_ = assoc.user
            return login_and_forward(request, user_)
        except AuthKeyUserAssociation.DoesNotExist:
            request.session['assoc_key'] = assoc_key
            request.session['auth_provider'] = provider
            return HttpResponseRedirect(reverse('auth_external_register'))

    return HttpResponseRedirect(reverse('auth_signin'))

def external_register(request):
    if request.method == 'POST' and 'bnewaccount' in request.POST:
        form1 = PublicRegistrationForm(request.POST)

        if signup_limit_reached(request):
            form1.add_error(None, _("Too many accounts have been created from your network recently. Please try again later."))
        elif form1.is_valid():
            user_ = User(username=form1.cleaned_data['username'], email=form1.cleaned_data['email'], real_name=form1.cleaned_data['real_name'])
            user_.email_isvalid = request.session.get('auth_validated_email', '') == form1.cleaned_data['email']
            user_.set_unusable_password()

            if User.objects.all().count() == 0:
                user_.is_superuser = True
                user_.is_staff = True
            # Double opt-in, unless the sign-in service confirmed the address (or this is the site owner).
            user_.email_confirmation_required = not (user_.email_isvalid or user_.is_superuser)

            user_.save()
            count_signup(request)
            UserJoinsAction(user=user_, ip=request.META['REMOTE_ADDR']).save()

            try:
                assoc_key = request.session['assoc_key']
                auth_provider = request.session['auth_provider']
            except:
                request.session['auth_error'] = _(
                        "Oops, something went wrong in the middle of this process. Please try again. Note that you need to have cookies enabled for the authentication to work."
                        )
                logging.error("Missing session data when trying to complete user registration: %s" % ", ".join(
                        ["%s: %s" % (k, v) for k, v in redact_meta(request.META)]))
                return HttpResponseRedirect(reverse('auth_signin'))

            uassoc = AuthKeyUserAssociation(user=user_, key=assoc_key, provider=auth_provider)
            uassoc.save()

            del request.session['assoc_key']
            del request.session['auth_provider']

            if accounts.must_confirm_to_sign_in(user_):
                return HttpResponseRedirect(reverse('auth_check_email'))
            return login_and_forward(request, user_, message=welcome_message(user_))
    else:
        auth_provider = request.session.get('auth_provider', None)
        if not auth_provider:
            request.session['auth_error'] = _(
                    "Oops, something went wrong in the middle of this process. Please try again.")
            logging.error("Missing session data when trying to complete user registration: %s" % ", ".join(
                    ["%s: %s" % (k, v) for k, v in redact_meta(request.META)]))
            return HttpResponseRedirect(reverse('auth_signin'))

        provider_class = AUTH_PROVIDERS[auth_provider].consumer

        user_data = provider_class.get_user_data(request.session['assoc_key'])

        if not user_data:
            user_data = request.session.get('auth_consumer_data', {})

        username = user_data.get('username', '')
        email = user_data.get('email', '')
        real_name = user_data.get('real_name', '')

        # Only treat the address as validated when the provider says it verified it.
        if email and user_data.get('email_verified', True):
            request.session['auth_validated_email'] = email

        form1 = PublicRegistrationForm(initial={
        'next': '/',
        'username': username,
        'email': email,
        'real_name': real_name
        })

    provider_context = AUTH_PROVIDERS[request.session['auth_provider']].context

    return render(request, 'auth/complete.html', {
    'form1': form1,
    'provider':provider_context and mark_safe(provider_context.human_name) or _('unknown'),
    'login_type':provider_context.id,
    'gravatar_faq_url':reverse('faq') + '#gravatar',
    })

def request_temp_login(request):
    """"Forgot your password?": emails a link to choose a new password. The
    answer is the same whether or not the address has an account."""
    if request.method == 'POST':
        form = TemporaryLoginRequestForm(request.POST)

        if form.is_valid():
            if not accounts.request_password_reset(request, form.cleaned_data['email']):
                messages.error(request, _("Too many password reset emails were requested. Please try again in an "
                                          "hour."))
                return render(request, 'auth/temp_login_request.html', {'form': form})
            return render(request, 'auth/check_email.html', {
                'kind': 'reset', 'link_minutes': accounts.RESET_MINUTES})
    else:
        form = TemporaryLoginRequestForm()

    return render(request, 'auth/temp_login_request.html', {'form': form})


@never_cache
def temp_signin(request, user, code):
    """The link of the password reset email: a form for the new password (and
    the two-step code, if the member uses it). Opening the link changes
    nothing, so mail scanners that open links don't use it up; the password
    is only changed, and the link used up, when the form is sent. Then every
    session of the account is signed out and the member signs in again."""
    user = User.objects.filter(id=user).first()
    if user is None or user.is_suspended() or not accounts.check_reset_link(user, code):
        return render(request, 'auth/link_invalid.html', {'kind': 'reset'}, status=410)

    needs_code = two_factor.is_enabled(user)
    code_error = None
    if request.method == 'POST':
        form = SetPasswordForm(request.POST, user=user)
        result = None
        # The code is checked (and a recovery code used up) only once the new
        # password is acceptable, so a typo in it costs no code.
        if needs_code and form.is_valid():
            result = two_factor.check_code(request, user, request.POST.get('code', ''), 'password_reset')
            if result == two_factor.PAUSED:
                code_error = _("Too many wrong codes. Wait %(minutes)s minutes and try again.") % {
                    'minutes': two_factor.lockout_minutes()}
            elif result not in (two_factor.OK_TOTP, two_factor.OK_RECOVERY):
                code_error = _("That code is not right. Enter the newest code from your app, or a recovery code.")
        if form.is_valid() and not code_error and accounts.check_reset_link(user, code, consume=True):
            user.set_password(form.cleaned_data['password1'])
            user.save()
            accounts.password_changed(request, user, 'reset')
            if request.user.is_authenticated:
                logout(request)
            request.session[SIGNIN_USERNAME_SESSION_ATTR] = user.username
            messages.info(request, _("Your password has been changed and you were signed out everywhere. Sign in "
                                     "with your new password."))
            return HttpResponseRedirect(reverse('auth_signin'))
    else:
        form = SetPasswordForm(user=user)
    form.fields['password1'].label = _('New password')
    form.fields['password2'].label = _('Confirm new password')
    DescribedFieldsMixin.describe_fields(form)
    return render(request, 'auth/password_reset.html', {
        'form': form, 'reset_user': user, 'needs_code': needs_code, 'code_error': code_error,
        'has_password': user.has_usable_password(),
    })


def send_validation_email(request):
    """"Confirm your email address": shows where the link was sent, and sends a
    new one (POST). Signed-out visitors (who can't sign in before confirming)
    type their address; the answer is the same whether or not it has an account."""
    signed_in = request.user.is_authenticated
    if request.method == 'POST':
        if signed_in:
            user = request.user
            if user.email_isvalid:
                messages.info(request, _("Your email address is already confirmed."))
            elif accounts.resend_confirmation(request, user):
                messages.info(request, _("We sent a new confirmation link to %(email)s. It works for %(hours)d "
                                         "hours.") % {'email': escape(user.email), 'hours': accounts.CONFIRM_HOURS})
            else:
                messages.error(request, _("Too many confirmation emails were sent. Please try again in an hour."))
            return HttpResponseRedirect(clean_next(request.POST.get('next')) if request.POST.get('next')
                                        else reverse('send_validation_email'))
        form = TemporaryLoginRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            if accounts.over_limit(request, 'confirm-email', email.lower()):
                messages.error(request, _("Too many confirmation emails were sent. Please try again in an hour."))
            else:
                for user in User.objects.filter(email__iexact=email, is_active=True, email_isvalid=False):
                    accounts.send_confirmation(user)
                    security_log.event('confirmation_sent', request, account=user)
                return render(request, 'auth/check_email.html', {'kind': 'confirm',
                                                                  'link_hours': accounts.CONFIRM_HOURS})
    else:
        form = TemporaryLoginRequestForm()

    return render(request, 'auth/confirm_email.html', {
        'form': form,
        'link_hours': accounts.CONFIRM_HOURS,
        'pending_email': accounts.pending_email(request.user) if signed_in else None,
    })


@never_cache
def validate_email(request, user, code):
    """The link of the welcome / confirmation email. Works signed out too; it
    never signs anyone in."""
    user = get_object_or_404(User, id=user)
    result = accounts.confirm_email(request, user, code)
    if result == 'confirmed' and request.user.is_authenticated and request.user.pk == user.pk:
        request.user.email_isvalid = True
        request.user.email_confirmation_required = False
        pending = request.session.get(PENDING_SUBMISSION_SESSION_ATTR)
        if pending and not accounts.validation_required(user, pending['type']):
            # A question or answer written before confirming is published now.
            messages.info(request, _("Thank you, your email address is confirmed."))
            return manage_pending_data(request, _('save'), reverse('index'))
    status = 410 if result == 'invalid' else 200
    return render(request, 'auth/email_confirmed.html', {
        'result': result, 'confirmed_user': user,
        'signed_in_as_them': request.user.is_authenticated and request.user.pk == user.pk,
        'link_hours': accounts.CONFIRM_HOURS,
    }, status=status)


@never_cache
def confirm_email_change(request, user, code):
    """The link sent to the new address of an email change."""
    user = get_object_or_404(User, id=user)
    result = accounts.confirm_email_change(request, user, code)
    return render(request, 'auth/email_change_result.html', {
        'result': result, 'changed_user': user,
        'signed_in_as_them': request.user.is_authenticated and request.user.pk == user.pk,
    }, status=410 if result == 'invalid' else 200)


@never_cache
def cancel_email_change(request, user, code):
    """The cancel link sent to the old address. GET only asks, so mail scanners
    that open links cancel nothing; POST cancels and signs out everywhere."""
    user = get_object_or_404(User, id=user)
    new_email = accounts.pending_email(user)
    if not new_email or not ValidationHash.objects.validate(code, user, 'emailcancel', [new_email], consume=False):
        return render(request, 'auth/link_invalid.html', {'kind': 'email_cancel'}, status=410)
    if request.method == 'POST':
        accounts.cancel_email_change(request, user, code)
        if request.user.is_authenticated and request.user.pk == user.pk:
            logout(request)
        return render(request, 'auth/email_change_result.html', {'result': 'cancelled', 'changed_user': user})
    return render(request, 'auth/email_change_cancel.html', {
        'changed_user': user, 'new_email_masked': accounts.mask_email(new_email)})


@require_POST
def pending_email_change(request):
    """Resend or cancel the confirmation of the member's own new address (edit profile page)."""
    if not request.user.is_authenticated:
        return HttpResponseRedirect(reverse('auth_signin'))
    user = request.user
    new_email = accounts.pending_email(user)
    if new_email and request.POST.get('action') == 'resend':
        if accounts.request_email_change(request, user, new_email):
            messages.info(request, _("We sent the confirmation link to %s again.") % escape(new_email))
        else:
            messages.error(request, _("Too many emails were sent. Please try again in an hour."))
    elif new_email:
        accounts.clear_pending_email(user)
        security_log.event('email_change_withdrawn', request, account=user)
        messages.info(request, _("The change of your email address was cancelled."))
    return HttpResponseRedirect(reverse('edit_user', kwargs={'id': user.id, 'slug': slugify(user.username)}))


def auth_settings(request, id):
    user_ = get_object_or_404(User, id=id)

    if not (request.user.is_superuser or request.user == user_):
        return HttpResponseUnauthorized(request)

    auth_keys = user_.auth_keys.all()

    if request.user.is_superuser or (not user_.has_usable_password()):
        FormClass = SetPasswordForm
    else:
        FormClass = ChangePasswordForm

    if request.POST:
        if FormClass is SetPasswordForm:
            # No old password asked: "Confirm it's you" instead (a stolen session
            # must not be able to set a password and keep the account).
            refused = sudo.require_recent_auth(request, reverse('user_authsettings', kwargs={'id': user_.id}))
            if refused:
                return refused
        form = FormClass(request.POST, user=user_)
        if 'oldpw' in form.fields and login_paused(request, user_.username):
            form.is_valid()
            form.add_error('oldpw', _("Too many wrong passwords. Wait %(minutes)s minutes and try again.") % {
                'minutes': int(settings.LOGIN_LOCKOUT_MINUTES)})
        elif form.is_valid():
            is_new_pass = not user_.has_usable_password()
            user_.set_password(form.cleaned_data['password1'])
            user_.save()
            # Other sessions of this account are signed out; this one stays. The member gets an email.
            accounts.password_changed(request, user_, 'admin' if request.user != user_ else
                                      'set' if is_new_pass else 'changed')

            if is_new_pass:
                messages.info(request, _("New password set"))
                if not request.user.is_superuser:
                    form = ChangePasswordForm(user=user_)
            else:
                messages.info(request, _("Your password was changed"))

            return HttpResponseRedirect(reverse('user_authsettings', kwargs={'id': user_.id}))
        elif 'oldpw' in form.errors:
            count_login_failure(request, user_.username)
            security_log.event('password_change_failed', request, logging.WARNING, account=user_)
    else:
        form = FormClass(user=user_)

    auth_keys_list = []

    for k in auth_keys:
        provider = AUTH_PROVIDERS.get(k.provider, None)

        if provider is not None:
            name =  "%s: %s" % (provider.context.human_name, provider.context.readable_key(k))
        else:
            from forum.authentication.base import ConsumerTemplateContext
            "unknown: %s" % ConsumerTemplateContext.readable_key(k)

        auth_keys_list.append({
        'name': name,
        'id': k.id
        })

    # Help texts and errors linked to their inputs, as on the sign-up page.
    DescribedFieldsMixin.describe_fields(form)

    return render(request, 'auth/auth_settings.html', {
    'view_user': user_,
    "can_view_private": (user_ == request.user) or request.user.is_superuser,
    'form': form,
    'has_password': user_.has_usable_password(),
    'auth_keys': auth_keys_list,
    'allow_local_auth': AUTH_PROVIDERS.get('local', None),
    })

@require_POST
def remove_external_provider(request, id):
    association = get_object_or_404(AuthKeyUserAssociation, id=id)
    if not (request.user.is_superuser or request.user == association.user):
        return HttpResponseUnauthorized(request)
    from forum.utils import sudo
    if sudo.sign_in_methods(association.user) <= 1:
        # The last way to sign in: removing it locks the account.
        refused = sudo.require_recent_auth(request, reverse('user_authsettings', kwargs={'id': association.user.id}))
        if refused:
            return refused

    messages.info(request, _("You removed the association with %s") % association.provider)
    association.delete()
    return HttpResponseRedirect(reverse('user_authsettings', kwargs={'id': association.user.id}))

def welcome_message(user):
    if accounts.needs_confirmation(user):
        return _("Welcome! We've emailed you a link to confirm your address. Confirm it to ask, answer and comment.")
    return _("Welcome! Your account is ready.")


def login_and_forward(request, user, forward=None, message=None, two_factor_method=None, after_two_factor=()):
    """Signs `user` in and redirects. Members with two-step verification on
    are sent to the code page first, unless `two_factor_method` says how
    they already passed it ('totp', 'recovery' or 'passkey'). `after_two_factor`
    names account changes the code page makes once the code is right
    (two_factor.AFTER_RESET_PASSWORD). New members who must confirm their
    address before signing in (EMAIL_CONFIRMATION_MODE 'signin') get a new
    link instead."""
    if user.is_suspended():
        return forward_suspended_user(request, user)

    if accounts.must_confirm_to_sign_in(user):
        sent = accounts.resend_confirmation(request, user)
        security_log.event('login_unconfirmed', request, account=user)
        request.session.pop(accounts.REMEMBER_SESSION_KEY, None)
        if sent:
            messages.info(request, _("Please confirm your email address first. We sent a new link to the address "
                                     "you signed up with."))
        else:
            messages.error(request, _("Please confirm your email address first, with the link we emailed you."))
        return HttpResponseRedirect(reverse('auth_check_email'))

    if two_factor_method is None and two_factor.is_enabled(user):
        two_factor.start_pending(request, user, forward, message, after_two_factor)
        security_log.event('two_factor_required', request, account=user)
        return HttpResponseRedirect(reverse('auth_two_factor'))

    user.backend = "django.contrib.auth.backends.ModelBackend"
    login(request, user)  # a new session key: no session fixation
    accounts.signed_in(request, user)
    two_factor.clear_pending(request)
    if two_factor_method:
        request.session[two_factor.METHOD_SESSION_KEY] = two_factor_method

    # Store the login action
    UserLoginAction(user=user, ip=request.META['REMOTE_ADDR']).save()

    response = _forward_after_login(request, user, forward, message)
    accounts.note_device(request, response, user)
    return response


def _forward_after_login(request, user, forward, message):
    if message is None:
        message = _("Welcome back, %s! You're signed in.") % escape(smart_str(user.username))

    messages.info(request, message)

    if not forward:
        forward = request.session.get(ON_SIGNIN_SESSION_ATTR, reverse('index'))

    pending_data = request.session.get(PENDING_SUBMISSION_SESSION_ATTR, None)

    if pending_data and not accounts.validation_required(user, pending_data['type']):
        submission_time = datetime.datetime.fromisoformat(pending_data['time'])
        if submission_time < datetime.datetime.now() - datetime.timedelta(minutes=int(settings.HOLD_PENDING_POSTS_MINUTES)):
            del request.session[PENDING_SUBMISSION_SESSION_ATTR]
        elif submission_time < datetime.datetime.now() - datetime.timedelta(minutes=int(settings.WARN_PENDING_POSTS_MINUTES)):
            messages.info(request, (_("You have a %s pending submission.") % pending_data['data_name']) + " %s, %s, %s" % (
                html.hyperlink(reverse('manage_pending_data', kwargs={'action': _('save')}), _("save it")),
                html.hyperlink(reverse('manage_pending_data', kwargs={'action': _('review')}), _("review")),
                html.hyperlink(reverse('manage_pending_data', kwargs={'action': _('cancel')}), _("cancel"))
            ))
        else:
            return manage_pending_data(request, _('save'), forward)

    additional_get_params = urllib.parse.urlencode(dict([k, v.encode('utf-8')] for k, v in request.GET.items()))

    parsed_forward = urlparse(forward)

    # If there is already some parsed query in the URL then change the forward URL
    if parsed_forward.query:
        forward_url = forward + "&%s" % additional_get_params
    else:
        forward_url = forward + "?%s" % additional_get_params

    return HttpResponseRedirect(forward_url)

def suspended_account(username, password):
    """The suspended account `username` if `password` is its password, else None.

    Django refuses to authenticate inactive (suspended) accounts, so without
    this the person would only read "invalid password": they get the
    suspension message instead, and are signed in if the suspension has ended.
    """
    try:
        user = User.objects.get(username=username, is_active=False)
    except User.DoesNotExist:
        return None
    if user.suspension is None or not user.check_password(password):
        return None
    if not user.is_suspended():  # the suspension has just been lifted
        user = User.objects.filter(id=user.id).first()
    return user

def forward_suspended_user(request, user, show_private_msg=True):
    message = _("Sorry, but this account is suspended")
    if show_private_msg:
        msg_type = 'privatemsg'
    else:
        msg_type = 'publicmsg'

    suspension = user.suspension
    if suspension:
        message += (":<br />" + escape(suspension.extra.get(msg_type, '')))

    messages.info(request, message)
    return HttpResponseRedirect(reverse('index'))

def check_email(request):
    """"Check your inbox" after signing up when the address must be confirmed
    before signing in (also shown when such an account tries to sign in)."""
    return render(request, 'auth/check_email.html', {'kind': 'signup', 'link_hours': accounts.CONFIRM_HOURS})


def _local_next(value):
    """A path on this site to go to, or '' (clean_next falls back to a full URL)."""
    value = clean_next(value) if value else ''
    return value if value.startswith('/') else ''


def signout(request):
    """Signing out is a POST (with the CSRF token), so no link or image on
    another site can sign people out; GET shows the confirmation page.
    "everywhere" also ends the member's other sessions."""
    if request.method != 'POST':
        if not request.user.is_authenticated:
            return HttpResponseRedirect(reverse('index'))
        return render(request, 'logout.html', {'next': _local_next(request.GET.get('next'))})
    if request.user.is_authenticated:
        user = request.user
        if request.POST.get('everywhere') == '1':
            accounts.sign_out_everywhere(user)
            security_log.event('signout_everywhere', request, account=user)
        logout(request)  # the session is deleted and the cookie gets a new key
    forward = _local_next(request.POST.get('next')) or reverse('index')
    messages.info(request, _("You're signed out."))
    return HttpResponseRedirect(forward)


@require_POST
def signout_others(request):
    """"Sign out of all other sessions" on the security page."""
    if not request.user.is_authenticated:
        return HttpResponseRedirect(reverse('auth_signin'))
    accounts.sign_out_everywhere(request.user, request, keep_current=True)
    security_log.event('signout_other_sessions', request, account=request.user)
    messages.info(request, _("You're signed out on every other browser and device. This one stays signed in."))
    return HttpResponseRedirect(reverse('user_security', kwargs={'id': request.user.id}))
