/* "Get notifications on this device" (templates/push/switch.html; server side
   in forum/utils/push.py). Permission is asked only when the switch is
   pressed, never on page load. Turning it on subscribes this browser with
   PushManager (the forum's VAPID public key) and sends the subscription to
   /push/subscribe/; turning it off unsubscribes and tells /push/unsubscribe/.
   Explains why it can't be turned on: unsupported browser, notifications
   blocked, or iPhone/iPad where the forum must be opened from the Home Screen. */
(function () {
    'use strict';
    if (window.osqaPush) return;
    window.osqaPush = true;

    var root = window.scriptUrl || '/';
    // Texts come from the switch's data-msg-* attributes (translated in the template).
    var STRINGS = {};

    function readStrings(box) {
        ['on', 'off', 'dismissed', 'failed', 'working'].forEach(function (name) {
            STRINGS[name] = STRINGS[name] || box.getAttribute('data-msg-' + name) || '';
        });
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function isIOS() {
        var ua = navigator.userAgent || '';
        return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    }

    function isStandalone() {
        return navigator.standalone === true ||
            (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
    }

    function supported() {
        return window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window &&
            'Notification' in window;
    }

    function keyBytes(base64url) {
        var padded = (base64url + '===='.slice(0, (4 - base64url.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
        var raw = window.atob(padded), bytes = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        return bytes;
    }

    function sameKey(subscription, key) {
        var old = subscription.options && subscription.options.applicationServerKey;
        if (!old) return true;  // the browser doesn't tell
        old = new Uint8Array(old);
        if (old.length !== key.length) return false;
        for (var i = 0; i < key.length; i++) if (old[i] !== key[i]) return false;
        return true;
    }

    function sha256(text) {
        return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)).then(function (buffer) {
            return Array.prototype.map.call(new Uint8Array(buffer), function (b) {
                return ('0' + b.toString(16)).slice(-2);
            }).join('');
        });
    }

    function post(url, data) {
        return fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken()},
            body: JSON.stringify(data)
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (body) {
                if (!response.ok) {
                    var error = new Error(body.error || STRINGS.failed);
                    error.fromServer = true;  // already a sentence for people
                    throw error;
                }
                return body;
            });
        });
    }

    function registration() {
        return navigator.serviceWorker.register(root + 'sw.js', {scope: root}).then(function () {
            return navigator.serviceWorker.ready;
        });
    }

    function Switch(box) {
        this.box = box;
        this.button = box.querySelector('.push-toggle');
        this.status = box.querySelector('.push-status');
        this.known = (box.getAttribute('data-endpoints') || '').split(/\s+/).filter(Boolean);
        this.busy = false;
        readStrings(box);
        box.hidden = false;
        this.button.addEventListener('click', this.toggle.bind(this));
    }

    Switch.prototype.note = function (name) {
        var notes = this.box.querySelectorAll('.push-note');
        for (var i = 0; i < notes.length; i++) notes[i].hidden = !notes[i].classList.contains('push-' + name);
    };

    Switch.prototype.show = function (on, message) {
        this.button.setAttribute('aria-checked', on ? 'true' : 'false');
        this.box.classList.toggle('is-on', on);
        if (message !== undefined) this.status.textContent = message;
    };

    Switch.prototype.unavailable = function (why) {
        this.note(why);
        this.button.disabled = true;
        this.box.classList.add('is-unavailable');
        this.show(false);
    };

    Switch.prototype.init = function () {
        var self = this;
        if (isIOS() && !isStandalone()) {
            return self.unavailable('ios');
        }
        if (!supported()) return self.unavailable('unsupported');
        if (Notification.permission === 'denied') return self.unavailable('denied');
        navigator.serviceWorker.getRegistration(root).then(function (reg) {
            return reg && reg.pushManager ? reg.pushManager.getSubscription() : null;
        }).then(function (subscription) {
            if (!subscription || Notification.permission !== 'granted') return false;
            return sha256(subscription.endpoint).then(function (hash) {
                markThisDevice(hash);
                return self.known.indexOf(hash) >= 0;
            });
        }).then(function (on) {
            self.show(on);
        }, function () {
            self.show(false);
        });
    };

    Switch.prototype.toggle = function () {
        if (this.busy) return;
        this.busy = true;
        this.button.setAttribute('aria-busy', 'true');
        this.status.textContent = STRINGS.working;
        var self = this;
        var done = function () {
            self.busy = false;
            self.button.removeAttribute('aria-busy');
        };
        var action = this.button.getAttribute('aria-checked') === 'true' ? this.turnOff() : this.turnOn();
        action.then(done, function (error) {
            done();
            // The browser's own errors (no push service, private window...) are technical.
            self.status.textContent = (error && error.fromServer && error.message) || STRINGS.failed;
        });
    };

    Switch.prototype.turnOn = function () {
        var self = this;
        // Asked here, after the press, and only here.
        return Promise.resolve(Notification.requestPermission()).then(function (permission) {
            if (permission === 'denied') {
                self.unavailable('denied');
                self.status.textContent = '';
                return null;
            }
            if (permission !== 'granted') {
                self.show(false, STRINGS.dismissed);
                return null;
            }
            var key = keyBytes(self.box.getAttribute('data-key'));
            return registration().then(function (reg) {
                var subscribe = function () {
                    return reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
                };
                return reg.pushManager.getSubscription().then(function (existing) {
                    if (!existing) return subscribe();
                    if (sameKey(existing, key)) return existing;
                    // Made with the site's previous keys: the server can't push to it.
                    return existing.unsubscribe().then(subscribe);
                });
            }).then(function (subscription) {
                return post(self.box.getAttribute('data-subscribe-url'), subscription.toJSON()).then(function () {
                    return sha256(subscription.endpoint);
                }, function (error) {
                    subscription.unsubscribe().catch(function () {});
                    throw error;
                });
            }).then(function (hash) {
                remember(self.box.getAttribute('data-user'));
                self.known.push(hash);
                markThisDevice(hash);
                syncAll(true);
            });
        });
    };

    Switch.prototype.turnOff = function () {
        var self = this;
        return navigator.serviceWorker.getRegistration(root).then(function (reg) {
            return reg && reg.pushManager ? reg.pushManager.getSubscription() : null;
        }).then(function (subscription) {
            if (!subscription) return null;
            var endpoint = subscription.endpoint;
            return subscription.unsubscribe().then(function () {
                return post(self.box.getAttribute('data-unsubscribe-url'), {endpoint: endpoint});
            });
        }).then(function () {
            remember(null);
            syncAll(false);
        });
    };

    var switches = [];

    // Who turned push on in this browser (osqa.pwa.js stops it when someone else signs in).
    function remember(user) {
        try {
            if (user) window.localStorage.setItem('osqa-push-user', user);
            else window.localStorage.removeItem('osqa-push-user');
        } catch (e) { /* private window: nothing to remember */ }
    }

    function syncAll(on) {
        switches.forEach(function (item) { item.show(on, on ? STRINGS.on : STRINGS.off); });
    }

    function markThisDevice(hash) {
        var items = document.querySelectorAll('.push-device');
        for (var i = 0; i < items.length; i++) {
            var mark = items[i].querySelector('.push-device-this');
            if (mark) mark.hidden = items[i].getAttribute('data-endpoint-hash') !== hash;
        }
    }

    // "Not now" on the asker's prompt (push/ask_prompt.html): not shown again for 30 days.
    document.addEventListener('click', function (evt) {
        var later = evt.target.closest && evt.target.closest('[data-push-prompt-later]');
        if (!later) return;
        try {
            window.localStorage.setItem('osqa-push-prompt', String(Date.now()));
        } catch (e) { /* private window: just hide it */ }
        var prompt = later.closest('.push-prompt');
        prompt.hidden = true;
        var heading = document.querySelector('h1');
        if (heading) {
            heading.setAttribute('tabindex', '-1');
            heading.focus({preventScroll: true});
        }
    });

    function start() {
        var boxes = document.querySelectorAll('[data-push-switch]');
        for (var i = 0; i < boxes.length; i++) {
            var item = new Switch(boxes[i]);
            switches.push(item);
            item.init();
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
