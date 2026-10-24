"""Draws the overlay with Pillow: the classic card and the arc-reactor HUD.

Everything is rendered to an RGBA image that LayeredWindow puts on screen, so edges,
glows and shadows are smooth against whatever app is underneath.
"""
import functools
import math
from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import winapi
from core import fmt_countdown, fmt_time, panel_style, split_bosses
from effects import Effects

SS = 3  # supersampling factor for shapes


# ---- colour helpers ---------------------------------------------------------

def hex_rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def with_alpha(rgb, alpha):
    return (*rgb, max(0, min(255, round(alpha * 255))))


@functools.lru_cache(maxsize=256)
def fade_table(alpha):
    """A lookup table that scales a mask's values by `alpha` (cached: building it is the slow part)."""
    return [round(v * alpha) for v in range(256)]


def colorize(mask, rgb, alpha=1.0):
    layer = Image.new("RGBA", mask.size, (*rgb, 0))
    layer.putalpha(mask if alpha >= 1 else mask.point(fade_table(round(alpha, 3))))
    return layer


def aa_mask(size, draw):
    """An antialiased L mask: `draw(ImageDraw, scale)` paints at SS x size, then it's shrunk."""
    w, h = size
    big = Image.new("L", (w * SS, h * SS), 0)
    draw(ImageDraw.Draw(big), SS)
    return big.resize(size, Image.LANCZOS)


# ---- fonts ------------------------------------------------------------------

class FontBook:
    """Pillow fonts by Windows family name, so any installed font works (Adobe Fonts too)."""

    def __init__(self):
        self._files = {}
        self._fonts = {}

    def clear(self):
        self._files.clear()
        self._fonts.clear()

    def get(self, family, size, bold=False):
        key = (family, max(6, round(size)), bold)
        if key not in self._fonts:
            self._fonts[key] = self._load(*key)
        return self._fonts[key]

    def _load(self, family, size, bold):
        if (family, bold) not in self._files:
            self._files[(family, bold)] = self._find(family, bold)
        found = self._files[(family, bold)]
        if found:
            data, index, variation = found
            try:
                font = ImageFont.truetype(BytesIO(data), size, index=index)
                if variation:
                    font.set_variation_by_name(variation)
                return font
            except (OSError, ValueError):
                pass
        for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        return ImageFont.load_default(size)

    @staticmethod
    def _find(family, bold):
        found = winapi.font_bytes(family, bold)
        if not found:
            return None
        data, collection = found
        index = 0
        if collection:
            best = None
            for i in range(64):
                try:
                    name, style = ImageFont.truetype(BytesIO(data), 12, index=i).getname()
                except OSError:
                    break
                if family.lower().startswith(name.lower()):
                    if ("bold" in style.lower()) == bold:
                        best = i
                        break
                    best = i if best is None else best
            index = best or 0

        # Variable fonts (e.g. Segoe UI Variable) hold every weight in one file.
        variation = None
        try:
            font = ImageFont.truetype(BytesIO(data), 12, index=index)
            names = [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
        except Exception:
            names = []
        if names:
            base = font.getname()[0]
            style = family[len(base):].strip() if family.lower().startswith(base.lower()) else ""
            wanted = [f"{style} Bold".strip(), "Bold"] if bold else [style or "Regular", "Regular"]
            variation = next((n for w in wanted for n in names if n.lower() == w.lower()), None)
        return data, index, variation


def fit(book, family, size, bold, text, max_w):
    """The largest font (down to 60% of `size`) that fits `text` in `max_w`."""
    s = size
    while s > size * 0.6:
        font = book.get(family, s, bold)
        if font.getlength(text) <= max_w:
            return font
        s *= 0.94
    return book.get(family, size * 0.6, bold)


def ellipsize(font, text, max_w):
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def labelled(label, text, sep=" · "):
    """'Next event · 10:50 AM', or just the time when the label is blank."""
    return f"{label.strip()}{sep}{text}" if label.strip() else text


def cap_height(font):
    return -font.getbbox("0", anchor="ls")[1]


def tracked_width(font, text, tracking):
    return sum(font.getlength(c) for c in text) + tracking * (len(text) - 1)


class Ink:
    """Text and shapes drawn as per-colour masks, then tinted: no dark fringes on transparency."""

    def __init__(self, size):
        self.size = size
        self.layers = []

    def mask(self, rgba):
        if self.layers and self.layers[-1][0] == rgba:
            return self.layers[-1][1]
        mask = Image.new("L", self.size, 0)
        self.layers.append((rgba, mask))
        return mask

    def text(self, xy, text, font, rgba, anchor="ls", tracking=0):
        draw = ImageDraw.Draw(self.mask(rgba))
        if not tracking:
            draw.text(xy, text, font=font, fill=255, anchor=anchor)
            return
        x, y = xy
        width = tracked_width(font, text, tracking)
        x -= {"l": 0, "m": width / 2, "r": width}[anchor[0]]
        for c in text:
            draw.text((x, y), c, font=font, fill=255, anchor="l" + anchor[1])
            x += font.getlength(c) + tracking

    def paste(self, rgba, mask, xy):
        self.mask(rgba).paste(mask, xy, mask)

    def onto(self, image, offset=(0, 0)):
        for rgba, mask in self.layers:
            # Text covers a small part of the panel, so only colour and blend the part that has ink.
            box = mask.getbbox()
            if box:
                layer = colorize(mask.crop(box), rgba[:3], rgba[3] / 255)
                image.alpha_composite(layer, (offset[0] + box[0], offset[1] + box[1]))


def pill_mask(w, h):
    return aa_mask((max(1, round(w)), max(1, round(h))),
                   lambda d, s: d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), h * s / 2, fill=255))


def dot_mask(r):
    size = max(1, round(r * 2))
    return aa_mask((size, size), lambda d, s: d.ellipse((0, 0, size * s - 1, size * s - 1), fill=255))


def pill_buttons(ink, specs, font, x, y, w, h, gap):
    """Side-by-side pill buttons filling width `w`. specs: [(action, label, background rgba, text rgba)].
    Returns their click areas: [(action, (x0, y0, x1, y1))]."""
    bw = (w - gap * (len(specs) - 1)) / len(specs)
    areas = []
    for i, (action, text, background, color) in enumerate(specs):
        bx = x + i * (bw + gap)
        ink.paste(background, pill_mask(bw, h), (round(bx), round(y)))
        ink.text((bx + bw / 2, y + h / 2 + cap_height(font) / 2), text, font, color, "ms")
        areas.append((action, (round(bx), round(y), round(bx + bw), round(y + h))))
    return areas


class Theme:
    def __init__(self, s):
        self.bg, self.fg, self.dim, self.accent, self.warn, self.live = (
            hex_rgb(s[k]) for k in ("bg", "fg", "dim", "accent", "warn", "live"))


POSITION_KEYS = ("x", "y", "list_x", "list_y", "stopwatch_x", "stopwatch_y", "notify_x", "notify_y")


def signature(s):
    """Everything in the settings that can change what a panel looks like."""
    return repr(sorted((key, value) for key, value in s.items() if key not in POSITION_KEYS))


# ---- box panels (the card and the upcoming list) ----------------------------

class PanelPainter:
    """The rounded box behind the card and the list: shadow, fill (solid or animated), border."""

    def __init__(self):
        self.effects = Effects()
        self._parts = {}

    def parts(self, s, W, H, m, k):
        key = (W, H, m, k, s["fg"], s["accent"], s["bg_opacity"])
        if key not in self._parts:
            if len(self._parts) > 8:
                self._parts.clear()
            t = Theme(s)
            r = round(18 * k)
            shadow = Image.new("RGBA", (W + 2 * m, H + 2 * m), (0, 0, 0, 0))
            blur = Image.new("L", shadow.size, 0)
            ImageDraw.Draw(blur).rounded_rectangle((m, m + 6 * k, m + W, m + H + 6 * k), r,
                                                   fill=round(170 * s["bg_opacity"]))
            shadow.putalpha(blur.filter(ImageFilter.GaussianBlur(12 * k)))

            shape = aa_mask((W, H), lambda d, sc: d.rounded_rectangle((0, 0, W * sc - 1, H * sc - 1), r * sc, fill=255))
            fill_mask = shape.point(lambda v: round(v * s["bg_opacity"]))

            deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            border = aa_mask((W, H), lambda d, sc: d.rounded_rectangle(
                (0, 0, W * sc - 1, H * sc - 1), r * sc, outline=255, width=round(max(1, k) * sc)))
            deco.alpha_composite(colorize(border, t.fg, 0.10))
            # A thin accent highlight along the top edge.
            line = aa_mask((W, H), lambda d, sc: d.rounded_rectangle(
                (W * sc * 0.18, 0, W * sc * 0.82, round(1.5 * k * sc)), k * sc, fill=255))
            deco.alpha_composite(colorize(line, t.accent, 0.85))
            glow = Image.new("L", (W, H), 0)
            ImageDraw.Draw(glow).rectangle((W * 0.2, 0, W * 0.8, 3 * k), fill=255)
            deco.alpha_composite(colorize(glow.filter(ImageFilter.GaussianBlur(6 * k)), t.accent, 0.5))
            self._parts[key] = (shadow, fill_mask, deco)
        return self._parts[key]

    def paint(self, s, W, H, m, k, t):
        shadow, fill_mask, deco = self.parts(s, W, H, m, k)
        panel = self.effects.frame(s, (W, H), k, t).convert("RGBA")
        panel.putalpha(fill_mask)
        img = shadow.copy()
        img.alpha_composite(panel, (m, m))
        img.alpha_composite(deco, (m, m))
        return img


def upcoming_row(ink, s, t, x0, x1, base, col, tm, bosses, row_font, time_font):
    ink.text((x0, base), fmt_time(tm, s["clock_24h"]), time_font, with_alpha(mix(t.dim, t.accent, 0.35), 1))
    ink.text((x0 + col, base), ellipsize(row_font, bosses.replace(" & ", " · "), x1 - x0 - col), row_font,
             with_alpha(t.fg, 0.8))


# ---- classic card -----------------------------------------------------------

class CardRenderer:
    def __init__(self, fonts, painter):
        self.fonts = fonts
        self.painter = painter
        self._content = (None, None)

    def render(self, s, st, k, t, with_list):
        W, H, m, content = self.content(s, st, k, with_list)
        img = self.painter.paint(s, W, H, m, k, t)
        img.alpha_composite(content)
        return img

    def content(self, s, st, k, with_list):
        """All the text, laid out once a second: (panel width, height, shadow margin, RGBA layer)."""
        key = (st["second"], st["warn"], k, with_list, signature(s))
        if self._content[0] == key:
            return self._content[1]
        t = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        pad = round(20 * k)
        W = round(s["width"] * k)
        inner = W - 2 * pad
        m = round(24 * k)
        items = []  # (height, draw(ink, x, y))

        label, small = F(8.5, True), F(9)
        track = 1.6 * k

        title = s["title"].strip().upper()
        clock = fmt_time(st["now"], s["clock_24h"], True) if s["show_clock"] else ""

        def header(ink, x, y):
            base = y + cap_height(label)
            if title:
                room = inner - 11 * k - (small.getlength(clock) + 12 * k if clock else 0)
                ink.paste(with_alpha(t.accent, 1), dot_mask(3 * k), (round(x), round(base - cap_height(label) / 2 - 3 * k)))
                ink.text((x + 11 * k, base), ellipsize(label, title, room - len(title) * track), label,
                         with_alpha(t.dim, 1), tracking=track)
            if clock:
                ink.text((x + inner, base), clock, small, with_alpha(t.dim, 1), "rs")
        if title or clock:
            items.append((cap_height(label), header))
            items.append((16 * k, None))

        if st["just"]:
            bosses, since = st["just"]
            chip_font = F(8, True)
            chip_text = labelled(s["past_label"], f"{fmt_countdown(int(since))} ago", " ").upper()
            chip_w = tracked_width(chip_font, chip_text, 1.2 * k) + 30 * k
            chip_h = 22 * k

            def chip(ink, x, y, text=chip_text):
                ink.paste(with_alpha(t.live, 0.16), pill_mask(chip_w, chip_h), (round(x), round(y)))
                ink.paste(with_alpha(t.live, 1), dot_mask(3 * k), (round(x + 10 * k), round(y + chip_h / 2 - 3 * k)))
                ink.text((x + 20 * k, y + chip_h / 2 + cap_height(chip_font) / 2), text, chip_font,
                         with_alpha(t.live, 1), tracking=1.2 * k)
            items.append((chip_h, chip))
            items.append((8 * k, None))
            prev_font = F(10)
            items.append((prev_font.getmetrics()[0], lambda ink, x, y, f=prev_font, b=bosses: ink.text(
                (x, y + f.getmetrics()[0]), ellipsize(f, b.replace(" & ", " · "), inner), f, with_alpha(t.dim, 1))))
            items.append((18 * k, None))

        if st["next"]:
            next_time, bosses = st["next"]
            text = labelled(s["next_label"], fmt_time(next_time, s["clock_24h"])).upper()
            items.append((cap_height(label), lambda ink, x, y: ink.text(
                (x, y + cap_height(label)), text, label, with_alpha(t.dim, 1), tracking=track)))
            items.append((10 * k, None))
            for line in split_bosses(bosses):
                font = fit(self.fonts, s["font"], 17 * k, True, line, inner)
                asc = font.getmetrics()[0]
                items.append((asc + 3 * k, lambda ink, x, y, f=font, l=line, a=asc: ink.text(
                    (x, y + a), ellipsize(f, l, inner), f, with_alpha(t.fg, 1))))
            big = F(46, True)
            color = t.warn if st["warn"] else t.fg
            items.append((10 * k, None))
            items.append((cap_height(big), lambda ink, x, y: ink.text(
                (x - 2 * k, y + cap_height(big)), fmt_countdown(st["secs"]), big, with_alpha(color, 1))))
            items.append((16 * k, None))
            bar_h = 4 * k
            progress = 1 - st["frac_left"]

            def bar(ink, x, y):
                ink.paste(with_alpha(t.fg, 0.10), pill_mask(inner, bar_h), (round(x), round(y)))
                if progress > 0:
                    ink.paste(with_alpha(t.warn if st["warn"] else t.accent, 1),
                              pill_mask(max(bar_h, inner * progress), bar_h), (round(x), round(y)))
            items.append((bar_h, bar))
        else:
            items.append((F(14, True).getmetrics()[0], lambda ink, x, y: ink.text(
                (x, y + F(14, True).getmetrics()[0]), "Nothing scheduled", F(14, True), with_alpha(t.fg, 1))))
            items.append((6 * k, None))
            items.append((small.getmetrics()[0], lambda ink, x, y: ink.text(
                (x, y + small.getmetrics()[0]), "Right-click to open Settings", small, with_alpha(t.dim, 1))))

        if with_list and st["upcoming"]:
            items.append((20 * k, None))
            row_font, time_font = F(10), F(9.5, True)
            col = max(time_font.getlength(fmt_time(tm, s["clock_24h"])) for tm, _ in st["upcoming"]) + 12 * k
            for tm, bosses in st["upcoming"]:
                items.append((row_font.getmetrics()[0] + 9 * k, lambda ink, x, y, tm=tm, b=bosses: upcoming_row(
                    ink, s, t, x, x + inner, y + row_font.getmetrics()[0], col, tm, b, row_font, time_font)))

        H = round(2 * pad + sum(h for h, _ in items))
        layer = Image.new("RGBA", (W + 2 * m, H + 2 * m), (0, 0, 0, 0))
        ink = Ink(layer.size)
        y = m + pad
        for h, draw in items:
            if draw:
                draw(ink, m + pad, y)
            y += h
        ink.onto(layer)
        self._content = (key, (W, H, m, layer))
        return self._content[1]


# ---- upcoming list (its own panel) ------------------------------------------

class ListRenderer:
    def __init__(self, fonts, painter):
        self.fonts = fonts
        self.painter = painter
        self._content = (None, None)

    def render(self, s, st, k, t, with_just):
        content = self.content(s, st, k, with_just)
        if content is None:
            return None
        W, H, m, layer = content
        img = self.painter.paint(s, W, H, m, k, t)
        img.alpha_composite(layer)
        return img

    def content(self, s, st, k, with_just):
        key = (st["second"], k, with_just, signature(s))
        if self._content[0] == key:
            return self._content[1]
        just = st["just"] if with_just else None
        if not just and not st["upcoming"]:
            self._content = (key, None)
            return None
        t = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        pad = round(16 * k)
        W = round(s["width"] * k)
        m = round(24 * k)
        row_h = round(22 * k)
        label = F(8.5, True)
        heading = s["list_label"].strip().upper()
        head_h = cap_height(label) + 12 * k if heading else 0
        rows = (1 if just else 0) + len(st["upcoming"])
        H = round(2 * pad + head_h + rows * row_h - 4 * k)

        layer = Image.new("RGBA", (W + 2 * m, H + 2 * m), (0, 0, 0, 0))
        ink = Ink(layer.size)
        x0, x1 = m + pad + 2 * k, m + W - pad
        y = m + pad
        if heading:
            ink.text((x0, y + cap_height(label)), ellipsize(label, heading, x1 - x0), label, with_alpha(t.dim, 1),
                     tracking=1.6 * k)
            y += head_h
        row_font, time_font = F(10), F(9.5, True)
        if just:
            bosses, since = just
            base = y + row_h / 2 + cap_height(row_font) / 2
            ink.paste(with_alpha(t.live, 1), dot_mask(3 * k), (round(x0), round(base - cap_height(row_font) / 2 - 3 * k)))
            tag = labelled(s["past_label"], f"{fmt_countdown(int(since))} ago", " ")
            ink.text((x0 + 12 * k, base), tag, time_font, with_alpha(t.live, 1))
            col = x0 + 12 * k + time_font.getlength(tag) + 10 * k
            ink.text((col, base), ellipsize(row_font, bosses.replace(" & ", " · "), x1 - col), row_font,
                     with_alpha(t.live, 0.9))
            y += row_h
        if st["upcoming"]:
            col = max(time_font.getlength(fmt_time(tm, s["clock_24h"])) for tm, _ in st["upcoming"]) + 12 * k
            for tm, bosses in st["upcoming"]:
                upcoming_row(ink, s, t, x0, x1, y + row_h / 2 + cap_height(row_font) / 2, col, tm, bosses,
                             row_font, time_font)
                y += row_h
        ink.onto(layer)
        self._content = (key, (W, H, m, layer))
        return self._content[1]


# ---- arc reactor ------------------------------------------------------------

class ReactorRenderer:
    FRAMES = 72
    SPIN_SECONDS = 6.0  # time for the rings to turn one symmetry step (15 degrees)

    def __init__(self, fonts):
        self.fonts = fonts
        # Several panels can be arcs at once (timer, stopwatch), so keep a few looks and sizes.
        self._static = {}
        self._rings = {}
        self._dynamic = (None, None)

    @staticmethod
    def geometry(k):
        D = round(300 * k)
        g = round(34 * k)
        return D, g, D + 2 * g

    def static(self, s, k):
        key = (k, s["bg"], s["fg"], s["accent"], s["bg_opacity"])
        if key in self._static:
            return self._static[key]
        t = Theme(s)
        D, g, C = self.geometry(k)
        R = D / 2
        c = C / 2
        img = Image.new("RGBA", (C, C), (0, 0, 0, 0))

        def ring(radius, width):
            return lambda d, sc: d.ellipse(((c - radius) * sc, (c - radius) * sc, (c + radius) * sc, (c + radius) * sc),
                                           outline=255, width=max(1, round(width * sc)))

        # Outer glow.
        halo = Image.new("L", (C, C), 0)
        ImageDraw.Draw(halo).ellipse((c - R, c - R, c + R, c + R), outline=255, width=round(5 * k))
        img.alpha_composite(colorize(halo.filter(ImageFilter.GaussianBlur(14 * k)), t.accent, 0.55))
        img.alpha_composite(colorize(halo.filter(ImageFilter.GaussianBlur(5 * k)), t.accent, 0.35))

        # Disc with a soft radial gradient.
        disc = aa_mask((C, C), lambda d, sc: d.ellipse(((c - R) * sc, (c - R) * sc, (c + R) * sc, (c + R) * sc), fill=255))
        radial = Image.radial_gradient("L").resize((D, D))
        canvas = Image.new("L", (C, C), 255)
        canvas.paste(radial, (g, g))
        fill = Image.composite(Image.new("RGB", (C, C), mix(t.bg, (0, 0, 0), 0.35)),
                               Image.new("RGB", (C, C), mix(t.bg, t.accent, 0.10)), canvas).convert("RGBA")
        fill.putalpha(disc.point(lambda v: round(v * s["bg_opacity"])))
        img.alpha_composite(fill, (0, 0))

        img.alpha_composite(colorize(aa_mask((C, C), ring(R - k, 1.6 * k)), t.accent, 0.9))
        img.alpha_composite(colorize(aa_mask((C, C), ring(0.895 * R, 7 * k)), t.fg, 0.07))

        def ticks(major):
            def draw(d, sc):
                for i in range(60):
                    if (i % 5 == 0) != major:
                        continue
                    a = math.radians(i * 6 - 90)
                    r0, r1 = (0.775 * R, 0.84 * R) if major else (0.80 * R, 0.84 * R)
                    d.line([((c + r0 * math.cos(a)) * sc, (c + r0 * math.sin(a)) * sc),
                            ((c + r1 * math.cos(a)) * sc, (c + r1 * math.sin(a)) * sc)],
                           fill=255, width=max(1, round((2 if major else 1) * k * sc)))
            return draw
        img.alpha_composite(colorize(aa_mask((C, C), ticks(False)), t.fg, 0.22))
        img.alpha_composite(colorize(aa_mask((C, C), ticks(True)), t.accent, 0.9))

        if len(self._static) >= 4:
            self._static.pop(next(iter(self._static)))
        self._static[key] = img
        return img

    def ring_frame(self, k, index):
        """One rotating-ring mask. The spin repeats every 15 degrees, so FRAMES of them cover it;
        each is made the first time it's needed and then reused."""
        if k not in self._rings:
            if len(self._rings) >= 3:
                self._rings.pop(next(iter(self._rings)))
            self._rings[k] = (self.ring_masks(k), {})
        (outer, inner, c), frames = self._rings[k]
        if index not in frames:
            angle = 15 * index / self.FRAMES
            frames[index] = ImageChops.lighter(outer.rotate(-angle, Image.BILINEAR, center=(c, c)),
                                               inner.rotate(angle, Image.BILINEAR, center=(c, c)))
        return frames[index]

    def ring_masks(self, k):
        D, g, C = self.geometry(k)
        R = D / 2
        c = C / 2

        def arcs(radius, width, pattern):
            def draw(d, sc):
                box = ((c - radius) * sc, (c - radius) * sc, (c + radius) * sc, (c + radius) * sc)
                for step in range(24):
                    for start, length in pattern:
                        a = step * 15 + start
                        d.arc(box, a, a + length, fill=255, width=max(1, round(width * sc)))
            return draw

        outer = aa_mask((C, C), arcs(0.955 * R, 3 * k, [(0, 9), (11, 2)]))
        inner = aa_mask((C, C), arcs(0.735 * R, 1.3 * k, [(0, 5)])).point(lambda v: v // 2)
        return outer, inner, c

    def dynamic(self, s, st, k):
        """The progress arc and all text; changes once a second."""
        key = (st["second"], st["warn"], k, signature(s))
        if self._dynamic[0] == key:
            return self._dynamic[1]
        t = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        D, g, C = self.geometry(k)
        R = D / 2
        c = C / 2
        img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
        color = t.warn if st["warn"] else t.accent

        if st["next"]:
            frac = max(0.0, min(1.0, st["frac_left"]))
            radius, width = 0.895 * R, 7 * k
            box = lambda sc: ((c - radius) * sc, (c - radius) * sc, (c + radius) * sc, (c + radius) * sc)  # noqa: E731
            end = math.radians(-90 + 360 * frac)
            head = (c + radius * math.cos(end), c + radius * math.sin(end))

            def arc(d, sc):
                if frac <= 0:
                    return
                d.arc(box(sc), -90, -90 + 360 * frac, fill=255, width=round(width * sc))
                for a in (math.radians(-90), end):  # round caps
                    x, y = c + radius * math.cos(a), c + radius * math.sin(a)
                    d.ellipse(((x - width / 2) * sc, (y - width / 2) * sc, (x + width / 2) * sc, (y + width / 2) * sc), fill=255)
            mask = aa_mask((C, C), arc)
            img.alpha_composite(colorize(mask.filter(ImageFilter.GaussianBlur(7 * k)), color, 0.75))
            img.alpha_composite(colorize(mask, color))
            if frac > 0:
                dot = dot_mask(2.6 * k)
                img.alpha_composite(colorize(dot, (255, 255, 255)),
                                    (round(head[0] - dot.width / 2), round(head[1] - dot.height / 2)))

        ink = Ink(img.size)
        glow = Ink(img.size)
        label, small = F(8.5, True), F(9)
        max_w = 0.58 * D
        if st["next"]:
            next_time, bosses = st["next"]
            lines = split_bosses(bosses)
            boss_fonts = [fit(self.fonts, s["font"], 14 * k, True, line, max_w) for line in lines]
            big = fit(self.fonts, s["font"], 50 * k, True, fmt_countdown(st["secs"]), 0.62 * D)
            heights = [cap_height(label), 10 * k, *[f.getmetrics()[0] + 2 * k for f in boss_fonts], 12 * k,
                       cap_height(big)]
            if s["show_clock"]:
                heights += [14 * k, cap_height(small)]
            y = c - sum(heights) / 2
            ink.text((c, y + cap_height(label)), labelled(s["next_label"], fmt_time(next_time, s["clock_24h"])).upper(),
                     label, with_alpha(t.dim, 1), "ms", 1.6 * k)
            title = s["title"].strip().upper()
            if title:
                # Up in the band between the text and the tick ring.
                ink.text((c, c - 0.6 * R), ellipsize(label, title, 0.8 * R), label, with_alpha(t.accent, 0.9), "ms", 1.6 * k)
            y += cap_height(label) + 10 * k
            for font, line in zip(boss_fonts, lines):
                y += font.getmetrics()[0]
                ink.text((c, y), ellipsize(font, line, max_w), font, with_alpha(t.fg, 1), "ms")
                y += 2 * k
            y += 12 * k + cap_height(big)
            text_color = t.warn if st["warn"] else t.fg
            glow.text((c, y), fmt_countdown(st["secs"]), big, with_alpha(color, 1), "ms")
            ink.text((c, y), fmt_countdown(st["secs"]), big, with_alpha(text_color, 1), "ms")
            if s["show_clock"]:
                y += 14 * k + cap_height(small)
                ink.text((c, y), fmt_time(st["now"], s["clock_24h"], True), small, with_alpha(t.dim, 1), "ms")
        else:
            ink.text((c, c), "Nothing scheduled", F(16, True), with_alpha(t.fg, 1), "mm")
            ink.text((c, c + 20 * k), "Right-click → Settings", small, with_alpha(t.dim, 1), "mm")

        for rgba, mask in glow.layers:
            img.alpha_composite(colorize(mask.filter(ImageFilter.GaussianBlur(9 * k)), rgba[:3], 0.55))
        ink.onto(img)
        self._dynamic = (key, img)
        return img

    def render(self, s, st, k, t):
        img = self.static(s, k).copy()
        index = int((t % self.SPIN_SECONDS) / self.SPIN_SECONDS * self.FRAMES) if s["animate"] else 0
        img.alpha_composite(colorize(self.ring_frame(k, index), Theme(s).accent, 0.8))
        img.alpha_composite(self.dynamic(s, st, k))
        return img


# ---- state ------------------------------------------------------------------

def build_state(now, upcoming, prev, s, max_upcoming):
    """Everything the renderers need, from the schedule maths."""
    st = {"now": now, "second": int(now.timestamp()), "next": None, "secs": 0, "frac_left": 0.0,
          "warn": False, "just": None, "upcoming": []}
    if prev and (now - prev[0]).total_seconds() < s["just_spawned_seconds"]:
        st["just"] = (prev[1], (now - prev[0]).total_seconds())
    if upcoming:
        next_time, bosses = upcoming[0]
        remaining = (next_time - now).total_seconds()
        period = (next_time - prev[0]).total_seconds() if prev else 3600
        st.update(next=(next_time, bosses), remaining=remaining, secs=math.ceil(remaining),
                  frac_left=remaining / period if period > 0 else 0,
                  warn=bool(s["warn_seconds"]) and remaining <= s["warn_seconds"],
                  upcoming=upcoming[1:1 + min(s["upcoming"], max_upcoming)])
    return st


def sample_state(s):
    """A fixed example for settings previews: 3:48 to go, 1:12 after the last event."""
    now = datetime(2026, 1, 1, 10, 46, 12)
    nxt = datetime(2026, 1, 1, 10, 50)
    names = [e["bosses"] for e in s["schedule"]] or ["Example event"]
    upcoming = [(nxt + timedelta(minutes=5 * i), names[(i + 10) % len(names)]) for i in range(1 + 12)]
    prev = (datetime(2026, 1, 1, 10, 45), names[9 % len(names)])
    return build_state(now, upcoming, prev, dict(s, just_spawned_seconds=120), 12)


def logo(size, accent="#3ad0ff"):
    """The app icon: a tiny arc reactor. Used for the .ico, the tray and window icons."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    accent = hex_rgb(accent)
    glow = Image.new("L", (s, s), 0)
    ImageDraw.Draw(glow).ellipse((s * .12, s * .12, s * .88, s * .88), outline=255, width=max(1, s // 12))
    img.alpha_composite(colorize(glow.filter(ImageFilter.GaussianBlur(s / 14)), accent, 0.8))
    img.alpha_composite(colorize(aa_mask((s, s), lambda d, k: d.ellipse(
        (s * .14 * k, s * .14 * k, s * .86 * k, s * .86 * k), fill=255)), (10, 16, 24)))
    img.alpha_composite(colorize(aa_mask((s, s), lambda d, k: d.arc(
        (s * .2 * k, s * .2 * k, s * .8 * k, s * .8 * k), -90, 180, fill=255, width=round(s * .09 * k))), accent))
    img.alpha_composite(colorize(aa_mask((s, s), lambda d, k: d.ellipse(
        (s * .14 * k, s * .14 * k, s * .86 * k, s * .86 * k), outline=255, width=max(1, round(s * .03 * k)))), accent, 0.7))
    img.alpha_composite(colorize(aa_mask((s, s), lambda d, k: d.ellipse(
        (s * .4 * k, s * .4 * k, s * .6 * k, s * .6 * k), fill=255)), (230, 250, 255)))
    return img


class Renderer:
    """Draws every panel. Each method takes the full settings and applies that panel's own style."""

    def __init__(self):
        from notifications import NotificationRenderer
        from stopwatch import StopwatchRenderer
        self.fonts = FontBook()
        self.painter = PanelPainter()
        self.card = CardRenderer(self.fonts, self.painter)
        self.reactor = ReactorRenderer(self.fonts)
        self.list = ListRenderer(self.fonts, self.painter)
        self.watch = StopwatchRenderer(self.fonts, self.painter, self.reactor)
        self.notices = NotificationRenderer(self.fonts, self.painter, self.reactor)

    @staticmethod
    def list_is_separate(settings):
        """Is the upcoming list its own panel? Always with the arc timer; optional with the card."""
        return settings["styles"]["timer"]["shape"] == "reactor" or settings["split_list"]

    def timer(self, settings, st, k, t=0.0):
        s = panel_style(settings, "timer")
        if s["shape"] == "reactor":
            return self.reactor.render(s, st, k * s["scale"], t)
        with_list = settings["show_list"] and not self.list_is_separate(settings)
        return self.card.render(s, st, k * s["scale"], t, with_list=with_list)

    def list_panel(self, settings, st, k, t=0.0):
        """The separate list panel, or None when it isn't separate or has nothing to show."""
        if not self.list_is_separate(settings):
            return None
        s = panel_style(settings, "list")
        with_just = settings["styles"]["timer"]["shape"] == "reactor"
        return self.list.render(s, st, k * s["scale"], t, with_just=with_just)

    def stopwatch(self, settings, watch, k, t=0.0):
        """(image, buttons): buttons are [(action, (x0, y0, x1, y1))] in image pixels."""
        s = panel_style(settings, "stopwatch")
        return self.watch.render(s, watch, k * s["scale"], t)

    def notification(self, settings, notice, count, k, t=0.0):
        """(image, buttons) for the newest notification; `count` is how many are waiting in all."""
        s = panel_style(settings, "notification")
        return self.notices.render(s, notice, count, k * s["scale"], t)

    def animating(self, settings, watch):
        """Does anything on screen need redrawing every frame?"""
        styles = settings["styles"]

        def moving(name):
            style = styles[name]
            if not style["animate"]:
                return False
            return style["shape"] == "reactor" or self.painter.effects.is_animated(panel_style(settings, name))
        if settings["show_timer"] and moving("timer"):
            return True
        if settings["show_list"] and self.list_is_separate(settings) and moving("list"):
            return True
        return settings["show_stopwatch"] and (watch.running or moving("stopwatch"))

    def preview(self, settings, panel, st, watch, k):
        """A thumbnail for the settings window: the stopwatch, or the timer with its list under it."""
        if panel == "stopwatch":
            return self.stopwatch(settings, watch, k)[0]
        if panel == "notification":
            from notifications import sample_notice
            return self.notification(settings, sample_notice(datetime.now()), 1, k)[0]
        top = self.timer(settings, st, k)
        bottom = self.list_panel(settings, st, k) if settings["show_list"] else None
        if bottom is None:
            return top
        img = Image.new("RGBA", (max(top.width, bottom.width), top.height + bottom.height - round(30 * k)), (0, 0, 0, 0))
        img.alpha_composite(top, ((img.width - top.width) // 2, 0))
        img.alpha_composite(bottom, ((img.width - bottom.width) // 2, top.height - round(30 * k)))
        return img
