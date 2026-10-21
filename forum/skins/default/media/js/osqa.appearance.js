/* Admin > Look and feel (osqaadmin/guides/appearance.html): a ready-made
   style's button (or the Style list) fills in the fields, and the light and
   dark samples and the contrast lines follow the fields as they change. The colours are worked out as
   forum/utils/appearance.py does for the site (keep the two in step):
   lightness moved, hue kept, until text has 4.5:1 contrast. */
(function () {
    'use strict';

    var WHITE = '#ffffff', LIGHT_BACKGROUND = '#f5f7fa';
    var DARK_SURFACE = '#161b22', DARK_BACKGROUND = '#0d1117';
    var RATIO = 4.5;
    // osqa.css's own values, used while a colour is the default.
    var SKIN = {
        light: {soft: '#eaf1fb'},
        dark: {link: '#79b0ff', button: '#2f6fd6', soft: '#1a2a42', accent: '#cf430c'}
    };

    function rgb(c) {
        return [1, 3, 5].map(function (i) { return parseInt(c.substr(i, 2), 16); });
    }

    function hex(channels) {
        return '#' + channels.map(function (c) {
            return ('0' + Math.max(0, Math.min(255, Math.round(c))).toString(16)).slice(-2);
        }).join('');
    }

    function luminance(c) {
        var v = rgb(c).map(function (x) {
            x /= 255;
            return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
    }

    function contrast(a, b) {
        var la = luminance(a), lb = luminance(b);
        return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    }

    function mix(a, b, share) {
        var x = rgb(a), y = rgb(b);
        return hex(x.map(function (v, i) { return v + (y[i] - v) * share; }));
    }

    function mod1(x) {
        return ((x % 1) + 1) % 1;
    }

    // Python's colorsys.rgb_to_hls / hls_to_rgb.
    function toHls(c) {
        var ch = rgb(c).map(function (x) { return x / 255; });
        var r = ch[0], g = ch[1], b = ch[2];
        var max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
        if (max === min) return [0, l, 0];
        var range = max - min;
        var s = l <= 0.5 ? range / (max + min) : range / (2 - max - min);
        var rc = (max - r) / range, gc = (max - g) / range, bc = (max - b) / range;
        var h = r === max ? bc - gc : (g === max ? 2 + rc - bc : 4 + gc - rc);
        return [mod1(h / 6), l, s];
    }

    function fromHls(h, l, s) {
        if (s === 0) return hex([l * 255, l * 255, l * 255]);
        var m2 = l <= 0.5 ? l * (1 + s) : l + s - l * s, m1 = 2 * l - m2;
        function v(hue) {
            hue = mod1(hue);
            if (hue < 1 / 6) return m1 + (m2 - m1) * hue * 6;
            if (hue < 0.5) return m2;
            if (hue < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - hue) * 6;
            return m1;
        }
        return hex([v(h + 1 / 3) * 255, v(h) * 255, v(h - 1 / 3) * 255]);
    }

    function withLightness(c, l) {
        var hls = toHls(c);
        return fromHls(hls[0], Math.max(0, Math.min(1, l)), hls[2]);
    }

    function readable(c, against, lighter) {
        function ok(x) {
            return against.every(function (other) { return contrast(x, other) >= RATIO; });
        }
        if (ok(c)) return c;
        var start = toHls(c)[1];
        for (var step = 1; step <= 100; step++) {
            var candidate = withLightness(c, lighter ? start + step / 100 : start - step / 100);
            if (ok(candidate)) return candidate;
        }
        return lighter ? WHITE : '#000000';
    }

    function format(text, values) {
        return text.replace(/%\((\w+)\)s/g, function (all, name) { return values[name]; });
    }

    function init() {
        var samples = document.getElementById('appearance-samples');
        var brandField = document.getElementById('id_THEME_BRAND_COLOR');
        var accentField = document.getElementById('id_THEME_ACCENT_COLOR');
        if (!samples || !brandField || !accentField) return;
        var backgroundField = document.getElementById('id_THEME_BACKGROUND');
        var fontField = document.getElementById('id_THEME_FONT');
        var report = document.getElementById('appearance-contrast');
        var styleButtons = document.querySelectorAll('.appearance-style-use');
        var styleField = document.getElementById('id_THEME_STYLE');
        var widthField = document.getElementById('id_THEME_PAGE_WIDTH');
        var themeField = document.getElementById('id_DEFAULT_THEME');
        var defaults = {brand: samples.getAttribute('data-default-brand'), accent: samples.getAttribute('data-default-accent')};
        var fonts = {};
        try {
            fonts = JSON.parse(samples.getAttribute('data-fonts') || '{}');
        } catch (e) { /* the system font */ }

        function colour(field, fallback) {
            return /^#[0-9a-f]{6}$/i.test(field.value) ? field.value.toLowerCase() : fallback;
        }

        function update() {
            var brand = colour(brandField, defaults.brand), accent = colour(accentField, defaults.accent);
            var custom = brand !== defaults.brand;
            var lightBrand = readable(brand, [WHITE, LIGHT_BACKGROUND]);
            var accentButton = readable(accent, [WHITE]);
            var background = backgroundField ? backgroundField.value : 'default';
            var light = {
                brand: lightBrand, button: lightBrand, accent: accentButton,
                soft: custom ? mix(brand, WHITE, 0.9) : SKIN.light.soft,
                background: background === 'white' ? WHITE : (background === 'tinted' ? mix(brand, WHITE, 0.955) : LIGHT_BACKGROUND)
            };
            var dark = {
                brand: custom ? readable(brand, [DARK_SURFACE, DARK_BACKGROUND], true) : SKIN.dark.link,
                button: custom ? readable(brand, [WHITE]) : SKIN.dark.button,
                accent: accent !== defaults.accent ? accentButton : SKIN.dark.accent,
                soft: custom ? mix(brand, DARK_BACKGROUND, 0.8) : SKIN.dark.soft,
                background: DARK_BACKGROUND
            };
            var font = (fontField && fonts[fontField.value]) || '';
            [['light', light], ['dark', dark]].forEach(function (pair) {
                var sample = samples.querySelector('[data-theme-sample="' + pair[0] + '"]');
                if (!sample) return;
                Object.keys(pair[1]).forEach(function (name) {
                    sample.style.setProperty('--sample-' + name, pair[1][name]);
                });
                if (font) sample.style.setProperty('--sample-font', font);
                else sample.style.removeProperty('--sample-font');
            });

            Array.prototype.forEach.call(styleButtons, function (button) {
                var on = !!styleField && button.getAttribute('data-style') === styleField.value;
                button.setAttribute('aria-pressed', on ? 'true' : 'false');
            });

            if (report) {
                var lines = [];
                [['brand', brand, lightBrand], ['accent', accent, accentButton]].forEach(function (item) {
                    var ratio = contrast(item[2], WHITE).toFixed(1);
                    var line = format(report.getAttribute('data-' + item[0] + '-text'), {ratio: ratio});
                    if (item[1] !== item[2]) {
                        line += ' ' + format(report.getAttribute('data-adjusted-text'), {color: item[2]});
                    } else {
                        line += ' ✔ ' + report.getAttribute('data-ok-text');
                    }
                    lines.push(line);
                });
                report.textContent = '';
                lines.forEach(function (text) {
                    var li = document.createElement('li');
                    li.textContent = text;
                    report.appendChild(li);
                });
            }
        }

        // Fills the fields in from a style's button, as if typed (the
        // admin page counts them as unsaved changes).
        function set(field, value) {
            if (!field || !value || field.value === value) return;
            field.value = value;
            field.dispatchEvent(new Event('change', {bubbles: true}));
        }
        function applyStyle(button) {
            set(styleField, button.getAttribute('data-style'));
            set(brandField, button.getAttribute('data-brand'));
            set(accentField, button.getAttribute('data-accent'));
            set(backgroundField, button.getAttribute('data-background'));
            set(fontField, button.getAttribute('data-font'));
            set(widthField, button.getAttribute('data-width'));
            set(themeField, button.getAttribute('data-theme'));
            update();
        }
        Array.prototype.forEach.call(styleButtons, function (button) {
            button.addEventListener('click', function () { applyStyle(button); });
        });
        if (styleField) {
            styleField.addEventListener('change', function () {
                var button = document.querySelector('.appearance-style-use[data-style="' + styleField.value + '"]');
                if (button) applyStyle(button);
                update();
            });
        }
        [brandField, accentField, backgroundField, fontField].forEach(function (field) {
            if (!field) return;
            field.addEventListener('input', update);
            field.addEventListener('change', update);
        });
        update();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
