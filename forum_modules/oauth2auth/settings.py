from django.utils.translation import gettext_lazy as _

from forum.settings import EXT_KEYS_SET
from forum.settings.base import Setting
from forum.settings.forms import SecretInput
from forum.settings.guides import Section, register, keys_status, WARNING

# Each provider shows up on the sign-in page once its client id and secret are
# set. Register the redirect URI <APP_URL>/account/<provider>/done/ with the
# provider (provider = google, github or facebook); the External Keys page
# shows it with a copy button (sections below).

GOOGLE_CLIENT_ID = Setting('GOOGLE_CLIENT_ID', '', EXT_KEYS_SET, dict(
label = _("Google client ID"),
help_text = _("OAuth client ID from the Google Cloud console (APIs & Services > Credentials)."),
example = '123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com',
keywords = _("oauth login sign-in social"),
required=False))

GOOGLE_CLIENT_SECRET = Setting('GOOGLE_CLIENT_SECRET', '', EXT_KEYS_SET, dict(
label = _("Google client secret"),
help_text = _("Shown next to the client ID in the Google Cloud console. Keep it secret."),
widget=SecretInput(),
keywords = _("oauth login sign-in social password"),
required=False))

GITHUB_CLIENT_ID = Setting('GITHUB_CLIENT_ID', '', EXT_KEYS_SET, dict(
label = _("GitHub client ID"),
help_text = _("From a GitHub OAuth app (Settings > Developer settings > OAuth Apps)."),
example = 'Ov23liAbCdEfGh123456',
keywords = _("oauth login sign-in social"),
required=False))

GITHUB_CLIENT_SECRET = Setting('GITHUB_CLIENT_SECRET', '', EXT_KEYS_SET, dict(
label = _("GitHub client secret"),
help_text = _("Generated on the OAuth app's page; GitHub shows it only once."),
widget=SecretInput(),
keywords = _("oauth login sign-in social password"),
required=False))

FACEBOOK_APP_ID = Setting('FACEBOOK_APP_ID', '', EXT_KEYS_SET, dict(
label = _("Facebook app ID"),
help_text = _("From developers.facebook.com (App settings > Basic)."),
example = '1234567890123456',
keywords = _("oauth login sign-in social meta"),
required=False))

FACEBOOK_APP_SECRET = Setting('FACEBOOK_APP_SECRET', '', EXT_KEYS_SET, dict(
label = _("Facebook app secret"),
help_text = _("App settings > Basic, next to the app ID. Keep it secret."),
widget=SecretInput(),
keywords = _("oauth login sign-in social meta password"),
required=False))


def https_warning(status):
    """Providers refuse plain http redirect addresses other than localhost."""
    from forum import settings
    url = str(settings.APP_URL)
    if status[0] != 'off' and url.startswith('http://') and '://localhost' not in url and '://127.0.0.1' not in url:
        return WARNING, _("The site's address (APP_URL in settings_local.py) starts with http://; sign-in providers "
                          "only accept https:// redirect addresses.")
    return status


def provider_status(id_name, secret_name, check_id=None):
    def status(values):
        state = keys_status(values, (id_name, secret_name),
                            _("Fill in both the ID and the secret; until then the button stays hidden."),
                            _("The sign-in page shows this provider."))
        problem = check_id and str(values.get(id_name) or '').strip() and check_id(str(values[id_name]).strip())
        return (WARNING, problem) if problem else https_warning(state)
    return status


def google_id_problem(value):
    if not value.endswith('.apps.googleusercontent.com'):
        return _("A Google client ID ends in .apps.googleusercontent.com; check that you copied the client ID, "
                 "not the project ID or the secret.")


def facebook_id_problem(value):
    if not value.isdigit():
        return _("A Facebook app ID is a number, such as 1234567890123456.")


register('extkeys', Section(
    'google-signin', _("Sign in with Google"), ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'),
    summary=_("Members sign in with their Google account; their email address arrives already confirmed."),
    steps=(
        _("Open the <a href=\"https://console.cloud.google.com/auth/overview\">Google Auth Platform</a> in the "
          "Google Cloud console (create a project first if you have none) and fill in the <strong>Branding</strong> "
          "page: app name, support email and your site's domain."),
        _("Under <strong>Audience</strong>, choose <strong>External</strong> and <strong>publish</strong> the app; "
          "while it is in testing only the test users you list can sign in."),
        _("Under <strong>Clients</strong>, create a client of type <strong>Web application</strong> and add the "
          "redirect URI below to its <strong>Authorized redirect URIs</strong>."),
        _("Copy the <strong>Client ID</strong> and <strong>Client secret</strong> into the fields below and save. "
          "Then sign out and try the Google button on the sign-in page."),
    ),
    copy=((_("Authorized redirect URI"), '{app_url}/account/google/done/'),),
    links=(("https://console.cloud.google.com/auth/clients", _("Google Cloud console: OAuth clients")),),
    keywords=_("oauth openid login sign-in social google account"),
    status=provider_status('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', google_id_problem), weight=10))

register('extkeys', Section(
    'github-signin', _("Sign in with GitHub"), ('GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET'),
    summary=_("Members sign in with their GitHub account, handy for developer communities."),
    steps=(
        _("On GitHub, open <a href=\"https://github.com/settings/developers\">Settings &gt; Developer settings "
          "&gt; OAuth Apps</a> (or your organization's settings, so the app doesn't depend on one person) and "
          "choose <strong>New OAuth app</strong>."),
        _("Enter the site's name, <code>{app_url}</code> as the <strong>Homepage URL</strong> and the callback "
          "URL below as the <strong>Authorization callback URL</strong>, then register the app."),
        _("Copy the <strong>Client ID</strong>, then choose <strong>Generate a new client secret</strong> and copy "
          "the secret right away: GitHub shows it only once."),
        _("Paste both into the fields below and save."),
    ),
    copy=((_("Authorization callback URL"), '{app_url}/account/github/done/'),),
    links=(("https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app",
            _("GitHub: creating an OAuth app")),),
    keywords=_("oauth login sign-in social developer"),
    status=provider_status('GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET'), weight=11))

register('extkeys', Section(
    'facebook-signin', _("Sign in with Facebook"), ('FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET'),
    summary=_("Members sign in with their Facebook account."),
    steps=(
        _("On <a href=\"https://developers.facebook.com/apps/\">Meta for Developers</a>, create an app with the "
          "use case <strong>Authenticate and request data from users with Facebook Login</strong>."),
        _("In the Facebook Login settings, add the redirect URI below to <strong>Valid OAuth Redirect "
          "URIs</strong>."),
        _("Under <strong>App settings &gt; Basic</strong>, fill in the privacy policy address, then copy the "
          "<strong>App ID</strong> and <strong>App secret</strong> into the fields below and save."),
        _("Switch the app to <strong>Live</strong>; in development mode only the app's own roles can sign in."),
    ),
    copy=((_("Valid OAuth Redirect URI"), '{app_url}/account/facebook/done/'),),
    links=(("https://developers.facebook.com/docs/facebook-login/web", _("Meta: Facebook Login for the web")),),
    keywords=_("oauth login sign-in social meta"),
    status=provider_status('FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET', facebook_id_problem), weight=12))
