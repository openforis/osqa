from django.forms.widgets import Textarea
from django.utils.translation import gettext_lazy as _

from forum.settings.base import Setting, SettingSet
from forum.settings.extkeys import EXT_KEYS_SET
from forum.settings.forms import SecretInput
from forum.settings.guides import Section, register, ON, OFF, WARNING

AI_SET = SettingSet('ai', _('AI assistance'), _(
    "Duplicate detection and spam moderation with Google Gemini. Enabled features send the text of new public "
    "posts (titles, bodies, comments) to Google (the Gemini API, or Vertex AI in your Google Cloud project); "
    "nothing else about the author is sent."), 2000)

GEMINI_API_KEY = Setting('GEMINI_API_KEY', '', EXT_KEYS_SET, dict(
label = _("Gemini API key"),
help_text = _("Turns on the AI features (Admin > AI assistance) through the Gemini API. Get a key at "
              "<a href='https://aistudio.google.com/apikey'>Google AI Studio</a>. Not needed when a Vertex AI "
              "project is set under Admin > AI assistance. If empty, the server's GEMINI_API_KEY or "
              "GOOGLE_API_KEY environment variable is used."),
widget=SecretInput(),
keywords = _("ai gemini google llm artificial intelligence"),
required=False))

AI_VERTEX_PROJECT = Setting('AI_VERTEX_PROJECT', '', AI_SET, dict(
label = _("Vertex AI project"),
help_text = _("Google Cloud project ID to use Gemini through Vertex AI instead of an API key. The server "
              "authenticates with Application Default Credentials (its service account, or "
              "<code>gcloud auth application-default login</code>), which need the Vertex AI User role. "
              "If empty, the GOOGLE_CLOUD_PROJECT environment variable is used."),
required=False))

AI_VERTEX_LOCATION = Setting('AI_VERTEX_LOCATION', 'global', AI_SET, dict(
label = _("Vertex AI location"),
help_text = _("Region of the Vertex AI endpoint, e.g. global, europe-west1 or us-central1."),
required=False))

AI_MODEL = Setting('AI_MODEL', 'gemini-3.8-flash', AI_SET, dict(
label = _("Gemini model"),
help_text = _("The model ID used for all AI features, e.g. gemini-3.8-flash, or gemini-3.5-flash-lite for lower cost.")))

AI_DUPLICATE_DETECTION = Setting('AI_DUPLICATE_DETECTION', True, AI_SET, dict(
label = _("Duplicate detection"),
help_text = _("While someone writes a question title, point out existing questions that ask the same thing."),
required=False))

AI_DUPLICATE_CHECKS_PER_HOUR = Setting('AI_DUPLICATE_CHECKS_PER_HOUR', 30, AI_SET, dict(
label = _("Duplicate checks per visitor per hour"),
help_text = _("Limits API use; beyond it the ask page shows the plain keyword matches.")))

AI_SPAM_MODERATION = Setting('AI_SPAM_MODERATION', True, AI_SET, dict(
label = _("Spam and abuse moderation"),
help_text = _("Review new and edited posts in the background. Suspected spam, abuse or off-topic posts are listed "
              "for moderators under Flagged posts; they are never hidden or deleted automatically."),
required=False))

AI_MODERATION_SKIP_REP = Setting('AI_MODERATION_SKIP_REP', 500, AI_SET, dict(
label = _("Skip moderation from reputation"),
help_text = _("Posts by users with at least this reputation (and by staff) are not reviewed.")))

AI_MODERATION_MIN_CONFIDENCE = Setting('AI_MODERATION_MIN_CONFIDENCE', 0.7, AI_SET, dict(
label = _("Report from confidence"),
help_text = _("How sure (0 to 1) the review must be before a post is reported to moderators.")))

AI_PROFILE_REVIEW = Setting('AI_PROFILE_REVIEW', True, AI_SET, dict(
label = _("Profile spam review"),
help_text = _("When a user below the skip reputation fills in or changes their website or \"about me\", check it for "
              "profile spam (SEO links, advertising). Suspect accounts are listed for moderators under Flagged posts; "
              "they are never suspended or deleted automatically."),
required=False))

# ---- Knowledge index and assistant ----------------------------------------

AI_EMBEDDING_MODEL = Setting('AI_EMBEDDING_MODEL', 'gemini-embedding-2', AI_SET, dict(
label = _("Embedding model"),
help_text = _("Gemini model used to index forum threads and documentation for semantic search.")))

AI_KNOWLEDGE_SEEDS = Setting('AI_KNOWLEDGE_SEEDS', "https://openforis.org/\n"
                             "https://collect-earth-online-doc.readthedocs.io/en/latest/\n"
                             "https://www.fao.org/in-action/openforis/\n"
                             "https://earthmap.org/", AI_SET, dict(
label = _("Documentation to crawl"),
help_text = _("One URL per line. The nightly index (manage.py build_knowledge_index) crawls each one and the pages "
              "linked from it within the same site and path, respecting robots.txt, and lets the assistant use them."),
widget=Textarea(attrs={'rows': 6}),
required=False))

AI_KNOWLEDGE_MAX_PAGES = Setting('AI_KNOWLEDGE_MAX_PAGES', 300, AI_SET, dict(
label = _("Pages to crawl per URL"),
help_text = _("Upper limit of documentation pages fetched from each URL above per run.")))

AI_ASSISTANT = Setting('AI_ASSISTANT', True, AI_SET, dict(
label = _("Assistant on the ask page"),
help_text = _("Offer an AI answer before a question is posted. It is only shown when forum answers or the crawled "
              "documentation clearly cover the question and a second check finds every statement supported by them."),
required=False))

AI_ASSISTANT_PER_HOUR = Setting('AI_ASSISTANT_PER_HOUR', 10, AI_SET, dict(
label = _("Assistant answers per visitor per hour")))

AI_SUGGEST_ANSWERS = Setting('AI_SUGGEST_ANSWERS', True, AI_SET, dict(
label = _("Suggested answers on unanswered questions"),
help_text = _("manage.py suggest_answers (run hourly) adds a clearly marked AI suggestion, with sources, to questions "
              "still unanswered after the time below, but only when forum answers or the crawled documentation clearly "
              "cover the question and a second check finds every statement supported by them. The asker and "
              "moderators can mark it helpful or remove it. It doesn't count as an answer and earns no reputation."),
required=False))

AI_SUGGEST_AFTER_HOURS = Setting('AI_SUGGEST_AFTER_HOURS', 24, AI_SET, dict(
label = _("Suggest an answer after (hours)")))


def gemini_status(values):
    import os
    key = str(values.get('GEMINI_API_KEY') or '').strip()
    project = str(AI_VERTEX_PROJECT).strip() or os.environ.get('GOOGLE_CLOUD_PROJECT', '').strip()
    if project:
        return ON, _("AI features run through Vertex AI in the Google Cloud project %s (Admin > AI assistance); "
                     "the key is not used.") % project
    if key and not key.startswith('AIza'):
        return WARNING, _("Gemini API keys start with AIza; check that you copied the key itself.")
    if key:
        return ON, _("AI features are on; choose which ones under Admin > AI assistance.")
    if os.environ.get('GEMINI_API_KEY', '').strip() or os.environ.get('GOOGLE_API_KEY', '').strip():
        return ON, _("Using the key in the server's GEMINI_API_KEY or GOOGLE_API_KEY environment variable.")
    return OFF, ''


register('extkeys', Section(
    'gemini', _("Google Gemini (AI assistance)"), ('GEMINI_API_KEY',),
    summary=_("Turns on duplicate detection, spam and abuse review, and the answer assistant. The text of new "
              "public posts is sent to Google; see Admin > AI assistance for what each feature does."),
    steps=(
        _("Sign in to <a href=\"https://aistudio.google.com/apikey\">Google AI Studio</a> and choose "
          "<strong>Create API key</strong> (in a Google Cloud project with billing for more than the free "
          "tier's limits)."),
        _("Paste the key, which starts with <code>AIza</code>, below and save."),
        _("Choose the features and the model under Admin &gt; AI assistance. On Google Cloud you can use a "
          "Vertex AI project there instead of a key."),
    ),
    links=(("https://ai.google.dev/gemini-api/docs/api-key", _("Google: using Gemini API keys")),),
    keywords=_("ai gemini llm vertex artificial intelligence duplicates moderation assistant"),
    status=gemini_status, weight=30))
