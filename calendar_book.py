"""The calendar: dated events with tags, reminders and notes.

Events are your data, saved the moment they change (calendar.json next to the settings).
An event is crossed off once it's over (or when you mark it done), never deleted for you.
The event timer's repeating schedule deliberately doesn't appear here.
"""
import json
import uuid
from datetime import date, datetime, time, timedelta

import core
from alarms import parse_hm

DEFAULT_TAGS = [
    {"id": "important", "name": "Important", "color": "#ff5d73"},
    {"id": "school", "name": "School", "color": "#3ad0ff"},
    {"id": "work", "name": "Work", "color": "#ffb547"},
    {"id": "personal", "name": "Personal", "color": "#4ade80"},
]
REMINDERS = [(None, "None"), (0, "At start"), (5, "5 min before"), (15, "15 min before"), (30, "30 min before"),
             (60, "1 hour before"), (1440, "1 day before")]
LATE_LIMIT = timedelta(minutes=10)  # a reminder this late (PC asleep, app closed) still shows; older ones don't


def new_event(**values):
    event = {"id": uuid.uuid4().hex, "title": "New event", "date": date.today().isoformat(), "all_day": False,
             "start": "09:00", "end": "", "tag": "", "notes": "", "reminder": 0, "done": False, "notified": False}
    event.update(values)
    return event


def event_day(event):
    try:
        return date.fromisoformat(event["date"])
    except ValueError:
        return date.today()


def starts(event):
    hm = parse_hm(event["start"]) if not event["all_day"] else None
    return datetime.combine(event_day(event), time(*hm) if hm else time(0, 0))


def ends(event):
    """When an event is over: its end time, else its start time; all-day events last the whole day."""
    if event["all_day"]:
        return datetime.combine(event_day(event) + timedelta(days=1), time(0, 0))
    hm = parse_hm(event["end"])
    end = datetime.combine(event_day(event), time(*hm)) if hm else starts(event)
    return max(end, starts(event))


def time_range(event, clock_24h):
    if event["all_day"]:
        return "All day"
    text = core.fmt_time(starts(event), clock_24h)
    if parse_hm(event["end"]):
        text += " – " + core.fmt_time(ends(event), clock_24h)
    return text


class CalendarBook:
    def __init__(self, path=None):
        self.path = path or core.SETTINGS_PATH.with_name("calendar.json")
        self.events = []
        self.tags = [dict(t) for t in DEFAULT_TAGS]
        self.snoozes = []  # [{"id": event id, "at": iso}]
        self.load()

    # ---- storage ----

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.events = [new_event(**e) for e in data.get("events", []) if isinstance(e, dict)]
            if isinstance(data.get("tags"), list):
                self.tags = [t for t in data["tags"] if isinstance(t, dict) and {"id", "name", "color"} <= set(t)]
            self.snoozes = [s for s in data.get("snoozes", []) if isinstance(s, dict) and "at" in s]
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"events": self.events, "tags": self.tags, "snoozes": self.snoozes},
                                            indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- events ----

    def get(self, event_id):
        return next((e for e in self.events if e["id"] == event_id), None)

    def put(self, event):
        """Add or replace an event. Changing its time re-arms its reminder."""
        old = self.get(event["id"])
        if old and (old["date"], old["start"], old["all_day"], old["reminder"]) != \
                (event["date"], event["start"], event["all_day"], event["reminder"]):
            event["notified"] = False
        self.events = [e for e in self.events if e["id"] != event["id"]] + [event]
        self.save()

    def delete(self, event_id):
        self.events = [e for e in self.events if e["id"] != event_id]
        self.snoozes = [s for s in self.snoozes if s["id"] != event_id]
        self.save()

    def set_done(self, event_id, done):
        event = self.get(event_id)
        if event:
            event["done"] = done
            self.save()

    def is_done(self, event, now=None):
        return event["done"] or ends(event) <= (now or datetime.now())

    def on_day(self, day):
        """Events on `day`: all-day ones first, then by start time."""
        return sorted((e for e in self.events if event_day(e) == day),
                      key=lambda e: (not e["all_day"], starts(e), e["title"].lower()))

    def tag(self, tag_id):
        return next((t for t in self.tags if t["id"] == tag_id), None)

    # ---- tags ----

    def put_tag(self, tag):
        self.tags = [t for t in self.tags if t["id"] != tag["id"]] + [tag]
        self.save()

    def delete_tag(self, tag_id):
        self.tags = [t for t in self.tags if t["id"] != tag_id]
        for event in self.events:
            if event["tag"] == tag_id:
                event["tag"] = ""
        self.save()

    @staticmethod
    def new_tag(name="New tag", color="#a78bfa"):
        return {"id": uuid.uuid4().hex, "name": name, "color": color}

    # ---- reminders ----

    def snooze(self, event_id, minutes, now=None):
        now = now or datetime.now()
        self.snoozes.append({"id": event_id, "at": (now + timedelta(minutes=max(1, minutes))).isoformat(timespec="seconds")})
        self.save()

    def due(self, now=None):
        """Events whose reminder time has come (each reminds once), plus snoozed ones."""
        now = now or datetime.now()
        reminding, changed = [], False
        for event in self.events:
            if event["notified"] or event["reminder"] is None or event["done"]:
                continue
            at = starts(event) - timedelta(minutes=event["reminder"])
            if now >= at:
                event["notified"] = True
                changed = True
                if now - at <= LATE_LIMIT and now < ends(event) + LATE_LIMIT:
                    reminding.append(event)
        for snooze in list(self.snoozes):
            try:
                at = datetime.fromisoformat(snooze["at"])
            except ValueError:
                at = now
            if now >= at:
                self.snoozes.remove(snooze)
                event = self.get(snooze["id"])
                if event and not event["done"]:
                    reminding.append(event)
                changed = True
        if changed:
            self.save()
        return reminding
