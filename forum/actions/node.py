from django.utils.html import strip_tags, escape
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from forum.models.action import ActionProxy
from forum.models import Comment, Question, Answer, NodeRevision
from forum import settings, REQUEST_HOLDER
from forum.utils import review

from django.contrib import messages

class NodeEditAction(ActionProxy):
    def create_revision_data(self, initial=False, **data):
        revision_data = dict(summary=data.get('summary', (initial and _('Initial revision') or '')), body=data['text'])

        if data.get('title', None):
            revision_data['title'] = strip_tags(data['title'].strip())

        if data.get('tags', None):
            revision_data['tagnames'] = data['tags'].strip()

        return revision_data

class AskAction(NodeEditAction):
    verb = _lazy("asked")

    def process_data(self, **data):
        processed_data = self.create_revision_data(True, **data)
        # Node.summary is a read-only property; the initial revision gets no summary.
        processed_data.pop('summary', None)
        if 'added_at' in data:
            processed_data['added_at'] = data['added_at']

        self._review_state = review.state_for_new_post(self.user)
        # Held posts are hidden from their first save (search index, tag counts).
        question = Question(author=self.user, state_string=review.state_mark(self._review_state), **processed_data)
        question.save()
        self.node = question

    def process_action(self):
        review.queue_post(self, getattr(self, '_review_state', None))
        messages.info(REQUEST_HOLDER.request, review.held_notice() if review.is_held(self.node) else self.describe(self.user))

    def describe(self, viewer=None):
        return _("%(user)s asked %(question)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'question': self.hyperlink(self.node.get_absolute_url(), self.node.title)
        }

class AnswerAction(NodeEditAction):
    verb = _lazy("answered")

    def process_data(self, **data):
        revision_data = self.create_revision_data(True, **data)
        revision_data.pop('summary', None)
        self._review_state = review.state_for_new_post(self.user, data['question'])
        answer = Answer(author=self.user, parent=data['question'], state_string=review.state_mark(self._review_state),
                        **revision_data)
        answer.save()
        self.node = answer

    def process_action(self):
        review.queue_post(self, getattr(self, '_review_state', None))
        self.node.question.reset_answer_count_cache()

        messages.info(REQUEST_HOLDER.request, review.held_notice() if review.is_held(self.node) else self.describe(self.user))


    def describe(self, viewer=None):
        question = self.node.parent
        if question is None:  # the answer was converted into a question since
            question = original_question(AnswerToQuestionAction.objects.filter(node=self.node).first() or self)
        return _("%(user)s answered %(asker)s on %(question)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'asker': self.hyperlink(question.author.get_profile_url(), self.friendly_username(viewer, question.author)),
            'question': self.hyperlink(self.node.get_absolute_url(), question.title)
        }

class CommentAction(ActionProxy):
    verb = _lazy("commented")

    def process_data(self, text='', parent=None):
        self._review_state = review.state_for_new_post(self.user, parent)
        comment = Comment(author=self.user, parent=parent, body=text, state_string=review.state_mark(self._review_state))
        comment.save()
        self.node = comment

    def process_action(self):
        review.queue_post(self, getattr(self, '_review_state', None))

    def describe(self, viewer=None):
        post = self.node.parent
        if post is None:  # the comment was converted into a question since
            post = original_question(CommentToQuestionAction.objects.filter(node=self.node).first() or self)
        return _("%(user)s commented on %(post_desc)s") % {
            'user': self.hyperlink(self.node.author.get_profile_url(), self.friendly_username(viewer, self.node.author)),
            'post_desc': self.describe_node(viewer, post)
        }

class ReviseAction(NodeEditAction):
    verb = _lazy("edited")

    def process_data(self, **data):
        revision_data = self.create_revision_data(**data)
        revision = self.node.create_revision(self.user, **revision_data)
        self.extra = revision.revision

    def process_action(self):
        self.node.last_edited = self
        self.node.save()

    def describe(self, viewer=None):
        return _("%(user)s edited %(post_desc)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'post_desc': self.describe_node(viewer, self.node)
        }

    def get_absolute_url(self):
        return self.node.get_revisions_url()

class RetagAction(ActionProxy):
    verb = _lazy("retagged")

    def process_data(self, tagnames=''):
        active = self.node.active_revision
        revision_data = dict(summary=_('Retag'), title=active.title, tagnames=strip_tags(tagnames.strip()), body=active.body)
        revision = self.node.create_revision(self.user, **revision_data)
        self.extra = revision.revision

    def process_action(self):
        self.node.last_edited = self
        self.node.save()

    def describe(self, viewer=None):
        return _("%(user)s retagged %(post_desc)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'post_desc': self.describe_node(viewer, self.node)
        }

    def get_absolute_url(self):
        return self.node.get_revisions_url()

class RollbackAction(ActionProxy):
    verb = _lazy("reverted")

    def process_data(self, activate=None):
        previous = self.node.active_revision
        self.node.activate_revision(self.user, activate)
        self.extra = "%d:%d" % (previous.revision, activate.revision)

    def process_action(self):
        self.node.last_edited = self
        self.node.save()

    def describe(self, viewer=None):
        revisions = [NodeRevision.objects.get(node=self.node, revision=int(n)) for n in self.extra.split(':')]

        return _("%(user)s reverted %(post_desc)s from revision %(initial)d (%(initial_sum)s) to revision %(final)d (%(final_sum)s)") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'post_desc': self.describe_node(viewer, self.node),
            'initial': revisions[0].revision, 'initial_sum': escape(revisions[0].summary),
            'final': revisions[1].revision, 'final_sum': escape(revisions[1].summary),
        }

    def get_absolute_url(self):
        return self.node.get_revisions_url()

class CloseAction(ActionProxy):
    verb = _lazy("closed")

    def process_data(self, duplicate_of=None, move_answers=False):
        self._duplicate_of = duplicate_of
        self._move_answers = move_answers

    def process_action(self):
        duplicate_of = getattr(self, '_duplicate_of', None)

        self.node.marked = True
        self.node.nstate.closed = self
        self.node.last_edited = self
        if duplicate_of:
            extra = dict(self.node.extra) if isinstance(self.node.extra, dict) else {}
            extra['duplicate_of'] = duplicate_of.id
            self.node.extra = extra
        self.node.update_last_activity(self.user, save=True)

        if duplicate_of and getattr(self, '_move_answers', False):
            self.move_answers_to(duplicate_of)

    def move_answers_to(self, target):
        """Merge a duplicate: its answers (with their comments) move to the original question."""
        from forum.models import Answer
        question = self.node
        for answer in list(question.answers.all()):
            if answer.nis.accepted:
                # The acceptance belonged to the duplicate's asker.
                answer.nstate.accepted.cancel(self.user, ip=self.ip)
                answer = Answer.objects.get(id=answer.id)
            answer.parent = target
            answer.abs_parent = target
            answer.save()
            for comment in answer.comments.all():
                comment.abs_parent = target
                comment.save()

        for q in (question, target):
            q.reset_answer_count_cache()
            q.reset_accepted_count_cache()
        target.update_last_activity(self.user, save=True)

    def cancel_action(self):
        self.node.marked = False
        self.node.nstate.closed = None
        if isinstance(self.node.extra, dict) and 'duplicate_of' in self.node.extra:
            extra = dict(self.node.extra)
            del extra['duplicate_of']
            self.node.extra = extra
        self.node.update_last_activity(self.user, save=True)

    def describe(self, viewer=None):
        return _("%(user)s closed %(post_desc)s: %(reason)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'post_desc': self.describe_node(viewer, self.node),
            'reason': escape(self.extra)
        }

class AnswerToCommentAction(ActionProxy):
    verb = _lazy("converted")

    def process_data(self, new_parent=None):
        self.node.parent = new_parent
        self.node.node_type = "comment"

        for comment in self.node.comments.all():
            comment.parent = new_parent
            comment.save()

        self.node.last_edited = self
        self.node.update_last_activity(self.user, save=True)
        try:
            self.node.abs_parent.reset_answer_count_cache()
        except AttributeError:
            pass

    def describe(self, viewer=None):
        return _("%(user)s converted an answer to %(question)s into a comment") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'question': self.describe_node(viewer, self.node.abs_parent),
        }

class CommentToAnswerAction(ActionProxy):
    verb = _lazy("converted")

    def process_data(self, question):
        self.node.parent = question
        self.node.node_type = "answer"
        self.node.last_edited = self
        self.node.update_last_activity(self.user, save=True)

        # Now updated the cached data
        question.reset_answer_count_cache()

    def describe(self, viewer=None):
        return _("%(user)s converted comment on %(question)s into an answer") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'question': self.describe_node(viewer, self.node.abs_parent),
        }
def original_question(action):
    """The question a converted post belonged to (its parent links are
    cleared by the conversion); the new question itself if it's gone."""
    from forum.models import Question
    extra = action.extra if isinstance(action.extra, dict) else {}
    # Older conversions stored the question object itself.
    question_id = extra.get('original_question_id') or getattr(extra.get('original_question'), 'id', None)
    return Question.objects.filter(id=question_id).first() or action.node

class CommentToQuestionAction(NodeEditAction):
    verb = _lazy("converted")

    def process_data(self, **data):
        revision_data = self.create_revision_data(**data)
        revision = self.node.create_revision(self.user, **revision_data)

        self.extra = {
            'covert_revision': revision.revision,
            'original_question_id': self.node.abs_parent_id,
        }

        self.node.node_type = "question"
        self.node.parent = None
        self.node.abs_parent = None

    def process_action(self):
        self.node.last_edited = self
        self.node.save()

    def describe(self, viewer=None):
        return _("%(user)s converted comment on %(question)s to a new question") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'question': self.describe_node(viewer, original_question(self)),
        }

class AnswerToQuestionAction(NodeEditAction):
    verb = _lazy("converted to question")

    def process_data(self,  **data):
        revision_data = self.create_revision_data(**data)
        revision = self.node.create_revision(self.user, **revision_data)

        original_question = self.node.question

        self.extra = {
            'covert_revision': revision.revision,
            'original_question_id': original_question.id,
        }

        self.node.node_type = "question"
        self.node.parent = None
        self.node.abs_parent = None

        original_question.reset_answer_count_cache()

    def process_action(self):
        self.node.last_edited = self
        self.node.save()


    def describe(self, viewer=None):
        return _("%(user)s converted an answer to %(question)s into a separate question") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'question': self.describe_node(viewer, original_question(self)),
        }

class WikifyAction(ActionProxy):
    verb = _lazy("wikified")

    def process_action(self):
        self.node.nstate.wiki = self
        self.node.last_edited = self
        self.node.update_last_activity(self.user, save=True)

    def cancel_action(self):
        self.node.nstate.wiki = None
        self.node.update_last_activity(self.user, save=True)

    def describe(self, viewer=None):
        return _("%(user)s marked %(node)s as community wiki.") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'node': self.describe_node(viewer, self.node),
        }



class QueueForReviewAction(ActionProxy):
    """A new post went to the review queue (FIRST_POSTS_MODERATION): `extra`
    is the state, 'pending_review' (held) or 'unreviewed' (published). The
    action of that node state; see forum/utils/review.py."""
    verb = _lazy("waiting for review")

    def describe(self, viewer=None):
        return _("%(post_desc)s is waiting for review") % {
            'post_desc': self.describe_node(viewer, self.node),
        }


class ApprovePostAction(ActionProxy):
    """A moderator approved a post from the review queue. A held post is
    published (and the posts held under it approved with it); followers get
    the notifications that were held back (hooks in forum/subscriptions.py and
    forum/notifications.py). Cancelling it puts the post back in the queue."""
    verb = _lazy("approved")

    def save(self, data=None, *args, **kwargs):
        if not self.id:
            self.extra = {'state': review.HELD if review.is_held(self.node) else review.UNREVIEWED}
        return super().save(data, *args, **kwargs)

    def process_action(self):
        for child in review.release(self.node):
            approval = ApprovePostAction(user=self.user, node=child, ip=self.ip)
            approval.cascade = True
            approval.save()

    def cancel_action(self):
        state = self.extra.get('state') if isinstance(self.extra, dict) else None
        review.hold_again(self.node, state or review.UNREVIEWED)

    @property
    def was_held(self):
        return isinstance(self.extra, dict) and self.extra.get('state') == review.HELD

    def describe(self, viewer=None):
        return _("%(user)s approved %(post_desc)s") % {
            'user': self.hyperlink(self.user.get_profile_url(), self.friendly_username(viewer, self.user)),
            'post_desc': self.describe_node(viewer, self.node),
        }
