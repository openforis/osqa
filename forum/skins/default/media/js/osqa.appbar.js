/* The phone's bottom tab bar (display/app_bar.html): "More" opens the menu
   sheet as a modal dialog (the browser moves the focus in, closes it with
   Escape and gives the focus back to the button); a tap on the backdrop or
   the close button closes it too, and so does dragging it down by its head. */
(function () {
    'use strict';
    var button = document.getElementById('app-more');
    var sheet = document.getElementById('app-more-sheet');
    if (!button || !sheet || typeof sheet.showModal !== 'function') {
        return;
    }
    button.addEventListener('click', function () {
        sheet.style.transform = '';
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

    // Dragged down by more than a third of its height (or flicked), it
    // closes; otherwise it slides back.
    var head = sheet.querySelector('.app-sheet-head');
    var startY = null, lastY = 0, lastTime = 0, speed = 0;
    if (!head) {
        return;
    }
    head.addEventListener('pointerdown', function (evt) {
        if (evt.pointerType === 'mouse' || evt.target.closest('button')) {
            return;
        }
        startY = lastY = evt.clientY;
        lastTime = evt.timeStamp;
        speed = 0;
        head.setPointerCapture(evt.pointerId);
        sheet.classList.add('is-dragging');
    });
    head.addEventListener('pointermove', function (evt) {
        if (startY === null) {
            return;
        }
        var elapsed = evt.timeStamp - lastTime;
        if (elapsed > 0) {
            speed = (evt.clientY - lastY) / elapsed;
        }
        lastY = evt.clientY;
        lastTime = evt.timeStamp;
        sheet.style.transform = 'translateY(' + Math.max(0, evt.clientY - startY) + 'px)';
    });
    function release(evt) {
        if (startY === null) {
            return;
        }
        var moved = evt.clientY - startY;
        startY = null;
        sheet.classList.remove('is-dragging');
        if (evt.type === 'pointerup' && (moved > sheet.offsetHeight / 3 || (moved > 30 && speed > 0.5))) {
            sheet.close();
            sheet.style.transform = '';
            return;
        }
        sheet.classList.add('is-settling');
        sheet.style.transform = '';
        window.setTimeout(function () {
            sheet.classList.remove('is-settling');
        }, 200);
    }
    head.addEventListener('pointerup', release);
    head.addEventListener('pointercancel', release);
})();
