"""Regression coverage for operator publish-order hardening.

The supervised campaign convenience helper must never emit a consequential
publishing request before the canonical six-stage cognition workflow reaches
Final CMO. Deployment remains a separate provenance-bound pathway.
"""

import unittest

from workspace.operator import OperatorWorkspace


class _RuntimeSpy:
    def __init__(self):
        self.execute_calls = []
        self.publish_calls = []
        self.artifact = object()

    def execute_run(self, context):
        self.execute_calls.append(context)
        return context, {"status": "READY_FOR_DEPLOYMENT"}, self.artifact

    def request_publish_action(self, *args, **kwargs):
        self.publish_calls.append((args, kwargs))
        raise AssertionError("publish must not be emitted by execute_supervised_campaign")


class TestOperatorPublishOrderHardening(unittest.TestCase):
    def _workspace(self):
        workspace = object.__new__(OperatorWorkspace)
        runtime = _RuntimeSpy()
        context = object()
        create_calls = []

        workspace.runtime = runtime

        def _create_run(**kwargs):
            create_calls.append(kwargs)
            return context

        workspace.create_run = _create_run
        return workspace, runtime, context, create_calls

    def test_supervised_campaign_runs_cognition_without_pre_cognition_publish(self):
        workspace, runtime, context, create_calls = self._workspace()

        artifact = workspace.execute_supervised_campaign(
            business_id="BIZ_TEST",
            objective="Launch governed campaign",
        )

        self.assertIs(artifact, runtime.artifact)
        self.assertEqual(runtime.execute_calls, [context])
        self.assertEqual(runtime.publish_calls, [])
        self.assertEqual(
            create_calls,
            [{"business_id": "BIZ_TEST", "objective": "Launch governed campaign"}],
        )

    def test_auto_approval_remains_forbidden_before_any_run_or_publish(self):
        workspace, runtime, _context, create_calls = self._workspace()

        with self.assertRaisesRegex(RuntimeError, "AUTO_APPROVAL_FORBIDDEN"):
            workspace.execute_supervised_campaign(
                business_id="BIZ_TEST",
                objective="Launch governed campaign",
                auto_approve_token="TOKEN",
            )

        self.assertEqual(create_calls, [])
        self.assertEqual(runtime.execute_calls, [])
        self.assertEqual(runtime.publish_calls, [])


if __name__ == "__main__":
    unittest.main()
