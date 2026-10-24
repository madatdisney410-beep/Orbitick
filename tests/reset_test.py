"""Reset layout puts both panels back in place (on screen, not just in settings) for every case."""
import sys
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

core.SETTINGS_PATH = OUT / "reset_settings.json"
if core.SETTINGS_PATH.exists():
    core.SETTINGS_PATH.unlink()
import overlay  # noqa: E402
from PIL import ImageGrab  # noqa: E402

app = overlay.Overlay()
results = []


class Ev:
    def __init__(self, x, y):
        self.x_root, self.y_root = x, y


def drag(p, dx, dy, pause_ms=0):
    x, y = p.window.winfo_rootx() + 30, p.window.winfo_rooty() + 30
    p.start_drag(Ev(x, y))
    p.drag(Ev(x + dx // 2, y + dy // 2))
    if pause_ms:  # let animation frames redraw mid-drag
        end = app.root.tk.call("clock", "milliseconds") + pause_ms
        while app.root.tk.call("clock", "milliseconds") < end:
            app.root.update()
    p.drag(Ev(x + dx, y + dy))
    p.end_drag(Ev(x + dx, y + dy))


def screen(p):
    app.root.update()
    return p.window.winfo_rootx(), p.window.winfo_rooty(), p.window.winfo_width(), p.window.winfo_height()


def check(tag, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + tag + (f"  ({detail})" if detail else ""))


def verify(tag):
    tx, ty, tw, th = screen(app.timer)
    lx, ly, lw, lh = screen(app.list)
    centred = abs((tx + tw / 2) - (lx + lw / 2)) <= 1
    below = ly > ty + th * 0.6
    matches_saved = (lx, ly) == (app.settings["list_x"], app.settings["list_y"])
    check(tag, (tx, ty) == (40, 40) and app.view["styles"]["timer"]["scale"] == 1.0 and app.view["styles"]["list"]["scale"] == 1.0
          and centred and below and matches_saved,
          f"timer ({tx},{ty}) {tw}x{th} | list ({lx},{ly}) {lw}x{lh} | centred {centred} below {below} "
          f"on-screen=saved {matches_saved}")


seq = []


def add(fn, d=500):
    seq.append((fn, d))


def run(i=0):
    if i == len(seq):
        print(f"{sum(results)}/{len(results)} checks passed")
        app.quit()
        return
    seq[i][0]()
    app.root.after(seq[i][1], lambda: run(i + 1))


# 1. Arc reactor: move + resize both, reset from the right-click menu path.
add(lambda: app.update_style("timer", shape="reactor"), 600)
add(lambda: (drag(app.timer, 600, 300), drag(app.list, -20, 250), app.nudge_scale(app.timer, 0.4),
             app.nudge_scale(app.list, 0.3)), 600)
add(lambda: app.reset_layout(), 600)
add(lambda: verify("Arc reactor, moved and resized, then Reset layout"), 100)

# 2. Dragging still works while the reactor animates (redraws now carry the position).


def drag_while_animating():
    drag(app.timer, 200, 120, pause_ms=400)
    tx, ty, _, _ = screen(app.timer)
    check("Dragging during animation lands where released", (tx, ty) == (240, 160) == (app.settings["x"], app.settings["y"]),
          f"screen ({tx},{ty}) saved ({app.settings['x']},{app.settings['y']})")
add(drag_while_animating, 600)


def stays_put():
    tx, ty, _, _ = screen(app.timer)
    check("Panel stays where it was dropped on later frames", (tx, ty) == (240, 160), f"({tx},{ty})")
add(stays_put, 100)

# 3. Linked panels, reset while Settings is open, and the Settings sliders follow.
add(lambda: (app.update(link_panels=True), drag(app.list, 400, 100), app.nudge_scale(app.timer, -0.3),
             app.open_settings()), 1200)
add(lambda: app.reset_layout(), 600)


def settings_synced():
    verify("Linked panels, Reset layout with Settings open")
    sw = app.settings_window
    check("Settings size sliders return to 100%", sw.style_controls["scale"].value == 1.0 and sw.draft["styles"]["list"]["scale"] == 1.0)
    sw.cancel()
add(settings_synced, 300)

# 4. Classic card with a separate list.
add(lambda: (app.update_style("timer", shape="card"), app.update(split_list=True, link_panels=False), drag(app.list, 300, 50),
             drag(app.timer, 200, 400), app.nudge_scale(app.list, 0.25)), 600)
add(lambda: app.reset_layout(), 600)
add(lambda: verify("Classic card with separate list"), 100)

# 5. Pictures of both, after a reset.
add(lambda: (app.update_style("timer", shape="reactor"), app.reset_layout()), 900)


def shot():
    tx, ty, tw, th = screen(app.timer)
    lx, ly, lw, lh = screen(app.list)
    ImageGrab.grab(bbox=(min(tx, lx), ty, max(tx + tw, lx + lw), ly + lh), all_screens=True).save(OUT / "reset_reactor.png")
add(shot, 100)

app.root.after(600, run)
app.root.mainloop()
