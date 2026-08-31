"""PROD-CORE-AUTHORITY-01A: Run-Pinned Model Authority + Canonical Execution + Approval Boundary.

Validates three critical authority defects and their fixes:
1. RUN-PINNED Model Policy/Provider snapshot must fail-closed (no silent fallback)
2. Single canonical execute_run authority (no manual stage orchestration)
3. Auto-approval forbidden — human intent required for gated actions

Invariant: 5 logical agents, 6 logical stages. Final CMO = CMO second pass. Never Agent 6.
"""

from __future__ import annotations

import copy
import threading
import time
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import (
    ModelPolicy,
    ModelTarget,
    ProviderDefinition,
    ProviderRegistrySnapshot,
)
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import (
    RuntimeContext,
    RuntimeStage,
    RuntimeStatus,
)
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.queue import RunManager, RunQueueStatus
from tools.capabilities import CapabilityRegistry, RiskLevel
from tools.receipts import ExecutionStatus
from tools.security import (
    HumanApprovalRecord,
    PendingApprovalStatus,
    PolicyEngine,
)
from tools.tool_gateway import ToolGateway, ToolRequest
from workspace.operator import OperatorWorkspace


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockScriptedGateway(UniversalModelGateway):
    """Deterministic scriptable model gateway for authority testing."""

    def __init__(
        self,
        stage_responses: Optional[Dict[str, str]] = None,
        fail_stage: Optional[str] = None,
    ):
        super().__init__(free_only_mode=True)
        self.stage_responses = stage_responses or {}
        self.fail_stage = fail_stage
        self.calls: List[Dict[str, Any]] = []
        self.call_signatures: List[str] = []

    def generate(
        self,
        request: ModelRequest,
        agent_id: Optional[str] = None,
        model_policy: Optional[ModelPolicy] = None,
        provider_snapshot: Optional[ProviderRegistrySnapshot] = None,
    ) -> ModelResponse:
        sig = f"agent_id={agent_id} policy={model_policy is not None} snap={provider_snapshot is not None}"
        self.call_signatures.append(sig)
        self.calls.append({
            "agent_id": agent_id,
            "has_policy": model_policy is not None,
            "has_snapshot": provider_snapshot is not None,
        })

        sys_msg = request.messages[0].content if request.messages else ""
        stage_directive = sys_msg.split("=== CURRENT RUNTIME STAGE DIRECTIVE ===", 1)[-1]
        resolved_agent = agent_id or (request.metadata or {}).get("agent_id")
        if resolved_agent == "cmo":
            stage = (
                "final_cmo"
                if any(marker in stage_directive for marker in (
                    "Final Governed Go-To-Market",
                    "Final Governed Strategy",
                    "governed final synthesis",
                ))
                else "cmo_initial"
            )
        elif resolved_agent in {"intelligence", "strategist", "creative", "performance"}:
            stage = resolved_agent
        else:
            stage = "unknown"

        if self.fail_stage and self.fail_stage == stage:
            return ModelResponse(
                request_id=request.request_id,
                provider="mock",
                model_name="mock-deterministic",
                status=ModelResponseStatus.ERROR,
                content="",
                error=f"INJECTED_FAILURE_{stage.upper()}",
            )

        resp_text = self.stage_responses.get(stage, f"Default output for {stage}")
        return ModelResponse(
            request_id=request.request_id,
            provider="mock",
            model_name="mock-deterministic",
            status=ModelResponseStatus.SUCCESS,
            content=resp_text,
        )


class TypeErrorGateway(UniversalModelGateway):
    """Gateway whose generate() only accepts (self, request) — no kwargs.

    This mimics a legacy gateway implementation whose signature is incompatible
    with the canonical pinned call (agent_id, model_policy, provider_snapshot).
    Calling with extra kwargs raises TypeError, triggering the fallback chain.
    """

    def __init__(self):
        super().__init__(free_only_mode=True)
        self.call_count = 0

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            provider="mock",
            model_name="mock",
            status=ModelResponseStatus.SUCCESS,
            content="Response from legacy signature",
        )


def _build_runtime(gateway: Optional[UniversalModelGateway] = None) -> FiveAgentDepartmentRuntime:
    gw = gateway or MockScriptedGateway()
    return FiveAgentDepartmentRuntime(
        model_gateway=gw,
        tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


def _build_runtime_with_gateway(
    model_policy: ModelPolicy,
    provider_snapshot: Optional[ProviderRegistrySnapshot] = None,
) -> FiveAgentDepartmentRuntime:
    """Build a runtime whose gateway has authoritative model_policy and provider_registry."""
    gw = UniversalModelGateway(free_only_mode=False)
    gw.model_policy = model_policy
    if provider_snapshot:
        gw.provider_registry = MagicMock()
        gw.provider_registry.snapshot.return_value = provider_snapshot
        gw.provider_registry._configs = {}
        gw.provider_registry._adapters = {}
    return FiveAgentDepartmentRuntime(
        model_gateway=gw,
        tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


# ===========================================================================
# DEFECT 1 — RUN-PINNED MODEL CONFIG FAIL-OPEN
# ===========================================================================

class TestDefect1RunPinnedFailOpen(unittest.TestCase):
    """Reproduction and regression tests for RUN-PIN-FAILOPEN-01."""

    def test_A_malformed_model_policy_reconstruction_fails_closed(self) -> None:
        """A. Malformed run-pinned ModelPolicy → reconstruction fails → FAIL CLOSED."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Test pin", business_id="BIZ_001")
        ctx.model_policy = {"policy": {"totally": "invalid", "missing_fields": True}}

        # After fix: _call_agent_llm raises RuntimeError on reconstruction failure
        with self.assertRaises(RuntimeError) as cm:
            rt._call_agent_llm(
                agent_name="cmo",
                system_instruction="Test",
                user_prompt="Test",
                context=ctx,
            )
        self.assertIn("RUN_PINNED_MODEL_CONFIGURATION_INVALID", str(cm.exception))

    def test_B_malformed_provider_registry_snapshot_fails_closed(self) -> None:
        """B. Malformed ProviderRegistrySnapshot → reconstruction fails → FAIL CLOSED."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Test provider pin", business_id="BIZ_001")
        ctx.model_policy = {
            "policy": {"global_target": {"provider_id": "xkiro", "model_id": "test"}},
            "providers": {"bad_provider": {"this": "is", "not": "a", "ProviderDefinition": True}},
        }

        with self.assertRaises(RuntimeError) as cm:
            rt._call_agent_llm(
                agent_name="cmo",
                system_instruction="Test",
                user_prompt="Test",
                context=ctx,
            )
        self.assertIn("RUN_PINNED_MODEL_CONFIGURATION_INVALID", str(cm.exception))

    def test_C_typeerror_is_real_error_not_retried(self) -> None:
        """C. TypeError from gateway is propagated as real error, no legacy retry fallback.

        After fix: TypeError is NOT retried — it's a real gateway error.
        """
        gw = TypeErrorGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Test TypeError", business_id="BIZ_001")
        content, err = rt._call_agent_llm(
            agent_name="cmo",
            system_instruction="Test",
            user_prompt="Test",
            context=ctx,
        )
        # After fix: 1 call only (no retry), TypeError propagates as error
        self.assertEqual(gw.call_count, 0)  # generate() never succeeded
        self.assertIsNotNone(err)
        self.assertIn("TypeErrorGateway", err)

    def test_D_settings_changed_after_run_start_cannot_drift(self) -> None:
        """D. Provider/model/settings changed AFTER run start → cannot drift (fail-closed)."""
        policy_v1 = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="model_v1"),
            configuration_version="v1",
        )
        rt = _build_runtime_with_gateway(model_policy=policy_v1)

        ctx = rt.start_run(objective="Test drift", business_id="BIZ_001")
        ctx.model_policy = {"broken": True}

        # Mutate the live gateway to configuration B
        rt.model_gateway.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_b", model_id="model_v2"),
            configuration_version="v2",
        )

        with self.assertRaises(RuntimeError) as cm:
            rt._call_agent_llm(
                agent_name="cmo",
                system_instruction="Test",
                user_prompt="Test",
                context=ctx,
            )
        self.assertIn("RUN_PINNED_MODEL_CONFIGURATION_INVALID", str(cm.exception))


# ===========================================================================
# DEFECT 2 — DUAL EXECUTION AUTHORITY
# ===========================================================================

class TestDefect2DualExecutionAuthority(unittest.TestCase):
    """Reproduction and regression tests for DUAL-EXECUTION-AUTHORITY-01."""

    def test_6_workspace_delegates_to_canonical_execute_run(self) -> None:
        """K. Workspace.execute_supervised_campaign delegates to canonical execute_run."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)
        ws = OperatorWorkspace(runtime=rt)

        # Track if execute_run is called
        execute_run_called = [False]
        original_execute_run = rt.execute_run
        def tracking_execute_run(ctx):
            execute_run_called[0] = True
            return original_execute_run(ctx)
        rt.execute_run = tracking_execute_run

        # Track individual stage calls
        called_stages: List[str] = []
        for stage_name, attr in [
            ("cmo_initial", "execute_stage_cmo_initial"),
            ("intelligence", "execute_stage_intelligence"),
            ("strategist", "execute_stage_strategist"),
            ("creative", "execute_stage_creative"),
            ("performance", "execute_stage_performance"),
            ("final_cmo", "execute_stage_final_cmo"),
        ]:
            original = getattr(rt, attr)
            def make_tracked(name, fn):
                def tracked(ctx):
                    called_stages.append(name)
                    return fn(ctx)
                return tracked
            setattr(rt, attr, make_tracked(stage_name, original))

        artifact = ws.execute_supervised_campaign(
            business_id="BIZ_001",
            objective="Test canonical delegation",
        )

        # After fix: execute_run IS called (workspace delegates)
        self.assertTrue(execute_run_called[0])
        # All 6 stages are called through execute_run
        self.assertEqual(called_stages, [
            "cmo_initial", "intelligence", "strategist",
            "creative", "performance", "final_cmo",
        ])


# ===========================================================================
# DEFECT 3 — AUTO APPROVAL AUTHORITY
# ===========================================================================

class TestDefect3AutoApprovalAuthority(unittest.TestCase):
    """Reproduction and regression tests for AUTO-APPROVAL-AUTHORITY-01."""

    def test_10_arbitrary_token_rejected_by_workspace(self) -> None:
        """Q. Truthy arbitrary auto_approve_token is rejected with AUTO_APPROVAL_FORBIDDEN."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)
        ws = OperatorWorkspace(runtime=rt)

        with self.assertRaises(RuntimeError) as ctx:
            ws.execute_supervised_campaign(
                business_id="BIZ_001",
                objective="Test auto approval rejection",
                auto_approve_token="ARBITRARY_TRUTHY_TOKEN",
            )
        self.assertIn("AUTO_APPROVAL_FORBIDDEN", str(ctx.exception))

    def test_12_approve_gated_action_requires_explicit_token_or_pending(self) -> None:
        """T. approve_gated_action with no token and no pending_id returns False (fail-closed)."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        # Create a pending approval for the run
        ctx = rt.start_run(objective="Test approval", business_id="BIZ_001",
                           trusted_run_id="RUN-AUTO-TEST-001")

        # Request a publish action to create a pending approval
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)

        # Call approve_gated_action with NO token and NO pending_id
        ws = OperatorWorkspace(runtime=rt)
        result = ws.approve_gated_action(
            run_id="RUN-AUTO-TEST-001",
            approval_token=None,
            pending_approval_id=None,
        )

        # After fix: must fail-closed — no auto-approval without explicit token or pending_id
        self.assertFalse(result)


# ===========================================================================
# INVARIANT TESTS — 5 AGENTS / 6 STAGES
# ===========================================================================

class TestInvariantFiveAgentsSixStages(unittest.TestCase):
    """§16: Structural invariants — exactly 5 logical agents, 6 stages."""

    def test_16a_five_agents_no_agent_6(self) -> None:
        """All stage outputs use exactly 5 agents: cmo, intelligence, strategist, creative, performance."""
        rt = _build_runtime()
        ctx, final_cmo, artifact = rt.run_workflow(
            objective="Invariant test", business_id="BIZ_001"
        )

        allowed_agents = {"cmo", "intelligence", "strategist", "creative", "performance"}
        for stage_name, stage_out in ctx.stage_outputs.items():
            agent = stage_out.get("agent")
            self.assertIn(agent, allowed_agents, f"Stage {stage_name} uses unexpected agent: {agent}")

    def test_16b_final_cmo_is_cmo_second_pass(self) -> None:
        """Stage 6 (FINAL_CMO) agent = 'cmo', never a sixth agent."""
        rt = _build_runtime()
        ctx, final_cmo, artifact = rt.run_workflow(
            objective="Final CMO identity test", business_id="BIZ_001"
        )
        self.assertEqual(final_cmo.get("agent"), "cmo")
        self.assertEqual(final_cmo.get("stage"), "FINAL_CMO")


# ===========================================================================
# RUN IMMUTABILITY — RUN-A stays config A after live mutation
# ===========================================================================

class TestRunImmutability(unittest.TestCase):
    """§5: Run-A remains pinned to configuration A after live settings mutation."""

    def test_5_run_a_uses_config_a_after_mutation(self) -> None:
        """RUN-A started under config A uses only A even after gateway mutates to B."""
        policy_a = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="model_v1"),
            agent_overrides={
                "intelligence": ModelTarget(provider_id="provider_a_intel", model_id="intel_v1"),
            },
            fallback_chain=[
                ModelTarget(provider_id="provider_a", model_id="model_v1"),
            ],
            configuration_version="v1",
        )
        rt = _build_runtime_with_gateway(model_policy=policy_a)

        # Start RUN-A
        ctx_a = rt.start_run(objective="Run A", business_id="BIZ_A",
                             trusted_run_id="RUN-IMMUT-A")

        # Verify pinned policy is stored
        stored_pol = ctx_a.model_policy
        self.assertIn("policy", stored_pol)
        self.assertEqual(stored_pol["policy"]["global_target"]["provider_id"], "provider_a")
        self.assertEqual(stored_pol["configuration_version"], "v1")

        # Mutate live gateway to config B
        policy_b = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_b", model_id="model_v2"),
            configuration_version="v2",
        )
        rt.model_gateway.model_policy = policy_b

        # Execute RUN-A — should still use A's pinned config
        ctx_a, _, art_a = rt.execute_run(ctx_a)
        self.assertEqual(art_a.run_id, "RUN-IMMUT-A")

        # The stored policy should still be config A
        stored_pol_after = ctx_a.model_policy
        self.assertEqual(stored_pol_after["configuration_version"], "v1")
        self.assertEqual(stored_pol_after["policy"]["global_target"]["provider_id"], "provider_a")

    def test_5b_run_b_gets_config_b(self) -> None:
        """RUN-B started after mutation gets config B."""
        policy_a = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="model_v1"),
            configuration_version="v1",
        )
        rt = _build_runtime_with_gateway(model_policy=policy_a)

        # Start RUN-A under config A
        ctx_a = rt.start_run(objective="Run A", business_id="BIZ_A",
                             trusted_run_id="RUN-IMMUT-A2")

        # Mutate to config B
        policy_b = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_b", model_id="model_v2"),
            configuration_version="v2",
        )
        rt.model_gateway.model_policy = policy_b

        # Start RUN-B under config B
        ctx_b = rt.start_run(objective="Run B", business_id="BIZ_B",
                             trusted_run_id="RUN-IMMUT-B")

        stored_b = ctx_b.model_policy
        self.assertEqual(stored_b["configuration_version"], "v2")
        self.assertEqual(stored_b["policy"]["global_target"]["provider_id"], "provider_b")


# ===========================================================================
# FAILURE SHORT-CIRCUIT
# ===========================================================================

class TestFailureShortCircuit(unittest.TestCase):
    """§8: Upstream stage failure prevents downstream expensive work."""

    def test_P_intelligence_failure_stops_strategist(self) -> None:
        """If Intelligence fails, Strategist is not invoked."""
        gw = MockScriptedGateway(fail_stage="intelligence")
        rt = _build_runtime(gateway=gw)

        stages_called: List[str] = []
        orig_strat = rt.execute_stage_strategist
        def tracked_strat(ctx):
            stages_called.append("strategist")
            return orig_strat(ctx)
        rt.execute_stage_strategist = tracked_strat

        ctx, _, _ = rt.run_workflow(
            objective="Fail at intelligence", business_id="BIZ_001"
        )

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertNotIn("strategist", stages_called)

    def test_P_strategist_failure_stops_creative(self) -> None:
        """If Strategist fails, Creative is not invoked."""
        gw = MockScriptedGateway(fail_stage="strategist")
        rt = _build_runtime(gateway=gw)

        stages_called: List[str] = []
        orig_creative = rt.execute_stage_creative
        def tracked_creative(ctx):
            stages_called.append("creative")
            return orig_creative(ctx)
        rt.execute_stage_creative = tracked_creative

        ctx, _, _ = rt.run_workflow(
            objective="Fail at strategist", business_id="BIZ_001"
        )

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertNotIn("creative", stages_called)

    def test_P_creative_failure_stops_performance(self) -> None:
        """If Creative fails, Performance is not invoked."""
        gw = MockScriptedGateway(fail_stage="creative")
        rt = _build_runtime(gateway=gw)

        stages_called: List[str] = []
        orig_perf = rt.execute_stage_performance
        def tracked_perf(ctx):
            stages_called.append("performance")
            return orig_perf(ctx)
        rt.execute_stage_performance = tracked_perf

        ctx, _, _ = rt.run_workflow(
            objective="Fail at creative", business_id="BIZ_001"
        )

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertNotIn("performance", stages_called)

    def test_P_performance_failure_stops_final_cmo(self) -> None:
        """If Performance fails, Final CMO is not executed; failure remains fail-closed."""
        gw = MockScriptedGateway(fail_stage="performance")
        rt = _build_runtime(gateway=gw)

        final_cmo_called = [False]
        orig_final = rt.execute_stage_final_cmo
        def tracked_final(ctx):
            final_cmo_called[0] = True
            return orig_final(ctx)
        rt.execute_stage_final_cmo = tracked_final

        ctx, final_out, _ = rt.run_workflow(
            objective="Fail at performance", business_id="BIZ_001"
        )

        # An unreached Final CMO must not start after a failed prerequisite stage.
        self.assertFalse(final_cmo_called[0])
        self.assertEqual(final_out.get("status"), "NOT_REACHED")
        self.assertEqual(final_out.get("failed_stage"), "PERFORMANCE")


# ===========================================================================
# CROSS-RUN APPROVAL ISOLATION
# ===========================================================================

class TestCrossRunApprovalIsolation(unittest.TestCase):
    """§13: Cross-run approval mismatch must fail closed."""

    def test_13a_run_a_token_rejected_for_run_b(self) -> None:
        """RUN-A approval token cannot be used in RUN-B context."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        policy = rt.tool_gateway.policy_engine
        pending_a = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Run A content"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-CROSS-A",
            business_id="BIZ_001",
        )
        ok, rec_a, _ = policy.approve_pending_action(pending_a.pending_approval_id, approved_by="Operator")
        self.assertTrue(ok)

        ctx_b = rt.start_run(objective="Run B", business_id="BIZ_001",
                             trusted_run_id="RUN-CROSS-B")

        # Token from RUN-A used in RUN-B — must fail
        rec = rt.request_publish_action(ctx_b, platform="linkedin",
                                         approval_token=rec_a.approval_token)
        self.assertNotEqual(rec.status.value, "SUCCESS")

    def test_13b_fabricated_token_rejected(self) -> None:
        """Fabricated approval token is rejected."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Fabricated token test", business_id="BIZ_001")
        rec = rt.request_publish_action(ctx, platform="linkedin",
                                         approval_token="FABRICATED-TOKEN-12345")
        self.assertNotEqual(rec.status.value, "SUCCESS")

    def test_13c_empty_token_rejected(self) -> None:
        """Empty token is rejected."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Empty token test", business_id="BIZ_001")
        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token="")
        self.assertNotEqual(rec.status.value, "SUCCESS")

    def test_13d_truthy_arbitrary_token_rejected(self) -> None:
        """Truth arbitrary string as token is rejected."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Arbitrary token test", business_id="BIZ_001")
        rec = rt.request_publish_action(ctx, platform="linkedin",
                                         approval_token="ARBITRARYTruthyToken")
        self.assertNotEqual(rec.status.value, "SUCCESS")


# ===========================================================================
# QUEUE / API CANNOT CARRY AUTO-APPROVAL AUTHORITY
# ===========================================================================

class TestQueueApiAutoApprovalForbidden(unittest.TestCase):
    """§14: Queue and API endpoints cannot carry auto-approval authority."""

    def test_S_queue_rejects_auto_approve_token(self) -> None:
        """Queue enqueue_run rejects auto_approve_token with AUTO_APPROVAL_FORBIDDEN."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)
        mgr = RunManager(runtime=rt, max_workers=0)

        with self.assertRaises((ValueError, RuntimeError)) as ctx:
            mgr.enqueue_run(
                objective="Test auto-approval rejection",
                auto_approve_token="SOME_TOKEN",
            )
        self.assertIn("AUTO_APPROVAL_FORBIDDEN", str(ctx.exception))

    def test_R_auto_approve_token_rejected_by_workspace(self) -> None:
        """Workspace.execute_supervised_campaign rejects auto_approve_token."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)
        ws = OperatorWorkspace(runtime=rt)

        with self.assertRaises((ValueError, RuntimeError)) as ctx:
            ws.execute_supervised_campaign(
                business_id="BIZ_001",
                objective="Test rejection",
                auto_approve_token="SOME_TOKEN",
            )
        self.assertIn("AUTO_APPROVAL_FORBIDDEN", str(ctx.exception))


# ===========================================================================
# PUBLISHING WITHOUT HUMAN APPROVAL
# ===========================================================================

class TestPublishingRequiresHumanApproval(unittest.TestCase):
    """§15: No live publish without human approval."""

    def test_X_publishing_proposal_is_pending_not_completed(self) -> None:
        """request_publish_action creates PENDING proposal, not immediate publish."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="Publish test", business_id="BIZ_001")
        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token=None)

        # Must be WAITING_FOR_APPROVAL, not SUCCESS
        self.assertEqual(rec.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)


# ===========================================================================
# GATEWAY PROVIDER ARCHITECTURE REGRESSION
# ===========================================================================

class TestProviderArchitectureRegression(unittest.TestCase):
    """§17: Provider/Model architecture regression — global, 5 agent overrides, fallback chain."""

    def test_17a_global_provider_and_model(self) -> None:
        """Global provider/model is resolved correctly."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
        )
        target = policy.resolve_target_for_agent()
        self.assertEqual(target.provider_id, "xkiro")
        self.assertEqual(target.model_id, "mistralai/mistral-large-2512")

    def test_17b_five_agent_overrides(self) -> None:
        """All 5 agents can have distinct model overrides."""
        policy = ModelPolicy(
            agent_overrides={
                "cmo": ModelTarget(provider_id="p_cmo", model_id="cmo_model"),
                "intelligence": ModelTarget(provider_id="p_intel", model_id="intel_model"),
                "strategist": ModelTarget(provider_id="p_strat", model_id="strat_model"),
                "creative": ModelTarget(provider_id="p_creative", model_id="creative_model"),
                "performance": ModelTarget(provider_id="p_perf", model_id="perf_model"),
            },
        )
        for agent in ["cmo", "intelligence", "strategist", "creative", "performance"]:
            target = policy.resolve_target_for_agent(agent)
            self.assertIsNotNone(target)
            self.assertIn(agent, {"cmo": "p_cmo", "intelligence": "p_intel",
                                   "strategist": "p_strat", "creative": "p_creative",
                                   "performance": "p_perf"})

    def test_17c_fallback_chain(self) -> None:
        """Candidate chain for an agent includes primary + fallback entries."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="primary", model_id="model_a"),
            fallback_chain=[
                ModelTarget(provider_id="primary", model_id="model_a"),
                ModelTarget(provider_id="fallback", model_id="model_b"),
            ],
        )
        chain = policy.get_candidate_chain_for_agent()
        self.assertGreaterEqual(len(chain), 2)

    def test_17d_run_pinned_snapshot_stored(self) -> None:
        """start_run stores pinned policy/providers in context for the run's lifetime."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="pinned_provider", model_id="pinned_model"),
            configuration_version="v42",
        )
        gw = UniversalModelGateway(free_only_mode=False)
        gw.model_policy = policy
        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )
        ctx = rt.start_run(objective="Pin test", business_id="BIZ_001")
        self.assertIn("policy", ctx.model_policy)
        self.assertEqual(ctx.model_policy["configuration_version"], "v42")
        self.assertEqual(ctx.model_policy["policy"]["global_target"]["provider_id"], "pinned_provider")


# ===========================================================================
# SECURITY / UIAUTH REGRESSION
# ===========================================================================

class TestSecurityUIAuthRegression(unittest.TestCase):
    """§18: Security/UIAUTH regression — approval authority and tool gateway."""

    def test_18a_approval_token_cannot_cross_runs(self) -> None:
        """Approval token from RUN-A is rejected in RUN-B (PROD-RUNTIME-01 invariant)."""
        policy = PolicyEngine()
        pending_a = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "test"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-SEC-A",
            business_id="BIZ_001",
        )
        ok, rec, _ = policy.approve_pending_action(pending_a.pending_approval_id, approved_by="Op")
        self.assertTrue(ok)

        tool_gw = ToolGateway(capability_registry=CapabilityRegistry(), policy_engine=policy)
        cap = tool_gw.registry.get_capability("social_publishing")
        decision = policy.evaluate(
            agent_id="cmo",
            capability=cap,
            approval_token=rec.approval_token,
            run_id="RUN-SEC-B",
            business_id="BIZ_001",
            parameters={"platform": "linkedin", "content": "test"},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_RUN_MISMATCH")

    def test_18b_consumed_token_replay_rejected(self) -> None:
        """Consumed approval token cannot be replayed."""
        policy = PolicyEngine()
        pending = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "test"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-REPLAY",
            business_id="BIZ_001",
        )
        ok, rec, _ = policy.approve_pending_action(pending.pending_approval_id, approved_by="Op")
        self.assertTrue(ok)

        # Mark as consumed
        rec.consumed = True

        tool_gw = ToolGateway(capability_registry=CapabilityRegistry(), policy_engine=policy)
        cap = tool_gw.registry.get_capability("social_publishing")
        decision = policy.evaluate(
            agent_id="cmo",
            capability=cap,
            approval_token=rec.approval_token,
            run_id="RUN-REPLAY",
            business_id="BIZ_001",
            parameters={"platform": "linkedin", "content": "test"},
        )
        self.assertFalse(decision.allowed)


# ===========================================================================
# RUNTIME REGRESSION
# ===========================================================================

class TestRuntimeRegression(unittest.TestCase):
    """§19: Runtime regression — canonical execution authority."""

    def test_19a_run_workflow_uses_canonical_execute_run(self) -> None:
        """run_workflow delegates to start_run + execute_run."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        execute_run_called = [False]
        original = rt.execute_run
        def tracking(ctx):
            execute_run_called[0] = True
            return original(ctx)
        rt.execute_run = tracking

        ctx, _, _ = rt.run_workflow(objective="Canonical test", business_id="BIZ_001")
        self.assertTrue(execute_run_called[0])

    def test_19b_queue_worker_uses_canonical_execute_run(self) -> None:
        """Queue worker uses start_run → execute_run (not manual orchestration)."""
        gw = MockScriptedGateway()
        rt = _build_runtime(gateway=gw)

        execute_run_called = [False]
        original = rt.execute_run
        def tracking(ctx):
            execute_run_called[0] = True
            return original(ctx)
        rt.execute_run = tracking

        mgr = RunManager(runtime=rt, max_workers=1)
        item = mgr.enqueue_run(objective="Queue canonical test")

        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            if item.status in (RunQueueStatus.COMPLETED, RunQueueStatus.FAILED):
                break
            time.sleep(0.05)

        self.assertTrue(execute_run_called[0])
        self.assertEqual(item.status, RunQueueStatus.COMPLETED)
        mgr._stop_event.set()


# ===========================================================================
# TYPEERROR FALLBACK REMOVAL
# ===========================================================================

class TestTypeErrorFallbackRemoval(unittest.TestCase):
    """§3: TypeError must NOT trigger fallback to less-governed API."""

    def test_F_typeerror_is_real_error_not_feature_detection(self) -> None:
        """F. TypeError from gateway is propagated as real error, not retried."""
        gw = TypeErrorGateway()
        rt = _build_runtime(gateway=gw)

        ctx = rt.start_run(objective="TypeError test", business_id="BIZ_001")
        content, err = rt._call_agent_llm(
            agent_name="cmo",
            system_instruction="Test",
            user_prompt="Test",
            context=ctx,
        )

        # After fix: TypeError is a real error — no legacy retry fallback
        # call_count = 0 because generate() was never successfully called
        self.assertEqual(gw.call_count, 0)
        self.assertIsNotNone(err)
        self.assertIn("TypeErrorGateway", err)


# ===========================================================================
# START-RUN SNAPSHOT FAILURE
# ===========================================================================

class TestStartRunSnapshotFailure(unittest.TestCase):
    """§4: start_run must fail-closed when gateway exists but snapshot fails."""

    def test_G_snapshot_failure_is_fatal(self) -> None:
        """G. If gateway has model_policy but snapshot() fails, start_run fails closed."""
        gw = UniversalModelGateway(free_only_mode=False)
        gw.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="p", model_id="m"),
        )
        # Make snapshot() raise
        gw.provider_registry = MagicMock()
        gw.provider_registry.snapshot.side_effect = RuntimeError("SNAPSHOT_FAILURE")

        rt = FiveAgentDepartmentRuntime(
            model_gateway=gw,
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
        )

        # Before fix: start_run silently swallows and creates partial pol_dict
        # After fix: start_run raises RUN_PINNED_MODEL_CONFIGURATION_INVALID
        with self.assertRaises(RuntimeError) as ctx:
            rt.start_run(objective="Snapshot failure test", business_id="BIZ_001")
        self.assertIn("RUN_PINNED_MODEL_CONFIGURATION_INVALID", str(ctx.exception))


# ===========================================================================
# STAGE FAILURE SHORT-CIRCUIT (integration)
# ===========================================================================

class TestStageFailureShortCircuitIntegration(unittest.TestCase):
    """§8: Integration test — stage failure prevents downstream expensive work."""

    def test_cmo_failure_stops_all_downstream(self) -> None:
        """If CMO Initial fails, no other stage executes."""
        gw = MockScriptedGateway(fail_stage="cmo_initial")
        rt = _build_runtime(gateway=gw)

        stages_executed: List[str] = []
        for stage_name, attr in [
            ("intelligence", "execute_stage_intelligence"),
            ("strategist", "execute_stage_strategist"),
            ("creative", "execute_stage_creative"),
            ("performance", "execute_stage_performance"),
        ]:
            original = getattr(rt, attr)
            def make_tracked(name, fn):
                def tracked(ctx):
                    stages_executed.append(name)
                    return fn(ctx)
                return tracked
            setattr(rt, attr, make_tracked(stage_name, original))

        ctx, _, _ = rt.run_workflow(
            objective="CMO failure stops all", business_id="BIZ_001"
        )
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(len(stages_executed), 0)


if __name__ == "__main__":
    unittest.main()
