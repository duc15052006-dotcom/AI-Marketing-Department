"""Bounded, observation-driven desktop session, independent of GUI libraries."""
from __future__ import annotations

import base64
import hashlib
import math
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Protocol


class DesktopError(RuntimeError):
    pass


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    left: int
    top: int
    width: int
    height: int


class Backend(Protocol):
    def window(self) -> Window: ...
    def stopped(self) -> bool: ...
    def capture(self) -> bytes: ...
    def click(self, x: int, y: int, duration: float) -> None: ...
    def write_char(self, char: str) -> None: ...
    def press(self, key: str) -> None: ...
    def scroll(self, ticks: int, x: int, y: int) -> None: ...


class DesktopSession:
    """A trusted host grants one window, lifetime and operation budget.

    Observation IDs are one-use, short-lived and invalidated before dispatch.
    A receipt records dispatched input, never claims a post was published.
    """
    def __init__(self, backend: Backend, *, max_actions: int = 20,
                 lifetime: float = 300, clock=time.monotonic,
                 sleep=time.sleep, rng=None):
        if type(max_actions) is not int or not 1 <= max_actions <= 200:
            raise ValueError('max_actions must be 1..200')
        if not isinstance(lifetime, (int, float)) or not math.isfinite(lifetime) or not 1 <= lifetime <= 3600:
            raise ValueError('lifetime must be 1..3600 seconds')
        self.backend, self.clock, self.sleep = backend, clock, sleep
        self.rng = rng or secrets.SystemRandom()
        self.window = backend.window()
        self.deadline = clock() + lifetime
        self.remaining = max_actions
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._observation = None
        self._call_deadline = None

    def stop(self):
        self._stop.set()

    def _guard(self):
        if self._stop.is_set() or self.backend.stopped():
            self.stop()
            raise DesktopError('DESKTOP_STOPPED')
        if self._call_deadline is not None and self.clock() >= self._call_deadline:
            raise DesktopError('DESKTOP_OPERATION_TIMEOUT')
        if self.clock() >= self.deadline:
            raise DesktopError('DESKTOP_SESSION_EXPIRED')
        if self.backend.window() != self.window:
            raise DesktopError('DESKTOP_WINDOW_CHANGED')

    def _wait(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end:
            self._guard()
            self.sleep(min(0.05, end - self.clock()))
        self._guard()

    def _capture(self):
        self._guard()
        png = self.backend.capture()
        self._guard()
        return png

    def observe(self):
        with self._lock:
            self._call_deadline = self.clock() + 30
            self._observation = None
            png = self._capture()
            token = secrets.token_urlsafe(24)
            digest = hashlib.sha256(png).hexdigest()
            self._observation = (token, self.clock(), digest)
            return {'observation_id': token, 'png_base64': base64.b64encode(png).decode('ascii'),
                    'sha256': digest, 'width': self.window.width, 'height': self.window.height,
                    'coordinate_space': 'window-relative', 'expires_in_seconds': 15}

    def _rect(self, value):
        if not isinstance(value, (list, tuple)) or len(value) != 4 or any(type(v) is not int for v in value):
            raise DesktopError('DESKTOP_RECT_INVALID')
        x, y, width, height = value
        if x < 0 or y < 0 or width < 7 or height < 7 or x + width > self.window.width or y + height > self.window.height:
            raise DesktopError('DESKTOP_RECT_OUTSIDE_WINDOW_OR_TOO_SMALL')
        # Inset prevents edge clicks. Repeated coordinates remain possible; no
        # coordinate blacklist that would eventually force clicks outside a button.
        inset = max(2, min(8, min(width, height) // 5))
        return (self.window.left + self.rng.randint(x + inset, x + width - inset - 1),
                self.window.top + self.rng.randint(y + inset, y + height - inset - 1))

    def act(self, action: dict, *, timeout_seconds=30.0):
        with self._lock:
            if type(timeout_seconds) not in (float, int) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
                raise DesktopError('DESKTOP_TIMEOUT_INVALID')
            self._call_deadline = self.clock() + timeout_seconds
            self._guard()
            if self.remaining <= 0:
                raise DesktopError('DESKTOP_ACTION_BUDGET_EXHAUSTED')
            if not isinstance(action, dict):
                raise DesktopError('DESKTOP_ACTION_INVALID')
            kind = action.get('kind')
            fields = {'click': {'rect'}, 'type': {'text'}, 'press': {'key'}, 'scroll': {'rect', 'ticks'}}
            if kind not in fields or set(action) != fields[kind] | {'kind', 'observation_id'}:
                raise DesktopError('DESKTOP_ACTION_INVALID')
            point = self._rect(action['rect']) if kind in ('click', 'scroll') else None
            if kind == 'type' and (not isinstance(action['text'], str) or not 1 <= len(action['text']) <= 500 or
                                   any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f or 0xd800 <= ord(c) <= 0xdfff for c in action['text'])):
                raise DesktopError('DESKTOP_TEXT_INVALID')
            if kind == 'press' and action['key'] not in ('enter', 'tab', 'backspace', 'left', 'right', 'up', 'down', 'delete'):
                raise DesktopError('DESKTOP_KEY_NOT_ALLOWED')
            if kind == 'scroll' and (type(action['ticks']) is not int or not 1 <= abs(action['ticks']) <= 5):
                raise DesktopError('DESKTOP_SCROLL_INVALID')
            observation, self._observation = self._observation, None
            if not observation or action['observation_id'] != observation[0]:
                raise DesktopError('DESKTOP_OBSERVATION_INVALID')
            self._wait(self.rng.uniform(0.35, 1.4))
            if self.clock() - observation[1] > 15:
                raise DesktopError('DESKTOP_OBSERVATION_EXPIRED')
            if hashlib.sha256(self._capture()).hexdigest() != observation[2]:
                raise DesktopError('DESKTOP_SCREEN_CHANGED_REOBSERVE')
            self.remaining -= 1
            # From here failures have ambiguous/partial effects: never retry.
            try:
                if kind == 'click':
                    self.backend.click(*point, self.rng.uniform(0.15, 0.45))
                elif kind == 'type':
                    for char in action['text']:
                        self._guard()
                        self.backend.write_char(char)
                        self._wait(self.rng.uniform(0.025, 0.09))
                elif kind == 'press':
                    self.backend.press(action['key'])
                else:
                    self.backend.scroll(action['ticks'], *point)
                self._wait(self.rng.uniform(0.25, 0.8))
                after = self._capture()
            except Exception:
                self.stop()
                raise DesktopError('DESKTOP_OUTCOME_UNCERTAIN_STOPPED') from None
            return {'input_dispatched': True, 'semantic_success': 'UNVERIFIED',
                    'remaining_actions': self.remaining,
                    'after_sha256': hashlib.sha256(after).hexdigest(),
                    'after_png_base64': base64.b64encode(after).decode('ascii')}
