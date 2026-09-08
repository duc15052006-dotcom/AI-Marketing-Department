"""Adversarial RED contract for run-isolated knowledge citation lineage.

Invariant under test:
A long-lived FiveAgentDepartmentRuntime may process many runs, but a sealed
DepartmentRunArtifact must expose only knowledge citations referenced by that
specific RuntimeContext. Citations retained by the runtime-wide
LineageInspector from earlier or unrelated runs must never leak into the next
artifact. Mutable RuntimeContext.knowledge_refs is request input, not citation
ownership authority.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge.models import KnowledgeCitation
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime


class TestRuntimeLineageCitationRunIsolation(unittest.TestCase):
    @staticmethod
    def _citation(citation_id: str, knowledge_id: str) -> KnowledgeCitation:
        return KnowledgeCitation(
            citation_id=citation_id,
            knowledge_id=knowledge_id,
            chunk_id=f"CHK-{knowledge_id}",
            source_id=f"SRC-{knowledge_id}",
            claim_ref=f"claim:{knowledge_id}",
            confidence=1.0,
        )

    @staticmethod
    def _context(run_id: str, business_id: str, citation_ids: list[str]) -> RuntimeContext:
        context = RuntimeContext(
            run_id=run_id,
            objective=f"Isolation contract for {run_id}",
            business_id=business_id,
            project_id=f"PROJ-{run_id}",
            status=RuntimeStatus.RUNNING,
        )
        context.knowledge_refs.extend(citation_ids)
        return context

    def test_second_run_artifact_excludes_first_run_citation(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        citation_a = self._citation("CIT-RUN-A", "KNOW-RUN-A")
        citation_b = self._citation("CIT-RUN-B", "KNOW-RUN-B")

        runtime.lineage_inspector.add_citation(citation_a)
        artifact_a = runtime.complete_run(
            self._context("RUN-LINEAGE-A", "BIZ-LINEAGE-A", [citation_a.citation_id])
        )
        self.assertEqual(artifact_a.lineage_summary["citations"], [citation_a.citation_id])

        runtime.lineage_inspector.add_citation(citation_b)
        artifact_b = runtime.complete_run(
            self._context("RUN-LINEAGE-B", "BIZ-LINEAGE-B", [citation_b.citation_id])
        )

        self.assertEqual(artifact_b.knowledge_used, [citation_b.citation_id])
        self.assertEqual(
            artifact_b.lineage_summary["citations"],
            [citation_b.citation_id],
            "STILL PRESENT: run B artifact leaks runtime-global citation(s) from run A.",
        )
        self.assertNotIn(citation_a.citation_id, artifact_b.lineage_summary["citations"])

    def test_previous_run_owned_citation_cannot_be_reinjected_via_mutable_refs(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        citation_a = self._citation("CIT-OWNED-RUN-A", "KNOW-OWNED-RUN-A")
        runtime.lineage_inspector.add_citation(citation_a)

        artifact_a = runtime.complete_run(
            self._context("RUN-OWNER-A", "BIZ-OWNER-A", [citation_a.citation_id])
        )
        self.assertEqual(artifact_a.knowledge_used, [citation_a.citation_id])
        self.assertEqual(artifact_a.lineage_summary["citations"], [citation_a.citation_id])

        # Adversarial mutation: current-run refs are not an ownership authority.
        artifact_b = runtime.complete_run(
            self._context("RUN-OWNER-B", "BIZ-OWNER-B", [citation_a.citation_id])
        )

        self.assertEqual(
            artifact_b.knowledge_used,
            [],
            "STILL PRESENT: mutable run-B refs can claim a citation already owned by run A.",
        )
        self.assertEqual(
            artifact_b.lineage_summary["citations"],
            [],
            "STILL PRESENT: mutable run-B refs can reinject run A citation into sealed lineage.",
        )

    def test_unknown_mutable_ref_cannot_be_sealed_as_owned_citation(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        unknown_citation_id = "CIT-NOT-IN-LINEAGE-INSPECTOR"

        artifact = runtime.complete_run(
            self._context(
                "RUN-UNKNOWN-CITATION",
                "BIZ-UNKNOWN-CITATION",
                [unknown_citation_id],
            )
        )

        self.assertEqual(
            artifact.knowledge_used,
            [],
            "STILL PRESENT: mutable refs can fabricate sealed knowledge ownership without a citation record.",
        )
        self.assertEqual(
            artifact.lineage_summary["citations"],
            [],
            "STILL PRESENT: unknown mutable citation ref appears in sealed lineage.",
        )

    def test_citation_ownership_survives_completed_artifact_cache_eviction(self) -> None:
        runtime = FiveAgentDepartmentRuntime(max_completed_runs_cache=1)
        citation_a = self._citation("CIT-EVICTED-OWNER-A", "KNOW-EVICTED-OWNER-A")
        citation_b = self._citation("CIT-EVICTION-FILLER-B", "KNOW-EVICTION-FILLER-B")
        runtime.lineage_inspector.add_citation(citation_a)
        runtime.lineage_inspector.add_citation(citation_b)

        artifact_a = runtime.complete_run(
            self._context("RUN-EVICT-OWNER-A", "BIZ-EVICT-OWNER-A", [citation_a.citation_id])
        )
        self.assertEqual(artifact_a.knowledge_used, [citation_a.citation_id])

        runtime.complete_run(
            self._context("RUN-EVICT-FILLER-B", "BIZ-EVICT-FILLER-B", [citation_b.citation_id])
        )
        self.assertIsNone(runtime.get_completed_run("RUN-EVICT-OWNER-A"))

        artifact_c = runtime.complete_run(
            self._context("RUN-EVICT-ATTACKER-C", "BIZ-EVICT-ATTACKER-C", [citation_a.citation_id])
        )
        self.assertEqual(
            artifact_c.knowledge_used,
            [],
            "STILL PRESENT: citation ownership disappears when the owner's artifact leaves the bounded cache.",
        )
        self.assertEqual(artifact_c.lineage_summary["citations"], [])

    def test_failed_artifact_seal_does_not_claim_citation_ownership(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        citation = self._citation("CIT-FAILED-SEAL", "KNOW-FAILED-SEAL")
        runtime.lineage_inspector.add_citation(citation)

        with patch(
            "runtime.engine.DepartmentRunArtifact.compute_artifact_hash",
            side_effect=RuntimeError("forced seal failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced seal failure"):
                runtime.complete_run(
                    self._context(
                        "RUN-FAILED-SEAL-A",
                        "BIZ-FAILED-SEAL-A",
                        [citation.citation_id],
                    )
                )

        artifact_b = runtime.complete_run(
            self._context(
                "RUN-AFTER-FAILED-SEAL-B",
                "BIZ-AFTER-FAILED-SEAL-B",
                [citation.citation_id],
            )
        )
        self.assertEqual(
            artifact_b.knowledge_used,
            [citation.citation_id],
            "STILL PRESENT: a failed artifact seal can poison citation ownership for a later valid run.",
        )
        self.assertEqual(artifact_b.lineage_summary["citations"], [citation.citation_id])

    def test_unreferenced_runtime_global_citation_never_enters_artifact(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        referenced = self._citation("CIT-REFERENCED", "KNOW-REFERENCED")
        unrelated = self._citation("CIT-UNRELATED", "KNOW-UNRELATED")
        runtime.lineage_inspector.add_citation(unrelated)
        runtime.lineage_inspector.add_citation(referenced)

        artifact = runtime.complete_run(
            self._context("RUN-LINEAGE-REFERENCED", "BIZ-LINEAGE-REFERENCED", [referenced.citation_id])
        )

        self.assertEqual(artifact.knowledge_used, [referenced.citation_id])
        self.assertEqual(
            artifact.lineage_summary["citations"],
            [referenced.citation_id],
            "STILL PRESENT: an unreferenced runtime-global citation contaminates sealed lineage.",
        )
        self.assertNotIn(unrelated.citation_id, artifact.lineage_summary["citations"])

    def test_empty_current_run_does_not_inherit_previous_citations(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        prior = self._citation("CIT-PRIOR", "KNOW-PRIOR")
        runtime.lineage_inspector.add_citation(prior)
        runtime.complete_run(
            self._context("RUN-LINEAGE-PRIOR", "BIZ-LINEAGE-PRIOR", [prior.citation_id])
        )

        artifact_empty = runtime.complete_run(
            self._context("RUN-LINEAGE-EMPTY", "BIZ-LINEAGE-EMPTY", [])
        )

        self.assertEqual(artifact_empty.knowledge_used, [])
        self.assertEqual(
            artifact_empty.lineage_summary["citations"],
            [],
            "STILL PRESENT: citation history from a prior run leaks into a citation-free run.",
        )


if __name__ == "__main__":
    unittest.main()
