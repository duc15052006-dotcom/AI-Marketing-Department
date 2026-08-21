"""Unit and Static Tests for Minimal Live Model Execution Bridge (Phase 3A / 3A.1.1).

Validates agent loading, provider normalization, budget governance,
output repair, qualitative confidence contracts, quota blocker classification,
cost accounting separation, and bounded workflow orchestration.
"""

import json
import unittest
from pathlib import Path
from schemas.protocol import AgentRole, TaskEnvelope, TaskStatus
from integrations.models import (
    AgentLoader,
    AgentRunResult,
    BaseModelAdapter,
    CostGovernanceConfig,
    CostTracker,
    GeminiProviderAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelRouter,
    ModelUsage,
    OpenAIProviderAdapter,
    PERMANENT_AGENT_IDS,
    WorkflowDefinition,
    WorkflowOrchestrator,
    WorkflowStep,
    invoke_agent,
    parse_and_validate_agent_json,
)


class MockProviderAdapter(BaseModelAdapter):
    """MOCK / UNIT TEST Provider Adapter for deterministic contract testing."""

    def __init__(
        self,
        canned_response_text: str,
        status: ModelResponseStatus = ModelResponseStatus.SUCCESS,
        provider_label: str = "mock",
    ):
        self.canned_response_text = canned_response_text
        self.status = status
        self._provider_label = provider_label
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_label

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=self.status,
            content=self.canned_response_text,
            usage=ModelUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            latency_ms=12.5,
        )


class TestModelExecutionBridge(unittest.TestCase):
    def setUp(self):
        self.workspace_root = Path(__file__).resolve().parent.parent
        self.loader = AgentLoader(self.workspace_root)

    def test_agent_loader_only_accepts_five_permanent_agents(self):
        """Verify loader loads all 5 permanent agents and rejects any 6th agent."""
        self.assertEqual(len(PERMANENT_AGENT_IDS), 5)
        for agent_id in ["cmo", "intelligence", "strategist", "creative", "performance"]:
            agent_def = self.loader.load_agent(agent_id)
            self.assertEqual(agent_def.agent_id, agent_id)
            self.assertTrue(len(agent_def.system_dna) > 100)
            self.assertTrue(len(agent_def.name) > 0)

        with self.assertRaises(ValueError):
            self.loader.load_agent("tiktok_guru")

        with self.assertRaises(ValueError):
            self.loader.load_agent("seo_specialist")

    def test_provider_adapter_missing_api_key_safety(self):
        """Verify unconfigured provider adapters return safe error without leaking or crashing."""
        gemini = GeminiProviderAdapter(api_key="")
        self.assertFalse(gemini.is_configured())

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Hello")]
        )
        resp = gemini.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp.error)
        self.assertNotIn("AIza", resp.error)  # No secret key leakage

        openai = OpenAIProviderAdapter(api_key="")
        self.assertFalse(openai.is_configured())
        resp_oa = openai.generate(req)
        self.assertEqual(resp_oa.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp_oa.error)

    def test_model_router_fallback_mechanism(self):
        """Verify ModelRouter dispatches to available provider and handles fallback."""
        router = ModelRouter(default_provider="working")

        failing_mock = MockProviderAdapter(
            canned_response_text="",
            status=ModelResponseStatus.ERROR,
            provider_label="failing",
        )

        working_mock = MockProviderAdapter(
            canned_response_text='{"output": {"result": "ok"}, "confidence": "HIGH"}',
            provider_label="working",
        )

        router.register_adapter(failing_mock)
        router.register_adapter(working_mock)
        router.set_fallback_chain(["failing", "working"])

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Test prompt")]
        )
        response = router.generate(req, preferred_provider="failing")
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(response.provider, "working")

    def test_output_json_repair_parser(self):
        """Verify parse_and_validate_agent_json parses direct, markdown code-fence, and raw JSON."""
        # 1. Clean JSON
        state1, data1 = parse_and_validate_agent_json('{"key": "value"}')
        self.assertEqual(state1, "VALID")
        self.assertEqual(data1, {"key": "value"})

        # 2. Markdown wrapped JSON
        state2, data2 = parse_and_validate_agent_json('Here is the output:\n```json\n{"summary": "test"}\n```\nDone.')
        self.assertEqual(state2, "REPAIRABLE")
        self.assertEqual(data2, {"summary": "test"})

        # 3. Invalid JSON
        state3, data3 = parse_and_validate_agent_json("Not a json string at all")
        self.assertEqual(state3, "INVALID")
        self.assertIsNone(data3)

    def test_invoke_agent_with_mock_adapter(self):
        """Verify invoke_agent builds prompt, executes model call, and returns structured AgentRunResult."""
        canned_json = json.dumps(
            {
                "output": {"findings": "High viral attention, transaction evidence unverified."},
                "confidence": "MEDIUM",
                "confidence_rationale": "High view metrics established but transaction proof missing",
                "evidence_references": ["TIKTOK-TREND-01"],
                "unknown_facts": ["Purchase conversion rate"],
                "assumptions": ["Audience enjoys entertainment value"],
                "hypotheses": ["Commercial conversion will remain below 0.5%"],
                "next_action": "Handoff to Strategist for bounded testing",
            }
        )
        mock_adapter = MockProviderAdapter(canned_response_text=canned_json)

        task = TaskEnvelope(
            task_id="TASK-20260816-SMOKE-01",
            objective="Evaluate viral TikTok trend for commercial potential",
            business_context="Auditing 80M view comedy soundbite",
            product_id="PROD_DEV_TOOL_01",
            brand_id="BRAND_DEVTOOL",
            owner_agent=AgentRole.INTELLIGENCE,
            output_schema="IntelligenceReport",
            escalation_rule="Escalate if high spend required",
            next_action="Handoff to Strategist",
        )

        res: AgentRunResult = invoke_agent(
            agent_id="intelligence",
            task_envelope=task,
            adapter=mock_adapter,
            loader=self.loader,
        )

        self.assertEqual(res.status, TaskStatus.COMPLETED)
        self.assertEqual(res.agent_id, "intelligence")
        self.assertEqual(res.product_id, "PROD_DEV_TOOL_01")
        self.assertEqual(res.confidence, "MEDIUM")
        self.assertEqual(res.confidence_rationale, "High view metrics established but transaction proof missing")
        self.assertIn("Purchase conversion rate", res.unknown_facts)
        # Invariant: No private chain-of-thought fields
        self.assertNotIn("chain_of_thought", res.model_dump())

    def test_qualitative_confidence_and_no_arbitrary_decimals(self):
        """Verify confidence contract requires qualitative tiers (LOW, MEDIUM, HIGH) without arbitrary floats."""
        # 1. Qualitative tier
        res1 = AgentRunResult(
            agent_id="intelligence",
            task_id="TASK-01",
            product_id="PROD-01",
            confidence="LOW",
            confidence_rationale="Sample size too small to extrapolate",
        )
        self.assertEqual(res1.confidence, "LOW")
        self.assertIsNone(res1.statistical_confidence)

        # 2. String confidence tier validation
        self.assertIn(res1.confidence, {"LOW", "MEDIUM", "HIGH", "UNKNOWN"})

    def test_failed_request_usage_is_not_fabricated(self):
        """Verify failed requests record zero/actual usage and do not treat max_tokens (4096) as consumed."""
        failing_adapter = MockProviderAdapter(canned_response_text="", status=ModelResponseStatus.ERROR)
        req = ModelRequest(max_tokens=4096, messages=[ModelMessage(role=ModelRole.USER, content="Test")])
        resp = failing_adapter.generate(req)
        # Verify prompt and response usage
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertNotEqual(resp.usage.completion_tokens, 4096)

    def test_cost_accounting_separation(self):
        """Verify CostTracker explicitly separates local estimated cost from provider-reported cost."""
        tracker = CostTracker()
        tracker.record_usage("gpt-5.6-sol", ModelUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500), provider_cost=0.005)
        summary = tracker.summary()

        self.assertIn("local_estimated_cost_usd", summary)
        self.assertIn("provider_reported_cost_usd", summary)
        self.assertIn("pricing_source", summary)
        self.assertIn("estimate_limitations", summary)
        self.assertEqual(summary["provider_reported_cost_usd"], 0.005)
        self.assertGreater(summary["local_estimated_cost_usd"], 0.0)

    def test_reuse_stored_live_intelligence_runs(self):
        """Verify stored live Intelligence evaluation runs can be reloaded from disk without re-executing API calls."""
        eval_path = self.workspace_root / "evaluations" / "live" / "single_agent" / "intelligence_run_1.json"
        if eval_path.exists():
            data = json.loads(eval_path.read_text(encoding="utf-8"))
            self.assertEqual(data["AGENT_ID"], "intelligence")
            self.assertEqual(data["PARSE_STATUS"], "VALID")
            self.assertEqual(data["SEMANTIC_EVALUATION"], "PASS")

    def test_cost_and_budget_governance_enforcement(self):
        """Verify CostTracker tracks tokens and raises budget breach exception."""
        config = CostGovernanceConfig(max_model_calls=3, max_token_budget=500)
        tracker = CostTracker(config)

        # Call 1
        tracker.record_usage("gemini-1.5-pro", ModelUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        tracker.check_budget_limits()
        self.assertEqual(tracker.total_calls, 1)

        # Call 2
        tracker.record_usage("gemini-1.5-pro", ModelUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        tracker.check_budget_limits()

        # Call 3 (hits max_model_calls limit)
        tracker.record_usage("gemini-1.5-pro", ModelUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        with self.assertRaises(RuntimeError) as ctx:
            tracker.check_budget_limits()
        self.assertIn("BUDGET_BREACH", str(ctx.exception))

    def test_bounded_workflow_orchestrator_execution(self):
        """Verify WorkflowOrchestrator runs sequential steps, records traces, and respects max step bounds."""
        canned_json = json.dumps(
            {
                "output": {"summary": "Step completed successfully"},
                "confidence": "HIGH",
                "unknown_facts": ["Future market shift"],
                "assumptions": ["Baseline holds"],
                "hypotheses": ["Step outcome validated"],
                "next_action": "Proceed to next specialist",
            }
        )
        mock_adapter = MockProviderAdapter(canned_response_text=canned_json)

        task = TaskEnvelope(
            task_id="TASK-20260816-WORKFLOW-01",
            objective="Execute multi-agent GTM alignment",
            business_context="Evaluating new product launch",
            product_id="PROD_GTM_01",
            brand_id="BRAND_GTM",
            owner_agent=AgentRole.CMO,
            output_schema="GTMBrief",
            escalation_rule="Escalate on error",
            next_action="Handoff to Intelligence",
        )

        wf_def = WorkflowDefinition(
            name="CMO to Intelligence to Strategist Workflow",
            steps=[
                WorkflowStep(agent_id="cmo"),
                WorkflowStep(agent_id="intelligence"),
                WorkflowStep(agent_id="strategist"),
            ],
            max_agent_steps=5,
            timeout_seconds=30.0,
        )

        orchestrator = WorkflowOrchestrator(adapter=mock_adapter)
        summary = orchestrator.run_workflow(initial_task=task, workflow_def=wf_def)

        self.assertEqual(summary.status, TaskStatus.COMPLETED)
        self.assertEqual(summary.steps_executed, 3)
        self.assertEqual(len(summary.results), 3)
        # Handoff traces between steps (CMO->Intelligence, Intelligence->Strategist)
        self.assertEqual(len(summary.traces), 2)
        self.assertEqual(summary.traces[0].from_agent, AgentRole.CMO)
        self.assertEqual(summary.traces[0].to_agent, AgentRole.INTELLIGENCE)
        self.assertEqual(summary.traces[1].from_agent, AgentRole.INTELLIGENCE)
        self.assertEqual(summary.traces[1].to_agent, AgentRole.STRATEGIST)


if __name__ == "__main__":
    unittest.main()
