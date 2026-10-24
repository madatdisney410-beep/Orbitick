"""A small dark widget kit on top of Tk: rounded cards, toggles, sliders, colour wheel, menus."""
import colorsys
import math
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageTk

import winapi
from core import THEME_DEFAULTS
from render import aa_mask, colorize, hex_rgb

UI = {
    "bg": "#0c0f14",
    "side": "#0f131a",
    "card": "#151a22",
    "card_hi": "#1c222c",
    "field": "#0f1319",
    "border": "#262d39",
    "text": "#e9edf3",
    "muted": "#8b94a7",
    "faint": "#5b6578",
    "accent": "#3ad0ff",
    "accent_hi": "#7be2ff",
    "on_accent": "#03131b",
    "danger": "#ff6b7a",
}

ICON = {
    "schedule": "", "appearance": "", "font": "", "alerts": "", "hotkeys": "",
    "add": "", "delete": "", "close": "", "settings": "", "refresh": "",
    "open": "", "play": "", "search": "", "hide": "", "lock": "",
    "pointer": "", "quit": "", "check": "", "reset": "", "move": "",
    "sound": "", "app": "", "folder": "", "flag": "", "stop": "",
    "stopwatch": "", "events": "",
    "calendar": "", "alarms": "", "notifications": "", "prev": "", "layout": "",
    "next": "", "tag": "", "edit": "",
}


def luminance(color):
    r, g, b = (c / 255 for c in hex_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def derive_palette(bg, accent, text):
    """Every colour the window uses, from the three a theme picks."""
    B, A, T = hex_rgb(bg), hex_rgb(accent), hex_rgb(text)

    def m(a, b, t):
        return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    light = luminance(bg) > 0.5
    T0, T = T, m(T, A, 0.15)  # surfaces and secondary text take a faint tint of the accent
    danger = (214, 51, 74) if light else (255, 107, 122)
    hexed = {k: rgb_hex(v) if isinstance(v, tuple) else v for k, v in {
        "bg": bg, "text": rgb_hex(T0), "accent": accent,
        "side": m(B, T, 0.015), "card": m(B, T, 0.045), "card_hi": m(B, T, 0.075), "hover": m(B, T, 0.11),
        "field": m(B, (255, 255, 255), 0.7) if light else m(B, T, 0.012), "border": m(B, T, 0.115),
        "muted": m(T, B, 0.42), "faint": m(T, B, 0.6), "track": m(B, T, 0.09), "thumb": m(B, T, 0.17),
        "outline": m(B, T, 0.22), "nav_on": m(B, T, 0.07), "nav_hover": m(B, T, 0.04),
        "accent_hi": m(A, (0, 0, 0), 0.15) if light else m(A, (255, 255, 255), 0.35),
        "on_accent": "#03131b" if luminance(accent) > 0.45 else "#ffffff",
        "danger": rgb_hex(danger), "danger_bg": m(B, danger, 0.14), "light": light,
    }.items()}
    return hexed


def apply_theme(theme):
    UI.update(derive_palette(theme.get("bg", THEME_DEFAULTS["bg"]), theme.get("accent", THEME_DEFAULTS["accent"]),
                             theme.get("text", THEME_DEFAULTS["text"])))


class _Env:
    k = 1.0
    font = "Segoe UI"
    display = "Segoe UI"
    icons = None


env = _Env()


def init(root):
    env.k = root.winfo_fpixels("1i") / 96
    families = set(tkfont.families(root))
    env.font = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), "TkDefaultFont")
    env.display = next((f for f in ("Segoe UI Variable Display", "Segoe UI") if f in families), env.font)
    env.icons = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), None)


def px(n):
    return max(1, round(n * env.k))


def font(size=10, weight="normal", display=False):
    return (env.display if display else env.font, round(size), weight)  # Tk wants whole point sizes


def glyph(name):
    return ICON[name] if env.icons else ""


_images = {}


def photo(key, make):
    """Cache PhotoImages (Tk forgets images nobody holds a reference to)."""
    if key not in _images:
        _images[key] = ImageTk.PhotoImage(make())
    return _images[key]


def rounded(w, h, r, fill=None, outline=None, width=1):
    def make():
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if fill:
            img.alpha_composite(colorize(aa_mask((w, h), lambda d, s: d.rounded_rectangle(
                (0, 0, w * s - 1, h * s - 1), r * s, fill=255)), hex_rgb(fill)))
        if outline:
            img.alpha_composite(colorize(aa_mask((w, h), lambda d, s: d.rounded_rectangle(
                (0, 0, w * s - 1, h * s - 1), r * s, outline=255, width=max(1, round(width * s)))), hex_rgb(outline)))
        return img
    return photo(("rounded", w, h, r, fill, outline, width), make)


def circle(d, fill, ring=None):
    def make():
        img = colorize(aa_mask((d, d), lambda dr, s: dr.ellipse((0, 0, d * s - 1, d * s - 1), fill=255)), hex_rgb(fill))
        if ring:
            img.alpha_composite(colorize(aa_mask((d, d), lambda dr, s: dr.ellipse(
                (0, 0, d * s - 1, d * s - 1), outline=255, width=max(1, round(px(2) * s)))), hex_rgb(ring)))
        return img
    return photo(("circle", d, fill, ring), make)


# ---- basic widgets ----------------------------------------------------------

class Button(tk.Canvas):
    STYLES = {
        "primary": ("accent", "accent_hi", "on_accent"),
        "secondary": ("card_hi", "hover", "text"),
        "ghost": (None, "card_hi", "muted"),
        "danger": (None, "danger_bg", "danger"),
    }

    def __init__(self, parent, text="", command=None, kind="secondary", icon=None, height=34, size=10, padx=14,
                 labels=()):
        """`labels`: every text this button will ever show, so it's sized for the longest one."""
        base, hover, fg = self.STYLES[kind]
        bg = parent["bg"]
        f = font(size, "bold" if kind == "primary" else "normal")
        icon_w = px(16) + (px(8) if text else 0) if icon and env.icons else 0
        text_w = max(tkfont.Font(font=f).measure(t) for t in (text, *labels))
        w = text_w + icon_w + 2 * px(padx)
        h = px(height)
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.images = (rounded(w, h, px(8), UI.get(base, base) or bg), rounded(w, h, px(8), UI.get(hover, hover)))
        self.bg_item = self.create_image(0, 0, anchor="nw", image=self.images[0])
        x = px(padx)
        if icon_w:
            self.create_text(x, h / 2, text=ICON[icon], font=(env.icons, size), fill=UI[fg], anchor="w")
            x += icon_w
        if icon_w:
            self.label = self.create_text(x, h / 2, text=text, font=f, fill=UI[fg], anchor="w")
        else:
            self.label = self.create_text(w / 2, h / 2, text=text, font=f, fill=UI[fg], anchor="center")
        self.bind("<Enter>", lambda e: self.itemconfig(self.bg_item, image=self.images[1]))
        self.bind("<Leave>", lambda e: self.itemconfig(self.bg_item, image=self.images[0]))
        self.bind("<ButtonRelease-1>", lambda e: self.command and self.command())

    def set_text(self, text):
        self.itemconfig(self.label, text=text)


class Chips(tk.Frame):
    """A row of pill buttons with one selected. options: [(key, label)]."""

    def __init__(self, parent, options, value, command):
        super().__init__(parent, bg=parent["bg"])
        self.value, self.command = value, command
        self.chips = {}
        f = font(10)
        for key, text in options:
            w, h = tkfont.Font(font=f).measure(text) + 2 * px(16), px(32)
            canvas = tk.Canvas(self, width=w, height=h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
            canvas.pack(side="left", padx=(0, px(6)))
            items = (canvas.create_image(0, 0, anchor="nw"), canvas.create_text(w / 2, h / 2, text=text, font=f))
            canvas.bind("<ButtonRelease-1>", lambda e, k=key: self.pick(k))
            canvas.bind("<Enter>", lambda e, k=key: self.draw(hover=k))
            canvas.bind("<Leave>", lambda e: self.draw())
            self.chips[key] = (canvas, items, w, h)
        self.draw()

    def draw(self, hover=None):
        for key, (canvas, (bg, label), w, h) in self.chips.items():
            on = key == self.value
            fill = UI["accent"] if on else (UI["hover"] if key == hover else UI["card_hi"])
            canvas.itemconfig(bg, image=rounded(w, h, h // 2, fill, None if on else UI["border"]))
            canvas.itemconfig(label, fill=UI["on_accent"] if on else UI["text"])

    def pick(self, key):
        self.set(key)
        self.command(key)

    def set(self, key, notify=False):
        self.value = key
        self.draw()
        if notify:
            self.command(key)


class MultiChips(Chips):
    """Chips where any number can be on. `value` is a set of keys."""

    def __init__(self, parent, options, value, command):
        super().__init__(parent, options, set(value), command)

    def draw(self, hover=None):
        for key, (canvas, (bg, label), w, h) in self.chips.items():
            on = key in self.value
            fill = UI["accent"] if on else (UI["hover"] if key == hover else UI["card_hi"])
            canvas.itemconfig(bg, image=rounded(w, h, h // 2, fill, None if on else UI["border"]))
            canvas.itemconfig(label, fill=UI["on_accent"] if on else UI["text"])

    def pick(self, key):
        self.value ^= {key}
        self.draw()
        self.command(set(self.value))

    def set(self, value, notify=False):
        self.value = set(value)
        self.draw()
        if notify:
            self.command(set(self.value))


class Toggle(tk.Canvas):
    def __init__(self, parent, value, command):
        self.w, self.h = px(42), px(24)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.value = bool(value)
        self.command = command
        self.track = self.create_image(0, 0, anchor="nw")
        self.knob = self.create_image(0, self.h / 2, anchor="w")
        self.bind("<ButtonRelease-1>", lambda e: self.set(not self.value, notify=True))
        self.draw()

    def draw(self):
        on = self.value
        self.itemconfig(self.track, image=rounded(self.w, self.h, self.h // 2, UI["accent"] if on else UI["track"],
                                                  None if on else UI["border"]))
        d = self.h - px(8)
        self.itemconfig(self.knob, image=circle(d, UI["on_accent"] if on else UI["muted"]))
        self.coords(self.knob, self.w - d - px(4) if on else px(4), self.h / 2)

    def set(self, value, notify=False):
        self.value = bool(value)
        self.draw()
        if notify and self.command:
            self.command(self.value)


class Slider(tk.Frame):
    def __init__(self, parent, value, lo, hi, step, command, fmt=str, length=220):
        super().__init__(parent, bg=parent["bg"])
        self.lo, self.hi, self.step, self.command, self.fmt = lo, hi, step, command, fmt
        self.w, self.h = px(length), px(24)
        self.pad = px(9)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0,
                                cursor="hand2")
        self.canvas.pack(side="left")
        self.readout = tk.Label(self, width=7, anchor="e", bg=parent["bg"], fg=UI["muted"], font=font(10))
        self.readout.pack(side="left", padx=(px(6), 0))
        cy = self.h / 2
        self.canvas.create_line(self.pad, cy, self.w - self.pad, cy, width=px(4), capstyle="round", fill=UI["hover"])
        self.fill = self.canvas.create_line(self.pad, cy, self.pad, cy, width=px(4), capstyle="round", fill=UI["accent"])
        self.knob = self.canvas.create_image(0, cy, image=circle(px(16), UI["text"], UI["accent"]))
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.canvas.bind(seq, self.drag)
        self.value = None
        self.set(value)

    def drag(self, e):
        frac = (e.x - self.pad) / (self.w - 2 * self.pad)
        self.set(self.lo + frac * (self.hi - self.lo), notify=True)

    def set(self, value, notify=False):
        value = min(self.hi, max(self.lo, round((value - self.lo) / self.step) * self.step + self.lo))
        value = round(value, 4)
        changed = value != self.value
        self.value = value
        x = self.pad + (value - self.lo) / (self.hi - self.lo) * (self.w - 2 * self.pad)
        cy = self.h / 2
        self.canvas.coords(self.fill, self.pad, cy, x, cy)
        self.canvas.coords(self.knob, x, cy)
        self.readout.config(text=self.fmt(value))
        if notify and changed and self.command:
            self.command(value)


def field(parent, var, width=10, justify="left", size=10, mono=False):
    wrap = tk.Frame(parent, bg=UI["field"], highlightthickness=1, highlightbackground=UI["border"],
                    highlightcolor=UI["border"])
    entry = tk.Entry(wrap, textvariable=var, width=width, bg=UI["field"], fg=UI["text"], insertbackground=UI["text"],
                     relief="flat", bd=0, font=("Cascadia Mono", size) if mono else font(size), justify=justify,
                     selectbackground=UI["accent"], selectforeground=UI["on_accent"])
    entry.pack(padx=px(10), pady=px(7), fill="x", expand=True)
    entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=UI["accent"]))
    entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=getattr(wrap, "rest", UI["border"])))
    wrap.entry = entry
    return wrap


def mark_field(wrap, error):
    wrap.rest = UI["danger"] if error else UI["border"]
    wrap.config(highlightbackground=wrap.rest)


class Card(tk.Frame):
    """A frame with a rounded background, redrawn to fit whenever it's resized."""

    def __init__(self, parent, color=None, radius=10, outline=None):
        self.color = color or UI["card"]
        super().__init__(parent, bg=parent["bg"])
        self.radius, self.outline = radius, outline
        self.bg_label = tk.Label(self, bd=0, bg=parent["bg"])
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._resize)

    def _resize(self, e):
        if e.width > 2 and e.height > 2:
            self.bg_label.config(image=rounded(e.width, e.height, px(self.radius), self.color, self.outline))

    def body(self, padx=18, pady=14):
        inner = tk.Frame(self, bg=self.color)
        inner.pack(fill="both", expand=True, padx=px(padx), pady=px(pady))
        return inner


def section(parent, title):
    tk.Label(parent, text=title.upper(), bg=parent["bg"], fg=UI["faint"], font=font(8, "bold"),
             anchor="w").pack(fill="x", pady=(px(18), px(8)))


def setting_row(parent, title, desc=None):
    """A card row with a title/description on the left; returns the frame for its control."""
    card = Card(parent)
    card.pack(fill="x", pady=(0, px(6)))
    inner = card.body(18, 12)
    left = tk.Frame(inner, bg=card.color)
    left.pack(side="left", fill="x", expand=True)
    tk.Label(left, text=title, bg=card.color, fg=UI["text"], font=font(10), anchor="w").pack(anchor="w")
    if desc:
        tk.Label(left, text=desc, bg=card.color, fg=UI["muted"], font=font(9), anchor="w", justify="left",
                 wraplength=px(330)).pack(anchor="w", pady=(px(1), 0))
    right = tk.Frame(inner, bg=card.color)
    right.pack(side="right", padx=(px(12), 0))
    return right


class ScrollFrame(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=parent["bg"])
        self.canvas = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, bd=0, yscrollincrement=px(24))
        # A wide strip to grab, with a slim thumb drawn in it.
        self.bar = tk.Canvas(self, width=px(14), bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.inner = tk.Frame(self.canvas, bg=parent["bg"])
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y", padx=(px(2), 0))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.window, width=e.width))
        self.canvas.configure(yscrollcommand=self._moved)
        self.view = (0.0, 1.0)
        self.hover = self.dragging = False
        self._grab = 0.0
        self.bar.bind("<Enter>", lambda e: self._set_hover(True))
        self.bar.bind("<Leave>", lambda e: self._set_hover(False))
        self.bar.bind("<Button-1>", self._press)
        self.bar.bind("<B1-Motion>", self._drag)
        self.bar.bind("<ButtonRelease-1>", self._release)
        self.bar.bind("<Configure>", lambda e: self._draw())

    def _moved(self, first, last):
        self.view = (float(first), float(last))
        self._draw()

    def _draw(self):
        first, last = self.view
        self.bar.delete("all")
        if last - first < 0.999:
            h = self.bar.winfo_height()
            active = self.hover or self.dragging
            x = self.bar.winfo_width() / 2
            self.bar.create_line(x, first * h + px(4), x, last * h - px(4), width=px(8 if active else 5),
                                 capstyle="round", fill=UI["muted"] if active else UI["thumb"])

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def _press(self, e):
        first, last = self.canvas.yview()
        frac = e.y / max(1, self.bar.winfo_height())
        if not first <= frac <= last:
            # Clicked the track: jump so the thumb centres on the pointer, then drag from there.
            self.canvas.yview_moveto(frac - (last - first) / 2)
            first, last = self.canvas.yview()  # the callback copy updates later
        self._grab = frac - first
        self.dragging = True
        self._draw()

    def _drag(self, e):
        if self.dragging:
            self.canvas.yview_moveto(e.y / max(1, self.bar.winfo_height()) - self._grab)

    def _release(self, e):
        self.dragging = False
        self._draw()

    def scroll(self, units):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(units, "units")

    def scroll_to(self, widget):
        """Scroll so `widget` (somewhere inside this frame) is in view."""
        self.update_idletasks()
        y = widget.winfo_rooty() - self.inner.winfo_rooty()
        self.canvas.yview_moveto(max(0.0, (y - px(60)) / max(1, self.inner.winfo_height())))


# ---- swatches and colour picker ---------------------------------------------

class Swatch(tk.Canvas):
    def __init__(self, parent, color, command, w=46, h=28):
        self.w, self.h = px(w), px(h)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.item = self.create_image(0, 0, anchor="nw")
        self.set(color)
        self.bind("<ButtonRelease-1>", lambda e: command())

    def set(self, color):
        self.color = color
        self.itemconfig(self.item, image=rounded(self.w, self.h, px(7), color, UI["outline"], px(1)))


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def valid_hex(text):
    text = text.strip()
    if not text.startswith("#"):
        text = "#" + text
    try:
        return rgb_hex(hex_rgb(text)) if len(text) in (4, 7) else None
    except ValueError:
        return None


_wheel_planes = {}


def wheel_planes(size):
    if size not in _wheel_planes:
        c = (size - 1) / 2
        hue, sat = bytearray(size * size), bytearray(size * size)
        for y in range(size):
            dy = c - y
            for x in range(size):
                dx = x - c
                i = y * size + x
                hue[i] = round((math.atan2(dy, dx) / (2 * math.pi)) % 1 * 255)
                sat[i] = round(min(1.0, math.hypot(dx, dy) / c) * 255)
        mask = aa_mask((size, size), lambda d, s: d.ellipse((0, 0, size * s - 1, size * s - 1), fill=255))
        _wheel_planes[size] = (Image.frombytes("L", (size, size), bytes(hue)),
                               Image.frombytes("L", (size, size), bytes(sat)), mask)
    return _wheel_planes[size]


class ColorPicker(tk.Toplevel):
    PRESETS = ["#3ad0ff", "#22d3ee", "#4ade80", "#a3e635", "#facc15", "#ffb547", "#fb923c", "#ff5d73",
               "#f472b6", "#a78bfa", "#818cf8", "#eef3fa", "#8794a8", "#1f2937", "#0b1017", "#000000"]

    def __init__(self, master, title, color, on_change):
        super().__init__(master, bg=UI["bg"])
        self.title(title)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(master)
        self.original = color
        self.on_change = on_change
        r, g, b = (c / 255 for c in hex_rgb(color))
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r, g, b)

        body = tk.Frame(self, bg=UI["bg"])
        body.pack(padx=px(22), pady=(px(18), px(8)))
        tk.Label(body, text=title, bg=UI["bg"], fg=UI["text"], font=font(13, "bold", True), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, px(14)))

        self.size = px(232)
        left = tk.Frame(body, bg=UI["bg"])
        left.grid(row=1, column=0, sticky="n")
        self.wheel = tk.Canvas(left, width=self.size, height=self.size, bg=UI["bg"], highlightthickness=0,
                               cursor="crosshair")
        self.wheel.pack()
        self.wheel_img = self.wheel.create_image(0, 0, anchor="nw")
        self.marker = self.wheel.create_oval(0, 0, 0, 0, outline="white", width=px(2))
        self.marker_in = self.wheel.create_oval(0, 0, 0, 0, outline="#000000", width=1)
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.wheel.bind(seq, self.pick_wheel)

        tk.Label(left, text="Brightness", bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w").pack(
            fill="x", pady=(px(14), px(6)))
        self.bar_h = px(18)
        self.bar = tk.Canvas(left, width=self.size, height=self.bar_h, bg=UI["bg"], highlightthickness=0, cursor="hand2")
        self.bar.pack()
        self.bar_img = self.bar.create_image(0, 0, anchor="nw")
        self.bar_knob = self.bar.create_image(0, self.bar_h / 2, image=circle(px(18), UI["text"], "#000000"))
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.bar.bind(seq, self.pick_value)

        right = tk.Frame(body, bg=UI["bg"])
        right.grid(row=1, column=1, sticky="n", padx=(px(24), 0))
        compare = tk.Frame(right, bg=UI["bg"])
        compare.pack(anchor="w")
        self.before = Swatch(compare, color, lambda: self.set_hex(self.original), 80, 44)
        self.before.grid(row=0, column=0)
        self.after = Swatch(compare, color, lambda: None, 80, 44)
        self.after.grid(row=0, column=1, padx=(px(6), 0))
        for col, text in enumerate(("Before", "New")):
            tk.Label(compare, text=text, bg=UI["bg"], fg=UI["faint"], font=font(8)).grid(row=1, column=col, pady=(px(3), 0))

        tk.Label(right, text="Hex", bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w").pack(fill="x", pady=(px(14), px(4)))
        self.hex_var = tk.StringVar(value=color)
        self.hex_field = field(right, self.hex_var, width=12, mono=True)
        self.hex_field.pack(anchor="w", fill="x")
        self.hex_field.entry.bind("<Return>", lambda e: self.typed_hex())
        self.hex_field.entry.bind("<FocusOut>", lambda e: self.typed_hex(), add="+")
        self.rgb_label = tk.Label(right, bg=UI["bg"], fg=UI["faint"], font=font(9), anchor="w")
        self.rgb_label.pack(fill="x", pady=(px(4), 0))

        tk.Label(right, text="Presets", bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w").pack(fill="x", pady=(px(14), px(6)))
        grid = tk.Frame(right, bg=UI["bg"])
        grid.pack(anchor="w")
        for i, preset in enumerate(self.PRESETS):
            Swatch(grid, preset, lambda p=preset: self.set_hex(p), 26, 26).grid(row=i // 8, column=i % 8, padx=(0, px(5)), pady=(0, px(5)))

        buttons = tk.Frame(self, bg=UI["bg"])
        buttons.pack(fill="x", padx=px(22), pady=(px(10), px(18)))
        Button(buttons, "Done", self.destroy, "primary").pack(side="right")
        Button(buttons, "Cancel", self.cancel).pack(side="right", padx=(0, px(8)))
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

        self.redraw(notify=False)
        winapi.style_window(self, hex_rgb(UI["bg"]), dark=not UI["light"])
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_force()

    @property
    def hex(self):
        return rgb_hex(c * 255 for c in colorsys.hsv_to_rgb(self.h, self.s, self.v))

    def redraw(self, notify=True, wheel=True):
        size = self.size
        if wheel:
            hue, sat, mask = wheel_planes(size)
            img = Image.merge("HSV", (hue, sat, Image.new("L", (size, size), round(self.v * 255)))).convert("RGBA")
            img.putalpha(mask)
            self.wheel_photo = ImageTk.PhotoImage(img)
            self.wheel.itemconfig(self.wheel_img, image=self.wheel_photo)
        c = (size - 1) / 2
        a = self.h * 2 * math.pi
        x, y = c + math.cos(a) * self.s * c, c - math.sin(a) * self.s * c
        r = px(8)
        self.wheel.coords(self.marker, x - r, y - r, x + r, y + r)
        self.wheel.coords(self.marker_in, x - r + px(2), y - r + px(2), x + r - px(2), y + r - px(2))

        full = colorsys.hsv_to_rgb(self.h, self.s, 1)
        bar = Image.linear_gradient("L").rotate(90).resize((size, self.bar_h))  # dark on the left
        top = Image.new("RGB", (size, self.bar_h), tuple(round(c * 255) for c in full))
        img = Image.composite(top, Image.new("RGB", (size, self.bar_h), (0, 0, 0)), bar).convert("RGBA")
        img.putalpha(aa_mask((size, self.bar_h), lambda d, s: d.rounded_rectangle(
            (0, 0, size * s - 1, self.bar_h * s - 1), self.bar_h * s / 2, fill=255)))
        self.bar_photo = ImageTk.PhotoImage(img)
        self.bar.itemconfig(self.bar_img, image=self.bar_photo)
        self.bar.coords(self.bar_knob, px(9) + self.v * (size - 2 * px(9)), self.bar_h / 2)

        color = self.hex
        self.after.set(color)
        self.hex_var.set(color)
        self.rgb_label.config(text="RGB  {}  {}  {}".format(*hex_rgb(color)))
        if notify:
            self.on_change(color)

    def pick_wheel(self, e):
        c = (self.size - 1) / 2
        dx, dy = e.x - c, c - e.y
        self.h = (math.atan2(dy, dx) / (2 * math.pi)) % 1
        self.s = min(1.0, math.hypot(dx, dy) / c)
        if self.v < 0.15:
            self.v = 1.0
            self.redraw()
        else:
            self.redraw(wheel=False)

    def pick_value(self, e):
        self.v = min(1.0, max(0.0, (e.x - px(9)) / (self.size - 2 * px(9))))
        self.redraw()

    def set_hex(self, color):
        r, g, b = (c / 255 for c in hex_rgb(color))
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r, g, b)
        self.redraw()

    def typed_hex(self):
        color = valid_hex(self.hex_var.get())
        mark_field(self.hex_field, color is None)
        if color:
            self.set_hex(color)

    def cancel(self):
        self.on_change(self.original)
        self.destroy()


# ---- hotkey recorder --------------------------------------------------------

KEYSYM_NAMES = {"space": "Space", "Prior": "PageUp", "Next": "PageDown", "Home": "Home", "End": "End",
                "Insert": "Insert", "Delete": "Delete", "Tab": "Tab", "Pause": "Pause"}
MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Win_L", "Win_R",
                    "Super_L", "Super_R", "Caps_Lock", "Num_Lock"}


def combo_from_event(e):
    """A Tk key event -> 'Ctrl+Alt+B', or None if it's only a modifier / unsupported key."""
    if e.keysym in MODIFIER_KEYSYMS:
        return None
    if len(e.keysym) == 1 and e.keysym.isalnum():
        key = e.keysym.upper()
    elif e.keysym.startswith("F") and e.keysym[1:].isdigit():
        key = e.keysym
    elif e.keysym in KEYSYM_NAMES:
        key = KEYSYM_NAMES[e.keysym]
    else:
        return None
    mods = [name for bit, name in ((0x4, "Ctrl"), (0x20000, "Alt"), (0x1, "Shift")) if e.state & bit]
    if not mods and not key.startswith("F"):
        return None  # a bare letter would fire while typing in chat
    return "+".join(mods + [key])


class HotkeyField(tk.Frame):
    def __init__(self, parent, value, command, on_capture=None):
        super().__init__(parent, bg=UI["field"], highlightthickness=1, highlightbackground=UI["border"], cursor="hand2")
        self.value, self.command, self.on_capture = value, command, on_capture
        self.label = tk.Label(self, width=16, bg=UI["field"], fg=UI["text"], font=font(10), anchor="w", takefocus=1)
        self.label.pack(padx=px(10), pady=px(7))
        self.capturing = False
        for w in (self, self.label):
            w.bind("<Button-1>", lambda e: self.start())
        self.label.bind("<KeyPress>", self.key)
        self.label.bind("<FocusOut>", lambda e: self.stop())
        self.show()

    def show(self):
        if self.capturing:
            self.label.config(text="Press a key combination…", fg=UI["accent"])
        else:
            self.label.config(text=self.value or "Off", fg=UI["text"] if self.value else UI["faint"])
        self.config(highlightbackground=UI["accent"] if self.capturing else UI["border"])

    def start(self):
        self.capturing = True
        self.label.focus_set()
        if self.on_capture:
            self.on_capture(True)
        self.show()

    def stop(self):
        if self.capturing:
            self.capturing = False
            if self.on_capture:
                self.on_capture(False)
            self.show()

    def key(self, e):
        if not self.capturing:
            return
        if e.keysym == "Escape":
            self.stop()
        elif e.keysym in ("BackSpace", "Delete") and not e.state & 0x4:
            self.value = ""
            self.command("")
            self.stop()
        else:
            combo = combo_from_event(e)
            if combo:
                self.value = combo
                self.command(combo)
                self.stop()
        return "break"


# ---- popup menu -------------------------------------------------------------

class PopupMenu(tk.Toplevel):
    """A dark context menu. items: (icon, label, command, checked) tuples, or None for a divider."""

    def __init__(self, master, items, x, y):
        super().__init__(master, bg=UI["border"])
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        body = tk.Frame(self, bg=UI["card"])
        body.pack(padx=1, pady=1)
        inner = tk.Frame(body, bg=UI["card"])
        inner.pack(padx=px(5), pady=px(5))
        for item in items:
            if item is None:
                tk.Frame(inner, bg=UI["border"], height=1).pack(fill="x", padx=px(8), pady=px(4))
                continue
            icon, text, command, checked = item
            row = tk.Frame(inner, bg=UI["card"], cursor="hand2")
            row.pack(fill="x")
            parts = [row]
            if env.icons:
                parts.append(tk.Label(row, text=ICON[icon], font=(env.icons, 10), width=2, bg=UI["card"],
                                      fg=UI["muted"]))
                parts[-1].pack(side="left", padx=(px(8), px(4)), pady=px(7))
            parts.append(tk.Label(row, text=text, font=font(10), bg=UI["card"], fg=UI["text"], anchor="w"))
            parts[-1].pack(side="left", padx=(px(4), px(18)), pady=px(7), fill="x", expand=True)
            if checked is not None:
                mark = ICON["check"] if env.icons else "✓"
                parts.append(tk.Label(row, text=mark if checked else "", font=(env.icons, 10) if env.icons else font(10),
                                      width=2, bg=UI["card"], fg=UI["accent"]))
                parts[-1].pack(side="right", padx=(0, px(8)))

            def hover(on, parts=parts):
                for p in parts:
                    p.config(bg=UI["card_hi"] if on else UI["card"])

            def click(e, command=command):
                self.destroy()
                command()
            for p in parts:
                p.bind("<Enter>", lambda e, h=hover: h(True))
                p.bind("<Leave>", lambda e, h=hover: h(False))
                p.bind("<ButtonRelease-1>", click)

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = min(x, self.winfo_vrootx() + self.winfo_screenwidth() - w - 4) if x + w > self.winfo_screenwidth() else x
        y = y - h if y + h > self.winfo_screenheight() else y
        self.geometry(f"+{x}+{y}")
        winapi.style_window(self)
        self.bind("<FocusOut>", lambda e: self.destroy() if e.widget is self else None)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(30, self.focus_force)


# Start with the full default palette, so every window (the installer included) has every colour,
# even if it never applies a theme of its own.
apply_theme(THEME_DEFAULTS)
