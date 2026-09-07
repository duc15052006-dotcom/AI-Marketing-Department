"""Conservative plain-text clipboard lease, never overwriting concurrent copies."""
import secrets
from desktop.controller import DesktopError


class TextClipboardLease:
    def __init__(self, api, text, hwnd):
        self.api, self.original, self.sequence = api, None, None
        self.text = text
        self.marker = secrets.token_hex(32).encode('ascii')
        self.marker_format = api.RegisterClipboardFormat('AI-Marketing-Department.DesktopLease.v1')
        api.OpenClipboard(hwnd)
        try:
            formats, current = [], 0
            while True:
                current = api.EnumClipboardFormats(current)
                if current == 0: break
                formats.append(current)
            # Preserve rich/image/file/custom clipboards by refusing modification.
            if any(f not in (1, 7, 13, 16) for f in formats) or (formats and 13 not in formats):
                raise DesktopError('DESKTOP_CLIPBOARD_FORMAT_UNSUPPORTED')
            if formats: self.original = api.GetClipboardData(13)
            api.EmptyClipboard()
            try:
                api.SetClipboardText(text, 13)
                api.SetClipboardData(self.marker_format, self.marker)
            except Exception:
                api.EmptyClipboard()
                if self.original is not None: api.SetClipboardText(self.original, 13)
                raise
        finally:
            api.CloseClipboard()
        # Windows may advance the sequence when closing a write transaction.
        # Re-open and authenticate our random marker + exact text BEFORE taking
        # the post-close sequence; a copy between close/open is never adopted.
        api.OpenClipboard(hwnd)
        try:
            if not self._owns_locked():
                raise DesktopError('DESKTOP_CLIPBOARD_CHANGED_BEFORE_PASTE')
            self.sequence = api.GetClipboardSequenceNumber()
            if not self.sequence:
                api.EmptyClipboard()
                if self.original is not None: api.SetClipboardText(self.original, 13)
                raise DesktopError('DESKTOP_CLIPBOARD_SEQUENCE_UNAVAILABLE')
        finally:
            api.CloseClipboard()

    def _owns_locked(self):
        try:
            marker = self.api.GetClipboardData(self.marker_format)
            return bytes(marker).rstrip(b'\0') == self.marker and self.api.GetClipboardData(13) == self.text
        except Exception:
            return False

    def restore(self, hwnd):
        self.api.OpenClipboard(hwnd)
        try:
            if self.api.GetClipboardSequenceNumber() != self.sequence or not self._owns_locked():
                return False
            self.api.EmptyClipboard()
            if self.original is not None:
                self.api.SetClipboardText(self.original, 13)
            return True
        finally:
            self.api.CloseClipboard()
