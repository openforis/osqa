from .forms import CommaStringListWidget, StringListWidget
from django.forms import CheckboxSelectMultiple
from django.forms.widgets import RadioSelect
from .base import Setting, SettingSet
from django.utils.translation import gettext as _

USERS_SET = SettingSet('users', _('Members'), _("Sign-up, accounts, profiles and what members may change about themselves."), 20)

ALLOW_NEGATIVE_REPUTATION = Setting('ALLOW_NEGATIVE_REPUTATION', True, USERS_SET, dict(
label = _("Allow negative reputation"),
help_text = _("Check if you want to allow negative user reputations in the community."),
required=False))

STORE_GREETING_IN_COOKIE = Setting('STORE_GREETING_IN_COOKIE', True, USERS_SET, dict(
label = _("Store greeting in cookie"),
help_text = _("If you check this the greeting will be stored in a cookie and the users won't be notified on logout."),
required=False))

EDITABLE_SCREEN_NAME = Setting('EDITABLE_SCREEN_NAME', False, USERS_SET, dict(
label = _("Editable screen name"),
help_text = _("Allow users to alter their screen name."),
required=False))

MIN_USERNAME_LENGTH = Setting('MIN_USERNAME_LENGTH', 3, USERS_SET, dict(
label = _("Minimum username length"),
help_text = _("The minimum length (in character) of a username.")))

RESERVED_USERNAMES = Setting('RESERVED_USERNAMES',
[_('fuck'), _('shit'), _('ass'), _('sex'), _('add'), _('edit'), _('save'), _('delete'), _('manage'), _('update'), _('remove'), _('new')]
, USERS_SET, dict(
label = _("Disabled usernames"),
help_text = _("A comma separated list of disabled usernames (usernames not allowed during a new user registration)."),
widget=CommaStringListWidget))

TRUNCATE_LONG_USERNAMES = Setting('TRUNCATE_LONG_USERNAMES', True, USERS_SET, dict(
label=_("Truncate long usernames"),
help_text = _("The long usernames will be truncated.."),
required=False,
))

SHOW_USER_ACCEPT_RATE = Setting('SHOW_USER_ACCEPT_RATE', True, USERS_SET, dict(
label = _("Show user accept rate"),
help_text = _("If you check this the user accept rate will be displayed on the user posts."),
required=False))

FREEZE_ACCEPT_RATE_FOR = Setting('FREEZE_ACCEPT_RATE_FOR',
["admin",],
USERS_SET, dict(
label = _("Freeze accept rate"),
help_text = _("Freeze answers accept rate for the selected users."),
widget=StringListWidget))

TRUNCATE_USERNAMES_LONGER_THAN = Setting('TRUNCATE_USERNAMES_LONGER_THAN', 15, USERS_SET, dict(
label = _("Truncate usernames longer than"),
help_text = _("The usernames that are longer than this will be truncated and ... will be appended.")))

SHOW_STATUS_DIAMONDS = Setting('SHOW_STATUS_DIAMONDS', True, USERS_SET, dict(
label=_("Show status diamonds"),
help_text = _("Show status \"diamonds\" next to moderators or superusers usernames."),
required=False,
))

EMAIL_UNIQUE = Setting('EMAIL_UNIQUE', True, USERS_SET, dict(
label = _("Force unique email"),
help_text = _("Should each user have an unique email."),
required=False))

EMAIL_CONFIRMATION_MODE = Setting('EMAIL_CONFIRMATION_MODE', 'signin', USERS_SET, dict(
label = _("Email confirmation for new members"),
help_text = _("Everyone who signs up with an email address gets a link to confirm it (valid for 48 hours). By "
              "default they can sign in only after confirming, and the sign-up page answers the same whether or "
              "not the address already has an account (its owner gets an email instead). Members who joined "
              "before this setting existed, accounts made by administrators or imported, and addresses already "
              "confirmed by a sign-in service are not affected."),
widget=RadioSelect,
choices=(("signin", _("They must confirm before they can sign in")),
         ("post", _("They can sign in at once, but must confirm before asking, answering or commenting")),
         ("off", _("Not required (only the actions ticked below need a confirmed address)"))),
required=False))

UNCONFIRMED_ACCOUNT_DAYS = Setting('UNCONFIRMED_ACCOUNT_DAYS', 7, USERS_SET, dict(
label = _("Delete unconfirmed new accounts after (days)"),
help_text = _("The cleanup_inactive_users command (run daily from cron) deletes accounts that signed up but never "
              "confirmed their email address within this many days and have no posts or other activity. Only while "
              "email confirmation is required. 0 turns it off.")))

ACCOUNT_DELETION_POSTS = Setting('ACCOUNT_DELETION_POSTS', 'keep', USERS_SET, dict(
label = _("Posts of deleted accounts"),
help_text = _("What happens to the questions, answers and comments of members who delete their account. Their "
              "profile and personal data are always removed."),
widget=RadioSelect,
choices=(("keep", _("Keep them, shown as by \"deleted-user\" (other people's answers and discussions depend on them)")),
         ("delete", _("Delete them (moderators can still see deleted posts)"))),
required=False))

REQUIRE_EMAIL_VALIDATION_TO = Setting('REQUIRE_EMAIL_VALIDATION_TO', [], USERS_SET, dict(
label = _("Require email validation to..."),
help_text = _("Which actions members without a confirmed email address can't do, whenever they joined. New "
              "members also follow the \"Email confirmation for new members\" setting above."),
widget=CheckboxSelectMultiple,
choices=(("ask", _("ask questions")), ("answer", _("provide answers")), ("comment", _("make comments")), ("flag", _("report posts"))),
required=False,
))

DONT_NOTIFY_UNVALIDATED = Setting('DONT_NOTIFY_UNVALIDATED', True, USERS_SET, dict(
label = _("Don't notify to invalid emails"),
help_text = _("Do not notify users with unvalidated emails."),
required=False))

HOLD_PENDING_POSTS_MINUTES = Setting('HOLD_PENDING_POSTS_MINUTES', 120, USERS_SET, dict(
label=_("Hold pending posts for X minutes"),
help_text=_("How much time in minutes a post should be kept in session until the user logs in or validates the email.")
))

WARN_PENDING_POSTS_MINUTES = Setting('WARN_PENDING_POSTS_MINUTES', 15, USERS_SET, dict(
label=_("Warn about pending posts afer X minutes"),
help_text=_("How much time in minutes a user that just logged in or validated his email should be warned about a pending post instead of publishing it automatically.")
))

GRAVATAR_RATING_CHOICES = (
    ('g', _('suitable for display on all websites with any audience type.')),
    ('pg', _('may contain rude gestures, provocatively dressed individuals, the lesser swear words, or mild violence.')),
    ('r', _('may contain such things as harsh profanity, intense violence, nudity, or hard drug use.')),
    ('x', _('may contain hardcore sexual imagery or extremely disturbing violence.')),
)

GRAVATAR_ALLOWED_RATING = Setting('GRAVATAR_ALLOWED_RATING', 'g', USERS_SET, dict(
label = _("Gravatar rating"),
help_text = _("Gravatar allows users to self-rate their images so that they can indicate if an image is appropriate for a certain audience."),
widget=RadioSelect,
choices=GRAVATAR_RATING_CHOICES,
required=False))

GRAVATAR_DEFAULT_CHOICES = (
    ('mm', _('(mystery-man) a simple, cartoon-style silhouetted outline of a person (does not vary by email hash)')),
    ('identicon', _('a geometric pattern based on an email hash')),
    ('monsterid', _('a generated "monster" with different colors, faces, etc')),
    ('wavatar', _('generated faces with differing features and backgrounds')),
)

GRAVATAR_DEFAULT_IMAGE = Setting('GRAVATAR_DEFAULT_IMAGE', 'identicon', USERS_SET, dict(
label = _("Gravatar default"),
help_text = _("Gravatar has a number of built in options which you can also use as defaults."),
widget=RadioSelect,
choices=GRAVATAR_DEFAULT_CHOICES,
required=False))


SIGNUP_MIN_SECONDS = Setting('SIGNUP_MIN_SECONDS', 3, USERS_SET, dict(
label = _("Minimum time to fill in the sign-up form"),
help_text = _("Seconds. Sign-up forms sent faster than this, or with the hidden trap field filled in, are refused: "
              "bots do that, people don't. 0 turns the time check off.")))

SIGNUP_LIMIT_PER_IP = Setting('SIGNUP_LIMIT_PER_IP', 5, USERS_SET, dict(
label = _("Sign-ups per IP address per hour"),
help_text = _("New accounts allowed from one IP address within an hour. 0 means no limit.")))

PROFILE_LINKS_MIN_REP = Setting('PROFILE_LINKS_MIN_REP', 25, USERS_SET, dict(
label = _("Reputation for profile links"),
help_text = _("Below this reputation a user's website and the links in their \"about me\" are shown as plain text, "
              "and their profile page asks search engines not to index it, so spam accounts gain nothing from it.")))

INACTIVE_ACCOUNT_DAYS = Setting('INACTIVE_ACCOUNT_DAYS', 15, USERS_SET, dict(
label = _("Delete dormant accounts after (days)"),
help_text = _("The cleanup_inactive_users command (run daily from cron) deletes accounts older than this that never "
              "confirmed their email, never posted, voted or did anything else, and haven't logged in during that "
              "time. Staff accounts are never deleted. 0 turns it off.")))
