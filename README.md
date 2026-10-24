# Orbitick

An overlay timer for Windows that stays on top of any fullscreen app. It counts down to events that repeat on a schedule, and also has alarms, a calendar and a stopwatch.

Orbitick is a separate program. It only reads your PC clock, and it never reads from, modifies or injects into any other app.

**Version:** 1.8.1

## Download

Get the latest version from the [Releases page](../../releases/latest).

* **Orbitick Setup.exe:** the installer. It installs for your Windows account only, so no administrator rights are needed. Use this one if you are not sure.
* **Orbitick 1.8.1 Portable.zip:** no installation. Unzip it anywhere and run `Orbitick.exe`.

The app is not code signed yet, so Windows SmartScreen may show "Windows protected your PC". Click **More info**, then **Run anyway**.

## Recent update: 1.8.1

* **Your own schedule from the start:** Orbitick no longer comes with a built in event preset. New installs start with a simple example schedule to replace with your own events. If you had the old built in preset applied, it is kept as your own preset file.
* **Clearer wording:** the app and this page now say plainly that Orbitick never reads from, modifies or injects into any other app.

## 1.8.0

* **New name:** Cadence is now **Orbitick**. Installing Orbitick replaces Cadence, and your settings, alarms, calendar and presets come with it.
* **Portable version:** a ZIP download that runs without installing.
* **Preset files:** presets are now `.orbitickpreset` files in your presets folder. You can import, export and share them, or double click one to import it. Presets made with Cadence still work.

## Features

* **Event timer:** a repeating hourly schedule, with presets you can save and share.
* **Upcoming list:** the next few events at a glance.
* **Stopwatch:** with laps, as its own panel.
* **Alarms:** weekly on any days, or once on a chosen date, with your own sound.
* **Calendar:** month, week and day views, with tags and reminders. Finished events are crossed off, not deleted.
* **Overlay notifications:** with Snooze and Dismiss.
* **Styles:** card or arc shape for each panel, animated effects or your own images, colours and fonts.
* **Layout:** a live map of all your monitors where you drag panels into place, plus layout presets.
* **Hotkeys and tray icon:** control everything without leaving the app you are using.

Your settings and data are stored in `%APPDATA%\Orbitick`. Orbitick does not collect any data or connect to the internet.

## Run from source

Requires Python 3.12 on Windows.

```
pip install pillow pystray
python orbitick.pyw
```

## Build the downloads

```
pip install pyinstaller
python build.py
```

This writes `Orbitick Setup.exe` and the portable ZIP to `release/`.

## Tests

```
python tests/run_tests.py
```

These are UI tests, so their windows appear on screen while they run. Leave the PC alone until they finish: switching to another app can minimize the test windows, and the checks that need a visible window then fail.
