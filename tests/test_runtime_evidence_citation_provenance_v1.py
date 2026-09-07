"""Adversarial RED contract for durable model-facing Evidence citation provenance.

Invariant under test:
A model-facing EVID-* identifier emitted by the Intelligence research grounding
must remain resolvable after the run is sealed:

    evidence_id -> observation_id -> execution_id -> action_intent_id

The durable artifact must retain only this causal identity index. It must not
copy raw observation payloads or bounded evidence content into lineage metadata.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.observation.models import (
    ContentTrustLevel,
    ContentTruthStatus,
    EpistemicType,
    ExtractionConfidence,
    SourceCredibility,
)
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


RUN_ID = "RUN-EVID-CITATION-001"
BUSINESS_ID = "BIZ-EVID-CITATION-001"
PROJECT_ID = "PROJ-EVID-CITATION-001"
EXECUTION_ID = "EXEC-EVID-CITATION-001"
ACTION_INTENT_ID = "ACT-EVID-CITATION-001"
OBSERVATION_ID = "OBS-EVID-CITATION-001"
RAW_SENTINEL = "RAW-EVIDENCE-MUST-NOT-BE-PERSISTED"


def _observation_payload(action_intent_id: Optional[str] = ACTION_INTENT_ID) -> Dict[str, Any]:
    return {
        "observation_id": OBSERVATION_ID,
        "capability": "search_web",
        "source_platform": "search_engine",
        "source_type": "search_discovery",
        "source_url_or_id": "search://duckduckgo?q=evidence+audit",
        "collected_at": "2026-09-08T00:00:00+00:00",
        "observed_at": "2026-09-08T00:00:00+00:00",
        "backend_used": "search_duckduckgo_html",
        "collection_method": "SEARCH_ENGINE_DISCOVERY",
        "raw_reference": None,
        "normalized_data": {
            "search_results": {
                "query": "evidence audit",
                "results": [
                    {
                        "rank": 1,
                        "title": "Canonical evidence source",
                        "url": "https://example.com/evidence",
                        "snippet": RAW_SENTINEL,
                    }
                ],
                "result_count": 1,
            },
            # Adversarial payload fields must never become provenance authority.
            "execution_id": "EXEC-FORGED-IN-PAYLOAD",
            "action_intent_id": "ACT-FORGED-IN-PAYLOAD",
            "evidence_id": "EVID-FORGED-IN-PAYLOAD",
        },
        "evidence_class": EpistemicType.OBSERVATION,
        "freshness_days": 0.0,
        "extraction_confidence": ExtractionConfidence.HIGH,
        "source_credibility": SourceCredibility.UNKNOWN,
        "content_truth_status": ContentTruthStatus.UNVERIFIED,
        "confidence": None,
        "limitations": ["Search snippets are discovery pointers."],
        "product_id": "evidence-audit-product",
        "brand_id": "evidence-audit-brand",
        "content_trust": ContentTrustLevel.UNTRUSTED_EXTERNAL,
        "run_id": RUN_ID,
        "business_id": BUSINESS_ID,
        "project_id": PROJECT_ID,
        "execution_id": EXECUTION_ID,
        "action_intent_id": action_intent_id,
    }


def _receipt(action_intent_id: Optional[str] = ACTION_INTENT_ID) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=EXECUTION_ID,
        run_id=RUN_ID,
        agent_id="intelligence",
        capability_id="web_search",
        provider="observation_search_adapter",
        request_hash="request-hash",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        status=ExecutionStatus.SUCCESS,
        execution_mode=ExecutionMode.REAL,
        error_class=None,
        error_message=None,
        cost_or_token_usage={},
        artifact_references=[],
        approval_reference=None,
        action_intent_id=action_intent_id,
        business_id=BUSINESS_ID,
        project_id=PROJECT_ID,
        chat_id=None,
        result_hash="result-hash",
        data={"query": "evidence audit", "result_count": 1},
        output=None,
        observation_record=_observation_payload(action_intent_id),
    )


class TestRuntimeEvidenceCitationProvenance(unittest.TestCase):
    """Model-facing Evidence IDs must survive the stage-local grounding lifetime."""

    def _run_intelligence(
        self,
        action_intent_id: Optional[str] = ACTION_INTENT_ID,
    ) -> tuple[FiveAgentDepartmentRuntime, RuntimeContext, ExecutionReceipt, str]:
        runtime = FiveAgentDepartmentRuntime()
        context = RuntimeContext(
            run_id=RUN_ID,
            objective="Research evidence citation durability",
            business_id=BUSINESS_ID,
            project_id=PROJECT_ID,
            status=RuntimeStatus.RUNNING,
        )
        receipt = _receipt(action_intent_id)

        grounded_pkg = MagicMock()
        grounded_pkg.provenance_index = {}
        grounded_pkg.evidence_items = []
        grounded_pkg.render_prompt_section.return_value = ""

        knowledge_result = MagicMock()
        knowledge_result.citations = []
        memory_result = MagicMock()
        captured: Dict[str, str] = {}

        def fake_llm(*args: Any, **kwargs: Any) -> tuple[str, None]:
            captured["prompt"] = str(args[2])
            return "Grounded deterministic research result.", None

        def passthrough_handoff(
            _context: RuntimeContext,
            _stage_key: str,
            _agent_id: str,
            _raw_output: str,
            output: Dict[str, Any],
            delegation: Optional[Dict[str, Any]] = None,
        ) -> tuple[Dict[str, Any], None, str]:
            return output, None, "EMPTY"

        with (
            patch.object(runtime, "_build_stage_lineage_context", return_value=(knowledge_result, memory_result)),
            patch.object(runtime, "_execute_tool_request", return_value=receipt),
            patch.object(runtime, "_follow_intelligence_search_pages", return_value=[]),
            patch.object(runtime.context_compiler, "compile_grounded_package", return_value=grounded_pkg),
            patch.object(runtime, "_reconcile_grounded_stage_provenance", return_value=None),
            patch.object(runtime, "_call_agent_llm", side_effect=fake_llm),
            patch.object(runtime, "_finalize_stage_handoff", side_effect=passthrough_handoff),
        ):
            output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "COMPLETED")
        prompt = captured.get("prompt", "")
        match = re.search(r"<research_grounding>\s*(\{.*?\})\s*</research_grounding>", prompt, re.DOTALL)
        self.assertIsNotNone(match, "Intelligence must actually send model-facing research grounding.")
        grounding = json.loads(match.group(1))
        self.assertTrue(grounding["evidence_items"], "Grounding must expose at least one EvidenceItem.")
        evidence_id = grounding["evidence_items"][0]["evidence_id"]
        self.assertTrue(evidence_id.startswith("EVID-"))
        return runtime, context, receipt, evidence_id

    def test_stage_persists_exact_causal_index_for_model_facing_evidence(self) -> None:
        runtime, context, _receipt_obj, evidence_id = self._run_intelligence()
        del runtime

        index = context.working_state.get("research_evidence_causal_index")
        self.assertIsInstance(
            index,
            dict,
            "STILL PRESENT: stage-local EVID-* has no durable causal index in RuntimeContext.",
        )
        self.assertIn(evidence_id, index)
        self.assertEqual(
            index[evidence_id],
            {
                "observation_id": OBSERVATION_ID,
                "execution_id": EXECUTION_ID,
                "action_intent_id": ACTION_INTENT_ID,
            },
        )

    def test_payload_forgery_cannot_replace_canonical_causal_identity(self) -> None:
        _runtime, context, _receipt_obj, evidence_id = self._run_intelligence()
        entry = context.working_state["research_evidence_causal_index"][evidence_id]
        self.assertEqual(entry["execution_id"], EXECUTION_ID)
        self.assertEqual(entry["action_intent_id"], ACTION_INTENT_ID)
        self.assertNotEqual(entry["execution_id"], "EXEC-FORGED-IN-PAYLOAD")
        self.assertNotEqual(entry["action_intent_id"], "ACT-FORGED-IN-PAYLOAD")

    def test_unbound_action_intent_remains_none_and_is_not_synthesized(self) -> None:
        _runtime, context, _receipt_obj, evidence_id = self._run_intelligence(action_intent_id=None)
        entry = context.working_state["research_evidence_causal_index"][evidence_id]
        self.assertEqual(entry["observation_id"], OBSERVATION_ID)
        self.assertEqual(entry["execution_id"], EXECUTION_ID)
        self.assertIsNone(entry["action_intent_id"])

    def test_complete_run_seals_same_evidence_causal_index(self) -> None:
        runtime, context, receipt, evidence_id = self._run_intelligence()
        with patch.object(runtime.tool_gateway.receipt_repository, "get_receipt", return_value=receipt):
            artifact = runtime.complete_run(context)

        index = artifact.lineage_summary.get("evidence_causal_index")
        self.assertIsInstance(
            index,
            dict,
            "STILL PRESENT: sealed DepartmentRunArtifact loses model-facing EVID-* provenance.",
        )
        self.assertEqual(
            index[evidence_id],
            {
                "observation_id": OBSERVATION_ID,
                "execution_id": EXECUTION_ID,
                "action_intent_id": ACTION_INTENT_ID,
            },
        )
        self.assertEqual(artifact.execution_receipts[0].execution_id, EXECUTION_ID)
        self.assertEqual(runtime.get_completed_run(RUN_ID).lineage_summary["evidence_causal_index"], index)

    def test_causal_index_is_integrity_sealed_and_does_not_copy_raw_evidence(self) -> None:
        runtime, context, receipt, evidence_id = self._run_intelligence()
        with patch.object(runtime.tool_gateway.receipt_repository, "get_receipt", return_value=receipt):
            artifact = runtime.complete_run(context)

        index = artifact.lineage_summary["evidence_causal_index"]
        serialized = json.dumps(index, sort_keys=True)
        self.assertNotIn(RAW_SENTINEL, serialized)
        self.assertNotIn("normalized_data", serialized)
        self.assertNotIn("bounded_content", serialized)
        self.assertEqual(
            set(index[evidence_id]),
            {"observation_id", "execution_id", "action_intent_id"},
        )

        sealed_hash = artifact.final_artifact_hash
        artifact.lineage_summary["evidence_causal_index"][evidence_id]["execution_id"] = "EXEC-TAMPERED"
        self.assertNotEqual(sealed_hash, artifact.compute_artifact_hash())


if __name__ == "__main__":
    unittest.main()
