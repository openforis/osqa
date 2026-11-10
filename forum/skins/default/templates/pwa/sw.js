/* OSQA service worker (served by forum.views.pwa.service_worker at /sw.js).

   Caching rules
   -------------
   Only GET requests to this site are looked at; everything else (posts,
   votes, AJAX commands, uploads, other sites) goes straight to the network.

   Never intercepted at all (personal, mutating or not pages):
     /admin/, /nimda/, /account/ (sign-in, sign-out, settings), /notifications/,
     /users/ (profiles and their tabs), /upfiles/, /mcp, /export/, /pending-data/,
     /upload/, /preview/, /logout/, /i18n/, /csp-report/, /sw.js, the manifest.
   Requests that are neither skin media nor navigations (fetch/XHR, such as
   the live question page's /questions/<id>/updates/ polls) aren't either.

   Skin media (/m/<skin>/media/...), in a cache named after VERSION, a hash
   of this file and of the media files (the same content hashes as the ?v=
   tokens of media URLs), so each deploy gets a new cache and `activate`
   deletes the old ones. Versioned URLs (?v=<hash>) never change: cache first.
   Others (images referenced from CSS): stale-while-revalidate. Offline, a
   saved page that refers to an older version of a file gets the version in
   the cache (same path, any ?v=).

   Pages (navigations): network first. Successful (200) pages of the home
   page, question lists, questions and tags are stored in PAGES, newest last,
   trimmed to the last PAGE_CACHE_SIZE pages. Without a network the saved copy
   is served, marked with <meta name="osqa-offline-copy"> so the page shows
   the "you are offline" banner; any other page falls back to /offline/,
   which lists the saved pages. /offline/ is fetched without cookies when the
   worker installs, so it never shows who was signed in.

   Privacy: saved pages of a signed-in member show their name. The page cache
   is emptied when the browser navigates to the sign-out URL, and by
   osqa.pwa.js whenever the signed-in user differs from the one who was
   signed in when the pages were saved (session expired, another account).

   Push notifications (forum/utils/push.py, osqa.push.js)
   ------------------------------------------------------
   `push` shows the message the server sent: {title, body, url, tag, icon}
   (title and body are plain text; url is /notifications/<id>/, which marks
   the in-site notification read and redirects to the post). Messages with
   the same tag (one question) replace each other. `notificationclick`
   brings a forum tab to the front and opens the URL in it, or opens a new
   window. Only URLs of this site are opened. Signing out (the sign-out
   navigation above) also unsubscribes this browser from push. A push also
   sets the unread count on the installed app's icon (Badging API).
*/
'use strict';

const VERSION = '{{ version }}';
const PREFIX = {{ prefix|safe }};
const STATIC = 'osqa-static-' + VERSION;
const PAGES = 'osqa-pages-v1';
const PAGE_CACHE_SIZE = {{ page_cache_size }};
const OFFLINE_URL = PREFIX + '/offline/';
const APP_NAME = {{ app_name|safe }};
const ICON = {{ icon|safe }};
const NOTIFICATIONS_URL = PREFIX + '/notifications/';

const NEVER = /^\/(admin|nimda|account|notifications|users|upfiles|mcp|export|pending-data|upload|preview|logout|i18n|csp-report)(\/|$)|^\/(sw\.js|manifest\.webmanifest)$/;
const SIGN_OUT = /^\/account\/signout\/$/;
const MEDIA = /^\/m\/(?!django_admin\/|static\/)\w+\/media\//;
const SAVED_PAGES = [
    /^\/$/,
    /^\/questions\/$/,
    /^\/questions\/unanswered\/$/,
    /^\/questions\/\d+(\/[^\/]*)?$/,
    /^\/tags\/$/,
    /^\/tags\/[^\/]+\/$/,
];

function sitePath(url) {
    const path = url.pathname;
    return PREFIX && path.startsWith(PREFIX) ? path.slice(PREFIX.length) || '/' : path;
}

self.addEventListener('install', event => {
    event.waitUntil((async () => {
        const cache = await caches.open(STATIC);
        // The offline page as an anonymous visitor sees it, and the files it uses.
        const response = await fetch(OFFLINE_URL, {credentials: 'omit'});
        if (response.ok) {
            const html = await response.clone().text();
            await cache.put(OFFLINE_URL, response);
            const assets = new Set();
            for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
                const url = new URL(match[1].replace(/&amp;/g, '&'), self.location.href);
                if (url.origin === self.location.origin && MEDIA.test(sitePath(url))) assets.add(url.href);
            }
            await Promise.all([...assets].map(url => cache.add(url).catch(() => null)));
        }
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        for (const name of await caches.keys()) {
            if (name.startsWith('osqa-') && name !== STATIC && name !== PAGES) await caches.delete(name);
        }
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;
    const path = sitePath(url);
    // Signing out (the form POSTs): no saved pages, no more push on this browser.
    if (request.mode === 'navigate' && SIGN_OUT.test(path) && (request.method === 'GET' || request.method === 'POST')) {
        event.waitUntil(Promise.all([caches.delete(PAGES), stopPush()]));
        return;
    }
    if (request.method !== 'GET') return;
    if (NEVER.test(path)) return;
    if (MEDIA.test(path) && !request.headers.has('range')) {
        event.respondWith(url.searchParams.has('v') ? cacheFirst(event, request) : staleWhileRevalidate(event, request));
    } else if (request.mode === 'navigate') {
        event.respondWith(networkFirst(event, request, SAVED_PAGES.some(pattern => pattern.test(path))));
    }
});

async function cacheFirst(event, request) {
    const cache = await caches.open(STATIC);
    const cached = await cache.match(request);
    if (cached) return cached;
    try {
        const response = await fetch(request);
        if (response.ok && response.type === 'basic') event.waitUntil(cache.put(request, response.clone()));
        return response;
    } catch (error) {
        const other = await cache.match(request, {ignoreSearch: true});
        if (other) return other;
        throw error;
    }
}

async function staleWhileRevalidate(event, request) {
    const cache = await caches.open(STATIC);
    const cached = await cache.match(request);
    const fresh = fetch(request).then(response => {
        if (response.ok && response.type === 'basic') {
            event.waitUntil(cache.put(request, response.clone()));
        }
        return response;
    });
    if (cached) {
        event.waitUntil(fresh.catch(() => null));
        return cached;
    }
    return fresh.catch(async error => {
        const other = await cache.match(request, {ignoreSearch: true});
        if (other) return other;
        throw error;
    });
}

async function networkFirst(event, request, save) {
    try {
        const response = await fetch(request);
        const cacheControl = response.headers.get('Cache-Control') || '';
        if (save && response.status === 200 && response.type === 'basic' && !cacheControl.includes('no-store') &&
                (response.headers.get('Content-Type') || '').startsWith('text/html')) {
            event.waitUntil(savePage(request, response.clone()));
        }
        return response;
    } catch (error) {
        const cached = await caches.match(request.url, {cacheName: PAGES, ignoreVary: true});
        if (cached) return markedCopy(cached);
        const offline = await caches.match(OFFLINE_URL, {cacheName: STATIC, ignoreVary: true});
        if (offline) return markedCopy(offline);
        throw error;
    }
}

async function savePage(request, response) {
    const headers = new Headers(response.headers);
    headers.set('X-OSQA-Saved-At', new Date().toISOString());
    const copy = new Response(await response.blob(), {status: 200, statusText: response.statusText, headers: headers});
    const cache = await caches.open(PAGES);
    await cache.delete(request.url, {ignoreVary: true});  // re-added last: the cache keeps the order pages were saved
    await cache.put(request.url, copy);
    const keys = await cache.keys();
    for (const old of keys.slice(0, Math.max(0, keys.length - PAGE_CACHE_SIZE))) await cache.delete(old);
}

async function markedCopy(response) {
    const saved = response.headers.get('X-OSQA-Saved-At') || '';
    const html = (await response.text()).replace(/<head(\s[^>]*)?>/i,
        match => match + '<meta name="osqa-offline-copy" content="' + saved + '">');
    const headers = new Headers(response.headers);
    headers.delete('Content-Length');
    return new Response(html, {status: 200, headers: headers});
}

// -- push notifications ----------------------------------------------------

async function stopPush() {
    try {
        const subscription = self.registration.pushManager && await self.registration.pushManager.getSubscription();
        if (subscription) await subscription.unsubscribe();
    } catch (error) {
        // nothing subscribed, or push unavailable
    }
}

function siteUrl(url) {
    // Only this site's pages are opened from a notification.
    try {
        const parsed = new URL(url, self.location.origin);
        if (parsed.origin === self.location.origin && /^https?:$/.test(parsed.protocol)) return parsed.href;
    } catch (error) {
        // not a URL
    }
    return new URL(NOTIFICATIONS_URL, self.location.origin).href;
}

function text(value, length) {
    return typeof value === 'string' ? value.slice(0, length) : '';
}

self.addEventListener('push', event => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (error) {
        data = {};
    }
    if (!data || typeof data !== 'object') data = {};
    const options = {
        body: text(data.body, 200),
        icon: siteUrl(text(data.icon, 500) || ICON),
        badge: siteUrl(ICON),
        tag: text(data.tag, 64) || 'osqa-notification',
        renotify: true,
        data: {url: siteUrl(text(data.url, 500) || NOTIFICATIONS_URL), id: Number(data.id) || null},
    };
    event.waitUntil(Promise.all([
        self.registration.showNotification(text(data.title, 100) || APP_NAME, options),
        updateBadge(),
    ]));
});

// The unread count on the installed app's icon (Badging API), as the bell shows it.
async function updateBadge() {
    if (!self.navigator.setAppBadge) return;
    try {
        const response = await fetch(NOTIFICATIONS_URL + 'count/', {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
        if (!response.ok) return;
        const unread = Number((await response.json()).unread) || 0;
        await (unread ? self.navigator.setAppBadge(unread) : self.navigator.clearAppBadge());
    } catch (error) {
        // offline or signed out: leave it
    }
}

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = siteUrl(event.notification.data && event.notification.data.url);
    event.waitUntil((async () => {
        const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
        const tabs = windows.filter(client => new URL(client.url).origin === self.location.origin);
        tabs.sort((a, b) => (b.focused ? 1 : 0) - (a.focused ? 1 : 0));
        for (const tab of tabs) {
            let opened = null;
            try {
                // navigate() works for the tabs this worker controls; opening
                // /notifications/<id>/ marks the notification read.
                opened = await tab.navigate(url);
            } catch (error) {
                // not controlled by this worker: try the next one
            }
            if (opened) {
                try {
                    await opened.focus();
                } catch (error) {
                    // the browser decides whether a tab may come to the front
                }
                return;
            }
        }
        if (self.clients.openWindow) await self.clients.openWindow(url);
    })());
});
