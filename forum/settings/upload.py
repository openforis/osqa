import os.path
from .base import Setting, SettingSet
from django.utils.translation import gettext_lazy as _

UPLOAD_SET = SettingSet('paths', _('File uploads'), _("Where uploaded files are kept, and their size limits."), 600)

UPFILES_FOLDER = Setting('UPFILES_FOLDER', os.path.join(os.path.dirname(os.path.dirname(__file__)),'upfiles'), UPLOAD_SET, dict(
label = _("Uploaded files folder"),
help_text = _("The filesystem path where uploaded files will be stored. Please note that this folder must exist.")))

UPFILES_ALIAS = Setting('UPFILES_ALIAS', '/upfiles/', UPLOAD_SET, dict(
label = _("Uploaded files alias"),
help_text = _("The url alias for uploaded files. Notice that if you change this setting, you'll need to restart your site.")))

ALLOW_MAX_FILE_SIZE = Setting('ALLOW_MAX_FILE_SIZE', 2.5, UPLOAD_SET, dict(
label = _("Max file size"),
help_text = _("The maximum allowed file size for uploads in mb.")))

UPLOAD_MAX_IMAGE_SIDE = Setting('UPLOAD_MAX_IMAGE_SIDE', 2000, UPLOAD_SET, dict(
label = _("Max image size in pixels"),
help_text = _("Uploaded images are reduced so that their longest side is at most this many pixels. Location and other metadata are always removed."),
min_value = 100))

UPLOADS_PER_HOUR = Setting('UPLOADS_PER_HOUR', 30, UPLOAD_SET, dict(
label = _("Image uploads per member per hour"),
help_text = _("Moderators and administrators have no limit. 0 means no limit.")))
