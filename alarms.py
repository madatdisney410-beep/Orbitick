"""Alarms, like a phone's clock app: a time, a label, and either repeat days (weekly) or a date
(once), plus a sound and snooze.

Alarms are your data rather than settings, so they're saved the moment they change
(alarms.json next to the settings). Each enabled alarm remembers its next ring time.
"""
import json
import uuid
from datetime import date, datetime, time, timedelta

import core

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MISSED_LIMIT = timedelta(minutes=10)  # ring late (e.g. after the PC wakes) only if this recent


def new_alarm(**values):
    alarm = {"id": uuid.uuid4().hex, "time": "07:00", "label": "Alarm", "days": [], "date": None, "enabled": True,
             "sound": "tone:radar", "volume": 0.8, "snooze": 9, "next": None}
    alarm.update(values)
    return alarm


def parse_hm(text):
    """'7:30' or '07:30' -> (7, 30), or None."""
    try:
        h, m = (int(p) for p in str(text).strip().split(":"))
    except ValueError:
        return None
    return (h, m) if 0 <= h < 24 and 0 <= m < 60 else None


def alarm_date(alarm):
    try:
        return date.fromisoformat(alarm["date"]) if alarm.get("date") else None
    except ValueError:
        return None


def next_occurrence(alarm, after):
    """The first time after `after` that this alarm should ring, or None (an invalid time, or a
    one-time alarm whose date and time have passed)."""
    hm = parse_hm(alarm["time"])
    if not hm:
        return None
    on = alarm_date(alarm)
    if not alarm["days"] and on:
        at = datetime.combine(on, time(*hm))
        return at if at > after else None
    for offset in range(8):
        day = after.date() + timedelta(days=offset)
        if alarm["days"] and day.weekday() not in alarm["days"]:
            continue
        at = datetime.combine(day, time(*hm))
        if at > after:
            return at
    return None


def describe_day(day, today=None):
    today = today or date.today()
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%a %d %b").replace(" 0", " ")


def repeat_summary(days, on=None):
    days = sorted(set(days))
    if not days:
        return f"Once · {describe_day(on)}" if on else "Once"
    if days == list(range(7)):
        return "Every day"
    if days == list(range(5)):
        return "Weekdays"
    if days == [5, 6]:
        return "Weekends"
    return ", ".join(DAYS[d] for d in days)


def _iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def _parse(text):
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


class AlarmBook:
    def __init__(self, path=None):
        self.path = path or core.SETTINGS_PATH.with_name("alarms.json")
        self.alarms = []
        self.snoozes = []  # [{"id": alarm id, "at": iso}]
        self.load()

    # ---- storage ----

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.alarms = [new_alarm(**a) for a in data.get("alarms", []) if isinstance(a, dict)]
            self.snoozes = [s for s in data.get("snoozes", []) if isinstance(s, dict) and _parse(s.get("at"))]
        except (OSError, ValueError, AttributeError, TypeError):
            self.alarms, self.snoozes = [], []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"alarms": self.alarms, "snoozes": self.snoozes}, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- editing ----

    def get(self, alarm_id):
        return next((a for a in self.alarms if a["id"] == alarm_id), None)

    def put(self, alarm, now=None):
        """Add or replace an alarm, and work out when it next rings."""
        now = now or datetime.now()
        if not alarm["days"] and not alarm_date(alarm):
            # A one-time alarm without a date rings at the next time it comes round (today or tomorrow).
            upcoming = next_occurrence(dict(alarm, date=None), now)
            alarm["date"] = upcoming.date().isoformat() if upcoming else None
        if alarm["days"]:
            alarm["date"] = None
        alarm["next"] = _iso(next_occurrence(alarm, now)) if alarm["enabled"] else None
        for i, a in enumerate(self.alarms):
            if a["id"] == alarm["id"]:
                self.alarms[i] = alarm
                break
        else:
            self.alarms.append(alarm)
        self.alarms.sort(key=lambda a: parse_hm(a["time"]) or (99, 99))
        self.snoozes = [s for s in self.snoozes if s["id"] != alarm["id"]]
        self.save()

    def set_enabled(self, alarm_id, enabled, now=None):
        alarm = self.get(alarm_id)
        if alarm:
            alarm["enabled"] = enabled
            self.put(alarm, now)

    def delete(self, alarm_id):
        self.alarms = [a for a in self.alarms if a["id"] != alarm_id]
        self.snoozes = [s for s in self.snoozes if s["id"] != alarm_id]
        self.save()

    def snooze(self, alarm_id, minutes, now=None):
        now = now or datetime.now()
        self.snoozes.append({"id": alarm_id, "at": _iso(now + timedelta(minutes=max(1, minutes)))})
        self.save()

    # ---- ringing ----

    def due(self, now=None):
        """Alarms (and snoozes) whose time has come. Moves repeating alarms on to their next day and
        switches one-time alarms off, as a phone does."""
        now = now or datetime.now()
        ringing, changed = [], False
        for alarm in self.alarms:
            at = _parse(alarm["next"])
            if not (alarm["enabled"] and at and now >= at):
                continue
            if now - at <= MISSED_LIMIT:
                ringing.append(alarm)
            if alarm["days"]:
                alarm["next"] = _iso(next_occurrence(alarm, now))
            else:
                alarm["enabled"], alarm["next"] = False, None
            changed = True
        for snooze in list(self.snoozes):
            if now >= _parse(snooze["at"]):
                self.snoozes.remove(snooze)
                alarm = self.get(snooze["id"])
                if alarm:
                    ringing.append(alarm)
                changed = True
        if changed:
            self.save()
        return ringing

    def on_day(self, day):
        """[(time, alarm)] ringing on `day`, for the calendar: repeating alarms on their weekdays,
        one-time alarms on the day they're set for."""
        out = []
        for alarm in self.alarms:
            hm = parse_hm(alarm["time"])
            if not (alarm["enabled"] and hm):
                continue
            if alarm["days"]:
                if day.weekday() in alarm["days"] and day >= date.today():
                    out.append((time(*hm), alarm))
            else:
                at = _parse(alarm["next"])
                if at and at.date() == day:
                    out.append((time(*hm), alarm))
        return sorted(out, key=lambda pair: pair[0])
