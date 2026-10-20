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

    // Settings pages (osqaadmin/set.html): "Use default" fills a field in
    // with its default (saved with the others by Save), rows changed since the
    // page was loaded are marked and counted in the save bar, and leaving the
    // page with unsaved changes asks first.
    var $settingsForm = $('form.admin-settings-form');
    if ($settingsForm.length) {
        var form = $settingsForm[0];
        var submitting = false;

        // The row's value as data-default writes it, or null for fields this
        // can't compare (lists, several check boxes, uploads).
        var fieldValue = function($row) {
            var $image = $row.find('input[type=hidden][name$="_old"]');
            if ($image.length) return $image.val();
            var $fields = $row.find('input[name], select[name], textarea[name]')
                .not('[type=hidden], [type=file], .admin-copy input');
            var names = $fields.map(function() { return this.name; }).get().filter(function(name, i, all) {
                return all.indexOf(name) === i;
            });
            if (names.length !== 1) return null;
            if ($fields.is('[type=radio]')) return $fields.filter(':checked').val() || '';
            if ($fields.length !== 1) return null;
            if ($fields.is('[type=checkbox]')) return $fields.prop('checked') ? 'true' : 'false';
            if ($fields.is('select[multiple]')) return null;
            return $fields.val();
        };
        var setFieldValue = function($row, value) {
            var $image = $row.find('input[type=hidden][name$="_old"]');
            if ($image.length) {
                $image.val(value);
                $row.find('img.setting-image-preview').attr('src', value);
                $row.find('input[type=file]').val('');
                return;
            }
            var $fields = $row.find('input[name], select[name], textarea[name]')
                .not('[type=hidden], [type=file], .admin-copy input');
            if ($fields.is('[type=radio]')) {
                $fields.each(function() { this.checked = this.value === value; });
            } else if ($fields.is('[type=checkbox]')) {
                $fields.prop('checked', value === 'true');
            } else {
                $fields.val(value);
            }
            $fields.first().trigger('change').trigger('focus');
        };
        var snapshot = function($row) {
            return $row.find('input[name], select[name], textarea[name]').not('.admin-copy input').map(function() {
                if (this.type === 'file') return this.files && this.files.length ? 'file:' + this.value : '';
                if (this.type === 'checkbox' || this.type === 'radio') return this.checked ? '1' : '0';
                return this.value;
            }).get().join('\u0001');
        };
        var $rows = $settingsForm.find('.setting-row');
        $rows.each(function() {
            var $row = $(this);
            $row.data('initial', snapshot($row));
            if (fieldValue($row) === null) $row.find('.setting-reset').remove();
        });
        var $unsaved = $settingsForm.find('.admin-unsaved-status');
        var update = function() {
            var dirty = 0;
            $rows.each(function() {
                var $row = $(this);
                var changed = snapshot($row) !== $row.data('initial');
                $row.toggleClass('is-dirty', changed);
                if (changed) dirty++;
                var value = fieldValue($row);
                if (value !== null) {
                    $row.find('.setting-default').prop('hidden', value === String($row.attr('data-default')));
                }
            });
            $settingsForm.toggleClass('has-unsaved', dirty > 0).data('dirty', dirty);
            var text = '';
            if (dirty === 1) text = $settingsForm.attr('data-unsaved-one') || '';
            else if (dirty > 1) text = ($settingsForm.attr('data-unsaved-many') || '').replace('%(count)s', dirty);
            if ($unsaved.text() !== text) $unsaved.text(text);
            $settingsForm.find('.admin-discard').prop('hidden', dirty === 0);
        };
        $settingsForm.on('input change', update);
        $settingsForm.on('click', '.setting-reset', function() {
            var $row = $(this).closest('.setting-row');
            setFieldValue($row, String($row.attr('data-default')));
            update();
        });
        $settingsForm.on('reset', function() {
            window.setTimeout(function() {
                $rows.find('img.setting-image-preview').each(function() {
                    var $old = $(this).closest('.setting-row').find('input[type=hidden][name$="_old"]');
                    $(this).attr('src', $old.val());
                });
                update();
            }, 0);
        });
        // Preview opens the site in another tab: this page stays, unsaved.
        $settingsForm.on('submit', function() { submitting = this.target !== '_blank'; });
        window.addEventListener('beforeunload', function(evt) {
            if (!submitting && $settingsForm.data('dirty')) {
                evt.preventDefault();
                evt.returnValue = '';
            }
        });
        update();
    }

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

    // "/" goes to the admin search, as on the public pages (unless typing,
    // or the member turned keyboard shortcuts off).
    $(document).on('keydown', function(evt) {
        if (evt.key !== '/' || evt.ctrlKey || evt.metaKey || evt.altKey) return;
        if (document.documentElement.getAttribute('data-shortcuts') === 'off') return;
        var target = evt.target;
        if (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName)) return;
        var search = document.getElementById('admin-search-q');
        if (search) {
            evt.preventDefault();
            search.focus();
            search.select();
        }
    });

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
});
