"""1.7.0 (and 1.8 names): preset files - folder, import, export, open folder, migration, double-click requests."""
import json
import shutil
import sys
import traceback
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import winapi  # noqa: E402

winapi.enable_dpi_awareness()
import core  # noqa: E402

DATA = OUT / "v17"
shutil.rmtree(DATA, ignore_errors=True)
DATA.mkdir()
core.SETTINGS_PATH = DATA / "settings.json"
# A 1.6 settings file with presets stored inside it: they should move into files on start.
old = dict(event_presets=[dict({k: core.DEFAULTS[k] for k in core.PRESET_KEYS}, name="Old raids",
                               schedule=[{"at": "10", "bosses": "Old boss"}])],
           layout_presets=[{"name": "Old desk", "positions": {"x": 100, "y": 120}, "show": {"show_timer": True},
                            "scales": {"timer": 1.0}}])
core.SETTINGS_PATH.write_text(json.dumps(old))

import overlay  # noqa: E402
import presets  # noqa: E402
import settings_ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

opened, dialog_answers = [], []
settings_ui.os.startfile = lambda path: opened.append(Path(path))
settings_ui.filedialog.askopenfilename = lambda **kw: dialog_answers.pop(0)
settings_ui.filedialog.asksaveasfilename = lambda **kw: dialog_answers.pop(0)

app = overlay.Overlay()
app.update(show_timer=False, show_list=False)
root = app.root
errors, results = [], []
root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
SHARED = DATA / "shared"
SHARED.mkdir()


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
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"v17_{name}.png")


def win():
    return app.settings_window


def status():
    return win().status.cget("text") if hasattr(win(), "status") else ""


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


def migrated():
    data = json.loads(core.SETTINGS_PATH.read_text())
    check("Presets from 1.6 settings move into preset files", [p["name"] for p in presets.load_all("event")] == ["Old raids"]
          and [p["name"] for p in presets.load_all("layout")] == ["Old desk"])
    check("...and are removed from settings.json", data["event_presets"] == [] and data["layout_presets"] == [])
    app.open_settings("events")
step(migrated, 1500)


def event_page():
    w = win()
    w.apply_preset("Old raids")
    w.save()
    check("A migrated preset still applies", app.settings["schedule"][0]["bosses"] == "Old boss")
    app.open_settings("events")
step(event_page, 1200)


def export_event():
    w = win()
    dialog_answers.append(str(SHARED / "Old raids.orbitickpreset"))
    w.export_preset("event", "Old raids")
    data = json.loads((SHARED / "Old raids.orbitickpreset").read_text(encoding="utf-8"))
    check("Export writes a self-describing preset file", data["orbitick_preset"] == "event" and data["name"] == "Old raids"
          and data["schedule"][0]["bosses"] == "Old boss", sorted(data))
    w.open_preset_folder("event")
    check("Open folder opens the event presets folder", opened and opened[-1] == presets.folder("event")
          and opened[-1].is_dir(), opened)
    # Import the same file back: the name is taken, so it becomes "Old raids (2)".
    dialog_answers.append(str(SHARED / "Old raids.orbitickpreset"))
    w.import_preset("event")
step(export_event, 1200)


def imported_copy():
    names = [p["name"] for p in presets.load_all("event")]
    check("Importing a preset whose name is taken keeps both", names == ["Old raids", "Old raids (2)"], names)
    check("The imported preset shows on the page at once", "Old raids (2)" in [p["name"] for p in win().event_presets()])
    grab(win().win, "event_presets")
    # A layout file imported from the event page lands with the layouts.
    layout = dict(presets.find("layout", "Old desk"), name="Streaming")
    presets.export("layout", layout, SHARED / "Streaming.orbitickpreset")
    dialog_answers.append(str(SHARED / "Streaming.orbitickpreset"))
    win().import_preset("event")
step(imported_copy, 1200)


def imported_layout():
    check("A layout file imported anywhere is filed as a layout", presets.find("layout", "Streaming") is not None
          and presets.find("event", "Streaming") is None)
    bad = SHARED / "broken.orbitickpreset"
    bad.write_text("{not json", encoding="utf-8")
    dialog_answers.append(str(bad))
    win().import_preset("layout")
    win().bad_message = status()
step(imported_layout, 1200)


def broken_file():
    check("A broken file is refused with a message and not added", len(presets.load_all("layout")) == 2
          and "couldn't be read" in win().bad_message, win().bad_message)
    # Hand-dropped file: copy a preset straight into the folder.
    shutil.copy(SHARED / "Streaming.orbitickpreset", presets.folder("layout") / "Dropped in.cadencepreset")
    raw = json.loads((presets.folder("layout") / "Dropped in.cadencepreset").read_text(encoding="utf-8"))
    raw["name"] = "Dropped in"
    (presets.folder("layout") / "Dropped in.cadencepreset").write_text(json.dumps(raw), encoding="utf-8")
    win().show("layout")
    win().rebuild_page("layout")
step(broken_file, 1000)


def layout_page():
    check("Files dropped into the folder appear", "Dropped in" in [p["name"] for p in presets.load_all("layout")])
    grab(win().win, "layout_presets")
    win().cancel()
    # Double-click a preset file while Orbitick runs: the launcher writes a request and pokes the app.
    src = SHARED / "Weekend.orbitickpreset"
    event = dict(presets.find("event", "Old raids"), name="Weekend")
    presets.export("event", event, src)
    presets.write_request(presets.import_for_launch(str(src)))
    app.commands.put("launch_request")
step(layout_page, 1500)


def launched():
    check("Double-clicked file is imported", presets.find("event", "Weekend") is not None)
    check("...with a message in the window", "Weekend" in status(), status())
    check("...and the window opens on the Event timer page", app.window_open() and win().current == "events",
          getattr(win(), "current", None))
    check("...and the request note is used up", not presets.request_path().exists())
    grab(win().win, "double_click")
    win().cancel()
    bad = SHARED / "nope.orbitickpreset"
    bad.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    presets.write_request(presets.import_for_launch(str(bad)))
    app.commands.put("launch_request")
step(launched, 1500)


def launched_bad():
    check("A bad double-clicked file opens the window with no crash", app.window_open())
    win().cancel()
    app.commands.put("launch_request")  # a plain second launch: no note
step(launched_bad, 1200)


def plain():
    check("A plain second launch still opens the window", app.window_open())
step(plain, 300)

root.after(900, run)
root.mainloop()
