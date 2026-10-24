"""The stopwatch: its state (start, stop, laps, reset) and how it's drawn, as a card or an arc."""
import json
import math
import time

from PIL import Image

import core
from render import Ink, Theme, cap_height, colorize, dot_mask, ellipsize, fit, pill_buttons, with_alpha


def fmt_stopwatch(seconds, hundredths=True):
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
    return text + f".{int((seconds - whole) * 100):02d}" if hundredths else text


class Stopwatch:
    """Start, stop, laps and reset. Timed by the wall clock and saved on every change, so a running
    stopwatch keeps counting while Orbitick is closed."""

    def __init__(self, path=None):
        self.path = path or core.SETTINGS_PATH.with_name("stopwatch.json")
        self.running = False
        self.started = 0.0  # time.time() when last started
        self.banked = 0.0  # seconds counted before that
        self.laps = []  # the running total at each lap
        self.load()

    def elapsed(self, now=None):
        return self.banked + ((now or time.time()) - self.started if self.running else 0.0)

    def toggle(self):
        if self.running:
            self.banked = self.elapsed()
            self.running = False
        else:
            self.started = time.time()
            self.running = True
        self.save()

    def lap_or_reset(self):
        """The left-hand button, as on a phone: Lap while running, Reset while stopped."""
        if self.running:
            self.lap()
        else:
            self.reset()

    def lap(self):
        if self.running:
            self.laps.append(self.elapsed())
            self.save()

    def reset(self):
        self.running = False
        self.banked = 0.0
        self.laps = []
        self.save()

    def lap_times(self, now=None):
        """[(lap number, seconds, in progress)], newest first, starting with the lap in progress."""
        marks = [0.0] + self.laps
        rows = [(i + 1, marks[i + 1] - marks[i], False) for i in reversed(range(len(self.laps)))]
        if self.laps or self.running:
            rows.insert(0, (len(self.laps) + 1, self.elapsed(now) - marks[-1], True))
        return rows

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.running = bool(data.get("running"))
            self.started = float(data.get("started", 0))
            self.banked = float(data.get("banked", 0))
            self.laps = [float(x) for x in data.get("laps", [])]
        except (OSError, ValueError, TypeError, AttributeError):
            self.running, self.started, self.banked, self.laps = False, 0.0, 0.0, []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"running": self.running, "started": self.started,
                                             "banked": self.banked, "laps": self.laps}), encoding="utf-8")
        except OSError:
            pass


def button_labels(watch, now):
    left = "Lap" if watch.running else "Reset"
    right = "Stop" if watch.running else ("Resume" if watch.elapsed(now) > 0 else "Start")
    return left, right


class StopwatchRenderer:
    def __init__(self, fonts, painter, reactor):
        self.fonts = fonts
        self.painter = painter
        self.reactor = reactor  # the arc shares the timer's disc, glow and spinning rings
        self._dots = {}
        self._base = {}  # disc + faint dot ring, per look
        self._lit = (None, None)  # the lit dots only change once a second

    def render(self, s, watch, k, t):
        now = time.time()
        return self.arc(s, watch, k, t, now) if s["shape"] == "reactor" else self.card(s, watch, k, t, now)

    def draw_buttons(self, ink, s, th, watch, now, font, x, y, w, h, gap):
        """Lap/Reset and Start/Stop pills side by side; returns their click areas."""
        left, right = button_labels(watch, now)
        idle = not watch.running and watch.elapsed(now) == 0
        fill = th.warn if watch.running else th.live
        specs = [("lap_or_reset", left, with_alpha(th.fg, 0.10), with_alpha(th.dim if idle else th.fg, 1)),
                 ("toggle", right, with_alpha(fill, 0.95), (12, 16, 22, 255))]
        return pill_buttons(ink, specs, font, x, y, w, h, gap)

    # ---- card ----

    def card(self, s, watch, k, t, now):
        th = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        pad, m = round(20 * k), round(24 * k)
        W = round(s["width"] * k)
        inner = W - 2 * pad
        label, big, row_font, button_font = F(8.5, True), F(44, True), F(10), F(10.5, True)
        rows = watch.lap_times(now)[:s["stopwatch_laps"]]
        row_h = row_font.getmetrics()[0] + 9 * k
        button_h = round(34 * k)
        H = round(2 * pad + cap_height(label) + 16 * k + cap_height(big) + 18 * k + button_h
                  + (14 * k + len(rows) * row_h if rows else 0))

        img = self.painter.paint(s, W, H, m, k, t)
        ink = Ink(img.size)
        x, y = m + pad, m + pad
        base = y + cap_height(label)
        title = s["stopwatch_label"].strip().upper()
        if title:
            ink.paste(with_alpha(th.accent, 1), dot_mask(3 * k), (round(x), round(base - cap_height(label) / 2 - 3 * k)))
            ink.text((x + 11 * k, base), ellipsize(label, title, inner * 0.6), label, with_alpha(th.dim, 1), tracking=1.6 * k)
        state = "RUNNING" if watch.running else ("PAUSED" if watch.elapsed(now) > 0 else "READY")
        ink.text((x + inner, base), state, label, with_alpha(th.live if watch.running else th.dim, 1), "rs", 1.6 * k)

        y = base + 16 * k + cap_height(big)
        text = fmt_stopwatch(watch.elapsed(now), s["stopwatch_hundredths"])
        ink.text((x - 2 * k, y), text, fit(self.fonts, s["font"], 44 * k, True, text, inner), with_alpha(th.fg, 1))

        y += 18 * k
        buttons = self.draw_buttons(ink, s, th, watch, now, button_font, x, y, inner, button_h, 10 * k)
        y += button_h

        if rows:
            y += 14 * k
            done = [seconds for _, seconds, current in watch.lap_times(now) if not current]
            fastest, slowest = (min(done), max(done)) if len(done) >= 2 else (None, None)
            for number, seconds, current in rows:
                base = y + row_font.getmetrics()[0]
                color = th.fg
                if not current and seconds == fastest:
                    color = th.live
                elif not current and seconds == slowest:
                    color = th.warn
                ink.text((x, base), f"Lap {number}", row_font, with_alpha(th.dim, 1))
                ink.text((x + inner, base), fmt_stopwatch(seconds, s["stopwatch_hundredths"]), row_font,
                         with_alpha(color, 0.9), "rs")
                y += row_h
        ink.onto(img)
        return img, [(action, (x0, y0, x1, y1)) for action, (x0, y0, x1, y1) in buttons]

    # ---- arc ----

    def dots(self, k, lit):
        """Masks for the ring of 60 second-dots: all of them faint, and the first `lit` of them."""
        if k not in self._dots:
            if len(self._dots) >= 2:
                self._dots.pop(next(iter(self._dots)))
            self._dots[k] = {}
        cache = self._dots[k]
        if lit not in cache:
            D, g, C = self.reactor.geometry(k)
            R, c = D / 2, C / 2
            mask = Image.new("L", (C, C), 0)
            dot = dot_mask(2.3 * k)
            for i in range(lit):
                a = math.radians(i * 6 - 90)
                x, y = c + 0.895 * R * math.cos(a), c + 0.895 * R * math.sin(a)
                mask.paste(dot, (round(x - dot.width / 2), round(y - dot.height / 2)), dot)
            cache[lit] = mask
        return cache[lit]

    def arc(self, s, watch, k, t, now):
        th = Theme(s)
        F = lambda size, bold=False: self.fonts.get(s["font"], size * k, bold)  # noqa: E731
        reactor = self.reactor
        D, g, C = reactor.geometry(k)
        R, c = D / 2, C / 2
        key = (k, s["bg"], s["fg"], s["accent"], s["bg_opacity"])
        if key not in self._base:
            if len(self._base) >= 2:
                self._base.pop(next(iter(self._base)))
            base = reactor.static(s, k).copy()
            base.alpha_composite(colorize(self.dots(k, 60), th.fg, 0.16))
            self._base[key] = base
        img = self._base[key].copy()
        spinning = s["animate"] and watch.running
        index = int((t % reactor.SPIN_SECONDS) / reactor.SPIN_SECONDS * reactor.FRAMES) if spinning else 0
        img.alpha_composite(colorize(reactor.ring_frame(k, index), th.accent, 0.8))

        elapsed = watch.elapsed(now)
        in_minute = elapsed % 60
        if int(in_minute):
            color = th.warn if not watch.running else th.accent
            lit_key = (k, int(in_minute), color)
            if self._lit[0] != lit_key:
                self._lit = (lit_key, colorize(self.dots(k, int(in_minute)), color))
            img.alpha_composite(self._lit[1])
        if elapsed:
            a = math.radians(in_minute * 6 - 90)
            head = dot_mask(3.4 * k)
            x, y = c + 0.895 * R * math.cos(a), c + 0.895 * R * math.sin(a)
            img.alpha_composite(colorize(head, (255, 255, 255)), (round(x - head.width / 2), round(y - head.height / 2)))

        ink = Ink(img.size)
        label, small, button_font = F(8.5, True), F(9), F(9.5, True)
        title = s["stopwatch_label"].strip().upper()
        if title:
            ink.text((c, c - 0.6 * R), ellipsize(label, title, 0.8 * R), label, with_alpha(th.accent, 0.9), "ms", 1.6 * k)
        text = fmt_stopwatch(elapsed, s["stopwatch_hundredths"])
        big = fit(self.fonts, s["font"], 46 * k, True, text, 0.64 * D)
        ink.text((c, c + 0.06 * R), text, big, with_alpha(th.fg, 1), "ms")
        laps = watch.lap_times(now)
        if laps:
            number, seconds, _ = laps[0]
            ink.text((c, c + 0.21 * R), f"LAP {number} · {fmt_stopwatch(seconds, s['stopwatch_hundredths'])}", small,
                     with_alpha(th.dim, 1), "ms")
        button_w = 0.54 * D
        buttons = self.draw_buttons(ink, s, th, watch, now, button_font, c - button_w / 2, c + 0.31 * R, button_w,
                                    round(26 * k), 8 * k)
        ink.onto(img)
        return img, buttons
