"""Alarm and reminder sounds: built-in tones and your own audio files.

Built-in tones are generated once as WAV files (no audio assets to ship). Everything plays
through Windows MCI, so MP3, WAV and WMA files all work, looped if needed, at any volume.
A sound is named either "tone:<name>" or by a file path.
"""
import ctypes
import itertools
import math
import struct
import sys
import wave
from pathlib import Path

import core

TONES = [("radar", "Radar"), ("chime", "Chime"), ("pulse", "Pulse"), ("beacon", "Beacon"), ("digital", "Digital")]
AUDIO_TYPES = [("Audio files", "*.mp3 *.wav *.wma *.m4a"), ("All files", "*.*")]
RATE = 22050


def _note(freq, ms, volume=0.5, decay=0.0, harmonics=((1, 1.0),)):
    count = int(RATE * ms / 1000)
    fade = RATE * 0.006  # short fades at both ends avoid clicks
    two_pi_f = 2 * math.pi * freq
    out = []
    for i in range(count):
        t = i / RATE
        level = volume * min(1.0, i / fade, (count - i) / fade) * (math.exp(-decay * t) if decay else 1.0)
        out.append(level * sum(a * math.sin(two_pi_f * h * t) for h, a in harmonics))
    return out


def _rest(ms):
    return [0.0] * int(RATE * ms / 1000)


BELL = ((1, 1.0), (2, 0.35), (3, 0.12))
PATTERNS = {
    "radar": lambda: _note(1046, 90) + _rest(60) + _note(1046, 90) + _rest(60) + _note(1318, 110) + _rest(650),
    "chime": lambda: _note(880, 800, 0.45, 3.0, BELL) + _note(659, 1100, 0.45, 2.4, BELL) + _rest(300),
    "pulse": lambda: sum((_note(523, 260, 0.45, 5.0, BELL) + _rest(240) for _ in range(3)), []) + _rest(400),
    "beacon": lambda: _note(587, 150, 0.4) + _note(740, 150, 0.4) + _note(880, 240, 0.4, 2.0) + _rest(760),
    "digital": lambda: sum((_note(2048, 60, 0.3) + _rest(60) for _ in range(4)), []) + _rest(560),
}


def tone_path(name):
    """The WAV file for a built-in tone, generated the first time it's needed."""
    name = name if name in PATTERNS else "radar"
    path = core.SETTINGS_PATH.with_name("tones") / f"{name}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        samples = PATTERNS[name]()
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32000)) for v in samples))
    return path


def resolve(sound):
    """A sound setting -> a playable file path (falling back to the default tone)."""
    if sound and sound.startswith("tone:"):
        return tone_path(sound[5:])
    if sound and Path(sound).is_file():
        return Path(sound)
    return tone_path("radar")


def describe(sound):
    if sound and sound.startswith("tone:"):
        return dict(TONES).get(sound[5:], "Radar")
    return Path(sound).name if sound else "Radar"


def _mci(command):
    if sys.platform != "win32":
        return 1
    return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)


class Player:
    """Plays one sound at a time. Call from the UI thread (MCI devices belong to the thread that opened them)."""
    _ids = itertools.count(1)

    def __init__(self):
        self.alias = None
        self.looping = False

    def play(self, sound, loop=False, volume=1.0):
        self.stop()
        alias = f"orbitick{next(self._ids)}"
        if _mci(f'open "{resolve(sound)}" type mpegvideo alias {alias}'):
            return False
        self.alias, self.looping = alias, loop
        _mci(f"setaudio {alias} volume to {round(max(0.0, min(1.0, volume)) * 1000)}")
        _mci(f"play {alias}{' repeat' if loop else ''}")
        return True

    def stop(self):
        if self.alias:
            _mci(f"close {self.alias}")
        self.alias, self.looping = None, False
