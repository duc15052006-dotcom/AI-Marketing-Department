"""Conservative plain-text clipboard lease, never overwriting concurrent copies."""
from desktop.controller import DesktopError


class TextClipboardLease:
    def __init__(self, api, text, hwnd):
        self.api, self.original, self.sequence = api, None, None
        api.OpenClipboard(hwnd)
        try:
            formats, current = [], 0
            while True:
                current = api.EnumClipboardFormats(current)
                if current == 0: break
                formats.append(current)
            # Only plain Unicode text and its Windows-synthesized representations.
            # HTML, images, files, custom/delayed objects are left untouched.
            if any(f not in (1, 7, 13, 16) for f in formats) or (formats and 13 not in formats):
                raise DesktopError('DESKTOP_CLIPBOARD_FORMAT_UNSUPPORTED')
            if formats: self.original = api.GetClipboardData(13)
            api.EmptyClipboard()
            try:
                api.SetClipboardText(text, 13)
            except Exception:
                if self.original is not None: api.SetClipboardText(self.original, 13)
                raise
            self.sequence = api.GetClipboardSequenceNumber()
            if not self.sequence:
                api.EmptyClipboard()
                if self.original is not None: api.SetClipboardText(self.original, 13)
                raise DesktopError('DESKTOP_CLIPBOARD_SEQUENCE_UNAVAILABLE')
        finally:
            api.CloseClipboard()

    def restore(self, hwnd):
        self.api.OpenClipboard(hwnd)
        try:
            if self.api.GetClipboardSequenceNumber() != self.sequence:
                return False
            self.api.EmptyClipboard()
            if self.original is not None:
                self.api.SetClipboardText(self.original, 13)
            return True
        finally:
            self.api.CloseClipboard()
