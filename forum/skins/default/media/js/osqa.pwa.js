/* Installable app and offline reading (see templates/pwa/sw.js for the caching rules).
   - registers the service worker at the site root;
   - shows the "you are offline" banner on a saved copy served by the worker;
   - empties the saved pages when the signed-in user changes, so a shared
     computer doesn't keep showing a signed-out member's pages, and stops
     browser push (osqa.push.js) when another member signs in;
   - on /offline/, lists the saved pages. */
(function () {
    'use strict';
    var PAGES = 'osqa-pages-v1';
    var USER_KEY = 'osqa-pwa-user';
    var PUSH_USER_KEY = 'osqa-push-user';
    var script = document.currentScript;
    var user = script ? script.getAttribute('data-user') || '' : '';
    var root = window.scriptUrl || '/';
    var savedCopy = document.querySelector('meta[name="osqa-offline-copy"]');

    function whenReady(fn) {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
        else fn();
    }

    function forgetPagesIfUserChanged() {
        var previous = null;
        try {
            previous = window.localStorage.getItem(USER_KEY);
            window.localStorage.setItem(USER_KEY, user);
        } catch (e) {
            previous = null;
        }
        if (previous !== null && previous !== user && window.caches) {
            window.caches.delete(PAGES).catch(function () {});
        }
        forgetPushIfUserChanged();
    }

    // Browser push (osqa.push.js) was turned on by PUSH_USER_KEY's member: when
    // they sign out, or someone else signs in on this browser, it stops, so a
    // shared device doesn't keep showing their notifications (sw.js stops it
    // on the sign-out request too).
    function forgetPushIfUserChanged() {
        var owner = null;
        try {
            owner = window.localStorage.getItem(PUSH_USER_KEY);
        } catch (e) {
            return;
        }
        if (!owner || owner === user || !('serviceWorker' in navigator)) return;
        try {
            window.localStorage.removeItem(PUSH_USER_KEY);
        } catch (e) { /* ignore */ }
        navigator.serviceWorker.getRegistration(root).then(function (reg) {
            return reg && reg.pushManager ? reg.pushManager.getSubscription() : null;
        }).then(function (subscription) {
            return subscription ? subscription.unsubscribe() : null;
        }).catch(function () {});
    }

    function listSavedPages(list) {
        var empty = document.getElementById('offline-none');
        var suffix = list.getAttribute('data-title-suffix') || '';
        var show = function (entries) {
            entries.forEach(function (entry) {
                var item = document.createElement('li');
                var link = document.createElement('a');
                link.href = entry.url;
                link.textContent = entry.title;
                item.appendChild(link);
                if (entry.saved) {
                    var when = document.createElement('span');
                    when.className = 'offline-saved-at';
                    when.textContent = ' (' + new Date(entry.saved).toLocaleString(window.i18nLang || undefined) + ')';
                    item.appendChild(when);
                }
                list.appendChild(item);
            });
            if (empty) empty.hidden = entries.length > 0;
            list.setAttribute('data-loaded', String(entries.length));
        };
        if (!window.caches) return show([]);
        window.caches.open(PAGES).then(function (cache) {
            return cache.keys().then(function (requests) {
                return Promise.all(requests.reverse().map(function (request) {
                    return cache.match(request, {ignoreVary: true}).then(function (response) {
                        if (!response) return null;  // removed meanwhile
                        return response.text().then(function (html) {
                            var title = new DOMParser().parseFromString(html, 'text/html').title || request.url;
                            if (suffix && title.length > suffix.length && title.slice(-suffix.length) === suffix) {
                                title = title.slice(0, -suffix.length);
                            }
                            return {url: request.url, title: title, saved: response.headers.get('X-OSQA-Saved-At')};
                        });
                    });
                }));
            });
        }).then(function (entries) {
            show(entries.filter(Boolean));
        }, function () { show([]); });
    }

    whenReady(function () {
        var list = document.getElementById('offline-pages');
        if (list) listSavedPages(list);
        if (savedCopy && !list) {
            var banner = document.getElementById('offline-banner');
            if (banner) banner.hidden = false;
        }
    });

    if (savedCopy) return;  // a saved copy: who it shows is not who is signed in now
    forgetPagesIfUserChanged();
    // Signed out: no unread count on the app's icon (osqa.notifications.js sets it).
    if (!user && navigator.clearAppBadge) navigator.clearAppBadge().catch(function () {});
    if ('serviceWorker' in navigator && window.isSecureContext) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register(root + 'sw.js', {scope: root}).catch(function () {});
        });
    }
})();
