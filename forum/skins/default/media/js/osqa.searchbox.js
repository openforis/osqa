/* The header search box (header.html #searchbox).

   - Suggestions while typing: questions, tags and people from
     /search/suggest/?q= (forum.views.search.suggest), after a 200 ms pause,
     from 2 characters on; a newer request aborts the one in flight.
   - The input is an ARIA 1.2 combobox: aria-expanded, aria-controls the
     listbox, aria-activedescendant for the active option. Arrow keys move,
     Enter opens the active option (or submits the search), Escape closes the
     panel and then leaves the field. The last option, "Search for “…”",
     runs the full search.
   - "/" anywhere outside a text field focuses the box (unless keyboard
     shortcuts are turned off: <html data-shortcuts="off">).
   - The clear button empties the field.

   Server data is only ever put in the page with textContent (and <mark>
   elements around the typed words), never as HTML.
*/
(function () {
    'use strict';

    var DELAY = 200;
    var MIN_LENGTH = 2;
    var GROUPS = [['questions', 'Questions'], ['tags', 'Tags'], ['users', 'People']];
    var SVG = 'http://www.w3.org/2000/svg';
    var ICONS = {
        questions: 'M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z',
        all: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20.5 20.5l-4.2-4.2'
    };

    function init(form) {
        var input = form.querySelector('.searchbox-input');
        var clear = form.querySelector('.searchbox-clear');
        var panel = form.querySelector('.searchbox-panel');
        var listbox = form.querySelector('[role="listbox"]');
        var status = form.querySelector('[role="status"]');
        if (!input || !panel || !listbox) return;
        var data = form.dataset;
        var texts = {questions: data.textQuestions, tags: data.textTags, users: data.textPeople};

        var timer = null, controller = null, results = {}, options = [], active = -1, shown = '';

        function icon(path, size) {
            var svg = document.createElementNS(SVG, 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('width', size || 16);
            svg.setAttribute('height', size || 16);
            svg.setAttribute('aria-hidden', 'true');
            svg.setAttribute('focusable', 'false');
            svg.setAttribute('fill', 'none');
            svg.setAttribute('stroke', 'currentColor');
            svg.setAttribute('stroke-width', '2');
            svg.setAttribute('stroke-linecap', 'round');
            svg.setAttribute('stroke-linejoin', 'round');
            var p = document.createElementNS(SVG, 'path');
            p.setAttribute('d', path);
            svg.appendChild(p);
            return svg;
        }

        /* As the server sees it: spaces collapsed, none in front, 100 characters at most. */
        function normalized(value) {
            return value.replace(/\s+/g, ' ').replace(/^ /, '').slice(0, 100);
        }

        function escapeRegExp(text) {
            return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function highlighter(words) {
            words = (words || []).filter(function (w) { return w; }).map(escapeRegExp);
            if (!words.length) return null;
            words.sort(function (a, b) { return b.length - a.length; });
            try {
                // At a word start (the start, or after a non-word character): the typed
                // part only, so "rast" shows as <mark>rast</mark>er.
                return new RegExp('(^|[^\\p{L}\\p{N}_])(' + words.join('|') + ')', 'giu');
            } catch (e) {
                return null;
            }
        }

        /* `text` as text nodes, with the matches of `regex` in <mark>. */
        function marked(text, regex) {
            var fragment = document.createDocumentFragment();
            var last = 0, match;
            if (regex) {
                regex.lastIndex = 0;
                while ((match = regex.exec(text)) !== null) {
                    var start = match.index + match[1].length;
                    if (start > last) fragment.appendChild(document.createTextNode(text.slice(last, start)));
                    var mark = document.createElement('mark');
                    mark.textContent = match[2];
                    fragment.appendChild(mark);
                    last = start + match[2].length;
                    if (match[0].length === 0) regex.lastIndex++;
                }
            }
            if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
            return fragment;
        }

        function span(className, content) {
            var el = document.createElement('span');
            el.className = className;
            if (typeof content === 'string') el.textContent = content;
            else if (content) el.appendChild(content);
            return el;
        }

        function addOption(parent, item) {
            var option = document.createElement('div');
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false');
            option.id = 'searchbox-option-' + options.length;
            option.className = 'searchbox-option' + (item.className ? ' ' + item.className : '');
            item.build(option);
            option.addEventListener('mousedown', function (event) { event.preventDefault(); });
            option.addEventListener('click', function () { choose(item); });
            parent.appendChild(option);
            options.push({element: option, item: item});
        }

        function render(result) {
            var regex = highlighter(result.highlight);
            listbox.textContent = '';
            options = [];
            active = -1;
            input.removeAttribute('aria-activedescendant');
            GROUPS.forEach(function (group) {
                var key = group[0], items = result[key] || [];
                if (!items.length) return;
                var box = document.createElement('div');
                box.setAttribute('role', 'group');
                box.className = 'searchbox-group';
                box.setAttribute('aria-labelledby', 'searchbox-group-' + key);
                var label = span('searchbox-group-label', texts[key] || group[1]);
                label.id = 'searchbox-group-' + key;
                label.setAttribute('role', 'presentation');
                box.appendChild(label);
                items.forEach(function (row) {
                    addOption(box, {url: row.url, className: 'searchbox-' + key, build: function (option) {
                        if (key === 'questions') {
                            option.appendChild(span('searchbox-icon', icon(ICONS.questions)));
                            option.appendChild(span('searchbox-label', marked(row.title, regex)));
                            var meta = span('searchbox-meta' + (row.accepted ? ' is-accepted' : ''), row.meta);
                            option.appendChild(meta);
                        } else if (key === 'tags') {
                            var tag = span('searchbox-label');
                            tag.appendChild(span('searchbox-tag', marked(row.name, regex)));
                            option.appendChild(tag);
                            option.appendChild(span('searchbox-meta', row.meta));
                        } else {
                            // The first letter of the name, covered by the picture once it loads.
                            var avatar = span('searchbox-icon searchbox-initial', (row.name || '?').charAt(0).toUpperCase());
                            avatar.setAttribute('aria-hidden', 'true');
                            var img = document.createElement('img');
                            img.className = 'searchbox-avatar';
                            img.alt = '';
                            img.width = 28;
                            img.height = 28;
                            img.decoding = 'async';
                            img.referrerPolicy = 'no-referrer';
                            img.addEventListener('error', function () { img.remove(); });
                            img.src = row.avatar;
                            avatar.appendChild(img);
                            option.appendChild(avatar);
                            option.appendChild(span('searchbox-label', marked(row.name, regex)));
                            option.appendChild(span('searchbox-meta', row.meta));
                        }
                    }});
                });
                listbox.appendChild(box);
            });
            var query = result.q.trim();
            addOption(listbox, {submit: true, className: 'searchbox-all', build: function (option) {
                option.appendChild(span('searchbox-icon', icon(ICONS.all)));
                var label = (data.textSearchFor || 'Search for “{query}”').split('{query}');
                option.appendChild(span('searchbox-label', label[0] + query + (label[1] || '')));
            }});
            shown = result.q;
            open();
            var count = options.length - 1;
            if (status) {
                status.textContent = count === 1 ? (data.textOne || '1 suggestion') :
                    (data.textMany || '{count} suggestions').replace('{count}', count);
            }
        }

        function open() {
            if (!options.length) return;
            panel.hidden = false;
            input.setAttribute('aria-expanded', 'true');
        }

        function close() {
            panel.hidden = true;
            input.setAttribute('aria-expanded', 'false');
            setActive(-1);
        }

        function isOpen() {
            return !panel.hidden;
        }

        function setActive(index) {
            if (active >= 0 && options[active]) options[active].element.setAttribute('aria-selected', 'false');
            active = index;
            if (index >= 0 && options[index]) {
                var element = options[index].element;
                element.setAttribute('aria-selected', 'true');
                input.setAttribute('aria-activedescendant', element.id);
                // Keep it in view inside the scrolling panel.
                var top = element.offsetTop, bottom = top + element.offsetHeight;
                if (top < panel.scrollTop) panel.scrollTop = top - 6;
                else if (bottom > panel.scrollTop + panel.clientHeight) panel.scrollTop = bottom - panel.clientHeight + 6;
            } else {
                input.removeAttribute('aria-activedescendant');
            }
        }

        function choose(item) {
            if (item.submit) {
                close();
                submit();
            } else if (item.url) {
                close();
                window.location.href = item.url;
            }
        }

        function submit() {
            if (typeof form.requestSubmit === 'function') form.requestSubmit();
            else form.submit();
        }

        function fetchSuggestions(text) {
            var key = text.toLowerCase();
            if (results[key]) {
                render(results[key]);
                return;
            }
            if (controller) controller.abort();
            controller = typeof AbortController === 'function' ? new AbortController() : null;
            var url = data.suggestUrl + '?q=' + encodeURIComponent(text);
            fetch(url, {headers: {'Accept': 'application/json'}, credentials: 'same-origin',
                        signal: controller ? controller.signal : undefined})
                .then(function (response) {
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    return response.json();
                })
                .then(function (result) {
                    results[key] = result;
                    // Only if it still matches what is typed.
                    if (normalized(input.value) === result.q &&
                            document.activeElement === input) {
                        render(result);
                    }
                })
                .catch(function () { /* aborted, offline or failed: no suggestions */ });
        }

        function changed() {
            var value = input.value;
            if (clear) clear.hidden = !value;
            setActive(-1);  // Enter now searches for what is typed
            clearTimeout(timer);
            var text = normalized(value);
            if (text.trim().length < MIN_LENGTH) {
                if (controller) controller.abort();
                shown = '';
                close();
                options = [];
                listbox.textContent = '';
                return;
            }
            timer = setTimeout(function () { fetchSuggestions(text); }, DELAY);
        }

        input.addEventListener('input', changed);

        input.addEventListener('keydown', function (event) {
            if (event.isComposing) return;
            // Suggestions for other text than the field's (a request pending) are not reopened.
            var count = shown === normalized(input.value) ? options.length : 0;
            switch (event.key) {
            case 'ArrowDown':
            case 'Down':
                if (!count) return;
                event.preventDefault();
                if (!isOpen()) { open(); setActive(0); return; }
                setActive(active + 1 < count ? active + 1 : 0);
                break;
            case 'ArrowUp':
            case 'Up':
                if (!count) return;
                event.preventDefault();
                if (!isOpen()) { open(); setActive(count - 1); return; }
                setActive(active > 0 ? active - 1 : count - 1);
                break;
            case 'Enter':
                if (isOpen() && active >= 0 && options[active]) {
                    event.preventDefault();
                    choose(options[active].item);
                }
                break;
            case 'Escape':
            case 'Esc':
                if (isOpen()) {
                    event.preventDefault();
                    close();
                } else if (!form.closest('dialog[open]')) {
                    // In the phone's search sheet Escape closes the sheet instead.
                    event.preventDefault();
                    input.blur();
                }
                break;
            case 'Tab':
                close();
                break;
            }
        });

        input.addEventListener('focus', function () {
            if (shown && shown === normalized(input.value)) open();
        });

        form.addEventListener('focusout', function (event) {
            if (!event.relatedTarget || !form.contains(event.relatedTarget)) close();
        });

        document.addEventListener('mousedown', function (event) {
            if (isOpen() && !form.contains(event.target)) close();
        });

        if (clear) {
            clear.hidden = !input.value;
            clear.addEventListener('click', function () {
                input.value = '';
                clear.hidden = true;
                shown = '';
                if (controller) controller.abort();
                close();
                input.focus();
            });
        }

        // "/" focuses the box, unless typing somewhere else.
        document.addEventListener('keydown', function (event) {
            if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
            // A member who turned keyboard shortcuts off (osqa.shortcuts.js).
            if (document.documentElement.getAttribute('data-shortcuts') === 'off') return;
            var target = event.target;
            if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
            event.preventDefault();
            if (!input.getClientRects().length && window.osqaOpenSearch) {
                window.osqaOpenSearch();  // a phone: the box is in the Search sheet
                return;
            }
            input.focus();
            input.select();
        });
    }

    function start() {
        var form = document.getElementById('searchbox');
        if (form) init(form);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
