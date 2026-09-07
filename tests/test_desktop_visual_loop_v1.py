"""Visual-loop, provider-boundary and clipboard adversarial contracts."""
import base64
import json
import unittest

from desktop.controller import DesktopError, DesktopSession
from desktop.vision import VisualLoop, CompatibleVisionPlanner
from desktop.clipboard import TextClipboardLease
from tests.test_local_desktop_control_v1 import FakeBackend


def proposal(action=None, status='act'):
    return {'status': status, 'reason': 'visible target', 'expected': 'draft saved',
            'action': action if action is not None else ({'kind': 'click', 'rect': [10, 20, 80, 40]} if status == 'act' else None)}


class Planner:
    def __init__(self, fn): self.fn, self.calls = fn, []
    def propose(self, goal, observation, previous):
        self.calls.append((goal, observation, previous))
        return self.fn(len(self.calls), observation)


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.now = 0
        def sleep(seconds): self.now += seconds
        self.session = DesktopSession(self.backend, clock=lambda: self.now, sleep=sleep)

    def test_relocates_target_after_screen_changes_during_model_call(self):
        def plan(n, observation):
            if n == 1:
                self.backend.png = b'moved-button'
                return proposal()
            if n == 2:
                self.assertEqual(base64.b64decode(observation['png_base64']), b'moved-button')
                return proposal({'kind': 'click', 'rect': [300, 200, 80, 40]})
            return proposal(status='done')
        approvals = []
        result = VisualLoop(self.session, Planner(plan), lambda p: approvals.append(p) or True).run('Save draft')
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertGreater(self.backend.calls[0][1], 400)
        self.assertEqual(result['status'], 'MODEL_REPORTED_COMPLETE_UNVERIFIED')

    def test_after_action_image_and_expected_result_reach_next_model_call(self):
        def click(*args):
            self.backend.calls.append(args)
            self.backend.png = b'after-input'
        self.backend.click = click
        planner = Planner(lambda n, obs: proposal() if n == 1 else proposal(status='done'))
        VisualLoop(self.session, planner, lambda p: True).run('Save draft')
        _, observation, previous = planner.calls[1]
        self.assertEqual(base64.b64decode(observation['png_base64']), b'after-input')
        self.assertEqual(previous['expected'], 'draft saved')
        self.assertEqual(previous['semantic_success'], 'UNVERIFIED')

    def test_approval_callback_cannot_mutate_approved_action(self):
        def approve(p): p['action']['rect'] = [400, 200, 80, 40]; return True
        VisualLoop(self.session, Planner(lambda n, obs: proposal()), approve, max_steps=1).run('Click')
        self.assertLess(self.backend.calls[0][1], 200)

    def test_screen_change_during_approval_requires_new_proposal_and_approval(self):
        approvals = []
        def approve(p):
            approvals.append(p)
            if len(approvals) == 1: self.backend.png = b'changed-during-review'
            return True
        VisualLoop(self.session, Planner(lambda n, obs: proposal()), approve, max_steps=1).run('Click')
        self.assertEqual(len(approvals), 2)
        self.assertEqual(len(self.backend.calls), 1)

    def test_model_flags_cannot_grant_approval(self):
        p = proposal(); p['approved'] = True
        with self.assertRaisesRegex(DesktopError, 'PROPOSAL_INVALID'):
            VisualLoop(self.session, Planner(lambda n, obs: p), lambda p: True).run('Click')
        self.assertFalse(self.backend.calls)

    def test_false_and_truthy_nonboolean_approval_do_not_dispatch(self):
        for value in (False, 'yes', 1):
            self.setUp()
            result = VisualLoop(self.session, Planner(lambda n, obs: proposal()), lambda p: value).run('Click')
            self.assertEqual(result['status'], 'APPROVAL_DECLINED')
            self.assertFalse(self.backend.calls)

    def test_failed_input_is_never_replanned_or_retried(self):
        self.backend.fail_click = True
        planner = Planner(lambda n, obs: proposal())
        with self.assertRaisesRegex(DesktopError, 'OUTCOME_UNCERTAIN'):
            VisualLoop(self.session, planner, lambda p: True).run('Click')
        self.assertEqual(len(planner.calls), 1)
        self.assertEqual(len(self.backend.calls), 1)

    def test_stop_while_model_runs_prevents_dispatch(self):
        def plan(n, obs): self.session.stop(); return proposal()
        with self.assertRaisesRegex(DesktopError, 'STOPPED'):
            VisualLoop(self.session, Planner(plan), lambda p: True).run('Click')
        self.assertFalse(self.backend.calls)

    def test_long_model_latency_refreshes_only_identical_screen(self):
        def plan(n, obs): self.now += 20; return proposal()
        result = VisualLoop(self.session, Planner(plan), lambda p: True, max_steps=1).run('Click')
        self.assertEqual(result['steps'], 1)

    def test_unstable_screen_bounded(self):
        def plan(n, obs): self.backend.png = str(n).encode(); return proposal()
        planner = Planner(plan)
        result = VisualLoop(self.session, planner, lambda p: True, max_replans=2).run('Click')
        self.assertEqual(result['status'], 'SCREEN_UNSTABLE')
        self.assertEqual(len(planner.calls), 3)
        self.assertFalse(self.backend.calls)

    def test_long_text_uses_paste_and_is_reviewed_before_dispatch(self):
        self.backend.paste = lambda text, guard, wait: self.backend.calls.append(('paste', text))
        approvals = []
        text = 'Bài viết dài\n' * 100
        result = VisualLoop(self.session, Planner(lambda n, obs: proposal({'kind': 'type', 'text': text})),
                            lambda p: approvals.append(p) or True, max_steps=1).run('Write draft')
        self.assertEqual(approvals[0]['action']['kind'], 'paste')
        self.assertEqual(self.backend.calls, [('paste', text)])
        self.assertEqual(result['steps'], 1)

    def test_provider_receives_image_and_no_redirects_or_secret_error_echo(self):
        import httpx
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload['messages'][1]['content'][1]['image_url']['url'], 'data:image/png;base64,cG5n')
            self.assertIn('UNTRUSTED DATA', payload['messages'][0]['content'])
            return httpx.Response(302, headers={'Location': 'https://another-host/'}, text='secret-provider-error')
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
            planner = CompatibleVisionPlanner('https://example.test/v1', 'vision-model', 'secret', client=client)
            with self.assertRaisesRegex(DesktopError, '^VISION_PROVIDER_REQUEST_FAILED$'):
                planner.propose('draft', {'width': 10, 'height': 10, 'png_base64': 'cG5n'}, None)

    def test_provider_parse_and_truncated_response(self):
        import httpx
        for finish in ('stop', 'length'):
            def handler(request):
                return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(proposal())}}]})
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                planner = CompatibleVisionPlanner('http://127.0.0.1:1234/v1', 'local', client=client)
                args = ('draft', {'width': 10, 'height': 10, 'png_base64': 'cG5n'}, None)
                if finish == 'stop': self.assertEqual(planner.propose(*args), proposal())
                else:
                    with self.assertRaisesRegex(DesktopError, 'INCOMPLETE'): planner.propose(*args)

    def test_endpoint_rejects_plaintext_external_and_embedded_secrets(self):
        for url in ('http://external.test/v1', 'https://key:pass@example.test/v1', 'https://example.test/v1?key=secret'):
            with self.assertRaises(DesktopError): CompatibleVisionPlanner(url, 'model', 'key')


class Clipboard:
    def __init__(self):
        self.formats, self.value, self.sequence = [13], 'original', 1
        self.concurrent_on_close = False
        self.marker = None
        self.dirty = False
    def RegisterClipboardFormat(self, name): return 50000
    def SetClipboardData(self, format, data): self.marker = data; self.dirty = True
    def OpenClipboard(self, hwnd): pass
    def CloseClipboard(self):
        if self.dirty:
            self.sequence += 1
            self.dirty = False
        if self.concurrent_on_close:
            self.concurrent_on_close = False
            self.value = 'human copy'; self.marker = None; self.sequence += 1
    def EnumClipboardFormats(self, previous):
        return self.formats[0] if not previous and self.formats else 0
    def GetClipboardData(self, format): return self.value if format == 13 else self.marker
    def EmptyClipboard(self): self.value = None; self.marker = None; self.dirty = True; self.sequence += 1
    def SetClipboardText(self, value, format): self.value = value; self.sequence += 1
    def GetClipboardSequenceNumber(self): return self.sequence


class ClipboardTests(unittest.TestCase):
    def test_restores_original_text(self):
        api = Clipboard(); lease = TextClipboardLease(api, 'long text', 1)
        self.assertEqual(api.value, 'long text')
        self.assertTrue(lease.restore(1))
        self.assertEqual(api.value, 'original')

    def test_concurrent_copy_is_never_overwritten_including_close_race(self):
        api = Clipboard(); api.concurrent_on_close = True
        with self.assertRaisesRegex(DesktopError, 'CHANGED_BEFORE_PASTE'):
            TextClipboardLease(api, 'long text', 1)
        self.assertEqual(api.value, 'human copy')

    def test_copy_after_lease_is_preserved(self):
        api = Clipboard(); lease = TextClipboardLease(api, 'long text', 1)
        api.EmptyClipboard(); api.SetClipboardText('later human copy', 13); api.CloseClipboard()
        self.assertFalse(lease.restore(1))
        self.assertEqual(api.value, 'later human copy')

    def test_rich_clipboard_is_left_untouched(self):
        api = Clipboard(); api.formats = [49152]
        with self.assertRaisesRegex(DesktopError, 'FORMAT_UNSUPPORTED'): TextClipboardLease(api, 'new', 1)
        self.assertEqual(api.value, 'original')

    def test_empty_clipboard_restored(self):
        api = Clipboard(); api.formats = []; api.value = None
        lease = TextClipboardLease(api, 'new', 1)
        lease.restore(1)
        self.assertIsNone(api.value)


if __name__ == '__main__': unittest.main()
