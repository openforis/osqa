/*
 * Pasting and dropping into the post editor (textarea#editor, osqa.editor.js):
 *
 * - images (one or several, pasted or dropped) are uploaded with the editor's
 *   upload endpoint (messages.upload_url, JSON reply); each gets a placeholder
 *   "![Uploading name.png…]()" that becomes ![name](/upfiles/...) when done, or
 *   is removed with the error shown under the text box;
 * - rich HTML (web pages, Word, Google Docs) is converted to Markdown by
 *   osqaHtmlToMarkdown (osqa.htmltomd.js); HTML is never inserted as such;
 * - Ctrl+Shift+V (Cmd+Shift+V) pastes the plain text, as does any paste
 *   inside a code block;
 * - on the ask page, what another app shared with the installed app (images,
 *   title, text, link; ?shared=1, see takeShared) is added the same way.
 */
(function () {
    var plainUntil = 0;

    function text(key, fallback) {
        return (window.messages && messages[key]) || fallback;
    }

    function editorOf(textarea) {
        return textarea.osqaEditor || null;
    }

    function refresh(textarea) {
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
    }

    function insertBlock(textarea, snippet) {
        var editor = editorOf(textarea);
        if (editor) {
            editor.insertBlock(snippet);
            return;
        }
        var start = textarea.selectionStart, end = textarea.selectionEnd;
        var before = textarea.value.slice(0, start), after = textarea.value.slice(end);
        var pre = before && !/\n\n$/.test(before) ? (before.slice(-1) === '\n' ? '\n' : '\n\n') : '';
        var post = after && !/^\n/.test(after) ? '\n\n' : '\n';
        textarea.value = before + pre + snippet + post + after;
        var caret = (before + pre + snippet + post).length;
        textarea.setSelectionRange(caret, caret);
        refresh(textarea);
    }

    function replaceText(textarea, placeholder, replacement) {
        var value = textarea.value, pos = value.indexOf(placeholder);
        if (pos < 0) return;
        var end = pos + placeholder.length;
        if (!replacement) {
            // Removing a placeholder also removes the blank lines it was given.
            var before = value.slice(0, pos).match(/\n*$/)[0].length, after = value.slice(end).match(/^\n*/)[0].length;
            var keep = end + after === value.length ? Math.min(before + after, 1) :
                       pos === before ? 0 : Math.min(before + after, 2);
            pos -= before;
            end += after;
            replacement = new Array(keep + 1).join('\n');
        }
        var newValue = value.slice(0, pos) + replacement + value.slice(end);
        // Keep the caret where the writer is typing.
        var shift = newValue.length - value.length;
        var keep = function (p) { return p >= end ? p + shift : p > pos ? pos + replacement.length : p; };
        var start = keep(textarea.selectionStart), stop = keep(textarea.selectionEnd);
        var editor = editorOf(textarea);
        if (editor) {
            editor.apply(newValue, start, stop);
        } else {
            textarea.value = newValue;
            textarea.setSelectionRange(start, stop);
            refresh(textarea);
        }
    }

    function errorBox(textarea) {
        var holder = textarea.parentNode;
        var box = holder.querySelector('.upload-errors');
        if (!box) {
            box = document.createElement('div');
            box.className = 'upload-errors';
            box.setAttribute('role', 'alert');
            holder.insertBefore(box, textarea.nextSibling);
        }
        return box;
    }

    function showError(textarea, name, message) {
        var box = errorBox(textarea);
        var line = document.createElement('p');
        line.className = 'upload-error';
        line.textContent = (name ? name + ': ' : '') + message;
        box.appendChild(line);
        setTimeout(function () {
            line.remove();
            if (!box.children.length) box.remove();
        }, 10000);
    }

    function uniquePlaceholder(textarea, name) {
        var base = text('uploading', 'Uploading') + ' ' + name, label = base + '…', n = 1;
        while (textarea.value.indexOf('![' + label + ']()') >= 0) {
            label = base + ' (' + (++n) + ')…';
        }
        return '![' + label + ']()';
    }

    function upload(textarea, file) {
        var name = (file.name || 'image.png').replace(/[\[\]()]/g, '');
        var placeholder = uniquePlaceholder(textarea, name);
        insertBlock(textarea, placeholder);
        var send = window.OsqaEditor ? window.OsqaEditor.uploadFile(file) : Promise.resolve({});
        var alt = window.OsqaEditor ? window.OsqaEditor.altFromName(name) : name.replace(/\.[^.]+$/, '');
        return send.then(function (reply) {
            if (reply.url && !reply.error) {
                replaceText(textarea, placeholder, '![' + (alt || 'image') + '](' + reply.url + ')');
            } else {
                replaceText(textarea, placeholder, '');
                showError(textarea, name, reply.error || text('upload_failed', 'The image could not be uploaded.'));
            }
        });
    }

    function images(list) {
        return Array.prototype.filter.call(list || [], function (f) {
            return f && f.type && f.type.indexOf('image/') === 0;
        });
    }

    function inCode(textarea) {
        var v = textarea.value, s = textarea.selectionStart;
        if (window.OsqaEditor && window.OsqaEditor.fenceAt(v, s)) return true;
        // Inside an inline code span on this line.
        var line = v.slice(v.lastIndexOf('\n', s - 1) + 1, s);
        return ((line.match(/`/g) || []).length % 2) === 1;
    }

    function pasteHtml(textarea, html) {
        if (!window.osqaHtmlToMarkdown || !window.osqaHtmlIsRich || !window.osqaHtmlIsRich(html)) return false;
        var markdown = window.osqaHtmlToMarkdown(html);
        if (!markdown) return false;
        var editor = editorOf(textarea);
        if (/\n/.test(markdown) && editor) {
            var v = textarea.value, s = textarea.selectionStart;
            var lineHasText = v.slice(v.lastIndexOf('\n', s - 1) + 1, s).trim();
            if (/^(#|>|```|\||- |\d+\. )/.test(markdown) && lineHasText) {
                editor.insertBlock(markdown);
                return true;
            }
        }
        if (editor) {
            editor.replaceSelection(markdown);
        } else {
            textarea.setRangeText(markdown, textarea.selectionStart, textarea.selectionEnd, 'end');
            refresh(textarea);
        }
        return true;
    }

    function setup(textarea) {
        textarea.addEventListener('keydown', function (evt) {
            var mod = evt.ctrlKey || evt.metaKey;
            if (mod && evt.shiftKey && (evt.key === 'V' || evt.key === 'v')) {
                plainUntil = Date.now() + 1000;
            }
        });

        textarea.addEventListener('paste', function (evt) {
            var data = evt.clipboardData;
            if (!data) return;
            var plain = Date.now() < plainUntil;
            plainUntil = 0;
            var html = data.getData('text/html');
            var plainText = data.getData('text/plain') || '';
            var files = images(data.files);
            // An image on its own (a screenshot, an image copied from a page): upload it.
            if (files.length && !plainText.trim()) {
                evt.preventDefault();
                files.forEach(function (f) { upload(textarea, f); });
                return;
            }
            if (!plain && html && !inCode(textarea) && pasteHtml(textarea, html)) {
                evt.preventDefault();
            }
            // Otherwise the browser pastes the plain text.
        });

        function hasFiles(evt) {
            return evt.dataTransfer && Array.prototype.indexOf.call(evt.dataTransfer.types, 'Files') >= 0;
        }
        textarea.addEventListener('dragover', function (evt) {
            if (hasFiles(evt)) {
                evt.preventDefault();
                evt.dataTransfer.dropEffect = 'copy';
                textarea.classList.add('drop-target');
            }
        });
        textarea.addEventListener('dragleave', function () {
            textarea.classList.remove('drop-target');
        });
        textarea.addEventListener('drop', function (evt) {
            textarea.classList.remove('drop-target');
            var files = images(evt.dataTransfer && evt.dataTransfer.files);
            if (!files.length) {
                if (hasFiles(evt)) {
                    evt.preventDefault();
                    showError(textarea, '', text('upload_not_image', 'Only images can be added to a post.'));
                }
                return;
            }
            evt.preventDefault();
            textarea.focus();
            files.forEach(function (f) { upload(textarea, f); });
        });
    }

    // What another app shared with the installed app (manifest share_target):
    // the service worker kept it in the 'osqa-shared' cache and opened the ask
    // page with ?shared=1 (pwa/sw.js). The title goes in an empty title field,
    // the text and link in the body, and each image is uploaded as if it had
    // been pasted; then the cache is emptied.
    var SHARED = 'osqa-shared';

    function takeShared(textarea) {
        if (!/[?&]shared=1(&|$)/.test(location.search) || !window.caches) return;
        history.replaceState(null, '', location.pathname);
        var prefix = window.scriptUrl ? window.scriptUrl.replace(/\/$/, '') : '';
        caches.open(SHARED).then(function (cache) {
            return cache.match(prefix + '/share-target/shared.json').then(function (response) {
                return response ? response.json() : null;
            }).then(function (shared) {
                if (!shared) return null;
                var title = document.getElementById('id_title');
                var heading = (shared.title || '').trim();
                if (title && heading && !title.value.trim()) {
                    title.value = heading;
                    title.dispatchEvent(new Event('input', {bubbles: true}));
                }
                var body = [shared.text, shared.url].map(function (part) { return (part || '').trim(); })
                    .filter(function (part, i, all) { return part && all.indexOf(part) === i; }).join('\n\n');
                if (body) {
                    insertBlock(textarea, body);
                    refresh(textarea);
                }
                return Promise.all((shared.files || []).map(function (item) {
                    return cache.match(item.key).then(function (response) {
                        return response ? response.blob() : null;
                    }).then(function (blob) {
                        if (blob) return upload(textarea, new File([blob], item.name || 'image', {type: blob.type}));
                    });
                }));
            });
        }).then(function () {
            return caches.delete(SHARED);
        }).catch(function () { /* nothing shared, or no cache storage */ });
    }

    function start() {
        if (!window.messages || !messages.upload_url) return;
        document.querySelectorAll('textarea#editor').forEach(setup);
        var editor = document.querySelector('textarea#editor');
        if (editor && document.getElementById('id_title')) takeShared(editor);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
