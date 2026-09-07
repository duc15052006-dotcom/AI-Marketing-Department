"""Opt-in window-scoped autonomy with local supervision, not a semantic sandbox."""
from __future__ import annotations
import base64
import copy
import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from desktop.controller import DesktopError, DesktopSession, Window
from desktop.vision import validate_proposal


@dataclass(frozen=True)
class TaskGrant:
    """Constructed by the trusted host after user consent, never from model output.

    A window grant permits input throughout that window, including consequential
    buttons. Goal text is guidance, NOT enforcement of domain/account/spend scope.
    """
    goal: str
    window: Window
    max_steps: int = 10
    allowed_kinds: tuple = ('click', 'type', 'paste', 'press', 'scroll')

    def __post_init__(self):
        if not isinstance(self.goal, str) or not 1 <= len(self.goal.strip()) <= 8000:
            raise ValueError('Invalid goal')
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 50:
            raise ValueError('Invalid step budget')
        if type(self.allowed_kinds) is not tuple or not self.allowed_kinds or any(
            k not in ('click', 'type', 'paste', 'press', 'scroll') for k in self.allowed_kinds
        ): raise ValueError('Invalid action grant')


class LiveSession(DesktopSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paused = threading.Event()
        self.generation = 0
        self._authorized_generation = None

    def pause(self):
        self.paused.set()
        self.generation += 1

    def resume(self):
        # Never clears stop or extends lifetime. Pending plans stay invalidated.
        self.paused.clear()

    def _guard(self):
        if self._stop.is_set(): raise DesktopError('DESKTOP_STOPPED')
        if self.paused.is_set(): raise DesktopError('DESKTOP_PAUSED')
        if self._authorized_generation is not None and self._authorized_generation != self.generation:
            raise DesktopError('DESKTOP_PAUSED')
        super()._guard()

    def act(self, action, *, generation=None, timeout_seconds=30.0):
        self._authorized_generation = self.generation if generation is None else generation
        try:
            return super().act(action, timeout_seconds=timeout_seconds)
        finally:
            self._authorized_generation = None

    def checkpoint(self):
        while self.paused.is_set():
            if self._stop.wait(0.05): raise DesktopError('DESKTOP_STOPPED')
            if self.clock() >= self.deadline: raise DesktopError('DESKTOP_SESSION_EXPIRED')
        if self._stop.is_set(): raise DesktopError('DESKTOP_STOPPED')

    def preview(self):
        """Read-only frame; never issues/replaces an action observation token.

        Skip busy native input rather than race clipboard/modifier guards. The
        viewer must mark the last frame stale while input owns the backend.
        """
        if not self._lock.acquire(blocking=False): return None
        try:
            self._call_deadline = self.clock() + 30
            png = self._capture()
            return {'png_base64': base64.b64encode(png).decode('ascii'),
                    'sha256': hashlib.sha256(png).hexdigest(),
                    'captured_at': time.monotonic(),
                    'width': self.window.width, 'height': self.window.height}
        finally:
            self._lock.release()


class LiveTask:
    """One bounded task; no per-click approval and no changes to gateway policy.

    Optional verifier is trusted host code (e.g. structured application readback).
    Model completion alone remains unverified. Evidence/events are bounded and
    memory-only; the host chooses whether and where to persist them.
    """
    def __init__(self, session, planner, grant, *, verifier=None, max_replans=5):
        if not isinstance(grant, TaskGrant) or grant.window != session.window:
            raise ValueError('Grant does not match bound window')
        if type(max_replans) is not int or not 0 <= max_replans <= 10:
            raise ValueError('Invalid replan budget')
        if verifier is not None and not callable(verifier): raise ValueError('Invalid verifier')
        self.session, self.planner, self.grant = session, planner, grant
        self.verifier, self.max_replans = verifier, max_replans
        self._events = deque(maxlen=200)
        self._event_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._used = False
        self.last_observation = None

    def emit(self, status, **data):
        with self._event_lock:
            self._events.append({'status': status, 'time': time.monotonic(), **copy.deepcopy(data)})

    def events(self):
        with self._event_lock: return copy.deepcopy(list(self._events))

    def run(self):
        with self._run_lock:
            if self._used: raise DesktopError('LIVE_TASK_ALREADY_USED')
            self._used = True
        steps, replans, previous = 0, 0, None
        try:
            while steps < self.grant.max_steps and replans <= self.max_replans:
                self.session.checkpoint()
                generation = self.session.generation
                before = self.session.observe()
                started = time.monotonic()
                self.emit('PLANNING', steps=steps)
                proposal = validate_proposal(self.planner.propose(
                    self.grant.goal, copy.deepcopy(before), copy.deepcopy(previous)))
                self.session.checkpoint()
                fresh = self.session.observe()
                self.last_observation = {**fresh, 'captured_at': time.monotonic()}
                if generation != self.session.generation or fresh['sha256'] != before['sha256']:
                    replans += 1
                    self.emit('REPLANNING', reason='View or supervision state changed')
                    continue
                self.emit('PROPOSED', proposal=proposal, planning_seconds=time.monotonic()-started)
                if proposal['status'] == 'blocked':
                    return self.finish('BLOCKED', steps)
                if proposal['status'] == 'done':
                    verification = self.verifier(self.grant.goal, copy.deepcopy(fresh)) if self.verifier else None
                    self.session.checkpoint()
                    final_view = self.session.observe()
                    verified = (generation == self.session.generation and final_view['sha256'] == fresh['sha256']
                                and isinstance(verification, dict) and verification.get('verified') is True
                                and isinstance(verification.get('evidence'), str)
                                and 0 < len(verification['evidence']) <= 8000)
                    if verified: self.emit('VERIFICATION', evidence=verification['evidence'])
                    return self.finish('HOST_VERIFIED' if verified else 'MODEL_REPORTED_COMPLETE_UNVERIFIED', steps)
                if proposal['action']['kind'] not in self.grant.allowed_kinds:
                    return self.finish('OUTSIDE_GRANT', steps)
                self.session.checkpoint()
                if generation != self.session.generation:
                    replans += 1
                    continue
                self.emit('ACTING', action=proposal['action'])
                try:
                    receipt = self.session.act({**proposal['action'], 'observation_id': fresh['observation_id']}, generation=generation)
                except DesktopError as exc:
                    if str(exc) in ('DESKTOP_PAUSED', 'DESKTOP_SCREEN_CHANGED_REOBSERVE', 'DESKTOP_OBSERVATION_EXPIRED'):
                        replans += 1
                        continue
                    raise
                steps += 1
                self.last_observation = {'png_base64': receipt['after_png_base64'],
                                         'sha256': receipt['after_sha256'], 'captured_at': time.monotonic()}
                self.emit('INPUT_DISPATCHED_UNVERIFIED', steps=steps, before_sha256=fresh['sha256'],
                          after_sha256=receipt['after_sha256'])
                previous = {'action': proposal['action'], 'expected': proposal['expected'],
                            'input_dispatched': True, 'semantic_success': 'UNVERIFIED'}
            return self.finish('STEP_LIMIT' if steps >= self.grant.max_steps else 'REPLAN_LIMIT', steps)
        except Exception:
            self.emit('STOPPED_OR_ERROR', steps=steps)
            raise
        finally:
            self.session.stop()

    def finish(self, status, steps):
        self.emit(status, steps=steps)
        return {'status': status, 'steps': steps}
