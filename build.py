"""Builds release/Orbitick Setup.exe (the app packed inside a small installer) and a portable ZIP.

Run it with the build environment's Python (it has PyInstaller, Pillow and pystray):

    %LOCALAPPDATA%\\OrbitickBuild\\venv\\Scripts\\python.exe build.py

Intermediate files go to %LOCALAPPDATA%\\OrbitickBuild, outside OneDrive; only the finished
downloads land in release/.
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import APP_NAME, VERSION  # noqa: E402
from render import logo  # noqa: E402

BUILD = Path(os.environ["LOCALAPPDATA"]) / "OrbitickBuild"
RELEASE = HERE / "release"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{app}'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{app}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def pyinstaller(name, script, icon, *extra):
    version_file = BUILD / f"{name}.version.txt"
    parts = tuple(int(p) for p in VERSION.split(".")) + (0,)
    version_file.write_text(VERSION_INFO.format(v=parts, app=APP_NAME, name=name, version=VERSION), encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", name, "--icon", str(icon), "--version-file", str(version_file),
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--paths", str(HERE), *extra, str(script),
    ], check=True)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    icon = BUILD / "orbitick.ico"
    logo(256).save(icon, sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])

    # 1. The app itself, as a folder (starts faster than a single-file exe).
    pyinstaller(APP_NAME, HERE / "orbitick.pyw", icon,
                # Imported lazily or picked at runtime, so name them explicitly.
                "--hidden-import", "settings_ui", "--hidden-import", "pystray._win32")
    app_dir = BUILD / "dist" / APP_NAME

    # 2. Pack it up as the installer's payload.
    payload = BUILD / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
        for f in app_dir.rglob("*"):
            z.write(f, f.relative_to(app_dir))

    # 3. The installer, as one exe with the payload inside.
    sep = os.pathsep
    pyinstaller(f"{APP_NAME} Setup", HERE / "setup.py", icon, "--onefile",
                "--add-data", f"{payload}{sep}.", "--add-data", f"{HERE / 'installer' / 'uninstall.ps1'}{sep}.")

    RELEASE.mkdir(exist_ok=True)
    for old in RELEASE.iterdir():
        old.unlink()
    out = RELEASE / f"{APP_NAME} Setup.exe"
    shutil.copy2(BUILD / "dist" / f"{APP_NAME} Setup.exe", out)

    # 4. The portable version: the same app folder, run from wherever it's unzipped.
    portable = RELEASE / f"{APP_NAME} {VERSION} Portable.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as z:
        for f in app_dir.rglob("*"):
            z.write(f, Path(APP_NAME) / f.relative_to(app_dir))
    for f in (out, portable):
        print(f"Built {f} ({f.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
