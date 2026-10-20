"""Installable app: the web app manifest, the service worker and the offline page.

The service worker (template `pwa/sw.js`, caching rules documented there) is
served from the site root so its scope covers every page; the browser checks
it for updates on navigations, so it is never cached for long. Its static
cache is named after a hash of the worker itself and of the skin media files
(the same content hashes as the ?v= tokens of media URLs), so each deploy that
changes either gets a fresh cache and the old one is dropped when the new
worker activates.
"""
import hashlib
import json
import os

from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.utils.translation import get_language
from django.views.decorators.cache import cache_control

from forum import settings
from forum.templatetags.extra_tags import media
from forum.utils import appearance, static_files

THEME_COLOR_DARK = '#161b22'   # osqa.css --surface in dark mode (the header)
BACKGROUND_COLOR = '#f5f7fa'   # osqa.css --background
PAGE_CACHE_SIZE = 50

SKINS_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'skins')
BUNDLED_UPFILES_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'upfiles')
IMAGE_TYPES = {'PNG': 'image/png', 'WEBP': 'image/webp', 'JPEG': 'image/jpeg', 'GIF': 'image/gif'}

_version = None
_logo_cache = {}


def prefix():
    return settings.FORCE_SCRIPT_NAME or ''


def bundled_icons():
    return [
        {'src': media('/media/images/icons/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': media('/media/images/icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': media('/media/images/icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
         'purpose': 'maskable'},
    ]


def logo_icon():
    """The admin's APP_LOGO as an icon, when it is an uploaded image that is
    (nearly) square and at least 192 pixels wide; None otherwise (the bundled
    default logo is a wide word mark, so the bundled icons are used)."""
    logo = str(settings.APP_LOGO or '')
    if not logo.startswith('/upfiles/'):
        return None
    relative = logo[len('/upfiles/'):].split('?')[0]
    for root in (str(settings.UPFILES_FOLDER), BUNDLED_UPFILES_ROOT):
        root = os.path.realpath(root)
        path = os.path.realpath(os.path.join(root, relative))
        if path.startswith(root + os.sep) and os.path.isfile(path):
            break
    else:
        return None
    key = (path, os.path.getmtime(path))
    if key not in _logo_cache:
        _logo_cache.clear()
        _logo_cache[key] = _read_logo(path, logo)
    return _logo_cache[key]


def _read_logo(path, url):
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
            kind = IMAGE_TYPES.get(image.format)
    except Exception:
        return None
    if not kind or min(width, height) < 192 or max(width, height) > 1.25 * min(width, height):
        return None
    return {'src': prefix() + url, 'sizes': '%dx%d' % (width, height), 'type': kind, 'purpose': 'any'}


def icons():
    logo = logo_icon()
    return [logo] if logo else bundled_icons()


def touch_icon_url():
    logo = logo_icon()
    return logo['src'] if logo else media('/media/images/icons/apple-touch-icon.png')


@cache_control(max_age=3600)
def manifest(request):
    root = prefix() + '/'
    data = {
        'id': root,
        'name': str(settings.APP_TITLE),
        'short_name': str(settings.APP_SHORT_NAME),
        'description': str(settings.APP_DESCRIPTION),
        'lang': get_language() or 'en',
        'start_url': root,
        'scope': root,
        'display': 'standalone',
        'theme_color': appearance.theme_color(),
        'background_color': BACKGROUND_COLOR,
        'icons': icons(),
    }
    return HttpResponse(json.dumps(data, indent=2), content_type='application/manifest+json')


def version():
    """Changes whenever the worker or any skin media file changes (computed once per process).

    Made of the same content hashes as the ?v= tokens of {% media %} URLs
    (forum.utils.static_files), so a deploy that changes a file changes both
    its URL and the worker's cache name, and every server of a deploy agrees.
    """
    global _version
    if _version is None:
        digest = hashlib.sha256(get_template('pwa/sw.js').template.source.encode())
        for folder, dirs, files in sorted(os.walk(SKINS_ROOT)):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(folder, name)
                if os.sep + 'media' + os.sep in path:
                    digest.update(('%s:%s;' % (os.path.relpath(path, SKINS_ROOT).replace(os.sep, '/'),
                                               static_files.file_token(path))).encode())
        _version = digest.hexdigest()[:12]
    return _version


@cache_control(no_cache=True, max_age=0)
def service_worker(request):
    response = render(request, 'pwa/sw.js', {
        'version': version(),
        'prefix': json.dumps(prefix()),
        'page_cache_size': PAGE_CACHE_SIZE,
        # Push notifications: the title when a message has none, and the icon.
        'app_name': json.dumps(str(settings.APP_SHORT_NAME)),
        'icon': json.dumps(icons()[0]['src']),
    }, content_type='application/javascript; charset=utf-8')
    response['Service-Worker-Allowed'] = prefix() + '/'
    return response


def offline(request):
    return render(request, 'pwa/offline.html')
