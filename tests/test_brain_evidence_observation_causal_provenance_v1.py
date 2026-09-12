"""Adversarial RED for ObservationRecord -> EvidenceItem causal provenance.

Invariant: when EvidenceBuilder materializes an EvidenceItem from an ObservationRecord,
the evidence must preserve the Observation's exact canonical execution provenance.
The builder must never invent, replace, or derive execution/action-intent identity from
untrusted payload metadata. Legacy observations remain explicitly unbound from Brain
ActionIntent provenance.
"""

from __future__ import annotations

import unittest

from tools.evidence.builder import EvidenceBuilder
from tools.evidence.models import EvidenceItem
from tools.observation.models import ObservationRecord


class BrainEvidenceObservationCausalProvenanceV1Tests(unittest.TestCase):
    CAPABILITY_ID = "search_web"

    @classmethod
    def _observation(
        cls,
        *,
        execution_id: str = "EXEC-CANONICAL-001",
        action_intent_id: str | None = "AI-CANONICAL-001",
        normalized_data: dict | None = None,
    ) -> ObservationRecord:
        return ObservationRecord(
            observation_id="OBS-EVIDENCE-PROV-001",
            capability=cls.CAPABILITY_ID,
            source_platform="search_engine",
            source_type="search_discovery",
            source_url_or_id="canonical evidence query",
            backend_used="search_test",
            collection_method="SEARCH_ENGINE_DISCOVERY",
            normalized_data=normalized_data or {
                "search_results": {
                    "results": [
                        {
                            "rank": 1,
                            "title": "bounded source",
                            "url": "https://example.com/source",
                            "snippet": "bounded evidence",
                        }
                    ]
                }
            },
            product_id="product-evidence-provenance",
            brand_id="brand-evidence-provenance",
            run_id="RUN-EVIDENCE-PROV-001",
            business_id="business-evidence-provenance",
            project_id="project-evidence-provenance",
            execution_id=execution_id,
            action_intent_id=action_intent_id,
        )

    def test_evidence_contract_exposes_causal_execution_fields(self) -> None:
        self.assertIn(
            "execution_id",
            EvidenceItem.__annotations__,
            "STILL_PRESENT: EvidenceItem has no causal execution provenance field.",
        )
        self.assertIn(
            "action_intent_id",
            EvidenceItem.__annotations__,
            "STILL_PRESENT: EvidenceItem has no canonical Brain ActionIntent provenance field.",
        )

    def test_semantic_observation_to_evidence_preserves_exact_causal_identity(self) -> None:
        evidence = EvidenceBuilder.observation_to_evidence(self._observation())
        payload = evidence.model_dump()

        self.assertEqual(
            "EXEC-CANONICAL-001",
            payload.get("execution_id"),
            "STILL_PRESENT: Observation -> Evidence loses exact execution provenance.",
        )
        self.assertEqual(
            "AI-CANONICAL-001",
            payload.get("action_intent_id"),
            "STILL_PRESENT: Observation -> Evidence loses exact ActionIntent provenance.",
        )

    def test_legacy_observation_preserves_execution_without_fabricating_action_intent(self) -> None:
        evidence = EvidenceBuilder.observation_to_evidence(
            self._observation(
                execution_id="EXEC-LEGACY-001",
                action_intent_id=None,
            )
        )
        payload = evidence.model_dump()

        self.assertEqual(
            "EXEC-LEGACY-001",
            payload.get("execution_id"),
            "STILL_PRESENT: legacy evidence loses its actual execution provenance.",
        )
        self.assertIsNone(
            payload.get("action_intent_id"),
            "REGRESSION: legacy Observation -> Evidence must not fabricate Brain provenance.",
        )

    def test_builder_does_not_generate_causal_identity_for_unbound_observation(self) -> None:
        evidence = EvidenceBuilder.observation_to_evidence(
            self._observation(execution_id="", action_intent_id=None)
        )
        payload = evidence.model_dump()

        self.assertEqual(
            "",
            payload.get("execution_id"),
            "REGRESSION: EvidenceBuilder must not generate an execution identity.",
        )
        self.assertIsNone(
            payload.get("action_intent_id"),
            "REGRESSION: EvidenceBuilder must not generate Brain ActionIntent provenance.",
        )

    def test_untrusted_normalized_metadata_cannot_replace_observation_provenance(self) -> None:
        evidence = EvidenceBuilder.observation_to_evidence(
            self._observation(
                normalized_data={
                    "execution_id": "EXEC-PAYLOAD-FORGED",
                    "action_intent_id": "AI-PAYLOAD-FORGED",
                    "search_results": {"results": []},
                }
            )
        )
        payload = evidence.model_dump()

        self.assertEqual("EXEC-CANONICAL-001", payload.get("execution_id"))
        self.assertEqual("AI-CANONICAL-001", payload.get("action_intent_id"))
        self.assertNotEqual("EXEC-PAYLOAD-FORGED", payload.get("execution_id"))
        self.assertNotEqual("AI-PAYLOAD-FORGED", payload.get("action_intent_id"))

    def test_evidence_round_trip_preserves_causal_identity(self) -> None:
        evidence = EvidenceBuilder.observation_to_evidence(self._observation())
        restored = EvidenceItem(**evidence.model_dump())
        payload = restored.model_dump()

        self.assertEqual("EXEC-CANONICAL-001", payload.get("execution_id"))
        self.assertEqual("AI-CANONICAL-001", payload.get("action_intent_id"))


if __name__ == "__main__":
    unittest.main()
