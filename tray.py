"""System tray icon. Optional: without pystray installed the app simply runs without one."""
import threading

from core import APP_NAME
from render import logo


def start_tray(app):
    """Show the tray icon; menu clicks are queued as commands for the Tk thread."""
    try:
        import pystray
    except ImportError:
        return None

    def send(command):
        return lambda: app.commands.put(command)

    menu = pystray.Menu(
        pystray.MenuItem("Open Orbitick", send("open_settings"), default=True),
        pystray.MenuItem("Calendar", send("open_calendar")),
        pystray.MenuItem("Alarms", send("open_alarms")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Show overlay", send("toggle_visible"), checked=lambda item: not app.hidden),
        pystray.MenuItem("Event timer", send("toggle_timer"), checked=lambda item: app.view["show_timer"]),
        pystray.MenuItem("Upcoming list", send("toggle_list"), checked=lambda item: app.view["show_list"]),
        pystray.MenuItem("Stopwatch", send("toggle_stopwatch_panel"), checked=lambda item: app.view["show_stopwatch"]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: "Stop stopwatch" if app.watch.running else "Start stopwatch", send("stopwatch_toggle")),
        pystray.MenuItem("Reset stopwatch", send("stopwatch_reset")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Click-through", send("toggle_click_through"),
                         checked=lambda item: app.view["click_through"]),
        pystray.MenuItem("Sound alerts", send("toggle_sound"), checked=lambda item: app.view["sound"]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Quit {APP_NAME}", send("quit")),
    )
    icon = pystray.Icon(APP_NAME, logo(64), APP_NAME, menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon
