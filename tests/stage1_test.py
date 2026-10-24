"""Stage 1: per-panel styles (with migration from old settings) and the stopwatch panel."""
import json
import sys
import time
import traceback
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

core.SETTINGS_PATH = OUT / "stage1_settings.json"
for f in (core.SETTINGS_PATH, OUT / "stopwatch.json"):
    if f.exists():
        f.unlink()
# An old-format (1.2.x) settings file: one flat look shared by the timer and the list.
core.SETTINGS_PATH.write_text(json.dumps({"shape": "reactor", "accent": "#ff5d73", "scale": 1.0, "list_scale": 1.0,
                                          "panel_effect": "galaxy", "title": "Raid Timer"}))
import overlay  # noqa: E402
import stopwatch  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
root = app.root
errors, results = [], []
root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


class Ev:
    def __init__(self, x, y):
        self.x_root, self.y_root = x, y


def press(panel, x, y, dx=0, dy=0):
    """Press at window pixel (x, y), optionally move, release."""
    X, Y = panel.pos[0] + x, panel.pos[1] + y
    panel.start_drag(Ev(X, Y))
    if dx or dy:
        panel.drag(Ev(X + dx // 2, Y + dy // 2))
        panel.drag(Ev(X + dx, Y + dy))
    panel.end_drag(Ev(X + dx, Y + dy))


def click_button(panel, action):
    for name, (x0, y0, x1, y1) in panel.buttons:
        if name == action:
            press(panel, (x0 + x1) // 2, (y0 + y1) // 2)
            return True
    return False


def grab_panels(name, panels=None):
    root.update()
    shown = [p for p in (panels or app.panels) if p.shown]
    x0 = min(p.pos[0] for p in shown)
    y0 = min(p.pos[1] for p in shown)
    x1 = max(p.pos[0] + p.size[0] for p in shown)
    y1 = max(p.pos[1] + p.size[1] for p in shown)
    ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).save(OUT / f"{name}.png")


def grab(widget, name):
    widget.update()
    x, y, w, h = widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"{name}.png")


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


def migrated():
    st = app.settings["styles"]
    check("Old settings migrate into the timer and list styles",
          st["timer"]["shape"] == "reactor" and st["timer"]["accent"] == "#ff5d73" and st["list"]["panel_effect"] == "galaxy"
          and st["stopwatch"]["accent"] == core.STYLE_DEFAULTS["accent"] and app.settings["title"] == "Raid Timer")
    app.update(show_stopwatch=True)
step(migrated, 700)


def stopwatch_appears():
    sw, t = app.stopwatch, app.timer
    check("Stopwatch panel appears beside the timer", sw.shown and sw.pos[0] > t.pos[0] + t.size[0] // 2,
          f"timer at {t.pos} {t.size}, stopwatch at {sw.pos} {sw.size}")
    check("Stopwatch panel has clickable buttons", [a for a, _ in sw.buttons] == ["lap_or_reset", "toggle"], sw.buttons)
    click_button(sw, "toggle")
step(stopwatch_appears, 1300)


def started():
    check("Clicking Start on the panel starts it", app.watch.running and app.watch.elapsed() > 1.0,
          f"{app.watch.elapsed():.2f} s")
    app.update(locked=True)
    click_button(app.stopwatch, "lap_or_reset")
step(started, 700)


def lapped():
    check("Clicking Lap works, even with positions locked", len(app.watch.laps) == 1, app.watch.laps)
    app.update(locked=False)
    before = app.stopwatch.pos
    x0, y0, x1, y1 = dict(app.stopwatch.buttons)["toggle"]
    press(app.stopwatch, (x0 + x1) // 2, (y0 + y1) // 2, 80, 40)  # a drag that starts on a button
    check("Dragging from a button moves the panel instead of clicking",
          app.watch.running and app.stopwatch.pos == (before[0] + 80, before[1] + 40), f"{before} -> {app.stopwatch.pos}")
step(lapped, 400)


def perf():
    st, _ = app.state(app.view)
    for _ in range(5):
        app.draw(st)
    t0 = time.perf_counter()
    for _ in range(30):
        app.draw(st)
    ms = (time.perf_counter() - t0) / 30 * 1000
    check("All three panels animating stay cheap", ms < 25, f"{ms:.1f} ms per frame (arc timer + galaxy list + running stopwatch)")
    grab_panels("stage1_running")
step(perf, 300)


def hotkeys_and_scale():
    app.run_command("stopwatch_toggle")
    stopped = not app.watch.running
    app.nudge_scale(app.stopwatch, 0.1)
    styles = app.view["styles"]
    check("Stopwatch hotkey command stops it", stopped)
    check("Ctrl+scroll resizes only that panel", styles["stopwatch"]["scale"] == 1.1 and styles["timer"]["scale"] == 1.0)
step(hotkeys_and_scale, 400)


def persists():
    again = stopwatch.Stopwatch()
    check("Stopwatch state survives a restart",
          abs(again.elapsed() - app.watch.elapsed()) < 0.01 and again.laps == app.watch.laps and not again.running,
          f"{again.elapsed():.2f} s, laps {again.laps}")
step(persists, 100)

# Settings window: per-panel look.
step(lambda: app.open_settings(), 1500)


def style_stopwatch():
    sw = app.settings_window
    sw.show("appearance")
    sw.pick_style_panel("stopwatch")
    sw.pick_shape("reactor")
    sw.set_style("accent", "#a78bfa")
step(style_stopwatch, 900)


def separate_looks():
    v = app.view["styles"]
    check("Styling the stopwatch leaves the timer alone",
          v["stopwatch"]["shape"] == "reactor" and v["stopwatch"]["accent"] == "#a78bfa" and v["timer"]["accent"] == "#ff5d73")
    grab(app.settings_window.win, "stage1_appearance_stopwatch")
    sw = app.settings_window
    sw.pick_style_panel("list")
    sw.copy_style("stopwatch")
step(separate_looks, 700)


def copied():
    v = app.view["styles"]
    check("Copy style copies the look but keeps the size",
          v["list"]["accent"] == "#a78bfa" and v["list"]["panel_effect"] == v["stopwatch"]["panel_effect"]
          and v["list"]["scale"] == 1.0)
    for page in ("events", "stopwatch"):
        app.settings_window.show(page)
        grab(app.settings_window.win, f"stage1_page_{page}")
    app.settings_window.show("appearance")
    app.settings_window.pages["appearance"].canvas.yview_moveto(0.0)
    app.settings_window.pick_style_panel("stopwatch")
step(copied, 900)
step(lambda: grab(app.settings_window.win, "stage1_appearance_top"), 300)


def saved():
    app.settings_window.save()
    data = json.loads(core.SETTINGS_PATH.read_text())
    check("Saved settings keep a separate style per panel",
          data["styles"]["stopwatch"]["shape"] == "reactor" and data["styles"]["timer"]["accent"] == "#ff5d73"
          and "accent" not in data)
    app.reset_layout()
step(saved, 900)


def reset():
    t, sw, lst = app.timer, app.stopwatch, app.list
    check("Reset layout: sizes back to 100%, stopwatch beside the timer, list under it",
          all(s["scale"] == 1.0 for s in app.view["styles"].values()) and t.pos == (40, 40)
          and sw.pos[0] > 40 + t.size[0] // 2 and lst.pos[1] > 40 + t.size[1] // 2,
          f"timer {t.pos}, list {lst.pos}, stopwatch {sw.pos}")
    grab_panels("stage1_reset")
step(reset, 100)

root.after(800, run)
root.mainloop()
