"""Thin ctypes wrappers for the Windows bits Tk can't do on its own.

- LayeredWindow: per-pixel transparent window contents (smooth circles, soft shadows).
- Hotkeys: system-wide hotkeys that work while another app has focus.
- font_bytes / add_font_file: read any installed font (including Adobe Fonts) for Pillow.
"""
import ctypes
import os
import queue
import sys
import threading

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_NOREPEAT = 0x4000
FR_PRIVATE = 0x10
TTCF_TABLE = 0x66637474  # 'ttcf': the whole font collection

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    vp = ctypes.c_void_p

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    def _proto(fn, restype, *argtypes):
        fn.restype, fn.argtypes = restype, list(argtypes)

    _proto(user32.GetAncestor, vp, vp, ctypes.c_uint)
    _proto(user32.GetWindowLongPtrW, ctypes.c_ssize_t, vp, ctypes.c_int)
    _proto(user32.SetWindowLongPtrW, ctypes.c_ssize_t, vp, ctypes.c_int, ctypes.c_ssize_t)
    _proto(user32.GetDC, vp, vp)
    _proto(user32.ReleaseDC, ctypes.c_int, vp, vp)
    _proto(user32.UpdateLayeredWindow, wintypes.BOOL, vp, vp, ctypes.POINTER(wintypes.POINT),
           ctypes.POINTER(wintypes.SIZE), vp, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
           ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD)
    _proto(user32.WindowFromPoint, vp, wintypes.POINT)
    _proto(user32.RegisterHotKey, wintypes.BOOL, vp, ctypes.c_int, ctypes.c_uint, ctypes.c_uint)
    _proto(user32.UnregisterHotKey, wintypes.BOOL, vp, ctypes.c_int)
    _proto(user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), vp, ctypes.c_uint, ctypes.c_uint)
    _proto(user32.PostThreadMessageW, wintypes.BOOL, wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
    _proto(gdi32.CreateCompatibleDC, vp, vp)
    _proto(gdi32.CreateDIBSection, vp, vp, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(vp), vp, wintypes.DWORD)
    _proto(gdi32.SelectObject, vp, vp, vp)
    _proto(gdi32.DeleteObject, wintypes.BOOL, vp)
    _proto(gdi32.DeleteDC, wintypes.BOOL, vp)
    _proto(gdi32.CreateFontW, vp, *([ctypes.c_int] * 5), *([wintypes.DWORD] * 8), ctypes.c_wchar_p)
    _proto(gdi32.GetFontData, wintypes.DWORD, vp, wintypes.DWORD, wintypes.DWORD, vp, wintypes.DWORD)
    _proto(gdi32.AddFontResourceExW, ctypes.c_int, ctypes.c_wchar_p, wintypes.DWORD, vp)


class SingleInstance:
    """One Orbitick at a time. Launching it again pokes the running one instead."""

    def __init__(self, name=None):
        # ORBITICK_INSTANCE lets a test copy run beside the real one without poking it.
        name = name or os.environ.get("ORBITICK_INSTANCE") or "OrbitickOverlayTimer"
        self.first = True
        if not IS_WINDOWS:
            return
        kernel32.CreateMutexW.restype = kernel32.CreateEventW.restype = vp
        self.mutex = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        self.first = kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        self.event = kernel32.CreateEventW(None, False, False, f"Local\\{name}.Show")  # auto-reset

    def poke_existing(self):
        if IS_WINDOWS:
            kernel32.SetEvent(vp(self.event))

    def listen(self, callback):
        """Call `callback` (from a background thread) each time another launch pokes us."""
        if not IS_WINDOWS:
            return

        def wait():
            while kernel32.WaitForSingleObject(vp(self.event), 0xFFFFFFFF) == 0:
                callback()
        threading.Thread(target=wait, daemon=True).start()


def set_app_id(app_id):
    """Group our windows under the app's own taskbar identity rather than Python's."""
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except (AttributeError, OSError):
            pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Orbitick"


def launch_command():
    """How Windows should start this app: the installed exe, or pythonw + script when run from source."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    from pathlib import Path
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(sys.argv[0]).resolve()}"'


def starts_with_windows():
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_start_with_windows(enabled):
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def enable_dpi_awareness():
    """Render crisply on scaled displays instead of being bitmap-stretched by Windows."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def root_hwnd(widget):
    widget.update_idletasks()
    return user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT


def set_ex_style(hwnd, add=0, remove=0):
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (style | add) & ~remove)


def monitors():
    """[(left, top, right, bottom)] for every display, in screen pixels (secondary screens can be negative)."""
    if not IS_WINDOWS:
        return []
    found = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, vp, vp, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def collect(monitor, dc, rect, data):
        r = rect.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return 1
    user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    return found


def window_from_point(x, y):
    return user32.WindowFromPoint(wintypes.POINT(x, y))


def style_window(widget, caption_rgb=None, dark=True):
    """Dark (or light) title bar, and on Windows 11 a matching caption colour and rounded corners."""
    if not IS_WINDOWS:
        return
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = root_hwnd(widget)
        dwm.DwmSetWindowAttribute(vp(hwnd), 20, ctypes.byref(ctypes.c_int(1 if dark else 0)), 4)  # dark mode
        dwm.DwmSetWindowAttribute(vp(hwnd), 33, ctypes.byref(ctypes.c_int(2)), 4)  # round corners
        if caption_rgb:
            r, g, b = caption_rgb
            dwm.DwmSetWindowAttribute(vp(hwnd), 35, ctypes.byref(ctypes.c_int(r | g << 8 | b << 16)), 4)
    except (AttributeError, OSError):
        pass


class LayeredWindow:
    """Shows a Pillow RGBA image as the whole window, with per-pixel alpha.

    Fully transparent pixels are also click-through, so a round overlay only catches
    clicks on the circle itself.
    """

    def __init__(self, widget):
        self.hwnd = root_hwnd(widget)
        set_ex_style(self.hwnd, add=WS_EX_LAYERED | WS_EX_NOACTIVATE)

    def set_click_through(self, enabled):
        if enabled:
            set_ex_style(self.hwnd, add=WS_EX_TRANSPARENT)
        else:
            set_ex_style(self.hwnd, remove=WS_EX_TRANSPARENT)

    def show(self, image, opacity=1.0, pos=None):
        """Draw `image` as the window. Passing `pos` moves it in the same call, so a size change
        and a move can't be applied separately (and one of them lost)."""
        w, h = image.size
        data = image.tobytes("raw", "BGRa")  # premultiplied BGRA, as UpdateLayeredWindow wants
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bits = vp()
        bitmap = gdi32.CreateDIBSection(mem, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(mem, bitmap)
            blend = BLENDFUNCTION(0, 0, max(0, min(255, round(opacity * 255))), 1)  # AC_SRC_ALPHA
            dest = ctypes.byref(wintypes.POINT(*pos)) if pos else None
            args = (self.hwnd, screen, dest, ctypes.byref(wintypes.SIZE(w, h)), mem,
                    ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)
            if not user32.UpdateLayeredWindow(*args):
                # Showing a hidden Tk window switches it to "constant alpha" layering, after which
                # Windows refuses per-pixel updates. Dropping and re-adding WS_EX_LAYERED resets that.
                set_ex_style(self.hwnd, remove=WS_EX_LAYERED)
                set_ex_style(self.hwnd, add=WS_EX_LAYERED)
                user32.UpdateLayeredWindow(*args)
            gdi32.SelectObject(mem, old)
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)


def font_bytes(family, bold=False):
    """The raw font file Windows uses for `family`, as (bytes, is_collection), or None.

    Going through GDI means anything Windows can draw works, including fonts activated
    from Adobe Creative Cloud and private font files added with add_font_file.
    """
    if not IS_WINDOWS:
        return None
    dc = gdi32.CreateCompatibleDC(None)
    font = gdi32.CreateFontW(-64, 0, 0, 0, 700 if bold else 400, 0, 0, 0, 1, 0, 0, 4, 0, family)
    old = gdi32.SelectObject(dc, font)
    try:
        for table in (TTCF_TABLE, 0):
            size = gdi32.GetFontData(dc, table, 0, None, 0)
            if size and size != 0xFFFFFFFF:
                buf = ctypes.create_string_buffer(size)
                gdi32.GetFontData(dc, table, 0, buf, size)
                return buf.raw, table == TTCF_TABLE
        return None
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(font)
        gdi32.DeleteDC(dc)


def add_font_file(path):
    """Make a .ttf/.otf usable by this app only (nothing is installed system-wide)."""
    return IS_WINDOWS and gdi32.AddFontResourceExW(str(path), FR_PRIVATE, None) > 0


class Hotkeys:
    """Registers system-wide hotkeys on a background thread; fired names land in `self.fired`."""

    def __init__(self, parse):
        self.parse = parse
        self.fired = queue.Queue()
        self.failed = []
        self.thread = None
        self.thread_id = None

    def start(self, bindings, labels):
        self.stop()
        if not IS_WINDOWS:
            return
        items = [(name, text) for name, text in bindings.items() if text.strip()]
        ready = threading.Event()
        self.failed = []

        def run():
            self.thread_id = kernel32.GetCurrentThreadId()
            ids = []
            for i, (name, text) in enumerate(items, 1):
                combo = self.parse(text)
                if combo and user32.RegisterHotKey(None, i, combo[0] | MOD_NOREPEAT, combo[1]):
                    ids.append(i)
                else:
                    self.failed.append(f"{labels[name]} ({text})")
            ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.fired.put(items[msg.wParam - 1][0])
            for i in ids:
                user32.UnregisterHotKey(None, i)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(2)

    def stop(self):
        if self.thread and self.thread.is_alive():
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            self.thread.join(2)
        self.thread = None
