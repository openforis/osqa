// Ask and edit question pages (templates/ask.html, question_edit.html).

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function(c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
}

// Writing tips (question_edit_tips.html): the tip for the field being filled in opens.
$(function () {
    var tips = {'id_title': '#title_side_bar', 'editor': '#editor_side_bar_tip', 'id_tags': '#tags_side_bar'};
    $.each(tips, function (field, tip) {
        $('#' + field).on('focus', function () {
            var details = $(tip)[0];
            if (details && !details.open) details.open = true;
        });
    });
});

// The title's length under the field, and whether it reaches the minimum (compose/title_length.html).
$(function () {
    var title = document.getElementById('id_title'), count = document.getElementById('title-metrics');
    if (!title || !count) return;
    var hint = document.getElementById('title-min-hint');
    var min = hint ? parseInt(hint.getAttribute('data-min-length'), 10) || 0 : 0;
    var messages = window.messages || {};
    if (hint) {
        var described = (title.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        if (described.indexOf(hint.id) < 0) title.setAttribute('aria-describedby', described.concat(hint.id).join(' '));
    }
    function update() {
        var length = title.value.length;
        count.textContent = length + ' ' + (length === 1 ? messages.character || 'character' : messages.characters || 'characters');
        if (hint) {
            hint.classList.toggle('is-met', length >= min);
            hint.classList.toggle('is-short', length > 0 && length < min);
        }
    }
    title.addEventListener('input', update);
    update();
});

// "Similar questions" while the title is typed (the related_questions view):
// a disclosure listing the matches, each marked accepted, answered or unanswered.
$(function () {
    var $title = $('#id_title');
    var $box = $('#ask-related-questions');
    var url = window.related_questions_url;
    if (!url || !$title.length || !$box.length) return;

    var cache = {}, timer = null, last = null, open = true;
    var text = function (name) { return $box.attr('data-' + name) || ''; };

    function status(q) {
        if (q.accepted) {
            return '<span class="similar-status is-accepted">' + escapeHtml(text('accepted')) + '</span>';
        }
        if (q.answers) {
            var label = q.answers == 1 ? text('answer') : text('answers').replace('%s', q.answers);
            return '<span class="similar-status is-answered">' + escapeHtml(label) + '</span>';
        }
        return '<span class="similar-status is-unanswered">' + escapeHtml(text('unanswered')) + '</span>';
    }

    function render(questions) {
        if (!questions || !questions.length) {
            $box.prop('hidden', true).empty();
            return;
        }
        var html = '<details class="similar-details"' + (open ? ' open' : '') + '><summary>' +
            '<span class="similar-title">' + escapeHtml(text('title')) + '</span>' +
            '<span class="similar-count">' + questions.length + '</span></summary>' +
            '<p class="similar-hint">' + escapeHtml(text('hint')) + '</p><ul class="similar-list">';
        $.each(questions, function (i, q) {
            // Titles and summaries are user text: escaped.
            html += '<li class="similar-item"><a class="similar-link" href="' + escapeHtml(q.url) +
                '" target="_blank" rel="noopener"' + (q.summary ? ' title="' + escapeHtml(q.summary) + '"' : '') + '>' +
                escapeHtml(q.title) + '</a>' + (q.answers === undefined ? '' : status(q)) + '</li>';
        });
        $box.html(html + '</ul></details>').prop('hidden', false);
    }

    // "toggle" doesn't bubble: listen in the capture phase.
    $box[0].addEventListener('toggle', function (e) {
        if (e.target.tagName === 'DETAILS') open = e.target.open;
    }, true);

    function reload() {
        var q = $title.val().trim();
        if (q === last) return;
        last = q;
        if (q.length < 3) {
            render([]);
            return;
        }
        if (cache[q]) {
            render(cache[q]);
            return;
        }
        $.post(url, {title: q}, null, 'json').done(function (data) {
            cache[q] = data || [];
            if ($title.val().trim() === q) render(cache[q]);
        });
    }

    $title.on('input keyup focus', function () {
        clearTimeout(timer);
        timer = setTimeout(reload, 300);
    });
});

// AI duplicate detection (forum_modules/ai): after a pause in typing the title,
// ask the server which existing questions ask the same thing.
$(function() {
    var url = window.ai_duplicates_url;
    var $title = $('#id_title'), $box = $('#ask-duplicates');
    if (!url || !$title.length || !$box.length) return;

    var timer = null, last = '', request = 0, dismissed = {};

    function render(title, duplicates) {
        if (!duplicates.length || dismissed[title]) {
            $box.prop('hidden', true).empty();
            return;
        }
        var html = '<div class="ask-duplicates-head"><strong>' + escapeHtml(messages.ai_duplicates_title) +
                   '</strong><button type="button" class="ask-duplicates-dismiss plain-button">' +
                   escapeHtml(messages.ai_duplicates_dismiss) + '</button></div><ul>';
        $.each(duplicates, function(i, d) {
            var status = d.accepted ? messages.ai_duplicates_accepted :
                         (d.answers == 1 ? messages.ai_duplicates_answer : messages.ai_duplicates_answers.replace('%s', d.answers));
            html += '<li><a href="' + escapeHtml(d.url) + '" target="_blank" rel="noopener">' + escapeHtml(d.title) + '</a>' +
                    ' <span class="ask-duplicates-status' + (d.accepted ? ' accepted' : '') + '">' + escapeHtml(status) + '</span>' +
                    '<div class="ask-duplicates-reason">' + escapeHtml(d.reason) + '</div></li>';
        });
        $box.html(html + '</ul><p class="ask-duplicates-note">' + escapeHtml(messages.ai_duplicates_note) + '</p>')
            .prop('hidden', false);
    }

    function check() {
        var title = $title.val().trim();
        if (title === last) return;
        last = title;
        var id = ++request;
        if (title.length < 15 || title.split(/\s+/).length < 3) {
            render(title, []);
            return;
        }
        $.post(url, {title: title, text: $('#editor').val() || ''}).done(function(data) {
            if (id === request) render(title, data.duplicates || []);
        });
    }

    $title.on('input', function() {
        clearTimeout(timer);
        timer = setTimeout(check, 1200);
    }).on('blur', check);

    $box.on('click', '.ask-duplicates-dismiss', function() {
        dismissed[last] = true;
        $box.prop('hidden', true).empty();
    });
});

// AI assistant (forum_modules/ai): an answer from the forum and the
// documentation before the question is posted.
$(function() {
    var url = window.ai_assistant_url;
    var $button = $('#ask-assistant-button'), $out = $('#ask-assistant-answer');
    if (!url || !$button.length) return;

    function show(html) {
        $out.html(html).prop('hidden', false);
    }

    $button.on('click', function() {
        var title = $('#id_title').val().trim();
        if (title.length < 15) {
            show('<p class="ask-assistant-status">' + escapeHtml(messages.ai_assistant_title) + '</p>');
            $('#id_title').focus();
            return;
        }
        $button.prop('disabled', true);
        show('<p class="ask-assistant-status">' + escapeHtml(messages.ai_assistant_working) + '</p>');
        $.post(url, {title: title, text: $('#editor').val() || ''}).done(function(data) {
            if (data.insufficient) {
                // Nothing in the forum or the documentation covers it: no answer is shown.
                var reason = data.html ? '<div class="ask-assistant-body">' + data.html + '</div>' : '';
                show('<p class="ask-assistant-status">' + escapeHtml(messages.ai_assistant_insufficient) + '</p>' + reason);
                return;
            }
            // data.html was rendered and sanitized by the server.
            var html = '<div class="ask-assistant-body">' + data.html + '</div>';
            if (data.sources && data.sources.length) {
                html += '<div class="ai-suggestion-sources"><strong>' + escapeHtml(messages.ai_assistant_sources) + '</strong><ol>';
                $.each(data.sources, function(i, s) {
                    html += '<li><a href="' + escapeHtml(s.url) + '" target="_blank" rel="nofollow noopener">' +
                            escapeHtml(s.title) + '</a> <span class="ai-source-kind">' + escapeHtml(s.kind) + '</span></li>';
                });
                html += '</ol></div>';
            }
            show(html + '<p class="ai-suggestion-note">' + escapeHtml(messages.ai_assistant_note) + '</p>');
        }).fail(function(xhr) {
            show('<p class="ask-assistant-status">' + escapeHtml(xhr.status == 429 ? messages.ai_assistant_limit : messages.ai_assistant_failed) + '</p>');
        }).always(function() {
            $button.prop('disabled', false);
        });
    });
});
