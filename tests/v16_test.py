"""1.6.0: live layout map (every panel draggable) and layout presets."""
import json
import sys
import traceback
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

DATA = OUT / "v16"
DATA.mkdir(exist_ok=True)
core.SETTINGS_PATH = DATA / "settings.json"
for name in ("settings.json", "alarms.json", "calendar.json", "stopwatch.json"):
    if (DATA / name).exists():
        (DATA / name).unlink()
import shutil  # noqa: E402

shutil.rmtree(DATA / "presets", ignore_errors=True)
import overlay  # noqa: E402
import presets  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
app.update(show_stopwatch=True, split_list=True)
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
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"v16_{name}.png")


def win():
    return app.settings_window


def rect(m, style):
    items = [i for i in m.find_withtag(f"panel:{style}") if m.type(i) == "rectangle"]
    return [round(c) for c in m.coords(items[0])] if items else None


class Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def drag_on_map(m, style, dx, dy):
    x0, y0, x1, y1 = rect(m, style)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    m.press(Ev(cx, cy))
    m.move(Ev(cx + dx // 2, cy + dy // 2))
    m.move(Ev(cx + dx, cy + dy))
    m.release(Ev(cx + dx, cy + dy))


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


step(lambda: app.open_settings("layout"), 1800)


def map_shows_panels():
    m = win().layout_map
    shown = sorted(t[6:] for i in m.find_all() for t in m.gettags(i) if t.startswith("panel:"))
    check("Map shows every panel, notification included", set(shown) == {"timer", "list", "stopwatch", "notification"}, set(shown))
    check("Map covers every monitor", len(m.screens) >= 1, m.screens)
    before = app.timer.pos
    drag_on_map(m, "timer", 60, 30)
    after = app.timer.pos
    moved = (after[0] - before[0], after[1] - before[1])
    expected = (round(60 / m.scale), round(30 / m.scale))
    check("Dragging the event timer on the map moves the real panel",
          abs(moved[0] - expected[0]) <= 2 and abs(moved[1] - expected[1]) <= 2
          and (app.settings["x"], app.settings["y"]) == after, f"moved {moved}, expected ~{expected}")
    win().layout_map.before_list = rect(m, "list")
    app.list.move_to(app.list.pos[0] + 300, app.list.pos[1] + 100)  # moved on screen, not on the map
    app.set_positions({"list_x": app.list.pos[0], "list_y": app.list.pos[1]})
    app.nudge_scale(app.stopwatch, 0.4)
    win().layout_map.before_watch = rect(m, "stopwatch")
step(map_shows_panels, 1200)


def map_follows():
    m = win().layout_map
    now_list, now_watch = rect(m, "list"), rect(m, "stopwatch")
    check("Map follows a panel moved on screen", now_list[0] > m.before_list[0] + 20, f"{m.before_list} -> {now_list}")
    check("Map follows a panel resized with Ctrl + scroll",
          (now_watch[2] - now_watch[0]) > (m.before_watch[2] - m.before_watch[0]) + 5, f"{m.before_watch} -> {now_watch}")
    grab(win().win, "layout_page")
    win().new_layout()
step(map_follows, 700)


def name_layout():
    d = [w for w in win().win.winfo_children() if w.winfo_class() == "Toplevel"][0]
    d.name_var.set("Gaming")
    d.save()
    saved = presets.load_all("layout")
    check("Save current layout stores positions, sizes and visibility", [l["name"] for l in saved] == ["Gaming"]
          and saved[0]["positions"]["x"] == app.settings["x"] and saved[0]["scales"]["stopwatch"] == 1.4
          and saved[0]["show"]["show_stopwatch"] is True, saved[0]["scales"])
    win().gaming = dict(pos=app.timer.pos, list=app.list.pos)
    # Rearrange: move things, hide the stopwatch, shrink it.
    app.reset_layout()
    app.update(show_stopwatch=False)
step(name_layout, 900)


def apply_gaming():
    w = win()
    check("Rearranged before applying", app.timer.pos == (40, 40) and not app.view["show_stopwatch"])
    w.apply_layout("Gaming")
step(apply_gaming, 900)


def restored():
    g = win().gaming
    check("Applying the layout restores positions, sizes and visibility",
          app.timer.pos == g["pos"] and app.list.pos == g["list"] and app.view["show_stopwatch"]
          and app.view["styles"]["stopwatch"]["scale"] == 1.4, (app.timer.pos, g["pos"]))
    data = json.loads(core.SETTINGS_PATH.read_text())
    check("Layout presets are saved immediately", data["layout_preset"] == "Gaming" and len(presets.load_all("layout")) == 1)
    app.update(locked=True)
    m = win().layout_map
    win().locked_before = app.timer.pos
    drag_on_map(m, "timer", 80, 0)
step(restored, 700)


def locked():
    check("Locked positions can't be dragged on the map either", app.timer.pos == win().locked_before)
    app.update(locked=False)
    win().show("notifications")
    win().screen_map.preset("tr")
step(locked, 700)


def notifications_map():
    m = win().screen_map
    sx = app.settings["notify_x"]
    check("Notifications page map: corner buttons still work", sx > root.winfo_screenwidth() // 2, sx)
    grab(win().win, "notifications_page")
    win().show("layout")
    win().delete_layout()
step(notifications_map, 700)


def deleted():
    check("Deleting a layout keeps the panels where they are", presets.load_all("layout") == [] and
          app.timer.pos == win().gaming["pos"])
step(deleted, 300)

root.after(900, run)
root.mainloop()
