"""Settings switches apply live, outside changes sync into Settings, scrollbar drags."""
import copy
import json
import sys
import traceback
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

core.SETTINGS_PATH = OUT / "test3_settings.json"
if core.SETTINGS_PATH.exists():
    core.SETTINGS_PATH.unlink()
import overlay  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
app.update_style("timer", shape="reactor")
app.update(x=60, y=60)
app.timer.move_to(60, 60)
root = app.root
errors = []
root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


class Ev:
    def __init__(self, x_root=0, y_root=0, x=0, y=0, delta=0):
        self.x_root, self.y_root, self.x, self.y, self.delta = x_root, y_root, x, y, delta


def drag(panel, dx, dy):
    x, y = panel.window.winfo_rootx() + 30, panel.window.winfo_rooty() + 30
    panel.start_drag(Ev(x, y))
    panel.drag(Ev(x + dx, y + dy))
    panel.end_drag(Ev(x + dx, y + dy))


def pos():
    return {k: app.settings[k] for k in ("x", "y", "list_x", "list_y")}


steps = []


def step(fn, delay=400):
    steps.append((fn, delay))


def run(i=0):
    if i >= len(steps) or errors:
        print("errors:", len(errors))
        for e in errors:
            print(e)
        print(f"{sum(results)}/{len(results)} checks passed")
        app.quit()
        return
    try:
        steps[i][0]()
    except Exception:
        errors.append(traceback.format_exc())
    root.after(steps[i][1], lambda: run(i + 1))


step(lambda: app.open_settings(), 1200)


def settings_switch_links_without_saving():
    sw = app.settings_window
    sw.controls["link_panels"].set(True, notify=True)  # as if clicked
    root.after(100, lambda: None)
step(settings_switch_links_without_saving, 300)


def drag_links():
    before = pos()
    drag(app.list, 30, 20)
    after = pos()
    check("Settings switch (not saved yet) links the panels",
          after["x"] - before["x"] == 30 and after["list_x"] - before["list_x"] == 30, f"{before} -> {after}")
step(drag_links, 300)


def menu_unlinks_and_syncs():
    app.toggle("link_panels")  # what the right-click menu does
    sw = app.settings_window
    check("Right-click change shows in the open Settings switch",
          sw.controls["link_panels"].value is False and sw.draft["link_panels"] is False)
    before = pos()
    drag(app.list, 10, 10)
    after = pos()
    check("Unlinked again: only the dragged panel moves",
          after["x"] == before["x"] and after["list_x"] - before["list_x"] == 10, f"{before} -> {after}")
step(menu_unlinks_and_syncs, 300)


def settings_lock():
    sw = app.settings_window
    sw.controls["locked"].set(True, notify=True)
    root.after(10, lambda: None)
step(settings_lock, 300)


def locked_drag():
    before = pos()
    drag(app.timer, 50, 50)
    check("Settings 'Lock positions' applies before saving", pos() == before)
    app.settings_window.controls["locked"].set(False, notify=True)
step(locked_drag, 300)


def ctrl_scroll_syncs():
    app.nudge_scale(app.list, 0.05)
    sw = app.settings_window
    sw.pick_style_panel("list")
    check("Ctrl+scroll moves the Settings size slider", abs(sw.style_controls["scale"].value - 1.05) < 1e-6,
          f"slider {sw.style_controls['scale'].value}")
step(ctrl_scroll_syncs, 300)


def scrollbar():
    sw = app.settings_window
    sw.show("appearance")
    root.update()
    page = sw.pages["appearance"]
    bar = page.bar
    h = bar.winfo_height()
    start = page.canvas.yview()[0]
    page._press(Ev(y=round(h * 0.9)))   # click low on the track: jump there
    page._drag(Ev(y=round(h * 0.95)))
    page._release(Ev())
    jumped = page.canvas.yview()[0]
    page._press(Ev(y=round((jumped + 0.01) * h)))  # grab the thumb near its top
    page._drag(Ev(y=round(0.02 * h)))               # drag it all the way up
    page._release(Ev())
    top = page.canvas.yview()[0]
    check("Scrollbar: clicking the track jumps down", jumped > start + 0.3, f"{start:.2f} -> {jumped:.2f}")
    check("Scrollbar: dragging the thumb scrolls back up", top < 0.05, f"{jumped:.2f} -> {top:.2f}")
    x, y = bar.winfo_rootx(), bar.winfo_rooty()
    page._set_hover(True)
    root.update()
    ImageGrab.grab(bbox=(x - 260, y, x + bar.winfo_width(), y + h), all_screens=True).save(OUT / "scrollbar.png")
    before = page.canvas.yview()[0]
    c = page.canvas; app.update(x=1500, y=60, list_x=1500, list_y=500); app.timer.move_to(1500, 60); app.list.move_to(1500, 500); root.update(); sw.wheel(Ev(x_root=c.winfo_rootx() + c.winfo_width() // 2, y_root=c.winfo_rooty() + c.winfo_height() // 2, delta=-120))
    root.update()
    after = page.canvas.yview()[0]
    region_h = float(page.canvas.cget("scrollregion").split()[3])
    import ui as _ui
    step_px = 3 * _ui.px(24)
    check(f"One wheel notch scrolls 3 steps ({step_px} px at this display scale)", abs((after - before) * region_h - step_px) < 2,
          f"{(after - before) * region_h:.0f} px")
step(scrollbar, 500)


def save():
    sw = app.settings_window
    sw.save()  # may stay open only if the installed app already holds the hotkeys
    saved = json.loads(core.SETTINGS_PATH.read_text())
    check("Saved settings keep the right-click choice", saved["link_panels"] is False and saved["locked"] is False)
step(save, 400)



# ---- custom backgrounds ----
import effects  # noqa: E402
import settings_ui  # noqa: E402
MEDIA = Path(__file__).resolve().parent / "media"
settings_ui.DATA_DIR = OUT / "data"


def media_checks():
    try:
        effects.inspect_media(MEDIA / "too_long_20s.gif")
        check("20-second animation is refused", False)
    except ValueError as e:
        check("20-second animation is refused", "20.0 seconds" in str(e), str(e))
    sw = app.settings_window or (app.open_settings() or app.settings_window)
    sw.show("appearance")
    sw.pick_style_panel("timer")
    for name in ("too_long_20s.gif", "orbit_4s.gif"):
        settings_ui.filedialog.askopenfilename = lambda **kw: str(MEDIA / name)
        sw.choose_media()
        print("   status after choosing", name, "->", sw.status.cget("text"))
    check("Valid animation is copied into the settings folder",
          Path(sw.style()["custom_bg"]).parent == settings_ui.DATA_DIR / "backgrounds" and Path(sw.style()["custom_bg"]).exists())
    check("Choosing a file selects the Custom image effect",
          sw.style()["panel_effect"] == "custom" and sw.style_controls["panel_effect"].value == "custom")
step(lambda: (app.update_style("timer", shape="card"), app.update(split_list=True, show_list=True), app.open_settings()), 900)
step(media_checks, 1200)


def animation_plays():
    s = app.view
    check("Animated custom background redraws every frame", app.renderer.animating(s, app.watch))
    st, _ = app.state(s)
    a = app.renderer.timer(s, st, app.k, 0.25)
    b = app.renderer.timer(s, st, app.k, 2.25)
    from PIL import ImageChops
    check("Animation frames change over time", ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is not None)
    grab_both("custom_gif")
    import time as _t
    t0 = _t.perf_counter()
    for _ in range(30):
        app.draw(st)
    print(f"   card + list with custom GIF: {(_t.perf_counter() - t0) / 30 * 1000:.1f} ms/frame")
step(animation_plays, 300)


def fits():
    sw = app.settings_window
    settings_ui.filedialog.askopenfilename = lambda **kw: str(MEDIA / "banner.png")
    sw.choose_media()
    for mode in ("fill", "stretch", "fit"):
        sw.style_controls["custom_fit"].set(mode, notify=True)
        app.preview(copy.deepcopy(sw.draft))
        st, _ = app.state(app.view)
        app.draw(st)
        grab_both(f"custom_png_{mode}")
    check("Still image does not force constant redraws", not app.renderer.animating(app.view, app.watch))
step(fits, 500)


def grab_both(name):
    root.update()
    shown = [p for p in app.panels if p.shown]
    x0 = min(p.window.winfo_rootx() for p in shown)
    y0 = min(p.window.winfo_rooty() for p in shown)
    x1 = max(p.window.winfo_rootx() + p.window.winfo_width() for p in shown)
    y1 = max(p.window.winfo_rooty() + p.window.winfo_height() for p in shown)
    ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).save(OUT / f"{name}.png")

root.after(800, run)
root.mainloop()
