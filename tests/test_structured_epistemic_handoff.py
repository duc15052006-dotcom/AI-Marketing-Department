"""COLLAB-05 — Structured Epistemic Handoff contracts.

Uses the REAL FiveAgentDepartmentRuntime. The scripted gateway controls only
model responses; stages may append the machine handoff block (sentinel + JSON
fence) exactly as the production prompt instructs, and the production parser
(runtime/handoff.py + invocation.parse_and_validate_agent_json) does all
extraction/validation. No prose-regex heuristics, no second model call.
"""

import json
import unittest

from integrations.models.gateway import UniversalModelGateway
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime, record_constraint
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway
from runtime.handoff import (
    EpistemicType,
    StageHandoff,
    build_epistemic_item,
    extract_handoff_payload,
    render_handoff_sections,
)

sys_path_note = None  # noqa: keep module imports repo-relative via tests package


def fence(payload: dict) -> str:
    return "=== STRUCTURED HANDOFF ===\n```json\n" + json.dumps(payload) + "\n```"


class StructuredScriptedGateway(UniversalModelGateway):
    """Scripted gateway; reply values may be str OR (text, structured_payload)."""

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
        sys_msg = request.messages[0].content if request.messages and request.messages[0].role == __import__(
            "integrations.models.base", fromlist=["ModelRole"]).ModelRole.SYSTEM else ""
        for label, marker in self.MARKERS:
            if marker in sys_msg:
                return label
        return "unknown"

    def generate(self, request, **kwargs):
        from integrations.models.base import ModelResponse, ModelResponseStatus
        label = self._label(request)
        self.calls.append((label, request.messages[-1].content))
        if label in self.fail_stages:
            return ModelResponse(
                request_id=request.request_id, provider="structured_mock",
                model_name="m", status=ModelResponseStatus.ERROR, error="SCRIPTED_FAIL",
            )
        reply = self.replies.get(label, f"[{label}] baseline deliverable.")
        if isinstance(reply, tuple):
            text, payload = reply
            content = text + "\n\n" + fence(payload)
        else:
            content = reply
        return ModelResponse(
            request_id=request.request_id, provider="structured_mock",
            model_name="m", status=ModelResponseStatus.SUCCESS, content=content,
        )


def build_runtime(gateway):
    return FiveAgentDepartmentRuntime(
        model_gateway=gateway,
        tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


def run_pipeline(gateway, objective="demo objective", business_id="BIZ_AUDIT", real_adapter=False):
    rt = build_runtime(gateway)
    if real_adapter:
        from tools.adapters import AdapterResult, BaseCapabilityAdapter
        from tools.receipts import ExecutionMode

        class RealTestAdapter(BaseCapabilityAdapter):
            @property
            def adapter_name(self):
                return "real_test_search"

            def execute(self, capability_id, parameters, timeout_seconds=15.0, *, run_id="", business_id="", project_id=""):
                return AdapterResult(success=True, data={"result": "real observation"}, execution_mode=ExecutionMode.REAL)

        rt.tool_gateway.register_adapter(RealTestAdapter(), aliases=["search_adapter", "image_gen_adapter"])
    ctx = rt.start_run(objective=objective, business_id=business_id)
    rt.execute_stage_cmo_initial(ctx)
    rt.execute_stage_intelligence(ctx)
    rt.execute_stage_strategist(ctx)
    rt.execute_stage_creative(ctx)
    rt.execute_stage_performance(ctx)
    final_out = rt.execute_stage_final_cmo(ctx)
    artifact = rt.complete_run(ctx)
    return rt, ctx, final_out, artifact


def prompts_for(gw, label):
    return [u for (l, u) in gw.calls if l == label]


class TestStructuredEpistemicHandoff(unittest.TestCase):

    # 1/2. CMO objective + constraints preserved structurally
    def test_01_02_cmo_handoff_carries_objective_and_constraints(self):
        gw = StructuredScriptedGateway()
        rt = build_runtime(gw)
        ctx = rt.start_run(objective="quang cao my pham sinh hoc", business_id="BIZ_AUDIT")
        record_constraint(ctx, "Khong duoc noi san pham chua mun.", origin="USER_CONSTRAINT")
        rt.execute_stage_cmo_initial(ctx)

        handoff = ctx.working_state["stage_handoffs"]["cmo_initial"]
        self.assertEqual(handoff["objective"], "quang cao my pham sinh hoc")
        self.assertIn("Khong duoc noi san pham chua mun.", handoff["constraints"])
        self.assertEqual(handoff["source_agent"], "cmo")

    # 3/14/15. CMO unknown reaches Intelligence as UNKNOWN; constraints+unknowns persist downstream
    def test_03_14_15_unknown_and_constraints_flow_to_intelligence(self):
        gw = StructuredScriptedGateway(replies={
            "cmo_initial": ("Delegation framed.", {
                "unknowns": ["Do we know the churn rate? No."],
            }),
        })
        rt = build_runtime(gw)
        ctx = rt.start_run(objective="SaaS growth plan", business_id="BIZ_AUDIT")
        record_constraint(ctx, "Budget phai o duoi 10 trieu VND.", origin="USER_CONSTRAINT")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)

        intel_prompt = prompts_for(gw, "intelligence")[-1]
        self.assertIn("UNKNOWNS — DO NOT INVENT ANSWERS", intel_prompt)
        self.assertIn("churn rate", intel_prompt)
        self.assertIn("[OPEN]", intel_prompt)
        self.assertIn("BINDING CONSTRAINTS & RESTRICTIONS", intel_prompt)
        self.assertIn("10 trieu VND", intel_prompt)

        intel_handoff = ctx.stage_outputs["intelligence"]["handoff"]
        # inherited context fields remain structural in every stage handoff:
        self.assertEqual(intel_handoff["constraints"], ctx.constraints)

    # 4/5. Intelligence UNKNOWN / ASSUMPTION reach Strategist as typed items
    def test_04_05_intelligence_typed_items_reach_strategist(self):
        gw = StructuredScriptedGateway(replies={
            "intelligence": (
                "Analysis prose.", {
                    "unknowns": [{"text": "Churn rate unknown"}],
                    "assumptions": [{"text": "Market keeps current growth pace"}],
                    "facts": [{"text": "Competitor cut prices"}],
                }
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)

        strat_prompt = prompts_for(gw, "strategist")[-1]
        self.assertIn("UNKNOWNS — DO NOT INVENT ANSWERS", strat_prompt)
        self.assertIn("Churn rate unknown", strat_prompt)
        self.assertIn("ASSUMPTIONS — DO NOT TREAT AS FACT", strat_prompt)
        self.assertIn("Market keeps current growth pace", strat_prompt)

        intel_h = ctx.stage_outputs["intelligence"]["handoff"]
        self.assertEqual(intel_h["unknowns"][0]["epistemic_type"], "UNKNOWN")
        self.assertEqual(intel_h["assumptions"][0]["epistemic_type"], "ASSUMPTION")

    # 6/7. FACT with deployable evidence stays; unsupported FACT downgraded
    def test_06_fact_with_real_receipt_keeps_evidence(self):
        gw = StructuredScriptedGateway(replies={
            "intelligence": (
                "Findings prose.", {
                    "facts": [{"text": "Search volume up per tool", "evidence_refs": ["TOOL-RUN-DEPT-001"]}],
                }
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw, real_adapter=True)
        facts = ctx.stage_outputs["intelligence"]["handoff"]["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["verification"], "SOURCE_BACKED")
        self.assertEqual(facts[0]["evidence_refs"], ["TOOL-RUN-DEPT-001"])

    def test_07_unsupported_fact_downgraded_not_verified(self):
        gw = StructuredScriptedGateway(replies={
            "intelligence": (
                "Prose.", {"facts": [{"text": "Rival is failing (no source)"}]},
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)
        h = ctx.stage_outputs["intelligence"]["handoff"]
        self.assertEqual(h["facts"], [])
        downgraded = [i for i in h["observations"] if i["downgraded_from"] == "FACT"]
        self.assertEqual(len(downgraded), 1)
        self.assertEqual(downgraded[0]["verification"], "UNSUPPORTED")
        self.assertIn("deployable evidence", downgraded[0]["downgrade_reason"])
        self.assertTrue(downgraded[0]["item_id"].endswith("-D"))

    # 8/9. strategist hypothesis reaches Creative as HYPOTHESIS (never product fact)
    def test_08_09_strategist_hypothesis_typed_for_creative(self):
        gw = StructuredScriptedGateway(replies={
            "strategist": (
                "Positioning prose.", {
                    "hypotheses": [{"text": "GenZ pays +15% for eco packaging"}],
                }
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)
        creative_prompt = prompts_for(gw, "creative")[-1]
        self.assertIn("HYPOTHESES — REQUIRE TESTING", creative_prompt)
        self.assertIn("+15% for eco packaging", creative_prompt)
        self.assertNotIn("VERIFIED / SOURCE-BACKED INFORMATION\n[VERIFIED] GenZ", creative_prompt)
        strat_h = ctx.stage_outputs["strategist"]["handoff"]["hypotheses"]
        self.assertEqual(strat_h[0]["epistemic_type"], "HYPOTHESIS")

    # 10. creative claim retains cited source ids/evidence refs
    def test_10_creative_claim_keeps_source_binding(self):
        gw = StructuredScriptedGateway(replies={
            "creative": (
                "Creative prose.", {
                    "claims": [{"text": "Serum hydrates per lab test", "source_ids": ["SRC-LAB-1"],
                                "evidence_refs": ["TOOL-RUN-DEPT-001"]}],
                }
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw, real_adapter=True)
        claims = ctx.stage_outputs["creative"]["handoff"]["claims"]
        self.assertEqual(claims[0]["source_ids"], ["SRC-LAB-1"])
        self.assertEqual(claims[0]["evidence_refs"], ["TOOL-RUN-DEPT-001"])
        self.assertEqual(claims[0]["verification"], "SOURCE_BACKED")

    # 11. performance receives creative claims/hypotheses structurally
    def test_11_performance_receives_creative_structured_items(self):
        gw = StructuredScriptedGateway(replies={
            "creative": (
                "Creative prose.", {
                    "claims": [{"text": "Demo claim A"}],
                    "hypotheses": [{"text": "Hook H1 could lift CTR"}],
                }
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)
        perf_prompt = prompts_for(gw, "performance")[-1]
        # Unsupported claim is deterministically demoted to an observation
        # (monotonicity) and rendered with visible lineage — never as a
        # verified/standing claim.
        self.assertIn("=== OBSERVATIONS ===", perf_prompt)
        self.assertIn("Demo claim A", perf_prompt)
        self.assertIn("downgraded from FACT", perf_prompt)
        self.assertIn("[UNSUPPORTED", perf_prompt)
        self.assertNotIn("CLAIMS UNDER EVALUATION", perf_prompt)
        self.assertIn("HYPOTHESES — REQUIRE TESTING", perf_prompt)
        self.assertIn("Hook H1 could lift CTR", perf_prompt)

    # 12/13. INCONCLUSIVE travels structurally; Final cannot upgrade it
    def test_12_13_inconclusive_structural_and_not_overridable(self):
        gw = StructuredScriptedGateway(replies={
            "performance": (
                "RESULT: INCONCLUSIVE sample too small.", {}
            ),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)
        perf_h = ctx.stage_outputs["performance"]["handoff"]
        self.assertIs(perf_h["performance_inconclusive"], True)

        final_prompt = prompts_for(gw, "final_cmo")[-1]
        self.assertIn("PERFORMANCE STATUS: INCONCLUSIVE (STRUCTURAL", final_prompt)

        self.assertEqual(final_out["approval_status"], "BLOCKED")
        self.assertEqual(final_out["status"], "NOT_READY")

    # 16/17. checkpoint + artifact persistence
    def test_16_17_handoff_survives_checkpoint_and_artifact(self):
        gw = StructuredScriptedGateway(replies={
            "intelligence": ("Prose.", {"observations": [{"text": "Obs one"}]}),
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)

        snap = ctx.checkpoints[-1].working_state_snapshot
        self.assertIn("stage_handoffs", snap)
        self.assertIn("intelligence", snap["stage_handoffs"])
        self.assertEqual(snap["stage_handoffs"]["intelligence"]["observations"][0]["text"], "Obs one")

        self.assertIsInstance(artifact.epistemic_handoffs, dict)
        self.assertEqual(
            artifact.epistemic_handoffs,
            ctx.working_state["stage_handoffs"],
        )
        dumped = artifact.model_dump()
        self.assertIn("epistemic_handoffs", dumped)

    # 18/19. isolation
    def test_18_19_no_cross_chat_or_cross_brand_leakage(self):
        gw_a = StructuredScriptedGateway(replies={
            "intelligence": ("Prose.", {"unknowns": [{"text": "Brand A secret gap"}]}),
        })
        rt_a = build_runtime(gw_a)
        ctx_a = rt_a.start_run(objective="A plan", business_id="BIZ_BRAND_A")
        rt_a.execute_stage_cmo_initial(ctx_a)
        rt_a.execute_stage_intelligence(ctx_a)

        gw_b = StructuredScriptedGateway()
        rt_b = build_runtime(gw_b)
        ctx_b = rt_b.start_run(objective="B plan", business_id="BIZ_BRAND_B")
        rt_b.execute_stage_cmo_initial(ctx_b)

        b_block = rt_b._append_governance_block(ctx_b, "base")
        self.assertNotIn("Brand A secret gap", b_block)

    # 20/21. mock tier & failed receipts cannot support facts
    def test_20_21_non_deployable_evidence_cannot_verify_fact(self):
        prov = {
            "TOOL-MOCK-1": {"epistemic_tier": "MOCK_OR_SANDBOX"},
            "TOOL-GONE-1": None,
        }
        item_mock = build_epistemic_item(EpistemicType.FACT, {"text": "x", "evidence_refs": ["TOOL-MOCK-1"]}, 1, "INTELLIGENCE", "intelligence", prov)
        item_missing = build_epistemic_item(EpistemicType.FACT, {"text": "y", "evidence_refs": ["TOOL-GONE-1"]}, 2, "INTELLIGENCE", "intelligence", prov)
        self.assertEqual(item_mock.epistemic_type, "OBSERVATION")
        self.assertEqual(item_missing.epistemic_type, "OBSERVATION")

    # 22. malformed structured payload fabricates nothing
    def test_22_malformed_payload_yields_empty_not_fabricated(self):
        raw = "Analysis.\n\n=== STRUCTURED HANDOFF ===\n```json\n{not valid json\n```"
        status, payload = extract_handoff_payload(raw)
        self.assertEqual(status, "MALFORMED")
        self.assertIsNone(payload)

        gw = StructuredScriptedGateway(replies={
            "intelligence": "Prose part.\n\n" + raw.split("\n\n", 1)[1],
        })
        rt, ctx, final_out, artifact = run_pipeline(gw)
        h = ctx.stage_outputs["intelligence"]["handoff"]
        self.assertEqual(h["structured_parse_status"], "MALFORMED")
        self.assertEqual(h["facts"], [])
        self.assertEqual(h["unknowns"], [])
        # raw free text preserved verbatim including malformed block:
        self.assertEqual(ctx.stage_outputs["intelligence"]["market_findings"],
                         "Prose part.\n\n" + raw.split("\n\n", 1)[1])

    # 23. absent payload does not crash pipeline; parse status ABSENT
    def test_23_absent_payload_pipeline_runs(self):
        gw = StructuredScriptedGateway()
        rt, ctx, final_out, artifact = run_pipeline(gw)
        for stage in ("cmo_initial", "intelligence", "strategist", "creative", "performance", "final_cmo"):
            h = ctx.stage_outputs[stage]["handoff"]
            self.assertEqual(h["structured_parse_status"], "ABSENT")
        self.assertEqual(final_out["status"] in ("READY_FOR_DEPLOYMENT", "NOT_READY"), True)

    # 24. free-text outputs remain verbatim
    def test_24_free_text_preserved_verbatim(self):
        text = "POSITIONING Z: urban professionals first."
        gw = StructuredScriptedGateway(replies={"strategist": text})
        rt, ctx, final_out, artifact = run_pipeline(gw)
        self.assertEqual(ctx.stage_outputs["strategist"]["positioning"], text)

    # 25. five-agent invariant exact
    def test_25_five_agent_invariant(self):
        from governance.access_matrix import PERMANENT_FIVE_AGENTS
        self.assertEqual(PERMANENT_FIVE_AGENTS, {"cmo", "intelligence", "strategist", "creative", "performance"})
        rt = build_runtime(StructuredScriptedGateway())
        self.assertEqual(len({m for m in dir(rt) if m.startswith("execute_stage_")}), 6)


if __name__ == "__main__":
    unittest.main()
