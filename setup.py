"""Orbitick Setup: installs the app for the current Windows user (no admin rights needed).

- program files in %LOCALAPPDATA%\\Programs\\Orbitick
- Start menu (and optionally desktop) shortcut
- an entry in Settings > Apps > Installed apps whose Uninstall runs uninstall.ps1

Built into "Orbitick Setup.exe" by build.py, with the app itself bundled as payload.zip.
Run with --silent to install with the defaults and no window.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import winreg
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import APP_NAME, VERSION  # noqa: E402

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
TARGET = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME
EXE = TARGET / f"{APP_NAME}.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Orbitick"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PRESET_EXTS, PRESET_TYPE = (".orbitickpreset", ".cadencepreset"), "Orbitick.Preset"  # double-click to import
# The app was called Cadence up to 1.7; installing Orbitick replaces that install.
OLD_NAME = "Cadence"
OLD_TARGET = TARGET.with_name(OLD_NAME)
OLD_UNINSTALL_KEY = UNINSTALL_KEY.replace(APP_NAME, OLD_NAME)
NO_WINDOW = 0x08000000

SHORTCUTS = r"""
$shell = New-Object -ComObject WScript.Shell
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Orbitick.lnk"
$places = @((Join-Path ([Environment]::GetFolderPath("Programs")) "Orbitick.lnk"))
foreach ($old in @("Programs", "Desktop")) { Remove-Item (Join-Path ([Environment]::GetFolderPath($old)) "Cadence.lnk") -ErrorAction SilentlyContinue }
if ($env:BT_DESKTOP -eq "1") { $places += $desktop } else { Remove-Item $desktop -ErrorAction SilentlyContinue }
foreach ($path in $places) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $env:BT_EXE
    $link.WorkingDirectory = $env:BT_DIR
    $link.IconLocation = "$env:BT_EXE,0"
    $link.Description = "Overlay timer for things that repeat on a schedule"
    $link.Save()
}
"""


def installed_version(key_path=UNINSTALL_KEY):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, "DisplayVersion")[0]
    except OSError:
        return None


def old_starts_with_windows():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, OLD_NAME)
            return True
    except OSError:
        return False


def delete_key(path):
    """Delete a registry key and everything under it, if it's there."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_key(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def remove_old_install():
    """Take away Cadence (the old name): its program files, entry in Installed apps, startup entry and file type.
    Its data folder is moved over by the app itself on first start."""
    subprocess.run(["taskkill", "/f", "/im", f"{OLD_NAME}.exe"], capture_output=True, creationflags=NO_WINDOW)
    for attempt in range(20):
        try:
            if (OLD_TARGET / f"{OLD_NAME}.exe").exists():
                shutil.rmtree(OLD_TARGET)
            break
        except OSError:
            time.sleep(0.25)
    delete_key(OLD_UNINSTALL_KEY)
    delete_key(r"Software\Classes\Cadence.Preset")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, OLD_NAME)
    except OSError:
        pass


def close_running_app():
    subprocess.run(["taskkill", "/f", "/im", f"{APP_NAME}.exe"], capture_output=True, creationflags=NO_WINDOW)


def replace_files():
    for attempt in range(20):  # the old exe can take a moment to let go of its files
        try:
            if TARGET.exists():
                shutil.rmtree(TARGET)
            break
        except OSError:
            time.sleep(0.25)
    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE / "payload.zip") as payload:
        payload.extractall(TARGET)
    shutil.copy2(BUNDLE / "uninstall.ps1", TARGET / "uninstall.ps1")


def make_shortcuts(desktop):
    env = dict(os.environ, BT_EXE=str(EXE), BT_DIR=str(TARGET), BT_DESKTOP="1" if desktop else "0")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SHORTCUTS],
                   env=env, check=True, capture_output=True, creationflags=NO_WINDOW)


def register():
    size_kb = sum(f.stat().st_size for f in TARGET.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in {
            "DisplayName": APP_NAME,
            "DisplayVersion": VERSION,
            "Publisher": APP_NAME,
            "DisplayIcon": f"{EXE},0",
            "InstallLocation": str(TARGET),
            "UninstallString": ("powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden "
                                f'-File "{TARGET / "uninstall.ps1"}"'),
        }.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in {"NoModify": 1, "NoRepair": 1, "EstimatedSize": size_kb}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    register_preset_files()


def register_preset_files():
    classes = r"Software\Classes"
    for path, value in {
        **{rf"{classes}\{ext}": PRESET_TYPE for ext in PRESET_EXTS},
        rf"{classes}\{PRESET_TYPE}": f"{APP_NAME} preset",
        rf"{classes}\{PRESET_TYPE}\DefaultIcon": f'"{EXE}",0',
        rf"{classes}\{PRESET_TYPE}\shell\open\command": f'"{EXE}" "%1"',
    }.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED: refresh file icons


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{EXE}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def install(desktop=True, startup=False, progress=lambda text: None):
    progress(f"Closing {APP_NAME} if it's running…")
    close_running_app()
    remove_old_install()
    progress("Copying files…")
    replace_files()
    progress("Adding shortcuts…")
    make_shortcuts(desktop)
    progress("Registering with Windows…")
    register()
    set_startup(startup)


def launch():
    subprocess.Popen([str(EXE)], cwd=str(TARGET), creationflags=0x00000008)  # DETACHED_PROCESS


class SetupWindow:
    def __init__(self):
        import ui
        import winapi
        from PIL import ImageTk
        from render import logo
        self.ui = ui
        winapi.set_app_id("Orbitick.Setup")
        winapi.enable_dpi_awareness()
        root = self.root = tk.Tk()
        ui.init(root)
        UI, px, font = ui.UI, ui.px, ui.font
        root.title(f"{APP_NAME} Setup")
        root.configure(bg=UI["bg"])
        root.resizable(False, False)
        self.icon = ImageTk.PhotoImage(logo(64))
        root.iconphoto(True, self.icon)

        body = tk.Frame(root, bg=UI["bg"])
        body.pack(padx=px(32), pady=(px(28), px(10)), fill="x")
        head = tk.Frame(body, bg=UI["bg"])
        head.pack(fill="x")
        self.logo = ImageTk.PhotoImage(logo(px(64)))
        tk.Label(head, image=self.logo, bg=UI["bg"]).pack(side="left")
        names = tk.Frame(head, bg=UI["bg"])
        names.pack(side="left", padx=(px(14), 0))
        tk.Label(names, text=APP_NAME, bg=UI["bg"], fg=UI["text"], font=font(20, "bold", True)).pack(anchor="w")
        tk.Label(names, text=f"Version {VERSION} · overlay timer for anything on a schedule", bg=UI["bg"],
                 fg=UI["muted"], font=font(9)).pack(anchor="w")

        current, old = installed_version(), installed_version(OLD_UNINSTALL_KEY)
        if current:
            note = f"Version {current} is installed. Updating keeps your settings."
        elif old:
            note = (f"{OLD_NAME} {old} is installed. {APP_NAME} is its new name: installing replaces {OLD_NAME} and "
                    "keeps your settings, alarms, calendar and presets.")
        else:
            note = "Installs for your Windows account only. Administrator rights are not required."
        tk.Label(body, text=note, bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w", justify="left",
                 wraplength=px(440)).pack(fill="x", pady=(px(20), px(10)))

        self.options = {}
        for key, title, desc, default in [
            ("desktop", "Desktop shortcut", "A Start menu shortcut is always added.", True),
            ("startup", "Start with Windows", f"Opens {APP_NAME} when you sign in.", old_starts_with_windows()),
            ("launch", f"Launch {APP_NAME} after installation", None, True),
        ]:
            toggle = ui.Toggle(ui.setting_row(body, title, desc), default, None)
            toggle.pack()
            self.options[key] = toggle

        tk.Label(body, text=f"Location: {TARGET}", bg=UI["bg"], fg=UI["faint"], font=font(8), anchor="w",
                 justify="left", wraplength=px(440)).pack(fill="x", pady=(px(8), 0))

        footer = tk.Frame(root, bg=UI["bg"])
        footer.pack(fill="x", padx=px(32), pady=(px(10), px(26)))
        self.button = ui.Button(footer, "Update" if current or old else "Install", self.run, "primary", padx=26)
        self.button.pack(side="right")
        self.cancel = ui.Button(footer, "Cancel", root.destroy)
        self.cancel.pack(side="right", padx=(0, px(8)))
        self.status = tk.Label(footer, bg=UI["bg"], fg=UI["muted"], font=font(9), anchor="w", justify="left",
                               wraplength=px(240))
        self.status.pack(side="left", fill="x", expand=True)

        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
        winapi.style_window(root, ui.hex_rgb(UI["bg"]))
        self.done = False

    def say(self, text, error=False):
        self.status.config(text=text, fg=self.ui.UI["danger"] if error else self.ui.UI["muted"])
        self.root.update()

    def run(self):
        if self.done:
            self.root.destroy()
            return
        try:
            install(self.options["desktop"].value, self.options["startup"].value, self.say)
        except Exception as e:  # show anything that goes wrong instead of vanishing
            self.say(f"Installation failed: {e}", error=True)
            return
        self.done = True
        if self.options["launch"].value:
            launch()
        self.say(f"Installation complete. {APP_NAME} is available from the Start menu and the system tray.")
        self.button.set_text("Close")
        self.cancel.pack_forget()


if __name__ == "__main__":
    if "--silent" in sys.argv:
        install(desktop="--no-desktop" not in sys.argv, startup=old_starts_with_windows())
    else:
        SetupWindow().root.mainloop()
