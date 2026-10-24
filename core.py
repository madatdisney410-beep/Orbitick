"""Schedule maths, settings storage, hotkey parsing and sounds. No UI in here."""
import copy
import json
import os
import re
import threading
from datetime import timedelta
from pathlib import Path

try:
    import winsound
except ImportError:
    winsound = None

APP_NAME = "Orbitick"
VERSION = "1.8.1"
# Per-user data lives outside the install folder so updates and reinstalls keep it.
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "error.log"
OLD_DATA_DIR = DATA_DIR.with_name("Cadence")  # the app was called Cadence up to 1.7


def move_old_data():
    """Bring settings, alarms, calendar, media and presets over from Cadence (once, on first start)."""
    if DATA_DIR.exists() or not OLD_DATA_DIR.is_dir():
        return
    import shutil
    try:
        OLD_DATA_DIR.rename(DATA_DIR)
    except OSError:  # in use (an old copy still running): copy instead
        shutil.copytree(OLD_DATA_DIR, DATA_DIR)
    old, new = str(OLD_DATA_DIR), str(DATA_DIR)

    def fix(value):  # files inside the old folder (custom images, tones) are now in the new one
        if isinstance(value, str) and value.lower().startswith(old.lower()):
            return new + value[len(old):]
        if isinstance(value, list):
            return [fix(v) for v in value]
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        return value
    for path in DATA_DIR.glob("*.json"):
        try:
            path.write_text(json.dumps(fix(json.loads(path.read_text(encoding="utf-8-sig"))), indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

# Minutes past the hour; the list repeats every hour. A neutral example to replace with your own events.
DEFAULT_SCHEDULE = [
    {"at": "00:00", "bosses": "Top of the hour"},
    {"at": "15:00", "bosses": "Quarter past"},
    {"at": "30:00", "bosses": "Half past"},
    {"at": "45:00", "bosses": "Quarter to"},
]

# The look of a panel. Each panel keeps its own copy, so every one can be styled separately.
STYLE_DEFAULTS = {
    "shape": "card",  # "card" or "reactor" (the arc); the upcoming list is always a card
    "opacity": 1.0,
    "bg_opacity": 0.84,
    "scale": 1.0,
    "width": 300,
    "bg": "#0b1017",
    "fg": "#eef3fa",
    "dim": "#8794a8",
    "accent": "#3ad0ff",
    "warn": "#ffb547",
    "live": "#4ade80",
    "panel_effect": "none",  # see effects.EFFECTS
    "effect_speed": 1.0,
    "effect_strength": 0.7,
    "custom_bg": "",  # your own image/animation (copied into DATA_DIR/backgrounds)
    "custom_fit": "fill",  # fill, stretch or fit
    "animate": True,
}
# The app window's own look (App settings). Everything else is derived from these three colours.
THEME_PRESETS = {
    "midnight": ("Midnight", "#0c0f14", "#3ad0ff", "#e9edf3"),
    "graphite": ("Graphite", "#161719", "#a5b4fc", "#ececf1"),
    "ocean": ("Ocean", "#08151f", "#2dd4bf", "#e2f0f4"),
    "forest": ("Forest", "#0b130f", "#4ade80", "#e5f1e9"),
    "rose": ("Rose", "#150c11", "#fb7185", "#f6e8ee"),
    "light": ("Light", "#f3f5f9", "#2563eb", "#141922"),
}
THEME_DEFAULTS = {
    "bg": "#0c0f14", "accent": "#3ad0ff", "text": "#e9edf3",
    # A background for the window's sidebar and page header, like the panels' backgrounds.
    "effect": "none", "custom_bg": "", "custom_fit": "fill", "effect_strength": 0.6, "effect_speed": 1.0,
}

PANELS = {"timer": "Event timer", "list": "Upcoming list", "stopwatch": "Stopwatch", "notification": "Notifications"}
SHAPED_PANELS = ("timer", "stopwatch", "notification")  # panels that can be a card or an arc

DEFAULTS = {
    "schedule": DEFAULT_SCHEDULE,
    "styles": {name: dict(STYLE_DEFAULTS, **({"width": 320} if name == "notification" else {})) for name in PANELS},
    "font": "Segoe UI",
    "font_files": [],
    "theme": dict(THEME_DEFAULTS),
    # Panel positions and visibility. None = not placed yet: it's put next to the timer when first shown.
    "x": 40,
    "y": 40,
    "list_x": None,
    "list_y": None,
    "stopwatch_x": None,
    "stopwatch_y": None,
    "notify_x": None,  # None: the top-right corner of the screen
    "notify_y": None,
    "show_timer": True,
    "show_list": True,
    "show_stopwatch": False,
    "split_list": False,  # card only; the arc always shows the list as its own panel
    "link_panels": False,  # dragging any panel moves all of them, keeping their spacing
    "layout_presets": [],  # likewise; layouts are preset files now
    "layout_preset": "",  # the one last applied
    "locked": False,
    "click_through": False,
    # Event timer: wording on the overlay itself, so it can time anything.
    "event_presets": [],  # only read to move old presets into preset files (presets.py)
    "event_preset": "",  # the one last applied
    "title": "Event Timer",
    "next_label": "Next event",
    "past_label": "Started",
    "list_label": "Upcoming",
    "show_clock": True,
    "clock_24h": False,
    "upcoming": 3,
    # Stopwatch
    "stopwatch_label": "Stopwatch",
    "stopwatch_hundredths": True,
    "stopwatch_laps": 3,
    # Notifications (alarms and calendar reminders)
    "reminder_sound": "tone:chime",
    "reminder_volume": 0.8,
    "alarm_timeout": 5,  # minutes an alarm keeps sounding before it goes quiet (the notification stays)
    # Alerts & timing
    "just_spawned_seconds": 120,
    "sound": True,
    "warn_seconds": 60,
    "warn_sound": "",
    "spawn_sound": "",
    "offset_seconds": 0,
    "hotkeys": {
        "toggle_visible": "Ctrl+Alt+B",
        "toggle_click_through": "Ctrl+Alt+N",
        "open_settings": "Ctrl+Alt+S",
        "stopwatch_toggle": "Ctrl+Alt+P",
        "stopwatch_lap": "Ctrl+Alt+L",
        "stopwatch_reset": "",
        "dismiss_notification": "Ctrl+Alt+D",
        "snooze_notification": "Ctrl+Alt+Z",
    },
}
# What an event timer preset holds: a whole setup you can switch to in one click.
PRESET_KEYS = ("schedule", "title", "next_label", "past_label", "list_label", "warn_seconds", "just_spawned_seconds")

HOTKEY_LABELS = {
    "toggle_visible": "Show or hide the overlay",
    "toggle_click_through": "Turn click-through on or off",
    "open_settings": "Open settings",
    "stopwatch_toggle": "Start or stop the stopwatch",
    "stopwatch_lap": "Record a stopwatch lap",
    "stopwatch_reset": "Reset the stopwatch",
    "dismiss_notification": "Dismiss a notification",
    "snooze_notification": "Snooze a notification",
}
COLOR_KEYS = ["bg", "accent", "fg", "dim", "warn", "live"]
MAX_UPCOMING = 12

WARN_BEEP = [(880, 120), (880, 120)]
SPAWN_BEEP = [(660, 120), (880, 120), (1100, 200)]


# ---- schedule ---------------------------------------------------------------

def parse_at(at):
    """'MM' or 'MM:SS' past the hour -> seconds, or None if invalid."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{1,2}))?\s*", at)
    if not m:
        return None
    minute, second = int(m.group(1)), int(m.group(2) or 0)
    return minute * 60 + second if minute < 60 and second < 60 else None


def compile_schedule(entries):
    """Settings entries -> sorted [(seconds past the hour, bosses)], skipping invalid ones."""
    out = []
    for entry in entries:
        offset = parse_at(str(entry.get("at", "")))
        bosses = str(entry.get("bosses", "")).strip()
        if offset is not None and bosses:
            out.append((offset, bosses))
    return sorted(out)


def validate_schedule(rows):
    """[(at text, bosses text)] from the editor -> settings entries.

    Raises ValueError(row index, message) on the first bad row; blank rows are dropped.
    """
    entries = []
    for i, (at, bosses) in enumerate(rows):
        if not at.strip() and not bosses.strip():
            continue
        offset = parse_at(at)
        if offset is None:
            raise ValueError(i, f"â€œ{at.strip() or '(blank)'}â€ is not a valid time. Enter minutes past the hour, such as 05 or 05:30.")
        if not bosses.strip():
            raise ValueError(i, f"Enter a name for the event at {at.strip()}.")
        entries.append({"at": f"{offset // 60:02d}:{offset % 60:02d}", "bosses": bosses.strip()})
    return sorted(entries, key=lambda e: e["at"])


def spawns_after(now, schedule, count):
    """The next `count` spawns strictly after `now`, as (time, bosses)."""
    if not schedule:
        return []
    out = []
    hour = now.replace(minute=0, second=0, microsecond=0)
    while len(out) < count:
        for offset, bosses in schedule:
            t = hour + timedelta(seconds=offset)
            if t > now:
                out.append((t, bosses))
                if len(out) == count:
                    break
        hour += timedelta(hours=1)
    return out


def last_spawn(now, schedule):
    """The most recent spawn at or before `now`, as (time, bosses), or None."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    for h in (hour, hour - timedelta(hours=1)):
        past = [(h + timedelta(seconds=o), b) for o, b in schedule if h + timedelta(seconds=o) <= now]
        if past:
            return past[-1]
    return None


def split_bosses(bosses):
    return [b.strip() for b in bosses.split("&") if b.strip()]


def fmt_time(t, clock_24h, seconds=False):
    if clock_24h:
        return t.strftime("%H:%M:%S" if seconds else "%H:%M")
    return t.strftime("%I:%M:%S %p" if seconds else "%I:%M %p").lstrip("0")


def fmt_countdown(secs):
    if secs >= 3600:
        return f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}"
    return f"{secs // 60}:{secs % 60:02d}"


# ---- settings ---------------------------------------------------------------

def load_settings():
    settings = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    settings.update({k: v for k, v in saved.items() if k in DEFAULTS and k not in ("hotkeys", "styles", "theme")})
    if isinstance(saved.get("hotkeys"), dict):
        settings["hotkeys"].update(saved["hotkeys"])
    settings["theme"] = dict(THEME_DEFAULTS)
    if isinstance(saved.get("theme"), dict):
        settings["theme"].update({k: v for k, v in saved["theme"].items() if k in THEME_DEFAULTS})

    styles = saved.get("styles")
    if not isinstance(styles, dict):
        # Settings from before per-panel styles: the single old look becomes the timer's and the list's.
        old = {k: saved[k] for k in STYLE_DEFAULTS if k in saved}
        styles = {"timer": old, "list": dict(old, scale=saved.get("list_scale", old.get("scale", 1.0)))}
    for name in PANELS:
        style = settings["styles"][name]
        saved_style = styles.get(name)
        if isinstance(saved_style, dict):
            style.update({k: v for k, v in saved_style.items() if k in STYLE_DEFAULTS})
        if style["shape"] not in ("card", "reactor"):
            style["shape"] = "card"

    settings["layout_presets"] = [p for p in settings["layout_presets"]
                                  if isinstance(p, dict) and p.get("name") and {"positions", "show", "scales"} <= set(p)]
    settings["event_presets"] = [p for p in settings["event_presets"]
                                 if isinstance(p, dict) and p.get("name") and all(k in p for k in PRESET_KEYS)]
    if not compile_schedule(settings["schedule"]):
        settings["schedule"] = copy.deepcopy(DEFAULT_SCHEDULE)
    return settings



def panel_style(settings, name):
    """Everything a panel's renderer needs: the shared settings with that panel's own look on top."""
    return {**settings, **settings["styles"][name]}


def save_settings(settings):
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---- hotkeys ----------------------------------------------------------------

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
NAMED_KEYS = {
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "insert": 0x2D, "delete": 0x2E, "tab": 0x09, "pause": 0x13,
}


def parse_hotkey(text):
    """'Ctrl+Alt+B' -> (modifiers, virtual key), or None if it isn't a valid combo."""
    mods, vk = 0, None
    for part in (p.strip().lower() for p in text.split("+")):
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif vk is not None:
            return None
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif re.fullmatch(r"f([1-9]|1\d|2[0-4])", part):
            vk = 0x70 + int(part[1:]) - 1
        elif part in NAMED_KEYS:
            vk = NAMED_KEYS[part]
        else:
            return None
    return (mods, vk) if vk is not None else None


# ---- sound ------------------------------------------------------------------

def play(path, fallback):
    if winsound is None:
        return
    if path and Path(path).is_file():
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    else:
        # Beep blocks, so play it off the UI thread.
        threading.Thread(target=lambda: [winsound.Beep(f, d) for f, d in fallback], daemon=True).start()
