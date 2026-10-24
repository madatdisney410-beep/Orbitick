"""Overlay notifications for alarms and calendar reminders, drawn as a card or an arc.

A notice is a plain dict: kind ("alarm" or "event"), title, detail, at (datetime), source (the
alarm or event id), sound, volume, loop (alarms keep ringing until dismissed) and snooze (minutes).
"""
import math

from PIL import Image, ImageDraw, ImageFilter

from core import fmt_time
from render import Ink, Theme, cap_height, colorize, dot_mask, ellipsize, fit, pill_buttons, with_alpha

KIND_LABELS = {"alarm": "ALARM", "event": "REMINDER", "test": "PREVIEW"}
PULSE_STEPS = 16


def pulse(t, speed=1.1):
    """0..1, a slow breathing rhythm."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * speed * t)


def sample_notice(now):
    return {"kind": "test", "title": "Notification preview", "detail": "Drag this to where alarms should appear",
            "at": now, "source": None, "sound": "", "volume": 0.0, "loop": False, "snooze": 5}


class NotificationRenderer:
    def __init__(self, fonts, painter, reactor):
        self.fonts = fonts
        self.painter = painter
        self.reactor = reactor
        self._outlines = {}
        self._halos = {}
        self._arc_bases = {}  # disc + halo at each of PULSE_STEPS brightness levels

    def render(self, s, notice, count, k, t):
        if s["shape"] == "reactor":
            return self.arc(s, notice, count, k, t)
        return self.card(s, notice, count, k, t)

    def buttons(self, ink, th, notice, font, x, y, w, h, gap):
        specs = []
        if notice["snooze"]:
            specs.append(("snooze", f"Snooze {notice['snooze']} min", with_alpha(th.fg, 0.10), with_alpha(th.fg, 1)))
        specs.append(("dismiss", "Dismiss", with_alpha(th.accent, 0.95), (12, 16, 22, 255)))
        return pill_buttons(ink, specs, font, x, y, w, h, gap)

    # ---- card ----

    def outline(self, W, H, m, k):
        """A glowing edge around the card, faded in and out per frame for the pulse."""
        key = (W, H, m, k)
        if key not in self._outlines:
            if len(self._outlines) > 4:
                self._outlines.clear()
            r = round(18 * k)
            mask = Image.new("L", (W + 2 * m, H + 2 * m), 0)
            ImageDraw.Draw(mask).rounded_rectangle((m, m, m + W, m + H), r, outline=255, width=round(3 * k))
            self._outlines[key] = mask.filter(ImageFilter.GaussianBlur(6 * k))
        return self._outlines[key]

    def card(self, s, notice, count, k, t):
        th = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        pad, m = round(18 * k), round(24 * k)
        W = round(s["width"] * k)
        inner = W - 2 * pad
        label, small, detail_font, button_font = F(8.5, True), F(9), F(10), F(10, True)
        title_font = fit(self.fonts, s["font"], 19 * k, True, notice["title"], inner)
        button_h = round(34 * k)
        extra = cap_height(small) + 8 * k if count > 1 else 0
        H = round(2 * pad + cap_height(label) + 14 * k + title_font.getmetrics()[0] + 6 * k
                  + detail_font.getmetrics()[0] + extra + 16 * k + button_h)

        img = self.painter.paint(s, W, H, m, k, t)
        glow = colorize(self.outline(W, H, m, k), th.accent, 0.25 + 0.5 * pulse(t))
        img.alpha_composite(glow)
        ink = Ink(img.size)
        x, y = m + pad, m + pad
        base = y + cap_height(label)
        dot = dot_mask((2.6 + 1.2 * pulse(t)) * k)
        ink.paste(with_alpha(th.accent, 1), dot, (round(x + 3 * k - dot.width / 2), round(base - cap_height(label) / 2 - dot.height / 2)))
        ink.text((x + 12 * k, base), KIND_LABELS.get(notice["kind"], "NOTICE"), label, with_alpha(th.accent, 1), tracking=1.6 * k)
        ink.text((x + inner, base), fmt_time(notice["at"], s["clock_24h"]), small, with_alpha(th.dim, 1), "rs")
        y = base + 14 * k + title_font.getmetrics()[0]
        ink.text((x, y), ellipsize(title_font, notice["title"], inner), title_font, with_alpha(th.fg, 1))
        y += 6 * k + detail_font.getmetrics()[0]
        if notice["detail"]:
            ink.text((x, y), ellipsize(detail_font, notice["detail"], inner), detail_font, with_alpha(th.dim, 1))
        if count > 1:
            y += 8 * k + cap_height(small)
            ink.text((x, y), f"+{count - 1} more waiting", small, with_alpha(th.live, 1))
        y += 16 * k
        buttons = self.buttons(ink, th, notice, button_font, x, y, inner, button_h, 10 * k)
        ink.onto(img)
        return img, buttons

    # ---- arc ----

    def halo(self, k):
        if k not in self._halos:
            if len(self._halos) > 2:
                self._halos.clear()
            D, g, C = self.reactor.geometry(k)
            c, R = C / 2, D / 2
            mask = Image.new("L", (C, C), 0)
            ImageDraw.Draw(mask).ellipse((c - R, c - R, c + R, c + R), outline=255, width=round(8 * k))
            self._halos[k] = mask.filter(ImageFilter.GaussianBlur(16 * k))
        return self._halos[k]

    def arc(self, s, notice, count, k, t):
        th = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        reactor = self.reactor
        D, g, C = reactor.geometry(k)
        R, c = D / 2, C / 2
        level = round(pulse(t) * (PULSE_STEPS - 1))
        key = (k, level, s["bg"], s["fg"], s["accent"], s["bg_opacity"])
        if key not in self._arc_bases:
            if len(self._arc_bases) >= 2 * PULSE_STEPS:
                self._arc_bases.clear()
            base = Image.new("RGBA", (C, C), (0, 0, 0, 0))
            base.alpha_composite(colorize(self.halo(k), th.accent, 0.35 + 0.55 * level / (PULSE_STEPS - 1)))
            base.alpha_composite(reactor.static(s, k))
            self._arc_bases[key] = base
        img = self._arc_bases[key].copy()
        index = int((t % reactor.SPIN_SECONDS) / reactor.SPIN_SECONDS * reactor.FRAMES) if s["animate"] else 0
        img.alpha_composite(colorize(reactor.ring_frame(k, index), th.accent, 0.8))

        ink = Ink(img.size)
        label, small, button_font = F(8.5, True), F(9.5), F(9, True)
        ink.text((c, c - 0.6 * R), KIND_LABELS.get(notice["kind"], "NOTICE"), label, with_alpha(th.accent, 1), "ms", 1.6 * k)
        when = fmt_time(notice["at"], s["clock_24h"])
        big = fit(self.fonts, s["font"], 40 * k, True, when, 0.6 * D)
        ink.text((c, c - 0.12 * R), when, big, with_alpha(th.fg, 1), "ms")
        title_font = fit(self.fonts, s["font"], 14 * k, True, notice["title"], 0.6 * D)
        ink.text((c, c + 0.06 * R), ellipsize(title_font, notice["title"], 0.62 * D), title_font, with_alpha(th.fg, 1), "ms")
        line = notice["detail"] if count <= 1 else f"+{count - 1} more waiting"
        if line:
            ink.text((c, c + 0.2 * R), ellipsize(small, line, 0.6 * D), small,
                     with_alpha(th.live if count > 1 else th.dim, 1), "ms")
        button_w = 0.6 * D
        buttons = self.buttons(ink, th, notice, button_font, c - button_w / 2, c + 0.31 * R, button_w, round(26 * k), 8 * k)
        ink.onto(img)
        return img, buttons
