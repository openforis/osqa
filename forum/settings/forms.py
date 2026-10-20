import json
import os
from django import forms
from forum.settings.base import Setting
from forum.settings.guides import FIELD_EXTRAS
from django.utils.translation import gettext as _
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.core.files.storage import FileSystemStorage
from django.urls import reverse

class DummySetting:
    pass

class UnfilteredField(forms.CharField):
    def clean(self, value):
            return value


class SettingsSetForm(forms.Form):
    def __init__(self, set, data=None, unsaved=None, *args, **kwargs):
        initial = dict([(setting.name, setting.value) for setting in set])

        if unsaved:
            initial.update(unsaved)

        super(SettingsSetForm, self).__init__(data, initial=initial, *args, **kwargs)

        for setting in set:
            widget = setting.field_context.get('widget', None)

            if isinstance(setting, Setting.emulators.get(str, DummySetting)) and not widget:
                setting.field_context['widget'] = forms.TextInput(attrs={'class': 'longstring'})
            # Guidance (example, keywords: forum/settings/guides.py) is not a field argument.
            context = dict((k, v) for k, v in setting.field_context.items() if k not in FIELD_EXTRAS)

            if widget is forms.CheckboxSelectMultiple or widget is forms.SelectMultiple or isinstance(widget, forms.SelectMultiple):
                field = forms.MultipleChoiceField(**context)
            elif widget is forms.RadioSelect or isinstance(widget, forms.RadioSelect):
                field = forms.ChoiceField(**context)
            elif isinstance(setting, Setting.emulators.get(str, DummySetting)):
                field = forms.CharField(**context)
            elif isinstance(setting, Setting.emulators.get(float, DummySetting)):
                field = forms.FloatField(**context)
            elif isinstance(setting, Setting.emulators.get(int, DummySetting)):
                field = forms.IntegerField(**context)
            elif isinstance(setting, Setting.emulators.get(bool, DummySetting)):
                field = forms.BooleanField(**context)
            else:
                field = UnfilteredField(**context)

            self.fields[setting.name] = field

        self.set = set
        self.settings = dict((setting.name, setting) for setting in set)

    def as_table(self, names=None):
        """One row per setting (id "setting-<NAME>", the admin search's
        anchor): label and setting name, the field, its help and example, and
        its default with a "Use default" button (osqa.admin.js fills the field
        in; nothing is saved before Save). Rows of settings whose saved value
        isn't the default are marked "Changed". Only `names` when given (the
        sections of a guided page, forum/settings/guides.py)."""
        rows = []
        hidden = []

        top_errors = self.non_field_errors()
        if top_errors and names is None:
            rows.append('<tr><td colspan="2">%s</td></tr>' % top_errors)

        for name in self.fields if names is None else [n for n in names if n in self.fields]:
            bf = self[name]
            if bf.is_hidden:
                hidden.append(str(bf))
                continue

            setting = self.settings.get(name)
            # The id the field's aria-describedby names.
            help_text = bf.help_text and '<span class="helptext" id="%s_helptext">%s</span>' % (
                bf.auto_id, bf.help_text) or ''
            example = setting.field_context.get('example') if setting is not None else None
            if example:
                help_text += format_html('<span class="setting-example">{} <code>{}</code></span>',
                                         _('Example:'), example)
            customized = setting is not None and is_customized(setting)
            heading = format_html(
                '{label}{changed}<span class="setting-name" title="{title}">{name}</span>',
                label=bf.label and bf.label_tag() or '', name=name,
                title=_('Name of the setting, e.g. for templates: {{ settings.%s }}') % name,
                changed=format_html(' <span class="setting-changed">{}</span>', _('Changed')) if customized else '')
            default = ''
            if setting is not None and setting.default is not None:
                default = format_html(
                    '<div class="setting-default"{hidden}>{text} <span class="setting-default-value">{value}</span> '
                    '<button type="button" class="setting-reset">{reset}'
                    '<span class="admin-visually-hidden"> ({label})</span></button></div>',
                    hidden=mark_safe('' if customized else ' hidden'), text=_('Default:'), label=bf.label or name,
                    value=default_text(setting, self.fields[name]), reset=_('Use default'))
            rows.append(format_html(
                '<tr id="setting-{name}" class="setting-row{classes}" data-default="{default}">'
                '<th>{heading}</th><td>{errors}{field}{help}{default_row}</td></tr>',
                name=name, classes=' is-customized' if customized else '', default=default_value(setting),
                heading=heading, errors=mark_safe(str(bf.errors)), field=mark_safe(str(bf)), help=mark_safe(help_text),
                default_row=default))

        if hidden:
            if rows:
                rows[-1] = rows[-1][:-len('</td></tr>')] + ''.join(hidden) + '</td></tr>'
            else:
                rows.append('<tr><td colspan="2">%s</td></tr>' % ''.join(hidden))

        return mark_safe('\n'.join(str(r) for r in rows))

    def changed_labels(self):
        """Labels of the settings this (valid) form changes."""
        return [str(self.fields[name].label or name) for name in self.changed_data if name in self.fields]

    def save(self):
        for setting in self.set:
            setting.set_value(self.cleaned_data[setting.name])

def is_customized(setting):
    """The saved value differs from the default."""
    if setting.default is None:
        return False
    value = setting.value
    if isinstance(setting.default, (list, tuple)):
        return list(value or []) != list(setting.default)
    return value != setting.default


def default_value(setting):
    """The default as osqa.admin.js puts it in the field: "true"/"false" for
    check boxes, JSON for lists, else the text."""
    if setting is None or setting.default is None:
        return ''
    default = setting.default
    if isinstance(default, bool):
        return 'true' if default else 'false'
    if isinstance(default, (list, tuple)):
        return json.dumps(list(default))
    return str(default)


def default_text(setting, field):
    """The default as people read it: On/Off, a choice's label, "(empty)"."""
    default = setting.default
    if isinstance(default, bool):
        return _('On') if default else _('Off')
    if isinstance(default, (list, tuple)):
        default = ', '.join(str(v) for v in default)
    choices = getattr(field, 'choices', None) or getattr(getattr(field, 'widget', None), 'choices', None)
    for key, label in choices or ():
        if str(key) == str(default):
            return str(label)
    text = str(default)
    if not text.strip():
        return _('(empty)')
    return text if len(text) <= 80 else text[:77] + '…'


class ImageFormWidget(forms.Widget):
    def render(self, name, value, attrs=None, renderer=None):
        # The file input gets the field's id, so the setting's <label> names it.
        return format_html("""
            <img src="{value}" alt="{alt}" class="setting-image-preview" /><br />
            {change} <input type="file" id="{id}" name="{name}" accept="image/*" />
            <input type="hidden" name="{name}_old" value="{value}" />
            """, name=name, value=value or '', id=(attrs or {}).get('id') or 'id_%s' % name,
                           alt=_('Current image'), change=_('Change this:'))

    def value_from_datadict(self, data, files, name):
        if name in files:
            f = files[name]

            # check file type
            file_name_suffix = os.path.splitext(f.name)[1].lower()

            if not file_name_suffix in ('.jpg', '.jpeg', '.gif', '.png', '.bmp', '.tiff', '.ico', '.webp'):
                raise Exception('File type not allowed')

            from forum.settings import UPFILES_FOLDER, UPFILES_ALIAS

            from django.core.files.base import ContentFile
            from forum.utils.images import process_image

            # Re-encoded without metadata (EXIF, GPS...); icons are kept as they are.
            data, file_name = process_image(f, "_".join(f.name.split()), keep_ico=True)
            storage = FileSystemStorage(str(UPFILES_FOLDER), str(UPFILES_ALIAS))
            new_file_name = storage.save(file_name, ContentFile(data))
            return str(UPFILES_ALIAS) + new_file_name
        else:
            if "%s_old" % name in data:
                return data["%s_old" % name]
            elif name in data:
                return data[name]

class SecretInput(forms.PasswordInput):
    """A key or password setting: shown as dots, with a "Show" button
    (osqa.admin.js), and kept in the field when the page is saved again."""
    def __init__(self, attrs=None):
        super().__init__(attrs=dict({'class': 'longstring secret-input', 'autocomplete': 'off',
                                     'spellcheck': 'false'}, **(attrs or {})), render_value=True)


class StringListWidget(forms.Widget):
    def render(self, name, value, attrs=None, renderer=None):
        remove, add = _('Remove'), _('Add another')
        rows = format_html_join('', """
            <div class="string-list-input">
                <input type="text" name="{0}" value="{1}" />
                <button type="button" class="string_list_widget_button remove" aria-label="{2}" title="{2}">&minus;</button>
            </div>
            """, ((name, s, remove) for s in value or ()))

        return format_html("""
            <div class="string_list_widgets">
                {rows}
                <div class="string-list-add"><button type="button" name="{name}" class="string_list_widget_button add"
                    aria-label="{add}" title="{add}" data-remove-label="{remove}">+</button></div>
            </div>
            """, name=name, rows=rows, add=add, remove=remove)

    def value_from_datadict(self, data, files, name):
        if 'submit' in data:
            return data.getlist(name)
        else:
            return data[name]

class CommaStringListWidget(forms.Textarea):
    def render(self, name, value, attrs=None, renderer=None):
        return super(CommaStringListWidget, self).render(name, ', '.join(value), attrs, renderer)


    def value_from_datadict(self, data, files, name):
        if 'submit' in data:
            return [s.strip() for s in data[name].split(',')]
        else:
            return ', '.join(data[name])    

class TestEmailSettingsWidget(forms.TextInput):
    def render(self, name, value, attrs=None, renderer=None):
        if not value:
            value = ''

        return format_html("""
            <div id="test_email_settings">
                <a href="{url}" class="button test_button" role="button">{label}</a>

                <div class="test_email_status_box">
                <div style="display: none" class="ajax_indicator">{wait}</div>
                <div class="test_status" aria-live="polite"></div>
                </div>
            </div>
            """, url=reverse("test_email_settings"), label=_('Test'),
            wait=_('Testing your current e-mail settings. Please, wait.'))
