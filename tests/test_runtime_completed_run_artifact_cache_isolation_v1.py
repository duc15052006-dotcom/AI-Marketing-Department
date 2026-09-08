"""Regression tests for completed-run artifact cache isolation.

A completed DepartmentRunArtifact is a sealed audit record. The runtime cache
must never share mutable object identity with either the artifact returned by
run_workflow/complete_run or with callers of get_completed_run(). Otherwise an
external caller can mutate the cached historical record without crossing any
runtime authority boundary.
"""

from __future__ import annotations

import unittest

from integrations.models.base import ModelRequest, ModelResponse, ModelResponseStatus
from integrations.models.gateway import UniversalModelGateway
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class _DeterministicGateway(UniversalModelGateway):
    """Hermetic model gateway for cache-boundary regression tests."""

    def __init__(self) -> None:
        super().__init__(free_only_mode=True)

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        agent_id = kwargs.get("agent_id") or (request.metadata or {}).get("agent_id") or "unknown"
        return ModelResponse(
            request_id=request.request_id,
            provider="cache-isolation-test",
            model_name="deterministic",
            status=ModelResponseStatus.SUCCESS,
            content=f"Deterministic output for {agent_id}.",
        )


def _build_runtime() -> FiveAgentDepartmentRuntime:
    return FiveAgentDepartmentRuntime(
        model_gateway=_DeterministicGateway(),
        tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
        max_completed_runs_cache=8,
    )


class TestRuntimeCompletedRunArtifactCacheIsolationV1(unittest.TestCase):
    def _complete_run(self):
        runtime = _build_runtime()
        context, _, artifact = runtime.run_workflow(
            objective="Completed-run artifact cache isolation regression",
            business_id="BIZ_CACHE_ISOLATION",
        )
        self.assertIsNotNone(runtime.get_completed_run(context.run_id))
        return runtime, context.run_id, artifact

    def test_returned_completed_artifact_cannot_mutate_cached_history(self) -> None:
        """The completion return value must not alias the authoritative cache entry."""
        runtime, run_id, returned_artifact = self._complete_run()
        original_hash = returned_artifact.final_artifact_hash

        returned_artifact.final_cmo_output["external_tamper_marker"] = "RETURN_ALIAS"

        cached = runtime.get_completed_run(run_id)
        self.assertIsNotNone(cached)
        self.assertNotIn("external_tamper_marker", cached.final_cmo_output)
        self.assertEqual(cached.final_artifact_hash, original_hash)
        self.assertEqual(cached.compute_artifact_hash(), original_hash)

    def test_completed_run_reads_are_deep_snapshot_isolated(self) -> None:
        """Mutating one cache read must not mutate later reads or their nested state."""
        runtime, run_id, _ = self._complete_run()

        first = runtime.get_completed_run(run_id)
        self.assertIsNotNone(first)
        original_hash = first.final_artifact_hash
        first.lineage_summary["external_tamper_marker"] = {"source": ["READ_ALIAS"]}

        second = runtime.get_completed_run(run_id)
        self.assertIsNotNone(second)
        self.assertIsNot(first, second)
        self.assertNotIn("external_tamper_marker", second.lineage_summary)
        self.assertEqual(second.final_artifact_hash, original_hash)
        self.assertEqual(second.compute_artifact_hash(), original_hash)


if __name__ == "__main__":
    unittest.main()
