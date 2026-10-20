/*
 * Google Analytics 4 with consent (display/analytics_consent.html,
 * forum/utils/analytics.py).
 *
 * The banner asks every visitor; an inline script shows it before the first
 * paint while no choice is remembered. The choice goes into a first-party
 * cookie (accepted for 13 months, declined for 6, then the banner asks
 * again). gtag.js is fetched only after "Accept", with Consent Mode's
 * advertising signals denied, so nothing reaches Google before or without
 * consent. "Decline" after accepting turns Analytics off on this page and
 * deletes its cookies. Any [data-analytics-settings] button (the footer's
 * "Analytics cookies") shows the banner again.
 */
(function () {
    'use strict';

    var banner = document.getElementById('analytics-consent');
    if (!banner) return;

    var id = banner.getAttribute('data-measurement-id');
    var cookie = banner.getAttribute('data-cookie');
    var DAYS = {yes: 395, no: 182};
    var loaded = false;
    var opener = null;

    function remembered() {
        var match = document.cookie.match(new RegExp('(?:^|;\\s*)' + cookie + '=(yes|no)(?:;|$)'));
        return match ? match[1] : null;
    }

    function remember(choice) {
        document.cookie = cookie + '=' + choice + '; max-age=' + DAYS[choice] * 86400 + '; path=' +
            (window.scriptUrl || '/') + '; samesite=lax' + (location.protocol === 'https:' ? '; secure' : '');
    }

    function gtag() {
        window.dataLayer.push(arguments);
    }

    function load() {
        window['ga-disable-' + id] = false;
        if (loaded) {
            gtag('consent', 'update', {analytics_storage: 'granted'});
            return;
        }
        loaded = true;
        window.dataLayer = window.dataLayer || [];
        window.gtag = gtag;
        gtag('consent', 'default', {
            ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied',
            analytics_storage: 'granted'
        });
        gtag('js', new Date());
        gtag('config', id, {allow_google_signals: false, allow_ad_personalization_signals: false});
        var script = document.createElement('script');
        script.async = true;
        script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
        document.head.appendChild(script);
    }

    // Analytics cookies are set on the widest domain the browser allows
    // (cookie_domain "auto"): try every level of this host.
    function forgetAnalyticsCookies() {
        var names = document.cookie.split(';').map(function (part) {
            return part.split('=')[0].trim();
        }).filter(function (name) {
            return name === '_ga' || name.indexOf('_ga_') === 0 || name === '_gid' || name === '_gat';
        });
        var parts = location.hostname.split('.');
        names.forEach(function (name) {
            for (var i = 0; i < parts.length; i++) {
                var domain = parts.slice(i).join('.');
                document.cookie = name + '=; max-age=0; path=/; domain=' + domain;
            }
            document.cookie = name + '=; max-age=0; path=/';
        });
    }

    function stop() {
        window['ga-disable-' + id] = true;
        if (loaded) gtag('consent', 'update', {analytics_storage: 'denied'});
        forgetAnalyticsCookies();
    }

    function show(from) {
        var current = remembered();
        banner.querySelectorAll('[data-consent-current]').forEach(function (line) {
            line.hidden = line.getAttribute('data-consent-current') !== current;
        });
        opener = from || null;
        banner.hidden = false;
        banner.scrollIntoView({block: 'nearest'});
        banner.focus();
    }

    function choose(choice) {
        remember(choice);
        if (choice === 'yes') load(); else stop();
        banner.hidden = true;
        // Back to the button that showed the banner, or on to the page.
        var next = opener || document.getElementById('wrapper');
        opener = null;
        if (next) {
            if (!next.hasAttribute('tabindex') && !/^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(next.tagName)) {
                next.setAttribute('tabindex', '-1');
            }
            next.focus({preventScroll: true});
        }
    }

    banner.addEventListener('click', function (event) {
        var button = event.target.closest('[data-analytics-choice]');
        if (button) choose(button.getAttribute('data-analytics-choice'));
    });

    document.querySelectorAll('[data-analytics-settings]').forEach(function (button) {
        button.hidden = false;
    });
    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-analytics-settings]');
        if (!button) return;
        event.preventDefault();
        show(button);
    });

    if (remembered() === 'yes') load();
})();
