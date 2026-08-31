"""Comprehensive Test Suite for Trusted Runtime-Owned Progress Events (PROD-STREAMING-IMPLEMENTATION-01-B2).

Validates:
1. Typed finite event enums and schema validation
2. Run ID propagation and sequence monotonicity (1, 2, 3...)
3. Full workflow 6 real stages with Final CMO = agent CMO (zero Agent 6)
4. Research fast path emits Intelligence only with 0 CMO/Strategist/Creative/Performance/Final CMO events
5. Evidence boundary ordering: RESEARCH_EVIDENCE_READY occurs strictly before Intelligence model start
6. General conversation emits no research events and no fake multi-agent stages
7. Honest failure handling: RUN_FAILED emitted, never RUN_COMPLETED after failure, no fake STAGE_COMPLETED
8. Sink isolation: absence/failure of callback never crashes run, duplicates calls, or mutates policy
9. Zero leakage of credentials/API keys or model-generated text in event payloads
10. Model and search call count invariants preserved
"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from chat.engine import ChatConversationEngine
from chat.session import ChatSession, ChatRole, ChatMessage
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gateway import UniversalModelGateway
from runtime.context import (
    RuntimeContext,
    RuntimeStage,
    RuntimeStatus,
)
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.progress import (
    ProgressEmitter,
    ProgressEventType,
    ProgressMode,
    RuntimeProgressEvent,
    _sanitize_metadata,
)
from tools.receipts import ExecutionReceipt, ExecutionStatus


class FakeModelGateway(UniversalModelGateway):
    """Deterministic mock gateway for unit tests."""

    def __init__(self, should_fail: bool = False, fail_stage: Optional[str] = None):
        super().__init__(free_only_mode=True)
        self.should_fail = should_fail
        self.fail_stage = fail_stage
        self.call_count = 0
        self.recorded_requests: List[ModelRequest] = []

    def generate(
        self,
        request: ModelRequest,
        profile: str = "default",
        provider_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_policy: Optional[Any] = None,
        provider_snapshot: Optional[Any] = None,
        strict_model_pin: bool = False,
        allow_paid: bool = False,
    ) -> ModelResponse:
        self.call_count += 1
        self.recorded_requests.append(request)

        if self.should_fail:
            return ModelResponse(
                request_id=request.request_id,
                provider="fake_provider",
                model_name="fake_model",
                status=ModelResponseStatus.ERROR,
                error="SIMULATED_PROVIDER_FAILURE",
            )

        if self.fail_stage and agent_id == self.fail_stage:
            return ModelResponse(
                request_id=request.request_id,
                provider="fake_provider",
                model_name="fake_model",
                status=ModelResponseStatus.ERROR,
                error=f"SIMULATED_{self.fail_stage.upper()}_FAILURE",
            )

        # Standard deterministic success responses
        agent_key = (agent_id or "default").lower()
        if agent_key == "cmo":
            content = "# CHIẾN LƯỢC GTM TỔNG THỂ\n\nKế hoạch tiếp thị phân rã chi tiết cho các bộ phận chuyên môn."
        elif agent_key == "intelligence":
            content = "## Báo cáo nghiên cứu thị trường: Phân tích đối thủ và insight khách hàng mục tiêu."
        elif agent_key == "strategist":
            content = "## Định vị thương hiệu: Khách hàng ICP và thông điệp cốt lõi."
        elif agent_key == "creative":
            content = "## Ý tưởng sáng tạo: 3 góc tiếp cận quảng cáo và kịch bản video ngắn."
        elif agent_key == "performance":
            content = "## Phân bổ ngân sách & KPI: Mục tiêu CAC, ROAS và kế hoạch thử nghiệm."
        else:
            content = "Xin chào! Tôi có thể hỗ trợ gì cho bạn trong chiến dịch tiếp thị hôm nay?"

        return ModelResponse(
            request_id=request.request_id,
            provider="fake_provider",
            model_name="fake_model",
            status=ModelResponseStatus.SUCCESS,
            content=content,
            usage=ModelUsage(prompt_tokens=100, completion_tokens=150, total_tokens=250),
            latency_ms=10.0,
        )


class TestProdRuntimeProgress01(unittest.TestCase):
    """25+ Point Test Matrix for Trusted Runtime Progress Events."""

    def setUp(self) -> None:
        self.gateway = FakeModelGateway()
        self.runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway)

    # 1. event_type is typed / finite
    def test_01_event_types_are_typed_and_finite(self) -> None:
        expected_types = {
            "RUN_STARTED",
            "ROUTE_SELECTED",
            "RESEARCH_STARTED",
            "RESEARCH_SEARCH_STARTED",
            "RESEARCH_SEARCH_COMPLETED",
            "RESEARCH_EVIDENCE_READY",
            "STAGE_STARTED",
            "STAGE_COMPLETED",
            "MODEL_STARTED",
            "MODEL_COMPLETED",
            "RUN_COMPLETED",
            "RUN_FAILED",
        }
        enum_values = {e.value for e in ProgressEventType}
        self.assertEqual(expected_types, enum_values)

    # 2. run_id propagated correctly
    def test_02_run_id_propagated_correctly(self) -> None:
        events: List[RuntimeProgressEvent] = []
        ctx, out, art = self.runtime.run_workflow(
            objective="Chiến dịch ra mắt sản phẩm A",
            progress_sink=events.append,
        )
        self.assertTrue(len(events) > 0)
        for ev in events:
            self.assertEqual(ev.run_id, ctx.run_id)

    # 3. sequence strictly monotonic (1, 2, 3...)
    def test_03_sequence_strictly_monotonic(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(
            objective="Chiến dịch tăng trưởng Q4",
            progress_sink=events.append,
        )
        sequences = [ev.sequence for ev in events]
        self.assertEqual(sequences, list(range(1, len(events) + 1)))

    # 4. no duplicate sequence numbers
    def test_04_no_duplicate_sequence_numbers(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(
            objective="Chiến dịch quảng cáo đa kênh",
            progress_sink=events.append,
        )
        sequences = [ev.sequence for ev in events]
        self.assertEqual(len(sequences), len(set(sequences)))

    # 5. full workflow emits six real stages
    def test_05_full_workflow_emits_six_real_stages(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(
            objective="Kế hoạch marketing B2B SaaS",
            progress_sink=events.append,
        )
        stages_started = [ev.stage for ev in events if ev.event_type == ProgressEventType.STAGE_STARTED]
        expected_stages = ["CMO_INITIAL", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE", "FINAL_CMO"]
        self.assertEqual(stages_started, expected_stages)

    # 6. Final CMO stage uses agent=CMO
    def test_06_final_cmo_stage_uses_agent_cmo(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(
            objective="Kế hoạch marketing B2B SaaS",
            progress_sink=events.append,
        )
        final_cmo_started = [ev for ev in events if ev.stage == "FINAL_CMO" and ev.event_type == ProgressEventType.STAGE_STARTED]
        self.assertEqual(len(final_cmo_started), 1)
        self.assertEqual(final_cmo_started[0].agent, "CMO")
        self.assertEqual(final_cmo_started[0].stage, "FINAL_CMO")

    # 7. no Agent 6 exists
    def test_07_no_agent_6_exists(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(
            objective="Kế hoạch marketing thời trang",
            progress_sink=events.append,
        )
        for ev in events:
            self.assertNotIn(ev.agent, ["AGENT_6", "FINAL_CMO", "SYNTHESIS_AGENT", "AGENT6"])

    # 8. research fast path emits Intelligence only (0 CMO, 0 Strategist, 0 Creative, 0 Performance, 0 Final CMO)
    def test_08_research_fast_path_emits_intelligence_only(self) -> None:
        events: List[RuntimeProgressEvent] = []
        ctx, out, art = self.runtime.run_research_inquiry(
            objective="Tìm hiểu dung lượng thị trường EdTech Việt Nam",
            progress_sink=events.append,
        )
        agents_seen = {ev.agent for ev in events if ev.agent is not None}
        self.assertEqual(agents_seen, {"INTELLIGENCE"})

        stages_seen = {ev.stage for ev in events if ev.stage is not None}
        self.assertEqual(stages_seen, {"INTELLIGENCE"})

    # 9. research progress does NOT expose internal "final_cmo" compatibility key
    def test_09_research_progress_does_not_expose_final_cmo(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_research_inquiry(
            objective="Phân tích thị trường ô tô điện",
            progress_sink=events.append,
        )
        for ev in events:
            self.assertNotEqual(ev.stage, "FINAL_CMO")
            self.assertNotEqual(ev.stage, "final_cmo")
            self.assertNotEqual(ev.agent, "CMO")

    # 10. research evidence ready occurs before Intelligence model start
    def test_10_research_evidence_ready_occurs_before_model_start(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_research_inquiry(
            objective="Khảo sát hành vi người tiêu dùng FMCG",
            progress_sink=events.append,
        )
        event_types = [ev.event_type for ev in events]
        self.assertIn(ProgressEventType.RESEARCH_EVIDENCE_READY, event_types)
        self.assertIn(ProgressEventType.MODEL_STARTED, event_types)

        evidence_idx = event_types.index(ProgressEventType.RESEARCH_EVIDENCE_READY)
        model_idx = event_types.index(ProgressEventType.MODEL_STARTED)
        self.assertLess(evidence_idx, model_idx)

    # 11. General conversation emits no research events
    def test_11_general_conversation_emits_no_research_events(self) -> None:
        chat_engine = ChatConversationEngine(model_gateway=self.gateway)
        session = ChatSession(chat_id="chat-1", messages=[])
        events: List[RuntimeProgressEvent] = []

        chat_engine.generate_chat_response(
            session=session,
            user_message="Xin chào, bạn có thể làm gì?",
            progress_sink=events.append,
        )

        for ev in events:
            self.assertNotIn(ev.event_type, [
                ProgressEventType.RESEARCH_STARTED,
                ProgressEventType.RESEARCH_SEARCH_STARTED,
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                ProgressEventType.RESEARCH_EVIDENCE_READY,
            ])

    # 12. General conversation emits no fake five-agent stages
    def test_12_general_conversation_emits_no_fake_stages(self) -> None:
        chat_engine = ChatConversationEngine(model_gateway=self.gateway)
        session = ChatSession(chat_id="chat-2", messages=[])
        events: List[RuntimeProgressEvent] = []

        chat_engine.generate_chat_response(
            session=session,
            user_message="CPA là gì?",
            progress_sink=events.append,
        )

        for ev in events:
            self.assertIsNone(ev.stage)
            self.assertIsNone(ev.agent)
            self.assertNotEqual(ev.event_type, ProgressEventType.STAGE_STARTED)
            self.assertNotEqual(ev.event_type, ProgressEventType.STAGE_COMPLETED)

    # 13. failure emits RUN_FAILED
    def test_13_failure_emits_run_failed(self) -> None:
        failing_gateway = FakeModelGateway(should_fail=True)
        runtime = FiveAgentDepartmentRuntime(model_gateway=failing_gateway)
        events: List[RuntimeProgressEvent] = []

        ctx, out, art = runtime.run_workflow(
            objective="Chiến dịch thử nghiệm lỗi",
            progress_sink=events.append,
        )

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        event_types = [ev.event_type for ev in events]
        self.assertIn(ProgressEventType.RUN_FAILED, event_types)

    # 14. failure does NOT emit RUN_COMPLETED
    def test_14_failure_does_not_emit_run_completed(self) -> None:
        failing_gateway = FakeModelGateway(should_fail=True)
        runtime = FiveAgentDepartmentRuntime(model_gateway=failing_gateway)
        events: List[RuntimeProgressEvent] = []

        runtime.run_workflow(
            objective="Chiến dịch kiểm tra không hoàn tất",
            progress_sink=events.append,
        )

        event_types = [ev.event_type for ev in events]
        self.assertNotIn(ProgressEventType.RUN_COMPLETED, event_types)

    # 15. failed stage does NOT emit fake STAGE_COMPLETED
    def test_15_failed_stage_does_not_emit_fake_stage_completed(self) -> None:
        failing_gateway = FakeModelGateway(fail_stage="intelligence")
        runtime = FiveAgentDepartmentRuntime(model_gateway=failing_gateway)
        events: List[RuntimeProgressEvent] = []

        runtime.run_workflow(
            objective="Chiến dịch lỗi tại Intelligence",
            progress_sink=events.append,
        )

        completed_stages = [ev.stage for ev in events if ev.event_type == ProgressEventType.STAGE_COMPLETED]
        self.assertNotIn("INTELLIGENCE", completed_stages)
        self.assertNotIn("STRATEGIST", completed_stages)
        self.assertNotIn("FINAL_CMO", completed_stages)

    # 16. event sink absence does not change run result
    def test_16_sink_absence_does_not_change_run_result(self) -> None:
        ctx1, out1, art1 = self.runtime.run_workflow(objective="Kiểm thử không có sink")
        self.runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway)
        events: List[RuntimeProgressEvent] = []
        ctx2, out2, art2 = self.runtime.run_workflow(objective="Kiểm thử không có sink", progress_sink=events.append)

        self.assertEqual(ctx1.status, ctx2.status)
        self.assertEqual(len(ctx1.stage_outputs), len(ctx2.stage_outputs))
        self.assertEqual(art1.status, art2.status)

    # 17. event sink does not add model calls
    def test_17_sink_does_not_add_model_calls(self) -> None:
        gw1 = FakeModelGateway()
        rt1 = FiveAgentDepartmentRuntime(model_gateway=gw1)
        rt1.run_workflow(objective="Đo lường model call")

        gw2 = FakeModelGateway()
        rt2 = FiveAgentDepartmentRuntime(model_gateway=gw2)
        events: List[RuntimeProgressEvent] = []
        rt2.run_workflow(objective="Đo lường model call", progress_sink=events.append)

        self.assertEqual(gw1.call_count, gw2.call_count)
        # Six workflow stages now require seven model calls because the single\n        # permanent Performance agent executes mandatory internal Pass 5A + 5B.\n        self.assertEqual(gw2.call_count, 7)

    # 18. event sink does not add search calls
    def test_18_sink_does_not_add_search_calls(self) -> None:
        with patch.object(self.runtime.tool_gateway, "execute", wraps=self.runtime.tool_gateway.execute) as mock_exec:
            self.runtime.run_research_inquiry(objective="Đo lường search call")
            call_count_no_sink = mock_exec.call_count

        self.runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway)
        with patch.object(self.runtime.tool_gateway, "execute", wraps=self.runtime.tool_gateway.execute) as mock_exec:
            events: List[RuntimeProgressEvent] = []
            self.runtime.run_research_inquiry(objective="Đo lường search call", progress_sink=events.append)
            call_count_with_sink = mock_exec.call_count

        self.assertEqual(call_count_no_sink, call_count_with_sink)

    # 19. event sink failure does not duplicate model calls or crash run
    def test_19_sink_failure_does_not_duplicate_model_calls(self) -> None:
        def broken_sink(event: RuntimeProgressEvent) -> None:
            raise RuntimeError("CONSUMER_INTERNAL_CRASH")

        gw = FakeModelGateway()
        rt = FiveAgentDepartmentRuntime(model_gateway=gw)
        ctx, out, art = rt.run_workflow(objective="Chiến dịch sink hỏng", progress_sink=broken_sink)

        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        # A broken progress sink must not add calls beyond the canonical seven.\n        self.assertEqual(gw.call_count, 7)

    # 20. event sink failure does not mutate ModelPolicy or runtime status
    def test_20_sink_failure_does_not_mutate_policy(self) -> None:
        def broken_sink(event: RuntimeProgressEvent) -> None:
            raise ValueError("UI_DISCONNECTED")

        ctx, out, art = self.runtime.run_workflow(objective="Chiến dịch sink lỗi", progress_sink=broken_sink)
        self.assertTrue(ctx.model_policy.get("free_only_mode"))
        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)

    # 21. event messages contain no model-generated text
    def test_21_event_messages_contain_no_model_generated_text(self) -> None:
        events: List[RuntimeProgressEvent] = []
        self.runtime.run_workflow(objective="Kiểm tra nội dung message", progress_sink=events.append)

        forbidden_snippets = [
            "Kế hoạch tiếp thị phân rã chi tiết",
            "Phân tích đối thủ và insight",
            "3 góc tiếp cận quảng cáo",
        ]
        for ev in events:
            for snippet in forbidden_snippets:
                if ev.message:
                    self.assertNotIn(snippet, ev.message)

    # 22. events contain no credential / API key
    def test_22_events_contain_no_credential_or_api_key(self) -> None:
        emitter = ProgressEmitter(run_id="TEST-RUN")
        ev = emitter.emit(
            ProgressEventType.RUN_STARTED,
            metadata={
                "api_key": "sk-1234567890abcdef",
                "secret": "top_secret_token",
                "safe_field": "valid_value",
            }
        )
        self.assertNotIn("api_key", ev.metadata)
        self.assertNotIn("secret", ev.metadata)
        self.assertIn("safe_field", ev.metadata)
        self.assertEqual(ev.metadata["safe_field"], "valid_value")

    # 23. events contain no provider Authorization header
    def test_23_events_contain_no_auth_header(self) -> None:
        sanitized = _sanitize_metadata({
            "authorization": "Bearer ya29.123456",
            "auth_header": "Bearer test",
            "normal_id": "ID_12345",
        })
        self.assertNotIn("authorization", sanitized)
        self.assertNotIn("auth_header", sanitized)
        self.assertIn("normal_id", sanitized)

    # 24. B1 generate_stream semantics unchanged
    def test_24_gateway_streaming_b1_semantics_unchanged(self) -> None:
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        deltas = list(self.gateway.generate_stream(req))
        self.assertTrue(len(deltas) > 0)

    # 25. research fast-path call counts unchanged (exactly 1 model call)
    def test_25_research_fast_path_call_counts_unchanged(self) -> None:
        gw = FakeModelGateway()
        rt = FiveAgentDepartmentRuntime(model_gateway=gw)
        events: List[RuntimeProgressEvent] = []
        rt.run_research_inquiry(objective="Nghiên cứu thị trường cà phê", progress_sink=events.append)
        self.assertEqual(gw.call_count, 1)

    # 26. Cooperative cancellation emits RUN_FAILED
    def test_26_cancellation_emits_run_failed(self) -> None:
        events: List[RuntimeProgressEvent] = []
        ctx = self.runtime.start_run(objective="Chiến dịch hủy bỏ", progress_sink=events.append)
        self.runtime.cancel_run(ctx.run_id)
        self.runtime.execute_run(ctx, progress_sink=events.append)

        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        event_types = [ev.event_type for ev in events]
        self.assertIn(ProgressEventType.RUN_FAILED, event_types)
        self.assertNotIn(ProgressEventType.RUN_COMPLETED, event_types)

    # 27. General conversation error handling emits RUN_FAILED
    def test_27_general_chat_error_emits_run_failed(self) -> None:
        failing_gw = FakeModelGateway(should_fail=True)
        chat_engine = ChatConversationEngine(model_gateway=failing_gw)
        session = ChatSession(chat_id="chat-err", messages=[])
        events: List[RuntimeProgressEvent] = []

        res = chat_engine.generate_chat_response(
            session=session,
            user_message="Một câu hỏi phức tạp không có fallback offline",
            progress_sink=events.append,
        )
        self.assertFalse(res["success"])
        event_types = [ev.event_type for ev in events]
        self.assertIn(ProgressEventType.RUN_FAILED, event_types)
        self.assertNotIn(ProgressEventType.RUN_COMPLETED, event_types)

    # 28. RuntimeProgressEvent.mode rejects arbitrary invalid mode
    def test_28_invalid_mode_rejected_by_validation(self) -> None:
        from schemas.base import ValidationError
        with self.assertRaises(ValidationError):
            RuntimeProgressEvent(
                event_type=ProgressEventType.RUN_STARTED,
                run_id="TEST-1",
                sequence=1,
                mode="AGENT_SAYS_RESEARCH",  # Invalid
            )

    # 29. Valid ProgressMode serializes correctly
    def test_29_valid_mode_serializes_correctly(self) -> None:
        ev = RuntimeProgressEvent(
            event_type=ProgressEventType.RUN_STARTED,
            run_id="TEST-1",
            sequence=1,
            mode=ProgressMode.FULL_WORKFLOW,
        )
        self.assertEqual(ev.mode, ProgressMode.FULL_WORKFLOW)
        dumped = ev.model_dump()
        self.assertEqual(dumped["mode"], "FULL_WORKFLOW")

    # 30. Invalid agent rejected (no AGENT_6 or FINAL_CMO)
    def test_30_invalid_agent_rejected_by_validation(self) -> None:
        from schemas.base import ValidationError
        with self.assertRaises(ValidationError):
            RuntimeProgressEvent(
                event_type=ProgressEventType.STAGE_STARTED,
                run_id="TEST-1",
                sequence=1,
                agent="AGENT_6",  # Invalid
            )
        with self.assertRaises(ValidationError):
            RuntimeProgressEvent(
                event_type=ProgressEventType.STAGE_STARTED,
                run_id="TEST-1",
                sequence=1,
                agent="FINAL_CMO",  # Invalid (stage only)
            )

    # 31. Invalid stage rejected
    def test_31_invalid_stage_rejected_by_validation(self) -> None:
        from schemas.base import ValidationError
        with self.assertRaises(ValidationError):
            RuntimeProgressEvent(
                event_type=ProgressEventType.STAGE_STARTED,
                run_id="TEST-1",
                sequence=1,
                stage="FAKE_NONEXISTENT_STAGE",  # Invalid
            )

    # 32. Completed run releases sink callback
    def test_32_completed_run_releases_sink_callback(self) -> None:
        sink_events: List[RuntimeProgressEvent] = []
        ctx, out, art = self.runtime.run_workflow(
            objective="Chiến dịch kiểm tra release sink",
            progress_sink=sink_events.append,
        )
        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        # Active emitters registry must not hold completed run
        self.assertNotIn(ctx.run_id, self.runtime._active_emitters)
        # Completed progress must store immutable events tuple, not live emitter
        self.assertIn(ctx.run_id, self.runtime._completed_progress)
        self.assertIsInstance(self.runtime._completed_progress[ctx.run_id], tuple)

    # 33. Completed history contains events, not callable sink
    def test_33_completed_history_contains_events_not_sink(self) -> None:
        sink_events: List[RuntimeProgressEvent] = []
        ctx, out, art = self.runtime.run_workflow(
            objective="Chiến dịch kiểm tra event history",
            progress_sink=sink_events.append,
        )
        history = self.runtime.get_progress_events(ctx.run_id)
        self.assertTrue(len(history) > 0)
        self.assertEqual(len(history), len(sink_events))
        # No sink attribute on completed history items
        for ev in history:
            self.assertIsInstance(ev, RuntimeProgressEvent)

    # 34. Failure and cancellation terminalization release sink
    def test_34_failure_and_cancellation_release_sink(self) -> None:
        failing_gw = FakeModelGateway(should_fail=True)
        rt = FiveAgentDepartmentRuntime(model_gateway=failing_gw)
        sink_events: List[RuntimeProgressEvent] = []

        ctx_fail, _, _ = rt.run_workflow(objective="Lỗi", progress_sink=sink_events.append)
        self.assertEqual(ctx_fail.status, RuntimeStatus.FAILED)
        self.assertNotIn(ctx_fail.run_id, rt._active_emitters)
        self.assertIn(ctx_fail.run_id, rt._completed_progress)

        ctx_canc = rt.start_run(objective="Hủy", progress_sink=sink_events.append)
        rt.cancel_run(ctx_canc.run_id)
        rt.execute_run(ctx_canc, progress_sink=sink_events.append)
        self.assertEqual(ctx_canc.status, RuntimeStatus.CANCELLED)
        self.assertNotIn(ctx_canc.run_id, rt._active_emitters)
        self.assertIn(ctx_canc.run_id, rt._completed_progress)

    # 35. Late emit after finalization cannot call old sink
    def test_35_late_emit_after_finalization_does_not_call_sink(self) -> None:
        sink_called = 0
        def sink(ev: RuntimeProgressEvent) -> None:
            nonlocal sink_called
            sink_called += 1

        emitter = ProgressEmitter(run_id="RUN-LATE", sink=sink)
        emitter.emit(ProgressEventType.RUN_STARTED)
        self.assertEqual(sink_called, 1)

        emitter.finalize()
        self.assertTrue(emitter.is_closed)
        self.assertIsNone(emitter.sink)

        # Calling emit on finalized emitter does NOT notify sink
        emitter.emit(ProgressEventType.STAGE_STARTED, stage="CMO_INITIAL", agent="CMO")
        self.assertEqual(sink_called, 1)  # Still 1, not 2

    # 36. Completed progress cache remains bounded
    def test_36_completed_progress_cache_remains_bounded(self) -> None:
        small_cache_rt = FiveAgentDepartmentRuntime(model_gateway=self.gateway, max_completed_runs_cache=3)
        for i in range(5):
            small_cache_rt.run_workflow(objective=f"Run {i}")
        self.assertLessEqual(len(small_cache_rt._completed_progress), 3)

    # 37. Cross-run sequence and sink isolation
    def test_37_cross_run_sequence_and_sink_isolation(self) -> None:
        events_a: List[RuntimeProgressEvent] = []
        events_b: List[RuntimeProgressEvent] = []

        ctx_a, _, _ = self.runtime.run_workflow(objective="Chiến dịch A", progress_sink=events_a.append)
        ctx_b, _, _ = self.runtime.run_workflow(objective="Chiến dịch B", progress_sink=events_b.append)

        # Run A sequences 1..N
        seq_a = [e.sequence for e in events_a]
        self.assertEqual(seq_a, list(range(1, len(events_a) + 1)))

        # Run B sequences 1..M (starts at 1)
        seq_b = [e.sequence for e in events_b]
        self.assertEqual(seq_b, list(range(1, len(events_b) + 1)))

        # Sink isolation
        self.assertTrue(all(e.run_id == ctx_a.run_id for e in events_a))
        self.assertTrue(all(e.run_id == ctx_b.run_id for e in events_b))

    # 38. ProgressStage has exactly six canonical stages (no COMPLETED)
    def test_38_progress_stage_has_exactly_six_canonical_stages(self) -> None:
        from runtime.progress import ProgressStage
        expected_stages = {
            "CMO_INITIAL",
            "INTELLIGENCE",
            "STRATEGIST",
            "CREATIVE",
            "PERFORMANCE",
            "FINAL_CMO",
        }
        self.assertEqual(len(ProgressStage), 6)
        self.assertEqual({s.value for s in ProgressStage}, expected_stages)
        self.assertNotIn("COMPLETED", [s.value for s in ProgressStage])

    # 39. ProgressAgent has exactly five canonical agents
    def test_39_progress_agent_has_exactly_five_canonical_agents(self) -> None:
        from runtime.progress import ProgressAgent
        expected_agents = {
            "CMO",
            "INTELLIGENCE",
            "STRATEGIST",
            "CREATIVE",
            "PERFORMANCE",
        }
        self.assertEqual(len(ProgressAgent), 5)
        self.assertEqual({a.value for a in ProgressAgent}, expected_agents)
        self.assertNotIn("AGENT_6", [a.value for a in ProgressAgent])
        self.assertNotIn("FINAL_CMO", [a.value for a in ProgressAgent])

    # 40. get_progress_events returns an immutable tuple preventing caller-side mutation
    def test_40_get_progress_events_returns_immutable_tuple(self) -> None:
        ctx, _, _ = self.runtime.run_workflow(objective="Kiểm tra tính bất biến")
        history = self.runtime.get_progress_events(ctx.run_id)
        self.assertIsInstance(history, tuple)
        # Attempting to mutate tuple raises AttributeError
        with self.assertRaises(AttributeError):
            history.append(None)  # type: ignore[attr-defined]

        # Second lookup produces identical unchanged sequence
        history2 = self.runtime.get_progress_events(ctx.run_id)
        self.assertEqual(history, history2)

    # 41. Late emit after finalize does not mutate events or advance sequence
    def test_41_late_emit_after_finalize_does_not_mutate_events_or_advance_sequence(self) -> None:
        emitter = ProgressEmitter(run_id="RUN-FINALIZED")
        emitter.emit(ProgressEventType.RUN_STARTED)
        self.assertEqual(emitter.current_sequence, 1)
        self.assertEqual(len(emitter.events), 1)

        emitter.finalize()
        self.assertTrue(emitter.is_closed)

        result = emitter.emit(ProgressEventType.STAGE_STARTED, stage="CMO_INITIAL", agent="CMO")
        self.assertIsNone(result)
        self.assertEqual(emitter.current_sequence, 1)
        self.assertEqual(len(emitter.events), 1)

    # 42. _call_agent_llm with context.current_stage=RuntimeStage.INIT does not fail because of progress typing
    def test_42_call_agent_llm_with_init_stage_maps_stage_to_none_and_does_not_fail(self) -> None:
        events: List[RuntimeProgressEvent] = []
        ctx = self.runtime.start_run(objective="Test INIT LLM call", progress_sink=events.append)
        self.assertEqual(ctx.current_stage, RuntimeStage.INIT)

        content, err = self.runtime._call_agent_llm(
            agent_name="cmo",
            system_instruction="System prompt",
            user_prompt="User prompt",
            context=ctx,
        )
        self.assertIsNone(err)
        self.assertIsNotNone(content)

        # Progress events for model execution during INIT have stage=None, never stage="INIT"
        model_events = [e for e in events if e.event_type in (ProgressEventType.MODEL_STARTED, ProgressEventType.MODEL_COMPLETED)]
        self.assertTrue(len(model_events) >= 2)
        for me in model_events:
            self.assertIsNone(me.stage)

    # 43. runtime_stage_to_progress_stage maps canonical stages and returns None for lifecycle states
    def test_43_runtime_stage_to_progress_stage_mappings(self) -> None:
        from runtime.progress import runtime_stage_to_progress_stage, ProgressStage
        # Canonical mappings
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.CMO_INITIAL), ProgressStage.CMO_INITIAL)
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.INTELLIGENCE), ProgressStage.INTELLIGENCE)
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.STRATEGIST), ProgressStage.STRATEGIST)
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.CREATIVE), ProgressStage.CREATIVE)
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.PERFORMANCE), ProgressStage.PERFORMANCE)
        self.assertEqual(runtime_stage_to_progress_stage(RuntimeStage.FINAL_CMO), ProgressStage.FINAL_CMO)

        # Noncanonical lifecycle states map to None
        self.assertIsNone(runtime_stage_to_progress_stage(RuntimeStage.INIT))
        self.assertIsNone(runtime_stage_to_progress_stage(RuntimeStage.COMPLETED))
        self.assertIsNone(runtime_stage_to_progress_stage("ARBITRARY_STATE"))
        self.assertIsNone(runtime_stage_to_progress_stage(None))

    # 44. run_workflow without progress sink invokes 1-arg execute_run(context)
    def test_44_run_workflow_without_sink_invokes_1_arg_execute_run(self) -> None:
        execute_run_called = [False]
        original_execute_run = self.runtime.execute_run

        def tracking(ctx: RuntimeContext) -> Tuple[RuntimeContext, Dict[str, Any], DepartmentRunArtifact]:
            execute_run_called[0] = True
            return original_execute_run(ctx)

        self.runtime.execute_run = tracking  # type: ignore[assignment]
        try:
            ctx, _, art = self.runtime.run_workflow(objective="Test 1-arg compatibility")
            self.assertTrue(execute_run_called[0])
            self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        finally:
            self.runtime.execute_run = original_execute_run  # type: ignore[assignment]

    # 45. Genuine model TypeError propagates intact without feature detection
    def test_45_genuine_model_typeerror_preserved_and_unswallowed(self) -> None:
        class TypeErrorModelGateway(FakeModelGateway):
            def generate(self, *args: Any, **kwargs: Any) -> Any:
                raise TypeError("TypeErrorModelGateway simulated bad keyword")

        rt = FiveAgentDepartmentRuntime(model_gateway=TypeErrorModelGateway())
        ctx = rt.start_run(objective="Test TypeError unswallowed")
        content, err = rt._call_agent_llm(
            agent_name="cmo",
            system_instruction="sys",
            user_prompt="prompt",
            context=ctx,
        )
        self.assertIsNone(content)
        self.assertIsNotNone(err)
        self.assertIn("TypeErrorModelGateway", err)

    # 46. Supplying real progress sink produces valid progress events
    def test_46_progress_sink_receives_clean_events_during_full_workflow(self) -> None:
        events: List[RuntimeProgressEvent] = []
        ctx, _, _ = self.runtime.run_workflow(
            objective="Full workflow sink verification",
            progress_sink=events.append,
        )
        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        self.assertTrue(len(events) > 10)
        self.assertEqual(events[0].event_type, ProgressEventType.RUN_STARTED)
        self.assertEqual(events[-1].event_type, ProgressEventType.RUN_COMPLETED)


if __name__ == "__main__":
    unittest.main()
