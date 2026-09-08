"""Adversarial regression for completed DepartmentRunArtifact cache aliasing.

Invariant:
A caller must never receive a mutable alias to the runtime's canonical sealed
completed-run artifact. Mutating either the object returned by complete_run()
or an object returned by get_completed_run() must not change the canonical
cached artifact or leave its stored final_artifact_hash stale.
"""

from __future__ import annotations

import unittest

from runtime.engine import FiveAgentDepartmentRuntime


class RuntimeCompletedArtifactCacheAliasV1Tests(unittest.TestCase):
    def _complete_minimal_run(self):
        runtime = FiveAgentDepartmentRuntime()
        context = runtime.start_run(
            objective="Preserve canonical completed artifact authority",
            business_id="BIZ-ARTIFACT-ALIAS-V1",
        )
        artifact = runtime.complete_run(context)
        self.assertTrue(artifact.final_artifact_hash)
        self.assertEqual(
            artifact.compute_artifact_hash(),
            artifact.final_artifact_hash,
            "freshly sealed artifact must start internally consistent",
        )
        return runtime, context.run_id, artifact

    def test_complete_run_return_value_cannot_mutate_canonical_cache(self):
        runtime, run_id, returned = self._complete_minimal_run()
        original_objective = returned.objective
        original_hash = returned.final_artifact_hash

        returned.objective = "CALLER-TAMPERED-OBJECTIVE"
        returned.agent_outputs["caller_tamper"] = {"accepted": True}

        canonical = runtime.get_completed_run(run_id)
        self.assertIsNotNone(canonical)
        self.assertEqual(
            canonical.objective,
            original_objective,
            "complete_run() must not hand out the canonical cached object by mutable alias",
        )
        self.assertNotIn(
            "caller_tamper",
            canonical.agent_outputs,
            "nested mutation of complete_run() return value must not corrupt canonical cache",
        )
        self.assertEqual(canonical.final_artifact_hash, original_hash)
        self.assertEqual(
            canonical.compute_artifact_hash(),
            original_hash,
            "canonical cached artifact must remain consistent with its sealed hash",
        )

    def test_get_completed_run_return_value_cannot_mutate_canonical_cache(self):
        runtime, run_id, returned = self._complete_minimal_run()
        original_objective = returned.objective
        original_hash = returned.final_artifact_hash

        first_read = runtime.get_completed_run(run_id)
        self.assertIsNotNone(first_read)
        first_read.objective = "READER-TAMPERED-OBJECTIVE"
        first_read.lineage_summary["reader_tamper"] = ["forged-lineage"]

        second_read = runtime.get_completed_run(run_id)
        self.assertIsNotNone(second_read)
        self.assertEqual(
            second_read.objective,
            original_objective,
            "get_completed_run() must return a defensive snapshot, not the canonical cached object",
        )
        self.assertNotIn(
            "reader_tamper",
            second_read.lineage_summary,
            "nested mutation of one read must not affect later reads",
        )
        self.assertEqual(second_read.final_artifact_hash, original_hash)
        self.assertEqual(
            second_read.compute_artifact_hash(),
            original_hash,
            "later reads must remain consistent with the canonical sealed hash",
        )


if __name__ == "__main__":
    unittest.main()
