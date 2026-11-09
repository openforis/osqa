/* The phone's bottom tab bar (display/app_bar.html): "More" opens the menu
   sheet as a modal dialog (the browser moves the focus in, closes it with
   Escape and gives the focus back to the button); a tap on the backdrop or
   the close button closes it too. */
(function () {
    'use strict';
    var button = document.getElementById('app-more');
    var sheet = document.getElementById('app-more-sheet');
    if (!button || !sheet || typeof sheet.showModal !== 'function') {
        return;
    }
    button.addEventListener('click', function () {
        sheet.showModal();
        button.setAttribute('aria-expanded', 'true');
    });
    sheet.addEventListener('close', function () {
        button.setAttribute('aria-expanded', 'false');
    });
    sheet.addEventListener('click', function (evt) {
        if (evt.target === sheet || evt.target.closest('[data-sheet-close]')) {
            sheet.close();
        }
    });
})();
