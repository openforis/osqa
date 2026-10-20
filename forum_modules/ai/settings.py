from django.forms.widgets import RadioSelect, Textarea
from django.utils.translation import gettext_lazy as _

from forum.settings.base import Setting, SettingSet
from forum.settings.forms import SecretInput
from forum.settings.guides import Section, register, ON, OFF, WARNING

AI_SET = SettingSet('ai', _('AI assistance'), _(
    "Duplicate detection, spam moderation, an assistant and suggested answers with Google Gemini. Enabled "
    "features send the text of public posts (titles, bodies, comments) to Google (the Gemini API, or Vertex AI "
    "in your Google Cloud project); nothing else about the author is sent. Fill in the connection, press "
    "\"Test connection\" to check it, then save."), 2000)

# ---- Connection --------------------------------------------------------------

AI_PROVIDER = Setting('AI_PROVIDER', 'auto', AI_SET, dict(
label = _("Connect through"),
help_text = _("Automatic uses Vertex AI when a project is set (here or in GOOGLE_CLOUD_PROJECT), otherwise the "
              "Gemini API key."),
widget=RadioSelect,
choices=(('auto', _("Automatic")), ('gemini', _("Gemini API key")), ('vertex', _("Vertex AI (Google Cloud project)"))),
required=False))

# Kept under its old name (it was under External Keys), so saved keys still work.
GEMINI_API_KEY = Setting('GEMINI_API_KEY', '', AI_SET, dict(
label = _("Gemini API key"),
help_text = _("For the Gemini API: create a key at <a href='https://aistudio.google.com/apikey'>Google AI "
              "Studio</a> (it starts with AIza). If empty, the server's GEMINI_API_KEY or GOOGLE_API_KEY "
              "environment variable is used."),
widget=SecretInput(),
keywords = _("ai gemini google llm artificial intelligence"),
required=False))

AI_VERTEX_PROJECT = Setting('AI_VERTEX_PROJECT', '', AI_SET, dict(
label = _("Vertex AI project"),
help_text = _("For Vertex AI: the Google Cloud project ID (not its name or number). The server signs in with "
              "Application Default Credentials (on Google Cloud its service account, elsewhere "
              "GOOGLE_APPLICATION_CREDENTIALS or <code>gcloud auth application-default login</code>), which "
              "need the Vertex AI User role and the Vertex AI API enabled in the project. If empty, the "
              "GOOGLE_CLOUD_PROJECT environment variable is used."),
required=False))

AI_VERTEX_LOCATION = Setting('AI_VERTEX_LOCATION', 'global', AI_SET, dict(
label = _("Vertex AI location"),
help_text = _("Region of the Vertex AI endpoint: global (recommended, has the newest models), or e.g. "
              "europe-west1 or us-central1 to keep requests in a region."),
required=False))

AI_MODEL = Setting('AI_MODEL', 'gemini-3.8-flash', AI_SET, dict(
label = _("Gemini model"),
help_text = _("The model ID used for all text features, e.g. gemini-3.8-flash, or gemini-3.5-flash-lite for "
              "lower cost. It must support JSON output and thinking levels (Gemini 3 models do).")))

AI_EMBEDDING_MODEL = Setting('AI_EMBEDDING_MODEL', 'gemini-embedding-2', AI_SET, dict(
label = _("Embedding model"),
help_text = _("Gemini model used to index forum threads and documentation for semantic search and the "
              "assistant. After a change, the next run of manage.py build_knowledge_index embeds everything again "
              "(until then semantic search and the assistant find little).")))

# ---- Features ----------------------------------------------------------------

AI_DUPLICATE_DETECTION = Setting('AI_DUPLICATE_DETECTION', True, AI_SET, dict(
label = _("Duplicate detection"),
help_text = _("While someone writes a question title, point out existing questions that ask the same thing."),
required=False))

AI_DUPLICATE_CHECKS_PER_HOUR = Setting('AI_DUPLICATE_CHECKS_PER_HOUR', 30, AI_SET, dict(
label = _("Duplicate checks per visitor per hour"),
help_text = _("Limits API use; beyond it the ask page shows the plain keyword matches."),
min_value=0))

AI_SPAM_MODERATION = Setting('AI_SPAM_MODERATION', True, AI_SET, dict(
label = _("Spam and abuse moderation"),
help_text = _("Review new and edited posts in the background. Suspected spam, abuse or off-topic posts are listed "
              "for moderators under Flagged posts; they are never hidden or deleted automatically."),
required=False))

AI_MODERATION_SKIP_REP = Setting('AI_MODERATION_SKIP_REP', 500, AI_SET, dict(
label = _("Skip moderation from reputation"),
help_text = _("Posts by users with at least this reputation (and by staff) are not reviewed."),
min_value=0))

AI_MODERATION_MIN_CONFIDENCE = Setting('AI_MODERATION_MIN_CONFIDENCE', 0.7, AI_SET, dict(
label = _("Report from confidence"),
help_text = _("How sure (0 to 1) the review must be before a post is reported to moderators."),
min_value=0, max_value=1))

AI_PROFILE_REVIEW = Setting('AI_PROFILE_REVIEW', True, AI_SET, dict(
label = _("Profile spam review"),
help_text = _("When a user below the skip reputation fills in or changes their website or \"about me\", check it for "
              "profile spam (SEO links, advertising). Suspect accounts are listed for moderators under Flagged posts; "
              "they are never suspended or deleted automatically."),
required=False))

# ---- Knowledge index and assistant ----------------------------------------

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
help_text = _("Upper limit of documentation pages fetched from each URL above per run."),
min_value=1, max_value=10000))

AI_ASSISTANT = Setting('AI_ASSISTANT', True, AI_SET, dict(
label = _("Assistant on the ask page"),
help_text = _("Offer an AI answer before a question is posted. It is only shown when forum answers or the crawled "
              "documentation clearly cover the question and a second check finds every statement supported by them."),
required=False))

AI_ASSISTANT_PER_HOUR = Setting('AI_ASSISTANT_PER_HOUR', 10, AI_SET, dict(
label = _("Assistant answers per visitor per hour"),
min_value=0))

AI_SUGGEST_ANSWERS = Setting('AI_SUGGEST_ANSWERS', True, AI_SET, dict(
label = _("Suggested answers on unanswered questions"),
help_text = _("manage.py suggest_answers (run hourly) adds a clearly marked AI suggestion, with sources, to questions "
              "still unanswered after the time below, but only when forum answers or the crawled documentation clearly "
              "cover the question and a second check finds every statement supported by them. The asker and "
              "moderators can mark it helpful or remove it. It doesn't count as an answer and earns no reputation."),
required=False))

AI_SUGGEST_AFTER_HOURS = Setting('AI_SUGGEST_AFTER_HOURS', 24, AI_SET, dict(
label = _("Suggest an answer after (hours)"),
min_value=1))


# ---- Guidance on the page (forum/settings/guides.py) ------------------------------

def connection_status(values):
    from . import client, diagnostics
    if client.genai is None:
        return WARNING, _("The google-genai package is not installed on the server: pip install -r requirements.txt.")
    found = client.resolve(values)
    target = client.connection(values)
    if target is None:
        return OFF, ''
    if target[0] == 'gemini' and not found['key'][0].startswith('AIza'):
        return WARNING, _("Gemini API keys start with AIza; check that you copied the key itself.")
    return ON, diagnostics.describe(found, target)


def features_status(values):
    from . import client
    if not client.is_configured():
        return OFF, _("Needs the connection above.")
    return None, ''


def connection_panel(request):
    from .diagnostics import status_panel
    return status_panel(request)


register('ai', Section(
    'connection', _("Connection to Google Gemini"),
    ('AI_PROVIDER', 'GEMINI_API_KEY', 'AI_VERTEX_PROJECT', 'AI_VERTEX_LOCATION', 'AI_MODEL', 'AI_EMBEDDING_MODEL'),
    summary=_("Every AI feature on this page needs it. Fill it in, press <strong>Test connection</strong> to check "
              "it, then save."),
    steps=(
        _("Sign in to <a href=\"https://aistudio.google.com/apikey\">Google AI Studio</a> and choose "
          "<strong>Create API key</strong> (in a Google Cloud project with billing for more than the free "
          "tier's limits)."),
        _("Paste the key, which starts with <code>AIza</code>, under <strong>Gemini API key</strong>."),
        _("Or, on Google Cloud: choose <strong>Vertex AI</strong>, enter the project ID, enable the Vertex AI API "
          "in the project and give the server's account the Vertex AI User role."),
        _("Press <strong>Test connection</strong>: it says what works and, when something fails, how to fix it. "
          "Then save."),
    ),
    links=(("https://ai.google.dev/gemini-api/docs/api-key", _("Google: using Gemini API keys")),
           ("https://cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart",
            _("Google: Gemini on Vertex AI"))),
    keywords=_("ai gemini llm vertex artificial intelligence duplicates moderation assistant"),
    status=connection_status, extra=connection_panel, weight=10))

register('ai', Section(
    'moderation', _("Duplicates and moderation"),
    ('AI_DUPLICATE_DETECTION', 'AI_DUPLICATE_CHECKS_PER_HOUR', 'AI_SPAM_MODERATION', 'AI_MODERATION_SKIP_REP',
     'AI_MODERATION_MIN_CONFIDENCE', 'AI_PROFILE_REVIEW'),
    summary=_("While a question is written, and in the background after posts and profile changes. Nothing is "
              "hidden or deleted automatically: suspect posts and profiles go to the moderation inbox."),
    status=features_status, weight=20))

register('ai', Section(
    'knowledge', _("Knowledge index, assistant and suggested answers"),
    ('AI_KNOWLEDGE_SEEDS', 'AI_KNOWLEDGE_MAX_PAGES', 'AI_ASSISTANT', 'AI_ASSISTANT_PER_HOUR', 'AI_SUGGEST_ANSWERS',
     'AI_SUGGEST_AFTER_HOURS'),
    summary=_("Answers drawn only from the forum and the documentation below, with sources. The index is built "
              "nightly by manage.py build_knowledge_index; suggestions by manage.py suggest_answers (hourly)."),
    status=features_status, weight=30))
