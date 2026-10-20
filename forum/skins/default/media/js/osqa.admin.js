/* The admin menu is a <details> disclosure: open on wide screens, folded on
   phones (called right after the element, so it never flashes open). */
function osqaAdminMenu(details) {
    if (!details || !window.matchMedia) {
        return;
    }
    var wide = window.matchMedia('(min-width: 768px)');
    function update() {
        details.open = wide.matches;
    }
    update();
    if (wide.addEventListener) {
        wide.addEventListener('change', update);
    }
}

$(function() {
    $(document).on('click', '.string_list_widget_button', function() {
        var $but = $(this);

        if ($but.is('.add')) {
            var $remove = $('<button type="button" class="string_list_widget_button remove">\u2212</button>')
                .attr('aria-label', $but.attr('data-remove-label') || 'Remove')
                .attr('title', $but.attr('data-remove-label') || 'Remove');
            var $new = $('<div class="string-list-input" style="display: none;"></div>')
                .append($('<input type="text" value="" />').attr('name', $but.attr('name'))
                    .attr('aria-label', $but.attr('data-item-label') || ''))
                .append($remove);

            $but.parent().before($new);
            $new.slideDown('fast', function() {
                $new.css('display', '');
                $new.find('input').trigger('focus');
            });
        } else {
            $but.parent().slideUp('fast', function() {
                $but.parent().remove();
            });
        }

        return false;
    })

    $('.fieldtool').each(function() {
        var $link = $(this);
        var $input = $link.parent().parent().find('input, textarea');
        var name = $input.attr('name')

        if ($link.is('.context')) {
            $link.click(function() {
                var $contextbox = $('<input type="text" value="' + name + '" />');
                $link.replaceWith($contextbox);
            });
        } else if ($link.is('.default')) {
            if ($input.length == 1 && ($input.is('[type=text]') || $input.is('textarea'))) {
                $link.click(function() {
                    $.post(name + '/', function(data) {
                        $input.val(data);
                    });
                });
            } else {
                $link.attr('href', name + '/');
            }
        }
    });

    $('.url_field').each(function() {
        var $input = $(this);
        var $anchor = $input.parent().find('.url_field_anchor');
        var app_url = $anchor.attr('href');

        function rewrite_anchor() {
            var val = app_url + '/' +  $input.val();

            $anchor.attr('href', val);
            $anchor.html(val);

        }

        $input.keyup(rewrite_anchor);
        rewrite_anchor();        
    });

    // Keys and passwords (SecretInput): dots, with a button that shows them.
    $('input.secret-input').each(function() {
        var $input = $(this);
        var $button = $('<button type="button" class="secret-toggle" aria-pressed="false"></button>')
            .text($input.closest('form').attr('data-show-text') || 'Show')
            .attr('aria-controls', this.id);
        $input.wrap('<span class="secret-field"></span>').after($button);
        $button.on('click', function() {
            var shown = $input.attr('type') === 'text';
            var $form = $input.closest('form');
            $input.attr('type', shown ? 'password' : 'text');
            $button.attr('aria-pressed', shown ? 'false' : 'true')
                .text(shown ? ($form.attr('data-show-text') || 'Show') : ($form.attr('data-hide-text') || 'Hide'));
        });
    });

    // Links to other sites in the setup guides open in a new tab, so the
    // settings typed so far stay in this one.
    $('.admin-guide a[href^="http"]').each(function() {
        var $link = $(this);
        $link.attr({target: '_blank', rel: 'noopener noreferrer'});
        var hint = $('.admin-settings-form').attr('data-new-tab-text');
        if (hint) {
            $link.append($('<span class="admin-visually-hidden"></span>').text(' (' + hint + ')'));
        }
    });

    // "Find a setting on this page": hides the rows (and sections) that don't
    // match every word typed.
    var $filter = $('#settings-filter');
    if ($filter.length) {
        var normalize = function(text) {
            text = String(text || '').toLowerCase();
            return text.normalize ? text.normalize('NFD').replace(/[\u0300-\u036f]/g, '') : text;
        };
        var $status = $('.admin-filter-status');
        var timer = null;
        var apply = function() {
            var words = normalize($filter.val()).split(/\s+/).filter(Boolean);
            var shown = 0;
            var matches = function(text) {
                return words.every(function(word) { return text.indexOf(word) !== -1; });
            };
            $('.admin-settings-form .setting-row').each(function() {
                var text = normalize(this.textContent + ' ' + this.id.replace(/^setting-/, '').replace(/_/g, ' '));
                var $section = $(this).closest('.admin-guide');
                var heading = $section.length ? normalize($section.find('h2').first().text()) : '';
                var visible = !words.length || matches(text) || (heading && matches(heading));
                this.hidden = !visible;
                if (visible) shown++;
            });
            $('.admin-settings-form .admin-guide').each(function() {
                this.hidden = $(this).find('.setting-row').length > 0 && !$(this).find('.setting-row:not([hidden])').length;
            });
            if (!words.length) {
                $status.text('');
            } else if (shown) {
                $status.text(($filter.attr('data-count-text') || '%(count)s').replace('%(count)s', shown));
            } else {
                $status.text($filter.attr('data-none-text') || '');
            }
        };
        $filter.on('input', function() {
            window.clearTimeout(timer);
            timer = window.setTimeout(apply, 120);
        });
        $filter.on('keydown', function(evt) {
            // Enter goes to the first setting shown instead of submitting anything.
            if (evt.key === 'Enter') {
                evt.preventDefault();
                apply();
                var $first = $('.admin-settings-form .setting-row:not([hidden])').first();
                $first.find('input:not([type=hidden]), select, textarea').first().trigger('focus');
            }
        });
    }

    $('#test_email_settings a.test_button').on('click', function(evt) {
        evt.preventDefault();
        $('div.test_status').hide('slow')
        $('div.ajax_indicator').show('fast')
        $.post($(this).attr('href'), function(data) {
            $('div.test_status').html(data)
        }).fail(function(xhr) {
            $('div.test_status').text('HTTP ' + xhr.status + ' ' + (xhr.statusText || ''))
        }).always(function() {
            $('div.ajax_indicator').hide('fast')
            $('div.test_status').show('slow')
        })
    })

    // Admin > AI assistance > "Test connection" (forum_modules/ai): posts the
    // form as it is now, unsaved, and shows the explained result.
    $(document).on('click', '[data-ai-test]', function() {
        var button = this, form = button.form, result = document.getElementById('ai-test-result');
        if (!form || !result || button.disabled) {
            return;
        }
        var label = button.textContent;
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = button.getAttribute('data-busy-label') || label;
        result.innerHTML = '';
        fetch(button.getAttribute('data-ai-test'), {
            method: 'POST', body: new FormData(form), credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': $('meta[name="csrf-token"]').attr('content')}
        }).then(function(response) {
            return response.text().then(function(text) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                result.innerHTML = text;
            });
        }).catch(function(error) {
            result.textContent = (button.getAttribute('data-error-label') || '') + ' ' + error.message;
        }).then(function() {
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.textContent = label;
            result.scrollIntoView({block: 'nearest'});
        });
    });
});
