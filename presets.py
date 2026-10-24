"""Preset files: event timer presets and layout presets, one .orbitickpreset file each.

They live in the presets folder next to the settings (presets/event, presets/layout), so they can
be backed up, shared, dropped in by hand, or double-clicked to import. A preset file is JSON:
{"orbitick_preset": kind, "format": 1, "name": ..., ...that kind's own data}.
Files from Cadence (the app's old name: .cadencepreset, "cadence_preset") still import.
"""
import json
import re
from pathlib import Path

import core

EXT = ".orbitickpreset"
OLD_EXT = ".cadencepreset"
EXTS = (EXT, OLD_EXT)
KINDS = {"event": "event timer preset", "layout": "layout preset"}
FILE_TYPES = [("Orbitick presets", f"*{EXT} *{OLD_EXT}"), ("All files", "*.*")]
LAYOUT_KEYS = ("positions", "show", "scales")


def folder(kind=None):
    base = core.SETTINGS_PATH.with_name("presets")
    return base / kind if kind else base


def payload_keys(kind):
    return core.PRESET_KEYS if kind == "event" else LAYOUT_KEYS


def validate(data):
    """A preset file's contents -> (kind, preset dict). Raises ValueError with a message for the user."""
    if isinstance(data, dict) and "orbitick_preset" not in data and "cadence_preset" in data:
        data = dict(data, orbitick_preset=data["cadence_preset"])  # made by Cadence 1.7
    if not isinstance(data, dict) or data.get("orbitick_preset") not in KINDS:
        raise ValueError("This file isn't an Orbitick preset.")
    kind = data["orbitick_preset"]
    name = str(data.get("name", "")).strip()
    missing = [k for k in payload_keys(kind) if k not in data]
    if not name or missing:
        raise ValueError(f"This {KINDS[kind]} is incomplete and can't be used.")
    if kind == "event" and not core.compile_schedule(data["schedule"]):
        raise ValueError("This event timer preset has no valid events in its schedule.")
    preset = {key: data[key] for key in payload_keys(kind)}
    preset["name"] = name
    return kind, preset


def read(path):
    try:
        return validate(json.loads(Path(path).read_text(encoding="utf-8-sig")))  # -sig: Notepad may add a BOM
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("This file couldn't be read as an Orbitick preset.")


def to_json(kind, preset):
    data = {"orbitick_preset": kind, "format": 1, "app_version": core.VERSION, "name": preset["name"]}
    data.update({key: preset[key] for key in payload_keys(kind)})
    return json.dumps(data, indent=2)


def load_all(kind):
    """Every valid preset of this kind in the folder, by name. Broken or foreign files are skipped."""
    out = []
    directory = folder(kind)
    if directory.is_dir():
        for path in [p for ext in EXTS for p in directory.glob(f"*{ext}")]:
            try:
                file_kind, preset = read(path)
            except ValueError:
                continue
            if file_kind == kind:
                out.append(dict(preset, file=str(path)))
    return sorted(out, key=lambda p: p["name"].lower())


def find(kind, name):
    return next((p for p in load_all(kind) if p["name"].lower() == name.lower()), None)


def file_name(name):
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .") or "Preset")[:80]


def save(kind, preset):
    """Write (or overwrite, by name) a preset's file. Returns its path."""
    existing = find(kind, preset["name"])
    if existing and existing["file"].lower().endswith(EXT):
        path = Path(existing["file"])
    else:
        if existing:
            Path(existing["file"]).unlink(missing_ok=True)
        directory = folder(kind)
        directory.mkdir(parents=True, exist_ok=True)
        stem = file_name(preset["name"])
        path, n = directory / f"{stem}{EXT}", 1
        while path.exists():
            n += 1
            path = directory / f"{stem} ({n}){EXT}"
    path.write_text(to_json(kind, preset), encoding="utf-8")
    return path


def delete(kind, name):
    existing = find(kind, name)
    if existing:
        Path(existing["file"]).unlink(missing_ok=True)


def unique_name(kind, name, taken=()):
    names = {p["name"].lower() for p in load_all(kind)} | {t.lower() for t in taken}
    candidate, n = name, 1
    while candidate.lower() in names:
        n += 1
        candidate = f"{name} ({n})"
    return candidate


def import_file(path, reserved=()):
    """Copy a preset file into the folder (renamed if the name is taken). Returns (kind, preset)."""
    kind, preset = read(path)
    preset["name"] = unique_name(kind, preset["name"], reserved if kind == "event" else ())
    save(kind, preset)
    return kind, preset


def export(kind, preset, destination):
    Path(destination).write_text(to_json(kind, preset), encoding="utf-8")


def migrate(settings):
    """Move presets kept inside settings.json (Cadence 1.5 and 1.6) into preset files. Returns True if any moved."""
    moved = False
    for kind, key in (("event", "event_presets"), ("layout", "layout_presets")):
        for preset in settings.get(key) or []:
            try:
                _, clean = validate(dict(preset, orbitick_preset=kind))
            except ValueError:
                continue
            if not find(kind, clean["name"]):
                save(kind, clean)
            moved = True
        settings[key] = []
    # Up to 1.8.0 the app shipped with a built-in event preset. If that one is applied, keep the setup as the
    # user's own preset file so nothing disappears from their list.
    name = settings.get("event_preset") or ""
    if name and not find("event", name):
        try:
            _, clean = validate(dict({k: settings[k] for k in core.PRESET_KEYS}, cadence_preset="event", name=name))
            save("event", clean)
            moved = True
        except (KeyError, ValueError):
            settings["event_preset"] = ""
    return moved


# ---- requests from a second launch (double-clicked preset files) ----------

def request_path():
    return core.SETTINGS_PATH.with_name("request.json")


def write_request(request):
    """Leave a note for the running Orbitick: which page to show and what to say."""
    try:
        request_path().parent.mkdir(parents=True, exist_ok=True)
        request_path().write_text(json.dumps(request), encoding="utf-8")
    except OSError:
        pass


def take_request():
    path = request_path()
    try:
        request = json.loads(path.read_text(encoding="utf-8-sig"))
        path.unlink(missing_ok=True)
        return request if isinstance(request, dict) else None
    except (OSError, ValueError):
        return None


def import_for_launch(path):
    """Import a double-clicked preset file and describe the outcome for the app window."""
    try:
        kind, preset = import_file(path)
    except ValueError as e:
        return {"page": "events", "message": str(e), "error": True}
    return {"page": "events" if kind == "event" else "layout",
            "message": f"Imported the {KINDS[kind]} “{preset['name']}”. Select it to apply it."}
