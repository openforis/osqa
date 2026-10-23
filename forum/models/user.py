from .base import *
from .utils import PickledObjectField
from django.conf import settings as django_settings
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.contrib.auth.models import User as DjangoUser, AnonymousUser as DjangoAnonymousUser
from django.urls import get_script_prefix

from django.utils.encoding import smart_str, force_bytes

from forum.settings import TRUNCATE_LONG_USERNAMES, TRUNCATE_USERNAMES_LONGER_THAN

import hashlib
import hmac
import secrets
import string

import logging

class AnonymousUser(DjangoAnonymousUser):
    reputation = 0

    def get_visible_answers(self, question):
        return question.answers.visible_to(self)

    def can_view_deleted_post(self, post):
        return False

    def can_vote_up(self):
        return False

    def can_vote_down(self):
        return False

    def can_vote_count_today(self):
        return 0

    def can_flag_offensive(self, post=None):
        return False

    def can_view_offensive_flags(self, post=None):
        return False

    def can_comment(self, post):
        return False

    def can_like_comment(self, comment):
        return False

    def can_edit_comment(self, comment):
        return False

    def can_delete_comment(self, comment):
        return False

    def can_convert_to_comment(self, answer):
        return False

    def can_convert_to_question(self, answer):
        return False

    def can_convert_comment_to_answer(self, comment):
        return False

    def can_accept_answer(self, answer):
        return False

    def can_create_tags(self):
        return False

    def can_edit_post(self, post):
        return False

    def can_wikify(self, post):
        return False

    def can_cancel_wiki(self, post):
        return False

    def can_retag_questions(self):
        return False

    def can_close_question(self, question):
        return False

    def can_reopen_question(self, question):
        return False

    def can_delete_post(self, post):
        return False

    def can_upload_files(self):
        return False

    def is_a_super_user_or_staff(self):
        return False

def true_if_is_super_or_staff(fn):
    def decorated(self, *args, **kwargs):
        return self.is_superuser or self.is_staff or fn(self, *args, **kwargs)

    return decorated

def false_if_validation_required_to(item):
    def decorator(fn):
        def decorated(self, *args, **kwargs):
            from forum.utils.accounts import validation_required
            if validation_required(self, item):
                return False
            else:
                return fn(self, *args, **kwargs)
        return decorated
    return decorator

class UserManager(CachedManager):
    def get(self, *args, **kwargs):
        if not len(args) and len(kwargs) == 1 and 'username' in kwargs:
            matching_users = self.filter(username=kwargs['username'])

            if len(matching_users) == 1:
                return matching_users[0]
            elif len(matching_users) > 1:
                for user in matching_users:
                    if user.username == kwargs['username']:
                        return user
                return matching_users[0]
        return super().get(*args, **kwargs)

class User(BaseModel, DjangoUser):
    is_approved = models.BooleanField(default=False)
    email_isvalid = models.BooleanField(default=False)
    # Set by the sign-up views: the account must confirm its email address
    # (setting EMAIL_CONFIRMATION_MODE, forum/utils/accounts.py). Cleared on the
    # first confirmation; accounts that existed before keep False.
    email_confirmation_required = models.BooleanField(default=False)
    # Raised to sign the account out everywhere ("sign out of other sessions",
    # password reset); sessions remember the value they were signed in with.
    session_epoch = models.PositiveIntegerField(default=0)

    reputation = models.IntegerField(default=0)
    gold = models.PositiveIntegerField(default=0)
    silver = models.PositiveIntegerField(default=0)
    bronze = models.PositiveIntegerField(default=0)

    last_seen = models.DateTimeField(default=datetime.datetime.now)
    real_name = models.CharField(max_length=100, blank=True)
    website = models.URLField(max_length=200, blank=True)
    location = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    about = models.TextField(blank=True)

    subscriptions = models.ManyToManyField('Node', related_name='subscribers', through='QuestionSubscription')

    vote_up_count = DenormalizedField("actions", canceled=False, action_type="voteup")
    vote_down_count = DenormalizedField("actions", canceled=False, action_type="votedown")

    objects = UserManager()

    def __str__(self):
        return smart_str(self.username)

    @property
    def prop(self):
        prop = self.__dict__.get('_prop', None)

        if prop is None:
            prop = UserPropertyDict(self)
            self._prop = prop

        return prop

    @property
    def is_siteowner(self):
        #todo: temporary thing, for now lets just assume that the site owner will always be the first user of the application
        return self.id == 1


    def _decorated_name(self):
        username = smart_str(self.username)

        if len(username) > TRUNCATE_USERNAMES_LONGER_THAN and TRUNCATE_LONG_USERNAMES:
            username = '%s...' % username[:TRUNCATE_USERNAMES_LONGER_THAN-3]

        if settings.SHOW_STATUS_DIAMONDS:
            if self.is_superuser:
                return "%s \u2666\u2666" % username

            if self.is_staff:
                return "%s \u2666" % username

        return username

    @property
    def decorated_name(self):
        return self._decorated_name()

    def touch_last_seen(self):
        """Record that the user is using the site (at most once an hour)."""
        from django.core.cache import cache
        if cache.add('user-seen:%d' % self.id, True, 3600):
            self.last_seen = datetime.datetime.now()
            User.objects.filter(id=self.id).update(last_seen=self.last_seen)

    @property
    def last_activity(self):
        try:
            return self.actions.order_by('-action_date')[0].action_date
        except:
            return self.last_seen

    @property
    def gravatar(self):
        # Python 3: md5() requires bytes, not strings
        return md5(self.email.lower().encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        # If the community doesn't allow negative reputation, set it to 0
        # (changes from actions are F() expressions, already kept from going
        # below 0 by ActionRepute)
        if not settings.ALLOW_NEGATIVE_REPUTATION and isinstance(self.reputation, int) and self.reputation < 0:
            self.reputation = 0

        new = not bool(self.id)

        super().save(*args, **kwargs)

        if new:
            sub_settings = SubscriptionSettings(user=self)
            sub_settings.save()
    def get_profile_url(self):
        keyword_arguments = {
            'slug': slugify(smart_str(self.username))
        }
        if settings.INCLUDE_ID_IN_USER_URLS:
            keyword_arguments.update({
                'id': self.id,
            })
        return reverse('user_profile', kwargs=keyword_arguments)

    def get_absolute_url(self):
        root_relative_url = self.get_profile_url()
        relative_url = root_relative_url[len(get_script_prefix()):]
        return '%s/%s' % (django_settings.APP_URL, relative_url)
    def get_asked_url(self):
        return reverse('user_questions', kwargs={'mode': 'asked-by', 'user': self.id, 'slug': slugify(smart_str(self.username))})
    def get_user_subscriptions_url(self):
        keyword_arguments = {
            'slug': slugify(smart_str(self.username))
        }
        if settings.INCLUDE_ID_IN_USER_URLS:
            keyword_arguments.update({
                'id': self.id,
            })
        return reverse('user_subscriptions', kwargs=keyword_arguments)
    def get_answered_url(self):
        return reverse('user_questions', kwargs={'mode': 'answered-by', 'user': self.id, 'slug': slugify(self.username)})

    def get_subscribed_url(self):
        try:
            # Try to retrieve the Subscribed User URL.
            url = reverse('user_questions',
                           kwargs={'mode': 'subscribed-by', 'user': self.id, 'slug': slugify(smart_str(self.username))})
            return url
        except Exception as e:
            # If some Exception has been raised, don't forget to log it.
            logging.error("Error retrieving a subscribed user URL: %s" % e)

    def get_visible_answers(self, question):
        return question.answers.visible_to(self)

    # The per-day limits (votes, flags, reputation from up votes) count the
    # last 24 hours. (They used to start at midnight yesterday, so a "day"
    # lasted up to 48 hours.)
    @staticmethod
    def _one_day_ago():
        return datetime.datetime.now() - datetime.timedelta(days=1)

    def get_vote_count_today(self):
        return self.actions.filter(canceled=False, action_type__in=("voteup", "votedown"),
                                   action_date__gte=self._one_day_ago()).count()

    def get_reputation_by_upvoted_today(self):
        """Net reputation this user got in the last 24 hours from up votes on
        their posts: the gains of the up votes cast in that time, less the
        part given back by those of them that were cancelled."""
        from forum.models.action import ActionRepute
        total = ActionRepute.objects.filter(user=self, action__action_type='voteup',
                                            action__action_date__gte=self._one_day_ago()
                                            ).aggregate(total=models.Sum('value'))['total']
        return int(total or 0)

    def get_flagged_items_count_today(self):
        return self.actions.filter(canceled=False, action_type="flag",
                                   action_date__gte=self._one_day_ago()).count()

    def can_vote_count_today(self):
        votes_today = settings.MAX_VOTES_PER_DAY

        if settings.USER_REPUTATION_TO_MAX_VOTES:
            votes_today = votes_today + int(self.reputation)

        return votes_today

    def can_use_canned_comments(self):
        # The canned comments feature is available only for admins and moderators,
        # and only if the "Use canned comments" setting is activated in the administration.
        if (self.is_superuser or self.is_staff) and settings.USE_CANNED_COMMENTS:
            return True
        else:
            return False

    @true_if_is_super_or_staff
    def can_view_deleted_post(self, post):
        return post.author == self

    @true_if_is_super_or_staff
    def can_vote_up(self):
        return self.reputation >= int(settings.REP_TO_VOTE_UP)

    @true_if_is_super_or_staff
    def can_vote_down(self):
        return self.reputation >= int(settings.REP_TO_VOTE_DOWN)

    @false_if_validation_required_to('flag')
    def can_flag_offensive(self, post=None):
        if post is not None and post.author == self:
            return False
        return self.is_superuser or self.is_staff or self.reputation >= int(settings.REP_TO_FLAG)

    @true_if_is_super_or_staff
    def can_view_offensive_flags(self, post=None):
        if post is not None and post.author == self:
            return True
        return self.reputation >= int(settings.REP_TO_VIEW_FLAGS)

    @true_if_is_super_or_staff
    @false_if_validation_required_to('comment')
    def can_comment(self, post):
        return self == post.author or self.reputation >= int(settings.REP_TO_COMMENT
                ) or (post.__class__.__name__ == "Answer" and self == post.question.author)

    @true_if_is_super_or_staff
    def can_like_comment(self, comment):
        return self != comment.author and (self.reputation >= int(settings.REP_TO_LIKE_COMMENT))

    @true_if_is_super_or_staff
    def can_edit_comment(self, comment):
        return (comment.author == self and comment.added_at >= datetime.datetime.now() - datetime.timedelta(minutes=60)
        ) or self.is_superuser

    @true_if_is_super_or_staff
    def can_delete_comment(self, comment):
        return self == comment.author or self.reputation >= int(settings.REP_TO_DELETE_COMMENTS)

    def can_convert_comment_to_answer(self, comment):
        # We need to know what is the comment parent node type.
        comment_parent_type = comment.parent.node_type

        # If the parent is not a question or an answer this comment cannot be converted to an answer.
        if comment_parent_type != "question" and comment_parent_type != "answer":
            return False

        return (comment.parent.node_type in ('question', 'answer')) and (self.is_superuser or self.is_staff or (
            self == comment.author) or (self.reputation >= int(settings.REP_TO_CONVERT_COMMENTS_TO_ANSWERS)))

    def can_convert_to_comment(self, answer):
        return (not answer.marked) and (self.is_superuser or self.is_staff or answer.author == self or self.reputation >= int
                (settings.REP_TO_CONVERT_TO_COMMENT))

    def can_convert_to_question(self, node):
        return (not node.marked) and (self.is_superuser or self.is_staff or node.author == self or self.reputation >= int
                (settings.REP_TO_CONVERT_TO_QUESTION))

    @true_if_is_super_or_staff
    def can_accept_answer(self, answer):
        return self == answer.question.author and (settings.USERS_CAN_ACCEPT_OWN or answer.author != answer.question.author)

    @true_if_is_super_or_staff
    def can_create_tags(self):
        return self.reputation >= int(settings.REP_TO_CREATE_TAGS)

    @true_if_is_super_or_staff
    def can_edit_post(self, post):
        return self == post.author or self.reputation >= int(settings.REP_TO_EDIT_OTHERS
                                                             ) or (post.nis.wiki and self.reputation >= int(
                settings.REP_TO_EDIT_WIKI))

    @true_if_is_super_or_staff
    def can_wikify(self, post):
        return self == post.author or self.reputation >= int(settings.REP_TO_WIKIFY)

    @true_if_is_super_or_staff
    def can_cancel_wiki(self, post):
        return self == post.author

    @true_if_is_super_or_staff
    def can_retag_questions(self):
        return self.reputation >= int(settings.REP_TO_RETAG)

    @true_if_is_super_or_staff
    def can_close_question(self, question):
        return (self == question.author and self.reputation >= int(settings.REP_TO_CLOSE_OWN)
        ) or self.reputation >= int(settings.REP_TO_CLOSE_OTHERS)

    @true_if_is_super_or_staff
    def can_reopen_question(self, question):
        # Check whether the setting to Unify close and reopen permissions has been activated
        if bool(settings.UNIFY_PERMISSIONS_TO_CLOSE_AND_REOPEN):
            # If we unify close to reopen check whether the user has permissions to close.
            # If he has -- he can reopen his question too.
            can_reopen = (
                self == question.author and self.reputation >= int(settings.REP_TO_CLOSE_OWN)
            ) or self.reputation >= int(settings.REP_TO_CLOSE_OTHERS)
        else:
            # Check whether the user is the author and has the required permissions to reopen
            can_reopen = self == question.author and self.reputation >= int(settings.REP_TO_REOPEN_OWN)
        return can_reopen

    @true_if_is_super_or_staff
    def can_delete_post(self, post):
        if post.node_type == "comment":
            return self.can_delete_comment(post)

        return (self == post.author and (post.__class__.__name__ == "Answer" or
        not post.answers.exclude(author__id=self.id).count()))

    @true_if_is_super_or_staff
    def can_upload_files(self):
        return self.reputation >= int(settings.REP_TO_UPLOAD)

    @true_if_is_super_or_staff
    def is_a_super_user_or_staff(self):
        return False

    def email_valid_and_can_ask(self):
        from forum.utils.accounts import validation_required
        return not validation_required(self, 'ask')

    def email_valid_and_can_answer(self):
        from forum.utils.accounts import validation_required
        return not validation_required(self, 'answer')

    def check_password(self, old_passwd):
        self.__dict__.update(self.__class__.objects.filter(id=self.id).values('password')[0])
        return DjangoUser.check_password(self, old_passwd)

    @property
    def suspension(self):
        if self.__dict__.get('_suspension_dencache_', False) is not None:
            try:
                self.__dict__['_suspension_dencache_'] = self.reputes.get(action__action_type="suspend", action__canceled=False).action
            except ObjectDoesNotExist:
                self.__dict__['_suspension_dencache_'] = None
            except MultipleObjectsReturned:
                logging.error("Multiple suspension actions found for user %s (%s)" % (self.username, self.id))
                self.__dict__['_suspension_dencache_'] = self.reputes.filter(action__action_type="suspend", action__canceled=False
                                                                             ).order_by('-action__action_date')[0].action

        return self.__dict__['_suspension_dencache_']

    def _pop_suspension_cache(self):
        self.__dict__.pop('_suspension_dencache_', None)

    def is_suspended(self):
        if not self.is_active:
            suspension = self.suspension

            if suspension and suspension.extra.get('bantype', None) == 'forxdays' and (
            datetime.datetime.now() > suspension.action_date + datetime.timedelta(
                    days=int(suspension.extra.get('forxdays', 365)))):
                suspension.cancel()
            else:
                return True

        return False

    class Meta:
        app_label = 'forum'
        # Foreign keys to User are loaded through the base manager; use the
        # cached manager so they hit the object cache.
        base_manager_name = 'objects'
        indexes = [models.Index(fields=['reputation'], name='user_reputation_idx')]

class UserProperty(BaseModel):
    user = models.ForeignKey(User, related_name='properties', on_delete=models.CASCADE)
    key = models.CharField(max_length=16)
    value = PickledObjectField()

    class Meta:
        app_label = 'forum'
        unique_together = ('user', 'key')

    def cache_key(self):
        return self._generate_cache_key("%s:%s" % (self.user.id, self.key))

    @classmethod
    def infer_cache_key(cls, querydict):
        if 'user' in querydict and 'key' in querydict:
            cache_key = cls._generate_cache_key("%s:%s" % (querydict['user'].id, querydict['key']))
            if len(cache_key) > django_settings.CACHE_MAX_KEY_LENGTH:
                cache_key = cache_key[:django_settings.CACHE_MAX_KEY_LENGTH]
            return cache_key

        return None

class UserPropertyDict:
    def __init__(self, user):
        self.__dict__['_user'] = user

    def __get_property(self, name):
        # Remember missing properties too, so each access doesn't query again.
        key = '__%s__' % name
        if key in self.__dict__:
            return self.__dict__[key]
        try:
            user = self.__dict__['_user']
            prop = UserProperty.objects.get(user=user, key=name)
        except UserProperty.DoesNotExist:
            prop = None

        self.__dict__[key] = prop
        if prop is not None:
            self.__dict__[name] = prop.value
        return prop


    def __getattr__(self, name):
        # copy/pickle probe special names (__setstate__, __deepcopy__, ...),
        # also on instances rebuilt without __init__: those are not properties.
        if name.startswith('__') or '_user' not in self.__dict__:
            raise AttributeError(name)

        if self.__dict__.get(name, None):
            return self.__dict__[name]

        prop = self.__get_property(name)

        if prop:
            return prop.value
        else:
            return None

    def __setattr__(self, name, value):
        current = self.__get_property(name)

        if value is not None:
            if current:
                current.value = value
                self.__dict__[name] = value
                current.save(full_save=True)
            else:
                user = self.__dict__['_user']
                prop = UserProperty(user=user, value=value, key=name)
                prop.save()
                self.__dict__[name] = value
                self.__dict__['__%s__' % name] = prop
        else:
            if current:
                current.delete()
                self.__dict__.pop(name, None)
                self.__dict__['__%s__' % name] = None


class SubscriptionSettings(models.Model):
    user = models.OneToOneField(User, related_name='subscription_settings', editable=False, on_delete=models.CASCADE)

    enable_notifications = models.BooleanField(default=True)

    #notify if
    member_joins = models.CharField(max_length=1, default='n')
    new_question = models.CharField(max_length=1, default='n')
    new_question_watched_tags = models.CharField(max_length=1, default='i')
    subscribed_questions = models.CharField(max_length=1, default='i')

    #auto_subscribe_to
    all_questions = models.BooleanField(default=False)
    all_questions_watched_tags = models.BooleanField(default=False)
    questions_viewed = models.BooleanField(default=False)

    #notify activity on subscribed
    notify_answers = models.BooleanField(default=True)
    notify_reply_to_comments = models.BooleanField(default=True)
    notify_comments_own_post = models.BooleanField(default=True)
    notify_comments = models.BooleanField(default=False)
    notify_accepted = models.BooleanField(default=False)

    # New members opt in to the daily digest of new questions.
    send_digest = models.BooleanField(default=False)

    # How often activity emails (answers, comments, mentions, accepted answers,
    # new questions, new members) are sent: as it happens, gathered into a
    # daily or weekly summary (forum/utils/email_frequency.py), or never.
    FREQUENCY_IMMEDIATE, FREQUENCY_DAILY, FREQUENCY_WEEKLY, FREQUENCY_NEVER = 'i', 'd', 'w', 'n'
    email_frequency = models.CharField(max_length=1, default=FREQUENCY_IMMEDIATE)
    # Mentions are emailed right away even with a summary (or "never").
    mentions_immediate = models.BooleanField(default=True)
    # When the last daily or weekly summary was sent (at most one a day).
    last_summary_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        app_label = 'forum'

from forum.utils.time import one_day_from_now

def _token_digest(token):
    return 'sha256$' + hashlib.sha256(str(token).encode('utf-8')).hexdigest()


class ValidationHashManager(models.Manager):
    """One-time links (email confirmation, password reset, email change).

    The token in the link is an HMAC-SHA256 keyed with SECRET_KEY over a random
    seed, the user, the link type and `hash_data` (e.g. the address being
    confirmed, or the password hash, so a reset link dies when the password
    changes). Only a SHA-256 digest of the token is stored, so the table
    alone gives no working links. Each link works once, until `expiration`."""

    def _generate_hash(self, user, type, hash_data, seed):
        # Keyed with SECRET_KEY: knowing the seed, user and data is not
        # enough to make a valid link.
        message = "%s%s%s%s" % (seed, "".join(map(str, hash_data)), user.id, type)
        return hmac.new(force_bytes(django_settings.SECRET_KEY), message.encode('utf-8'), hashlib.sha256).hexdigest()

    def create_new(self, user, type, hash_data=(), expiration=None):
        seed = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        token = self._generate_hash(user, type, hash_data, seed)

        obj = ValidationHash(hash_code=_token_digest(token), seed=seed, user=user, type=type)

        if expiration is not None:
            obj.expiration = expiration

        try:
            obj.save()
        except:
            return None

        obj.token = token  # for the email; never stored
        return obj

    def _find(self, hash):
        hash = str(hash)
        obj = self.filter(hash_code=_token_digest(hash)).first()
        if obj is None:  # a link made before tokens were stored as digests
            obj = self.filter(hash_code=hash).first()
        return obj

    def validate(self, hash, user, type, hash_data=(), consume=True):
        """Whether `hash` is a valid, unexpired link of `type` for `user`.
        It is used up unless `consume` is False (a page that only shows a form)."""
        obj = self._find(hash)
        if obj is None or obj.type != type or obj.user_id != user.id:
            return False

        valid = hmac.compare_digest(str(hash), self._generate_hash(user, type, hash_data, obj.seed))

        if valid:
            if obj.expiration < datetime.datetime.now():
                obj.delete()
                return False
            if consume:
                # Only the request that deletes the row uses the link: two at
                # once (e.g. a double-submitted reset form) can't both pass.
                return self.filter(pk=obj.pk).delete()[0] > 0
            return True

        return False

class ValidationHash(models.Model):
    hash_code = models.CharField(max_length=255, unique=True)
    seed = models.CharField(max_length=12)
    expiration = models.DateTimeField(default=one_day_from_now)
    type = models.CharField(max_length=12)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    objects = ValidationHashManager()

    class Meta:
        unique_together = ('user', 'type')
        app_label = 'forum'

    def __str__(self):
        return getattr(self, 'token', None) or self.hash_code

class AuthKeyUserAssociation(models.Model):
    key = models.CharField(max_length=255, null=False, unique=True)
    provider = models.CharField(max_length=64)
    user = models.ForeignKey(User, related_name="auth_keys", on_delete=models.CASCADE)
    added_at = models.DateTimeField(default=datetime.datetime.now)

    class Meta:
        app_label = 'forum'
