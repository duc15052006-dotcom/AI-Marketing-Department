"""Windows interactive-session backend; optional dependencies loaded on opt-in."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import io
import sys

from desktop.controller import DesktopError, Window


class WindowsBackend:
    def __init__(self, hwnd: int):
        if sys.platform != 'win32':
            raise DesktopError('DESKTOP_WINDOWS_REQUIRED')
        if type(hwnd) is not int or hwnd <= 0:
            raise DesktopError('DESKTOP_WINDOW_REQUIRED')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.SetProcessDPIAware()
        import pyautogui
        self.gui = pyautogui
        self.gui.FAILSAFE = True
        self.gui.PAUSE = 0.1
        self.hwnd = hwnd
        self.bound = self._window()

    def _window(self):
        if self.user.GetForegroundWindow() != self.hwnd or not self.user.IsWindowVisible(self.hwnd) or self.user.IsIconic(self.hwnd):
            raise DesktopError('DESKTOP_TARGET_NOT_FOREGROUND')
        rect, pid = wintypes.RECT(), wintypes.DWORD()
        if not self.user.GetWindowRect(self.hwnd, ctypes.byref(rect)) or not self.user.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid)):
            raise DesktopError('DESKTOP_WINDOW_UNAVAILABLE')
        width, height = self.gui.size()
        if rect.left < 0 or rect.top < 0 or rect.right > width or rect.bottom > height:
            raise DesktopError('DESKTOP_PRIMARY_SCREEN_ONLY_RESTORE_WINDOW')
        if rect.right <= rect.left or rect.bottom <= rect.top:
            raise DesktopError('DESKTOP_WINDOW_INVALID')
        return Window(self.hwnd, pid.value, rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top)

    def window(self):
        return self._window()

    def stopped(self):
        # Esc, any held modifier, or GUI fail-safe stops the session. Do not
        # synthesize modifier releases: they may belong to the human operator.
        if self.user.GetAsyncKeyState(0x1b) & 0x8001 or any(
            self.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5b, 0x5c)
        ):
            return True
        self.gui.failSafeCheck()
        return False

    def _guard(self):
        if self.stopped() or self.window() != self.bound:
            raise DesktopError('DESKTOP_STOPPED_OR_WINDOW_CHANGED')

    def capture(self):
        self._guard()
        w = self.bound
        image = self.gui.screenshot(region=(w.left, w.top, w.width, w.height))
        self._guard()
        out = io.BytesIO()
        image.save(out, format='PNG')
        return out.getvalue()

    def _point(self, x, y):
        self._guard()
        w = self.bound
        if not w.left <= x < w.left+w.width or not w.top <= y < w.top+w.height:
            raise DesktopError('DESKTOP_POINT_OUTSIDE_WINDOW')
        target = self.user.WindowFromPoint(wintypes.POINT(x, y))
        if self.user.GetAncestor(target, 2) != self.hwnd:
            raise DesktopError('DESKTOP_TARGET_OCCLUDED')

    def click(self, x, y, duration):
        self._point(x, y)
        self.gui.moveTo(x, y, duration=duration)
        self._point(x, y)
        self.gui.click()

    def scroll(self, ticks, x, y):
        self._point(x, y)
        self.gui.moveTo(x, y, duration=0.2)
        self._point(x, y)
        # Windows defines one wheel notch as WHEEL_DELTA=120. Use SendInput
        # directly and check acceptance instead of an opaque GUI-library result.
        self._send([('mouse', ctypes.c_uint32(ticks * 120).value, 0x0800)])

    def press(self, key):
        self._guard()
        self.gui.press(key)

    def paste(self, text, guard, wait):
        from desktop.clipboard import TextClipboardLease
        import win32clipboard
        self._guard()
        lease = TextClipboardLease(win32clipboard, text, self.hwnd)
        try:
            guard()
            if win32clipboard.GetClipboardSequenceNumber() != lease.sequence:
                raise DesktopError('DESKTOP_CLIPBOARD_CHANGED_BEFORE_PASTE')
            # One checked batch avoids guard checks mistaking our own Ctrl
            # for a human-held modifier. On partial input, release owned keys.
            try:
                self._send([('virtual', 0x11, 0), ('virtual', 0x56, 0),
                            ('virtual', 0x56, 2), ('virtual', 0x11, 2)])
            except Exception:
                self.user.keybd_event(0x56, 0, 2, 0)
                self.user.keybd_event(0x11, 0, 2, 0)
                raise
            # Give the application a bounded opportunity to consume clipboard.
            # Application-level completion is still UNVERIFIED.
            wait(0.75)
        finally:
            lease.restore(self.hwnd)

    def write_char(self, char):
        self._guard()
        # KEYEVENTF_UNICODE supports Vietnamese without changing the clipboard.
        data = char.encode('utf-16-le')
        events = []
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i+2], 'little')
            events.extend(('keyboard', unit, flags) for flags in (4, 6))
        self._send(events)

    def _send(self, events):
        self._guard()
        class Mouse(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('data', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        class Keyboard(ctypes.Structure):
            _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        class Payload(ctypes.Union):
            _fields_ = [('mouse', Mouse), ('keyboard', Keyboard)]
        class Input(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('payload', Payload)]
        native = [
            Input(0, Payload(mouse=Mouse(0, 0, value, flags, 0, 0))) if kind == 'mouse'
            else Input(1, Payload(keyboard=Keyboard(value if kind == 'virtual' else 0,
                                                     0 if kind == 'virtual' else value, flags, 0, 0)))
            for kind, value, flags in events
        ]
        batch = (Input * len(native))(*native)
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        if self.user.SendInput(len(native), batch, ctypes.sizeof(Input)) != len(native):
            raise DesktopError('DESKTOP_NATIVE_INPUT_PARTIAL')
