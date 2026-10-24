"""The Calendar and Alarms pages of the app window, and their editing dialogs.

Both edit your data (calendar.json, alarms.json) directly: every change is saved at once,
so these pages don't use the settings window's Save and Cancel buttons.
"""
import calendar
import re
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog

import winapi
from alarms import DAYS, alarm_date, new_alarm, parse_hm, repeat_summary
from calendar_book import REMINDERS, ends, new_event, starts, time_range
from core import fmt_time
from render import hex_rgb
from sound import AUDIO_TYPES, TONES, Player, describe
from ui import UI, Button, Card, Chips, ColorPicker, MultiChips, Slider, Swatch, Toggle, env, field, font, mark_field, px

VIEWS = [("month", "Month"), ("week", "Week"), ("day", "Day")]


def parse_time_text(text):
    """'7:30', '07:30', '7:30 pm', '7pm' or '19:30' -> 'HH:MM', or None."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?", text.strip().lower())
    if not m:
        return None
    h, mi, half = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if half:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if half == "p" else 0)
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def show_time(hm_text, clock_24h):
    hm = parse_hm(hm_text)
    return fmt_time(datetime(2000, 1, 1, *hm), clock_24h) if hm else hm_text


def strike(size=10, weight="normal"):
    family, size, _ = font(size, weight)
    return (family, size, weight, "overstrike")


def relative_day(day, today=None):
    today = today or date.today()
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return day.strftime("%a %d %b").replace(" 0", " ")


# ---- shared bits ------------------------------------------------------------

class Dialog(tk.Toplevel):
    """A dark modal editor window with a title, a body and a Delete / Cancel / Save footer."""

    def __init__(self, parent, title, on_save, on_delete=None, width=560):
        super().__init__(parent, bg=UI["bg"])
        self.title(title)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(parent)
        self.on_save = on_save
        tk.Label(self, text=title, bg=UI["bg"], fg=UI["text"], font=font(14, "bold", True), anchor="w").pack(
            fill="x", padx=px(24), pady=(px(20), px(10)))
        self.body = tk.Frame(self, bg=UI["bg"], width=px(width))
        self.body.pack(fill="both", expand=True, padx=px(24))
        footer = tk.Frame(self, bg=UI["bg"])
        footer.pack(fill="x", padx=px(24), pady=(px(14), px(20)))
        Button(footer, "Save", self.save, "primary", padx=22).pack(side="right")
        Button(footer, "Cancel", self.destroy).pack(side="right", padx=(0, px(8)))
        if on_delete:
            Button(footer, "Delete", lambda: (on_delete(), self.destroy()), "danger", icon="delete").pack(side="left")
        self.status = tk.Label(footer, bg=UI["bg"], fg=UI["danger"], font=font(9), anchor="w", justify="left",
                               wraplength=px(260))
        self.status.pack(side="left", fill="x", expand=True, padx=(px(10), 0))
        self.bind("<Escape>", lambda e: self.destroy())

    def open(self, parent):
        winapi.style_window(self, hex_rgb(UI["bg"]), dark=not UI["light"])
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 3)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_force()

    def label(self, parent, text):
        tk.Label(parent, text=text, bg=parent["bg"], fg=UI["muted"], font=font(9), anchor="w").pack(
            fill="x", pady=(px(10), px(4)))

    def save(self):
        error = self.on_save()
        if error:
            self.status.config(text=error)
        else:
            self.destroy()


class SoundPicker(tk.Frame):
    """Built-in tones as chips, or your own audio file, with a play/stop preview."""

    def __init__(self, parent, value, on_change, volume=lambda: 0.8):
        super().__init__(parent, bg=parent["bg"])
        self.value, self.on_change, self.volume = value, on_change, volume
        self.player = Player()
        options = [(f"tone:{key}", name) for key, name in TONES]
        current = value if value.startswith("tone:") else None
        self.chips = Chips(self, options, current, self.pick)
        self.chips.pack(anchor="w")
        row = tk.Frame(self, bg=parent["bg"])
        row.pack(anchor="w", pady=(px(8), 0))
        Button(row, "Your own file…", self.choose, size=9, height=30, icon="open").pack(side="left")
        self.file_label = tk.Label(row, bg=parent["bg"], fg=UI["muted"], font=font(9), anchor="w")
        self.file_label.pack(side="left", padx=(px(10), px(10)))
        self.play_button = Button(row, "Play", self.toggle_preview, "ghost", icon="play", size=9, height=30,
                                  labels=("Stop",))
        self.play_button.pack(side="left")
        self.bind("<Destroy>", lambda e: self.player.stop() if e.widget is self else None)
        self.show()

    def show(self):
        self.file_label.config(text="" if self.value.startswith("tone:") else describe(self.value))

    def pick(self, value):
        self.value = value
        self.on_change(value)
        self.show()
        self.preview()

    def choose(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Choose a sound", filetypes=AUDIO_TYPES)
        if path:
            self.value = path
            self.chips.set(None)
            self.on_change(path)
            self.show()

    def preview(self):
        self.player.play(self.value, loop=False, volume=self.volume())
        self.play_button.set_text("Stop")
        self.after(4000, self.stop_preview)

    def stop_preview(self):
        self.player.stop()
        if self.winfo_exists():
            self.play_button.set_text("Play")

    def toggle_preview(self):
        if self.player.alias:
            self.stop_preview()
        else:
            self.preview()


class MiniMonth(tk.Frame):
    """A small month grid for picking a date."""

    def __init__(self, parent, value, on_pick):
        super().__init__(parent, bg=parent["bg"])
        self.value, self.on_pick = value, on_pick
        self.month = value.replace(day=1)
        head = tk.Frame(self, bg=parent["bg"])
        head.pack(fill="x")
        Button(head, "", lambda: self.shift(-1), "ghost", icon="prev", padx=8, height=28).pack(side="left")
        self.title = tk.Label(head, bg=parent["bg"], fg=UI["text"], font=font(10, "bold"))
        self.title.pack(side="left", expand=True)
        Button(head, "", lambda: self.shift(1), "ghost", icon="next", padx=8, height=28).pack(side="right")
        self.grid_frame = tk.Frame(self, bg=parent["bg"])
        self.grid_frame.pack(pady=(px(6), 0))
        self.draw()

    def shift(self, months):
        m = self.month.month - 1 + months
        self.month = date(self.month.year + m // 12, m % 12 + 1, 1)
        self.draw()

    def draw(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.title.config(text=self.month.strftime("%B %Y"))
        bg = self["bg"]
        for col, name in enumerate(DAYS):
            tk.Label(self.grid_frame, text=name[:2], bg=bg, fg=UI["faint"], font=font(8), width=4).grid(row=0, column=col)
        today = date.today()
        for row, week in enumerate(calendar.Calendar().monthdatescalendar(self.month.year, self.month.month), 1):
            for col, day in enumerate(week):
                selected = day == self.value
                color = UI["on_accent"] if selected else (UI["accent"] if day == today else
                                                          UI["text"] if day.month == self.month.month else UI["faint"])
                cell = tk.Label(self.grid_frame, text=day.day, width=4, height=1, bg=UI["accent"] if selected else bg,
                                fg=color, font=font(9, "bold" if selected or day == today else "normal"), cursor="hand2")
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, d=day: self.pick(d))

    def pick(self, day):
        self.value = day
        if day.month != self.month.month:
            self.month = day.replace(day=1)
        self.draw()
        self.on_pick(day)


def text_box(parent, value, height=4):
    wrap = tk.Frame(parent, bg=UI["field"], highlightthickness=1, highlightbackground=UI["border"])
    box = tk.Text(wrap, height=height, width=40, bg=UI["field"], fg=UI["text"], insertbackground=UI["text"],
                  relief="flat", bd=0, font=font(10), wrap="word", selectbackground=UI["accent"],
                  selectforeground=UI["on_accent"])
    box.pack(fill="both", expand=True, padx=px(10), pady=px(8))
    box.insert("1.0", value)
    wrap.box = box
    return wrap


# ---- event and tag editors -----------------------------------------------------

class EventDialog(Dialog):
    def __init__(self, page, event=None, day=None):
        self.page, self.book = page, page.book
        self.is_new = event is None
        self.event = dict(event) if event else new_event(date=(day or date.today()).isoformat(),
                                                          start=page.suggest_start(day))
        super().__init__(page.window.win, "New event" if self.is_new else "Edit event", self.commit,
                         None if self.is_new else self.delete)
        body, e, clock_24h = self.body, self.event, page.clock_24h()

        self.label(body, "Title")
        self.title_var = tk.StringVar(value="" if self.is_new else e["title"])
        self.title_field = field(body, self.title_var, width=46, size=11)
        self.title_field.pack(fill="x")

        cols = tk.Frame(body, bg=UI["bg"])
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=UI["bg"])
        left.pack(side="left", anchor="n")
        self.label(left, "Date")
        self.day = date.fromisoformat(e["date"])
        MiniMonth(left, self.day, self.pick_day).pack(anchor="w")

        right = tk.Frame(cols, bg=UI["bg"])
        right.pack(side="left", anchor="n", fill="x", expand=True, padx=(px(24), 0))
        self.label(right, "All day")
        self.all_day = Toggle(right, e["all_day"], lambda v: self.show_times())
        self.all_day.pack(anchor="w")
        self.times = tk.Frame(right, bg=UI["bg"])
        self.times.pack(fill="x")
        self.label(self.times, "Starts")
        self.start_var = tk.StringVar(value=show_time(e["start"], clock_24h))
        self.start_field = field(self.times, self.start_var, width=12)
        self.start_field.pack(anchor="w")
        self.label(self.times, "Ends (optional)")
        self.end_var = tk.StringVar(value=show_time(e["end"], clock_24h) if e["end"] else "")
        self.end_field = field(self.times, self.end_var, width=12)
        self.end_field.pack(anchor="w")
        tk.Label(self.times, text="For example 2:30 PM or 14:30.", bg=UI["bg"], fg=UI["faint"], font=font(8)).pack(
            anchor="w", pady=(px(4), 0))
        self.show_times()

        self.label(body, "Tag")
        tags = [("", "None")] + [(t["id"], t["name"]) for t in self.book.tags]
        self.tag = e["tag"] if self.book.tag(e["tag"]) else ""
        Chips(body, tags, self.tag, lambda v: setattr(self, "tag", v)).pack(anchor="w")

        self.label(body, "Reminder")
        self.reminder = e["reminder"]
        Chips(body, [(str(m), name) for m, name in REMINDERS], str(self.reminder),
              lambda v: setattr(self, "reminder", None if v == "None" else int(v))).pack(anchor="w")

        self.label(body, "Notes")
        self.notes = text_box(body, e["notes"], height=3)
        self.notes.pack(fill="x")
        self.open(page.window.win)
        self.title_field.entry.focus_set()

    def pick_day(self, day):
        self.day = day

    def show_times(self):
        if self.all_day.value:
            self.times.pack_forget()
        else:
            self.times.pack(fill="x")

    def commit(self):
        title = self.title_var.get().strip()
        if not title:
            mark_field(self.title_field, True)
            return "Enter a title for the event."
        e = self.event
        e.update(title=title, date=self.day.isoformat(), all_day=self.all_day.value, tag=self.tag,
                 reminder=self.reminder, notes=self.notes.box.get("1.0", "end").strip())
        if not e["all_day"]:
            start = parse_time_text(self.start_var.get())
            end = parse_time_text(self.end_var.get()) if self.end_var.get().strip() else ""
            mark_field(self.start_field, start is None)
            mark_field(self.end_field, end is None)
            if start is None:
                return "Enter a start time, such as 2:30 PM or 14:30."
            if end is None:
                return "Enter a valid end time, or leave it blank."
            if end and parse_hm(end) <= parse_hm(start):
                mark_field(self.end_field, True)
                return "The end time must be after the start time."
            e.update(start=start, end=end)
        if self.is_new or ends(e) > datetime.now():
            e["done"] = e["done"] and not self.is_new
        self.book.put(e)
        self.page.goto(self.day)
        return None

    def delete(self):
        self.book.delete(self.event["id"])
        self.page.refresh()


class TagDialog(Dialog):
    def __init__(self, page):
        self.page, self.book = page, page.book
        self.tags = [dict(t) for t in self.book.tags]
        super().__init__(page.window.win, "Tags", self.commit, width=440)
        tk.Label(self.body, text="Tags colour-code your events. Deleting a tag keeps its events.", bg=UI["bg"],
                 fg=UI["muted"], font=font(9), anchor="w").pack(fill="x")
        self.rows = tk.Frame(self.body, bg=UI["bg"])
        self.rows.pack(fill="x", pady=(px(10), 0))
        Button(self.body, "Add tag", self.add, icon="add", size=9, height=30).pack(anchor="w", pady=(px(8), 0))
        self.draw()
        self.open(page.window.win)

    def draw(self):
        for child in self.rows.winfo_children():
            child.destroy()
        self.vars = []
        for tag in self.tags:
            card = Card(self.rows)
            card.pack(fill="x", pady=(0, px(6)))
            body = card.body(12, 8)
            swatch = Swatch(body, tag["color"], lambda t=tag: self.recolor(t), 34, 26)
            swatch.pack(side="left")
            var = tk.StringVar(value=tag["name"])
            self.vars.append((tag, var))
            field(body, var, width=26).pack(side="left", fill="x", expand=True, padx=(px(10), px(10)))
            Button(body, "", lambda t=tag: self.remove(t), "ghost", icon="delete", padx=10, height=30).pack(side="right")

    def recolor(self, tag):
        def changed(color):
            tag["color"] = color
        picker = ColorPicker(self, f"Colour for {tag['name']}", tag["color"], changed)
        picker.bind("<Destroy>", lambda e: self.draw() if e.widget is picker and self.winfo_exists() else None)

    def sync_names(self):
        for tag, var in self.vars:
            tag["name"] = var.get().strip() or tag["name"]

    def add(self):
        self.sync_names()
        self.tags.append(self.book.new_tag())
        self.draw()

    def remove(self, tag):
        self.sync_names()
        self.tags.remove(tag)
        self.draw()

    def commit(self):
        self.sync_names()
        kept = {t["id"] for t in self.tags}
        for old in list(self.book.tags):
            if old["id"] not in kept:
                self.book.delete_tag(old["id"])
        for tag in self.tags:
            self.book.put_tag(tag)
        self.page.refresh()
        return None


# ---- calendar page ---------------------------------------------------------------

class CalendarPage:
    def __init__(self, window, page):
        self.window, self.app, self.book = window, window.app, window.app.calendar
        self.mode, self.day = "month", date.today()
        bar = tk.Frame(page, bg=UI["bg"])
        bar.pack(fill="x", pady=(px(4), px(12)))
        self.view_chips = Chips(bar, VIEWS, self.mode, self.set_mode)
        self.view_chips.pack(side="left")
        Button(bar, "", lambda: self.step(-1), "ghost", icon="prev", padx=10).pack(side="left", padx=(px(10), 0))
        Button(bar, "", lambda: self.step(1), "ghost", icon="next", padx=10).pack(side="left")
        Button(bar, "Today", lambda: self.goto(date.today()), size=9, height=30).pack(side="left", padx=(px(4), 0))
        Button(bar, "New event", lambda: EventDialog(self, day=self.day), "primary", icon="add").pack(side="right")
        Button(bar, "Tags", lambda: TagDialog(self), "ghost", icon="tag").pack(side="right", padx=(0, px(6)))
        self.heading = tk.Label(page, bg=UI["bg"], fg=UI["text"], font=font(14, "bold", True), anchor="w")
        self.heading.pack(fill="x", pady=(0, px(10)))
        self.body = tk.Frame(page, bg=UI["bg"])
        self.body.pack(fill="both", expand=True)
        self.refresh()

    def clock_24h(self):
        return self.window.draft["clock_24h"]

    def suggest_start(self, day):
        """The next whole hour today, or 9 AM on other days."""
        now = datetime.now()
        if (day or now.date()) == now.date() and now.hour < 23:
            return f"{now.hour + 1:02d}:00"
        return "09:00"

    def set_mode(self, mode):
        self.mode = mode
        self.refresh()

    def step(self, direction):
        if self.mode == "month":
            m = self.day.month - 1 + direction
            year, month = self.day.year + m // 12, m % 12 + 1
            self.day = date(year, month, min(self.day.day, calendar.monthrange(year, month)[1]))
        else:
            self.day += timedelta(days=7 if self.mode == "week" else 1) * direction
        self.refresh()

    def goto(self, day, mode=None):
        self.day = day
        if mode:
            self.mode = mode
            self.view_chips.set(mode)
        self.refresh()

    def items(self, day):
        """[(sort time, kind, object)] for a day: events and alarms together, in time order."""
        out = [(starts(e) if not e["all_day"] else datetime.combine(day, datetime.min.time()), "event", e)
               for e in self.book.on_day(day)]
        out += [(datetime.combine(day, t), "alarm", a) for t, a in self.app.alarms.on_day(day)]
        return sorted(out, key=lambda item: (item[0], item[1] == "alarm"))

    def refresh(self):
        for child in self.body.winfo_children():
            child.destroy()
        getattr(self, f"draw_{self.mode}")()

    def item_label(self, parent, kind, obj, compact=True, wrap=0):
        """An event or alarm: a coloured dot or bell, time and title; done events are crossed off.
        With `wrap`, the time sits on its own line and the title wraps to that width."""
        bg = parent["bg"]
        row = tk.Frame(parent, bg=bg, cursor="hand2")
        clock_24h = self.clock_24h()
        if kind == "alarm":
            icon, color = ("" if env.icons else "•"), UI["accent"]
            text, done = f"{show_time(obj['time'], clock_24h)} {obj['label'] or 'Alarm'}", False
        else:
            tag = self.book.tag(obj["tag"])
            icon, color = "●", tag["color"] if tag else UI["muted"]
            when = "" if obj["all_day"] else show_time(obj["start"], clock_24h) + " "
            text, done = when + obj["title"], self.book.is_done(obj)
        icon_font = (env.icons, 8) if kind == "alarm" and env.icons else font(8)
        text_font = strike(8 if compact else 10) if done else font(8 if compact else 10)
        if wrap:
            if kind == "alarm":
                when, title = show_time(obj["time"], clock_24h), obj["label"] or "Alarm"
            elif obj["all_day"]:
                when, title = "All day", obj["title"]
            else:
                when, title = show_time(obj["start"], clock_24h), obj["title"]
            head = tk.Frame(row, bg=bg)
            head.pack(fill="x")
            tk.Label(head, text=icon, bg=bg, fg=color, font=icon_font).pack(side="left")
            tk.Label(head, text=when, bg=bg, fg=UI["muted"], font=font(8), anchor="w").pack(side="left", padx=(px(3), 0))
            tk.Label(row, text=title, bg=bg, fg=UI["faint"] if done else UI["text"], anchor="w", justify="left",
                     wraplength=wrap, font=text_font).pack(fill="x")
        else:
            tk.Label(row, text=icon, bg=bg, fg=color, font=icon_font).pack(side="left")
            tk.Label(row, text=text, bg=bg, fg=UI["faint"] if done else UI["text"], anchor="w",
                     font=text_font).pack(side="left", fill="x", padx=(px(3), 0))
        target = (lambda e: AlarmDialog(self.window.alarms_page, obj)) if kind == "alarm" else (
            lambda e: EventDialog(self, obj))
        def bind_all_children(widget):
            widget.bind("<Button-1>", target)
            for child in widget.winfo_children():
                bind_all_children(child)
        bind_all_children(row)
        return row

    # ---- month ----

    def draw_month(self):
        self.heading.config(text=self.day.strftime("%B %Y"))
        grid = tk.Frame(self.body, bg=UI["bg"])
        grid.pack(fill="both", expand=True)
        for col, name in enumerate(DAYS):
            grid.columnconfigure(col, weight=1, uniform="day")
            tk.Label(grid, text=name.upper(), bg=UI["bg"], fg=UI["faint"], font=font(8, "bold"), anchor="w").grid(
                row=0, column=col, sticky="w", padx=px(6), pady=(0, px(4)))
        today = date.today()
        weeks = calendar.Calendar().monthdatescalendar(self.day.year, self.day.month)
        for row, week in enumerate(weeks, 1):
            grid.rowconfigure(row, minsize=px(92))
            for col, day in enumerate(week):
                in_month = day.month == self.day.month
                card = Card(grid, UI["card"] if in_month else UI["side"], 8, UI["accent"] if day == today else None)
                card.grid(row=row, column=col, sticky="nsew", padx=px(2), pady=px(2))
                body = card.body(8, 6)
                tk.Label(body, text=day.day, bg=card.color, anchor="w",
                         fg=UI["accent"] if day == today else (UI["text"] if in_month else UI["faint"]),
                         font=font(9, "bold" if day == today else "normal")).pack(fill="x")
                items = self.items(day)
                for _, kind, obj in items[:3]:
                    self.item_label(body, kind, obj).pack(fill="x")
                if len(items) > 3:
                    tk.Label(body, text=f"+{len(items) - 3} more", bg=card.color, fg=UI["muted"], font=font(8),
                             anchor="w").pack(fill="x")
                for w in (card, body, *body.winfo_children()[:1]):
                    w.bind("<Button-1>", lambda e, d=day: self.goto(d, "day"))
                    w.bind("<Double-Button-1>", lambda e, d=day: EventDialog(self, day=d))

    # ---- week ----

    def draw_week(self):
        start = self.day - timedelta(days=self.day.weekday())
        end = start + timedelta(days=6)
        self.heading.config(text=f"{start.day} {start:%B}" + (f" {start.year}" if start.year != end.year else "")
                            + f" – {end.day} {end:%B %Y}")
        grid = tk.Frame(self.body, bg=UI["bg"])
        grid.pack(fill="both", expand=True)
        today = date.today()
        for col in range(7):
            day = start + timedelta(days=col)
            grid.columnconfigure(col, weight=1, uniform="day")
            card = Card(grid, UI["card"], 8, UI["accent"] if day == today else None)
            card.grid(row=0, column=col, sticky="nsew", padx=px(2))
            body = card.body(8, 8)
            head = tk.Label(body, text=f"{DAYS[col]} {day.day}", bg=card.color, anchor="w", cursor="hand2",
                            fg=UI["accent"] if day == today else UI["text"], font=font(10, "bold"))
            head.pack(fill="x", pady=(0, px(6)))
            head.bind("<Button-1>", lambda e, d=day: self.goto(d, "day"))
            items = self.items(day)
            for _, kind, obj in items:
                self.item_label(body, kind, obj, wrap=px(96)).pack(fill="x", pady=(0, px(6)))
            if not items:
                tk.Label(body, text="Free", bg=card.color, fg=UI["faint"], font=font(8), anchor="w").pack(fill="x")
            add = tk.Label(body, text="+ Add", bg=card.color, fg=UI["muted"], font=font(8), anchor="w", cursor="hand2")
            add.pack(fill="x", pady=(px(8), 0))
            add.bind("<Button-1>", lambda e, d=day: EventDialog(self, day=d))
        grid.rowconfigure(0, minsize=px(360))

    # ---- day ----

    def draw_day(self):
        self.heading.config(text=self.day.strftime("%A, ") + f"{self.day.day} " + self.day.strftime("%B %Y"))
        items = self.items(self.day)
        if not items:
            card = Card(self.body)
            card.pack(fill="x")
            body = card.body(18, 18)
            tk.Label(body, text="Nothing on this day.", bg=card.color, fg=UI["muted"], font=font(10)).pack(side="left")
            Button(body, "New event", lambda: EventDialog(self, day=self.day), icon="add", size=9, height=30).pack(side="right")
            return
        clock_24h = self.clock_24h()
        for _, kind, obj in items:
            card = Card(self.body)
            card.pack(fill="x", pady=(0, px(6)))
            body = card.body(16, 12)
            left = tk.Frame(body, bg=card.color, width=px(140))
            left.pack(side="left", fill="y")
            left.pack_propagate(False)
            middle = tk.Frame(body, bg=card.color)
            middle.pack(side="left", fill="x", expand=True, padx=(px(12), 0))
            right = tk.Frame(body, bg=card.color)
            right.pack(side="right")
            if kind == "alarm":
                tk.Label(left, text=show_time(obj["time"], clock_24h), bg=card.color, fg=UI["accent"], font=font(10, "bold"),
                         anchor="w").pack(fill="x")
                tk.Label(middle, text=obj["label"] or "Alarm", bg=card.color, fg=UI["text"], font=font(11, "bold"),
                         anchor="w").pack(fill="x")
                tk.Label(middle, text=f"Alarm · {repeat_summary(obj['days'])}", bg=card.color, fg=UI["muted"], font=font(9),
                         anchor="w").pack(fill="x")
                Button(right, "", lambda a=obj: AlarmDialog(self.window.alarms_page, a), "ghost", icon="edit", padx=10,
                       height=30).pack(side="left")
                continue
            done = self.book.is_done(obj)
            tag = self.book.tag(obj["tag"])
            tk.Label(left, text=time_range(obj, clock_24h), bg=card.color, fg=UI["muted"], font=font(9), anchor="w",
                     wraplength=px(135), justify="left").pack(fill="x")
            tk.Label(middle, text=obj["title"], bg=card.color, fg=UI["faint"] if done else UI["text"], anchor="w",
                     font=strike(11, "bold") if done else font(11, "bold")).pack(fill="x")
            meta = tk.Frame(middle, bg=card.color)
            meta.pack(fill="x")
            if tag:
                tk.Label(meta, text=f"● {tag['name']}", bg=card.color, fg=tag["color"], font=font(9)).pack(side="left")
            if done:
                tk.Label(meta, text="Done", bg=card.color, fg=UI["muted"], font=font(9)).pack(side="left", padx=(px(8), 0))
            if obj["notes"]:
                tk.Label(middle, text=obj["notes"].splitlines()[0], bg=card.color, fg=UI["muted"], font=font(9),
                         anchor="w").pack(fill="x")
            if obj["done"] or not done:  # events that are simply over are crossed off automatically
                Button(right, "Undo" if obj["done"] else "Mark done", lambda e=obj: self.toggle_done(e), size=9,
                       height=30, icon="check", labels=("Mark done", "Undo")).pack(side="left", padx=(0, px(4)))
            Button(right, "", lambda e=obj: EventDialog(self, e), "ghost", icon="edit", padx=10, height=30).pack(side="left")
            Button(right, "", lambda e=obj: self.delete(e), "ghost", icon="delete", padx=10, height=30).pack(side="left")

    def toggle_done(self, event):
        self.book.set_done(event["id"], not event["done"])
        self.refresh()

    def delete(self, event):
        self.book.delete(event["id"])
        self.refresh()


# ---- alarms ------------------------------------------------------------------------

class AlarmDialog(Dialog):
    def __init__(self, page, alarm=None):
        self.page, self.book = page, page.app.alarms
        self.is_new = alarm is None
        self.alarm = dict(alarm) if alarm else new_alarm()
        super().__init__(page.window.win, "New alarm" if self.is_new else "Edit alarm", self.commit,
                         None if self.is_new else self.delete)
        body, a = self.body, self.alarm
        clock_24h = page.window.draft["clock_24h"]

        cols = tk.Frame(body, bg=UI["bg"])
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=UI["bg"])
        left.pack(side="left", anchor="n")
        self.label(left, "Time")
        self.time_var = tk.StringVar(value=show_time(a["time"], clock_24h))
        self.time_field = field(left, self.time_var, width=10, size=16)
        self.time_field.pack(anchor="w")
        tk.Label(left, text="For example 7:30 AM or 19:30.", bg=UI["bg"], fg=UI["faint"], font=font(8)).pack(
            anchor="w", pady=(px(4), 0))
        right = tk.Frame(cols, bg=UI["bg"])
        right.pack(side="left", anchor="n", fill="x", expand=True, padx=(px(20), 0))
        self.label(right, "Label")
        self.label_var = tk.StringVar(value=a["label"])
        field(right, self.label_var, width=30).pack(fill="x")

        self.label(body, "Repeat")
        quick = [("once", "Once"), ("weekdays", "Weekdays"), ("weekends", "Weekends"), ("daily", "Every day")]
        self.quick = Chips(body, quick, None, self.quick_pick)
        self.quick.pack(anchor="w")
        self.days = MultiChips(body, list(enumerate(DAYS)), a["days"], self.days_picked)
        self.days.pack(anchor="w", pady=(px(6), 0))
        tk.Label(body, text="Pick days to repeat every week, or none to ring once on a date.", bg=UI["bg"],
                 fg=UI["faint"], font=font(8), anchor="w").pack(fill="x", pady=(px(4), 0))

        # One-time alarms: which day.
        self.date_frame = tk.Frame(body, bg=UI["bg"])
        self.label(self.date_frame, "Date")
        today = date.today()
        self.day = alarm_date(a) or today
        quick_days = tk.Frame(self.date_frame, bg=UI["bg"])
        quick_days.pack(anchor="w")
        self.day_chips = Chips(quick_days, [("today", "Today"), ("tomorrow", "Tomorrow")], None, self.quick_day)
        self.day_chips.pack(side="left")
        self.month = MiniMonth(self.date_frame, self.day, self.pick_day)
        self.month.pack(anchor="w", pady=(px(6), 0))
        self.sync_day_chips()
        self.repeat_end = tk.Frame(body, bg=UI["bg"])  # marks where the date section goes
        self.repeat_end.pack(fill="x")
        self.days_picked(set(a["days"]))

        self.label(body, "Sound")
        self.volume_value = a["volume"]
        SoundPicker(body, a["sound"], lambda v: self.alarm.update(sound=v), lambda: self.volume_value).pack(anchor="w")
        sliders = tk.Frame(body, bg=UI["bg"])
        sliders.pack(fill="x", pady=(px(6), 0))
        self.label(sliders, "Volume")
        Slider(sliders, a["volume"], 0.05, 1, 0.05, lambda v: setattr(self, "volume_value", v),
               lambda v: f"{round(v * 100)}%", length=260).pack(anchor="w")
        self.label(sliders, "Snooze length")
        self.snooze_value = a["snooze"]
        Slider(sliders, a["snooze"], 0, 30, 1, lambda v: setattr(self, "snooze_value", int(v)),
               lambda v: "Off" if not v else f"{int(v)} min", length=260).pack(anchor="w")
        self.open(page.window.win)
        self.time_field.entry.focus_set()

    def quick_pick(self, key):
        days = {"once": [], "weekdays": [0, 1, 2, 3, 4], "weekends": [5, 6], "daily": list(range(7))}[key]
        self.days.set(days)
        self.days_picked(set(days))

    def days_picked(self, days):
        self.alarm["days"] = sorted(days)
        quick = {(): "once", (0, 1, 2, 3, 4): "weekdays", (5, 6): "weekends", tuple(range(7)): "daily"}
        self.quick.set(quick.get(tuple(sorted(days))))
        if days:
            self.date_frame.pack_forget()
        elif not self.date_frame.winfo_ismapped():
            self.date_frame.pack(fill="x", before=self.repeat_end)

    def quick_day(self, key):
        self.pick_day(date.today() + timedelta(days=1 if key == "tomorrow" else 0))
        self.month.value = self.day
        self.month.month = self.day.replace(day=1)
        self.month.draw()

    def pick_day(self, day):
        self.day = day
        self.sync_day_chips()

    def sync_day_chips(self):
        today = date.today()
        self.day_chips.set({today: "today", today + timedelta(days=1): "tomorrow"}.get(self.day))

    def commit(self):
        hm = parse_time_text(self.time_var.get())
        mark_field(self.time_field, hm is None)
        if hm is None:
            return "Enter a time, such as 7:30 AM or 19:30."
        if not self.alarm["days"]:
            if datetime.combine(self.day, datetime.strptime(hm, "%H:%M").time()) <= datetime.now():
                mark_field(self.time_field, True)
                return "That time has already passed on this day. Choose a later time or another date."
            self.alarm["date"] = self.day.isoformat()
        self.alarm.update(time=hm, label=self.label_var.get().strip() or "Alarm", volume=self.volume_value,
                          snooze=self.snooze_value, enabled=True)
        self.book.put(self.alarm)
        self.page.window.data_changed()
        return None

    def delete(self):
        self.book.delete(self.alarm["id"])
        self.page.window.data_changed()


class AlarmsPage:
    def __init__(self, window, page):
        self.window, self.app, self.book = window, window.app, window.app.alarms
        bar = tk.Frame(page, bg=UI["bg"])
        bar.pack(fill="x", pady=(px(4), px(12)))
        Button(bar, "New alarm", lambda: AlarmDialog(self), "primary", icon="add").pack(side="left")
        tk.Label(bar, text="Alarms ring while Orbitick is running, even with the panels hidden.", bg=UI["bg"],
                 fg=UI["faint"], font=font(9)).pack(side="right")
        self.list = tk.Frame(page, bg=UI["bg"])
        self.list.pack(fill="x")
        self.refresh()

    def next_ring(self, alarm):
        try:
            at = datetime.fromisoformat(alarm["next"]) if alarm["next"] else None
        except ValueError:
            at = None
        if not at:
            return "Off"
        return f"Rings {relative_day(at.date())} at {fmt_time(at, self.window.draft['clock_24h'])}"

    def refresh(self):
        for child in self.list.winfo_children():
            child.destroy()
        if not self.book.alarms:
            card = Card(self.list)
            card.pack(fill="x")
            body = card.body(18, 18)
            tk.Label(body, text="No alarms yet.", bg=card.color, fg=UI["muted"], font=font(10)).pack(side="left")
            return
        clock_24h = self.window.draft["clock_24h"]
        for alarm in self.book.alarms:
            card = Card(self.list)
            card.pack(fill="x", pady=(0, px(6)))
            body = card.body(20, 14)
            left = tk.Frame(body, bg=card.color)
            left.pack(side="left", fill="x", expand=True)
            on = alarm["enabled"]
            tk.Label(left, text=show_time(alarm["time"], clock_24h), bg=card.color, fg=UI["text"] if on else UI["faint"],
                     font=font(24, "bold", True), anchor="w").pack(fill="x")
            detail = f"{alarm['label'] or 'Alarm'} · {repeat_summary(alarm['days'])} · {self.next_ring(alarm)}"
            tk.Label(left, text=detail, bg=card.color, fg=UI["muted"] if on else UI["faint"], font=font(9),
                     anchor="w").pack(fill="x")
            right = tk.Frame(body, bg=card.color)
            right.pack(side="right")
            Button(right, "", lambda a=alarm: AlarmDialog(self, a), "ghost", icon="edit", padx=10, height=30).pack(
                side="left", padx=(0, px(8)))
            Toggle(right, on, lambda v, a=alarm: self.switch(a, v)).pack(side="left")

    def switch(self, alarm, on):
        self.book.set_enabled(alarm["id"], on)
        self.window.data_changed()
