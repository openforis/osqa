import os.path
from .base import Setting, SettingSet, BaseSetting

from django.forms.widgets import Textarea
from django.utils.translation import gettext_lazy as _
from django.conf import settings as djsettings
from django.utils.version import get_git_changeset

from forum.modules import get_modules_script_implementations

OSQA_VERSION = "Development Build"

VCS_REVISION = get_git_changeset()

# We'll have to keep in mind this variable on every release.
if VCS_REVISION == 'SVN-unknown':
    VCS_REVISION = 'SVN-1000'

MAINTAINANCE_MODE = Setting('MAINTAINANCE_MODE', None)

SETTINGS_PACK = Setting('SETTINGS_PACK', "default")
NODE_MAN_FILTERS = Setting('NODE_MAN_FILTERS', [])

APP_URL = djsettings.APP_URL
APP_BASE_URL = djsettings.APP_BASE_URL
FORCE_SCRIPT_NAME = djsettings.FORCE_SCRIPT_NAME
OSQA_SKIN = djsettings.OSQA_DEFAULT_SKIN
LANGUAGE_CODE = djsettings.LANGUAGE_CODE
ONLINE_USERS = Setting('ONLINE_USERS', {})


from .basic import *
from .appearance import *
from .sidebar import *
from .email import *
from .extkeys import *
from .minrep import *
from .repgain import *
from .voting import *
from .upload import *
from .about import *
from .faq import *
from .form import *
from .view import *
from .moderation import *
from .users import *
from .security import *
from .support import *
from .static import *
from .urls import *
from .accept import *
from .sitemaps import *
from .api import *
from .routing import *

# Defined before the module settings below are loaded: modules such as
# default_badges import it.
BADGES_SET = SettingSet('badges', _('Badges config'), _("Configure badges on your OSQA site."), 500)

__all__ = list(locals().keys())

# Be able to import all module settings as well
for k,v in get_modules_script_implementations('settings', BaseSetting).items():
   if k not in __all__:
        __all__.append(k)
        exec("%s = v" % k)



