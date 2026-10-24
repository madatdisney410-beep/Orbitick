"""1.4.0: app window, alarms, calendar, notifications, theme. Sounds play at zero volume."""
import json
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

DATA = OUT / "v14"
DATA.mkdir(exist_ok=True)
core.SETTINGS_PATH = DATA / "settings.json"
for name in ("settings.json", "alarms.json", "calendar.json", "stopwatch.json"):
    if (DATA / name).exists():
        (DATA / name).unlink()
import overlay  # noqa: E402
import planner_ui  # noqa: E402
from alarms import new_alarm  # noqa: E402
from calendar_book import new_event  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
app.update(show_stopwatch=True)
root = app.root
errors, results = [], []
root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
SILENT = 0.0004  # rounds to MCI volume 0: the sound path runs, nothing is heard


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def grab(widget, name):
    if widget.winfo_toplevel().state() == "iconic":  # in case it was minimised while the test ran
        widget.winfo_toplevel().deiconify()
    widget.winfo_toplevel().lift()
    widget.update()
    x, y, w, h = widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"v14_{name}.png")


def win():
    return app.settings_window


seq = []


def step(fn, delay=400):
    seq.append((fn, delay))


def run(i=0):
    if i >= len(seq) or errors:
        print("errors:", len(errors))
        for e in errors:
            print(e)
        print(f"{sum(results)}/{len(results)} checks passed")
        app.quit()
        return
    try:
        seq[i][0]()
    except Exception:
        errors.append(traceback.format_exc())
    root.after(seq[i][1], lambda: run(i + 1))


# ---- the app window ----
step(lambda: app.open_settings(), 1800)


def window_basics():
    w = win()
    check("Opens on the Calendar with Save/Cancel hidden", w.current == "calendar" and not w.footer.winfo_ismapped())
    w.show("events")
    w.win.update()
    check("Settings pages show Save/Cancel", w.footer.winfo_ismapped())
    check("Schedule is part of the Event timer page", "events" in w.pages and len(w.rows) == len(core.DEFAULT_SCHEDULE) and "schedule" not in w.pages)
    w.show("appearance")
    w.pick_style_panel("list")
    import ui

    def buttons(widget):
        for child in widget.winfo_children():
            if isinstance(child, ui.Button):
                yield child.itemcget(child.label, "text")
            yield from buttons(child)
    labels = [t for t in buttons(w.style_frame) if t in ("Event timer", "Stopwatch", "Notifications", "Upcoming list")]
    check("Copy style offers only Event timer, Stopwatch and Notifications", labels == ["Event timer", "Stopwatch", "Notifications"], labels)
    app.stopwatch_action("toggle")
    app.stopwatch_action("toggle")  # paused with time on it: the button reads Resume
    w.show("stopwatch")
step(window_basics, 600)


def resume_button():
    b = win().watch_toggle
    text = b.itemcget(b.label, "text")
    x0, _, x1, _ = b.bbox(b.label)
    check("Stopwatch button fits its label", text == "Resume" and x0 >= 0 and x1 <= int(b["width"]), f"{text}: text {x0}-{x1} in {b['width']}")
    grab(win().win, "stopwatch_page")
    app.watch.reset()
    win().show("calendar")
step(resume_button, 500)

# ---- calendar ----
today = date.today()


def add_events():
    book = app.calendar
    book.put(new_event(title="Maths test", date=today.isoformat(), start="09:00", end="10:00", tag="school", reminder=15))
    book.put(new_event(title="Birthday", date=(today + timedelta(days=2)).isoformat(), all_day=True, tag="personal", reminder=None))
    book.put(new_event(title="Yesterday's meeting", date=(today - timedelta(days=1)).isoformat(), start="14:00", tag="work"))
    # One with its reminder due right now, to pop a notification.
    soon = datetime.now() + timedelta(minutes=5)
    book.put(new_event(title="Revision session", date=soon.date().isoformat(), start=soon.strftime("%H:%M"), tag="important",
                       reminder=5))
    app.alarms.put(new_alarm(time="07:30", label="Wake up", days=[0, 1, 2, 3, 4], volume=SILENT))
    app.update(reminder_volume=SILENT)
    win().data_changed()
step(add_events, 700)


def month_view():
    w = win()
    check("Past events are crossed off, not deleted",
          app.calendar.is_done(next(e for e in app.calendar.events if e["title"] == "Yesterday's meeting"))
          and len(app.calendar.events) == 4)
    grab(w.win, "calendar_month")
    w.calendar_page.set_mode("week")
    w.calendar_page.view_chips.set("week")
step(month_view, 2200)  # the reminder (due now) appears on the next second's check


def reminder_popped():
    check("A due calendar reminder pops up as a notification",
          app.notices and app.notices[0]["kind"] == "event" and app.notification.shown, [n["title"] for n in app.notices])
    grab(win().win, "calendar_week")
    win().calendar_page.goto(today, "day")
step(reminder_popped, 700)
step(lambda: grab(win().win, "calendar_day"), 200)


def snooze_reminder():
    note = app.notification
    action_areas = dict(note.buttons)
    x0, y0, x1, y1 = action_areas["snooze"]
    note.start_drag(type("E", (), {"x_root": note.pos[0] + (x0 + x1) // 2, "y_root": note.pos[1] + (y0 + y1) // 2})())
    note.end_drag(type("E", (), {"x_root": note.pos[0] + (x0 + x1) // 2, "y_root": note.pos[1] + (y0 + y1) // 2})())
    check("Clicking Snooze on the notification snoozes the reminder",
          not app.notices and len(app.calendar.snoozes) == 1, app.calendar.snoozes)
step(snooze_reminder, 300)

# ---- alarms ----


def alarm_dialog():
    w = win()
    w.show("alarms")
    d = planner_ui.AlarmDialog(w.alarms_page)
    d.time_var.set("6:45 pm")
    d.label_var.set("Gym")
    d.quick_pick("weekends")
    d.volume_value = SILENT
    d.save()
    gym = next(a for a in app.alarms.alarms if a["label"] == "Gym")
    check("Alarm dialog saves time (12-hour input), label and repeat", gym["time"] == "18:45" and gym["days"] == [5, 6], gym)
    grab(w.win, "alarms_page")
    # Ring an alarm two seconds from now.
    ring = new_alarm(time=(datetime.now() + timedelta(minutes=1)).strftime("%H:%M"), label="Test alarm", volume=SILENT, snooze=9)
    app.alarms.put(ring)
    ring["next"] = (datetime.now() + timedelta(seconds=2)).isoformat(timespec="seconds")
    app.alarms.save()
step(alarm_dialog, 3500)


def alarm_rang():
    check("Due alarm rings: notification shows, sound loops", app.notices and app.notices[0]["kind"] == "alarm"
          and app.player.looping, [n["title"] for n in app.notices])
    ring = next(a for a in app.alarms.alarms if a["label"] == "Test alarm")
    check("One-time alarm switches itself off after ringing", not ring["enabled"])
    grab(app.notification.window, "notification_card")
    app.update(click_through=True)
    app.set_click_through(True)
    style = winapi.user32.GetWindowLongPtrW(winapi.vp(app.notification.layer.hwnd), -20)
    check("Notification stays clickable with click-through on", not style & winapi.WS_EX_TRANSPARENT)
    app.update(click_through=False)
    app.set_click_through(False)
    app.run_command("dismiss_notification")
    check("Dismiss hotkey clears it and stops the sound", not app.notices and not app.player.looping)
step(alarm_rang, 400)

# ---- notifications page ----


def placement():
    w = win()
    w.show("notifications")
    w.screen_map.preset("bl")
    sx, sy = app.settings["notify_x"], app.settings["notify_y"]
    check("Position preset moves the notification", sy > root.winfo_screenheight() // 2 and sx < 50, (sx, sy))
    app.test_notification()
step(placement, 900)


def test_notice():
    check("Test notification appears at the chosen spot",
          app.notification.shown and app.notification.pos == (app.settings["notify_x"], app.settings["notify_y"]),
          app.notification.pos)
    grab(win().win, "notifications_page")
    t0 = time.perf_counter()
    st, _ = app.state(app.view)
    for _ in range(20):
        app.draw(st)
    ms = (time.perf_counter() - t0) / 20 * 1000
    check("Drawing with a notification on screen stays cheap", ms < 30, f"{ms:.1f} ms per frame")
    app.notice_action("dismiss")
    app.update_style("notification", shape="reactor")
    app.test_notification()
step(test_notice, 900)


def arc_notice():
    grab(app.notification.window, "notification_arc")
    app.notice_action("dismiss")
    win().show("app")
step(arc_notice, 500)

# ---- theme ----


def theme_light():
    win().pick_theme_preset("light")
step(theme_light, 1500)


def theme_rebuilt():
    w = win()
    check("Theme preset rebuilds the window in the new colours", w.draft["theme"]["bg"] == "#f3f5f9" and
          planner_ui.UI["bg"] == "#f3f5f9" and w.current == "app")
    grab(w.win, "theme_light")
    w.show("calendar")
step(theme_rebuilt, 500)
step(lambda: grab(win().win, "theme_light_calendar"), 300)


def theme_galaxy():
    win().pick_theme_preset("midnight")
    win().set_theme(effect="galaxy")
step(theme_galaxy, 1700)


def galaxy():
    grab(win().win, "theme_galaxy")
    w = win()
    w.cancel()
    check("Cancel reverts the theme", planner_ui.UI["bg"] == "#0c0f14" and json.loads(core.SETTINGS_PATH.read_text())["theme"]["effect"] == "none")
step(galaxy, 300)

root.after(900, run)
root.mainloop()
