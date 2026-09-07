"""Hermetic regression tests. These do not operate the host mouse/keyboard."""
import random
import unittest
from dataclasses import replace

from desktop.controller import DesktopError, DesktopSession, Window
from desktop.adapter import register_desktop
from tools.tool_gateway import ToolGateway, ToolRequest
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionStatus, ExecutionMode


class FakeBackend:
    def __init__(self):
        self.current = Window(10, 20, 100, 100, 640, 480)
        self.png = b'fake-window-image'
        self.halt = False
        self.calls = []
        self.fail_click = False

    def window(self): return self.current
    def stopped(self): return self.halt
    def capture(self): return self.png
    def click(self, x, y, duration):
        self.calls.append(('click', x, y, duration))
        if self.fail_click: raise RuntimeError('lost focus after input')
    def write_char(self, char): self.calls.append(('type', char))
    def press(self, key): self.calls.append(('press', key))
    def scroll(self, ticks, x, y): self.calls.append(('scroll', ticks, x, y))


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.backend = FakeBackend()
        self.session = DesktopSession(self.backend, clock=lambda: self.now,
                                      sleep=self.sleep, rng=random.Random(42), max_actions=100)

    def sleep(self, value): self.now += value

    def action(self, kind='click', **kwargs):
        observation = self.session.observe()
        return {'kind': kind, 'observation_id': observation['observation_id'],
                **({'rect': [10, 20, 80, 40]} if kind == 'click' else kwargs)}

    def test_random_points_stay_in_safe_interior_and_vary(self):
        for _ in range(40): self.session.act(self.action())
        points = [(c[1], c[2]) for c in self.backend.calls]
        self.assertGreater(len(set(points)), 20)
        self.assertTrue(all(118 <= x <= 181 and 128 <= y <= 151 for x, y in points))
        self.assertGreater(len(set(c[3] for c in self.backend.calls)), 1)

    def test_observation_cannot_be_replayed(self):
        action = self.action()
        self.session.act(action)
        with self.assertRaisesRegex(DesktopError, 'OBSERVATION_INVALID'): self.session.act(action)
        self.assertEqual(len(self.backend.calls), 1)

    def test_stale_observation_denied(self):
        action = self.action()
        self.now = 16
        with self.assertRaisesRegex(DesktopError, 'OBSERVATION_EXPIRED'): self.session.act(action)
        self.assertFalse(self.backend.calls)

    def test_changed_screen_denied(self):
        action = self.action()
        self.backend.png = b'new screen'
        with self.assertRaisesRegex(DesktopError, 'SCREEN_CHANGED'): self.session.act(action)
        self.assertFalse(self.backend.calls)

    def test_window_scope_includes_handle_pid_position_and_size(self):
        for field in ('hwnd', 'pid', 'left', 'top', 'width', 'height'):
            with self.subTest(field=field):
                self.setUp()
                action = self.action()
                self.backend.current = replace(self.backend.current, **{field: getattr(self.backend.current, field)+1})
                with self.assertRaisesRegex(DesktopError, 'WINDOW_CHANGED'): self.session.act(action)
                self.assertFalse(self.backend.calls)

    def test_stop_during_pause_prevents_click(self):
        action = self.action()
        def interrupt(value):
            self.now += value
            self.backend.halt = True
        self.session.sleep = interrupt
        with self.assertRaisesRegex(DesktopError, 'STOPPED'): self.session.act(action)
        self.assertFalse(self.backend.calls)

    def test_explicit_stop_is_permanent(self):
        self.session.stop()
        with self.assertRaisesRegex(DesktopError, 'STOPPED'): self.session.observe()

    def test_action_budget(self):
        self.session.remaining = 1
        self.session.act(self.action())
        with self.assertRaisesRegex(DesktopError, 'BUDGET'): self.session.act(self.action())
        self.assertEqual(len(self.backend.calls), 1)

    def test_lifetime(self):
        self.now = 301
        with self.assertRaisesRegex(DesktopError, 'SESSION_EXPIRED'): self.session.observe()

    def test_unsafe_rectangles(self):
        for rect in ([-1, 0, 20, 20], [630, 0, 20, 20], [0, 0, 2, 2], [True, 0, 20, 20], [0, 0, 20]):
            with self.subTest(rect=rect):
                action = self.action()
                action['rect'] = rect
                with self.assertRaises(DesktopError): self.session.act(action)
        self.assertFalse(self.backend.calls)

    def test_unicode_text_preserved(self):
        text = 'Xin chào Việt Nam 👋'
        result = self.session.act(self.action('type', text=text))
        self.assertEqual(''.join(c[1] for c in self.backend.calls), text)
        self.assertEqual(result['semantic_success'], 'UNVERIFIED')

    def test_text_cannot_smuggle_enter_or_control_keys(self):
        for text in ('hello\nsubmit', '\t', '\x1b', '\x85', '\ud800', '', 'x'*501):
            with self.subTest(text=repr(text)):
                with self.assertRaisesRegex(DesktopError, 'TEXT_INVALID'): self.session.act(self.action('type', text=text))
        self.assertFalse(self.backend.calls)

    def test_unknown_keys_and_extra_fields_denied(self):
        with self.assertRaisesRegex(DesktopError, 'KEY_NOT_ALLOWED'): self.session.act(self.action('press', key='win'))
        action = self.action()
        action['double_click'] = True
        with self.assertRaisesRegex(DesktopError, 'ACTION_INVALID'): self.session.act(action)
        self.assertFalse(self.backend.calls)

    def test_scroll_bounded_and_positioned(self):
        for ticks in (0, 6, -6, True):
            with self.assertRaisesRegex(DesktopError, 'SCROLL_INVALID'):
                self.session.act(self.action('scroll', rect=[10, 20, 80, 40], ticks=ticks))
        self.session.act(self.action('scroll', rect=[10, 20, 80, 40], ticks=-3))
        self.assertEqual(self.backend.calls[0][:2], ('scroll', -3))

    def test_partial_input_failure_stops_no_retry(self):
        self.backend.fail_click = True
        with self.assertRaisesRegex(DesktopError, 'OUTCOME_UNCERTAIN'): self.session.act(self.action())
        with self.assertRaisesRegex(DesktopError, 'STOPPED'): self.session.observe()
        self.assertEqual(len(self.backend.calls), 1)

    def test_focus_change_during_typing_stops_remaining_characters(self):
        def write(char):
            self.backend.calls.append(('type', char))
            self.backend.current = replace(self.backend.current, hwnd=11)
        self.backend.write_char = write
        with self.assertRaisesRegex(DesktopError, 'OUTCOME_UNCERTAIN'):
            self.session.act(self.action('type', text='hello'))
        self.assertEqual(len(self.backend.calls), 1)

    def test_operation_timeout_before_input(self):
        with self.assertRaisesRegex(DesktopError, 'OPERATION_TIMEOUT'):
            self.session.act(self.action(), timeout_seconds=0.01)
        self.assertFalse(self.backend.calls)

    def test_gateway_requires_approval_and_preserves_scope(self):
        gateway = ToolGateway(capability_registry=CapabilityRegistry())
        adapter = register_desktop(gateway, self.session, run_id='r', business_id='b', project_id='p')
        action = self.action()
        request = ToolRequest(run_id='r', business_id='b', project_id='p', agent_id='cmo', capability_id='desktop_act', parameters=action)
        receipt = gateway.execute(request)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertFalse(self.backend.calls)
        approval = gateway.policy_engine.create_server_approval('desktop_act', parameters=action, run_id='r', business_id='b')
        request.approval_token = approval.approval_token
        receipt = gateway.execute(request)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        gateway.execute(request)
        self.assertEqual(len(self.backend.calls), 1)
        denied = adapter.execute('desktop_observe', {}, run_id='r', business_id='other', project_id='p')
        self.assertEqual(denied.error_code, 'DESKTOP_SCOPE_MISMATCH')

    def test_observe_requires_approval_and_duplicate_registration_denied(self):
        gateway = ToolGateway(capability_registry=CapabilityRegistry())
        register_desktop(gateway, self.session, run_id='r', business_id='b', project_id='p')
        receipt = gateway.execute(ToolRequest(run_id='r', business_id='b', project_id='p', agent_id='cmo', capability_id='desktop_observe', parameters={}))
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        with self.assertRaises(ValueError): register_desktop(gateway, self.session, run_id='r', business_id='b', project_id='p')


if __name__ == '__main__': unittest.main()
