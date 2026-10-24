"""Panel layout: a live map of your screens with every panel draggable on it, and layout presets."""
import tkinter as tk
from datetime import datetime

import winapi
from core import PANELS
from notifications import sample_notice
from render import POSITION_KEYS, hex_rgb, mix
from ui import UI, font, px, rounded

SHOW_KEYS = ("show_timer", "show_list", "show_stopwatch")


def mix_hex(a, b, t):
    return "#%02x%02x%02x" % mix(hex_rgb(a), hex_rgb(b), t)


def capture_layout(settings, name):
    """Where every panel is, its size, and which panels are showing: everything a layout preset restores."""
    return {"name": name,
            "positions": {key: settings[key] for key in POSITION_KEYS},
            "show": {key: settings[key] for key in SHOW_KEYS},
            "scales": {panel: settings["styles"][panel]["scale"] for panel in PANELS}}


class ScreenMap(tk.Canvas):
    """A live miniature of your screens. Every panel can be dragged on it, moving the real panel,
    and it keeps up when panels are moved or resized on screen."""
    CORNERS = [("tl", "Top left"), ("tc", "Top centre"), ("tr", "Top right"), ("bl", "Bottom left"), ("br", "Bottom right")]
    REFRESH_MS = 400

    def __init__(self, parent, app, width=460):
        self.app = app
        self.sw, self.sh = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
        self.screens = winapi.monitors() or [(0, 0, self.sw, self.sh)]
        self.x0 = min(m[0] for m in self.screens)
        self.y0 = min(m[1] for m in self.screens)
        span_w = max(m[2] for m in self.screens) - self.x0
        span_h = max(m[3] for m in self.screens) - self.y0
        self.w = px(width)
        self.scale = self.w / span_w
        self.h = round(span_h * self.scale)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0)
        self._drag = None  # (panel, grab offset x, grab offset y, current x, current y)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Motion>", self.hover)
        self.draw()
        self.after(self.REFRESH_MS, self.refresh)

    # ---- what's on screen ----

    def note_size(self):
        panel = self.app.notification
        if panel.size and panel.shown:
            return panel.size
        img, _ = self.app.renderer.notification(self.app.view, sample_notice(datetime.now()), 1, self.app.k)
        return img.size

    def panels(self):
        """[(panel, (x, y), (w, h))] for every panel showing, plus the notification wherever it would appear."""
        out = []
        for panel in (self.app.timer, self.app.list, self.app.stopwatch):
            if panel.shown and panel.size:
                out.append((panel, panel.pos, panel.size))
        s, w_h = self.app.settings, self.note_size()
        if s["notify_x"] is not None:
            note_pos = (s["notify_x"], s["notify_y"])
        else:
            margin = round(16 * self.app.k)
            note_pos = (self.sw - w_h[0] + margin, margin)
        out.append((self.app.notification, note_pos, w_h))
        if self._drag:
            panel, _, _, x, y = self._drag
            out = [(p, (x, y) if p is panel else pos, size) for p, pos, size in out]
        return out

    def to_map(self, x, y):
        return (x - self.x0) * self.scale, (y - self.y0) * self.scale

    # ---- drawing ----

    def draw(self):
        self.delete("all")
        for left, top, right, bottom in self.screens:
            mx, my = self.to_map(left, top)
            w, h = round((right - left) * self.scale), round((bottom - top) * self.scale)
            self.create_image(mx, my, anchor="nw", image=rounded(max(w - 2, 2), max(h - 2, 2), px(6), UI["field"],
                                                                  UI["border"], px(1)))
        for panel, (x, y), (w, h) in self.panels():
            x0, y0 = self.to_map(x, y)
            x1, y1 = self.to_map(x + w, y + h)
            note = panel is self.app.notification
            dragging = self._drag and self._drag[0] is panel
            tag = f"panel:{panel.style}"
            self.create_rectangle(x0, y0, x1, y1, tags=(tag,), width=2 if note or dragging else 1,
                                  outline=UI["accent"] if note or dragging else UI["outline"],
                                  fill=mix_hex(UI["field"], UI["accent"], 0.25 if note or dragging else 0.08))
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=PANELS[panel.style], tags=(tag,),
                             fill=UI["text"] if note or dragging else UI["muted"], font=font(7, "bold" if note else "normal"))
        if self.app.view["locked"]:
            self.create_text(px(8), px(8), anchor="nw", text="Positions are locked", fill=UI["muted"], font=font(8))

    def refresh(self):
        """Keep up with panels moving or resizing on screen while this page is open."""
        if not self.winfo_exists():
            return
        if self.winfo_ismapped() and not self._drag:
            self.draw()
        self.after(self.REFRESH_MS, self.refresh)

    # ---- dragging ----

    def panel_at(self, event):
        for item in reversed(self.find_overlapping(event.x, event.y, event.x, event.y)):
            for tag in self.gettags(item):
                if tag.startswith("panel:"):
                    return next(p for p in self.app.panels if p.style == tag[6:])
        return None

    def hover(self, e):
        self.config(cursor="fleur" if self.panel_at(e) and not self.app.view["locked"] else "")

    def press(self, e):
        panel = self.panel_at(e)
        if not panel or self.app.view["locked"]:
            return
        pos = next(pos for p, pos, _ in self.panels() if p is panel)
        mx, my = self.to_map(*pos)
        self._drag = (panel, e.x - mx, e.y - my, *pos)
        self.app.dragging = True  # so the overlay doesn't snap the panel back while it moves

    def move(self, e):
        if not self._drag:
            return
        panel, gx, gy, _, _ = self._drag
        size = next(size for p, _, size in self.panels() if p is panel)
        x, y = self.clamp((e.x - gx) / self.scale + self.x0, (e.y - gy) / self.scale + self.y0, size)
        self._drag = (panel, gx, gy, x, y)
        if panel.shown:
            panel.move_to(x, y)  # the real panel follows live
        self.draw()

    def release(self, e):
        if not self._drag:
            return
        panel, _, _, x, y = self._drag
        self._drag = None
        self.app.dragging = False
        self.app.set_positions({panel.x_key: x, panel.y_key: y})
        self.draw()

    def clamp(self, x, y, size):
        """Keep at least most of a panel on some screen."""
        w, h = size
        left, top = self.x0, self.y0
        right = max(m[2] for m in self.screens)
        bottom = max(m[3] for m in self.screens)
        return round(min(max(x, left - w * 0.1), right - w * 0.9)), round(min(max(y, top - h * 0.1), bottom - h * 0.9))

    def preset(self, key):
        """Put the notification in a corner (or the top centre) of the main screen."""
        w, h = self.note_size()
        m = round(16 * self.app.k)  # the panel image already has a shadow margin
        x = {"l": -m, "c": (self.sw - w) / 2, "r": self.sw - w + m}[key[1]]
        y = {"t": m, "b": self.sh - h - 2 * m}[key[0]]
        self.app.set_positions({"notify_x": round(x), "notify_y": round(y)})
        self.draw()
