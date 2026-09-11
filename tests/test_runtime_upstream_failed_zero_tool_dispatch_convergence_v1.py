from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime


class RuntimeUpstreamFailedZeroToolDispatchConvergenceV1Tests(unittest.TestCase):
    @staticmethod
    def _runtime() -> FiveAgentDepartmentRuntime:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._get_emitter = lambda *_args, **_kwargs: None
        runtime._execute_tool_request = MagicMock(side_effect=AssertionError('tool dispatch must not occur after known upstream failure'))
        return runtime

    @staticmethod
    def _failed_context(run_id: str, upstream_stage: str) -> RuntimeContext:
        context = RuntimeContext(
            run_id=run_id,
            objective='Launch a governed marketing campaign',
            business_id='BIZ-UPSTREAM-FAILED-CONVERGENCE-V1',
            project_id='PROJ-UPSTREAM-FAILED-CONVERGENCE-V1',
        )
        context.status = RuntimeStatus.FAILED
        context.stage_outputs[upstream_stage] = {
            'stage': upstream_stage.upper(),
            'status': 'FAILED',
            'error': 'UPSTREAM_TEST_FAILURE',
        }
        return context

    def test_intelligence_does_not_search_after_cmo_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context('RUN-UPSTREAM-FAILED-INT-CONV', 'cmo_initial')
        output = runtime.execute_stage_intelligence(context)
        self.assertEqual('FAILED', output['status'])
        self.assertEqual('PREVIOUS_STAGE_FAILED', output['error'])
        self.assertIsNone(output.get('search_receipt_id'))
        self.assertEqual([], context.execution_receipt_refs)
        runtime._execute_tool_request.assert_not_called()

    def test_content_does_not_mutate_lineage_after_intelligence_failure(self) -> None:
        runtime = self._runtime()
        runtime._build_stage_lineage_context = MagicMock(
            side_effect=AssertionError('lineage retrieval must not occur after known upstream failure')
        )
        runtime.context_compiler = MagicMock()
        runtime._call_agent_llm = MagicMock(
            side_effect=AssertionError('model invocation must not occur after known upstream failure')
        )
        context = self._failed_context('RUN-UPSTREAM-FAILED-CONTENT-CONV', 'intelligence')
        sentinel = {'upstream-source': {'origin': 'preexisting'}}
        context.working_state['provenance_index'] = dict(sentinel)

        output = runtime.execute_stage_content(context)

        self.assertEqual('FAILED', output['status'])
        self.assertEqual('PREVIOUS_STAGE_FAILED', output['error'])
        self.assertEqual([], output['citations'])
        self.assertEqual(sentinel, context.working_state['provenance_index'])
        runtime._build_stage_lineage_context.assert_not_called()
        runtime.context_compiler.compile_grounded_package.assert_not_called()
        runtime._call_agent_llm.assert_not_called()
        runtime._execute_tool_request.assert_not_called()

    def test_creative_does_not_generate_asset_after_content_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context('RUN-UPSTREAM-FAILED-CREATIVE-CONV', 'content')
        output = runtime.execute_stage_creative(context)
        self.assertEqual('FAILED', output['status'])
        self.assertEqual('PREVIOUS_STAGE_FAILED', output['error'])
        self.assertIsNone(output.get('visual_asset_receipt'))
        self.assertEqual([], context.execution_receipt_refs)
        self.assertEqual([], context.artifact_refs)
        runtime._execute_tool_request.assert_not_called()

    def test_performance_does_not_retrieve_analytics_after_creative_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context('RUN-UPSTREAM-FAILED-PERF-CONV', 'creative')
        output = runtime.execute_stage_performance(context)
        self.assertEqual('FAILED', output['status'])
        self.assertEqual('PREVIOUS_STAGE_FAILED', output['error'])
        self.assertIsNone(output.get('analytics_receipt_id'))
        self.assertEqual('NOT_ATTEMPTED:PREVIOUS_STAGE_FAILED', output.get('analytics_data_status'))
        self.assertEqual([], context.execution_receipt_refs)
        runtime._execute_tool_request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
