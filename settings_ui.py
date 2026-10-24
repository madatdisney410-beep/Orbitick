"""The app window: Calendar and Alarms (your data, saved instantly) and the settings pages
(previewed live on the overlay; Save keeps them, Cancel reverts)."""
import copy
import os
import shutil
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageDraw, ImageTk

import presets
import winapi
from core import (APP_NAME, DATA_DIR, DEFAULT_SCHEDULE, DEFAULTS, HOTKEY_LABELS, MAX_UPCOMING, PANELS,
                  PRESET_KEYS, SHAPED_PANELS, SPAWN_BEEP, THEME_PRESETS, VERSION, WARN_BEEP, compile_schedule,
                  parse_at, play, validate_schedule)
from effects import EFFECTS, FITS, MAX_ANIMATION_SECONDS, MEDIA_TYPES, inspect_media
from layout_ui import ScreenMap, capture_layout
from planner_ui import AlarmsPage, CalendarPage, Dialog, SoundPicker
from render import POSITION_KEYS, hex_rgb, logo, sample_state
from stopwatch import button_labels
from ui import (ICON, UI, Button, Card, Chips, ColorPicker, HotkeyField, ScrollFrame, Slider, Swatch, Toggle, apply_theme,
                env, field, font, mark_field, px, rounded, section, setting_row)

PAGES = [
    ("calendar", "Calendar", "Your events by month, week or day. Reminders appear as overlay notifications."),
    ("alarms", "Alarms", "Alarms ring with an overlay notification you can snooze or dismiss."),
    ("events", "Event timer", "The repeating schedule, plus labels, panels and display options for the event timer."),
    ("stopwatch", "Stopwatch", "A stopwatch panel with laps, controlled by its buttons or by hotkeys."),
    ("layout", "Layout", "Where each panel sits. Drag them here or on screen, and save arrangements as presets."),
    ("notifications", "Notifications", "Where alarm and reminder notifications appear, and how reminders sound."),
    ("appearance", "Appearance", "Layout, and the look of each panel: shape, background, colours and size."),
    ("font", "Font", "Choose any font installed on this PC, including Adobe Fonts."),
    ("alerts", "Event alerts", "Sound alerts and timing adjustments for the event timer."),
    ("hotkeys", "Hotkeys", "Keyboard shortcuts that work system-wide, even while another app is in focus."),
    ("app", "App", f"Theme, startup options, saved data and information about {APP_NAME}."),
]
NAV_GROUPS = {"calendar": "TOOLS", "layout": "SETTINGS"}  # a group heading goes before these pages
DATA_PAGES = ("calendar", "alarms")  # saved as you go, so Save / Cancel don't apply
NAV_H = 36

COLOR_ROWS = [
    ("bg", "Panel background", "Fill colour of the card and the Arc disc."),
    ("accent", "Accent", "Rings, progress indicators and highlights."),
    ("fg", "Text", "Event names and the countdown."),
    ("dim", "Secondary text", "Labels, the clock and upcoming times."),
    ("warn", "Warning", "Countdown and progress during the advance warning."),
    ("live", "Recent event", "Highlights the event that has just started."),
]
# Panels whose look can be copied onto another (the plain list isn't a fair source).
COPY_SOURCES = ("timer", "stopwatch", "notification")
# Some colours mean something different on the stopwatch.
COLOR_ROWS_BY_PANEL = {
    "stopwatch": {"fg": ("Text", "The time and lap times."),
                  "dim": ("Secondary text", "Labels and lap numbers."),
                  "warn": ("Stop", "Stop button and slowest lap."),
                  "live": ("Start", "Start button, running state and fastest lap.")},
    "list": {"fg": ("Text", "Event names."), "dim": ("Secondary text", "The heading and times.")},
    "notification": {"accent": ("Accent", "Glow, label and Dismiss button."), "fg": ("Text", "Title and time."),
                     "dim": ("Secondary text", "Details."), "live": ("Waiting count", "Shown when more are waiting.")},
}


class SampleWatch:
    """A stopwatch frozen mid-run, for the settings thumbnails."""
    running = True

    def elapsed(self, now=None):
        return 83.45

    def lap_times(self, now=None):
        return [(4, 6.15, True), (3, 27.5, False), (2, 24.69, False), (1, 25.11, False)]


class Sidebar(tk.Canvas):
    """The window's left column: brand, page links in groups, and the theme's background."""

    def __init__(self, parent, window):
        self.window = window
        self.w = px(228)
        super().__init__(parent, width=self.w, bg=UI["side"], highlightthickness=0, bd=0)
        self.background = self.create_image(0, 0, anchor="nw")
        self.logo = ImageTk.PhotoImage(logo(px(34)))
        self.create_image(px(18), px(20), anchor="nw", image=self.logo)
        self.create_text(px(62), px(22), text=APP_NAME, anchor="nw", font=font(12, "bold", True), fill=UI["text"])
        self.create_text(px(62), px(42), text="Overlay timer", anchor="nw", font=font(8), fill=UI["faint"])
        self.items = {}
        self.selected = self.hover = None
        y, h = px(74), px(NAV_H)
        for key, title, _ in PAGES:
            if key in NAV_GROUPS:
                y += px(8)
                self.create_text(px(28), y, text=NAV_GROUPS[key], anchor="nw", font=font(7, "bold"), fill=UI["faint"])
                y += px(18)
            tag = f"nav:{key}"
            box = self.create_image(px(16), y, anchor="nw", image=rounded(px(196), h, px(8)), tags=(tag,))
            bar = self.create_line(px(20), y + px(10), px(20), y + h - px(10), width=px(3), capstyle="round", fill="",
                                   tags=(tag,))
            icon = self.create_text(px(32), y + h / 2, text=ICON.get(key, ""), font=(env.icons, 11), anchor="w",
                                    tags=(tag,)) if env.icons else None
            label = self.create_text(px(60) if env.icons else px(32), y + h / 2, text=title, font=font(10), anchor="w",
                                     tags=(tag,))
            self.items[key] = (box, bar, icon, label)
            self.tag_bind(tag, "<Enter>", lambda e, k=key: self.set_hover(k))
            self.tag_bind(tag, "<Leave>", lambda e, k=key: self.set_hover(None) if self.hover == k else None)
            self.tag_bind(tag, "<ButtonRelease-1>", lambda e, k=key: window.show(k))
            y += h + px(2)
        self.paint()

    def select(self, key):
        self.selected = key
        self.paint()

    def set_hover(self, key):
        self.hover = key
        self.config(cursor="hand2" if key else "")
        self.paint()

    def paint(self):
        h = px(NAV_H)
        for key, (box, bar, icon, label) in self.items.items():
            on, over = key == self.selected, key == self.hover
            fill = UI["nav_on"] if on else (UI["nav_hover"] if over else None)
            self.itemconfig(box, image=rounded(px(196), h, px(8), fill))
            self.itemconfig(bar, fill=UI["accent"] if on else "")
            color = UI["text"] if on or over else UI["muted"]
            self.itemconfig(label, fill=color)
            if icon:
                self.itemconfig(icon, fill=UI["accent"] if on else color)


class ShapeOption(tk.Canvas):
    def __init__(self, parent, title, subtitle, command):
        self.w, self.h = px(262), px(268)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.bg_item = self.create_image(0, 0, anchor="nw")
        self.thumb_item = self.create_image(self.w / 2, px(14) + px(96), anchor="center")
        self.create_text(px(18), self.h - px(44), text=title, font=font(10.5, "bold"), fill=UI["text"], anchor="w")
        self.create_text(px(18), self.h - px(24), text=subtitle, font=font(9), fill=UI["muted"], anchor="w")
        self.check = self.create_text(self.w - px(18), self.h - px(44), text="", font=(env.icons or env.font, 11),
                                      fill=UI["accent"], anchor="e")
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.select(False)

    def select(self, on):
        self.itemconfig(self.bg_item, image=rounded(self.w, self.h, px(12), UI["card"],
                                                    UI["accent"] if on else UI["border"], px(2) if on else px(1)))
        self.itemconfig(self.check, text=(ICON["check"] if env.icons else "✓") if on else "")

    def set_thumb(self, img):
        img = img.copy()
        img.thumbnail((self.w - px(28), px(196)), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.itemconfig(self.thumb_item, image=self.photo)


class SettingsWindow:
    def __init__(self, app, draft=None, original=None, start_page="calendar"):
        self.app = app
        self.original = original or copy.deepcopy(app.settings)
        self.draft = draft or copy.deepcopy(app.settings)
        apply_theme(self.draft["theme"])
        self._preview_job = None
        self._thumb_job = None
        self._theme_job = None
        self._backdrop_job = None
        self._reset_armed = False
        self.t0 = time.monotonic()
        self.controls = {}  # settings key -> Toggle/Slider, for syncing outside changes

        win = self.win = tk.Toplevel(app.root, bg=UI["bg"])
        win.title(APP_NAME)
        win.geometry(f"{px(960)}x{px(660)}")
        win.minsize(px(860), px(560))
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.cancel)
        self.icon = ImageTk.PhotoImage(logo(64))
        win.iconphoto(False, self.icon)

        self.sidebar = Sidebar(win, self)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.bind("<Configure>", lambda e: self.paint_backdrop(once=True))

        main = tk.Frame(win, bg=UI["bg"])
        main.pack(side="left", fill="both", expand=True)
        self.header = tk.Canvas(main, height=px(92), bg=UI["bg"], highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.header_bg = self.header.create_image(0, 0, anchor="nw")
        self.title = self.header.create_text(px(36), px(24), anchor="nw", font=font(20, "bold", True), fill=UI["text"])
        self.subtitle = self.header.create_text(px(36), px(64), anchor="nw", font=font(10), fill=UI["muted"])
        self.header.bind("<Configure>", lambda e: self.paint_backdrop(once=True))

        footer = self.footer = tk.Frame(main, bg=UI["bg"])
        footer.pack(side="bottom", fill="x", padx=px(36), pady=(px(10), px(22)))
        self.footer_line = tk.Frame(main, bg=UI["border"], height=1)
        self.footer_line.pack(side="bottom", fill="x", padx=px(36))
        Button(footer, "Save", self.save, "primary", padx=22).pack(side="right")
        Button(footer, "Cancel", self.cancel).pack(side="right", padx=(0, px(8)))
        self.reset_button = Button(footer, "Reset to defaults", self.reset_all, "ghost", icon="reset")
        self.reset_button.pack(side="right", padx=(0, px(8)))
        self.status = tk.Label(footer, bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w", justify="left",
                               wraplength=px(330))
        self.status.pack(side="left", fill="x", expand=True)

        self.stack = tk.Frame(main, bg=UI["bg"])
        self.stack.pack(fill="both", expand=True, padx=(px(36), px(20)), pady=(px(10), 0))
        self.pages = {}
        for key, _, _ in PAGES:
            page = ScrollFrame(self.stack)
            getattr(self, f"build_{key}")(page.inner)
            self.pages[key] = page

        win.bind_all("<MouseWheel>", self.wheel)
        self.show(start_page)
        winapi.style_window(win, hex_rgb(UI["bg"]), dark=not UI["light"])
        self.refresh_thumbs()
        self.paint_backdrop()
        win.focus_force()

    # ---- plumbing ----

    def show(self, key):
        self.current = key
        for page in self.pages.values():
            page.pack_forget()
        self.sidebar.select(key)
        # Calendar and Alarms save as you go, so the settings footer would only confuse there.
        if key in DATA_PAGES:
            self.footer.pack_forget()
            self.footer_line.pack_forget()
        elif not self.footer.winfo_ismapped():
            self.footer.pack(side="bottom", fill="x", padx=px(36), pady=(px(10), px(22)), before=self.stack)
            self.footer_line.pack(side="bottom", fill="x", padx=px(36), before=self.stack)
        self.pages[key].pack(fill="both", expand=True)
        _, title, desc = next(p for p in PAGES if p[0] == key)
        self.header.itemconfig(self.title, text=title)
        self.header.itemconfig(self.subtitle, text=desc)
        if key == "notifications":
            self.screen_map.draw()
        elif key == "layout":
            self.layout_map.draw()
        elif key in DATA_PAGES:
            self.data_changed()

    def data_changed(self):
        """Alarms or calendar changed (here, or because an alarm rang): redraw those pages."""
        if self.win.winfo_exists():
            self.alarms_page.refresh()
            self.calendar_page.refresh()

    # ---- theme backdrop (sidebar and header) ----

    def theme_style(self, bg):
        th = self.draft["theme"]
        return {"panel_effect": th["effect"], "effect_strength": th["effect_strength"],
                "effect_speed": th["effect_speed"], "custom_bg": th["custom_bg"], "custom_fit": th["custom_fit"],
                "bg": bg, "fg": UI["text"], "accent": UI["accent"], "warn": "#ffb547"}

    def paint_backdrop(self, once=False):
        """Draw the theme's effect or image behind the sidebar and the page header; keep animating it if it moves."""
        if not self.win.winfo_exists():
            return
        effects = self.app.renderer.painter.effects
        side_style = self.theme_style(UI["side"])
        if side_style["panel_effect"] == "none":
            self.sidebar.itemconfig(self.sidebar.background, image="")
            self.header.itemconfig(self.header_bg, image="")
            return
        t, k = (time.monotonic() - self.t0), env.k
        size = (max(1, self.sidebar.winfo_width()), max(1, self.sidebar.winfo_height()))
        self.side_photo = ImageTk.PhotoImage(effects.frame(side_style, size, k, t))
        self.sidebar.itemconfig(self.sidebar.background, image=self.side_photo)
        w, h = max(1, self.header.winfo_width()), max(1, self.header.winfo_height())
        band = effects.frame(self.theme_style(UI["bg"]), (w, h), k, t)
        # Fade the header band into the page below it.
        fade = Image.linear_gradient("L").resize((w, h)).point(lambda v: min(255, int(v * 1.4)))
        band = Image.composite(Image.new("RGB", (w, h), hex_rgb(UI["bg"])), band, fade)
        self.header_photo = ImageTk.PhotoImage(band)
        self.header.itemconfig(self.header_bg, image=self.header_photo)
        if not once and effects.is_animated(side_style):
            self._backdrop_job = self.win.after(80, self.paint_backdrop)

    def theme_changed(self):
        """Theme edits rebuild the window in the new colours (shortly, so dragging a slider stays smooth)."""
        if self._theme_job:
            self.win.after_cancel(self._theme_job)
        self._theme_job = self.win.after(350, self.rebuild)

    def rebuild(self):
        draft, original, page = self.draft, self.original, self.current
        self.close()
        self.app.settings_window = SettingsWindow(self.app, draft, original, page)

    def wheel(self, e):
        widget = self.win.winfo_containing(e.x_root, e.y_root)
        if widget is None or widget.winfo_toplevel() is not self.win or isinstance(widget, tk.Listbox):
            return
        # Three steps per wheel notch (and more for high-resolution wheels that report bigger deltas).
        self.pages[self.current].scroll(-max(1, round(abs(e.delta) / 120)) * 3 * (1 if e.delta > 0 else -1))

    def say(self, text, error=False):
        self.status.config(text=text, fg=UI["danger"] if error else UI["muted"])

    def changed(self, thumbs=True):
        """Debounced live preview on the real overlay."""
        if self._preview_job:
            self.win.after_cancel(self._preview_job)
        self._preview_job = self.win.after(40, lambda: self.app.preview(copy.deepcopy(self.draft)))
        if thumbs:
            if self._thumb_job:
                self.win.after_cancel(self._thumb_job)
            self._thumb_job = self.win.after(250, self.refresh_thumbs)

    def set(self, key, value, thumbs=True):
        self.draft[key] = value
        self.changed(thumbs)

    def close(self):
        self.win.unbind_all("<MouseWheel>")
        self.app.settings_window = None
        self.win.destroy()

    def cancel(self):
        apply_theme(self.app.settings["theme"])  # undo an unsaved theme (the overlay's menus use it too)
        self.app.cancel_preview()
        self.close()

    def save(self):
        rows = [(r["at"].get(), r["bosses"].get()) for r in self.rows]
        for r in self.rows:
            mark_field(r["at_field"], False)
            mark_field(r["bosses_field"], False)
        try:
            entries = validate_schedule(rows)
        except ValueError as e:
            index, message = e.args
            row = self.rows[index]
            mark_field(row["at_field" if parse_at(row["at"].get()) is None else "bosses_field"], True)
            self.show("events")
            self.say(message, error=True)
            return
        if not entries:
            self.show("events")
            self.say("Add at least one event.", error=True)
            return
        combos = [c.lower() for c in self.draft["hotkeys"].values() if c]
        if len(combos) != len(set(combos)):
            self.show("hotkeys")
            self.say("Each action needs a different shortcut.", error=True)
            return
        self.draft["schedule"] = entries
        failed = self.app.commit(copy.deepcopy(self.draft))
        if failed:
            self.original = copy.deepcopy(self.draft)
            self.show("hotkeys")
            self.say("Saved. These shortcuts are already in use by another app: " + ", ".join(failed), error=True)
            return
        self.close()

    def reset_all(self):
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_button.set_text("Click again to confirm")
            self.win.after(3000, self._disarm_reset)
            return
        self.app.commit(copy.deepcopy(DEFAULTS))
        self.close()
        self.app.open_settings()

    def _disarm_reset(self):
        self._reset_armed = False
        if self.win.winfo_exists():
            self.reset_button.set_text("Reset to defaults")

    # ---- schedule ----

    def build_schedule(self, page):
        bar = tk.Frame(page, bg=UI["bg"])
        bar.pack(fill="x", pady=(px(4), px(12)))
        Button(bar, "Add event", self.add_row, icon="add").pack(side="left")
        Button(bar, "Restore default schedule", self.restore_schedule, "ghost", icon="reset").pack(side="left", padx=(px(8), 0))
        tk.Label(bar, text="Use “&” to show names on separate lines.", bg=UI["bg"], fg=UI["faint"], font=font(9)).pack(side="right")

        head = tk.Frame(page, bg=UI["bg"])
        head.pack(fill="x", padx=px(18), pady=(0, px(6)))
        tk.Label(head, text="TIME", bg=UI["bg"], fg=UI["faint"], font=font(8, "bold"), width=8, anchor="w").pack(side="left")
        tk.Label(head, text="EVENT", bg=UI["bg"], fg=UI["faint"], font=font(8, "bold"), anchor="w").pack(side="left", padx=(px(14), 0))
        self.rows_frame = tk.Frame(page, bg=UI["bg"])
        self.rows_frame.pack(fill="x")
        self.rows = []
        for entry in self.draft["schedule"]:
            self.add_row(entry["at"], entry["bosses"], focus=False)

    def add_row(self, at=None, bosses="", focus=True):
        if at is None:
            # Suggest five minutes after the latest event.
            last = max((parse_at(r["at"].get()) or 0 for r in self.rows), default=-300)
            at = f"{(last + 300) % 3600 // 60:02d}:00"
        card = Card(self.rows_frame)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(12, 9)
        row = {"card": card, "at": tk.StringVar(value=at), "bosses": tk.StringVar(value=bosses)}
        row["at_field"] = field(body, row["at"], width=7, justify="center", mono=True)
        row["at_field"].pack(side="left")
        row["bosses_field"] = field(body, row["bosses"], width=40)
        row["bosses_field"].pack(side="left", fill="x", expand=True, padx=(px(10), px(10)))
        Button(body, "", lambda: self.remove_row(row), "ghost", icon="delete", padx=10).pack(side="right")
        for var in (row["at"], row["bosses"]):
            var.trace_add("write", lambda *a: self.schedule_changed())
        self.rows.append(row)
        if focus:
            self.schedule_changed()
            self.win.after(50, lambda: (self.pages["events"].scroll_to(card), row["bosses_field"].entry.focus_set()))

    def remove_row(self, row):
        row["card"].destroy()
        self.rows.remove(row)
        self.schedule_changed()

    def restore_schedule(self):
        for row in list(self.rows):
            row["card"].destroy()
        self.rows.clear()
        for entry in DEFAULT_SCHEDULE:
            self.add_row(entry["at"], entry["bosses"], focus=False)
        self.schedule_changed()

    def schedule_changed(self):
        # Preview whatever parses; Save is where bad rows get flagged.
        self.draft["schedule"] = [{"at": r["at"].get(), "bosses": r["bosses"].get()} for r in self.rows
                                  if compile_schedule([{"at": r["at"].get(), "bosses": r["bosses"].get()}])]
        self.changed()

    # ---- calendar and alarms (planner_ui) ----

    def build_calendar(self, page):
        self.calendar_page = CalendarPage(self, page)

    def build_alarms(self, page):
        self.alarms_page = AlarmsPage(self, page)

    # ---- notifications ----

    def build_notifications(self, page):
        section(page, "Position")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Drag the notification to where it should appear, or use a corner below. "
                            "Your other panels can be dragged here too.",
                 bg=card.color, fg=UI["muted"], font=font(9), anchor="w").pack(anchor="w")
        self.screen_map = ScreenMap(body, self.app)
        self.screen_map.pack(anchor="w", pady=(px(10), px(10)))
        presets = tk.Frame(body, bg=card.color)
        presets.pack(anchor="w")
        for key, label in ScreenMap.CORNERS:
            Button(presets, label, lambda k=key: self.screen_map.preset(k), size=9, height=30).pack(side="left", padx=(0, px(6)))
        Button(body, "Show a test notification", self.app.test_notification, "primary", icon="notifications").pack(
            anchor="w", pady=(px(10), 0))

        section(page, "Calendar reminders")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Sound", bg=card.color, fg=UI["text"], font=font(10), anchor="w").pack(anchor="w")
        tk.Label(body, text="Plays once when a reminder appears.", bg=card.color, fg=UI["muted"], font=font(9),
                 anchor="w").pack(anchor="w", pady=(px(1), px(10)))
        SoundPicker(body, self.draft["reminder_sound"], lambda v: self.set("reminder_sound", v, thumbs=False),
                    lambda: self.draft["reminder_volume"]).pack(anchor="w")
        Slider(setting_row(page, "Reminder volume"), self.draft["reminder_volume"], 0, 1, 0.05,
               lambda v: self.set("reminder_volume", v, thumbs=False), lambda v: f"{round(v * 100)}%").pack()

        section(page, "Alarms")
        Slider(setting_row(page, "Alarm sound duration", "How long an unanswered alarm keeps ringing. "
                                                        "Its notification stays until you dismiss it."),
               self.draft["alarm_timeout"], 1, 30, 1, lambda v: self.set("alarm_timeout", int(v), thumbs=False),
               lambda v: f"{int(v)} min").pack()
        tk.Label(page, text="Each alarm's own sound, volume and snooze length are set on the Alarms page.", bg=UI["bg"],
                 fg=UI["faint"], font=font(9), anchor="w").pack(fill="x", pady=(px(8), px(16)))

    # ---- event timer presets (files in the presets folder) ----

    def event_presets(self):
        return presets.load_all("event")

    def preset_buttons(self, body, kind, current, editable, on_new, on_update, on_delete):
        """The button rows shared by event timer and layout presets."""
        row = tk.Frame(body, bg=body["bg"])
        row.pack(anchor="w", pady=(px(12), 0))
        Button(row, on_new[0], on_new[1], icon="add", size=9, height=30).pack(side="left")
        if editable:
            Button(row, on_update[0], on_update[1], icon="check", size=9, height=30).pack(side="left", padx=(px(6), 0))
            Button(row, "Delete", on_delete, "danger", icon="delete", size=9, height=30).pack(side="left", padx=(px(6), 0))
        row = tk.Frame(body, bg=body["bg"])
        row.pack(anchor="w", pady=(px(6), 0))
        Button(row, "Import…", lambda: self.import_preset(kind), "ghost", icon="open", size=9, height=30).pack(side="left")
        if current:
            Button(row, "Export…", lambda: self.export_preset(kind, current), "ghost", icon="folder", size=9,
                   height=30).pack(side="left", padx=(px(6), 0))
        Button(row, "Open folder", lambda: self.open_preset_folder(kind), "ghost", icon="folder", size=9,
               height=30).pack(side="left", padx=(px(6), 0))

    def build_presets(self, page):
        section(page, "Presets")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="A preset is a whole event timer setup: the schedule, labels and alert timing. Each one is a "
                            "file in your presets folder, so you can import, export and share them.", bg=card.color,
                 fg=UI["muted"], font=font(9), anchor="w", justify="left", wraplength=px(600)).pack(anchor="w")
        names = [p["name"] for p in self.event_presets()]
        current = self.draft["event_preset"] if self.draft["event_preset"] in names else None
        if names:
            Chips(body, [(n, n) for n in names], current, self.apply_preset).pack(anchor="w", pady=(px(12), 0))
        else:
            tk.Label(body, text="No saved presets yet.", bg=card.color, fg=UI["faint"], font=font(9), anchor="w").pack(
                anchor="w", pady=(px(10), 0))
        self.preset_buttons(body, "event", current, bool(current),
                            ("Save as new preset…", self.new_preset), ("Update this preset", self.update_preset),
                            self.delete_preset)

    def current_setup(self):
        """The event timer setup as it stands in this window, or a message if the schedule has a mistake."""
        try:
            schedule = validate_schedule([(r["at"].get(), r["bosses"].get()) for r in self.rows])
        except ValueError as e:
            return None, e.args[1]
        if not schedule:
            return None, "Add at least one event first."
        return dict({key: copy.deepcopy(self.draft[key]) for key in PRESET_KEYS}, schedule=schedule), None

    def apply_preset(self, name):
        preset = next(p for p in self.event_presets() if p["name"] == name)
        for key in PRESET_KEYS:
            self.draft[key] = copy.deepcopy(preset[key])
        self.draft["event_preset"] = name
        self.changed()
        self.rebuild_page("events")
        self.say(f"Applied “{name}”. Save to keep it.")

    def ask_name(self, title, on_name):
        dialog = Dialog(self.win, title, lambda: on_name(dialog.name_var.get().strip()), width=400)
        dialog.label(dialog.body, "Name")
        dialog.name_var = tk.StringVar()
        name_field = field(dialog.body, dialog.name_var, width=34)
        name_field.pack(fill="x")
        dialog.open(self.win)
        name_field.entry.focus_set()

    def new_preset(self):
        setup, error = self.current_setup()
        if error:
            self.say(error, error=True)
            return
        self.ask_name("Save as new preset", lambda name: self.add_preset(name, setup))

    def add_preset(self, name, setup):
        if not name:
            return "Enter a name for the preset."
        if any(p["name"].lower() == name.lower() for p in self.event_presets()):
            return "A preset with that name already exists."
        presets.save("event", dict(setup, name=name))
        self.draft["event_preset"] = name
        self.rebuild_page("events")
        self.say(f"Saved the preset “{name}” to your presets folder.")
        return None

    def update_preset(self):
        setup, error = self.current_setup()
        if error:
            self.say(error, error=True)
            return
        name = self.draft["event_preset"]
        presets.save("event", dict(setup, name=name))
        self.say(f"Updated “{name}” with the current setup.")

    def delete_preset(self):
        name = self.draft["event_preset"]
        presets.delete("event", name)
        self.draft["event_preset"] = ""
        self.rebuild_page("events")
        self.say(f"Deleted the preset “{name}”. The current setup is unchanged.")

    # ---- preset files: import, export, folder ----

    def import_preset(self, kind):
        path = filedialog.askopenfilename(parent=self.win, title="Import an Orbitick preset", filetypes=presets.FILE_TYPES)
        if not path:
            return
        try:
            got, preset = presets.import_file(path)
        except ValueError as e:
            self.say(str(e), error=True)
            return
        self.rebuild_page("events" if got == "event" else "layout")
        where = "" if got == kind else f" It's on the {'Event timer' if got == 'event' else 'Layout'} page."
        self.say(f"Imported the {presets.KINDS[got]} “{preset['name']}”.{where}")

    def export_preset(self, kind, name):
        preset = next((p for p in (self.event_presets() if kind == "event" else presets.load_all("layout"))
                       if p["name"] == name), None)
        if not preset:
            return
        path = filedialog.asksaveasfilename(parent=self.win, title="Export preset", defaultextension=presets.EXT,
                                            initialfile=presets.file_name(name) + presets.EXT,
                                            filetypes=presets.FILE_TYPES)
        if path:
            presets.export(kind, preset, path)
            self.say(f"Exported “{name}”. Double-click the file on any PC with {APP_NAME} to import it.")

    def open_preset_folder(self, kind):
        folder = presets.folder(kind)
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def rebuild_page(self, key):
        page = self.pages[key]
        for child in page.inner.winfo_children():
            child.destroy()
        getattr(self, f"build_{key}")(page.inner)
        page.canvas.yview_moveto(0)

    # ---- event timer ----

    def build_events(self, page):
        self.build_presets(page)
        section(page, "Schedule")
        tk.Label(page, text="Event times are minutes past the hour, and the schedule repeats every hour.", bg=UI["bg"],
                 fg=UI["muted"], font=font(9), anchor="w").pack(fill="x", pady=(0, px(8)))
        self.build_schedule(page)

        section(page, "Text")
        self.text_row(page, "title", "Title", "Displayed at the top of the timer. Leave blank to hide.")
        self.text_row(page, "next_label", "Next event label", "Precedes the time of the next event, for example “Next meeting”.")
        self.text_row(page, "past_label", "Recent event label", "Precedes the elapsed time once an event starts, for example “Spawned”.")
        self.text_row(page, "list_label", "Upcoming list heading", "Heading of the upcoming list panel. Leave blank to hide.")

        section(page, "Panels")
        self.toggle_row(page, "show_timer", "Show the event timer", thumbs=False)
        self.toggle_row(page, "show_list", "Show the upcoming list", thumbs=False)
        self.toggle_row(page, "split_list", "Separate upcoming list panel",
                        "Positions the list independently of the timer. Always enabled for the Arc shape.")
        Slider(setting_row(page, "Number of upcoming events"), self.draft["upcoming"], 0, MAX_UPCOMING, 1,
               lambda v: self.set("upcoming", int(v)), lambda v: str(int(v))).pack()

        section(page, "Display")
        self.toggle_row(page, "show_clock", "Show the current time")
        self.toggle_row(page, "clock_24h", "24-hour clock")
        tk.Frame(page, bg=UI["bg"], height=px(16)).pack()

    # ---- stopwatch ----

    def build_stopwatch(self, page):
        section(page, "Panel")
        self.toggle_row(page, "show_stopwatch", "Show the stopwatch",
                        "A draggable panel with Start, Stop, Lap and Reset buttons.", thumbs=False)
        self.text_row(page, "stopwatch_label", "Title", "Displayed at the top of the stopwatch. Leave blank to hide.")
        self.toggle_row(page, "stopwatch_hundredths", "Show hundredths of a second")
        Slider(setting_row(page, "Laps shown on the panel", "Most recent first, with the lap in progress at the top."),
               self.draft["stopwatch_laps"], 0, 10, 1, lambda v: self.set("stopwatch_laps", int(v)),
               lambda v: str(int(v))).pack()

        section(page, "Controls")
        right = setting_row(page, "Stopwatch", "The buttons on the panel and the hotkeys on the Hotkeys page do the same.")
        self.watch_toggle = Button(right, self.toggle_label(), lambda: self.watch_action("toggle"), "primary", size=9,
                                   height=30, padx=18, labels=("Start", "Resume", "Stop"))
        self.watch_toggle.pack(side="left")
        Button(right, "Lap", lambda: self.watch_action("lap"), size=9, height=30).pack(side="left", padx=(px(6), 0))
        Button(right, "Reset", lambda: self.watch_action("reset"), "ghost", size=9, height=30).pack(side="left", padx=(px(6), 0))
        tk.Frame(page, bg=UI["bg"], height=px(16)).pack()

    def toggle_label(self):
        return button_labels(self.app.watch, time.time())[1]

    def watch_action(self, action):
        self.app.stopwatch_action(action)

    def watch_changed(self):
        """The stopwatch changed (here, on its panel, or by hotkey): keep the button label current."""
        self.watch_toggle.set_text(self.toggle_label())

    # ---- layout ----

    def build_layout(self, page):
        section(page, "Your screens")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Drag any panel to move it; it moves on screen straight away. The map follows your panels "
                            "as you move or resize them.", bg=card.color, fg=UI["muted"], font=font(9), anchor="w",
                 justify="left", wraplength=px(600)).pack(anchor="w")
        self.layout_map = ScreenMap(body, self.app, width=600)
        self.layout_map.pack(anchor="w", pady=(px(10), 0))

        section(page, "Layout presets")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="A layout remembers where each panel sits, its size, and which panels are showing. Each one is a "
                            "file in your presets folder. Applying one takes effect immediately.", bg=card.color,
                 fg=UI["muted"], font=font(9), anchor="w", justify="left", wraplength=px(600)).pack(anchor="w")
        names = [layout["name"] for layout in presets.load_all("layout")]
        current = self.app.settings["layout_preset"] if self.app.settings["layout_preset"] in names else None
        if names:
            Chips(body, [(n, n) for n in names], current, self.apply_layout).pack(anchor="w", pady=(px(12), 0))
        else:
            tk.Label(body, text="No saved layouts yet.", bg=card.color, fg=UI["faint"], font=font(9), anchor="w").pack(
                anchor="w", pady=(px(10), 0))
        self.preset_buttons(body, "layout", current, bool(current), ("Save current layout as…", self.new_layout),
                            ("Update this layout", self.update_layout), self.delete_layout)

        section(page, "Behaviour")
        self.toggle_row(page, "link_panels", "Move panels together",
                        "Moving any panel moves all of them, preserving their relative positions.", thumbs=False)
        self.toggle_row(page, "locked", "Lock positions", "Prevents panels from being moved.", thumbs=False)
        Button(setting_row(page, "Reset layout", "Hold Ctrl and scroll over a panel to resize it. Reset layout restores "
                                                 "the default position and size of every panel."),
               "Reset layout", self.app.reset_layout, icon="move").pack()
        tk.Frame(page, bg=UI["bg"], height=px(16)).pack()

    def apply_layout(self, name):
        layout = presets.find("layout", name)
        if layout:
            self.app.apply_layout(layout)
        self.rebuild_page("layout")
        self.say(f"Applied the layout “{name}”.")

    def new_layout(self):
        self.ask_name("Save current layout", self.add_layout)

    def add_layout(self, name):
        if not name:
            return "Enter a name for the layout."
        if presets.find("layout", name):
            return "A layout with that name already exists."
        presets.save("layout", capture_layout(self.app.settings, name))
        self.app.update(layout_preset=name)
        self.rebuild_page("layout")
        self.say(f"Saved the layout “{name}” to your presets folder.")
        return None

    def update_layout(self):
        name = self.app.settings["layout_preset"]
        presets.save("layout", capture_layout(self.app.settings, name))
        self.say(f"Updated the layout “{name}” to the current arrangement.")

    def delete_layout(self):
        name = self.app.settings["layout_preset"]
        presets.delete("layout", name)
        self.app.update(layout_preset="")
        self.rebuild_page("layout")
        self.say(f"Deleted the layout “{name}”. Your panels stay where they are.")

    # ---- appearance ----

    def build_appearance(self, page):
        section(page, "Panel to customise")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Each panel has its own shape, background, colours and size.", bg=UI["card"],
                 fg=UI["muted"], font=font(9), anchor="w").pack(anchor="w")
        self.style_panel = "timer"
        self.panel_chips = Chips(body, list(PANELS.items()), self.style_panel, self.pick_style_panel)
        self.panel_chips.pack(anchor="w", pady=(px(10), 0))
        self.style_frame = tk.Frame(page, bg=UI["bg"])
        self.style_frame.pack(fill="x")
        self.build_style()

    def style(self):
        return self.draft["styles"][self.style_panel]

    def set_style(self, key, value, thumbs=True):
        self.style()[key] = value
        self.changed(thumbs)

    def pick_style_panel(self, name):
        self.style_panel = name
        self.panel_chips.set(name)
        self.build_style()

    def build_style(self):
        """(Re)build the look controls for the selected panel."""
        for child in self.style_frame.winfo_children():
            child.destroy()
        self.style_controls = {}
        self.shape_options = {}
        page, name, style = self.style_frame, self.style_panel, self.style()

        others = [n for n in COPY_SOURCES if n != name and n in PANELS]
        right = setting_row(page, "Copy style from", "Replaces this panel's look with another panel's. Its size is kept.")
        for other in others:
            Button(right, PANELS[other], lambda o=other: self.copy_style(o), size=9, height=30).pack(side="left", padx=(px(6), 0))

        if name in SHAPED_PANELS:
            section(page, "Shape")
            shapes = tk.Frame(page, bg=UI["bg"])
            shapes.pack(fill="x")
            subtitles = {"timer": ("Card with a progress bar", "Circular display with animated rings"),
                         "stopwatch": ("Card with buttons and laps", "Circular display with a seconds ring"),
                         "notification": ("Card with Snooze and Dismiss", "Circular display with a pulsing glow")}[name]
            self.shape_options = {
                "card": ShapeOption(shapes, "Classic", subtitles[0], lambda: self.pick_shape("card")),
                "reactor": ShapeOption(shapes, "Arc", subtitles[1], lambda: self.pick_shape("reactor")),
            }
            self.shape_options["card"].pack(side="left")
            self.shape_options["reactor"].pack(side="left", padx=(px(12), 0))
            self.shape_options[style["shape"]].select(True)

        section(page, "Background")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Effect", bg=UI["card"], fg=UI["text"], font=font(10), anchor="w").pack(anchor="w")
        where = "the Arc shape's disc stays solid" if name in SHAPED_PANELS else "applies to the whole panel"
        tk.Label(body, text=f"Background for this panel's card shape ({where}).", bg=UI["card"], fg=UI["muted"],
                 font=font(9), anchor="w").pack(anchor="w", pady=(px(1), 0))
        self.style_controls["panel_effect"] = Chips(body, EFFECTS, style["panel_effect"],
                                                    lambda v: self.set_style("panel_effect", v))
        self.style_controls["panel_effect"].pack(anchor="w", pady=(px(12), 0))

        right = setting_row(page, "Custom image or animation",
                            f"PNG, JPG, BMP, GIF, WebP or APNG. Animations can be up to {MAX_ANIMATION_SECONDS} seconds.")
        self.media_label = tk.Label(right, bg=UI["card"], fg=UI["muted"], font=font(9), width=22, anchor="e")
        self.media_label.pack(side="left", padx=(0, px(10)))
        Button(right, "Choose file…", self.choose_media, size=9, height=30, icon="open").pack(side="left")
        Button(right, "", self.clear_media, "ghost", icon="close", padx=10).pack(side="left", padx=(px(4), 0))
        self.show_media()
        self.style_controls["custom_fit"] = Chips(
            setting_row(page, "Image fit", "Fill covers the panel and crops the edges. Stretch matches the panel "
                                           "exactly. Fit shows the whole image."),
            FITS, style["custom_fit"], lambda v: self.set_style("custom_fit", v))
        self.style_controls["custom_fit"].pack()
        self.style_slider(page, "effect_speed", "Effect speed", "Also sets the playback speed of custom animations.",
                          0.25, 3, 0.05, lambda v: f"{v:.2f}×", thumbs=False)
        self.style_slider(page, "effect_strength", "Effect strength",
                          "For custom images, how strongly the image shows over the panel colour.", 0, 1, 0.05,
                          lambda v: f"{round(v * 100)}%")

        section(page, "Colours")
        self.swatches = {}
        names = dict(COLOR_ROWS_BY_PANEL.get(name, {}))
        for key, title, desc in COLOR_ROWS:
            title, desc = names.get(key, (title, desc))
            right = setting_row(page, title, desc)
            hex_label = tk.Label(right, text=style[key].upper(), bg=UI["card"], fg=UI["muted"],
                                 font=("Cascadia Mono", 9), width=8, anchor="e")
            hex_label.pack(side="left", padx=(0, px(10)))
            swatch = Swatch(right, style[key], lambda k=key, t=title: self.pick_color(k, t))
            swatch.pack(side="left")
            self.swatches[key] = (swatch, hex_label)

        section(page, "Size & opacity")
        pct = lambda v: f"{round(v * 100)}%"  # noqa: E731
        self.style_slider(page, "scale", "Size", "Hold Ctrl and scroll over the panel to change this quickly.",
                          0.5, 2.5, 0.05, pct, thumbs=False)
        self.style_slider(page, "width", "Width", "Applies to the Classic shape and the upcoming list.", 220, 560, 10,
                          lambda v: f"{int(v)} px", cast=int)
        self.style_slider(page, "bg_opacity", "Panel opacity", "Opacity of the panel background. Text remains fully opaque.",
                          0, 1, 0.01, pct)
        self.style_slider(page, "opacity", "Overall opacity", "Opacity of the entire panel, including text.", 0.2, 1, 0.01,
                          pct, thumbs=False)

        section(page, "Animation")
        self.style_controls["animate"] = Toggle(setting_row(page, "Animations", "Animated rings and backgrounds."),
                                                style["animate"], lambda v: self.set_style("animate", v))
        self.style_controls["animate"].pack()
        tk.Frame(page, bg=UI["bg"], height=px(16)).pack()
        self.refresh_thumbs()

    def style_slider(self, page, key, title, desc, lo, hi, step, fmt, thumbs=True, cast=float):
        slider = Slider(setting_row(page, title, desc), self.style()[key], lo, hi, step,
                        lambda v: self.set_style(key, cast(v), thumbs), fmt)
        slider.pack()
        self.style_controls[key] = slider

    def copy_style(self, source):
        keep = {"scale": self.style()["scale"]}
        self.draft["styles"][self.style_panel] = dict(copy.deepcopy(self.draft["styles"][source]), **keep)
        self.changed()
        self.build_style()
        self.say(f"Copied the look of the {PANELS[source].lower()}.")

    def text_row(self, page, key, title, desc):
        var = tk.StringVar(value=self.draft[key])
        field(setting_row(page, title, desc), var, width=24).pack()
        var.trace_add("write", lambda *a: self.set(key, var.get()))

    def show_media(self):
        path = self.style()["custom_bg"]
        self.media_label.config(text=Path(path).name if path else "No file chosen")

    def import_media(self):
        """Ask for an image or animation, check it, and copy it into the settings folder.
        Returns (path, frames, seconds), or None."""
        path = filedialog.askopenfilename(parent=self.win, title="Choose a background image or animation",
                                          filetypes=MEDIA_TYPES)
        if not path:
            return None
        try:
            frames, seconds = inspect_media(path)
        except ValueError as e:
            self.say(str(e), error=True)
            return None
        # Keep a copy with the settings, so moving or deleting the original doesn't break the panel.
        folder = DATA_DIR / "backgrounds"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / Path(path).name
        if Path(path).resolve() != target.resolve():
            stem, n = target.stem, 1
            while target.exists():
                n += 1
                target = folder / f"{stem} ({n}){target.suffix}"
            shutil.copy2(path, target)
        return str(target), frames, seconds

    def choose_media(self):
        chosen = self.import_media()
        if not chosen:
            return
        target, frames, seconds = chosen
        self.style()["custom_bg"] = target
        self.style_controls["panel_effect"].set("custom")
        self.set_style("panel_effect", "custom")
        self.show_media()
        self.say(f"Background set: animation ({seconds:.1f} seconds)." if frames > 1 else "Background set: image.")

    def clear_media(self):
        self.style()["custom_bg"] = ""
        if self.style()["panel_effect"] == "custom":
            self.style_controls["panel_effect"].set("none")
            self.style()["panel_effect"] = "none"
        self.changed()
        self.show_media()

    def toggle_row(self, page, key, title, desc=None, thumbs=True):
        self.controls[key] = Toggle(setting_row(page, title, desc), self.draft[key], lambda v: self.set(key, v, thumbs))
        self.controls[key].pack()

    def external_change(self, values):
        """Mirror changes made from the right-click menu, tray or panels, so this window never
        shows (or saves back) a stale value."""
        for key, value in values.items():
            if key in POSITION_KEYS:
                continue
            self.draft[key] = value
            self.original[key] = value
            if key in self.controls:
                self.controls[key].set(value)

    def external_style_change(self, name, values):
        """The same for one panel's look (Ctrl + scroll, Reset layout)."""
        self.draft["styles"][name].update(values)
        self.original["styles"][name].update(values)
        if name == self.style_panel:
            for key, value in values.items():
                if key in self.style_controls:
                    self.style_controls[key].set(value)

    def pick_shape(self, shape):
        for key, option in self.shape_options.items():
            option.select(key == shape)
        self.set_style("shape", shape, thumbs=False)

    def pick_color(self, key, title):
        swatch, label = self.swatches[key]

        def on_change(color):
            swatch.set(color)
            label.config(text=color.upper())
            self.set_style(key, color)
        ColorPicker(self.win, title, self.style()[key], on_change)

    def refresh_thumbs(self):
        self._thumb_job = None
        if not self.win.winfo_exists():
            return
        if self.shape_options:
            st = sample_state(self.draft)
            for shape, option in self.shape_options.items():
                preview = copy.deepcopy(self.draft)
                preview["styles"][self.style_panel].update(shape=shape, scale=1.0)
                preview["styles"]["list"]["scale"] = 1.0
                preview["show_list"] = True
                option.set_thumb(self.app.renderer.preview(preview, self.style_panel, st, SampleWatch(),
                                                           px(100) / 100 * 0.75))
        if hasattr(self, "font_preview"):  # the Font page is built after this one
            self.refresh_font_preview()

    # ---- font ----

    def build_font(self, page):
        top = tk.Frame(page, bg=UI["bg"])
        top.pack(fill="both", expand=True, pady=(px(4), 0))

        left = tk.Frame(top, bg=UI["bg"])
        left.pack(side="left", fill="y")
        self.font_search = tk.StringVar()
        search = field(left, self.font_search, width=28)
        search.pack(fill="x")
        hint = tk.Label(search, text="Search fonts…", bg=UI["field"], fg=UI["faint"], font=font(10), cursor="xterm")
        hint.place(x=px(10), rely=0.5, anchor="w")
        hint.bind("<Button-1>", lambda e: search.entry.focus_set())
        self.font_search.trace_add("write", lambda *a: hint.place_forget() if self.font_search.get()
                                   else hint.place(x=px(10), rely=0.5, anchor="w"))
        self.font_search.trace_add("write", lambda *a: self.fill_fonts())
        list_card = Card(left, UI["field"], 8, UI["border"])
        list_card.pack(fill="both", expand=True, pady=(px(8), 0))
        self.font_list = tk.Listbox(list_card, bg=UI["field"], fg=UI["text"], font=font(10), bd=0,
                                    highlightthickness=0, activestyle="none", selectbackground=UI["accent"],
                                    selectforeground=UI["on_accent"], height=16, width=30, exportselection=False)
        self.font_list.pack(fill="both", expand=True, padx=px(6), pady=px(6))
        self.font_list.bind("<<ListboxSelect>>", lambda e: self.pick_font())

        right = tk.Frame(top, bg=UI["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(px(18), 0))
        preview = Card(right)
        preview.pack(fill="x")
        body = preview.body(20, 16)
        self.font_name = tk.Label(body, bg=UI["card"], fg=UI["muted"], font=font(9), anchor="w")
        self.font_name.pack(anchor="w")
        self.font_preview = tk.Label(body, bg=UI["card"], bd=0)
        self.font_preview.pack(anchor="w", pady=(px(10), 0))

        buttons = tk.Frame(right, bg=UI["bg"])
        buttons.pack(fill="x", pady=(px(12), 0))
        Button(buttons, "Add font file…", self.add_font_file, icon="open").pack(side="left")
        Button(buttons, "Refresh list", self.refresh_fonts, "ghost", icon="refresh").pack(side="left", padx=(px(8), 0))

        info = Card(right)
        info.pack(fill="x", pady=(px(12), 0))
        body = info.body(18, 14)
        tk.Label(body, text="Using Adobe Fonts", bg=UI["card"], fg=UI["text"], font=font(10, "bold"), anchor="w").pack(anchor="w")
        tk.Label(body, bg=UI["card"], fg=UI["muted"], font=font(9), anchor="w", justify="left", wraplength=px(330), text=(
            "Activate a font in Creative Cloud (Fonts, or fonts.adobe.com), then select Refresh list. "
            "Activated fonts appear alongside installed fonts.\n\n"
            "Font files (.ttf, .otf) can also be added with Add font file. They are loaded "
            "by this app only and are not installed system-wide.")).pack(anchor="w", pady=(px(4), 0))
        self.refresh_fonts()

    def refresh_fonts(self):
        self.families = sorted({f for f in tkfont.families(self.win) if not f.startswith("@")}, key=str.lower)
        self.app.renderer.fonts.clear()
        self.fill_fonts()

    def fill_fonts(self):
        query = self.font_search.get().strip().lower()
        self.shown_families = [f for f in self.families if query in f.lower()]
        self.font_list.delete(0, "end")
        for family in self.shown_families:
            self.font_list.insert("end", family)
        if self.draft["font"] in self.shown_families:
            i = self.shown_families.index(self.draft["font"])
            self.font_list.selection_set(i)
            self.font_list.see(i)

    def pick_font(self):
        sel = self.font_list.curselection()
        if sel:
            self.set("font", self.shown_families[sel[0]])
            self.refresh_font_preview()

    def refresh_font_preview(self):
        family = self.draft["font"]
        fonts = self.app.renderer.fonts
        k = px(100) / 100
        w, h = round(330 * k), round(150 * k)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fg, accent, dim = hex_rgb(UI["text"]), hex_rgb(UI["accent"]), hex_rgb(UI["muted"])
        d.text((0, 0), "3:48", font=fonts.get(family, 56 * k, True), fill=fg, anchor="la")
        d.text((0, 78 * k), "Top of the hour · Half past", font=fonts.get(family, 15 * k, True), fill=accent, anchor="la")
        d.text((0, 104 * k), f"{self.draft['next_label']} 10:50 AM  ·  Quarter to", font=fonts.get(family, 11 * k), fill=dim, anchor="la")
        self.font_photo = ImageTk.PhotoImage(img)
        self.font_preview.config(image=self.font_photo)
        self.font_name.config(text=f"Current font: {family}")

    def add_font_file(self):
        path = filedialog.askopenfilename(parent=self.win, title="Add a font file",
                                          filetypes=[("Fonts", "*.ttf *.otf *.ttc"), ("All files", "*.*")])
        if not path:
            return
        before = set(tkfont.families(self.win))
        if not self.app.add_font(path):
            self.say("Windows could not load this font file.", error=True)
            return
        if path not in self.draft["font_files"]:
            self.draft["font_files"] = self.draft["font_files"] + [path]
        self.refresh_fonts()
        added = sorted(set(self.families) - before)
        if added:
            self.font_search.set("")
            self.draft["font"] = added[0]
            self.fill_fonts()
            self.changed()
            self.say(f"Added {', '.join(added)}.")
        else:
            self.say("This font is already available.")

    # ---- alerts ----

    def build_alerts(self, page):
        section(page, "Sounds")
        self.toggle_row(page, "sound", "Play sounds", thumbs=False)
        Slider(setting_row(page, "Advance warning", "Plays a sound and switches the countdown to the warning colour."),
               self.draft["warn_seconds"], 0, 300, 5, lambda v: self.set("warn_seconds", int(v), thumbs=False),
               lambda v: "Off" if not v else (f"{int(v) // 60}:{int(v) % 60:02d}" if v >= 60 else f"{int(v)} s")).pack()
        self.sound_row(page, "warn_sound", "Warning sound", WARN_BEEP)
        self.sound_row(page, "spawn_sound", "Event sound", SPAWN_BEEP)

        section(page, "Timing")
        Slider(setting_row(page, "Recent event display time", "How long the most recent event remains listed after it starts."),
               self.draft["just_spawned_seconds"], 0, 600, 10,
               lambda v: self.set("just_spawned_seconds", int(v), thumbs=False),
               lambda v: "Off" if not v else f"{int(v) // 60}:{int(v) % 60:02d}").pack()
        Slider(setting_row(page, "Clock correction", "Adjusts the timer if events occur slightly earlier or later than expected."),
               self.draft["offset_seconds"], -120, 120, 1, lambda v: self.set("offset_seconds", int(v), thumbs=False),
               lambda v: f"{int(v):+d} s").pack()

    def sound_row(self, page, key, title, fallback):
        right = setting_row(page, title, "Choose a .wav file, or use the built-in tone.")
        label = tk.Label(right, bg=UI["card"], fg=UI["muted"], font=font(9), width=18, anchor="e")
        label.pack(side="left", padx=(0, px(10)))

        def show():
            label.config(text=Path(self.draft[key]).name if self.draft[key] else "Built-in tone")

        def browse():
            path = filedialog.askopenfilename(parent=self.win, filetypes=[("WAV audio", "*.wav")])
            if path:
                self.set(key, path, thumbs=False)
                show()

        def clear():
            self.set(key, "", thumbs=False)
            show()
        Button(right, "", lambda: play(self.draft[key], fallback), "ghost", icon="play", padx=10).pack(side="left")
        Button(right, "Browse…", browse, size=9, height=30).pack(side="left", padx=(px(4), px(4)))
        Button(right, "", clear, "ghost", icon="close", padx=10).pack(side="left")
        show()

    # ---- hotkeys ----

    def build_hotkeys(self, page):
        section(page, "Shortcuts")
        for name, label in HOTKEY_LABELS.items():
            HotkeyField(setting_row(page, label), self.draft["hotkeys"].get(name, ""),
                        lambda combo, n=name: self.draft["hotkeys"].__setitem__(n, combo),
                        self.capturing).pack()
        section(page, "Mouse")
        self.toggle_row(page, "click_through", "Click-through",
                        "Mouse clicks pass through the overlay to the application underneath. "
                        "Use the shortcut above to turn it off.", thumbs=False)
        info = Card(page)
        info.pack(fill="x", pady=(px(14), 0))
        tk.Label(info.body(18, 14), bg=UI["card"], fg=UI["muted"], font=font(9), justify="left", anchor="w",
                 wraplength=px(560), text=(
                     "Select a field, then press the key combination to assign, for example Ctrl+Alt+B or F8. "
                     "Backspace clears a shortcut and Esc cancels. Changes apply when you save.")).pack(anchor="w")

    def capturing(self, active):
        # Don't let the old shortcuts fire while recording new ones.
        if active:
            self.app.hotkeys.stop()
        else:
            self.app.restart_hotkeys()

    # ---- app ----

    def build_app(self, page):
        theme = self.draft["theme"]
        section(page, "Theme")
        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Presets", bg=card.color, fg=UI["text"], font=font(10), anchor="w").pack(anchor="w")
        tk.Label(body, text="A starting point; adjust any colour below.", bg=card.color, fg=UI["muted"], font=font(9),
                 anchor="w").pack(anchor="w", pady=(px(1), px(10)))
        current = next((key for key, (_, bg, accent, text) in THEME_PRESETS.items()
                        if (bg, accent, text) == (theme["bg"], theme["accent"], theme["text"])), None)
        Chips(body, [(key, name) for key, (name, *_) in THEME_PRESETS.items()], current, self.pick_theme_preset).pack(anchor="w")

        for key, title, desc in [("bg", "Background", "The window's background. Cards and borders are derived from it."),
                                 ("accent", "Accent", "Buttons, selections and highlights."),
                                 ("text", "Text", "Headings and labels. Secondary text is derived from it.")]:
            right = setting_row(page, title, desc)
            tk.Label(right, text=theme[key].upper(), bg=UI["card"], fg=UI["muted"], font=("Cascadia Mono", 9), width=8,
                     anchor="e").pack(side="left", padx=(0, px(10)))
            Swatch(right, theme[key], lambda k=key, t=title: self.pick_theme_color(k, t)).pack(side="left")

        card = Card(page)
        card.pack(fill="x", pady=(0, px(6)))
        body = card.body(18, 14)
        tk.Label(body, text="Window background", bg=card.color, fg=UI["text"], font=font(10), anchor="w").pack(anchor="w")
        tk.Label(body, text="An effect or your own image behind the sidebar and page headings.", bg=card.color,
                 fg=UI["muted"], font=font(9), anchor="w").pack(anchor="w", pady=(px(1), px(10)))
        Chips(body, EFFECTS, theme["effect"], lambda v: self.set_theme(effect=v)).pack(anchor="w")
        right = setting_row(page, "Custom image or animation",
                            f"PNG, JPG, BMP, GIF, WebP or APNG. Animations can be up to {MAX_ANIMATION_SECONDS} seconds.")
        tk.Label(right, text=Path(theme["custom_bg"]).name if theme["custom_bg"] else "No file chosen", bg=UI["card"],
                 fg=UI["muted"], font=font(9), width=22, anchor="e").pack(side="left", padx=(0, px(10)))
        Button(right, "Choose file…", self.choose_theme_media, size=9, height=30, icon="open").pack(side="left")
        Button(right, "", lambda: self.set_theme(custom_bg="", effect="none" if theme["effect"] == "custom" else theme["effect"]),
               "ghost", icon="close", padx=10).pack(side="left", padx=(px(4), 0))
        Chips(setting_row(page, "Image fit"), FITS, theme["custom_fit"], lambda v: self.set_theme(custom_fit=v)).pack()
        Slider(setting_row(page, "Background strength"), theme["effect_strength"], 0, 1, 0.05,
               lambda v: self.set_theme(effect_strength=v), lambda v: f"{round(v * 100)}%").pack()
        Slider(setting_row(page, "Background speed"), theme["effect_speed"], 0.25, 3, 0.05,
               lambda v: self.set_theme(effect_speed=v), lambda v: f"{v:.2f}×").pack()

        section(page, "Startup")
        Toggle(setting_row(page, "Start with Windows", f"Opens {APP_NAME} automatically when you sign in. "
                                                       "Applies immediately."),
               winapi.starts_with_windows(), self.set_startup).pack()

        section(page, "Your data")
        right = setting_row(page, "Settings folder", str(DATA_DIR))
        Button(right, "Open folder", self.open_data_dir, icon="folder").pack()

        section(page, "About")
        about = Card(page)
        about.pack(fill="x")
        body = about.body(18, 16)
        self.about_logo = ImageTk.PhotoImage(logo(px(44)))
        tk.Label(body, image=self.about_logo, bg=UI["card"]).pack(side="left", anchor="n")
        text = tk.Frame(body, bg=UI["card"])
        text.pack(side="left", fill="x", expand=True, padx=(px(14), 0))
        tk.Label(text, text=f"{APP_NAME} {VERSION}", bg=UI["card"], fg=UI["text"], font=font(11, "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(text, bg=UI["card"], fg=UI["muted"], font=font(9), anchor="w", justify="left",
                 wraplength=px(520), text=(
                     "A standalone overlay timer for recurring scheduled events. It reads only the system "
                     "clock and does not read, modify or inject into any other app.\n\n"
                     f"{APP_NAME} runs from the system tray (bottom-right of the taskbar). To uninstall, open Windows "
                     f"Settings → Apps → Installed apps → {APP_NAME}.")).pack(anchor="w", pady=(px(4), 0))

    def set_theme(self, **values):
        self.draft["theme"].update(values)
        self.changed(thumbs=False)
        self.theme_changed()

    def pick_theme_preset(self, key):
        _, bg, accent, text = THEME_PRESETS[key]
        self.set_theme(bg=bg, accent=accent, text=text)

    def pick_theme_color(self, key, title):
        picker = ColorPicker(self.win, title, self.draft["theme"][key], lambda c: self.draft["theme"].update({key: c}))
        # Rebuilding mid-drag would close the picker, so apply the new colour when it closes.
        picker.bind("<Destroy>", lambda e: self.theme_changed() if e.widget is picker else None)

    def choose_theme_media(self):
        chosen = self.import_media()
        if chosen:
            self.set_theme(custom_bg=chosen[0], effect="custom")

    def set_startup(self, enabled):
        try:
            winapi.set_start_with_windows(enabled)
        except OSError as e:
            self.say(f"The startup setting could not be changed: {e}", error=True)
            return
        self.say(f"{APP_NAME} will start with Windows." if enabled else f"{APP_NAME} will no longer start with Windows.")

    def open_data_dir(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_DIR)
