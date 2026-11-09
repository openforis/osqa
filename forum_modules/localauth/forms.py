from forum.forms import NextUrlField, UserNameField, UserEmailField, SetPasswordForm
from forum.forms.auth import SignUpFieldsMixin
from forum.forms.general import username_for_signin
from forum.utils.antispam import BotTrapMixin
from forum.modules import call_all_handlers
from django.utils.translation import gettext as _
from django.contrib.auth import authenticate
from django import forms

class ClassicRegisterForm(BotTrapMixin, SignUpFieldsMixin, SetPasswordForm):
    """ legacy registration form """
    # The order of the page, also used by the error summary.
    field_order = ['username', 'email', 'password1', 'password2']

    next = NextUrlField()
    username = UserNameField()
    email = UserEmailField()

    def __init__(self, *args, check_email_taken=True, **kwargs):
        super().__init__(*args, **kwargs)
        # The sign-up view may answer a taken address like a new one instead.
        self.fields['email'].skip_clean = not check_email_taken

        # Try importing the ReCapthca public and private keys, Import Error will be raised in case it has been disabled
        try:
            from forum.settings import RECAPTCHA_PUB_KEY, RECAPTCHA_PRIV_KEY
            recaptcha_enabled = len(str(RECAPTCHA_PUB_KEY.value)) > 0 and len(str(RECAPTCHA_PRIV_KEY.value)) > 0
        except ImportError:
            recaptcha_enabled = False

        if recaptcha_enabled:
            spam_fields = call_all_handlers('create_anti_spam_field')
            if spam_fields:
                spam_fields = dict(spam_fields)
                for name, field in spam_fields.items():
                    self.fields[name] = field

                self._anti_spam_fields = spam_fields.keys()
            else:
                self._anti_spam_fields = []

    def anti_spam_fields(self):
        return [self[name] for name in self._anti_spam_fields]

class ClassicLoginForm(forms.Form):
    """ legacy account signin form """
    next = NextUrlField()
    username = UserNameField(required=False, skip_clean=True)
    password = forms.CharField(max_length=128,
                               widget=forms.widgets.PasswordInput(attrs={'class':'required login'}),
                               required=False)

    def __init__(self, data=None, files=None, auto_id='id_%s',
                 prefix=None, initial=None):
        super().__init__(data, files, auto_id,
                                               prefix, initial)
        self.user_cache = None

    def _clean_nonempty_field(self, field):
        value = None
        if field in self.cleaned_data:
            # None when the request has no such field (bots GET the sign-in URL)
            value = (self.cleaned_data[field] or '').strip()
            if value == '':
                value = None
        self.cleaned_data[field] = value
        return value

    def clean_username(self):
        return self._clean_nonempty_field('username')

    def clean_password(self):
        return self._clean_nonempty_field('password')

    def clean(self):
        error_list = []
        username = self.cleaned_data['username']
        password = self.cleaned_data['password']

        self.user_cache = None
        if username and password:
            user_ = authenticate(username=username_for_signin(username), password=password)

            if user_ is None:
                del self.cleaned_data['username']
                del self.cleaned_data['password']
                error_list.append(_("That username or email and password don't match. Check them and try again "
                                    "(the password is case-sensitive)."))
            else:
                try:
                    self.user_cache = user_.user
                except Exception:
                    error_list.append(_("This account can't sign in here. Please contact the site administrators."))

        elif password is None and username is None:
            error_list.append(_('Enter your username or email and your password.'))
        elif password is None:
            error_list.append(_('Enter your password.'))
        elif username is None:
            error_list.append(_('Enter your username or email.'))
        if len(error_list) > 0:
            self._errors['__all__'] = forms.utils.ErrorList(error_list)

        return self.cleaned_data

    def get_user(self):
        """ get authenticated user """
        return self.user_cache
