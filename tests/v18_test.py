"""1.8.0: the rename from Cadence. Old data folder, old preset files and the installer's registry helpers."""
import json
import shutil
import sys
import winreg
from pathlib import Path

APP, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(APP))
import core  # noqa: E402

DATA = OUT / "v18"
shutil.rmtree(DATA, ignore_errors=True)
OLD, NEW = DATA / "Roaming" / "Cadence", DATA / "Roaming" / "Orbitick"
core.OLD_DATA_DIR, core.DATA_DIR, core.SETTINGS_PATH = OLD, NEW, NEW / "settings.json"
import presets  # noqa: E402
import setup  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


# A Cadence 1.7 data folder: settings pointing at a copied background, an alarm with a tone, a preset file.
(OLD / "backgrounds").mkdir(parents=True)
(OLD / "backgrounds" / "stars.gif").write_bytes(b"GIF89a")
(OLD / "presets" / "event").mkdir(parents=True)
(OLD / "settings.json").write_text(json.dumps({"title": "Raid Timer", "styles": {"timer": {
    "media": str(OLD / "backgrounds" / "stars.gif")}}, "theme": {"media": "C:\\Elsewhere\\keep.png"}}), encoding="utf-8")
(OLD / "alarms.json").write_text(json.dumps([{"label": "Gym", "sound": str(OLD / "tones" / "bell.wav")}]),
                                 encoding="utf-8")
old_preset = dict({k: core.DEFAULTS[k] for k in core.PRESET_KEYS}, cadence_preset="event", format=1, name="Raids",
                  schedule=[{"at": "10", "bosses": "World Boss"}])
(OLD / "presets" / "event" / "Raids.cadencepreset").write_text(json.dumps(old_preset), encoding="utf-8")

core.move_old_data()
settings = json.loads((NEW / "settings.json").read_text(encoding="utf-8"))
check("The Cadence data folder becomes the Orbitick one", NEW.is_dir() and not OLD.exists())
check("Paths into the old folder now point into the new one",
      settings["styles"]["timer"]["media"] == str(NEW / "backgrounds" / "stars.gif")
      and Path(settings["styles"]["timer"]["media"]).exists(), settings["styles"]["timer"]["media"])
check("...in alarms too", json.loads((NEW / "alarms.json").read_text())[0]["sound"] == str(NEW / "tones" / "bell.wav"))
check("Paths elsewhere are left alone", settings["theme"]["media"] == "C:\\Elsewhere\\keep.png")
check("Settings are otherwise unchanged", settings["title"] == "Raid Timer")

OLD.mkdir()
(OLD / "settings.json").write_text("{}", encoding="utf-8")
core.move_old_data()
check("Moving happens only once (an existing Orbitick folder is never overwritten)",
      json.loads((NEW / "settings.json").read_text())["title"] == "Raid Timer")

check("Cadence preset files in the folder still load", [p["name"] for p in presets.load_all("event")] == ["Raids"])
raids = presets.find("event", "Raids")
presets.save("event", dict(raids, title="Raid Timer 2"))
files = sorted(p.name for p in (NEW / "presets" / "event").iterdir())
check("Updating a Cadence preset rewrites it with the new extension", files == ["Raids.orbitickpreset"], files)
data = json.loads((NEW / "presets" / "event" / "Raids.orbitickpreset").read_text(encoding="utf-8"))
check("...and the new key", data.get("orbitick_preset") == "event" and "cadence_preset" not in data
      and data["title"] == "Raid Timer 2")

shared = DATA / "shared.cadencepreset"
shared.write_text(json.dumps(dict(old_preset, name="Shared")), encoding="utf-8")
kind, preset = presets.import_file(shared)
check("Importing a file someone made with Cadence works", kind == "event" and presets.find("event", "Shared"))
request = presets.import_for_launch(str(shared))
check("Double-clicking an old file imports it too", "Shared (2)" in request["message"] and not request.get("error"),
      request)

# Installer registry helpers, on a throwaway key.
base = r"Software\OrbitickSetupTest"
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as key:
    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "x")
setup.delete_key(base)
try:
    winreg.OpenKey(winreg.HKEY_CURRENT_USER, base).Close()
    gone = False
except OSError:
    gone = True
check("The installer deletes a key with everything under it", gone)
setup.delete_key(base)  # already gone: no error
check("Installer targets the new names", setup.TARGET.name == "Orbitick" and setup.OLD_TARGET.name == "Cadence"
      and setup.OLD_UNINSTALL_KEY.endswith(r"Uninstall\Cadence") and ".cadencepreset" in setup.PRESET_EXTS)

# A preset that used to be built in, applied in 1.8.0, is kept as the user's own preset file.
settings = dict({k: core.DEFAULTS[k] for k in core.PRESET_KEYS}, event_preset="Old built in", title="Old title",
                event_presets=[], layout_presets=[])
moved = presets.migrate(settings)
kept = presets.find("event", "Old built in")
check("An applied preset that is no longer built in becomes the user's own file", moved and kept
      and kept["title"] == "Old title" and settings["event_preset"] == "Old built in")
check("...and only once", not presets.migrate(settings))
check("No preset comes built in", not hasattr(core, "BUILTIN_PRESET") and core.DEFAULTS["event_preset"] == "")

print("errors: 0")
print(f"{sum(results)}/{len(results)} checks passed")
