"""Live supervision contracts, no real desktop or network access."""
import random
import threading
import unittest
from desktop.controller import DesktopError
from desktop.live import LiveSession, LiveTask, TaskGrant
from tests.test_local_desktop_control_v1 import FakeBackend

ACT = {'status': 'act', 'reason': 'target', 'expected': 'opened',
       'action': {'kind': 'click', 'rect': [10, 20, 80, 40]}}
DONE = {'status': 'done', 'reason': 'visible', 'expected': '', 'action': None}

class Planner:
    def __init__(self, callback): self.callback = callback
    def propose(self, *args): return self.callback(*args)

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.backend = FakeBackend()
        self.session = LiveSession(self.backend, clock=lambda: self.now,
                                   sleep=self.sleep, rng=random.Random(4))
    def sleep(self, seconds): self.now += seconds
    def grant(self, **kw):
        return TaskGrant(goal='open draft', window=self.session.window,
                         max_steps=3, **kw)
    def test_preview_does_not_invalidate_action_observation(self):
        o = self.session.observe()
        self.assertNotIn('observation_id', self.session.preview())
        self.session.act({**ACT['action'], 'observation_id': o['observation_id']})
        self.assertEqual(len(self.backend.calls), 1)
    def test_stop_during_planning_never_dispatches(self):
        def propose(*a): self.session.stop(); return ACT
        task = LiveTask(self.session, Planner(propose), self.grant())
        with self.assertRaises(DesktopError): task.run()
        self.assertFalse(self.backend.calls)
    def test_grant_scope_cannot_change(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            LiveTask(self.session, Planner(lambda *a: ACT), replace(self.grant(), window=replace(self.session.window, pid=99)))
    def test_no_per_click_approval_and_done_is_not_verified(self):
        replies = iter([ACT, DONE])
        task = LiveTask(self.session, Planner(lambda *a: next(replies)), self.grant())
        result = task.run()
        self.assertEqual(result['status'], 'MODEL_REPORTED_COMPLETE_UNVERIFIED')
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(task.events()[-1]['status'], result['status'])
    def test_disallowed_action_is_denied_without_input(self):
        task = LiveTask(self.session, Planner(lambda *a: ACT), self.grant(allowed_kinds=('scroll',)))
        self.assertEqual(task.run()['status'], 'OUTSIDE_GRANT')
        self.assertFalse(self.backend.calls)
    def test_partial_failure_never_retried(self):
        self.backend.fail_click = True
        task = LiveTask(self.session, Planner(lambda *a: ACT), self.grant())
        with self.assertRaisesRegex(DesktopError, 'UNCERTAIN'): task.run()
        self.assertEqual(len(self.backend.calls), 1)
    def test_changed_pixels_discard_old_proposal(self):
        calls = []
        def propose(*a):
            calls.append(1)
            if len(calls) == 1: self.backend.png = b'changed'; return ACT
            return DONE
        task = LiveTask(self.session, Planner(propose), self.grant())
        task.run()
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.backend.calls)
    def test_verifier_must_supply_evidence_not_truthy_flag(self):
        task = LiveTask(self.session, Planner(lambda *a: DONE), self.grant(), verifier=lambda *a: True)
        self.assertEqual(task.run()['status'], 'MODEL_REPORTED_COMPLETE_UNVERIFIED')
    def test_host_verifier_receives_fresh_observation(self):
        def verify(goal, obs): return {'verified': True, 'evidence': obs['sha256']}
        task = LiveTask(self.session, Planner(lambda *a: DONE), self.grant(), verifier=verify)
        self.assertEqual(task.run()['status'], 'HOST_VERIFIED')
    def test_pause_invalidates_pending_plan_even_after_resume(self):
        calls = []
        def propose(*a):
            calls.append(1)
            if len(calls) == 1:
                self.session.pause(); self.session.resume(); return ACT
            return DONE
        task = LiveTask(self.session, Planner(propose), self.grant())
        task.run()
        self.assertFalse(self.backend.calls)
        self.assertEqual(len(calls), 2)
    def test_preview_skips_busy_input_without_blocking(self):
        with self.session._lock: self.assertIsNone(self.session.preview())
    def test_verifier_cannot_complete_after_stop(self):
        def verify(*a): self.session.stop(); return {'verified': True, 'evidence': 'x'}
        task = LiveTask(self.session, Planner(lambda *a: DONE), self.grant(), verifier=verify)
        with self.assertRaises(DesktopError): task.run()
    def test_task_cannot_run_twice(self):
        task = LiveTask(self.session, Planner(lambda *a: DONE), self.grant())
        task.run()
        with self.assertRaisesRegex(DesktopError, 'ALREADY_USED'): task.run()
    def test_pause_resume_before_dispatch_invalidates_generation(self):
        o = self.session.observe()
        generation = self.session.generation
        self.session.pause(); self.session.resume()
        with self.assertRaisesRegex(DesktopError, 'PAUSED'):
            self.session.act({**ACT['action'], 'observation_id': o['observation_id']}, generation=generation)
        self.assertFalse(self.backend.calls)
    def test_model_cannot_grant_permission(self):
        task = LiveTask(self.session, Planner(lambda *a: {**ACT, 'approved': True}), self.grant())
        with self.assertRaises(DesktopError): task.run()
        self.assertFalse(self.backend.calls)

if __name__ == '__main__': unittest.main()
