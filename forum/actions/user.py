from django.utils.translation import ugettext as _
from django.db.models import F
from forum.models.action import ActionProxy
from forum.models import Award, Badge, ValidationHash
from forum import settings
from forum.settings import APP_SHORT_NAME
from forum.utils.mail import send_email, send_template_email

class UserJoinsAction(ActionProxy):
    def repute_users(self):
        self.repute(self.user, int(settings.INITIAL_REP))

    def process_action(self):
        hash = ValidationHash.objects.create_new(self.user, 'email', [self.user.email])
        send_template_email([self.user], "auth/email_validation.html", {'validation_code': hash})

    def describe(self, viewer=None):
        return _("%(user)s %(have_has)s joined the %(app_name)s Q&A community") % {
        'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
        'have_has': self.viewer_or_user_verb(viewer, self.user, _('have'), _('has')),
        'app_name': APP_SHORT_NAME,
        }

class EditProfileAction(ActionProxy):
    def describe(self, viewer=None):
        return _("%(user)s edited %(hes_or_your)s %(profile_link)s") % {
        'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
        'hes_or_your': self.viewer_or_user_verb(viewer, self.user, _('your'), _('his')),
        'profile_link': self.hyperlink(self.user.get_profile_url(), _('profile')),
        }

class BonusRepAction(ActionProxy):
    def process_data(self, value):
        self._value = value

    def repute_users(self):
        self.repute(self.user, self._value)
        self.user.message_set.create(
                message=_("Congratulations, you have been awarded an extra %s reputation points.") % self._value +
                '<br />%s' % self.extra.get('message', _('Thank you')))

    def describe(self, viewer=None):
        value = self.extra.get('value', _('unknown'))
        message = self.extra.get('message', '')

        return _("%(user)s %(was_were)s awarded %(value)s reputation points: %(message)s") % {
        'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
        'was_were': self.viewer_or_user_verb(viewer, self.user, _('were'), _('was')),
        'value': value, 'message': message
        }

class AwardAction(ActionProxy):
    def process_data(self, badge, trigger):
        self.__dict__['_badge'] = badge
        self.__dict__['_trigger'] = trigger

    def process_action(self):
        badge = self.__dict__['_badge']
        trigger = self.__dict__['_trigger']

        award = Award(user=self.user, badge=badge, trigger=trigger, action=self)
        if self.node:
            award.node = self.node

        award.save()
        award.badge.awarded_count = F('awarded_count') + 1
        award.badge.save()

        if award.badge.type == Badge.GOLD:
            self.user.gold += 1
        if award.badge.type == Badge.SILVER:
            self.user.silver += 1
        if award.badge.type == Badge.BRONZE:
            self.user.bronze += 1

        self.user.save()

        self.user.message_set.create(message=_(
                """Congratulations, you have received a badge '%(badge_name)s'. Check out <a href=\"%(profile_url)s\">your profile</a>."""
                ) %
        dict(badge_name=award.badge.name, profile_url=self.user.get_profile_url()))

    def cancel_action(self):
        award = self.award
        badge = award.badge
        badge.awarded_count = F('awarded_count') - 1
        badge.save()
        award.delete()

    @classmethod
    def get_for(cls, user, badge, node=False):
        try:
            if node is False:
                return Award.objects.get(user=user, badge=badge).action
            else:
                return Award.objects.get(user=user, node=node, badge=badge).action
        except:
            return None

    def describe(self, viewer=None):
        return _("%(user)s %(were_was)s awarded the %(badge_name)s badge") % {
        'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
        'were_was': self.viewer_or_user_verb(viewer, self.user, _('were'), _('was')),
        'badge_name': self.award.badge.name,
        }

class SuspendAction(ActionProxy):
    def process_data(self, **kwargs):
        self.extra = kwargs

    def process_action(self):
        self.user.is_active = False
        self.user.save()

    def cancel_action(self):
        self.user.is_active = True
        self.user._pop_suspension_cache()
        self.user.save()
        self.user.message_set.create(message=_("Your suspension has been removed."))

    def describe(self, viewer=None):
        if self.extra.get('bantype', 'indefinitely') == 'forxdays' and self.extra.get('forxdays', None):
            suspension = _("for %s days") % self.extra['forxdays']
        else:
            suspension = _("indefinetely")

        return _("%(user)s %(were_was)s suspended %(suspension)s: %(msg)s") % {
        'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
        'were_was': self.viewer_or_user_verb(viewer, self.user, _('were'), _('was')),
        'suspension': suspension, 'msg': self.extra.get('publicmsg', _('Bad behaviour'))
        }