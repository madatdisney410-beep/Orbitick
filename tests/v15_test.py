"""1.5.0: event timer presets and dated alarms in the real window."""
import json
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

DATA = OUT / "v15"
DATA.mkdir(exist_ok=True)
core.SETTINGS_PATH = DATA / "settings.json"
for name in ("settings.json", "alarms.json", "calendar.json", "stopwatch.json"):
    if (DATA / name).exists():
        (DATA / name).unlink()
import shutil  # noqa: E402

shutil.rmtree(DATA / "presets", ignore_errors=True)
import overlay  # noqa: E402
import presets  # noqa: E402
import planner_ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
app.update(show_timer=False, show_list=False)
root = app.root
errors, results = [], []
root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def grab(widget, name):
    top = widget.winfo_toplevel()
    if top.state() == "iconic":
        top.deiconify()
    top.lift()
    widget.update()
    x, y, w, h = widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"v15_{name}.png")


def win():
    return app.settings_window


def dialog():
    return [w for w in win().win.winfo_children() if w.winfo_class() == "Toplevel"][0]


seq = []


def step(fn, delay=400):
    seq.append((fn, delay))


def run(i=0):
    if i >= len(seq) or errors:
        print("errors:", len(errors))
        for e in errors:
            print(e)
        print(f"{sum(results)}/{len(results)} checks passed")
        if app.window_open():
            app.settings_window.cancel()
        app.quit()
        return
    try:
        seq[i][0]()
    except Exception:
        errors.append(traceback.format_exc())
    root.after(seq[i][1], lambda: run(i + 1))


presets.save("event", dict({k: core.DEFAULTS[k] for k in core.PRESET_KEYS}, name="Hourly"))
step(lambda: app.open_settings("events"), 1500)


def make_preset():
    w = win()
    w.rows[0]["at"].set("02:30")
    w.rows[0]["bosses"].set("World Boss")
    w.pages["events"].inner.update()
    for key, value in (("title", "Raid Timer"), ("next_label", "Next raid")):
        w.draft[key] = value
    w.new_preset()
step(make_preset, 700)


def name_preset():
    d = dialog()
    d.name_var.set("Raids")
    d.save()
    w = win()
    saved = presets.load_all("event")
    raids = presets.find("event", "Raids")
    check("Save as new preset writes a preset file with the current setup",
          [p["name"] for p in saved] == ["Hourly", "Raids"] and raids["title"] == "Raid Timer"
          and raids["schedule"][0] == {"at": "02:30", "bosses": "World Boss"}
          and Path(raids["file"]).name == "Raids.orbitickpreset", saved)
    grab(w.win, "presets")
    w.apply_preset("Hourly")
step(name_preset, 600)


def applied_hourly():
    w = win()
    check("Applying another preset restores its schedule and labels", w.draft["title"] == "Event Timer"
          and len(w.rows) == len(core.DEFAULT_SCHEDULE) and w.rows[0]["bosses"].get() == "Top of the hour")
    w.apply_preset("Raids")
step(applied_hourly, 500)


def applied_raids():
    w = win()
    check("Switching to a saved preset swaps the whole setup", w.draft["title"] == "Raid Timer"
          and w.rows[0]["bosses"].get() == "World Boss")
    w.save()
    data = json.loads(core.SETTINGS_PATH.read_text())
    check("Saved: presets and the applied setup", data["event_preset"] == "Raids" and data["title"] == "Raid Timer"
          and data["event_presets"] == [] and len(presets.load_all("event")) == 2)
    app.open_settings("alarms")
step(applied_raids, 1500)


def new_alarm():
    planner_ui.AlarmDialog(win().alarms_page)
step(new_alarm, 700)


def once_tomorrow():
    d = dialog()
    check("New alarm starts as Once, with the date picker shown", d.alarm["days"] == [] and d.date_frame.winfo_ismapped())
    d.time_var.set("8:15 am")
    d.label_var.set("Dentist")
    d.quick_day("tomorrow")
    grab(d, "alarm_once")
    d.volume_value = 0.0004
    d.save()
    a = next(x for x in app.alarms.alarms if x["label"] == "Dentist")
    tomorrow = date.today() + timedelta(days=1)
    check("Once on Tomorrow saves that date and rings then", a["date"] == tomorrow.isoformat()
          and a["next"] == f"{tomorrow.isoformat()}T08:15:00", a["next"])
    planner_ui.AlarmDialog(win().alarms_page)
step(once_tomorrow, 700)


def past_today():
    d = dialog()
    past = (datetime.now() - timedelta(minutes=5)).strftime("%H:%M")
    d.time_var.set(past)
    d.quick_day("today")
    d.save()
    check("A time that has already passed today is refused with a message",
          d.winfo_exists() and "already passed" in d.status.cget("text"), d.status.cget("text"))
    d.days.set([0, 3], notify=True)
    check("Picking days hides the date (weekly alarm)", not d.date_frame.winfo_ismapped())
    d.time_var.set("6:30")
    d.label_var.set("Gym")
    d.volume_value = 0.0004
    grab(d, "alarm_weekly")
    d.save()
    gym = next(x for x in app.alarms.alarms if x["label"] == "Gym")
    check("Weekly Monday + Thursday alarm saved", gym["days"] == [0, 3] and gym["date"] is None and gym["next"])
step(past_today, 700)
step(lambda: grab(win().win, "alarms_list"), 300)

root.after(900, run)
root.mainloop()
