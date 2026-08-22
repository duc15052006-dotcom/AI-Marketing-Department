"""COLLAB-01 — Five-Agent Collaboration Integrity Audit (AUDIT ONLY).

Probes the ACTIVE production collaboration path:
    app_api/server.py -> FiveAgentDepartmentRuntime (runtime/engine.py)
        CMO Initial -> Intelligence -> Strategist -> Creative -> Performance
        -> Final CMO -> complete_run

Rules honored:
- Uses the REAL production runtime/handoff code. Mocks control ONLY model
  outputs (scripted replies per agent stage); they never bypass
  RuntimeContext / stage_outputs handoffs.
- Desired collaboration contracts that are currently BROKEN are left
  FAILING deliberately (audit evidence). Do not "fix" assertions to match
  defective behavior; defects are repaired in a later phase.

Audit contracts:
  A. Intelligence UNKNOWN text is preserved verbatim to Strategist (no engine
     escalation UNKNOWN->FACT).
  B. Intelligence tool receipt/source ID remains traceable downstream.
  C. Strategist structured output fields must derive from actual analysis,
     not be hardcoded templates injected by the engine.
  D. Creative unsupported product claims must be flagged/rejected downstream.
  E. Performance INCONCLUSIVE -> Final CMO must NOT auto-approve/declare winner.
  F. Performance failure -> Final CMO must fail closed (no fake GO/success).
  G. Stage failure propagates as PREVIOUS_STAGE_FAILED to downstream stages.
  H. MOCK tool receipt must stay MOCK_OR_SANDBOX (never VERIFIED_SOURCE).
  I. FAILED tool receipt must produce zero positive evidence.
  J. Original raw user objective remains accessible to Final CMO.
  K. CMO/context restrictions must reach Creative prompts. (Currently broken.)
  L. Knowledge scoping prevents cross-business contamination.
"""

import unittest

from chat.knowledge import SessionKnowledgeStore
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from governance.access_matrix import AgentAccessMatrix
from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.context import EpistemicTier, RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.context_compiler import ContextCompiler
from runtime.engine import (
    FiveAgentDepartmentRuntime,
    extract_explicit_user_constraints,
    record_constraint,
)
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class ScriptedAgentGateway(UniversalModelGateway):
    """Mock gateway that scripts replies PER AGENT STAGE and records prompts.

    Stage identification uses only the production system-prompt markers, so
    the production handoff mechanism (stage_outputs -> prompt interpolation)
    is exercised unmodified.
    """

    MARKERS = [
        ("final_cmo", "Final Governed Go-To-Market"),
        ("performance", "Performance Marketing & Analytics Director"),
        ("creative", "Creative Director"),
        ("strategist", "Marketing Strategist"),
        ("intelligence", "Intelligence Specialist"),
        ("cmo_initial", "Executive Master Orchestrator"),
    ]

    def __init__(self, replies=None, fail_stages=()):
        super().__init__(free_only_mode=True)
        self.replies = dict(replies or {})
        self.fail_stages = set(fail_stages)
        self.calls = []  # (stage_label, system_prompt, user_prompt)

    def _label(self, request: ModelRequest) -> str:
        sys_msg = ""
        if request.messages and request.messages[0].role == ModelRole.SYSTEM:
            sys_msg = request.messages[0].content
        for label, marker in self.MARKERS:
            if marker in sys_msg:
                return label
        return "unknown:" + sys_msg[:40]

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        label = self._label(request)
        sys_msg = request.messages[0].content if request.messages else ""
        user_msg = request.messages[-1].content if request.messages else ""
        self.calls.append((label, sys_msg, user_msg))

        if label in self.fail_stages:
            return ModelResponse(
                request_id=request.request_id,
                provider="scripted_mock",
                model_name="scripted",
                status=ModelResponseStatus.ERROR,
                error="SCRIPTED_STAGE_FAILURE",
            )

        content = self.replies.get(label, f"[{label}] default scripted deliverable.")
        return ModelResponse(
            request_id=request.request_id,
            provider="scripted_mock",
            model_name="scripted",
            status=ModelResponseStatus.SUCCESS,
            content=content,
        )


def build_runtime(gateway) -> FiveAgentDepartmentRuntime:
    return FiveAgentDepartmentRuntime(
        model_gateway=gateway,
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


def run_pipeline(gateway, objective="Tang doanh thu cho san pham X qua quang cao TikTok"):
    rt = build_runtime(gateway)
    ctx = rt.start_run(objective=objective, business_id="BIZ_AUDIT")
    rt.execute_stage_cmo_initial(ctx)
    rt.execute_stage_intelligence(ctx)
    rt.execute_stage_strategist(ctx)
    rt.execute_stage_creative(ctx)
    rt.execute_stage_performance(ctx)
    rt.execute_stage_final_cmo(ctx)
    artifact = rt.complete_run(ctx)
    return rt, ctx, artifact


def prompts_for(gateway, label):
    return [user for (lbl, _sys, user) in gateway.calls if lbl == label]


class TestCollaborationIntegrityAudit(unittest.TestCase):
    # ------------------------------------------------------------------
    # A. UNKNOWN preservation without escalation
    # ------------------------------------------------------------------
    def test_a_intelligence_unknown_not_escalated_to_fact(self):
        gw = ScriptedAgentGateway(replies={
            "intelligence": (
                "FINDING: competitor A lowered prices.\n"
                "EPISTEMIC STATUS: UNKNOWN - churn rate data unavailable.\n"
                "We do NOT know the churn rate."
            ),
        })
        rt, ctx, artifact = run_pipeline(gw)

        strat_prompts = prompts_for(gw, "strategist")
        self.assertTrue(strat_prompts, "Strategist must be invoked")
        joined = "\n".join(strat_prompts)
        # The unknown must reach the strategist verbatim (not dropped/upgraded).
        self.assertIn("churn rate data unavailable", joined)

        # Engine must NOT have fabricated a structured FACT from the unknown:
        intel_out = ctx.stage_outputs["intelligence"]
        self.assertNotIn("known_facts", intel_out)
        self.assertIsInstance(intel_out["market_findings"], str,
                              "Handoff of findings is plain text; no typed epistemic state exists")

    # ------------------------------------------------------------------
    # B. Source/receipt traceability
    # ------------------------------------------------------------------
    def test_b_intelligence_source_id_traceable_downstream(self):
        gw = ScriptedAgentGateway()
        rt, ctx, artifact = run_pipeline(gw)

        intel_out = ctx.stage_outputs["intelligence"]
        receipt_id = intel_out.get("search_receipt_id")
        self.assertTrue(receipt_id, "Intelligence output must carry its tool receipt id")
        artifact_receipt_ids = {r.execution_id for r in artifact.execution_receipts}
        self.assertIn(receipt_id, artifact_receipt_ids)
        self.assertIn(receipt_id, ctx.execution_receipt_refs)

    # ------------------------------------------------------------------
    # C. Strategist structured fields must derive from real analysis
    # ------------------------------------------------------------------
    def test_c_strategist_structured_fields_not_hardcoded_templates(self):
        gw = ScriptedAgentGateway(replies={
            "strategist": (
                "POSITIONING: premium eco-friendly segment.\n"
                "HYPOTHESIS: GenZ buyers pay +15% for sustainable packaging."
            ),
        })
        rt, ctx, artifact = run_pipeline(gw)
        strat_out = ctx.stage_outputs["strategist"]

        llm_text = gw.replies["strategist"]
        # DESIRED CONTRACT: structured value propositions come from the
        # strategist's own analysis, not engine-injected template strings.
        self.assertTrue(
            all(vp.split()[0].lower() in llm_text.lower() for vp in strat_out["value_propositions"]),
            f"DEFECT: engine injects hardcoded value_propositions "
            f"{strat_out['value_propositions']} that do not originate from the "
            f"strategist LLM analysis",
        )
        self.assertTrue(
            all(seg.lower() in llm_text.lower() for seg in strat_out["target_segments"]),
            "DEFECT: hardcoded target_segments unrelated to actual analysis",
        )

    # ------------------------------------------------------------------
    # D. Creative unsupported claim must be flagged/rejected
    # ------------------------------------------------------------------
    def test_d_creative_unsupported_product_claim_flagged(self):
        gw = ScriptedAgentGateway(replies={
            "creative": (
                "HOOK: '99% of dermatologists recommend our serum!'\n"
                "CLAIM: Clinically proven results in 3 days (no source provided).\n"
                "GUARANTEE: Money-back result promise."
            ),
        })
        rt, ctx, artifact = run_pipeline(gw)
        creative_out = ctx.stage_outputs["creative"]
        final_out = ctx.stage_outputs["final_cmo"]

        # The unsupported claim text does flow through (documented fact):
        self.assertIn("Clinically proven", creative_out["creative_synthesis"])

        # DESIRED CONTRACT: unsupported product claims must be flagged or
        # rejected before Final CMO approval. Active runtime has no claim gate.
        governance_marks = (
            creative_out.get("claim_safety_status")
            or final_out.get("claim_audit")
            or ("UNSUBSTANTIATED_CLAIM" in json.dumps(ctx.risk_flags) if (json := __import__("json")) else None)
        )
        self.assertIsNotNone(
            governance_marks,
            "DEFECT: unsupported creative product claim reached an APPROVED final "
            "plan with no claim-safety flag, rejection, or audit entry",
        )
        self.assertNotEqual(final_out.get("approval_status"), "APPROVED",
                            "DEFECT: final plan auto-approved containing unsubstantiated claims")

    # ------------------------------------------------------------------
    # E. Performance INCONCLUSIVE -> no WINNER declaration
    # ------------------------------------------------------------------
    def test_e_performance_inconclusive_final_cmo_must_not_declare_winner(self):
        gw = ScriptedAgentGateway(replies={
            "performance": "RESULT: INCONCLUSIVE. Sample size too small. No causal conclusion possible.",
        })
        rt, ctx, artifact = run_pipeline(gw)
        final_out = ctx.stage_outputs["final_cmo"]

        self.assertNotEqual(
            final_out.get("approval_status"), "APPROVED",
            "DEFECT: Final CMO auto-approves deployment although Performance "
            "explicitly reported INCONCLUSIVE",
        )
        self.assertNotIn(
            "READY_FOR_DEPLOYMENT", (final_out.get("status"),),
            "DEFECT: inconclusive performance still yields READY_FOR_DEPLOYMENT",
        ) if False else None  # status check performed below explicitly
        self.assertNotEqual(final_out.get("status"), "READY_FOR_DEPLOYMENT")

    # ------------------------------------------------------------------
    # F. Performance failure -> fail-closed Final CMO
    # ------------------------------------------------------------------
    def test_f_performance_failure_final_cmo_no_fake_success(self):
        gw = ScriptedAgentGateway(fail_stages={"performance"})
        rt, ctx, artifact = run_pipeline(gw)

        perf_out = ctx.stage_outputs["performance"]
        final_out = ctx.stage_outputs["final_cmo"]

        self.assertEqual(perf_out["status"], "FAILED")
        self.assertEqual(final_out["status"], "FAILED")
        self.assertEqual(final_out["approval_status"], "NOT_EVALUATED")
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        # No candidate memory may be written from a failed run.
        self.assertEqual(artifact.learning_candidates, [])

    # ------------------------------------------------------------------
    # G. Failure propagation PREVIOUS_STAGE_FAILED
    # ------------------------------------------------------------------
    def test_g_stage_failure_propagates_to_downstream(self):
        gw = ScriptedAgentGateway(fail_stages={"intelligence"})
        rt, ctx, artifact = run_pipeline(gw)

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        strat_out = ctx.stage_outputs["strategist"]
        crtv_out = ctx.stage_outputs["creative"]
        perf_out = ctx.stage_outputs["performance"]
        for out in (strat_out, crtv_out, perf_out):
            self.assertEqual(out["status"], "FAILED")
            self.assertEqual(out["error"], "PREVIOUS_STAGE_FAILED")

    # ------------------------------------------------------------------
    # H. MOCK receipt stays MOCK_OR_SANDBOX
    # ------------------------------------------------------------------
    def test_h_mock_tool_receipt_never_becomes_verified(self):
        compiler = ContextCompiler()
        ctx = RuntimeContext(objective="obj", business_id="BIZ_AUDIT")
        mock_receipt = ExecutionReceipt(
            run_id=ctx.run_id, agent_id="intelligence", capability_id="web_search",
            provider="mock_provider", request_hash="h", status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.MOCK, output={"results": ["simulated snippet"]},
        )
        pkg = compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[mock_receipt])
        tool_items = [i for i in pkg.evidence_items if i.source_type == "TOOL_RECEIPT"]
        self.assertEqual(len(tool_items), 1)
        self.assertEqual(tool_items[0].epistemic_tier, EpistemicTier.MOCK_OR_SANDBOX)
        self.assertNotEqual(tool_items[0].epistemic_tier, EpistemicTier.VERIFIED_SOURCE)
        self.assertNotEqual(tool_items[0].epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)

    # ------------------------------------------------------------------
    # I. FAILED receipt produces no positive evidence
    # ------------------------------------------------------------------
    def test_i_failed_tool_receipt_yields_no_evidence(self):
        compiler = ContextCompiler()
        ctx = RuntimeContext(objective="obj", business_id="BIZ_AUDIT")
        failed_receipt = ExecutionReceipt(
            run_id=ctx.run_id, agent_id="intelligence", capability_id="web_search",
            provider="mock_provider", request_hash="h", status=ExecutionStatus.ERROR,
            error_class="PROVIDER_FAILURE", output=None,
        )
        pkg = compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[failed_receipt])
        tool_items = [i for i in pkg.evidence_items if i.source_type == "TOOL_RECEIPT"]
        self.assertEqual(tool_items, [], "Failed tool must not become positive evidence")

    # ------------------------------------------------------------------
    # J. Original objective reaches Final CMO
    # ------------------------------------------------------------------
    def test_j_original_objective_preserved_to_final_cmo(self):
        raw_objective = "Giup toi lap ke hoach quang cao cho san pham trung tam nau uong ANPHA"
        gw = ScriptedAgentGateway()
        rt, ctx, artifact = run_pipeline(gw, objective=raw_objective)

        final_prompts = prompts_for(gw, "final_cmo")
        self.assertTrue(any(raw_objective in p for p in final_prompts),
                        "Raw user objective must appear in Final CMO prompt")
        self.assertEqual(artifact.final_cmo_output["master_gtm_plan"]["objective"], raw_objective)
        self.assertEqual(artifact.objective, raw_objective)

    # ------------------------------------------------------------------
    # K. Restrictions/constraints reach Creative
    # ------------------------------------------------------------------
    def test_k_context_constraints_reach_creative_prompt(self):
        gw = ScriptedAgentGateway()
        rt = build_runtime(gw)
        ctx = rt.start_run(objective="quang cao my pham")
        ctx.constraints.append("RESTRICTION: khong duoc su dung tuy bo nganh y te / medical claims")
        ctx.constraints.append("BRAND CONSTRAINT: mau sac thuong hieu chi dung xanh den")

        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)

        creative_prompts = "\n".join(prompts_for(gw, "creative"))
        self.assertIn(
            "khong duoc su dung tuy bo nganh y te",
            creative_prompts,
            "DEFECT: RuntimeContext.constraints exists but is never delivered to "
            "specialists - Creative receives no brand/legal restrictions",
        )

    # ------------------------------------------------------------------
    # L. Cross-business scope isolation
    # ------------------------------------------------------------------
    def test_l_no_cross_business_knowledge_contamination(self):
        repo = LocalKnowledgeRepository()
        doc_a = KnowledgeDocument(
            source_id="SRC_A", title="Brand A secret recipe",
            source_type=SourceType.PRODUCT_GROUND_TRUTH, content="Brand A confidential formula KFC-X.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH, scope="SCOPE_BIZ_BRAND_A",
        )
        doc_b = KnowledgeDocument(
            source_id="SRC_B", title="Brand B secret recipe",
            source_type=SourceType.PRODUCT_GROUND_TRUTH, content="Brand B confidential formula PK-Y.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH, scope="SCOPE_BIZ_BRAND_B",
        )
        repo.save_document(doc_a)
        repo.save_document(doc_b)

        compiler = ContextCompiler(knowledge_repo=repo)
        ctx_a = RuntimeContext(objective="marketing plan", business_id="BIZ_BRAND_A")
        pkg_a = compiler.compile_grounded_package("strategist", ctx_a)
        contents_a = " ".join(i.content for i in pkg_a.evidence_items)

        self.assertIn("KFC-X", contents_a)
        self.assertNotIn("PK-Y", contents_a, "Cross-brand contamination: Brand B secret leaked into Brand A context")


class TestFinalCmoApprovalGateSafety(unittest.TestCase):
    """COLLAB-02 safety contracts for the active Final CMO authorization gate."""

    def _runtime_with_repo(self, gateway, knowledge_repo=None):
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gateway,
            knowledge_repo=knowledge_repo or LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )
        return rt

    def _stages_through_performance(self, rt, ctx):
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)

    def test_04_supported_factual_claim_with_verified_source_can_be_approved(self):
        repo = LocalKnowledgeRepository()
        repo.save_document(KnowledgeDocument(
            source_id="SRC_VERIFIED_CLINICAL",
            title="Verified clinical study",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="TIER_1 lab result: serum hydration improved.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_BIZ_AUDIT",
        ))
        gw = ScriptedAgentGateway()
        rt = self._runtime_with_repo(gw, repo)
        ctx = rt.start_run(objective="quang cao serum duong am", business_id="BIZ_AUDIT")
        self._stages_through_performance(rt, ctx)

        verified_ids = [
            sid for sid, item in ctx.working_state.get("provenance_index", {}).items()
            if str(item.get("epistemic_tier", "")).upper() == "VERIFIED_SOURCE"
        ]
        self.assertTrue(verified_ids, "verified knowledge must be present in provenance index")
        gw.replies["final_cmo"] = (
            f"# KE HOACH GTM\n"
            f"Clinically proven results (Source: {verified_ids[0]}) theo nghien cuu da xac thuc."
        )
        final_out = rt.execute_stage_final_cmo(ctx)
        self.assertEqual(final_out["approval_status"], "APPROVED")
        self.assertEqual(final_out["status"], "READY_FOR_DEPLOYMENT")

    def test_05_creative_hypothesis_not_falsely_rejected_as_factual_claim(self):
        gw = ScriptedAgentGateway(replies={
            "final_cmo": (
                "# KE HOACH SANG TAO\n"
                "HYPOTHESIS: a clinically proven style hook could lift CTR "
                "(creative direction only, not a factual claim, to be tested).\n"
                "IDEA: concept video voi placeholder demo."
            ),
        })
        rt = self._runtime_with_repo(gw)
        ctx = rt.start_run(objective="campaign sang tao", business_id="BIZ_AUDIT")
        self._stages_through_performance(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)

        self.assertIn(final_out["approval_status"], ("APPROVED", "APPROVED_WITH_CONDITIONS"))
        self.assertEqual(final_out["status"], "READY_FOR_DEPLOYMENT")
        self.assertGreaterEqual(final_out["claim_audit"]["hypotheses_count"], 1)
        self.assertEqual(final_out["claim_audit"]["blocked_claims"], 0)

    def test_06_audit_gate_crash_fails_closed_never_approved(self):
        class ExplodingGateRuntime(FiveAgentDepartmentRuntime):
            def _evaluate_final_authorization(self, *args, **kwargs):
                raise RuntimeError("GATE_CRASH_SIMULATION")

        gw = ScriptedAgentGateway()
        rt = ExplodingGateRuntime(
            model_gateway=gw,
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        self._stages_through_performance(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        artifact = rt.complete_run(ctx)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")
        self.assertNotEqual(final_out.get("master_gtm_plan_markdown"), "",
                            "raw Final CMO output must be preserved even when blocked")
        self.assertTrue(any(r.startswith("AUDIT_GATE_ERROR") or r.startswith("FINAL_CMO_NOT_AUTHORIZED")
                            for r in ctx.risk_flags))
        self.assertEqual(artifact.learning_candidates, [], "no learning from a blocked run")

    def test_07_missing_audit_result_fails_closed(self):
        class NoneGateRuntime(FiveAgentDepartmentRuntime):
            def _evaluate_final_authorization(self, *args, **kwargs):
                return None

        gw = ScriptedAgentGateway()
        rt = NoneGateRuntime(
            model_gateway=gw,
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        self._stages_through_performance(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")
        self.assertIn("MISSING_AUDIT_RESULT", final_out["claim_audit"]["blocking_reasons"][0])

    def test_09_mock_tier_evidence_cannot_authorize_factual_claim(self):
        # Same-sentence citation: the literal "mock" inside a source ID must
        # NOT trigger the hypothesis exemption before the tier check.
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# PLAN\nClinically proven results (Source: TOOL-MOCKED-001).",
        })
        rt = self._runtime_with_repo(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        ctx.working_state["provenance_index"] = {
            "TOOL-MOCKED-001": {"epistemic_tier": "MOCK_OR_SANDBOX", "source_type": "TOOL_RECEIPT"},
        }
        self._stages_through_performance(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")

    def test_10_failed_receipt_reference_cannot_authorize_factual_claim(self):
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# PLAN\nClinically proven results. Source: TOOL-FAILED-999",
        })
        rt = self._runtime_with_repo(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        # Failed receipts never enter the provenance index (compiler skips them).
        self._stages_through_performance(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")

    def test_11_approval_policy_runs_exactly_once_per_final_stage(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime_with_repo(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        self._stages_through_performance(rt, ctx)

        call_counter = {"n": 0}
        original_gate = rt._evaluate_final_authorization

        def counting_gate(*args, **kwargs):
            call_counter["n"] += 1
            return original_gate(*args, **kwargs)

        rt._evaluate_final_authorization = counting_gate
        rt.execute_stage_final_cmo(ctx)
        self.assertEqual(call_counter["n"], 1, "authorization policy must run exactly once")

    def test_12_no_agent_six_invariant_preserved(self):
        from governance.access_matrix import PERMANENT_FIVE_AGENTS

        self.assertEqual(PERMANENT_FIVE_AGENTS, {"cmo", "intelligence", "strategist", "creative", "performance"})
        self.assertEqual(set(AgentAccessMatrix.PROFILES.keys()), PERMANENT_FIVE_AGENTS)

        rt = self._runtime_with_repo(ScriptedAgentGateway())
        stage_methods = {m for m in dir(rt) if m.startswith("execute_stage_")}
        self.assertEqual(stage_methods, {
            "execute_stage_cmo_initial",      # agent 1 (initial pass)
            "execute_stage_intelligence",     # agent 2
            "execute_stage_strategist",       # agent 3
            "execute_stage_creative",         # agent 4
            "execute_stage_performance",      # agent 5
            "execute_stage_final_cmo",        # agent 1 (final pass) - NOT a sixth agent
        })


class TestConstraintPropagation(unittest.TestCase):
    """COLLAB-03 — structural constraint/restriction channel contracts."""

    CONSTRAINT_A = "Khong duoc noi san pham chua mun (medical claims prohibited)."
    CONSTRAINT_B = "Ngan sach phai o duoi 10 trieu VND."

    def _runtime(self, gateway):
        return FiveAgentDepartmentRuntime(
            model_gateway=gateway,
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )

    def _seeded_context(self, rt, objective="quang cao my pham"):
        ctx = rt.start_run(objective=objective, business_id="BIZ_AUDIT", chat_id="CHAT-A")
        record_constraint(ctx, self.CONSTRAINT_A, origin="USER_CONSTRAINT", source="user_request")
        return ctx

    def _prompts(self, gw, label):
        return [user for (lbl, _s, user) in gw.calls if lbl == label]

    def _run_all_stages(self, rt, ctx):
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)

    # 1-6. constraint reaches every stage structurally
    def test_01_to_06_constraint_reaches_all_six_stages(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)
        self._run_all_stages(rt, ctx)
        rt.execute_stage_final_cmo(ctx)

        for label in ("cmo_initial", "intelligence", "strategist", "creative", "performance", "final_cmo"):
            prompts = "\n".join(self._prompts(gw, label))
            self.assertIn(
                self.CONSTRAINT_A, prompts,
                f"stage {label} must receive the binding constraint structurally",
            )
            self.assertIn("BINDING CONSTRAINTS & RESTRICTIONS", prompts,
                          f"stage {label} must label constraints as binding restrictions")

    # 7. verbatim preservation
    def test_07_constraint_text_verbatim_unchanged(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)
        creative_prompts_before = len(self._prompts(gw, "creative"))
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        joined = "\n".join(self._prompts(gw, "creative")[creative_prompts_before:])
        self.assertIn("- [USER_CONSTRAINT] " + self.CONSTRAINT_A, joined)

    # 8. multiple constraints stable order + artifact persistence
    def test_08_multiple_constraints_stable_order_and_artifact(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)
        record_constraint(ctx, self.CONSTRAINT_B, origin="BUSINESS_CONSTRAINT", source="brand_policy")
        self._run_all_stages(rt, ctx)
        cmo_final = rt.execute_stage_final_cmo(ctx)
        artifact = rt.complete_run(ctx)

        final_prompt = self._prompts(gw, "final_cmo")[-1]
        pos_a = final_prompt.find(self.CONSTRAINT_A)
        pos_b = final_prompt.find(self.CONSTRAINT_B)
        self.assertGreaterEqual(pos_a, 0)
        self.assertGreater(pos_b, pos_a, "constraint order must be stable")
        self.assertEqual(artifact.binding_constraints, [self.CONSTRAINT_A, self.CONSTRAINT_B])

    # 9/10. constraints are NOT facts / NOT evidence
    def test_09_10_constraints_separate_from_facts_and_evidence(self):
        repo = LocalKnowledgeRepository()
        mem_repo = LocalMemoryRepository()
        docs_before = len(repo.list_documents(scope="SCOPE_BIZ_AUDIT"))
        mems_before = len(mem_repo.list_memories())

        gw = ScriptedAgentGateway()
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw, knowledge_repo=repo, memory_repo=mem_repo,
        )
        ctx = self._seeded_context(rt)
        pkg = rt.context_compiler.compile_grounded_package("creative", ctx)

        constraint_evidence = [
            i for i in pkg.evidence_items if self.CONSTRAINT_A in i.content
        ]
        self.assertEqual(constraint_evidence, [], "constraints must never become evidence items")
        self.assertEqual(len(repo.list_documents(scope="SCOPE_BIZ_AUDIT")), docs_before)
        self.assertEqual(len(mem_repo.list_memories()), mems_before)

    # 11. model recommendation never promoted
    def test_11_model_recommendation_not_promoted_to_binding(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)
        ok = record_constraint(ctx, "Maybe avoid aggressive language.", origin="MODEL_RECOMMENDATION", source="cmo_llm")
        self.assertTrue(ok)

        self.assertNotIn("Maybe avoid aggressive language.", ctx.constraints)
        block = rt._render_governance_block(ctx)
        self.assertNotIn("Maybe avoid aggressive language.", block)
        ledger = ctx.working_state["constraint_ledger"]
        self.assertTrue(any(e["origin"] == "MODEL_RECOMMENDATION" for e in ledger),
                        "recommendation stays in audit ledger only")

    # 12/13. isolation
    def test_12_13_no_cross_brand_or_cross_chat_leakage(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx_a = rt.start_run(objective="brand A campaign", business_id="BIZ_BRAND_A", chat_id="CHAT-A")
        record_constraint(ctx_a, self.CONSTRAINT_A)
        ctx_b = rt.start_run(objective="brand B campaign", business_id="BIZ_BRAND_B", chat_id="CHAT-B")

        self.assertEqual(ctx_b.constraints, [])
        block_b = rt._render_governance_block(ctx_b)
        self.assertNotIn("chua mun", block_b)
        self.assertNotIn(self.CONSTRAINT_A, block_b)

    # 14. checkpoint persistence of constraints
    def test_14_constraints_survive_checkpoint_snapshot(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)
        rt.execute_stage_cmo_initial(ctx)
        last = ctx.checkpoints[-1]
        self.assertEqual(last.working_state_snapshot.get("binding_constraints"), [self.CONSTRAINT_A])

    # 15. Final approval cannot ignore hard restrictions
    def test_15_final_cannot_ignore_hard_restriction_medical(self):
        gw = ScriptedAgentGateway(replies={
            "creative": "HOOK: 'Clinically proven to cure acne!'",
            "final_cmo": "# PLAN\nClinically proven to improve skin.",
        })
        rt = self._runtime(gw)
        ctx = self._seeded_context(rt)  # medical claims prohibited
        self._run_all_stages(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")

    def test_15b_final_cannot_ignore_publish_prohibition(self):
        gw = ScriptedAgentGateway(replies={
            "final_cmo": "# PLAN\nDeploy now and auto-publish the campaign immediately.",
        })
        rt = self._runtime(gw)
        ctx = rt.start_run(objective="campaign thoi trang", business_id="BIZ_AUDIT")
        record_constraint(ctx, "Do not publish before approval.", origin="POLICY_CONSTRAINT", source="policy")
        self._run_all_stages(rt, ctx)
        final_out = rt.execute_stage_final_cmo(ctx)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        reasons = " ".join(final_out["claim_audit"]["blocking_reasons"])
        self.assertIn("CONSTRAINT_VIOLATION", reasons)
        self.assertTrue(any(r.startswith("FINAL_CMO_NOT_AUTHORIZED: ") for r in ctx.risk_flags))

    # 16. five-agent invariant
    def test_16_five_agent_invariant_intact(self):
        from governance.access_matrix import PERMANENT_FIVE_AGENTS
        self.assertEqual(PERMANENT_FIVE_AGENTS, {"cmo", "intelligence", "strategist", "creative", "performance"})
        rt = self._runtime(ScriptedAgentGateway())
        stage_methods = {m for m in dir(rt) if m.startswith("execute_stage_")}
        self.assertEqual(len(stage_methods), 6)


class TestProductionConstraintPath(unittest.TestCase):
    """PART 10 — no-producer false-green guard.

    Constraints must flow through the REAL production population path:
    raw user text -> deterministic extractor -> RuntimeContext/start_run ->
    downstream stage prompts. No manual ctx.constraints seeding allowed here.
    """

    USER_TEXT = (
        "Lap chien luoc quang cao cho my pham sinh hoc. "
        "Khong duoc noi san pham chua mun. "
        "Chi target khach hang Viet Nam."
    )

    def test_extractor_produces_explicit_restrictions_only(self):
        extracted = extract_explicit_user_constraints(self.USER_TEXT)
        self.assertEqual(len(extracted), 2, f"expected exactly the two imperative restrictions, got {extracted}")
        self.assertIn("Khong duoc noi san pham chua mun.", extracted[0])
        self.assertTrue(extracted[1].startswith("Chi target khach hang Viet Nam"))
        # benign marketing sentence must NOT be misread as a restriction
        benign = extract_explicit_user_constraints("Phân tích thị trường và lập campaign TikTok với ngân sách 30 triệu.")
        self.assertEqual(benign, [])

    def test_production_path_reaches_creative_structurally(self):
        gw = ScriptedAgentGateway()
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )
        # EXACT production entry semantics (start_run performs what server.py
        # does via extract_explicit_user_constraints at construction).
        ctx = rt.start_run(objective=self.USER_TEXT, business_id="BIZ_AD_HOC_EXPLORATION", chat_id="CHAT-PROD")
        self.assertGreaterEqual(len(ctx.constraints), 2, "producer must populate constraints")

        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)

        creative_prompt = [u for (l, _s, u) in gw.calls if l == "creative"][-1]
        self.assertIn("Khong duoc noi san pham chua mun.", creative_prompt)
        self.assertIn("[USER_CONSTRAINT]", creative_prompt)
        # raw user text untouched
        self.assertIn("Lap chien luoc quang cao cho my pham sinh hoc", ctx.objective)


class TestDataOriginIntegrity(unittest.TestCase):
    """COLLAB-04 — no fabricated/hardcoded agent outputs anywhere."""

    def _runtime(self, gateway):
        return FiveAgentDepartmentRuntime(
            model_gateway=gateway,
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )

    def _full_run(self, replies=None, fail_stages=()):
        gw = ScriptedAgentGateway(replies=replies, fail_stages=fail_stages)
        rt = self._runtime(gw)
        ctx = rt.start_run(objective="demo objective", business_id="BIZ_AUDIT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        artifact = rt.complete_run(ctx)
        return gw, rt, ctx, final_out, artifact

    # 1/2. strategist structured fields absent when model did not produce them
    def test_01_02_strategist_fields_empty_without_model_content(self):
        gw, rt, ctx, final_out, artifact = self._full_run(replies={
            "strategist": "POSITIONING: premium eco segment only.",
        })
        strat = ctx.stage_outputs["strategist"]
        self.assertEqual(strat["target_segments"], [])
        self.assertEqual(strat["value_propositions"], [])
        llm_text = "premium eco segment only"
        for vp in strat["value_propositions"]:
            self.assertIn(vp.split()[0].lower(), llm_text)
        self.assertEqual(strat["field_origins"]["value_propositions"], "NOT_PROVIDED")
        self.assertNotIn("Verified customer outcomes", str(ctx.stage_outputs))

    def test_02b_strategist_agent_derived_positioning_preserved(self):
        gw, rt, ctx, final_out, artifact = self._full_run(replies={
            "strategist": "POSITIONING X: beachhead la sinh vien urban.",
        })
        self.assertEqual(ctx.stage_outputs["strategist"]["positioning"], "POSITIONING X: beachhead la sinh vien urban.")
        self.assertEqual(ctx.stage_outputs["strategist"]["field_origins"]["positioning"], "AGENT_DERIVED")

    # 3/4. creative concept/headlines not fabricated
    def test_03_04_creative_concept_and_headlines_absent(self):
        gw, rt, ctx, final_out, artifact = self._full_run()
        creative = ctx.stage_outputs["creative"]
        self.assertIsNone(creative["concept_name"])
        self.assertEqual(creative["copy_headlines"], [])
        self.assertEqual(creative["field_origins"]["concept_name"], "NOT_PROVIDED")
        self.assertNotIn("Direct Response & Brand Affinity Concept", str(ctx.stage_outputs))
        self.assertNotIn("Direct Response", artifact.final_cmo_output["master_gtm_plan_markdown"])

    # 5. performance blueprint not invented
    def test_05_performance_blueprint_not_invented(self):
        gw, rt, ctx, final_out, artifact = self._full_run()
        perf = ctx.stage_outputs["performance"]
        self.assertEqual(perf["experiment_blueprint"], {})
        self.assertEqual(perf["field_origins"]["experiment_blueprint"], "NOT_PROVIDED")
        self.assertNotIn("Optimized creative hooks", str(ctx.stage_outputs))

    # 6. master plan does not upgrade template values
    def test_06_master_plan_preserves_absent_as_absent(self):
        gw, rt, ctx, final_out, artifact = self._full_run()
        plan = final_out["master_gtm_plan"]
        self.assertEqual(plan["strategy"]["value_propositions"], [])
        self.assertIsNone(plan["creative"]["concept_name"])
        self.assertEqual(plan["performance"]["experiment_blueprint"], {})
        self.assertEqual(plan["strategy"]["field_origins"]["positioning"], "AGENT_DERIVED")

    # 7/8/9. memory safety
    def test_07_08_09_candidate_memory_factual_or_zero(self):
        import re as _re
        # a) approved happy path: exactly one factual bookkeeping record
        gw, rt, ctx, final_out, artifact = self._full_run()
        cands = artifact.learning_candidates
        self.assertLessEqual(len(cands), 1)
        if cands:
            c = cands[0]
            content_l = c.content.lower()
            self.assertNotIn("succeed", content_l)
            self.assertNotIn("winning", content_l)
            self.assertNotIn("verified customer", content_l)
            self.assertNotIn("improves cvr", content_l)
            self.assertEqual(c.confidence, 0.5)
            self.assertLess(c.confidence, 0.60, "bookkeeping confidence must stay below verification threshold")
            self.assertEqual(c.context.get("record_type"), "RUN_DECISION_BOOKKEEPING")

        # b) blocked run: zero candidates
        gw2, rt2, ctx2, fo2, art2 = self._full_run(replies={
            "final_cmo": "# P\nClinically proven results.",
        })
        self.assertEqual(art2.learning_candidates, [])

    # 10. empty structured fields do not crash downstream
    def test_10_downstream_tolerates_empty_structured_fields(self):
        gw, rt, ctx, final_out, artifact = self._full_run()
        perf_prompt = [u for (l, _s, u) in gw.calls if l == "performance"][-1]
        self.assertNotIn("Creative Assets: None", perf_prompt)
        self.assertEqual(final_out["status"] in ("READY_FOR_DEPLOYMENT", "NOT_READY"), True)
        self.assertTrue(artifact.final_artifact_hash)

    # 11. genuinely agent-derived values remain preserved verbatim
    def test_11_agent_derived_values_preserved(self):
        replies = {
            "intelligence": "FINDINGS: competitor price cut 10%.",
            "strategist": "POSITIONING Y: value-first messaging.",
            "creative": "HOOKS: three scroll-stopper angles.",
            "performance": "KPI TREE: CAC guardrail 120k VND.",
        }
        gw, rt, ctx, final_out, artifact = self._full_run(replies=replies)
        self.assertEqual(ctx.stage_outputs["intelligence"]["market_findings"], replies["intelligence"])
        self.assertEqual(ctx.stage_outputs["strategist"]["positioning"], replies["strategist"])
        self.assertEqual(ctx.stage_outputs["creative"]["creative_synthesis"], replies["creative"])
        self.assertEqual(ctx.stage_outputs["performance"]["funnel_kpi"], replies["performance"])

    # 12/13/14. invariants
    def test_12_five_agent_invariant_intact(self):
        from governance.access_matrix import PERMANENT_FIVE_AGENTS
        self.assertEqual(PERMANENT_FIVE_AGENTS, {"cmo", "intelligence", "strategist", "creative", "performance"})

    def test_13_collab02_approval_safety_intact(self):
        gw, rt, ctx, final_out, artifact = self._full_run(replies={
            "performance": "RESULT: INCONCLUSIVE. Insufficient evidence.",
        })
        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")

    def test_14_collab03_constraints_intact(self):
        gw = ScriptedAgentGateway()
        rt = self._runtime(gw)
        ctx = rt.start_run(objective="quang cao my pham", business_id="BIZ_AUDIT")
        record_constraint(ctx, "Khong duoc noi san pham chua mun.", origin="USER_CONSTRAINT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        creative_prompt = [u for (l, _s, u) in gw.calls if l == "creative"][-1]
        self.assertIn("BINDING CONSTRAINTS & RESTRICTIONS", creative_prompt)
        self.assertIn("Khong duoc noi san pham chua mun.", creative_prompt)


if __name__ == "__main__":
    unittest.main()
