"""Orbitick: a standalone overlay that counts down to events that repeat on a schedule.

It only reads the PC clock. It never touches, reads or injects into any other app;
it's just a window that stays above whatever is fullscreen (borderless/windowed fullscreen).

This is the entry point for both the installed Orbitick.exe and running from source.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import LOG_PATH, move_old_data  # noqa: E402


def log_error(text):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log.write(text + "\n")
    except OSError:
        pass


def main():
    try:
        import PIL  # noqa: F401
    except ImportError:
        import tkinter as tk
        from tkinter import messagebox
        tk.Tk().withdraw()
        messagebox.showerror("Orbitick", "Orbitick needs Pillow. Open a terminal and run:\n\npip install pillow")
        return

    try:
        move_old_data()  # the app was called Cadence up to 1.7
    except Exception:
        log_error(traceback.format_exc())
    import presets
    import winapi
    # Double-clicking a preset file starts Orbitick with it: import it, and leave a note for the window.
    preset_file = next((a for a in sys.argv[1:] if a.lower().endswith(presets.EXTS)), None)
    if preset_file:
        presets.write_request(presets.import_for_launch(preset_file))
    instance = winapi.SingleInstance()
    if not instance.first:
        instance.poke_existing()  # already running: it shows its window (and the note, if any)
        return
    winapi.set_app_id("Orbitick.Overlay")
    winapi.enable_dpi_awareness()

    from overlay import Overlay
    app = Overlay(instance)
    # A windowed app has no console, so keep a log of anything that goes wrong.
    app.root.report_callback_exception = lambda *exc: log_error("".join(traceback.format_exception(*exc)))
    app.root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
