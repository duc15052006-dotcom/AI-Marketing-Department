"""Opt-in native Windows smoke; touches ONLY a Tk window owned by this test.

Normal offline discovery skips this. The dedicated CI job explicitly enables it.
"""
import os
import sys
import time
import unittest


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('RUN_DESKTOP_NATIVE_SMOKE') == '1',
                     'Native desktop smoke requires explicit Windows opt-in')
class WindowsDesktopSmoke(unittest.TestCase):
    def test_owned_window_click_unicode_backspace_scroll_and_stop(self):
        import ctypes
        import tkinter as tk
        from desktop.controller import DesktopError, DesktopSession
        from desktop.windows import WindowsBackend

        root = tk.Tk()
        session = None
        try:
            root.title('AI Marketing Department isolated desktop smoke')
            root.overrideredirect(True)
            root.geometry('600x360+100+100')
            root.attributes('-topmost', True)
            entry = tk.Entry(root, font=('Arial', 18), insertontime=0)
            entry.place(x=30, y=50, width=500, height=50)
            clicked = []
            button = tk.Button(root, text='Local test button', command=lambda: clicked.append(True))
            button.place(x=30, y=140, width=180, height=50)
            wheel = []
            scroll_area = tk.Text(root, wrap='none', insertontime=0)
            scroll_area.place(x=30, y=220, width=500, height=100)
            scroll_area.insert('1.0', '\n'.join(f'Row {i}' for i in range(80)))
            scroll_area.yview_moveto(0)
            scroll_area.bind('<MouseWheel>', lambda event: wheel.append(event.delta))
            root.update()
            root.focus_force()
            root.update()
            user = ctypes.WinDLL('user32', use_last_error=True)
            from ctypes import wintypes
            user.GetForegroundWindow.restype = wintypes.HWND
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            hwnd = user.GetForegroundWindow()
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            self.assertEqual(pid.value, os.getpid(), 'Never operate a window outside the test process')
            # Fixture setup only: keep initial cursor away from fail-safe corners.
            user.SetCursorPos(720, 500)
            user.GetAsyncKeyState(0x1b)  # clear historical Esc edge from runner setup
            backend = WindowsBackend(hwnd)
            def pump(seconds):
                root.update()
                time.sleep(seconds)
                root.update()
            session = DesktopSession(backend, sleep=pump, max_actions=10)
            def act(kind, **payload):
                root.update()
                observation = session.observe()
                result = session.act({'kind': kind, 'observation_id': observation['observation_id'], **payload})
                root.update()
                self.assertEqual(result['semantic_success'], 'UNVERIFIED')
                return result
            act('click', rect=[35, 145, 160, 40])
            self.assertEqual(clicked, [True])
            act('click', rect=[40, 60, 460, 30])
            text = 'Xin chào Việt Nam'
            act('type', text=text)
            self.assertEqual(entry.get(), text)
            act('press', key='backspace')
            self.assertEqual(entry.get(), text[:-1])
            import win32clipboard as clipboard
            clipboard.OpenClipboard(hwnd)
            try:
                clipboard.EmptyClipboard()
                clipboard.SetClipboardText('original clipboard', 13)
            finally:
                clipboard.CloseClipboard()
            long_text = ' Nội dung dài tiếng Việt.' * 30
            act('paste', text=long_text)
            self.assertEqual(entry.get(), text[:-1] + long_text)
            clipboard.OpenClipboard(hwnd)
            try:
                self.assertEqual(clipboard.GetClipboardData(13), 'original clipboard')
            finally:
                clipboard.CloseClipboard()
            act('click', rect=[40, 240, 200, 40])
            before_scroll = scroll_area.yview()
            act('scroll', rect=[40, 240, 200, 40], ticks=-2)
            self.assertTrue(wheel)
            self.assertGreater(scroll_area.yview()[0], before_scroll[0])
            backend.gui.keyDown('esc')
            try:
                with self.assertRaisesRegex(DesktopError, 'STOPPED'):
                    session.observe()
            finally:
                backend.gui.keyUp('esc')
            print('Native owned-window smoke: click, Unicode, key, scroll, Esc verified.')
        finally:
            if session is not None:
                session.stop()
            root.destroy()


if __name__ == '__main__':
    unittest.main()
