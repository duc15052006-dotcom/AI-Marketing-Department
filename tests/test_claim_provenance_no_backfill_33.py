"""Adversarial regressions for claim-evidence provenance scope laundering.

The claim gate must never manufacture source provenance from the active run.
Only provenance explicitly carried by the evidence itself may authorize a
scoped factual claim. An explicit GLOBAL source remains valid, while an
explicit SCOPE_<business> declaration may establish tenant scope without
requiring duplicate tenant metadata.
"""

import unittest

from runtime.claim_verification import MockClaimVerifier, SemanticScores
from runtime.context import RuntimeContext
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestClaimProvenanceNoBackfill(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = MockClaimVerifier(
            default_semantic_scores=SemanticScores(
                p_entailment=0.99,
                p_neutral=0.005,
                p_contradiction=0.005,
                argmax_label="ENTAILMENT",
            )
        )
        self.runtime = FiveAgentDepartmentRuntime(
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
            claim_verifier=self.verifier,
        )
        self.context = RuntimeContext(
            objective="Verify product facts",
            business_id="BIZ_ALPHA",
            project_id="PROJ_ALPHA",
            chat_id="CHAT_ALPHA",
        )

    def _scan(self, source: dict):
        source_id = source["source_id"]
        claim = f"Device battery capacity is 5000mAh (Source: {source_id})."
        return self.runtime._scan_unsupported_product_claims(
            corpus_text=claim,
            provenance_index={source_id: source},
            context=self.context,
            claim_verifier=self.verifier,
        )

    @staticmethod
    def _source(source_id: str, *, scope_marker=object()) -> dict:
        source = {
            "source_id": source_id,
            "epistemic_tier": "VERIFIED_SOURCE",
            "source_type": "CANONICAL_FACT",
            "content": "Device battery capacity is 5000mAh.",
            "metadata": {"authority": "TIER_1"},
        }
        if not isinstance(scope_marker, object) or type(scope_marker) is not object:
            source["scope"] = scope_marker
        return source

    def test_session_scoped_source_missing_tenant_is_not_backfilled_from_run(self) -> None:
        source = self._source("SRC_SESSION", scope_marker="SESSION_CHAT_ALPHA")
        total, supported, hypotheses, reasons, actions = self._scan(source)

        self.assertEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertEqual(hypotheses, 0)
        self.assertEqual(actions["claim_1"], "BLOCK_PUBLICATION")
        self.assertTrue(any("SECURITY_SCOPE" in reason or "SCOPE_VIOLATION" in reason for reason in reasons))

    def test_missing_scope_is_not_implicitly_promoted_to_global(self) -> None:
        source = {
            "source_id": "SRC_NO_SCOPE",
            "epistemic_tier": "VERIFIED_SOURCE",
            "source_type": "CANONICAL_FACT",
            "content": "Device battery capacity is 5000mAh.",
            "metadata": {"authority": "TIER_1"},
        }
        total, supported, hypotheses, reasons, actions = self._scan(source)

        self.assertEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertEqual(hypotheses, 0)
        self.assertEqual(actions["claim_1"], "BLOCK_PUBLICATION")
        self.assertTrue(any("SECURITY_SCOPE" in reason or "SCOPE_VIOLATION" in reason for reason in reasons))

    def test_explicit_business_scope_remains_authorizable_without_duplicate_tenant_metadata(self) -> None:
        source = self._source("SRC_BUSINESS", scope_marker="SCOPE_BIZ_ALPHA")
        total, supported, hypotheses, reasons, actions = self._scan(source)

        self.assertEqual(total, 1)
        self.assertEqual(supported, 1)
        self.assertEqual(hypotheses, 0)
        self.assertEqual(reasons, [])
        self.assertEqual(actions["claim_1"], "AUTHORIZE")

    def test_explicit_global_source_remains_authorizable(self) -> None:
        source = self._source("SRC_GLOBAL", scope_marker="GLOBAL")
        total, supported, hypotheses, reasons, actions = self._scan(source)

        self.assertEqual(total, 1)
        self.assertEqual(supported, 1)
        self.assertEqual(hypotheses, 0)
        self.assertEqual(reasons, [])
        self.assertEqual(actions["claim_1"], "AUTHORIZE")


if __name__ == "__main__":
    unittest.main()
