var response_commands = {
    refresh_page: function() {
        window.location.reload(true)
    },
    
    update_post_score: function(id, inc) {
        var $score_board = $('#post-' + id + '-score');
        var current = parseInt($score_board.html())
        if (isNaN(current)){
            current = 0;
        }
        $score_board.html(current + inc)
    },

    update_user_post_vote: function(id, vote_type) {
        var $upvote_button = $('#post-' + id + '-upvote');
        var $downvote_button = $('#post-' + id + '-downvote');

        $upvote_button.removeClass('on').attr('aria-pressed', 'false');
        $downvote_button.removeClass('on').attr('aria-pressed', 'false');

        if (vote_type == 'up') {
            $upvote_button.addClass('on').attr('aria-pressed', 'true');
        } else if (vote_type == 'down') {
            $downvote_button.addClass('on').attr('aria-pressed', 'true');
        }
    },

    update_favorite_count: function(inc) {
        var $favorite_count = $('#favorite-count');
        var count = parseInt($favorite_count.html());

        if (isNaN(count))
            count = 0;

        count += inc;

        if (count == 0)
            count = '';

        $favorite_count.html(count);
    },

    update_favorite_mark: function(type) {
        if (type == 'on') {
            $('#favorite-mark').addClass('on').attr('aria-pressed', 'true');
        } else {
            $('#favorite-mark').removeClass('on').attr('aria-pressed', 'false');
        }
    },

    mark_accepted: function(id) {        
        var $answer = $('#answer-container-' + id);
        $answer.addClass('accepted-answer');
        $answer.find('.accept-answer').addClass('on');
        $answer.find('a.accept-answer').attr('aria-pressed', 'true');
        $answer.find('.accept-answer').attr('title', $answer.find('.accept-answer').attr('bn:on'));
        $('#accept-hint').remove();
    },

    unmark_accepted: function(id) {
        var $answer = $('#answer-container-' + id);
        $answer.removeClass('accepted-answer');
        $answer.find('.accept-answer').removeClass('on');
        $answer.find('a.accept-answer').attr('aria-pressed', 'false');
        $answer.find('.accept-answer').attr('title', $answer.find('.accept-answer').attr('bn:off'));
    },

    remove_comment: function(id) {
        var $comment = $('#comment-' + id);
        $comment.css('background', 'red')
        $comment.fadeOut('slow', function() {
            $comment.remove();    
        });
    },

    award_points: function(id) {
        alert('ok');
    },

    insert_comment: function(post_id, comment_id, comment, username, profile_url, delete_url, edit_url, convert_url, can_convert, show_latest_comments_first) {
        var $container = $('#comments-container-' + post_id);
        var skeleton = $('#new-comment-skeleton-' + post_id).html().toString();

        // Replaced with functions: "$'" or "$`" in a comment are text, not
        // replacement patterns that would copy parts of the skeleton.
        var fill = {'%ID%': comment_id, '%COMMENT%': comment, '%USERNAME%': username, '%PROFILE_URL%': profile_url,
                    '%DELETE_URL%': delete_url, '%EDIT_URL%': edit_url, '%CONVERT_URL%': convert_url};
        skeleton = skeleton.replace(/%(ID|COMMENT|USERNAME|PROFILE_URL|DELETE_URL|EDIT_URL|CONVERT_URL)%/g,
                                    function (placeholder) { return String(fill[placeholder]); });
        if (show_latest_comments_first) {
            $container.prepend(skeleton);
        } else {
            $container.append(skeleton);
        }

        // Show the convert comment to answer tool only if the current comment can be converted
        if (can_convert == true) {
            $('#comment-' + comment_id + '-convert').show();
        }

        $('#comment-' + comment_id).slideDown('slow');
    },

    update_comment: function(comment_id, comment_text) {
        var $comment = $('#comment-' + comment_id);
        $comment.find('.comment-text').html(comment_text);

        $comment.slideDown('slow');
    },

    mark_deleted: function(post_type, post_id) {
        if (post_type == 'question') {
            var $container = $('#question-table');
            $container.addClass('deleted');
        } else {
            var $el = $('#' + post_type + '-container-' + post_id);
            $el.addClass('deleted');
        }
    },

    unmark_deleted: function(post_type, post_id) {
        if (post_type == 'answer') {
            var $answer = $('#answer-container-' + post_id);
            $answer.removeClass('deleted');
        } else {
            var $container = $('#question-table');
            $container.removeClass('deleted');
        }
    },

    set_subscription_button: function(text) {
        $('.subscription_switch').html(text);
    },

    set_subscription_status: function(text) {
        $('.subscription-status').html(text);
    },

    copy_url: function(url) {
    }
}

function show_dialog (extern) {
    var default_close_function = function($diag) {
        $diag.fadeOut('fast', function() {
            $diag.remove();
        });
    };

    var options = {
        extra_class: '',
        pos: {
            x: ($(window).width() / 2) + $(window).scrollLeft(),
            y: ($(window).height() / 2) + $(window).scrollTop()
        },
        dim: false, 
        yes_text: messages.ok,
        yes_callback: default_close_function,
        no_text: messages.cancel,
        show_no: false,
        close_on_clickoutside: false,
        copy: false
    }

    $.extend(options, extern);

    var copy_id = '';
    if (options.copy) {
        copy_id = ' id="copy_clip_button"'
    }

    if (options.event != undefined && options.event.pageX != undefined && options.event.pageY != undefined) {
        options.pos = {x: options.event.pageX, y: options.event.pageY};
    } else if (options.event && options.event.currentTarget != undefined) {
        var el = jQuery("#" + options.event.currentTarget.id);
        var position = el.offset();
        options.pos = {
            x: position.left,
            y: position.top
        }
    }

    // Keyboard users come back to what opened the dialog when it closes.
    var trigger = options.event && options.event.currentTarget && options.event.currentTarget.nodeType === 1
        ? options.event.currentTarget : document.activeElement;

    var html = '<div class="dialog ' + options.extra_class + '" role="dialog" aria-modal="true" tabindex="-1"'
             + ' style="display: none; z-index: 999;">'
             + '<div class="dialog-content">' + options.html + '</div><div class="dialog-buttons">';

    if (options.show_no) {
        html += '<button class="dialog-no">' + options.no_text + '</button>';
    }

    html += '<button class="dialog-yes"' + copy_id + '>' + options.yes_text + '</button>' + '</div></div>';

    var $dialog = $(html);

    $('body').append($dialog);
    // Content loaded from the server brings no scripts (the CSP would block
    // them): widgets in it are set up here, before the dialog is measured.
    init_prompt_widgets($dialog);
    var message = $dialog.find('.dialog-content')[0];
    message.style.visibility = "hidden";

    if (options.dim === false) {
        $dialog.css({
            visibility: 'hidden',
            display: 'block'
        });

        options.dim = {w: $dialog.width(), h: $dialog.height()};

        $dialog.css({
            width: 1,
            height: 1,
            visibility: 'visible'
        });
    }

    $dialog.css({
        top: options.pos.y,
        left: options.pos.x
    });
    
    top_position_change = (options.dim.h / 2)
    left_position_change = (options.dim.w / 2)
    
    new_top_position = options.pos.y - top_position_change
    new_left_position = options.pos.x - left_position_change
    
    if (new_left_position < 0) {
        left_position_change = 0
    }
    if (($(window).scrollTop() - new_top_position) > 0) {
        top_position_change = 0
    }
    if ((options.event.pageY + options.dim.h) > ($(window).height() + $(window).scrollTop())) {
        top_position_change = options.dim.h
    }
    if ((options.event.pageX + options.dim.w) > ($(window).width() + $(window).scrollLeft())) {
        left_position_change = options.dim.w
    }
    
    $dialog.animate({
        top: "-=" + top_position_change,
        left: "-=" + left_position_change,
        width: options.dim.w,
        height: options.dim.h
    }, 200, function() {
        message.style.visibility = "visible";
        dialog_focus_first($dialog);
    });

    dialog_keep_focus($dialog, trigger);

    $dialog.find('.dialog-yes').click(function() {
        options.yes_callback($dialog);
    });

    if (options.hasOwnProperty("no_callback")) {
        $dialog.find('.dialog-no:first-child').click(function() {
            options.no_callback($dialog);
        });
    } else {
        $dialog.find('.dialog-no:first-child').click(function() {
            default_close_function($dialog);
        });
    }

    if (options.close_on_clickoutside) {
        $dialog.one('clickoutside', function() {
            default_close_function($dialog);
        });
    }

    return $dialog;
}

var DIALOG_FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled):not([type=hidden]), ' +
                       'select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

// Focus goes to the dialog's first field, or else its first button.
function dialog_focus_first($dialog) {
    if (!$dialog[0].isConnected || $dialog[0].contains(document.activeElement)) return;
    var $field = $dialog.find('.dialog-content').find('input, select, textarea').filter(':visible').not(':disabled');
    var $target = $field.length ? $field.first() : $dialog.find('.dialog-buttons button').first();
    ($target.length ? $target : $dialog)[0].focus();  // native: jQuery's trigger skips it inside a click handler
}

// While a dialog is open, Tab and Shift+Tab stay inside it and Escape closes
// it (as its No/Cancel button would, or OK when that is the only button).
// When it is removed, focus returns to the element that opened it (or, if
// that was in a post menu that has closed since, to the menu's button).
function dialog_keep_focus($dialog, trigger) {
    $dialog.on('keydown', function(evt) {
        if (evt.key === 'Escape') {
            evt.preventDefault();
            evt.stopPropagation();
            var $no = $dialog.find('.dialog-no');
            ($no.length ? $no : $dialog.find('.dialog-yes')).first().trigger('click');
        } else if (evt.key === 'Tab') {
            var $items = $dialog.find(DIALOG_FOCUSABLE).filter(':visible');
            if (!$items.length) { evt.preventDefault(); return; }
            var first = $items[0], last = $items[$items.length - 1];
            if (evt.shiftKey && (document.activeElement === first || document.activeElement === $dialog[0])) {
                evt.preventDefault();
                last.focus();
            } else if (!evt.shiftKey && document.activeElement === last) {
                evt.preventDefault();
                first.focus();
            }
        }
    });
    if (!window.MutationObserver || !$dialog[0].parentNode) return;
    var observer = new MutationObserver(function() {
        if ($dialog[0].isConnected) return;
        observer.disconnect();
        var active = document.activeElement;
        if (active && active !== document.body && active.isConnected) return;  // already elsewhere (another dialog)
        var $back = $(trigger);
        if (!$back.length || !trigger.isConnected) return;
        if (!$back.is(':visible')) $back = $back.closest('.context-menu').find('.context-menu-trigger');
        if ($back.length) $back[0].focus();
    });
    observer.observe($dialog[0].parentNode, {childList: true});
}

function show_message(evt, msg, callback) {
    var $dialog = show_dialog({
        html: msg,
        extra_class: 'warning',
        event: evt,
        yes_callback: function() {
            $dialog.fadeOut('fast', function() {
                $dialog.remove();
            });
            if (callback) {
                callback();
            }
        },
        close_on_clickoutside: true
    });
}

// Widgets in prompt dialogs (templates node/*.html).
function init_prompt_widgets($dialog) {
    init_award_points($dialog);
}

// node/award_points.html: a slider and a field for the points; a warning when
// the points given would leave the giver below the reputation to comment.
function init_award_points($dialog) {
    var $box = $dialog.find('.award-points');
    if (!$box.length) return;
    var user_reputation = Number($box.attr('data-user-reputation'));
    var reputation_to_comment = Number($box.attr('data-reputation-to-comment'));
    var notified = false;
    var $input = $box.find('#points_input');
    var $slider = $box.find('.award_points_slider');

    function confirm_points(reputation, event) {
        if ((user_reputation - reputation) < reputation_to_comment && !notified) {
            notified = true;
            show_dialog({
                html: $('<div style="max-width: 300px !important; text-align: left;"></div>')
                    .text($box.attr('data-warning'))[0].outerHTML,
                extra_class: 'confirm',
                yes_text: messages.yes,
                show_no: true,
                no_callback: function() {
                    $(".dialog").fadeOut("fast", function() {
                        $('.dialog').remove();
                    })
                },
                no_text: messages.no,
                event: event
            });
        }
    }

    // jQuery UI is loaded on demand (osqa.autocomplete.js).
    var sliderReady = false;
    window.osqaJqueryUI().then(function() {
        $slider.slider({
            min: 1, max: user_reputation, value: Number($input.val()) || 1,
            slide: function(evt, ui) {
                $input.val(ui.value);
                confirm_points(Number(ui.value), evt);
            }
        });
        sliderReady = true;
    }, function() {});

    $input.on('change keyup', function(evt) {
        if ($(this).val() > user_reputation) {
            $(this).val(user_reputation);
        }
        confirm_points(Number($(this).val()), evt);
        if (sliderReady) {
            $slider.slider('option', 'value', $(this).val());
        }
    });
}

function load_prompt(evt, el, url) {
    $.get(url, function(data) {
        var doptions = {
         html: data,
            extra_class: 'prompt',
            yes_callback: function() {
                var postvars = {};
                $dialog.find('input, textarea, select').each(function() {
                    postvars[$(this).attr('name')] = $(this).val();
                });
                $.post(url, postvars, function(data) {
                    $dialog.fadeOut('fast', function() {
                        $dialog.remove();
                    });
                    process_ajax_response(data, evt);
                }, 'json');
            },
            show_no: true,
            copy: false
        }

        if (el.hasClass('copy')) {
            $.extend(doptions, { yes_text : 'Copy', copy: true});
        }

        if (!el.is('.centered')) {
            doptions.event = evt;
        }

        var $dialog = show_dialog(doptions);
    });
}

function process_ajax_response(data, evt, callback) {
    if (!data.success && data['error_message'] != undefined) {
        show_message(evt, data.error_message, function() {if (callback) callback(true);});
        end_command(false);
        return;  // the success callback must not run: it would clear the user's input
    }
    for (var command in (data.commands || {})) {
        response_commands[command].apply(null, data.commands[command]);
    }

    if (data['message'] != undefined) {
        show_message(evt, data.message, function() {if (callback) callback(false);})
    } else {
        if (callback) callback(false);
    }
    end_command(true);
}

var running = false;

function start_command() {
    $('body').append($('<div id="command-loader"></div>'));
    running = true;
}

function end_command(success) {
    if (success) {
        $('#command-loader').addClass('success');
        $('#command-loader').fadeOut("slow", function() {
            $('#command-loader').remove();
            running = false;
        });
    } else {
        $('#command-loader').remove();
        running = false;
    }
}

var comment_box_cursor_position = 0;
function canned_comment(post_id, comment) {
    textarea = $('#comment-' + post_id + '-form textarea')

    // Get the text from the beginning to the caret
    textarea_start = textarea.val().substr(0, comment_box_cursor_position)

    // Get the text from the caret to the end
    textarea_end = textarea.val().substr(comment_box_cursor_position, textarea.val().length)

    textarea.val(textarea_start + comment + textarea_end);
}

// Reduced motion: jQuery effects (fades, slides) finish at once.
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    jQuery.fx.off = true;
}

$(function() {
    // "Skip to content": focus the main content, so the next Tab goes on from there.
    $(document).on('click', '.skip-link', function(evt) {
        var target = document.getElementById((this.getAttribute('href') || '').slice(1));
        if (!target) return;
        evt.preventDefault();
        if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
        target.focus();
    });

    // Report and close dialogs: picking a reason fills the text box.
    $(document).on('change', '.dialog .prompt-examples', function() {
        var $dialog = $(this).closest('.dialog');
        $dialog.find('textarea[name=prompt]').val($(this).val());
        if (/duplicate/i.test($(this).val())) {
            $dialog.find('#close-duplicate-of').trigger('focus');
        }
    });

    // Permanent link dialog: clicking the link selects it; the dialog's
    // Copy button copies it.
    $(document).on('click', '#permanent_link_url', function() {
        $(this).trigger('select');
    });
    $(document).on('click', '#copy_clip_button', function() {
        var $field = $(this).closest('.dialog').find('#permanent_link_url');
        if (!$field.length) return;
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText($field.val());
        } else {
            $field.trigger('select');
            try { document.execCommand('copy'); } catch (e) {}
        }
    });

    // Share a question (post controls): the device's share sheet where there
    // is one, otherwise the link is copied.
    $(document).on('click', 'a.post-share', function(evt) {
        var url = new URL(this.getAttribute('href'), location.href).href;
        var title = $('h1').first().text().trim() || document.title;
        if (navigator.share) {
            evt.preventDefault();
            navigator.share({title: title, url: url}).catch(function () { /* cancelled */ });
        } else if (navigator.clipboard && window.isSecureContext) {
            evt.preventDefault();
            navigator.clipboard.writeText(url).then(function () {
                show_message(evt, messages.link_copied);
            });
        }
    });

    // Canned comments (node/comment_skeleton.html) go in at the caret.
    $(document).on('click', 'a.canned-comment', function(evt) {
        evt.preventDefault();
        canned_comment($(this).attr('data-post-id'), $(this).text());
    });

    // The close button of the message bar (base_content.html).
    $(document).on('click', '#close-notify', function() {
        notify.close(true);
    });

    $(document).on('keydown keyup mousedown mouseup mousemove', 'textarea.commentBox', function(evt) {
        comment_box_cursor_position = this.selectionStart;
    });

    $(document).on('click', 'a.ajax-command', function(evt) {
        if (running) return false;

        var el = $(this);

        var ajax_url = el.attr('href')
        ajax_url = ajax_url + "?nocache=" + new Date().getTime()

        $('.context-menu-dropdown').slideUp('fast');
        $('.context-menu-trigger[aria-expanded]').attr('aria-expanded', 'false');

        if (el.is('.withprompt')) {
            load_prompt(evt, el, ajax_url);
        } else if(el.is('.confirm')) {
            var doptions = {
                html: messages.confirm,
                extra_class: 'confirm',
                yes_callback: function() {
                    start_command();
                    $.post(ajax_url, {}, function(data) {
                        process_ajax_response(data, evt);
                        $dialog.fadeOut('fast', function() {
                            $dialog.remove();
                        });
                    }, 'json');
                },
                yes_text: messages.yes,
                show_no: true,
                no_text: messages.no
            }

            if (!el.is('.centered')) {
                doptions.event = evt;
            }
            var $dialog = show_dialog(doptions);
        } else {
            start_command();
            $.ajax({
                url: ajax_url,
                type: "POST",
                dataType: "json",
                contentType: "application/json; charset=utf-8",
                success: function(data) {
                    process_ajax_response(data, evt);
                }
            });
        }

        return false
    });

    // Post menus ("more"): a disclosure button (aria-expanded) with a list of
    // links; arrow keys move between the links, Escape closes and returns
    // focus to the button.
    // Post menus and comment forms: at load, and for posts the live question
    // page inserts later (osqa.live.js calls window.osqaInitPostWidgets).
    function init_post_widgets(scope) {
    $(scope).find('.context-menu').each(function() {
        var $menu = $(this);
        var $trigger = $menu.find('.context-menu-trigger');
        var $dropdown = $menu.find('.context-menu-dropdown');
        var native_button = $trigger.is('button');
        // aria-expanded is only allowed on buttons (not on a plain span trigger).
        var expandable = native_button || $trigger.attr('role') === 'button';

        function set_expanded(open) {
            if (expandable) $trigger.attr('aria-expanded', open ? 'true' : 'false');
        }

        function close(focus_trigger) {
            set_expanded(false);
            if ($dropdown.is(':visible')) $dropdown.slideUp('fast');
            if (focus_trigger) $trigger.trigger('focus');
        }

        if (!native_button) {
            $trigger.on('keydown', function(evt) {
                if (evt.key === 'Enter' || evt.key === ' ') {
                    evt.preventDefault();
                    $trigger.click();
                }
            });
        }

        $trigger.on('keydown', function(evt) {
            if (evt.key === 'ArrowDown' && $dropdown.is(':visible')) {
                evt.preventDefault();
                $dropdown.find('a').first().trigger('focus');
            }
        });

        $dropdown.on('keydown', 'a', function(evt) {
            var $links = $dropdown.find('a'), index = $links.index(this);
            if (evt.key === 'Escape') {
                evt.preventDefault();
                close(true);
            } else if (evt.key === 'ArrowDown' || evt.key === 'ArrowUp') {
                evt.preventDefault();
                index = (index + (evt.key === 'ArrowDown' ? 1 : -1) + $links.length) % $links.length;
                $links.eq(index).trigger('focus');
            } else if (evt.key === 'Home' || evt.key === 'End') {
                evt.preventDefault();
                $links.eq(evt.key === 'Home' ? 0 : -1).trigger('focus');
            }
        });

        $trigger.on('keydown', function(evt) {
            if (evt.key === 'Escape' && $dropdown.is(':visible')) close(true);
        });

        // Tabbing out of the menu closes it.
        $menu.on('focusout', function(evt) {
            if (evt.relatedTarget && !$menu[0].contains(evt.relatedTarget)) close(false);
        });

        $trigger.click(function(evt) {
            var opening = !$dropdown.is(':visible');
            set_expanded(opening);
            // Opened from the keyboard: move to the first link.
            var from_keyboard = native_button && evt.detail === 0;
            $dropdown.stop(true, true).slideToggle('fast', function() {
                if ($dropdown.is(':visible')) {
                   if (from_keyboard) $dropdown.find('a').first().trigger('focus');
                   // After this click (the slide ends at once with reduced motion).
                   setTimeout(function() {
                       $dropdown.one('clickoutside', function() {
                           if ($dropdown.is(':visible'))
                                close(false);
                       });
                   }, 0);
                }
            });
        });
    });

    $(scope).find('div.comment-form-container').each(function() {
        var $container = $(this);
        var $comment_tools = $container.parent().find('.comment-tools');
        var $comments_container = $container.parent().find('.comments-container');
        
        var $form = $container.find('form');

        if ($form.length) {
            var $textarea = $container.find('textarea');
            var textarea = $textarea.get(0);
            var $button = $container.find('.comment-submit');
            var $cancel = $container.find('.comment-cancel');
            var $chars_left_message = $container.find('.comments-chars-left-msg');
            var $chars_togo_message = $container.find('.comments-chars-togo-msg');
            var $chars_counter = $container.find('.comments-char-left-count');

            var $add_comment_link = $comment_tools.find('.add-comment-link');

            var chars_limits = $chars_counter.html().split('|');

            var min_length = parseInt(chars_limits[0]);
            var max_length = parseInt(chars_limits[1]);

            var warn_length = max_length - 30;
            var current_length = 0;
            var comment_in_form = false;
            var interval = null;

            var hcheck = true;

            $textarea.css("padding-top", 0).css("padding-bottom", 0).css("resize", "none");
            textarea.style.overflow = 'hidden';


            function cleanup_form() {
                $textarea.val('');
                $textarea.css('height', 80);
                $chars_counter.html(max_length);
                $chars_left_message.removeClass('warn');
                comment_in_form = false;
                current_length = 0;

                $chars_left_message.hide();
                $chars_togo_message.show();

                $chars_counter.removeClass('warn');
                $chars_counter.html(min_length);
                $button.prop("disabled", true);

                interval = null;
            }

            cleanup_form();

            function process_form_changes() {
                var length = $textarea.val().replace(/[ ]{2,}/g," ").length;

                if (current_length == length)
                    return;

                if (length < warn_length && current_length >= warn_length) {
                    $chars_counter.removeClass('warn');
                } else if (current_length < warn_length && length >= warn_length){
                    $chars_counter.addClass('warn');
                }

                if (length < min_length) {
                    $chars_left_message.hide();
                    $chars_togo_message.show();
                    $chars_counter.html(min_length - length);
                } else {
                    length = $textarea.val().length;
                    $chars_togo_message.hide();
                    $chars_left_message.show();
                    $chars_counter.html(max_length - length);
                }

                if (length > max_length || length < min_length) {
                    $button.prop("disabled", true);
                } else {
                    $button.prop("disabled", false);
                }

                var current_height = textarea.style.height;
                if (hcheck)
                    textarea.style.height = "0px";

                var h = Math.max(80, textarea.scrollHeight);
                textarea.style.height = current_height;
                $textarea.animate({height: h + 'px'}, 50);

                current_length = length;
            }

            function show_comment_form() {
                $container.slideDown('slow');
                $add_comment_link.fadeOut('slow');
                $textarea.focus();
                interval = window.setInterval(function() {
                    process_form_changes();
                }, 200);
            }

            function hide_comment_form() {
                if (interval != null) {
                    window.clearInterval(interval);
                    interval = null;
                }
                $container.slideUp('slow');
                $add_comment_link.fadeIn('slow');
            }

            $add_comment_link.click(function(){
                cleanup_form();
                show_comment_form();
                return false;
            });

            $(document).on('click', '#' + $comments_container.attr('id') + ' .comment-edit', function() {
                var $link = $(this);
                var comment_id = /comment-(\d+)-edit/.exec($link.attr('id'))[1];
                var $comment = $('#comment-' + comment_id);

                comment_in_form = comment_id;

                $.get($link.attr('href'), function(data) {
                    $textarea.val(data);
                });

                $comment.slideUp('slow');
                show_comment_form();
                return false;
            });

            $button.click(function(evt) {
                if (running) return false;

                var post_data = {
                    comment: $textarea.val()
                }

                if (comment_in_form) {
                    post_data['id'] = comment_in_form;
                }

                start_command();
                $.post($form.attr('action'), post_data, function(data) {
                    process_ajax_response(data, evt, function(error) {
                        if (!error) {
                            cleanup_form();
                            hide_comment_form();
                        }
                    });

                }, "json");

                return false;
            });

            // Submit comment with CTRL + Enter
            $textarea.keydown(function(e) {
                if (e.ctrlKey && e.keyCode == 13 && !$button.prop('disabled')) {
                    // console.log('submit');
                    $(this).parent().find('input.comment-submit').click();
                }
            });

            $cancel.click(function(event) {
                if (confirm("You will lose all of your changes in this comment.  Do you still wish to proceed?")){
                    if (comment_in_form) {
                        $comment = $('#comment-' + comment_in_form).slideDown('slow');
                    }
                    hide_comment_form();
                    cleanup_form();
                }
                return false;
            });
        }

        $comment_tools.find('.show-all-comments-link').click(function() {
            $comments_container.find('.not_top_scorer').slideDown('slow');
            $(this).fadeOut('slow');
            $comment_tools.find('.comments-showing').fadeOut('slow');
            return false;
        });
    });
    }
    init_post_widgets(document);
    window.osqaInitPostWidgets = init_post_widgets;

    // The editor's character and word count is in osqa.editor.js.
});

//var scriptUrl, interestingTags, ignoredTags, tags, $;
function pickedTags(){

    var sendAjax = function(tagname, reason, action, callback){
        var url = scriptUrl;
        if (action == 'add'){
            url += $.i18n._('mark-tag/');
            if (reason == 'good'){
                url += $.i18n._('interesting/');
            }
            else {
                url += $.i18n._('ignored/');
            }
        }
        else {
            url += $.i18n._('unmark-tag/');
        }
        url = url + tagname + '/';

        var call_settings = {
            type:'POST',
            url:url,
            data: ''
        };
        if (callback !== false){
            call_settings.success = callback;
        }
        $.ajax(call_settings);
    };


    var unpickTag = function(from_target ,tagname, reason, send_ajax){
        //send ajax request to delete tag
        var deleteTagLocally = function(){
            from_target[tagname].remove();
            delete from_target[tagname];
            $(".tags.interesting").trigger('contentchanged');
        };

        if (send_ajax){
            sendAjax(tagname,reason,'remove',deleteTagLocally);
        }
        else {
            deleteTagLocally();
        }
    };

    var setupTagDeleteEvents = function(obj,tag_store,tagname,reason,send_ajax){
        obj.off('mouseover').on('mouseover', function(){
            $(this).attr('src', mediaUrl('media/images/close-small-hover.png'));
        });
        obj.off('mouseout').on('mouseout', function(){
            $(this).attr('src', mediaUrl('media/images/close-small-dark.png'));
        });
        obj.click( function(){
            unpickTag(tag_store,tagname,reason,send_ajax);
        });
    };

    var handlePickedTag = function(obj,reason){
        var tagname = String($(obj).prev().val()).trim();
        var to_target = interestingTags;
        var from_target = ignoredTags;
        var to_tag_container;
        if (reason == 'bad'){
            to_target = ignoredTags;
            from_target = interestingTags;
            to_tag_container = $('div .tags.ignored');
        }
        else if (reason != 'good'){
            return;
        }
        else {
            to_tag_container = $('div .tags.interesting');
        }

        if (tagname in from_target){
            unpickTag(from_target,tagname,reason,false);
        }

        if (!(tagname in to_target)){
            //send ajax request to pick this tag

            sendAjax(tagname,reason,'add',function(){
                var new_tag = $('<span></span>');
                new_tag.addClass('deletable-tag');
                var tag_link = $('<a></a>');
                tag_link.attr('rel','tag');
                tag_link.attr('href', scriptUrl + $.i18n._('tags/') + tagname + '/');
                tag_link.html(tagname);
                var del_link = $('<img />');
                del_link.addClass('delete-icon');
                del_link.attr('src', mediaUrl('media/images/close-small-dark.png'));

                setupTagDeleteEvents(del_link, to_target, tagname, reason, true);

                new_tag.append(tag_link);
                new_tag.append(del_link);
                to_tag_container.append(new_tag);

                to_target[tagname] = new_tag;

                to_tag_container.trigger('contentchanged');
            });
        }
    };

    var collectPickedTags = function(){
        var good_prefix = 'interesting-tag-';
        var bad_prefix = 'ignored-tag-';
        var good_re = RegExp('^' + good_prefix);
        var bad_re = RegExp('^' + bad_prefix);
        interestingTags = {};
        ignoredTags = {};
        $('.deletable-tag').each(
            function(i,item){
                var item_id = $(item).attr('id');
                var tag_name, tag_store;
                if (good_re.test(item_id)){
                    tag_name = item_id.replace(good_prefix,'');
                    tag_store = interestingTags;
                    reason = 'good';
                }
                else if (bad_re.test(item_id)){
                    tag_name = item_id.replace(bad_prefix,'');
                    tag_store = ignoredTags;
                    reason = 'bad';
                }
                else {
                    return;
                }
                tag_store[tag_name] = $(item);
                setupTagDeleteEvents($(item).find('img'),tag_store,tag_name,reason,true);
            }
        );
    };

    var setupHideIgnoredQuestionsControl = function(){
        $('#hideIgnoredTagsCb').off('click').on('click', function(){
            $.ajax({
                        type: 'POST',
                        dataType: 'json',
                        cache: false,
                        url: scriptUrl + $.i18n._('command/'),
                        data: {command:'toggle-ignored-questions'}
                    });
        });
    };
    return {
        init: function(){
            collectPickedTags();
            setupHideIgnoredQuestionsControl();
            $("#interestingTagInput, #ignoredTagInput").osqaAutocomplete(messages.matching_tags_url, {max: 20});
            $("#interestingTagAdd").click(function(){handlePickedTag(this,'good');});
            $("#ignoredTagAdd").click(function(){handlePickedTag(this,'bad');});
        }
    };
}

Hilite={elementid:"content",exact:true,max_nodes:1000,onload:true,style_name:"hilite",style_name_suffix:true,debug_referrer:""};Hilite.search_engines=[["local","q"],["cnprog\\.","q"],["google\\.","q"],["search\\.yahoo\\.","p"],["search\\.msn\\.","q"],["search\\.live\\.","query"],["search\\.aol\\.","userQuery"],["ask\\.com","q"],["altavista\\.","q"],["feedster\\.","q"],["search\\.lycos\\.","q"],["alltheweb\\.","q"],["technorati\\.com/search/([^\\?/]+)",1],["dogpile\\.com/info\\.dogpl/search/web/([^\\?/]+)",1,true]];Hilite.decodeReferrer=function(d){var g=null;var e=new RegExp("");for(var c=0;c<Hilite.search_engines.length;c++){var f=Hilite.search_engines[c];e.compile("^http://(www\\.)?"+f[0],"i");var b=d.match(e);if(b){var a;if(isNaN(f[1])){a=Hilite.decodeReferrerQS(d,f[1])}else{a=b[f[1]+1]}if(a){a=decodeURIComponent(a);if(f.length>2&&f[2]){a=decodeURIComponent(a)}a=a.replace(/\'|"/g,"");a=a.split(/[\s,\+\.]+/);return a}break}}return null};Hilite.decodeReferrerQS=function(f,d){var b=f.indexOf("?");var c;if(b>=0){var a=new String(f.substring(b+1));b=0;c=0;while((b>=0)&&((c=a.indexOf("=",b))>=0)){var e,g;e=a.substring(b,c);b=a.indexOf("&",c)+1;if(e==d){if(b<=0){return a.substring(c+1)}else{return a.substring(c+1,b-1)}}else{if(b<=0){return null}}}}return null};Hilite.hiliteElement=function(f,e){if(!e||f.childNodes.length==0){return}var c=new Array();for(var b=0;b<e.length;b++){e[b]=e[b].toLowerCase();if(Hilite.exact){c.push("\\b"+e[b]+"\\b")}else{c.push(e[b])}}c=new RegExp(c.join("|"),"i");var a={};for(var b=0;b<e.length;b++){if(Hilite.style_name_suffix){a[e[b]]=Hilite.style_name+(b+1)}else{a[e[b]]=Hilite.style_name}}var d=function(m){var j=c.exec(m.data);if(j){var n=j[0];var i="";var h=m.splitText(j.index);var g=h.splitText(n.length);var l=m.ownerDocument.createElement("SPAN");m.parentNode.replaceChild(l,h);l.className=a[n.toLowerCase()];l.appendChild(h);return l}else{return m}};Hilite.walkElements(f.childNodes[0],1,d)};Hilite.hilite=function(){var a=Hilite.debug_referrer?Hilite.debug_referrer:document.referrer;var b=null;a=Hilite.decodeReferrer(a);if(a&&((Hilite.elementid&&(b=document.getElementById(Hilite.elementid)))||(b=document.body))){Hilite.hiliteElement(b,a)}};Hilite.walkElements=function(d,f,e){var a=/^(script|style|textarea)/i;var c=0;while(d&&f>0){c++;if(c>=Hilite.max_nodes){var b=function(){Hilite.walkElements(d,f,e)};setTimeout(b,50);return}if(d.nodeType==1){if(!a.test(d.tagName)&&d.childNodes.length>0){d=d.childNodes[0];f++;continue}}else{if(d.nodeType==3){d=e(d)}}if(d.nextSibling){d=d.nextSibling}else{while(f>0){d=d.parentNode;f--;if(d.nextSibling){d=d.nextSibling;break}}}}};if(Hilite.onload){if(window.attachEvent){window.attachEvent("onload",Hilite.hilite)}else{if(window.addEventListener){window.addEventListener("load",Hilite.hilite,false)}else{var __onload=window.onload;window.onload=function(){Hilite.hilite();__onload()}}}};

var mediaUrl = function(resource){
    return scriptUrl + 'm/' + osqaSkin + '/' + resource;
};

/*
 * jQuery i18n plugin
 * @requires jQuery v1.1 or later
 *
 * Examples at: http://recurser.com/articles/2008/02/21/jquery-i18n-translation-plugin/
 * Dual licensed under the MIT and GPL licenses:
 *   http://www.opensource.org/licenses/mit-license.php
 *   http://www.gnu.org/licenses/gpl.html
 *
 * Based on 'javascript i18n that almost doesn't suck' by markos
 * http://markos.gaivo.net/blog/?p=100
 *
 * Revision: $Id$
 * Version: 1.0.0  Feb-10-2008
 */
 (function($) {
/**
 * i18n provides a mechanism for translating strings using a jscript dictionary.
 *
 */


/*
 * i18n property list
 */
$.i18n = {

/**
 * setDictionary()
 * Initialise the dictionary and translate nodes
 *
 * @param property_list i18n_dict : The dictionary to use for translation
 */
	setDictionary: function(i18n_dict) {
		i18n_dict = i18n_dict;
	},

/**
 * _()
 * The actual translation function. Looks the given string up in the
 * dictionary and returns the translation if one exists. If a translation
 * is not found, returns the original word
 *
 * @param string str : The string to translate
 * @param property_list params : params for using printf() on the string
 * @return string : Translated word
 *
 */
	_: function (str, params) {
		var transl = str;
		if (i18n_dict&& i18n_dict[str]) {
			transl = i18n_dict[str];
		}
		return this.printf(transl, params);
	},

/**
 * toEntity()
 * Change non-ASCII characters to entity representation
 *
 * @param string str : The string to transform
 * @return string result : Original string with non-ASCII content converted to entities
 *
 */
	toEntity: function (str) {
		var result = '';
		for (var i=0;i<str.length; i++) {
			if (str.charCodeAt(i) > 128)
				result += "&#"+str.charCodeAt(i)+";";
			else
				result += str.charAt(i);
		}
		return result;
	},

/**
 * stripStr()
 *
 * @param string str : The string to strip
 * @return string result : Stripped string
 *
 */
 	stripStr: function(str) {
		return str.replace(/^\s*/, "").replace(/\s*$/, "");
	},

/**
 * stripStrML()
 *
 * @param string str : The multi-line string to strip
 * @return string result : Stripped string
 *
 */
	stripStrML: function(str) {
		// Split because m flag doesn't exist before JS1.5 and we need to
		// strip newlines anyway
		var parts = str.split('\n');
		for (var i=0; i<parts.length; i++)
			parts[i] = stripStr(parts[i]);

		// Don't join with empty strings, because it "concats" words
		// And strip again
		return stripStr(parts.join(" "));
	},

/*
 * printf()
 * C-printf like function, which substitutes %s with parameters
 * given in list. %%s is used to escape %s.
 *
 * Doesn't work in IE5.0 (splice)
 *
 * @param string S : string to perform printf on.
 * @param string L : Array of arguments for printf()
 */
	printf: function(S, L) {
		if (!L) return S;

		var nS = "";
		var tS = S.split("%s");

		for(var i=0; i<L.length; i++) {
			if (tS[i].lastIndexOf('%') == tS[i].length-1 && i != L.length-1)
				tS[i] += "s"+tS.splice(i+1,1)[0];
			nS += tS[i] + L[i];
		}
		return nS + tS[tS.length-1];
	}

};


})(jQuery);


//var i18nLang;
var i18nZh = {
	'insufficient privilege':'??????????',
	'cannot pick own answer as best':'??????????????',
	'anonymous users cannot select favorite questions':'?????????????',
	'please login':'??????',
	'anonymous users cannot vote':'????????',
	'>15 points requried to upvote':'??+15?????????',
	'>100 points required to downvote':'??+100?????????',
	'please see': '??',
	'cannot vote for own posts':'??????????',
	'daily vote cap exhausted':'????????????????',
	'cannot revoke old vote':'??????????????',
	'please confirm offensive':"??????????????????????",
	'anonymous users cannot flag offensive posts':'???????????',
	'cannot flag message as offensive twice':'???????',
	'flag offensive cap exhausted':'?????????????5??????',
	'need >15 points to report spam':"??+15??????????",
	'confirm delete':"?????/????????",
	'anonymous users cannot delete/undelete':"???????????????",
	'post recovered':"?????????????",
	'post deleted':"????????????",
	'add comment':'????',
	'community karma points':'????',
	'to comment, need':'????',
	'delete this comment':'?????',
	'hide comments':"????",
	'add a comment':"????",
	'comments':"??",
	'confirm delete comment':"?????????",
	'characters':'??',
	'can write':'???',
	'click to close':'???????',
	'loading...':'???...',
	'tags cannot be empty':'???????',
	'tablimits info':"??5????????????20????",
	'content cannot be empty':'???????',
	'content minchars': '????? {0} ???',
	'please enter title':'??????',
	'title minchars':"????? {0} ???",
	'delete':'??',
	'undelete':	'??',
	'bold':'??',
	'italic':'??',
	'link':'???',
	'quote':'??',
	'preformatted text':'??',
	'image':'??',
	'numbered list':'??????',
	'bulleted list':'??????',
	'heading':'??',
	'horizontal bar':'???',
	'undo':'??',
	'redo':'??',
	'enter image url':'<b>??????</b></p><p>???<br />http://www.example.com/image.jpg   \"????\"',
	'enter url':'<b>??Web??</b></p><p>???<br />http://www.cnprog.com/   \"????\"</p>"',
	'upload image':'?????????'
};

var i18nEn = {
	'need >15 points to report spam':'need >15 points to report spam ',
    '>15 points requried to upvote':'>15 points required to upvote ',
	'tags cannot be empty':'please enter at least one tag',
	'anonymous users cannot vote':'sorry, anonymous users cannot vote ',
	'anonymous users cannot select favorite questions':'sorry, anonymous users cannot select favorite questions ',
	'to comment, need': '(to comment other people\'s posts, karma ',
	'please see':'please see ',
	'community karma points':' or more is necessary) - ',
	'upload image':'Upload image:',
	'enter image url':'enter URL of the image, e.g. http://www.example.com/image.jpg \"image title\"',
	'enter url':'enter Web address, e.g. http://www.example.com \"page title\"',
	'daily vote cap exhausted':'sorry, you\'ve used up todays vote cap',
	'cannot pick own answer as best':'sorry, you cannot accept your own answer',
	'cannot revoke old vote':'sorry, older votes cannot be revoked',
	'please confirm offensive':'are you sure this post is offensive, contains spam, advertising, malicious remarks, etc.?',
	'flag offensive cap exhausted':'sorry, you\'ve used up todays cap of flagging offensive messages ',
	'confirm delete':'are you sure you want to delete this?',
	'anonymous users cannot delete/undelete':'sorry, anonymous users cannot delete or undelete posts',
	'post recovered':'your post is now restored!',
	'post deleted':'your post has been deleted',
	'confirm delete comment':'do you really want to delete this comment?',
	'can write':'have ',
	'tablimits info':'up to 5 tags, no more than 20 characters each',
	'content minchars': 'please enter more than {0} characters',
	'title minchars':"please enter at least {0} characters",
	'characters':'characters left',
    'cannot vote for own posts':'sorry, you cannot vote for your own posts',
    'cannot flag message as offensive twice':'cannot flag message as offensive twice ',
	'>100 points required to downvote':'>100 points required to downvote '
};

var i18nEs = {
	'insufficient privilege':'privilegio insuficiente',
	'cannot pick own answer as best':'no puede escoger su propia respuesta como la mejor',
	'anonymous users cannot select favorite questions':'usuarios anonimos no pueden seleccionar',
	'please login':'por favor inicie sesión',
	'anonymous users cannot vote':'usuarios anónimos no pueden votar',
	'>15 points requried to upvote': '>15 puntos requeridos para votar positivamente',
	'>100 points required to downvote':'>100 puntos requeridos para votar negativamente',
	'please see': 'por favor vea',
	'cannot vote for own posts':'no se puede votar por sus propias publicaciones',
	'daily vote cap exhausted':'cuota de votos diarios excedida',
	'cannot revoke old vote':'no puede revocar un voto viejo',
	'please confirm offensive':"por favor confirme ofensiva",
	'anonymous users cannot flag offensive posts':'usuarios anónimos no pueden marcar publicaciones como ofensivas',
	'cannot flag message as offensive twice':'no puede marcar mensaje como ofensivo dos veces',
	'flag offensive cap exhausted':'cuota para marcar ofensivas ha sido excedida',
	'need >15 points to report spam':"necesita >15 puntos para reportar spam",
	'confirm delete':"¿Está seguro que desea borrar esto?",
	'anonymous users cannot delete/undelete':"usuarios anónimos no pueden borrar o recuperar publicaciones",
	'post recovered':"publicación recuperada",
	'post deleted':"publicación borrada?",
	'add comment':'agregar comentario',
	'community karma points':'reputación comunitaria',
	'to comment, need':'para comentar, necesita reputación',
	'delete this comment':'borrar este comentario',
	'hide comments':"ocultar comentarios",
	'add a comment':"agregar comentarios",
	'comments':"comentarios",
	'confirm delete comment':"¿Realmente desea borrar este comentario?",
	'characters':'caracteres faltantes',
	'can write':'tiene ',
	'click to close':'haga click para cerrar',
	'loading...':'cargando...',
	'tags cannot be empty':'las etiquetas no pueden estar vacías',
	'tablimits info':"hasta 5 etiquetas de no mas de 20 caracteres cada una",
	'content cannot be empty':'el contenido no puede estar vacío',
	'content minchars': 'por favor introduzca mas de {0} caracteres',
	'please enter title':'por favor ingrese un título',
	'title minchars':"por favor introduzca al menos {0} caracteres",
	'delete':'borrar',
	'undelete':	'recuperar',
	'bold': 'negrita',
	'italic':'cursiva',
	'link':'enlace',
	'quote':'citar',
	'preformatted text':'texto preformateado',
	'image':'imagen',
	'numbered list':'lista numerada',
	'bulleted list':'lista no numerada',
	'heading':'??',
	'horizontal bar':'barra horizontal',
	'undo':'deshacer',
	'redo':'rehacer',
	'enter image url':'introduzca la URL de la imagen, por ejemplo?<br />http://www.example.com/image.jpg   \"titulo de imagen\"',
	'enter url':'introduzca direcciones web, ejemplo?<br />http://www.cnprog.com/   \"titulo del enlace\"</p>"',
	'upload image':'cargar imagen?'
};

var i18n = {
	'en':i18nEn,
	'zh_CN':i18nZh,
	'es':i18nEs
};

// URL paths are the same in every language, so dictionaries must not translate them;
// languages without a dictionary fall back to English.
var i18n_dict = jQuery.extend({}, i18nEn, i18n[i18nLang] || {});

var notify = function() {
    var visible = false;
    return {
        show: function(html) {
            if (html) {
                $("body").css("margin-top", "2.2em");
                $(".notify span").html(html);
            }
            $(".notify").fadeIn("slow");
            visible = true;
        },
        close: function(doPostback) {
            $(".notify").fadeOut("fast");
            $("body").css("margin-top", "0");
            visible = false;
        },
        isVisible: function() { return visible; }
    };
} ();

/*
 * jQuery outside events - v1.1 - 3/16/2010
 * http://benalman.com/projects/jquery-outside-events-plugin/
 *
 * Copyright (c) 2010 "Cowboy" Ben Alman
 * Dual licensed under the MIT and GPL licenses.
 * http://benalman.com/about/license/
 */
(function($,c,b){$.map("click dblclick mousemove mousedown mouseup mouseover mouseout change select submit keydown keypress keyup".split(" "),function(d){a(d)});a("focusin","focus"+b);a("focusout","blur"+b);$.addOutsideEvent=a;function a(g,e){e=e||g+b;var d=$(),h=g+"."+e+"-special-event";$.event.special[e]={setup:function(){d=d.add(this);if(d.length===1){$(c).on(h,f)}},teardown:function(){d=d.not(this);if(d.length===0){$(c).off(h)}},add:function(i){var j=i.handler;i.handler=function(l,k){l.target=k;j.apply(this,arguments)}}};function f(i){$(d).each(function(){var j=$(this);if(this!==i.target&&!j.has(i.target).length){j.triggerHandler(e,[i.target])}})}}})(jQuery,document,"outside");

$(document).ready( function(){
    pickedTags().init();

    $('input#bnewaccount').click(function() {
        $('#bnewaccount').disabled=true;
    });
});

function yourWorkWillBeLost(e) {
    if(browserTester('chrome')) {
        return "Are you sure you want to leave?  Your work will be lost.";
    } else if(browserTester('safari')) {
        return "Are you sure you want to leave?  Your work will be lost.";
    } else {
        if(!e) e = window.event;
        e.cancelBubble = true;
        e.returnValue = 'If you leave, your work will be lost.';

        if (e.stopPropagation) {
            e.stopPropagation();
            e.preventDefault();
        }
        return e;
    }
}

function browserTester(browserString) {
    return navigator.userAgent.toLowerCase().indexOf(browserString) > -1;
}

// Add missing IE functionality
if (!window.addEventListener) {
    if (window.attachEvent) {
        window.addEventListener = function (type, listener, useCapture) {
            window.attachEvent('on' + type, listener);
        };
        window.removeEventListener = function (type, listener, useCapture) {
            window.detachEvent('on' + type, listener);
        };
    } else {
        window.addEventListener = function (type, listener, useCapture) {
            window['on' + type] = listener;
        };
        window.removeEventListener = function (type, listener, useCapture) {
            window['on' + type] = null;
        };
    }
}
