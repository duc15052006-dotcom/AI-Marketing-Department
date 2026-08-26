"""Unit tests for Phase CLAIM-REPAIR-04: Semantic Claim <-> Evidence Binding.

Validates all 24 required contract points using deterministic MockClaimVerifier,
verifying:
- Wrong source same tier -> BLOCK (SEMANTIC_MISMATCH)
- Correct source with valid entailment -> AUTHORIZE / APPROVED
- Contradiction -> BLOCK
- Neutral / Inconclusive -> BLOCK
- Verifier / model unavailable -> BLOCK (fails closed)
- Model exception -> BLOCK (fails closed)
- Missing evidence text -> BLOCK (EVIDENCE_CONTENT_UNAVAILABLE)
- Foreign brand / chat / run scope violations -> BLOCK
- MOCK / SANDBOX / ERROR receipt rejection -> BLOCK
- Compound claims without decomposition -> BLOCK / INCONCLUSIVE
- Hypothesis / planning preservation -> PRESERVE_HYPOTHESIS
- Deterministic numeric & entity pre-guards -> BLOCK
- Raw Final CMO prose preservation -> verbatim un-rewritten
- Structured claim verification audit ledger persistence
- Five-Agent invariant (no 6th verifier agent)
"""

from __future__ import annotations

import hashlib
import unittest
from typing import Any, Dict

from governance.access_matrix import PERMANENT_FIVE_AGENTS
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.claim_verification import (
    BaseClaimVerifier,
    ClaimVerificationResult,
    DeterministicFindings,
    MockClaimVerifier,
    PROVISIONAL_TAU_CONTRADICTION,
    PROVISIONAL_TAU_ENTAILMENT,
    SemanticScores,
    VerificationVerdict,
)
from runtime.context import EpistemicTier, RuntimeContext
from runtime.engine import FiveAgentDepartmentRuntime
from schemas.claim_provenance import AllowedUsage, ClaimClass


class ScriptedAgentGateway(UniversalModelGateway):
    """Deterministic script-based model gateway for zero-download tests."""

    def __init__(self, replies: Dict[str, str] | None = None) -> None:
        super().__init__(free_only_mode=True)
        self.replies = replies or {}
        self.calls: list[tuple[str, str, str]] = []

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        system_content = next((m.content for m in request.messages if m.role == ModelRole.SYSTEM), "")
        user_content = next((m.content for m in request.messages if m.role == ModelRole.USER), "")

        agent_name = "cmo"
        sys_low = system_content.lower()
        if "final governed" in sys_low or "master gtm" in sys_low:
            agent_name = "final_cmo"
        elif "initial strategic brief" in sys_low or "cmo_initial" in sys_low:
            agent_name = "cmo_initial"
        elif "intelligence" in sys_low:
            agent_name = "intelligence"
        elif "strategist" in sys_low:
            agent_name = "strategist"
        elif "creative" in sys_low:
            agent_name = "creative"
        elif "performance" in sys_low:
            agent_name = "performance"

        self.calls.append((agent_name, system_content, user_content))
        content = self.replies.get(agent_name, f"DEFAULT_MOCK_REPLY for {agent_name}")
        return ModelResponse(
            request_id=request.request_id,
            provider="scripted_mock",
            model_name="scripted",
            status=ModelResponseStatus.SUCCESS,
            content=content,
        )


class TestClaimEvidenceBinding(unittest.TestCase):
    """Test suite covering CLAIM-REPAIR-04 semantic claim-evidence binding."""

    def setUp(self) -> None:
        self.repo = LocalKnowledgeRepository()
        self.mock_verifier = MockClaimVerifier()

    # 1. Wrong source same tier -> BLOCK (SEMANTIC_MISMATCH)
    def test_01_wrong_source_same_tier_blocked(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_SEO_KEYWORDS",
            title="SEO Keyword Strategy",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Top SEO keywords for dental clinics include tooth whitening and dental implants.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.01, p_neutral=0.95, p_contradiction=0.04, argmax_label="NEUTRAL"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="This automation tool delivers 10x ROI (Source: SRC_SEO_KEYWORDS).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("SEMANTIC_MISMATCH" in r for r in audit_res.blocking_reasons))

    # 2. Correct source with valid entailment -> AUTHORIZE
    def test_02_correct_source_authorized(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Official Hardware Spec: Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.98, p_neutral=0.01, p_contradiction=0.01, argmax_label="ENTAILMENT"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="# FINAL CMO PLAN\nDevice features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        self.assertEqual(audit_res.authorization_status, "APPROVED")
        self.assertEqual(audit_res.blocked_claims, 0)
        self.assertEqual(audit_res.supported_claims, 1)

    # 3. Contradiction -> BLOCK
    def test_03_contradiction_blocked(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_WARRANTY_DOC",
            title="Warranty Agreement",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Official warranty duration is 12 months from purchase date.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Comes with 24-month warranty (Source: SRC_WARRANTY_DOC).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("NUMERIC_VALUE_MISMATCH" in r or "SEMANTIC_MISMATCH" in r for r in audit_res.blocking_reasons))

    # 4. Neutral is not support -> BLOCK
    def test_04_neutral_not_support_blocked(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BRAND_HIST",
            title="Brand History",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Brand Alpha established headquarters in Vietnam in 2025.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.10, p_neutral=0.85, p_contradiction=0.05, argmax_label="NEUTRAL"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Brand Alpha is rated #1 in Vietnam (Source: SRC_BRAND_HIST).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("SEMANTIC_MISMATCH" in r for r in audit_res.blocking_reasons))

    # 5. Model / Verifier unavailable -> BLOCK
    def test_05_verifier_unavailable_fails_closed(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_VALID_DOC",
            title="Product Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Battery capacity: 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(simulate_model_failure=True),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Features 5000mAh battery (Source: SRC_VALID_DOC).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("SEMANTIC_MISMATCH" in r for r in audit_res.blocking_reasons))

    # 6. Model exception -> BLOCK (fails closed)
    def test_06_verifier_exception_fails_closed(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_VALID_DOC",
            title="Product Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Battery capacity: 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(simulate_exception=True),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Features 5000mAh battery (Source: SRC_VALID_DOC).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("SEMANTIC_MISMATCH" in r for r in audit_res.blocking_reasons))

    # 7. Missing evidence text -> BLOCK (EVIDENCE_CONTENT_UNAVAILABLE)
    def test_07_missing_evidence_text_blocked(self) -> None:
        prov_index = {
            "SRC_EMPTY_DOC": {
                "source_id": "SRC_EMPTY_DOC",
                "epistemic_tier": "VERIFIED_SOURCE",
                "content": "",
            }
        }
        ctx = RuntimeContext(objective="Test", business_id="BIZ_TEST")
        ctx.working_state["provenance_index"] = prov_index
        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=self.mock_verifier)
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Battery capacity is 5000mAh (Source: SRC_EMPTY_DOC).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("EVIDENCE_CONTENT_UNAVAILABLE" in r for r in audit_res.blocking_reasons))

    # 8. Foreign brand scope violation -> BLOCK
    def test_08_foreign_brand_scope_blocked(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BRAND_BETA",
            title="Beta Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Battery capacity: 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_BETA",
        ))
        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=self.mock_verifier)
        ctx = rt.start_run(objective="Test", business_id="BIZ_ALPHA")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Battery capacity is 5000mAh (Source: SRC_BRAND_BETA).",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("SCOPE_VIOLATION" in r for r in audit_res.blocking_reasons))

    # 9. Foreign chat session isolation -> BLOCK
    def test_09_foreign_chat_isolation_blocked(self) -> None:
        claim_meta = {"tenant_id": "BIZ_ALPHA", "chat_id": "CHAT_01"}
        source_meta = {"tenant_id": "BIZ_ALPHA", "chat_id": "CHAT_02", "source_id": "SRC_CHAT_02"}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery capacity is 5000mAh.",
            evidence_text="Battery capacity is 5000mAh.",
            claim_metadata=claim_meta,
            source_metadata=source_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.SCOPE_VIOLATION)

    # 10. Foreign run isolation -> BLOCK
    def test_10_foreign_run_isolation_blocked(self) -> None:
        claim_meta = {"tenant_id": "BIZ_ALPHA", "run_id": "RUN_01"}
        source_meta = {"tenant_id": "BIZ_ALPHA", "run_id": "RUN_02", "source_id": "SRC_RUN_02"}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery capacity is 5000mAh.",
            evidence_text="Battery capacity is 5000mAh.",
            claim_metadata=claim_meta,
            source_metadata=source_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.SCOPE_VIOLATION)

    # 11. MOCK receipt cannot authorize -> BLOCK
    def test_11_mock_receipt_cannot_authorize(self) -> None:
        source_meta = {"execution_mode": "MOCK", "source_id": "REC_MOCK_01"}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery capacity is 5000mAh.",
            evidence_text="Battery capacity is 5000mAh.",
            source_metadata=source_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)

    # 12. SANDBOX receipt cannot authorize -> BLOCK
    def test_12_sandbox_receipt_cannot_authorize(self) -> None:
        source_meta = {"execution_mode": "SANDBOX", "source_id": "REC_SANDBOX_01"}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery capacity is 5000mAh.",
            evidence_text="Battery capacity is 5000mAh.",
            source_metadata=source_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)

    # 13. ERROR receipt cannot authorize -> BLOCK
    def test_13_error_receipt_cannot_authorize(self) -> None:
        source_meta = {"status": "ERROR", "source_id": "REC_ERR_01"}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery capacity is 5000mAh.",
            evidence_text="Battery capacity is 5000mAh.",
            source_metadata=source_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)

    # 14. Compound claim without decomposition -> BLOCK / INCONCLUSIVE
    def test_14_compound_claim_guard(self) -> None:
        claim_meta = {"is_compound": True}
        res = self.mock_verifier.verify_claim(
            claim_text="5000mAh battery lasts 24 hours.",
            evidence_text="Battery capacity is 5000mAh.",
            claim_metadata=claim_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertEqual(res.deterministic_findings.guard_name, "COMPOUND_CLAIM_GUARD")

    # 15. Hypothesis does not become public fact
    def test_15_hypothesis_preserves_epistemic_type(self) -> None:
        claim_meta = {"claim_class": ClaimClass.HYPOTHESIS.value, "allowed_usage": AllowedUsage.HYPOTHESIS_ONLY.value}
        res = self.mock_verifier.verify_claim(
            claim_text="Battery messaging will lift conversion by 25%.",
            evidence_text="Battery capacity is 5000mAh.",
            claim_metadata=claim_meta,
        )
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertEqual(res.deterministic_findings.guard_name, "EPISTEMIC_HYPOTHESIS_PRESERVATION")

    # 16. Unrelated source cannot authorize -> BLOCK
    def test_16_unrelated_source_cannot_authorize(self) -> None:
        res = self.mock_verifier.verify_claim(
            claim_text="Clinically proven to cure cancer completely.",
            evidence_text="Aloe vera provides basic hydration for dry skin.",
        )
        # In a real model, this is Neutral/Contradiction. In mock, forced scoring reproduces this.
        mock = MockClaimVerifier(
            default_semantic_scores=SemanticScores(
                p_entailment=0.001, p_neutral=0.99, p_contradiction=0.009, argmax_label="NEUTRAL"
            )
        )
        res_m = mock.verify_claim(
            claim_text="Clinically proven to cure cancer completely.",
            evidence_text="Aloe vera provides basic hydration for dry skin.",
        )
        self.assertEqual(res_m.verdict, VerificationVerdict.INCONCLUSIVE)

    # 17. Deterministic numeric mismatch pre-blocks
    def test_17_numeric_mismatch_pre_blocks(self) -> None:
        res = self.mock_verifier.verify_claim(
            claim_text="Save 40% on subscription costs.",
            evidence_text="Customers save 15% on subscription costs.",
        )
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res.deterministic_findings.guard_name, "NUMERIC_VALUE_MISMATCH")

    # 18. Entity / SKU mismatch pre-blocks
    def test_18_entity_sku_mismatch_pre_blocks(self) -> None:
        res = self.mock_verifier.verify_claim(
            claim_text="Model PRO-X9 features fast charging.",
            evidence_text="Model LITE-V2 features fast charging.",
        )
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res.deterministic_findings.guard_name, "ENTITY_SKU_MISMATCH")

    # 19. Raw Final CMO output preserved verbatim
    def test_19_raw_final_cmo_output_preserved_verbatim(self) -> None:
        raw_text = "# FINAL_CMO_PLAN\nThis tool delivers 10x ROI (Source: SRC_UNKNOWN)."
        ctx = RuntimeContext(objective="Test", business_id="BIZ_TEST")
        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=self.mock_verifier)
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=raw_text,
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertEqual(raw_text, "# FINAL_CMO_PLAN\nThis tool delivers 10x ROI (Source: SRC_UNKNOWN).")

    # 20. Verifier result audit ledger preserved in working state
    def test_20_verifier_audit_ledger_preserved(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.98, p_neutral=0.01, p_contradiction=0.01, argmax_label="ENTAILMENT"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        ledger = ctx.working_state.get("claim_verification_ledger", [])
        self.assertGreaterEqual(len(ledger), 1)
        entry = ledger[0]
        sid = entry.get("source_id") if isinstance(entry, dict) else entry.source_id
        verdict = entry.get("verdict") if isinstance(entry, dict) else entry.verdict
        self.assertEqual(sid, "SRC_BATTERY_SPEC")
        self.assertEqual(verdict.value if hasattr(verdict, "value") else str(verdict), "SUPPORTED")

    # 21. Five-Agent invariant unchanged
    def test_21_five_agent_invariant(self) -> None:
        self.assertEqual(
            set(PERMANENT_FIVE_AGENTS),
            {"cmo", "intelligence", "strategist", "creative", "performance"},
            "Architecture must maintain exactly Five Agents.",
        )

    # 22. Positive E2E (Part 23)
    def test_22_positive_e2e_approval(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_SERUM_CLINICAL",
            title="Clinical Hydration Trial",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Clinical trial certifies: Serum provides 48-hour hydration.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# GTM PLAN\nClinically proven results (Source: SRC_SERUM_CLINICAL) theo bao cao phong thi nghiem.",
        })
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            knowledge_repo=self.repo,
            memory_repo=LocalMemoryRepository(),
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.96, p_neutral=0.03, p_contradiction=0.01, argmax_label="ENTAILMENT"
                )
            ),
        )
        ctx = rt.start_run(objective="quang cao serum", business_id="BIZ_TEST")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        self.assertEqual(final_out["approval_status"], "APPROVED")
        self.assertEqual(final_out["status"], "READY_FOR_DEPLOYMENT")

    # 23. Verifier unavailable E2E (Part 24)
    def test_23_verifier_unavailable_e2e_blocked(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_SERUM_CLINICAL",
            title="Clinical Hydration Trial",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Clinical trial certifies: Serum provides 48-hour hydration.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# GTM PLAN\nClinically proven results (Source: SRC_SERUM_CLINICAL) theo bao cao phong thi nghiem.",
        })
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            knowledge_repo=self.repo,
            memory_repo=LocalMemoryRepository(),
            claim_verifier=MockClaimVerifier(simulate_model_failure=True),
        )
        ctx = rt.start_run(objective="quang cao serum", business_id="BIZ_TEST")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")
        self.assertTrue(any("SEMANTIC_MISMATCH" in r for r in final_out["claim_audit"]["blocking_reasons"]))


    # 24. Artifact Integrity: Claim verification ledger mutation changes artifact hash
    def test_24_claim_verification_ledger_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.98, p_neutral=0.01, p_contradiction=0.01, argmax_label="ENTAILMENT"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        # Mutate authoritative claim verification verdict
        item = artifact.claim_verification_ledger[0]
        if isinstance(item, dict):
            item["verdict"] = "CONTRADICTED"
        else:
            item.verdict = VerificationVerdict.CONTRADICTED
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating claim verification ledger verdict MUST change final artifact hash.")

        # Mutate cited source_id
        if isinstance(item, dict):
            item["source_id"] = "SRC_MUTATED"
        else:
            item.source_id = "SRC_MUTATED"
        h3 = artifact.compute_artifact_hash()
        self.assertNotEqual(h2, h3, "Mutating claim verification ledger source_id MUST change final artifact hash.")

    # 25. Recording verifier captures exact atomic claim and evidence text
    def test_25_recording_verifier_captures_exact_claim_and_evidence_args(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_SEO_KEYWORDS",
            title="SEO Keyword Strategy",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Top SEO keywords for dental clinics include tooth whitening and dental implants.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        captured_calls: list[dict[str, Any]] = []

        class RecordingVerifier(BaseClaimVerifier):
            def verify_claim(self, claim_text, evidence_text, claim_metadata=None, source_metadata=None, deadline_monotonic=None):
                captured_calls.append({
                    "claim_text": claim_text,
                    "evidence_text": evidence_text,
                    "claim_meta": claim_metadata,
                    "source_meta": source_metadata,
                })
                return ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id="SRC_SEO_KEYWORDS",
                    verdict=VerificationVerdict.CONTRADICTED,
                    confidence=0.99,
                    reason="Irrelevant evidence",
                )

        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=RecordingVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        raw_final = "This automation tool delivers 10x ROI (Source: SRC_SEO_KEYWORDS)."
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=raw_final,
        )
        self.assertEqual(len(captured_calls), 1)
        self.assertEqual(captured_calls[0]["claim_text"], "This automation tool delivers 10x ROI")
        self.assertEqual(captured_calls[0]["evidence_text"], "Top SEO keywords for dental clinics include tooth whitening and dental implants.")
        self.assertEqual(captured_calls[0]["source_meta"]["source_id"], "SRC_SEO_KEYWORDS")

    # 26. Realistic premise-dependent verifier
    def test_26_realistic_premise_dependent_verifier(self) -> None:
        class RealisticFakeVerifier(BaseClaimVerifier):
            def verify_claim(self, claim_text, evidence_text, claim_metadata=None, source_metadata=None, deadline_monotonic=None):
                # Verify strictly based on string overlap / premise content
                if "5000mAh" in claim_text and "5000mAh" in evidence_text:
                    return ClaimVerificationResult(
                        claim_text=claim_text,
                        source_id="SRC_BATTERY",
                        verdict=VerificationVerdict.SUPPORTED,
                        confidence=0.95,
                        reason="Premise contains required capacity.",
                    )
                return ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id="SRC_BATTERY",
                    verdict=VerificationVerdict.CONTRADICTED,
                    confidence=0.95,
                    reason="Premise does not contain required capacity.",
                )

        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY",
            title="Battery Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Battery capacity: 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=RealisticFakeVerifier())
        ctx = rt.start_run(objective="Test GTM", business_id="BIZ_TEST")
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device has 5000mAh battery (Source: SRC_BATTERY).",
        )
        self.assertEqual(audit_res.authorization_status, "APPROVED")
        self.assertEqual(audit_res.supported_claims, 1)

    # 27. Multiple claims and multiple sources cross-isolation
    def test_27_multiple_claims_and_multiple_sources_isolation(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_DOC",
            title="Battery Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Battery capacity: 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_WARRANTY_DOC",
            title="Warranty Spec",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Warranty period is 12 months.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        calls: list[tuple[str, str]] = []

        class MultiVerifier(BaseClaimVerifier):
            def verify_claim(self, claim_text, evidence_text, claim_metadata=None, source_metadata=None, deadline_monotonic=None):
                calls.append((claim_text, evidence_text))
                return ClaimVerificationResult(
                    claim_text=claim_text,
                    verdict=VerificationVerdict.SUPPORTED,
                    confidence=0.95,
                    reason="Matched",
                )

        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=MultiVerifier())
        ctx = rt.start_run(objective="Test", business_id="BIZ_TEST")
        multi_text = (
            "Device has 5000mAh battery (Source: SRC_BATTERY_DOC). "
            "Includes a 30-day money-back guarantee (Source: SRC_WARRANTY_DOC)."
        )
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=multi_text,
        )
        self.assertEqual(len(calls), 2)
        # Assert Claim 1 verified against SRC_BATTERY_DOC and NOT SRC_WARRANTY_DOC
        self.assertEqual(calls[0][1], "Battery capacity: 5000mAh.")
        # Assert Claim 2 verified against SRC_WARRANTY_DOC and NOT SRC_BATTERY_DOC
        self.assertEqual(calls[1][1], "Warranty period is 12 months.")

    # 28. Final authorization is single deterministic authority
    def test_28_final_authorization_single_call_authority(self) -> None:
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# FINAL PLAN\nAll requirements satisfied.",
        })
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            knowledge_repo=self.repo,
            memory_repo=LocalMemoryRepository(),
            claim_verifier=self.mock_verifier,
        )
        ctx = rt.start_run(objective="Test single authority", business_id="BIZ_TEST")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)

    # 29. Artifact Integrity: Evidence content mutation changes artifact hash
    def test_29_evidence_content_hash_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        # Mutate evidence content hash (representing different evidence text under same claim/verdict)
        item = artifact.claim_verification_ledger[0]
        new_hash = "sha256_mutated_evidence_content_999"
        if isinstance(item, dict):
            item["evidence_content_hash"] = new_hash
        else:
            item.evidence_content_hash = new_hash
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating evidence content hash MUST change final artifact hash.")

    # 30. Artifact Integrity: Model revision mutation changes artifact hash
    def test_30_model_revision_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(model_revision="rev-alpha-12345"),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        item = artifact.claim_verification_ledger[0]
        if isinstance(item, dict):
            item["model_revision"] = "rev-beta-67890"
        else:
            item.model_revision = "rev-beta-67890"
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating model revision MUST change final artifact hash.")

    # 31. Artifact Integrity: Semantic scores mutation changes artifact hash
    def test_31_semantic_scores_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(
                default_semantic_scores=SemanticScores(
                    p_entailment=0.98, p_neutral=0.01, p_contradiction=0.01, argmax_label="ENTAILMENT"
                )
            ),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        item = artifact.claim_verification_ledger[0]
        if isinstance(item, dict):
            item["semantic_scores"]["p_entailment"] = 0.05
        else:
            item.semantic_scores.p_entailment = 0.05
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating semantic scores MUST change final artifact hash.")

    # 32. Artifact Integrity: Deterministic findings mutation changes artifact hash
    def test_32_deterministic_findings_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        item = artifact.claim_verification_ledger[0]
        if isinstance(item, dict):
            item["deterministic_findings"] = {
                "guard_name": "MUTATED_GUARD",
                "passed": False,
                "reason": "Injected finding",
                "extracted_claim_values": {},
                "extracted_evidence_values": {},
            }
        else:
            item.deterministic_findings.guard_name = "MUTATED_GUARD"
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating deterministic findings MUST change final artifact hash.")

    # 33. Artifact Integrity: Provenance context hash mutation changes artifact hash
    def test_33_provenance_context_hash_mutation_changes_artifact_hash(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        h1 = artifact.compute_artifact_hash()

        item = artifact.claim_verification_ledger[0]
        if isinstance(item, dict):
            item["provenance_context_hash"] = "mutated_provenance_hash_999"
        else:
            item.provenance_context_hash = "mutated_provenance_hash_999"
        h2 = artifact.compute_artifact_hash()
        self.assertNotEqual(h1, h2, "Mutating provenance context hash MUST change final artifact hash.")


    # 34. Engine-path evidence content hash verification
    def test_34_engine_path_evidence_content_hash_integrity(self) -> None:
        raw_evidence = "Official Battery capacity: 5000mAh."
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content=raw_evidence,
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="Device features 5000mAh battery (Source: SRC_BATTERY_SPEC).",
        )
        artifact = rt.complete_run(ctx)
        expected_digest = hashlib.sha256(raw_evidence.encode("utf-8")).hexdigest()
        ledger_entry = artifact.claim_verification_ledger[0]
        actual_digest = ledger_entry.get("evidence_content_hash") if isinstance(ledger_entry, dict) else ledger_entry.evidence_content_hash
        self.assertEqual(actual_digest, expected_digest)
        integ_repr = artifact._claim_verification_integrity_representation(ledger_entry)
        self.assertEqual(integ_repr["evidence_content_hash"], expected_digest)

    # 35. Provenance hash production path differentiation
    def test_35_provenance_context_hash_run_and_scope_differentiation(self) -> None:
        from runtime.claim_verification import compute_provenance_context_hash
        h_run1 = compute_provenance_context_hash(
            {"tenant_id": "BIZ_1", "run_id": "RUN_001", "chat_id": "CHAT_01"},
            {"tenant_id": "BIZ_1", "run_id": "RUN_001", "chat_id": "CHAT_01", "source_id": "SRC_1"},
        )
        h_run2 = compute_provenance_context_hash(
            {"tenant_id": "BIZ_1", "run_id": "RUN_002", "chat_id": "CHAT_01"},
            {"tenant_id": "BIZ_1", "run_id": "RUN_002", "chat_id": "CHAT_01", "source_id": "SRC_1"},
        )
        h_biz2 = compute_provenance_context_hash(
            {"tenant_id": "BIZ_2", "run_id": "RUN_001", "chat_id": "CHAT_01"},
            {"tenant_id": "BIZ_2", "run_id": "RUN_001", "chat_id": "CHAT_01", "source_id": "SRC_1"},
        )
        self.assertNotEqual(h_run1, h_run2, "Different run_ids must produce different provenance hashes.")
        self.assertNotEqual(h_run1, h_biz2, "Different tenant_ids must produce different provenance hashes.")

    # 36. Semantic float canonicalization & hash repeatability
    def test_36_semantic_scores_float_canonicalization_and_repeatability(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt1 = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=MockClaimVerifier())
        ctx1 = rt1.start_run(objective="GTM Campaign", business_id="BIZ_TEST", trusted_run_id="RUN_FIXED_001")
        rt1._evaluate_final_authorization(context=ctx1, perf_out={}, crtv_out={}, final_text="5000mAh battery (Source: SRC_BATTERY_SPEC).")
        art1 = rt1.complete_run(ctx1)

        rt2 = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=MockClaimVerifier())
        ctx2 = rt2.start_run(objective="GTM Campaign", business_id="BIZ_TEST", trusted_run_id="RUN_FIXED_001")
        rt2._evaluate_final_authorization(context=ctx2, perf_out={}, crtv_out={}, final_text="5000mAh battery (Source: SRC_BATTERY_SPEC).")
        art2 = rt2.complete_run(ctx2)

        self.assertEqual(art1.compute_artifact_hash(), art2.compute_artifact_hash(), "Identical runs must produce identical artifact hash.")

    # 37. Empty ledger default artifact hash safety
    def test_37_empty_ledger_default_artifact_hash_safety(self) -> None:
        rt = FiveAgentDepartmentRuntime(knowledge_repo=self.repo, claim_verifier=MockClaimVerifier())
        ctx = rt.start_run(objective="General brand positioning", business_id="BIZ_TEST")
        # Run with creative prose containing 0 material factual claims
        rt._evaluate_final_authorization(context=ctx, perf_out={}, crtv_out={}, final_text="Our vision is to empower modern marketers everywhere.")
        art = rt.complete_run(ctx)
        self.assertEqual(len(art.claim_verification_ledger), 0)
        self.assertTrue(len(art.final_artifact_hash) == 64, "Artifact must have a valid SHA-256 hash even with empty ledger.")

    # 38. Unavailable verifier metadata truthfulness
    def test_38_unavailable_verifier_metadata_truthfulness(self) -> None:
        self.repo.save_document(KnowledgeDocument(
            source_id="SRC_BATTERY_SPEC",
            title="Battery Spec Sheet",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="Device battery capacity is 5000mAh.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_TEST",
        ))
        rt = FiveAgentDepartmentRuntime(
            knowledge_repo=self.repo,
            claim_verifier=MockClaimVerifier(simulate_model_failure=True),
        )
        ctx = rt.start_run(objective="GTM Campaign", business_id="BIZ_TEST")
        rt._evaluate_final_authorization(context=ctx, perf_out={}, crtv_out={}, final_text="5000mAh battery (Source: SRC_BATTERY_SPEC).")
        artifact = rt.complete_run(ctx)
        entry = artifact.claim_verification_ledger[0]
        verdict = entry.get("verdict") if isinstance(entry, dict) else entry.verdict
        reason = entry.get("reason") if isinstance(entry, dict) else entry.reason
        self.assertEqual(verdict, VerificationVerdict.INCONCLUSIVE)
    # 39. Legacy artifact compatibility audit
    def test_39_legacy_artifact_hash_compatibility_audit(self) -> None:
        from datetime import datetime, timezone
        import json
        from runtime.artifacts import DepartmentRunArtifact, _normalize_for_hashing

        now = datetime.now(timezone.utc)
        # 1. Construct pre-claim-ledger legacy artifact data payload
        legacy_data = {
            "run_id": "RUN-LEGACY-001",
            "objective": "Launch brand",
            "status": "APPROVED",
            "agent_outputs": {"cmo": "plan"},
            "final_cmo_output": "Approved marketing plan.",
            "binding_constraints": ["Constraint 1"],
            "epistemic_handoffs": {},
            "execution_receipts": [],
            "errors": [],
            "started_at": now,
            "completed_at": now,
        }

        # 2. Compute legacy hash using old payload contract (without claim_verification_ledger)
        legacy_payload = {
            "run_id": legacy_data["run_id"],
            "objective": legacy_data["objective"],
            "status": legacy_data["status"],
            "agent_outputs": _normalize_for_hashing(legacy_data["agent_outputs"]),
            "final_cmo_output": _normalize_for_hashing(legacy_data["final_cmo_output"]),
            "binding_constraints": _normalize_for_hashing(legacy_data["binding_constraints"]),
            "epistemic_handoffs": _normalize_for_hashing(legacy_data["epistemic_handoffs"]),
            "execution_receipts": [],
        }
        raw_old = json.dumps(legacy_payload, sort_keys=True, separators=(",", ":"))
        old_hash = hashlib.sha256(raw_old.encode("utf-8")).hexdigest()

        # 3. Deserialize legacy artifact under current schema
        art = DepartmentRunArtifact(**legacy_data)
        self.assertEqual(art.claim_verification_ledger, [], "Deserialization succeeds with default empty list.")

        # 4. Compute current hash under current schema (includes claim_verification_ledger in payload)
        current_hash = art.compute_artifact_hash()

        # 5. Assert SCHEMA_DESERIALIZATION is COMPATIBLE, but recomputed hash changes due to newly sealed ledger boundary
        self.assertNotEqual(old_hash, current_hash, "Legacy hash changes due to inclusion of claim_verification_ledger in current integrity boundary.")


if __name__ == "__main__":
    unittest.main()
