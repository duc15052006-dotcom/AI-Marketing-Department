"""PROD-MODEL-STREAMING-01: Model-Layer Streaming Foundation Tests.

Deterministic unit tests for the lowest model-layer streaming foundation:
- StreamDelta type
- OpenAICompatibleTransport.post_json_stream
- OpenAICompatibleProviderAdapter.generate_stream
- UniversalModelGateway.generate_stream
- Optional BaseModelAdapter.generate_stream contract
- Fallback semantics (before/after first visible token)
- Non-streaming provider degradation
- Generator cleanup
- Run-pinned policy preservation
- Security (no secret leakage)
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
    StreamDelta,
    normalize_model_request,
)
from integrations.models.transport import OpenAICompatibleTransport
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import (
    ModelPolicy,
    ModelTarget,
    ProviderDefinition,
    ProviderRegistry,
)


# ── Fake Transport ──────────────────────────────────────────────────

class FakeStreamTransport:
    """Fake transport that returns pre-configured SSE events from post_json_stream."""

    def __init__(self, events: List[Dict[str, Any]], error: Optional[Dict[str, Any]] = None):
        self._events = events
        self._error = error
        self._last_payload: Optional[Dict[str, Any]] = None

    def build_headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "test"}

    def post_json(self, endpoint_path: str, payload: Dict[str, Any], timeout_seconds: Optional[float] = None) -> Tuple[int, Dict[str, str], str]:
        self._last_payload = payload
        if self._error:
            return self._error.get("status_code", 500), {}, self._error.get("body", "")
        resp_body = {
            "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return 200, {}, json.dumps(resp_body)

    def post_json_stream(self, endpoint_path: str, payload: Dict[str, Any], timeout_seconds: Optional[float] = None) -> Generator[Dict[str, Any], None, None]:
        self._last_payload = payload
        if self._error:
            yield self._error
            return
        for event in self._events:
            yield event


class FakeNonStreamingAdapter(BaseModelAdapter):
    """Fake adapter that only supports synchronous generate(), not streaming."""

    def __init__(self, provider_id: str = "fake_nostream", response_content: str = "sync response"):
        self._provider_id = provider_id
        self._response_content = response_content

    @property
    def provider_name(self) -> str:
        return self._provider_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=getattr(request, "request_id", "REQ-FAKE"),
            provider=self._provider_id,
            model_name=getattr(request, "model_name", "fake-model"),
            status=ModelResponseStatus.SUCCESS,
            content=self._response_content,
            usage=ModelUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, usage_source="PROVIDER_REPORTED"),
            latency_ms=100.0,
        )


class FakeFailingAdapter(BaseModelAdapter):
    """Fake adapter that always fails."""

    def __init__(self, provider_id: str = "fake_fail"):
        self._provider_id = provider_id

    @property
    def provider_name(self) -> str:
        return self._provider_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=getattr(request, "request_id", "REQ-FAKE"),
            provider=self._provider_id,
            model_name=getattr(request, "model_name", "fake-model"),
            status=ModelResponseStatus.ERROR,
            error="PROVIDER_ERROR: test failure",
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
            latency_ms=100.0,
        )

    def generate_stream(self, request: ModelRequest) -> Generator[StreamDelta, None, None]:
        yield StreamDelta(
            content="",
            finish_reason="error",
            provider=self._provider_id,
            model_name=getattr(request, "model_name", "fake-model"),
        )


def _make_sse_events(*contents: str) -> List[Dict[str, Any]]:
    """Build a list of SSE event dicts from content strings."""
    events = []
    for c in contents:
        events.append({"choices": [{"delta": {"content": c}, "finish_reason": None}]})
    events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    return events


def _make_request(content: str = "test") -> ModelRequest:
    return ModelRequest(
        request_id="REQ-TEST-001",
        model_name="test-model",
        messages=[ModelMessage(role=ModelRole.USER, content=content)],
        temperature=0.0,
        max_tokens=100,
        timeout_seconds=10.0,
    )


# ── Test 1: Ordered content deltas ──────────────────────────────────

class TestOrderedContentDeltas(unittest.TestCase):
    def test_yields_content_in_order(self):
        events = _make_sse_events("Hello", " World", "!")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        content_deltas = [d for d in deltas if d.content]
        self.assertEqual(len(content_deltas), 3)
        self.assertEqual(content_deltas[0].content, "Hello")
        self.assertEqual(content_deltas[1].content, " World")
        self.assertEqual(content_deltas[2].content, "!")

    def test_assembled_content_matches_full_text(self):
        events = _make_sse_events("Stream", "ing test successful.")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        full_text = "".join(d.content for d in deltas if d.content)
        self.assertEqual(full_text, "Streaming test successful.")


# ── Test 2: Role-only SSE chunk ignored ─────────────────────────────

class TestRoleOnlyChunk(unittest.TestCase):
    def test_role_only_delta_ignored(self):
        events = [
            {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        content_deltas = [d for d in deltas if d.content]
        self.assertEqual(len(content_deltas), 1)
        self.assertEqual(content_deltas[0].content, "Hello")


# ── Test 3: finish_reason terminates generation ─────────────────────

class TestFinishReason(unittest.TestCase):
    def test_finish_reason_delta_present(self):
        events = _make_sse_events("Hi")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        finish_deltas = [d for d in deltas if d.finish_reason]
        self.assertEqual(len(finish_deltas), 1)
        self.assertEqual(finish_deltas[0].finish_reason, "stop")

    def test_no_content_after_finish_reason(self):
        events = [
            {"choices": [{"delta": {"content": "A"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [{"delta": {"content": "B"}, "finish_reason": None}]},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        content_after_finish = []
        found_finish = False
        for d in deltas:
            if d.finish_reason:
                found_finish = True
            elif found_finish and d.content:
                content_after_finish.append(d.content)
        self.assertEqual(len(content_after_finish), 0)


# ── Test 4: [DONE] accepted ────────────────────────────────────────

class TestDoneAccepted(unittest.TestCase):
    def test_done_terminates_stream(self):
        transport = FakeStreamTransport([])

        def custom_stream(endpoint_path, payload, timeout_seconds=None):
            yield {"choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]}
            yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}
            # [DONE] is handled by transport, not yielded as event

        transport.post_json_stream = custom_stream
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        self.assertTrue(any(d.content == "Hi" for d in deltas))
        self.assertTrue(any(d.finish_reason == "stop" for d in deltas))


# ── Test 5: No requirement to wait for socket EOF ───────────────────

class TestNoSocketEOF(unittest.TestCase):
    def test_stream_ends_on_finish_reason(self):
        events = [
            {"choices": [{"delta": {"content": "X"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        last_delta = deltas[-1]
        self.assertEqual(last_delta.finish_reason, "stop")


# ── Test 6: Malformed SSE handling ──────────────────────────────────

class TestMalformedSSE(unittest.TestCase):
    def test_malformed_json_skipped(self):
        events = [
            {"choices": [{"delta": {"content": "Good"}, "finish_reason": None}]},
            {"_malformed": True},
            {"choices": [{"delta": {"content": "End"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        content = "".join(d.content for d in deltas if d.content)
        self.assertIn("Good", content)
        self.assertIn("End", content)


# ── Test 7: Provider error before first token → fallback ────────────

class TestErrorBeforeFirstToken(unittest.TestCase):
    def test_error_yields_error_delta(self):
        transport = FakeStreamTransport([], error={"_error": True, "status_code": 500, "body": "server error"})
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")

    def test_gateway_fallback_on_error_before_first_token(self):
        transport_a = FakeStreamTransport([], error={"_error": True, "status_code": 500, "body": "a down"})
        events_b = _make_sse_events("recovered from b")
        transport_b = FakeStreamTransport(events_b)

        adapter_a = OpenAICompatibleProviderAdapter(
            provider_id="provider_a",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport_a,
        )
        adapter_b = OpenAICompatibleProviderAdapter(
            provider_id="provider_b",
            base_url="https://fake-b.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport_b,
        )

        prov_def_a = ProviderDefinition(
            provider_id="provider_a",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        prov_def_b = ProviderDefinition(
            provider_id="provider_b",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-b.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        registry = ProviderRegistry()
        registry.register_provider(prov_def_a)
        registry.register_provider(prov_def_b)
        registry._injected_adapters["provider_a"] = adapter_a
        registry._injected_adapters["provider_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="test-model"),
            fallback_chain=[
                ModelTarget(provider_id="provider_a", model_id="test-model"),
                ModelTarget(provider_id="provider_b", model_id="test-model"),
            ],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        content = "".join(d.content for d in deltas if d.content)
        self.assertEqual(content, "recovered from b")


# ── Test 8: Stream unsupported before first token → fallback/degradation ──

class TestStreamUnsupported(unittest.TestCase):
    def test_base_adapter_yields_stream_unsupported(self):
        class RawAdapter(BaseModelAdapter):
            @property
            def provider_name(self):
                return "raw"
            def generate(self, request):
                return ModelResponse(request_id="R", provider="raw", model_name="m", status=ModelResponseStatus.SUCCESS, content="x")

        adapter = RawAdapter()
        deltas = list(adapter.generate_stream(_make_request()))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "stream_unsupported")


# ── Test 9: Synchronous provider degradation ────────────────────────

class TestSyncDegradation(unittest.TestCase):
    def test_sync_response_as_single_delta(self):
        adapter = FakeNonStreamingAdapter(provider_id="sync_prov", response_content="synchronous result")
        prov_def = ProviderDefinition(
            provider_id="sync_prov",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        registry = ProviderRegistry()
        registry.register_provider(prov_def)
        registry._injected_adapters["sync_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_prov", model_id="test-model"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "synchronous result")
        self.assertEqual(deltas[0].finish_reason, "stop")

    def test_gateway_degrades_non_streaming_adapter_to_single_delta(self):
        adapter = FakeNonStreamingAdapter(provider_id="sync_prov", response_content="gw sync result")
        prov_def = ProviderDefinition(
            provider_id="sync_prov",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        registry = ProviderRegistry()
        registry.register_provider(prov_def)
        registry._injected_adapters["sync_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_prov", model_id="test-model"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "gw sync result")
        self.assertEqual(deltas[0].finish_reason, "stop")


# ── Test 10: Provider error after first visible token → NO fallback ──

class TestErrorAfterFirstToken(unittest.TestCase):
    def test_gateway_no_fallback_after_content(self):
        events_first = [
            {"choices": [{"delta": {"content": "Partial"}, "finish_reason": None}]},
            {"_error": True, "status_code": 500, "body": "mid-stream error"},
        ]
        transport_first = FakeStreamTransport(events_first)

        adapter_first = OpenAICompatibleProviderAdapter(
            provider_id="provider_a",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport_first,
        )

        prov_def_a = ProviderDefinition(
            provider_id="provider_a",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        prov_def_b = ProviderDefinition(
            provider_id="provider_b",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-b.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        registry = ProviderRegistry()
        registry.register_provider(prov_def_a)
        registry.register_provider(prov_def_b)
        registry._injected_adapters["provider_a"] = adapter_first
        registry._injected_adapters["provider_b"] = FakeNonStreamingAdapter(provider_id="provider_b", response_content="SHOULD_NOT_BE_CALLED")

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="test-model"),
            fallback_chain=[
                ModelTarget(provider_id="provider_a", model_id="test-model"),
                ModelTarget(provider_id="provider_b", model_id="test-model"),
            ],
            free_only_mode=False,
        )

        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        content = "".join(d.content for d in deltas if d.content)
        self.assertEqual(content, "Partial")
        self.assertNotIn("SHOULD_NOT_BE_CALLED", content)
        error_deltas = [d for d in deltas if d.finish_reason == "error"]
        self.assertGreaterEqual(len(error_deltas), 1)


# ── Test 11: Partial-output failure surfaced ────────────────────────

class TestPartialOutputFailure(unittest.TestCase):
    def test_partial_content_emitted_before_error(self):
        events = [
            {"choices": [{"delta": {"content": "Part1"}, "finish_reason": None}]},
            {"_error": True, "status_code": 500, "body": "broken"},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        content = "".join(d.content for d in deltas if d.content)
        self.assertIn("Part1", content)
        has_error = any(d.finish_reason == "error" for d in deltas)
        self.assertTrue(has_error)


# ── Test 12: Correct complete text assembly ─────────────────────────

class TestTextAssembly(unittest.TestCase):
    def test_delta_sum_equals_final(self):
        events = _make_sse_events("alpha", " ", "beta", " ", "gamma")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        assembled = "".join(d.content for d in deltas if d.content)
        self.assertEqual(assembled, "alpha beta gamma")

    def test_assembly_from_gateway_matches(self):
        events = _make_sse_events("g1", "-", "g2")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test_gw",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )

        prov_def = ProviderDefinition(
            provider_id="test_gw",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        registry = ProviderRegistry()
        registry.register_provider(prov_def)
        registry._injected_adapters["test_gw"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="test_gw", model_id="test-model"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        assembled = "".join(d.content for d in deltas if d.content)
        self.assertEqual(assembled, "g1-g2")


# ── Test 13: Generator close closes response ───────────────────────

class TestGeneratorCleanup(unittest.TestCase):
    def test_generator_close_calls_cleanup(self):
        class TrackingTransport:
            def __init__(self):
                self.close_called = False
                self._events = _make_sse_events("A")

            def build_headers(self):
                return {}

            def post_json_stream(self, endpoint_path, payload, timeout_seconds=None):
                try:
                    for e in self._events:
                        yield e
                finally:
                    self.close_called = True

        transport = TrackingTransport()
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        gen = adapter.generate_stream(_make_request())
        next(gen)
        gen.close()
        self.assertTrue(transport.close_called)

    def test_finally_block_executed_on_close(self):
        cleanup_ran = []

        def fake_stream(endpoint_path, payload, timeout_seconds=None):
            try:
                yield {"choices": [{"delta": {"content": "X"}, "finish_reason": None}]}
            finally:
                cleanup_ran.append(True)

        transport = MagicMock()
        transport.post_json_stream = fake_stream
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        gen = adapter.generate_stream(_make_request())
        next(gen)
        gen.close()
        self.assertEqual(len(cleanup_ran), 1)


# ── Test 14: Run-pinned provider snapshot preserved ─────────────────

class TestRunPinnedSnapshot(unittest.TestCase):
    def test_snapshot_used_for_adapter_resolution(self):
        adapter_a = FakeNonStreamingAdapter(provider_id="provider_a")
        adapter_b = FakeNonStreamingAdapter(provider_id="provider_b")

        prov_def_a = ProviderDefinition(
            provider_id="provider_a",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        prov_def_b = ProviderDefinition(
            provider_id="provider_b",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-b.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        registry = ProviderRegistry()
        registry.register_provider(prov_def_a)
        registry.register_provider(prov_def_b)
        registry._injected_adapters["provider_a"] = adapter_a
        registry._injected_adapters["provider_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="test-model"),
            fallback_chain=[ModelTarget(provider_id="provider_a", model_id="test-model")],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)

        snapshot = registry.snapshot()
        deltas = list(gateway.generate_stream(_make_request(), provider_snapshot=snapshot, model_policy=policy))
        content = "".join(d.content for d in deltas if d.content)
        self.assertIn("sync response", content)


# ── Test 15: Candidate ordering preserved ───────────────────────────

class TestCandidateOrdering(unittest.TestCase):
    def test_first_candidate_tried_first(self):
        adapter_a = FakeFailingAdapter(provider_id="provider_a")
        adapter_b = FakeNonStreamingAdapter(provider_id="provider_b", response_content="from_b")

        prov_def_a = ProviderDefinition(
            provider_id="provider_a",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-a.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        prov_def_b = ProviderDefinition(
            provider_id="provider_b",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://fake-b.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        registry = ProviderRegistry()
        registry.register_provider(prov_def_a)
        registry.register_provider(prov_def_b)
        registry._injected_adapters["provider_a"] = adapter_a
        registry._injected_adapters["provider_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="test-model"),
            fallback_chain=[
                ModelTarget(provider_id="provider_a", model_id="test-model"),
                ModelTarget(provider_id="provider_b", model_id="test-model"),
            ],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        content = "".join(d.content for d in deltas if d.content)
        self.assertIn("from_b", content)


# ── Test 16: No provider/model hard-code ────────────────────────────

class TestNoHardcode(unittest.TestCase):
    def test_stream_uses_policy_targets(self):
        events = _make_sse_events("ok")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="custom_provider",
            base_url="https://custom.test/v1",
            api_key_env="TEST_KEY",
            default_model="custom-model",
            api_key="sk-test-12345",
            transport=transport,
        )

        prov_def = ProviderDefinition(
            provider_id="custom_provider",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://custom.test/v1",
            api_key_env="TEST_KEY",
            default_model="custom-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        registry = ProviderRegistry()
        registry.register_provider(prov_def)
        registry._injected_adapters["custom_provider"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="custom_provider", model_id="custom-model"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False)
        deltas = list(gateway.generate_stream(_make_request(), model_policy=policy))
        self.assertEqual(transport._last_payload["model"], "custom-model")


# ── Test 17: No secret leakage ─────────────────────────────────────

class TestNoSecretLeakage(unittest.TestCase):
    def test_stream_deltas_contain_no_api_key(self):
        secret_key = "sk-super-secret-key-12345abcde"
        events = _make_sse_events("safe content")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key=secret_key,
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        for d in deltas:
            self.assertNotIn(secret_key, repr(d))
            self.assertNotIn("Bearer", repr(d))
            self.assertNotIn("Authorization", repr(d))

    def test_transport_headers_contain_key_but_stream_delta_does_not(self):
        secret_key = "sk-another-secret-xyz789"
        events = _make_sse_events("content")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key=secret_key,
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        all_text = " ".join(repr(d) for d in deltas)
        self.assertNotIn(secret_key, all_text)


# ── Test 18: Reasoning/internal fields not forwarded ────────────────

class TestNoReasoningFields(unittest.TestCase):
    def test_reasoning_content_not_in_delta(self):
        events = [
            {
                "choices": [{
                    "delta": {"content": "visible text", "reasoning": "internal thought", "reasoning_content": "more internal"},
                    "finish_reason": None,
                }]
            },
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        deltas = list(adapter.generate_stream(_make_request()))
        for d in deltas:
            self.assertNotIn("reasoning", d.model_dump())
            self.assertNotIn("reasoning_content", d.model_dump())


# ── Test 19: Existing synchronous generate() unchanged ─────────────

class TestSyncGenerateUnchanged(unittest.TestCase):
    def test_generate_returns_model_response(self):
        events = _make_sse_events("unused")
        transport = FakeStreamTransport(events)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="test",
            base_url="https://fake.test/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            api_key="sk-test-12345",
            transport=transport,
        )
        response = adapter.generate(_make_request())
        self.assertIsInstance(response, ModelResponse)
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)


# ── Test 20: Gemini/TheSpark adapters still instantiate ─────────────

class TestExistingAdapters(unittest.TestCase):
    def test_gemini_adapter_instantiates(self):
        from integrations.models.gemini_adapter import GeminiProviderAdapter
        adapter = GeminiProviderAdapter(api_key="fake-key", default_model="gemini-flash-latest")
        self.assertEqual(adapter.provider_name, "gemini")
        self.assertTrue(hasattr(adapter, "generate"))
        self.assertTrue(hasattr(adapter, "generate_stream"))

    def test_thespark_adapter_instantiates(self):
        from integrations.models.thespark_adapter import TheSparkProviderAdapter
        adapter = TheSparkProviderAdapter(api_key="fake-key", base_url="https://fake.test/v1")
        self.assertEqual(adapter.provider_name, "thespark")
        self.assertTrue(hasattr(adapter, "generate"))
        self.assertTrue(hasattr(adapter, "generate_stream"))


if __name__ == "__main__":
    unittest.main()
