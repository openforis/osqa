/* Keeps the notification bell's unread count current: checks every minute
   while the page is visible, and when the tab comes back into view. The
   phone's tab bar shows the same count (display/app_bar.html):
   [data-unread-badge] is hidden at 0, [data-unread-number] holds the number
   and [data-unread-label] the words for screen readers. The installed
   app's icon gets the same number. */
(function () {
    var bell = document.getElementById('notification-bell');
    if (!bell || !window.fetch) {
        return;
    }
    var badge = bell.querySelector('.notification-count');
    var baseTitle = document.title.replace(/^\(\d+\) /, '');

    function show(count) {
        badge.textContent = count;
        badge.hidden = !count;
        bell.classList.toggle('has-unread', count > 0);
        bell.setAttribute('aria-label', count ? bell.dataset.labelSome.replace('%(count)s', count) : bell.dataset.labelNone);
        document.title = (count ? '(' + count + ') ' : '') + baseTitle;
        document.querySelectorAll('[data-unread-badge]').forEach(function (el) { el.hidden = !count; });
        document.querySelectorAll('[data-unread-number]').forEach(function (el) { el.textContent = count; });
        document.querySelectorAll('[data-unread-label]').forEach(function (el) {
            el.textContent = count ? ', ' + bell.dataset.labelSome.replace('%(count)s', count) : '';
        });
        // The installed app's icon shows the count too (Badging API; the
        // service worker sets it when a push arrives).
        if (navigator.setAppBadge) {
            (count ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(function () {});
        }
    }

    function refresh() {
        if (document.visibilityState !== 'visible') {
            return;
        }
        fetch(bell.dataset.countUrl, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) { if (data) { show(data.unread); } })
            .catch(function () { /* offline: try again next time */ });
    }

    show(parseInt(badge.textContent, 10) || 0);
    setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
})();
