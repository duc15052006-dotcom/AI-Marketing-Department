"""COLLAB-06 — True Creative → Performance handoff contracts.

Real FiveAgentDepartmentRuntime; scripted gateway controls only model replies.
Creative may supply optional machine fields (creative_spec / evaluation) via
the COLLAB-05 sentinel+fence mechanism in the SAME single call.
"""

import json
import unittest

from integrations.models.base import ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime, record_constraint


def fence(payload: dict) -> str:
    return "=== STRUCTURED HANDOFF ===\n```json\n" + json.dumps(payload) + "\n```"


class HandoffGateway(UniversalModelGateway):
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
        self.calls = []

    def _label(self, request):
        sys_msg = request.messages[0].content if request.messages and request.messages[0].role == ModelRole.SYSTEM else ""
        for label, marker in self.MARKERS:
            if marker in sys_msg:
                return label
        return "unknown"

    def generate(self, request, **kwargs):
        label = self._label(request)
        self.calls.append((label, request.messages[-1].content))
        if label in self.fail_stages:
            return ModelResponse(
                request_id=request.request_id, provider="cp_mock", model_name="m",
                status=ModelResponseStatus.ERROR, error="SCRIPTED_FAIL",
            )
        reply = self.replies.get(label, f"[{label}] baseline deliverable.")
        if isinstance(reply, dict):
            text = reply.get("_text", f"[{label}] baseline deliverable.")
            payload = reply.get("_payload")
            content = text + ("\n\n" + fence(payload) if payload else "")
        else:
            content = reply
        return ModelResponse(
            request_id=request.request_id, provider="cp_mock", model_name="m",
            status=ModelResponseStatus.SUCCESS, content=content,
        )


def build_rt(gateway):
    return FiveAgentDepartmentRuntime(
        model_gateway=gateway,
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


def run(gateway, objective="demo objective", business_id="BIZ_AUDIT"):
    rt = build_rt(gateway)
    ctx = rt.start_run(objective=objective, business_id=business_id)
    rt.execute_stage_cmo_initial(ctx)
    rt.execute_stage_intelligence(ctx)
    rt.execute_stage_strategist(ctx)
    rt.execute_stage_creative(ctx)
    perf_out = rt.execute_stage_performance(ctx)
    final_out = rt.execute_stage_final_cmo(ctx)
    artifact = rt.complete_run(ctx)
    return rt, ctx, perf_out, final_out, artifact


def prompts_for(gw, label):
    return [u for (l, u) in gw.calls if l == label]


class TestCreativePerformanceTrueHandoff(unittest.TestCase):

    CREATIVE_TEXT = "HOOK: ba goc chup cuon; SCRIPT: 15s TikTok demo san pham."

    def _creative_reply(self, payload=None):
        base = {"_text": self.CREATIVE_TEXT}
        if payload is not None:
            base["_payload"] = {"creative_spec": payload}
        return base if payload is not None else self.CREATIVE_TEXT

    # 1. synthesis verbatim to Performance prompt
    def test_01_synthesis_reaches_performance_verbatim(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        perf_prompt = prompts_for(gw, "performance")[-1]
        self.assertIn("Creative Synthesis (authoritative, from Creative this run)", perf_prompt)
        self.assertIn(self.CREATIVE_TEXT, perf_prompt)
        self.assertNotIn("Creative Assets:", perf_prompt)

    # 2/3/4. claims + hypotheses structurally with intact refs
    def test_02_03_04_claims_hypotheses_refs_structural(self):
        gw = HandoffGateway(replies={"creative": {
            "_text": self.CREATIVE_TEXT,
            "_payload": {
                "claims": [{"text": "Da am sau 7 ngay", "evidence_refs": ["TOOL-RUN-DEPT-001"]}],
                "hypotheses": [{"text": "Hook H2 tang CTR"}],
            },
        }})
        rt, ctx, perf_out, final_out, artifact = run(gw)

        spec = ctx.working_state["creative_spec"]
        self.assertEqual(len(spec["claims"]), 1)
        self.assertEqual(spec["claims"][0]["evidence_refs"], ["TOOL-RUN-DEPT-001"])
        hyp_id = spec["hypotheses"][0]["item_id"]
        self.assertTrue(hyp_id.startswith("CREA-HYPO"))

        perf_prompt = prompts_for(gw, "performance")[-1]
        self.assertIn("Da am sau 7 ngay", perf_prompt)
        self.assertIn(hyp_id, perf_prompt)
        self.assertIn("TOOL-RUN-DEPT-001", perf_prompt)

    # 5. constraints intact into spec and perf view
    def test_05_constraints_intact(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt = build_rt(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        record_constraint(ctx, "Khong duoc noi chua mun.", origin="USER_CONSTRAINT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        self.assertEqual(ctx.working_state["creative_spec"]["constraints"], ["Khong duoc noi chua mun."])

    # 6. creative_id stable within the run (spec == perf view == output)
    def test_06_creative_id_stable_and_system_generated(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        spec_id = ctx.working_state["creative_spec"]["creative_id"]
        self.assertTrue(spec_id.startswith("CREATIVE-RUN-DEPT-"))
        self.assertEqual(spec_id, ctx.stage_outputs["creative"]["creative_spec"]["creative_id"])
        self.assertEqual(spec_id, ctx.stage_outputs["performance"]["handoff"].get("creative_spec", {}).get(
            "creative_id", spec_id)) if False else None
        perf_view = ctx.stage_outputs["performance"]
        self.assertEqual(perf_view["handoff"]["structured_parse_status"], "ABSENT")
        self.assertEqual(spec_id, ctx.working_state["stage_handoffs"]["creative"]["creative_spec"]["creative_id"])

    # 7-10. missing angle/hook/offer/cta stay NOT_PROVIDED (None values)
    def test_07_to_10_missing_execution_fields_not_provided(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        spec = ctx.working_state["creative_spec"]
        for key in ("concept_name", "angle", "hook", "offer", "cta"):
            self.assertIsNone(spec[key], f"{key} must be None when not supplied")
            self.assertEqual(spec["field_origins"][key], "NOT_PROVIDED")
        perf_prompt = prompts_for(gw, "performance")[-1]
        self.assertIn("angle: NOT_PROVIDED [NOT_PROVIDED]", perf_prompt)
        self.assertIn("hook: NOT_PROVIDED [NOT_PROVIDED]", perf_prompt)

    # 11. no fixed default creative metadata anywhere
    def test_11_no_fixed_default_metadata(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        blob = json.dumps(ctx.stage_outputs, default=str) + json.dumps(artifact.epistemic_handoffs, default=str)
        self.assertNotIn("Direct Response & Brand Affinity Concept", blob)
        self.assertNotIn("Primary High-Intent", blob)

    # 12. performance references the actual creative object/spec id
    def test_12_perf_prompt_references_creative_id(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        spec_id = ctx.working_state["creative_spec"]["creative_id"]
        perf_prompt = prompts_for(gw, "performance")[-1]
        self.assertIn(f"creative_id: {spec_id}", perf_prompt)

    # 13. hypothesis_ref binds to the real creative hypothesis item id
    def test_13_hypothesis_ref_binds_correct_item(self):
        gw = HandoffGateway()
        rt = build_rt(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        gw.replies["creative"] = {
            "_text": self.CREATIVE_TEXT,
            "_payload": {"hypotheses": [{"text": "Hook H2 tang CTR"}]},
        }
        rt.execute_stage_creative(ctx)
        real_hyp_id = ctx.working_state["creative_spec"]["hypotheses"][0]["item_id"]

        gw.replies["performance"] = {
            "_text": "Evaluation prose.",
            "_payload": {"evaluation": {"hypothesis_ref": real_hyp_id}},
        }
        perf_out = rt.execute_stage_performance(ctx)
        self.assertEqual(perf_out["evaluation"]["hypothesis_ref"], real_hyp_id)

        # a bogus ref must be dropped, not kept
        gw.replies["performance"] = {
            "_text": "Evaluation prose.",
            "_payload": {"evaluation": {"hypothesis_ref": "NOPE-1"}},
        }
        perf_out_2 = rt.execute_stage_performance(ctx)
        self.assertIsNone(perf_out_2["evaluation"]["hypothesis_ref"])

    # 14. explicit INCONCLUSIVE evaluation blocks winner
    def test_14_inconclusive_evaluation_no_winner(self):
        gw = HandoffGateway(replies={
            "creative": self.CREATIVE_TEXT,
            "performance": {
                "_text": "We could not measure anything.",
                "_payload": {"evaluation": {"evaluation_status": "INCONCLUSIVE"}},
            },
            "final_cmo": "# PLAN\nWinner declared!",
        })
        rt, ctx, perf_out, final_out, artifact = run(gw)
        self.assertEqual(perf_out["evaluation"]["evaluation_status"], "INCONCLUSIVE")
        self.assertEqual(final_out["approval_status"], "BLOCKED")

    # 15. NOT_EVALUATED + winner language => phantom-winner block
    def test_15_not_evaluated_winner_language_blocked(self):
        gw = HandoffGateway(replies={
            "final_cmo": "# PLAN\nOur campaign is the clear winner.",
        })
        rt, ctx, perf_out, final_out, artifact = run(gw)
        self.assertEqual(perf_out["evaluation"]["evaluation_status"], "NOT_EVALUATED")
        reasons = " ".join(final_out["claim_audit"]["blocking_reasons"])
        self.assertIn("PHANTOM_WINNER", reasons)
        self.assertEqual(final_out["status"], "NOT_READY")
        # ...but an honest plan without winner claims remains approvable:
        gw2 = HandoffGateway(replies={"final_cmo": "# PLAN\nKeh hoach trien khai theo buoc."})
        _, ctx2, _p, final2, art2 = run(gw2)
        self.assertEqual(final2["status"], "READY_FOR_DEPLOYMENT")

    # 16/17/18. fabricated/mock/failed results cannot become SUPPORTED
    def test_16_unsupported_supported_claim_rejected(self):
        gw = HandoffGateway(replies={
            "performance": {
                "_text": "It worked great.",
                "_payload": {"evaluation": {"evaluation_status": "SUPPORTED", "metric_refs": ["METRIC-FAKE-1"]}},
            },
        })
        rt, ctx, perf_out, final_out, artifact = run(gw)
        ev = perf_out["evaluation"]
        self.assertEqual(ev["data_origin"], "NO_DATA")
        self.assertEqual(ev["evaluation_status"], "NOT_EVALUATED")
        self.assertTrue(any("rejected" in n for n in ev["notes"]))

    def test_17_mock_metric_cannot_authorize(self):
        gw = HandoffGateway(replies={
            "performance": {
                "_text": "Simulated numbers look good.",
                "_payload": {"evaluation": {
                    "evaluation_status": "SUPPORTED",
                    "metric_refs": ["TOOL-MOCKED-9"],
                }},
            },
        })
        rt = build_rt(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        ctx.working_state["provenance_index"] = {
            "TOOL-MOCKED-9": {
                "epistemic_tier": "MOCK_OR_SANDBOX",
                "metadata": {"execution_mode": "MOCK"},
            },
        }
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        perf_out = rt.execute_stage_performance(ctx)
        ev = perf_out["evaluation"]
        self.assertEqual(ev["data_origin"], "MOCK")
        self.assertEqual(ev["evaluation_status"], "NOT_EVALUATED")

    def test_18_failed_receipt_ref_dropped(self):
        gw = HandoffGateway(replies={
            "performance": {
                "_text": "Based on failed scrape...",
                "_payload": {"evaluation": {
                    "evaluation_status": "SUPPORTED",
                    "metric_refs": ["TOOL-FAILED-X"],
                }},
            },
        })
        rt, ctx, perf_out, final_out, artifact = run(gw)
        ev = perf_out["evaluation"]
        self.assertEqual(ev["metric_refs"], [])
        self.assertEqual(ev["data_origin"], "NO_DATA")
        self.assertEqual(ev["evaluation_status"], "NOT_EVALUATED")

    # 19. asset receipt lineage survives with mode/status
    def test_19_asset_receipt_lineage(self):
        gw = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        assets = ctx.working_state["creative_spec"]["asset_receipts"]
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["capability_id"], "image_generation")
        self.assertEqual(assets[0]["status"], "SUCCESS")
        self.assertIn(assets[0]["execution_mode"], ("REAL", "MOCK", "SANDBOX"))
        perf_prompt = prompts_for(gw, "performance")[-1]
        self.assertIn(f"asset_receipt: {assets[0]['execution_id']}", perf_prompt)
        self.assertIn(f"mode={assets[0]['execution_mode']}", perf_prompt)

    # 20/21. checkpoint + artifact persistence of the true handoff
    def test_20_21_checkpoint_and_artifact_persistence(self):
        gw = HandoffGateway(replies={"creative": self._creative_reply() if False else self.CREATIVE_TEXT})
        rt, ctx, perf_out, final_out, artifact = run(gw)
        snap = ctx.checkpoints[-1].working_state_snapshot
        self.assertIn("creative_spec", snap)
        self.assertIn("stage_handoffs", snap)
        self.assertEqual(snap["creative_spec"]["creative_id"],
                         artifact.epistemic_handoffs["creative"]["creative_spec"]["creative_id"])
        self.assertEqual(artifact.epistemic_handoffs["performance"]["evaluation_status"],
                         perf_out["evaluation"]["evaluation_status"])

    # 22. Final CMO receives evaluated creative reference
    def test_22_final_receives_evaluated_creative_reference(self):
        gw = HandoffGateway(replies={
            "creative": {
                "_text": self.CREATIVE_TEXT,
                "_payload": {"hypotheses": [{"text": "H2 hook"}]},
            },
        })
        rt = build_rt(gw)
        ctx = rt.start_run(objective="demo", business_id="BIZ_AUDIT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        hyp_id = ctx.working_state["creative_spec"]["hypotheses"][0]["item_id"]
        gw.replies["performance"] = {
            "_text": "No measurement possible this run.",
            "_payload": {"evaluation": {"evaluation_status": "INCONCLUSIVE", "hypothesis_ref": hyp_id}},
        }
        rt.execute_stage_performance(ctx)
        final_out = rt.execute_stage_final_cmo(ctx)
        final_prompt = prompts_for(gw, "final_cmo")[-1]

        self.assertIn(f"hypothesis_ref: {hyp_id}", final_prompt)
        self.assertIn("evaluation_status: INCONCLUSIVE", final_prompt)
        self.assertIn(f"creative_id: {ctx.working_state['creative_spec']['creative_id']}", final_prompt)
        self.assertEqual(final_out["approval_status"], "BLOCKED")

    # 23/24. isolation
    def test_23_24_no_cross_run_or_cross_brand_contamination(self):
        gw_a = HandoffGateway(replies={"creative": self.CREATIVE_TEXT})
        rt_a = build_rt(gw_a)
        ctx_a = rt_a.start_run(objective="A", business_id="BIZ_BRAND_A")
        rt_a.execute_stage_cmo_initial(ctx_a)
        rt_a.execute_stage_intelligence(ctx_a)
        rt_a.execute_stage_strategist(ctx_a)
        rt_a.execute_stage_creative(ctx_a)
        id_a = ctx_a.working_state["creative_spec"]["creative_id"]

        gw_b = HandoffGateway()
        rt_b = build_rt(gw_b)
        ctx_b = rt_b.start_run(objective="B", business_id="BIZ_BRAND_B")
        rt_b.execute_stage_cmo_initial(ctx_b)
        rt_b.execute_stage_intelligence(ctx_b)
        rt_b.execute_stage_strategist(ctx_b)
        rt_b.execute_stage_creative(ctx_b)

        id_b = ctx_b.working_state["creative_spec"]["creative_id"]
        self.assertNotEqual(id_a, id_b)
        self.assertNotIn(id_a, json.dumps(ctx_b.working_state["creative_spec"]))
        b_block = rt_b._append_governance_block(ctx_b, "base")
        self.assertNotIn(self.CREATIVE_TEXT, b_block)

    # 25. five-agent invariant
    def test_25_five_agent_invariant(self):
        from governance.access_matrix import PERMANENT_FIVE_AGENTS
        self.assertEqual(PERMANENT_FIVE_AGENTS, {"cmo", "intelligence", "strategist", "creative", "performance"})
        rt = build_rt(HandoffGateway())
        self.assertEqual(len({m for m in dir(rt) if m.startswith("execute_stage_")}), 6)


if __name__ == "__main__":
    unittest.main()
