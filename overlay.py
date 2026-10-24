"""The overlay: works out the next event, draws its panels, plays alerts, handles input.

The overlay is made of panels, each its own see-through window that can be dragged,
resized (Ctrl + mouse wheel) and hidden on its own, with its own look: the event timer,
the upcoming list (its own panel with the arc, or when the card's list is split off),
the stopwatch, and the notification that pops up for alarms and calendar reminders.
"""
import queue
import time
import tkinter as tk
from datetime import datetime, timedelta

import presets
import ui
import winapi
from alarms import AlarmBook, repeat_summary
from calendar_book import CalendarBook, starts, time_range
from core import (APP_NAME, HOTKEY_LABELS, MAX_UPCOMING, PANELS, SPAWN_BEEP, WARN_BEEP, compile_schedule, last_spawn,
                  load_settings, parse_hotkey, play, save_settings, spawns_after)
from notifications import sample_notice
from render import POSITION_KEYS, Renderer, build_state
from sound import Player
from stopwatch import Stopwatch
from tray import start_tray

SCALE_RANGE = (0.5, 2.5)
POSITIONS = {"timer": ("x", "y"), "list": ("list_x", "list_y"), "stopwatch": ("stopwatch_x", "stopwatch_y"),
             "notification": ("notify_x", "notify_y")}
CLICK_SLOP = 4  # pixels a press can wander and still count as a click rather than a drag


class Panel:
    """One piece of the overlay on screen."""

    def __init__(self, app, window, style, show_key):
        self.app, self.window = app, window
        self.style, self.show_key = style, show_key
        self.name = PANELS[style].lower()
        # Notifications must always be answerable, so they ignore click-through.
        self.always_clickable = style == "notification"
        self.x_key, self.y_key = POSITIONS[style]
        window.overrideredirect(True)
        x, y = app.settings[self.x_key] or 0, app.settings[self.y_key] or 0
        window.geometry(f"1x1+{x}+{y}")
        self.layer = winapi.LayeredWindow(window)
        self.pos = (x, y)  # where this panel should be; passed along with every redraw
        self.size = None
        self.shown = True
        self.buttons = []  # [(action, (x0, y0, x1, y1))] clickable areas, in window pixels
        self._drag = None
        self._press = None
        window.bind("<ButtonPress-1>", self.start_drag)
        window.bind("<B1-Motion>", self.drag)
        window.bind("<ButtonRelease-1>", self.end_drag)
        window.bind("<Button-3>", lambda e: app.show_menu(e, self))
        window.bind("<Control-MouseWheel>", lambda e: app.nudge_scale(self, 0.05 if e.delta > 0 else -0.05))

    def show(self, img, opacity):
        if img is None:
            self.hide()
            return
        if not self.shown:
            self.window.deiconify()
            self.window.attributes("-topmost", True)
            self.layer.set_click_through(self.app.settings["click_through"] and not self.always_clickable)
            self.shown = True
            self.size = None
        s = self.app.settings
        if not self.app.dragging and s[self.x_key] is not None:
            self.pos = (s[self.x_key], s[self.y_key])  # saved position wins unless a drag is under way
        if img.size != self.size:
            self.size = img.size
            self.window.geometry(f"{img.width}x{img.height}+{self.pos[0]}+{self.pos[1]}")
        self.layer.show(img, opacity, self.pos)

    def hide(self):
        if self.shown:
            self.window.withdraw()
            self.shown = False

    def move_to(self, x, y):
        self.pos = (x, y)
        self.window.geometry(f"+{x}+{y}")

    def start_drag(self, e):
        self._press = (e.x_root, e.y_root)
        if self.app.view["locked"]:  # the live value, so the Settings switch applies before saving
            self._drag = None
            return
        # Work from the saved positions: a window's own idea of where it is can lag behind a move.
        s = self.app.settings
        x, y = (s[self.x_key], s[self.y_key]) if s[self.x_key] is not None else self.pos
        # Linked panels ride along, keeping their offset from this one.
        followers = [(p, p.pos[0] - x, p.pos[1] - y) if s[p.x_key] is None else (p, s[p.x_key] - x, s[p.y_key] - y)
                     for p in self.app.linked_to(self)]
        self._drag = (e.x_root - x, e.y_root - y, followers)
        self._moved = {}
        self.app.dragging = True

    def drag(self, e):
        if self._drag and self._press:
            if max(abs(e.x_root - self._press[0]), abs(e.y_root - self._press[1])) <= CLICK_SLOP and not self._moved:
                return  # still just a click
            grab_x, grab_y, followers = self._drag
            x, y = e.x_root - grab_x, e.y_root - grab_y
            # Remember where everything went: the windows report their new spot only after Tk catches up.
            for panel, px, py in [(self, x, y)] + [(p, x + dx, y + dy) for p, dx, dy in followers]:
                panel.move_to(px, py)
                self._moved.update({panel.x_key: px, panel.y_key: py})

    def end_drag(self, e):
        if self._drag and self._moved:
            self.app.set_positions(self._moved)
        elif self._press:
            self.click(e.x_root - self.pos[0], e.y_root - self.pos[1])
        self._drag = self._press = None
        self.app.dragging = False

    def click(self, x, y):
        for action, (x0, y0, x1, y1) in self.buttons:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.app.button_clicked(self, action)
                return


class Overlay:
    def __init__(self, instance=None):
        self.settings = load_settings()
        if presets.migrate(self.settings):  # presets used to live inside settings.json
            save_settings(self.settings)
        self.view = self.settings  # what's drawn; differs while the settings window previews a draft
        self.dragging = False
        for path in self.settings["font_files"]:
            winapi.add_font_file(path)

        # An invisible anchor window that's never shown or hidden. Every panel is its own window,
        # because hiding Tk's main window would also minimise the app window and other panels.
        root = self.root = tk.Tk()
        root.title(APP_NAME)
        root.withdraw()
        ui.init(root)
        ui.apply_theme(self.settings["theme"])
        self.k = ui.env.k
        self.renderer = Renderer()
        self.watch = Stopwatch()
        self.alarms = AlarmBook()
        self.calendar = CalendarBook()
        self.player = Player()
        self.notices = []  # waiting notifications, newest first
        self.sound_started = None
        self.last_check = None
        self.timer = Panel(self, tk.Toplevel(root), "timer", "show_timer")
        self.list = Panel(self, tk.Toplevel(root), "list", "show_list")
        self.stopwatch = Panel(self, tk.Toplevel(root), "stopwatch", "show_stopwatch")
        self.notification = Panel(self, tk.Toplevel(root), "notification", None)
        self.panels = (self.timer, self.list, self.stopwatch, self.notification)
        self.set_click_through(self.settings["click_through"])
        self.hotkeys = winapi.Hotkeys(parse_hotkey)
        self.restart_hotkeys()

        self.last_second = None
        self.dirty = True
        self.hidden = False
        self.alerted = set()
        self.last_topmost = 0.0
        self.settings_window = None
        # Requests from other threads (tray menu, a second launch), run on the Tk thread.
        self.commands = queue.Queue()
        self.tray = start_tray(self)
        if instance:
            instance.listen(lambda: self.commands.put("launch_request"))
        self.loop()
        if presets.request_path().exists():  # started by double-clicking a preset file
            root.after(600, self.launch_request)

    # ---- settings -------------------------------------------------------

    def save(self):
        save_settings(self.settings)

    def keep_positions(self, s):
        # Positions belong to the panels on screen, not to whatever the settings window is editing.
        s.update({key: self.settings[key] for key in POSITION_KEYS})

    def preview(self, draft):
        self.keep_positions(draft)
        self.view = draft
        self.dirty = True

    def cancel_preview(self):
        self.view = self.settings
        self.dirty = True

    def commit(self, new):
        """Keep settings from the settings window. Returns hotkeys that couldn't be registered."""
        self.keep_positions(new)
        self.settings = self.view = new
        ui.apply_theme(new["theme"])
        self.save()
        self.restart_hotkeys()
        self.set_click_through(new["click_through"])
        self.dirty = True
        self.refresh_tray()
        return self.hotkeys.failed

    def update(self, **values):
        """Change saved settings directly (menus, tray, dragging), keeping any live preview in step."""
        self.settings.update(values)
        if self.view is not self.settings:
            self.view.update(values)
        if self.settings_window and self.settings_window.win.winfo_exists():
            self.settings_window.external_change(values)
        self.save()
        self.dirty = True

    def update_style(self, name, **values):
        """Change one panel's look directly (Ctrl + scroll, Reset layout), the same way as update()."""
        self.settings["styles"][name].update(values)
        if self.view is not self.settings:
            self.view["styles"][name].update(values)
        if self.settings_window and self.settings_window.win.winfo_exists():
            self.settings_window.external_style_change(name, values)
        self.save()
        self.dirty = True

    def set_positions(self, positions):
        self.update(**positions)

    def restart_hotkeys(self):
        self.hotkeys.start(self.settings["hotkeys"], HOTKEY_LABELS)

    def add_font(self, path):
        if not winapi.add_font_file(path):
            return False
        self.renderer.fonts.clear()
        return True

    def toggle(self, key):
        # Flip what's live on screen, which may be an unsaved change from the settings window.
        self.update(**{key: not self.view[key]})
        self.refresh_tray()

    def refresh_tray(self):
        if self.tray:
            self.tray.update_menu()  # redraw the tick marks

    def nudge_scale(self, panel, step):
        lo, hi = SCALE_RANGE
        current = self.view["styles"][panel.style]["scale"]
        self.update_style(panel.style, scale=round(min(hi, max(lo, current + step)), 2))

    def open_settings(self, page=None):
        from settings_ui import SettingsWindow
        if self.window_open():
            win = self.settings_window.win
            win.deiconify()
            win.lift()
            win.focus_force()
        else:
            self.settings_window = SettingsWindow(self)
        if page:
            self.settings_window.show(page)

    def window_open(self):
        return self.settings_window is not None and self.settings_window.win.winfo_exists()

    def set_click_through(self, enabled):
        for panel in self.panels:
            panel.layer.set_click_through(enabled and not panel.always_clickable)

    def toggle_click_through(self):
        self.toggle("click_through")
        self.set_click_through(self.view["click_through"])

    def toggle_visible(self):
        self.hidden = not self.hidden
        if self.hidden:
            for panel in self.panels:
                panel.hide()
        self.dirty = True
        self.refresh_tray()

    def linked_to(self, panel):
        if not self.view["link_panels"] or panel is self.notification:
            return []
        return [p for p in self.panels if p is not panel and p.shown and p is not self.notification]

    def hide_panel(self, panel):
        self.update(**{panel.show_key: False})
        self.refresh_tray()

    def reset_layout(self):
        """Put every panel back to its default size and place: the list under the timer, the stopwatch beside it."""
        self.update(x=40, y=40, list_x=None, list_y=None, stopwatch_x=None, stopwatch_y=None, notify_x=None,
                    notify_y=None)
        for name in PANELS:
            self.update_style(name, scale=1.0)
        self.timer.move_to(40, 40)
        for panel in self.panels:
            panel.size = None  # re-apply geometry on the next draw

    def apply_layout(self, layout):
        """Restore a saved layout: positions, sizes and which panels show."""
        positions = {k: v for k, v in layout["positions"].items() if k in POSITION_KEYS}
        self.update(**positions, **layout["show"], layout_preset=layout["name"])
        for name, scale in layout["scales"].items():
            if name in PANELS:
                self.update_style(name, scale=scale)
        for panel in self.panels:
            panel.size = None  # re-apply geometry on the next draw
        self.refresh_tray()

    def place_new(self, panel, img):
        """First showing (or after Reset layout): put a panel next to the timer, or a notification in the
        top-right corner of the screen."""
        if panel is self.notification:
            margin = round(16 * self.k)
            self.set_positions({"notify_x": self.root.winfo_screenwidth() - img.width + margin, "notify_y": margin})
            panel.size = None
            return
        x, y = self.settings["x"], self.settings["y"]
        timer = self.timer
        if timer.shown and timer.size:
            overlap = round(30 * self.k * self.view["styles"]["timer"]["scale"])  # the shadows/glows can overlap
            if panel is self.list:
                x += (timer.size[0] - img.width) // 2
                y += timer.size[1] - overlap
            else:
                x += timer.size[0] - overlap
        self.set_positions({panel.x_key: x, panel.y_key: y})
        panel.size = None

    def button_clicked(self, panel, action):
        if panel is self.notification:
            self.notice_action(action)
        else:
            self.stopwatch_action(action)

    # ---- notifications --------------------------------------------------

    def check_reminders(self):
        """Once a second: ring due alarms and show due calendar reminders."""
        now = datetime.now()
        clock_24h = self.view["clock_24h"]
        for alarm in self.alarms.due(now):
            self.push_notice({"kind": "alarm", "title": alarm["label"] or "Alarm", "detail": repeat_summary(alarm["days"]) if alarm["days"] else "Once",
                              "at": now.replace(second=0, microsecond=0), "source": alarm["id"], "sound": alarm["sound"],
                              "volume": alarm["volume"], "loop": True, "snooze": alarm["snooze"]})
            if self.window_open():
                self.settings_window.data_changed()
        for event in self.calendar.due(now):
            tag = self.calendar.tag(event["tag"])
            detail = time_range(event, clock_24h) + (f" · {tag['name']}" if tag else "")
            self.push_notice({"kind": "event", "title": event["title"], "detail": detail, "at": starts(event),
                              "source": event["id"], "sound": self.view["reminder_sound"],
                              "volume": self.view["reminder_volume"], "loop": False, "snooze": 5})
        # A ringing alarm goes quiet after a while; its notification stays until answered.
        if self.player.looping and self.sound_started and \
                time.monotonic() - self.sound_started > 60 * self.view["alarm_timeout"]:
            self.player.stop()

    def push_notice(self, notice):
        self.notices.insert(0, notice)
        self.play_notice(notice)
        self.dirty = True

    def play_notice(self, notice):
        if notice["volume"] > 0:
            self.player.play(notice["sound"], loop=notice["loop"], volume=notice["volume"])
            self.sound_started = time.monotonic()
        else:
            self.player.stop()

    def notice_action(self, action):
        if not self.notices:
            return
        notice = self.notices.pop(0)
        if action == "snooze" and notice["snooze"]:
            book = {"alarm": self.alarms, "event": self.calendar}.get(notice["kind"])
            if book:
                book.snooze(notice["source"], notice["snooze"])
        elif action == "dismiss_all":
            self.notices.clear()
        # Carry on ringing for the next one waiting if it's an alarm; otherwise go quiet.
        if self.notices and self.notices[0]["loop"]:
            self.play_notice(self.notices[0])
        else:
            self.player.stop()
        self.dirty = True

    def test_notification(self):
        self.push_notice(sample_notice(datetime.now()))

    def stopwatch_action(self, action):
        getattr(self.watch, action)()  # toggle, lap, reset or lap_or_reset
        self.dirty = True
        self.refresh_tray()
        if self.settings_window and self.settings_window.win.winfo_exists():
            self.settings_window.watch_changed()

    def quit(self):
        self.player.stop()
        self.save()
        self.watch.save()
        self.hotkeys.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run_command(self, name):
        {"toggle_visible": self.toggle_visible,
         "toggle_click_through": self.toggle_click_through,
         "toggle_sound": lambda: self.toggle("sound"),
         "toggle_timer": lambda: self.toggle("show_timer"),
         "toggle_list": lambda: self.toggle("show_list"),
         "toggle_stopwatch_panel": lambda: self.toggle("show_stopwatch"),
         "stopwatch_toggle": lambda: self.stopwatch_action("toggle"),
         "stopwatch_lap": lambda: self.stopwatch_action("lap"),
         "stopwatch_reset": lambda: self.stopwatch_action("reset"),
         "dismiss_notification": lambda: self.notice_action("dismiss"),
         "snooze_notification": lambda: self.notice_action("snooze"),
         "open_calendar": lambda: self.open_settings("calendar"),
         "open_alarms": lambda: self.open_settings("alarms"),
         "open_settings": self.open_settings,
         "launch_request": self.launch_request,
         "quit": self.quit}[name]()

    def launch_request(self):
        """Orbitick was launched again (from the Start menu, or by double-clicking a preset file): show the
        window, on the page and with the message the new launch left, if any."""
        request = presets.take_request()
        if not request:
            self.open_settings()
            return
        self.open_settings(request["page"])
        window = self.settings_window
        window.rebuild_page(request["page"])
        window.say(request["message"], error=request.get("error", False))

    def show_menu(self, e, panel):
        s = self.view
        keys = s["hotkeys"]
        hint = lambda name: f"  ({keys[name]})" if keys[name] else ""  # noqa: E731
        items = []
        if panel is self.notification:
            ui.PopupMenu(self.root, [
                ("close", "Dismiss" + hint("dismiss_notification"), lambda: self.notice_action("dismiss"), None),
                ("reset", "Snooze" + hint("snooze_notification"), lambda: self.notice_action("snooze"), None),
                ("close", "Dismiss all", lambda: self.notice_action("dismiss_all"), None),
                None,
                ("settings", "Notification settings…", lambda: self.open_settings("notifications"), None),
            ], e.x_root, e.y_root)
            return
        if panel is self.stopwatch:
            items += [
                ("stop" if self.watch.running else "play", ("Stop" if self.watch.running else "Start") + hint("stopwatch_toggle"),
                 lambda: self.stopwatch_action("toggle"), None),
                ("flag", "Lap" + hint("stopwatch_lap"), lambda: self.stopwatch_action("lap"), None),
                ("reset", "Reset" + hint("stopwatch_reset"), lambda: self.stopwatch_action("reset"), None),
                None,
            ]
        items += [
            ("settings", "Settings…" + hint("open_settings"), self.open_settings, None),
            None,
            ("sound", "Sound alerts", lambda: self.toggle("sound"), s["sound"]),
            ("lock", "Lock positions", lambda: self.toggle("locked"), s["locked"]),
            ("move", "Move panels together", lambda: self.toggle("link_panels"), s["link_panels"]),
            ("pointer", "Click-through" + hint("toggle_click_through"), self.toggle_click_through, s["click_through"]),
            None,
            # Hidden panels come back from the tray icon, Settings, or the hotkey.
            ("hide", f"Hide {panel.name}", lambda: self.hide_panel(panel), None),
            ("hide", "Hide all panels" + hint("toggle_visible"), self.toggle_visible, None),
            ("move", "Reset layout", self.reset_layout, None),
            None,
            ("quit", "Quit", self.quit, None),
        ]
        ui.PopupMenu(self.root, items, e.x_root, e.y_root)

    # ---- update loop ----------------------------------------------------

    def state(self, s):
        schedule = compile_schedule(s["schedule"])
        now = datetime.now() + timedelta(seconds=s["offset_seconds"])
        prev = last_spawn(now, schedule)
        return build_state(now, spawns_after(now, schedule, 1 + MAX_UPCOMING), prev, s, MAX_UPCOMING), prev

    def draw(self, st):
        s = self.view
        styles = s["styles"]
        t = time.monotonic()
        note_img = None
        if self.notices:
            note_img, self.notification.buttons = self.renderer.notification(s, self.notices[0], len(self.notices),
                                                                             self.k, t)
            if self.settings["notify_x"] is None:
                self.place_new(self.notification, note_img)
        self.notification.show(note_img, styles["notification"]["opacity"])
        if self.hidden:  # notifications still appear while the other panels are hidden
            self.dirty = False
            return
        self.timer.show(self.renderer.timer(s, st, self.k, t) if s["show_timer"] else None, styles["timer"]["opacity"])

        list_img = self.renderer.list_panel(s, st, self.k, t) if s["show_list"] else None
        if list_img is not None and self.settings["list_x"] is None:
            self.place_new(self.list, list_img)
        self.list.show(list_img, styles["list"]["opacity"])

        watch_img = None
        if s["show_stopwatch"]:
            watch_img, self.stopwatch.buttons = self.renderer.stopwatch(s, self.watch, self.k, t)
            if self.settings["stopwatch_x"] is None:
                self.place_new(self.stopwatch, watch_img)
        self.stopwatch.show(watch_img, styles["stopwatch"]["opacity"])
        self.last_second = st["second"]
        self.dirty = False

    def loop(self):
        s = self.view
        st, prev = self.state(s)
        if st["second"] != self.last_check:
            self.last_check = st["second"]
            self.check_reminders()
        animating = bool(self.notices) or (not self.hidden and self.renderer.animating(s, self.watch))
        if animating or self.dirty or st["second"] != self.last_second:
            self.draw(st)
        self.alert(st, prev)
        for source in (self.hotkeys.fired, self.commands):
            while not source.empty():
                name = source.get()
                self.run_command(name)
                if name == "quit":
                    return
        # Fullscreen apps can push themselves on top; re-assert every couple of seconds.
        if time.monotonic() - self.last_topmost > 2:
            for panel in self.panels:
                if panel.shown:
                    panel.window.attributes("-topmost", True)
            self.last_topmost = time.monotonic()
        self.root.after(50 if animating else 200, self.loop)

    def alert(self, st, prev):
        s = self.view  # includes unsaved sound choices from the settings window
        now = st["now"]
        self.alerted = {key for key in self.alerted if key[1] > now - timedelta(hours=2)}
        if st["next"] and st["warn"] and ("warn", st["next"][0]) not in self.alerted:
            self.alerted.add(("warn", st["next"][0]))
            if s["sound"]:
                play(s["warn_sound"], WARN_BEEP)
        if prev and (now - prev[0]).total_seconds() < 2 and ("spawn", prev[0]) not in self.alerted:
            self.alerted.add(("spawn", prev[0]))
            if s["sound"]:
                play(s["spawn_sound"], SPAWN_BEEP)
