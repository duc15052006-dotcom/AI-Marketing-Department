"""A1-STRUCTURED-PROVIDER-ERROR-TRUTH-HALF-1-R3-FINAL: Targeted Tests.

Validates the lower-half structured model/provider stream error contract:
Transport -> Provider Adapter -> Universal Model Gateway.
Covers all ChatGPT R1, R2, and R3 final hardening passes:
1. BaseException / Process control-flow exception handling (GeneratorExit, KeyboardInterrupt, SystemExit)
2. Real transport generator cancellation (generator.close())
3. Universal gateway stream terminal enforcement for all generic BaseModelAdapter implementations
4. Universal gateway generic exception boundary secret isolation (zero raw exception text in safe_message)
5. Non-synthesis of HTTP 500 for internal synchronous transport exceptions
6. Single terminal delta guarantee (zero double-wrapping of structured errors)
"""

from __future__ import annotations

import errno
import io
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import urllib.error

from integrations.models.base import (
    MAX_SAFE_MESSAGE_LEN,
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelStreamError,
    ModelUsage,
    StreamDelta,
    normalize_model_request,
)
from integrations.models.config_service import ProviderConfigService, ProviderErrorCode
from integrations.models.gateway import (
    CANONICAL_STREAM_ERROR_CATEGORIES,
    CANONICAL_STREAM_ERROR_CODES,
    UniversalModelGateway,
    model_response_to_stream_error,
    normalize_public_stream_delta,
    normalize_public_stream_error,
    provider_error_code_to_stream_error,
    stream_error_to_provider_error_code,
)
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.registry import (
    ModelPolicy,
    ModelTarget,
    ProviderDefinition,
    ProviderRegistry,
)
from integrations.models.transport import (
    OpenAICompatibleTransport,
    classify_transport_error,
    classify_transport_to_stream_error,
    is_network_exception,
    is_timeout_exception,
    sanitize_secrets,
)


# ── Test Adapter Helpers ──────────────────────────────────────────

class MockTransport:
    """Mock transport returning configured SSE events or error payloads."""

    def __init__(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        error_event: Optional[Dict[str, Any]] = None,
        exception_to_raise: Optional[Exception] = None,
    ) -> None:
        self._events = events or []
        self._error_event = error_event
        self._exception = exception_to_raise
        self.last_payload: Optional[Dict[str, Any]] = None

    def build_headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": "Bearer secret-test-token"}

    def post_json_stream(
        self,
        endpoint_path: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        self.last_payload = payload
        if self._exception:
            raise self._exception
        if self._error_event:
            yield self._error_event
            return
        for evt in self._events:
            yield evt

    def post_json(
        self,
        endpoint_path: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> Tuple[int, Dict[str, str], str]:
        self.last_payload = payload
        if self._exception:
            raise self._exception
        if self._error_event:
            status = self._error_event.get("status_code", 500)
            body = self._error_event.get("body", "Error")
            headers = self._error_event.get("headers", {})
            return status, headers, body
        resp = {
            "choices": [{"message": {"role": "assistant", "content": "Sync fallback response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }
        return 200, {}, json.dumps(resp)


class MockSyncOnlyAdapter(BaseModelAdapter):
    """Adapter that does not implement streaming (yields stream_unsupported)."""

    def __init__(
        self,
        provider_name_val: str = "mock_sync_only",
        content: str = "Synchronous degradation success",
        status: ModelResponseStatus = ModelResponseStatus.SUCCESS,
        error_msg: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        exception_to_raise: Optional[Exception] = None,
    ):
        self._provider_name = provider_name_val
        self._content = content
        self._status = status
        self._error_msg = error_msg
        self._metadata = metadata or {}
        self._exception = exception_to_raise

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._exception:
            raise self._exception
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=self._status,
            content=self._content if self._status == ModelResponseStatus.SUCCESS else "",
            error=self._error_msg,
            metadata=self._metadata,
            finish_reason="stop" if self._status == ModelResponseStatus.SUCCESS else "error",
        )


class GenericMockStreamingAdapter(BaseModelAdapter):
    """Generic custom BaseModelAdapter yielding explicit StreamDelta sequences or raising exceptions."""

    def __init__(
        self,
        provider_name_val: str,
        deltas: Optional[List[StreamDelta]] = None,
        exception_to_raise: Optional[Exception] = None,
    ) -> None:
        self._provider_name = provider_name_val
        self._deltas = deltas or []
        self._exception = exception_to_raise

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._exception:
            raise self._exception
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="Generic mock generate content",
            finish_reason="stop",
        )

    def generate_stream(self, request: ModelRequest) -> Generator[StreamDelta, None, None]:
        if self._exception:
            raise self._exception
        for delta in self._deltas:
            yield delta


class TestStructuredProviderStreamError01(unittest.TestCase):
    """Targeted tests for Phase A1 Half-1-R3 Final Structured Stream Error Contract."""

    def _make_adapter(
        self,
        provider_id: str = "test_prov",
        api_key: Optional[str] = "test-api-key-12345",
        transport: Optional[Any] = None,
    ) -> OpenAICompatibleProviderAdapter:
        return OpenAICompatibleProviderAdapter(
            provider_id=provider_id,
            base_url="https://api.test-provider.com/v1",
            api_key_env="TEST_PROV_API_KEY",
            default_model="test-model-v1",
            api_key=api_key,
            transport=transport,
        )

    def _make_request(self, content: str = "Hello test") -> ModelRequest:
        return ModelRequest(
            model_name="test-model-v1",
            messages=[ModelMessage(role=ModelRole.USER, content=content)],
        )

    # ------------------------------------------------------------------
    # 1. HTTP 401 -> AUTH_ERROR
    # ------------------------------------------------------------------
    def test_01_http_401_auth_error_preserved(self) -> None:
        """Assert HTTP 401 yields StreamDelta with structured AUTH_ERROR."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 401,
                "headers": {},
                "body": json.dumps({"error": {"message": "Invalid API key provided", "code": "invalid_api_key"}}),
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "AUTH_ERROR")
        self.assertEqual(delta.error.category, "AUTHENTICATION")
        self.assertEqual(delta.error.http_status, 401)
        self.assertFalse(delta.error.retryable)
        self.assertIn("401", delta.error.safe_message)

    # ------------------------------------------------------------------
    # 2. HTTP 403 Permission / Access Denied
    # ------------------------------------------------------------------
    def test_02_http_403_permission_error_preserved(self) -> None:
        """Assert HTTP 403 yields StreamDelta with structured AUTHORIZATION_ERROR."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 403,
                "headers": {},
                "body": json.dumps({"error": {"message": "Access forbidden for this resource", "code": "permission_denied"}}),
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertIn(delta.error.code, ("AUTHORIZATION_ERROR", "PROVIDER_ACCESS_DENIED"))
        self.assertEqual(delta.error.category, "AUTHORIZATION")
        self.assertEqual(delta.error.http_status, 403)
        self.assertFalse(delta.error.retryable)

    # ------------------------------------------------------------------
    # 3. HTTP 429 -> RATE_LIMITED
    # ------------------------------------------------------------------
    def test_03_http_429_rate_limited_preserved(self) -> None:
        """Assert HTTP 429 yields StreamDelta with structured RATE_LIMITED and retryable=True."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 429,
                "headers": {},
                "body": json.dumps({"error": {"message": "Rate limit exceeded. Quota reached.", "code": "rate_limit_exceeded"}}),
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "RATE_LIMITED")
        self.assertEqual(delta.error.category, "RATE_LIMIT")
        self.assertEqual(delta.error.http_status, 429)
        self.assertTrue(delta.error.retryable)

    # ------------------------------------------------------------------
    # 4. Timeout -> TIMEOUT
    # ------------------------------------------------------------------
    def test_04_timeout_error_preserved(self) -> None:
        """Assert request timeout yields StreamDelta with structured TIMEOUT and retryable=True."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 408,
                "headers": {},
                "body": "Request timed out after 30.0s",
                "is_timeout": True,
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "TIMEOUT")
        self.assertEqual(delta.error.category, "TIMEOUT")
        self.assertTrue(delta.error.retryable)

    # ------------------------------------------------------------------
    # 5. Network Failure -> NETWORK_ERROR
    # ------------------------------------------------------------------
    def test_05_network_error_preserved(self) -> None:
        """Assert connection failure yields StreamDelta with structured NETWORK_ERROR."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 599,
                "headers": {},
                "body": "<urlopen error [Errno 111] Connection refused>",
                "is_timeout": False,
                "is_network": True,
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "NETWORK_ERROR")
        self.assertEqual(delta.error.category, "NETWORK")
        self.assertTrue(delta.error.retryable)
        self.assertIsNone(delta.error.http_status)

    # ------------------------------------------------------------------
    # 6. HTTP 500/503 -> PROVIDER_UNAVAILABLE
    # ------------------------------------------------------------------
    def test_06_http_500_503_provider_unavailable_preserved(self) -> None:
        """Assert HTTP 500/503 yields StreamDelta with structured PROVIDER_UNAVAILABLE and retryable=True."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 503,
                "headers": {},
                "body": "Service Unavailable. Backends overloaded.",
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "PROVIDER_UNAVAILABLE")
        self.assertEqual(delta.error.category, "SERVER_ERROR")
        self.assertEqual(delta.error.http_status, 503)
        self.assertTrue(delta.error.retryable)

    # ------------------------------------------------------------------
    # 7. Malformed Request -> REQUEST_SCHEMA_ERROR
    # ------------------------------------------------------------------
    def test_07_request_schema_error_preserved(self) -> None:
        """Assert malformed request yields StreamDelta with structured REQUEST_SCHEMA_ERROR."""
        adapter = self._make_adapter()
        deltas = list(adapter.generate_stream(None))  # type: ignore

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "REQUEST_SCHEMA_ERROR")
        self.assertEqual(delta.error.category, "VALIDATION")
        self.assertFalse(delta.error.retryable)

    # ------------------------------------------------------------------
    # 8. Missing API Key -> NO_CREDENTIAL
    # ------------------------------------------------------------------
    def test_08_missing_api_key_structured_error(self) -> None:
        """Assert unconfigured adapter yields StreamDelta with structured NO_CREDENTIAL."""
        adapter = self._make_adapter(api_key="")
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertEqual(delta.finish_reason, "error")
        self.assertIsNotNone(delta.error)
        self.assertEqual(delta.error.code, "NO_CREDENTIAL")
        self.assertEqual(delta.error.category, "CONFIGURATION")
        self.assertFalse(delta.error.retryable)

    # ------------------------------------------------------------------
    # 9. Gateway Fallback: A fails before token, B succeeds
    # ------------------------------------------------------------------
    def test_09_gateway_fallback_before_token_succeeds(self) -> None:
        """Assert Candidate A failing before first token falls back to B without emitting A's error."""
        t_a = MockTransport(error_event={"_error": True, "status_code": 429, "body": "Rate limited"})
        t_b = MockTransport(events=[
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "World!"}}]},
            {"_done": True},
        ])

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        req = self._make_request()
        deltas = list(gw.generate_stream(req, model_policy=policy))

        text = "".join(d.content for d in deltas)
        self.assertEqual(text, "Hello World!")
        error_deltas = [d for d in deltas if d.finish_reason == "error"]
        self.assertEqual(len(error_deltas), 0)

    # ------------------------------------------------------------------
    # 10. Gateway: All Candidates Fail (Preserve Provenance)
    # ------------------------------------------------------------------
    def test_10_gateway_all_candidates_fail_before_token_preserves_root_error_and_provenance(self) -> None:
        """Assert when all candidates fail before token, terminal delta retains exact candidate provider and error."""
        t_a = MockTransport(error_event={"_error": True, "status_code": 429, "body": "Rate limited A"})
        t_b = MockTransport(error_event={"_error": True, "status_code": 401, "body": "Unauthorized B"})

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        req = self._make_request()
        deltas = list(gw.generate_stream(req, model_policy=policy))

        self.assertEqual(len(deltas), 1)
        term_delta = deltas[0]
        self.assertEqual(term_delta.finish_reason, "error")
        self.assertIsNotNone(term_delta.error)
        self.assertEqual(term_delta.error.code, "AUTH_ERROR")
        self.assertEqual(term_delta.error.category, "AUTHENTICATION")
        self.assertEqual(term_delta.error.http_status, 401)
        self.assertEqual(term_delta.provider, "prov_b")
        self.assertEqual(term_delta.model_name, "m2")

    # ------------------------------------------------------------------
    # 11. Gateway: Visible Content from A Then A Errors (No Fallback)
    # ------------------------------------------------------------------
    def test_11_gateway_error_after_visible_token_forbids_fallback_and_emits_root_error(self) -> None:
        """Assert once visible content is emitted, zero fallback attempts occur and exact A error is emitted."""
        t_a = MockTransport(events=[
            {"choices": [{"delta": {"content": "Partial visible start. "}}]},
            {"_error": True, "status_code": 429, "body": "Rate limit exceeded mid-stream"},
        ])
        t_b = MockTransport(events=[
            {"choices": [{"delta": {"content": "B SHOULD NEVER BE CALLED"}}]},
        ])

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        req = self._make_request()
        deltas = list(gw.generate_stream(req, model_policy=policy))

        self.assertEqual(deltas[0].content, "Partial visible start. ")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")
        self.assertEqual(deltas[-1].provider, "prov_a")
        self.assertIsNone(t_b.last_payload)

    # ------------------------------------------------------------------
    # 12. Disabled Provider
    # ------------------------------------------------------------------
    def test_12_disabled_provider_structured_error(self) -> None:
        """Assert disabled provider yields structured PROVIDER_DISABLED error."""
        adapter = self._make_adapter(provider_id="prov_disabled")
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(
            provider_id="prov_disabled",
            display_name="Disabled Prov",
            enabled=False,
        ))
        reg._injected_adapters["prov_disabled"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_disabled", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_disabled", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "PROVIDER_DISABLED")
        self.assertEqual(deltas[0].error.category, "CONFIGURATION")
        self.assertEqual(deltas[0].provider, "prov_disabled")

    # ------------------------------------------------------------------
    # 13. Free-Only Policy Block (PAID)
    # ------------------------------------------------------------------
    def test_13_free_only_policy_block_paid_model(self) -> None:
        """Assert free-only mode blocking paid model yields truthful paid message."""
        adapter = self._make_adapter(provider_id="prov_paid")
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(
            provider_id="prov_paid",
            display_name="Paid Prov",
            cost_policy=CostPolicy.PAID,
        ))
        reg._injected_adapters["prov_paid"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_paid", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_paid", model_id="m1")],
            free_only_mode=True,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=True)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy, allow_paid=False))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "FREE_ONLY_POLICY_VIOLATION")
        self.assertEqual(deltas[0].error.category, "POLICY")
        self.assertIn("requires paid tier", deltas[0].error.safe_message)

    # ------------------------------------------------------------------
    # 14. No Candidates & Missing Adapter
    # ------------------------------------------------------------------
    def test_14_no_candidates_and_missing_adapter_structured_error(self) -> None:
        """Assert empty candidate list or missing adapter yields structured error."""
        reg = ProviderRegistry()
        policy_missing = ModelPolicy(
            global_target=ModelTarget(provider_id="non_existent", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="non_existent", model_id="m1")],
            free_only_mode=False,
        )
        gw_missing = UniversalModelGateway(provider_registry=reg, model_policy=policy_missing, free_only_mode=False)
        deltas = list(gw_missing.generate_stream(self._make_request(), model_policy=policy_missing))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "NO_AVAILABLE_PROVIDER")
        self.assertEqual(deltas[0].error.category, "CONFIGURATION")
        self.assertEqual(deltas[0].provider, "non_existent")

        gw_no_cand = UniversalModelGateway(provider_registry=reg)
        with patch.object(gw_no_cand, "resolve_candidate_chain", return_value=[]):
            deltas_no_cand = list(gw_no_cand.generate_stream(self._make_request()))
            self.assertEqual(len(deltas_no_cand), 1)
            self.assertEqual(deltas_no_cand[0].error.code, "NO_CANDIDATE_MODELS")
            self.assertEqual(deltas_no_cand[0].error.category, "ROUTING")
            self.assertEqual(deltas_no_cand[0].provider, "gateway")

    # ------------------------------------------------------------------
    # 15. Secret Sanitization
    # ------------------------------------------------------------------
    def test_15_secret_sanitization_in_stream_error(self) -> None:
        """Assert fake API key, Bearer tokens, and Authorization headers are redacted from ModelStreamError."""
        fake_secret = "sk-TEST-DO-NOT-USE-123456789"
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 401,
                "headers": {"authorization": f"Bearer {fake_secret}"},
                "body": f"Unauthorized request using key {fake_secret} and Authorization: Bearer {fake_secret}",
            }
        )
        adapter = self._make_adapter(api_key=fake_secret, transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        delta = deltas[0]
        self.assertIsNotNone(delta.error)
        safe_msg = delta.error.safe_message

        self.assertNotIn(fake_secret, safe_msg)
        self.assertNotIn(fake_secret, str(delta))
        self.assertNotIn("Bearer sk-", safe_msg)

    # ------------------------------------------------------------------
    # 16. Normal Successful Stream Unchanged
    # ------------------------------------------------------------------
    def test_16_normal_successful_stream_unchanged(self) -> None:
        """Assert normal successful streaming yields ordered deltas and no error."""
        transport = MockTransport(events=[
            {"choices": [{"delta": {"content": "Chunk 1, "}}]},
            {"choices": [{"delta": {"content": "Chunk 2, "}}]},
            {"choices": [{"delta": {"content": "Chunk 3."}}]},
            {"_done": True},
        ])
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        content_deltas = [d for d in deltas if d.content]
        self.assertEqual(len(content_deltas), 3)
        full_text = "".join(d.content for d in content_deltas)
        self.assertEqual(full_text, "Chunk 1, Chunk 2, Chunk 3.")
        self.assertEqual(deltas[-1].finish_reason, "stop")
        error_deltas = [d for d in deltas if d.finish_reason == "error"]
        self.assertEqual(len(error_deltas), 0)

    # ------------------------------------------------------------------
    # 17. stream_unsupported Synchronous Degradation Unchanged
    # ------------------------------------------------------------------
    def test_17_stream_unsupported_degradation_unchanged(self) -> None:
        """Assert non-streaming adapter degrades cleanly to single delta via gateway."""
        sync_adapter = MockSyncOnlyAdapter(provider_name_val="sync_prov", content="Synchronous full content")
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_prov", display_name="Sync Prov"))
        reg._injected_adapters["sync_prov"] = sync_adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_prov", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_prov", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "Synchronous full content")
        self.assertEqual(deltas[0].finish_reason, "stop")
        self.assertIsNone(deltas[0].error)

    # ------------------------------------------------------------------
    # 18. Terminal Candidate Provenance Retention
    # ------------------------------------------------------------------
    def test_18_terminal_candidate_provenance_retention(self) -> None:
        """Assert when candidate A (RATE_LIMITED) and candidate B (AUTH_ERROR) both fail, final delta is prov_b / m2."""
        t_a = MockTransport(error_event={"_error": True, "status_code": 429, "body": "Too many requests"})
        t_b = MockTransport(error_event={"_error": True, "status_code": 401, "body": "Invalid key"})

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        term = deltas[0]
        self.assertEqual(term.finish_reason, "error")
        self.assertEqual(term.provider, "prov_b")
        self.assertEqual(term.model_name, "m2")
        self.assertEqual(term.error.code, "AUTH_ERROR")
        self.assertEqual(term.error.http_status, 401)

    # ------------------------------------------------------------------
    # 19. Machine Code Does Not Depend on Message String
    # ------------------------------------------------------------------
    def test_19_machine_code_independent_of_message_text(self) -> None:
        """Assert classification uses canonical metadata and never parses safe_message string."""
        res_429 = classify_transport_error(status_code=429, headers={}, body_str="Custom unstructured error string", provider_name="p")
        self.assertEqual(res_429["code"], "RATE_LIMITED")
        self.assertEqual(res_429["category"], "RATE_LIMIT")

        res_401 = classify_transport_error(status_code=401, headers={}, body_str="Custom unauthorized text", provider_name="p")
        self.assertEqual(res_401["code"], "AUTH_ERROR")
        self.assertEqual(res_401["category"], "AUTHENTICATION")

        stream_err = classify_transport_to_stream_error(
            status_code=429,
            headers={},
            body_str="Arbitrary human prose from vendor",
            provider_name="vendor_x",
        )
        self.assertEqual(stream_err.code, "RATE_LIMITED")
        self.assertEqual(stream_err.category, "RATE_LIMIT")

    # ------------------------------------------------------------------
    # 20. Native Stream vs Sync Degradation Error Equivalence
    # ------------------------------------------------------------------
    def test_20_native_stream_and_sync_degradation_error_equivalence(self) -> None:
        """Assert HTTP 429, HTTP 401, and Timeout yield identical ModelStreamError code & category in both stream & sync modes."""
        # 1. Rate Limit 429 Equivalence
        t_stream_429 = MockTransport(error_event={"_error": True, "status_code": 429, "body": "Rate limited"})
        adapter_stream_429 = self._make_adapter(provider_id="p_stream_429", transport=t_stream_429)
        deltas_stream_429 = list(adapter_stream_429.generate_stream(self._make_request()))
        err_stream_429 = deltas_stream_429[0].error

        sync_adapter_429 = MockSyncOnlyAdapter(
            provider_name_val="p_sync_429",
            status=ModelResponseStatus.RATE_LIMITED,
            error_msg="RATE_LIMITED: 429 Too Many Requests",
            metadata={"error_code": "RATE_LIMITED", "error_category": "RATE_LIMIT", "retryable": True, "http_status": 429},
        )
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="p_sync_429", display_name="P Sync 429"))
        reg._injected_adapters["p_sync_429"] = sync_adapter_429
        policy_429 = ModelPolicy(global_target=ModelTarget(provider_id="p_sync_429", model_id="m1"), fallback_chain=[ModelTarget(provider_id="p_sync_429", model_id="m1")])
        gw_429 = UniversalModelGateway(provider_registry=reg, model_policy=policy_429, free_only_mode=False)
        deltas_sync_429 = list(gw_429.generate_stream(self._make_request(), model_policy=policy_429))
        err_sync_429 = deltas_sync_429[0].error

        self.assertEqual(err_stream_429.code, err_sync_429.code)
        self.assertEqual(err_stream_429.category, err_sync_429.category)
        self.assertEqual(err_stream_429.retryable, err_sync_429.retryable)

        # 2. Auth 401 Equivalence
        t_stream_401 = MockTransport(error_event={"_error": True, "status_code": 401, "body": "Unauthorized"})
        adapter_stream_401 = self._make_adapter(provider_id="p_stream_401", transport=t_stream_401)
        deltas_stream_401 = list(adapter_stream_401.generate_stream(self._make_request()))
        err_stream_401 = deltas_stream_401[0].error

        sync_adapter_401 = MockSyncOnlyAdapter(
            provider_name_val="p_sync_401",
            status=ModelResponseStatus.ERROR,
            error_msg="AUTH_ERROR: 401 Unauthorized",
            metadata={"error_code": "AUTH_ERROR", "error_category": "AUTHENTICATION", "retryable": False, "http_status": 401},
        )
        reg._injected_adapters["p_sync_401"] = sync_adapter_401
        reg.register_provider(ProviderDefinition(provider_id="p_sync_401", display_name="P Sync 401"))
        policy_401 = ModelPolicy(global_target=ModelTarget(provider_id="p_sync_401", model_id="m1"), fallback_chain=[ModelTarget(provider_id="p_sync_401", model_id="m1")])
        gw_401 = UniversalModelGateway(provider_registry=reg, model_policy=policy_401, free_only_mode=False)
        deltas_sync_401 = list(gw_401.generate_stream(self._make_request(), model_policy=policy_401))
        err_sync_401 = deltas_sync_401[0].error

        self.assertEqual(err_stream_401.code, err_sync_401.code)
        self.assertEqual(err_stream_401.category, err_sync_401.category)
        self.assertEqual(err_stream_401.retryable, err_sync_401.retryable)

    # ------------------------------------------------------------------
    # 21. Programming Exceptions Are Never Network Errors
    # ------------------------------------------------------------------
    def test_21_internal_programming_exception_not_network_error(self) -> None:
        """Assert unexpected ValueError in stream is mapped to STREAM_INTERNAL_ERROR, NOT NETWORK_ERROR."""
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": None,
                "headers": {},
                "body": "ValueError: synthetic internal bug",
                "is_timeout": False,
                "is_network": False,
                "is_internal": True,
            }
        )
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "STREAM_INTERNAL_ERROR")
        self.assertEqual(err.category, "INTERNAL")
        self.assertFalse(err.retryable)
        self.assertNotIn("Traceback", err.safe_message)

    # ------------------------------------------------------------------
    # 22. Free-Only Truth for UNKNOWN Cost Policy
    # ------------------------------------------------------------------
    def test_22_unknown_cost_policy_truth(self) -> None:
        """Assert CostPolicy.UNKNOWN fail-closed error explicitly mentions unverified/unknown cost, NOT paid tier."""
        adapter = self._make_adapter(provider_id="prov_unknown")
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(
            provider_id="prov_unknown",
            display_name="Unknown Cost Prov",
            cost_policy=CostPolicy.UNKNOWN,
        ))
        reg._injected_adapters["prov_unknown"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_unknown", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_unknown", model_id="m1")],
            free_only_mode=True,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=True)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy, allow_paid=False))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "FREE_ONLY_POLICY_VIOLATION")
        self.assertEqual(err.category, "POLICY")
        self.assertIn("unverified/unknown cost policy", err.safe_message)
        self.assertNotIn("requires paid tier", err.safe_message)

    # ------------------------------------------------------------------
    # 23. Unexpected Stream Truncation Before Visible Content
    # ------------------------------------------------------------------
    def test_23_unexpected_stream_truncation_before_token_allows_fallback(self) -> None:
        """Assert stream ending abruptly before visible content yields STREAM_TRUNCATED and falls back to B."""
        t_a = MockTransport(events=[])  # Empty stream without [DONE] or finish_reason
        t_b = MockTransport(events=[
            {"choices": [{"delta": {"content": "Recovered by candidate B"}}]},
            {"_done": True},
        ])

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        content = "".join(d.content for d in deltas)
        self.assertEqual(content, "Recovered by candidate B")

    # ------------------------------------------------------------------
    # 24. Unexpected Stream Truncation After Visible Content
    # ------------------------------------------------------------------
    def test_24_unexpected_stream_truncation_after_token_forbids_fallback(self) -> None:
        """Assert stream ending abruptly after visible content yields STREAM_TRUNCATED and forbids fallback to B."""
        t_a = MockTransport(events=[
            {"choices": [{"delta": {"content": "First token emitted..."}}]},
            # Stream closes abruptly here without [DONE] or finish_reason
        ])
        t_b = MockTransport(events=[
            {"choices": [{"delta": {"content": "B SHOULD NEVER RUN"}}]},
        ])

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(deltas[0].content, "First token emitted...")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "STREAM_TRUNCATED")
        self.assertEqual(deltas[-1].provider, "prov_a")
        self.assertIsNone(t_b.last_payload)

    # ------------------------------------------------------------------
    # 25. Safe Message Strictly Capped at MAX_SAFE_MESSAGE_LEN (<= 500)
    # ------------------------------------------------------------------
    def test_25_safe_message_bounded_length_and_secrets(self) -> None:
        """Assert safe_message is strictly capped at MAX_SAFE_MESSAGE_LEN (<= 500 chars) and contains 0 secrets."""
        fake_secret = "sk-SUPER-SECRET-LONG-TOKEN-987654321"
        long_body = f"Provider detailed verbose message: {fake_secret} " + ("A" * 1200)
        transport = MockTransport(
            error_event={
                "_error": True,
                "status_code": 500,
                "headers": {},
                "body": long_body,
            }
        )
        adapter = self._make_adapter(api_key=fake_secret, transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertNotIn(fake_secret, err.safe_message)
        self.assertLessEqual(len(err.safe_message), MAX_SAFE_MESSAGE_LEN)

    # ------------------------------------------------------------------
    # 26. REAL Transport: ValueError is INTERNAL, not NETWORK
    # ------------------------------------------------------------------
    def test_26_real_transport_valueerror_is_internal_not_network(self) -> None:
        """Assert REAL OpenAICompatibleTransport post_json_stream handles ValueError as INTERNAL error."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.side_effect = ValueError("Unexpected JSON parser bug in read")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_timeout"))

    # ------------------------------------------------------------------
    # 27. REAL Transport: PermissionError is NOT NETWORK
    # ------------------------------------------------------------------
    def test_27_real_transport_permissionerror_is_not_network(self) -> None:
        """Assert REAL OpenAICompatibleTransport handles local PermissionError as INTERNAL, NOT NETWORK."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.side_effect = PermissionError("Local filesystem permission denied")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 28. REAL Transport: FileNotFoundError is NOT NETWORK
    # ------------------------------------------------------------------
    def test_28_real_transport_filenotfounderror_is_not_network(self) -> None:
        """Assert REAL OpenAICompatibleTransport urlopen FileNotFoundError is INTERNAL, NOT NETWORK."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=FileNotFoundError("Local cert bundle missing")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 29. REAL Transport: ConnectionResetError is NETWORK
    # ------------------------------------------------------------------
    def test_29_real_transport_connectionreseterror_is_network(self) -> None:
        """Assert REAL OpenAICompatibleTransport ConnectionResetError is correctly classified as NETWORK_ERROR."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.side_effect = ConnectionResetError("Connection reset by peer")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_timeout"))

    # ------------------------------------------------------------------
    # 30. REAL Transport: socket.timeout is TIMEOUT
    # ------------------------------------------------------------------
    def test_30_real_transport_socket_timeout_is_timeout(self) -> None:
        """Assert REAL OpenAICompatibleTransport socket.timeout is correctly classified as TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=socket.timeout("Socket read timed out")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))
        self.assertEqual(err_evt.get("status_code"), 408)

    # ------------------------------------------------------------------
    # 31. Sync Degradation: Machine Metadata Beats Contradictory Human Text
    # ------------------------------------------------------------------
    def test_31_sync_degradation_machine_metadata_beats_contradictory_text(self) -> None:
        """Assert machine metadata (AUTH_ERROR) strictly overrides contradictory human error text."""
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="sync_adv",
            status=ModelResponseStatus.ERROR,
            error_msg="Vendor prose says 429 Rate limited timeout network failure",
            metadata={
                "error_code": "AUTH_ERROR",
                "error_category": "AUTHENTICATION",
                "retryable": False,
                "http_status": 401,
            },
        )
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_adv", display_name="Sync Adv"))
        reg._injected_adapters["sync_adv"] = sync_adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_adv", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_adv", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "AUTH_ERROR")
        self.assertEqual(err.category, "AUTHENTICATION")
        self.assertFalse(err.retryable)
        self.assertEqual(err.http_status, 401)

    # ------------------------------------------------------------------
    # 32. Sync RATE_LIMIT Result Does Not Require "429" in Text
    # ------------------------------------------------------------------
    def test_32_sync_rate_limit_public_result_does_not_require_429_text(self) -> None:
        """Assert ModelResponseStatus.RATE_LIMITED produces RATE_LIMITED public stream error without '429' in string."""
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="sync_quota",
            status=ModelResponseStatus.RATE_LIMITED,
            error_msg="Monthly credits quota completely exhausted",
        )
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_quota", display_name="Sync Quota"))
        reg._injected_adapters["sync_quota"] = sync_adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_quota", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_quota", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "RATE_LIMITED")
        self.assertEqual(err.category, "RATE_LIMIT")
        self.assertTrue(err.retryable)

    # ------------------------------------------------------------------
    # 33. MAX_SAFE_MESSAGE_LEN Strictly <= 500 Contract
    # ------------------------------------------------------------------
    def test_33_max_safe_message_len_strictly_bounded_at_500(self) -> None:
        """Assert ModelStreamError post-init strictly bounds safe_message to <= 500 characters."""
        long_msg = "X" * 1500
        err = ModelStreamError(
            code="TEST_ERROR",
            category="TEST",
            safe_message=long_msg,
            retryable=False,
        )
        self.assertLessEqual(len(err.safe_message), 500)
        self.assertTrue(err.safe_message.endswith("..."))
        self.assertEqual(len(err.safe_message), 500)

    # ------------------------------------------------------------------
    # 34. Valid [DONE] with Zero Text is EMPTY_RESPONSE, NOT Truncation
    # ------------------------------------------------------------------
    def test_34_valid_done_with_zero_text_is_empty_response_not_truncation(self) -> None:
        """Assert legitimate [DONE] completion with 0 visible tokens yields EMPTY_RESPONSE (retryable=True)."""
        transport = MockTransport(events=[
            {"_done": True},
        ])
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "EMPTY_RESPONSE")
        self.assertEqual(err.category, "RESPONSE_ERROR")
        self.assertTrue(err.retryable)

    # ------------------------------------------------------------------
    # 35. Valid finish_reason='stop' with Zero Text is EMPTY_RESPONSE
    # ------------------------------------------------------------------
    def test_35_valid_finish_reason_stop_with_zero_text_is_empty_response(self) -> None:
        """Assert finish_reason='stop' with 0 visible tokens yields EMPTY_RESPONSE (retryable=True)."""
        transport = MockTransport(events=[
            {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]},
        ])
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "EMPTY_RESPONSE")
        self.assertEqual(err.category, "RESPONSE_ERROR")
        self.assertTrue(err.retryable)

    # ------------------------------------------------------------------
    # 36. Content + [DONE] Stays Success
    # ------------------------------------------------------------------
    def test_36_content_plus_done_stays_success(self) -> None:
        """Assert stream with content followed by [DONE] is completely successful with 0 errors."""
        transport = MockTransport(events=[
            {"choices": [{"delta": {"content": "Visible answer."}}]},
            {"_done": True},
        ])
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        content_deltas = [d for d in deltas if d.content]
        self.assertEqual(len(content_deltas), 1)
        self.assertEqual(content_deltas[0].content, "Visible answer.")
        self.assertEqual(deltas[-1].finish_reason, "stop")
        self.assertIsNone(deltas[-1].error)

    # ------------------------------------------------------------------
    # 37. EOF Before Completion Remains STREAM_TRUNCATED
    # ------------------------------------------------------------------
    def test_37_eof_before_completion_remains_stream_truncated(self) -> None:
        """Assert abrupt stream EOF before valid terminal signal is classified as STREAM_TRUNCATED."""
        transport = MockTransport(events=[])  # Abrupt EOF without [DONE]
        adapter = self._make_adapter(transport=transport)
        deltas = list(adapter.generate_stream(self._make_request()))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "STREAM_TRUNCATED")
        self.assertEqual(err.category, "STREAM_PROTOCOL")
        self.assertTrue(err.retryable)

    # ------------------------------------------------------------------
    # 38. EOF After Visible Content Remains STREAM_TRUNCATED and Blocks Fallback
    # ------------------------------------------------------------------
    def test_38_eof_after_visible_content_remains_stream_truncated_and_blocks_fallback(self) -> None:
        """Assert abrupt EOF after emitting visible content yields STREAM_TRUNCATED (retryable=False) and forbids fallback."""
        t_a = MockTransport(events=[
            {"choices": [{"delta": {"content": "First partial chunk."}}]},
            # Stream socket drops here
        ])
        t_b = MockTransport(events=[
            {"choices": [{"delta": {"content": "SHOULD NEVER RUN"}}]},
        ])

        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)
        adapter_b = self._make_adapter(provider_id="prov_b", transport=t_b)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg.register_provider(ProviderDefinition(provider_id="prov_b", display_name="Prov B"))
        reg._injected_adapters["prov_a"] = adapter_a
        reg._injected_adapters["prov_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="prov_a", model_id="m1"),
                ModelTarget(provider_id="prov_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(deltas[0].content, "First partial chunk.")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "STREAM_TRUNCATED")
        self.assertFalse(deltas[-1].error.retryable)
        self.assertIsNone(t_b.last_payload)

    # ------------------------------------------------------------------
    # 39. Final Buffered [DONE] Without Newline Handled Truthfully
    # ------------------------------------------------------------------
    def test_39_final_buffered_done_without_newline_handled_truthfully(self) -> None:
        """Assert [DONE] in final transport buffer without trailing newline is correctly parsed as completion."""
        raw_sse = b"data: {\"choices\": [{\"delta\": {\"content\": \"Full text.\"}}]}\n\ndata: [DONE]"
        mock_resp = io.BytesIO(raw_sse)

        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["choices"][0]["delta"]["content"], "Full text.")
        self.assertTrue(events[1].get("_done"))

    # ------------------------------------------------------------------
    # 40. Secret Sanitization Still Passes After All Changes
    # ------------------------------------------------------------------
    def test_40_secret_sanitization_still_passes_after_all_changes(self) -> None:
        """Assert secret tokens and API keys are completely stripped across all error paths."""
        raw_secret = "sk-LIVE-SECRET-KEY-12345-ABCDE"
        err = ModelStreamError(
            code="AUTH_ERROR",
            category="AUTHENTICATION",
            safe_message=sanitize_secrets(f"Unauthorized with Bearer {raw_secret}", raw_secret),
            retryable=False,
            http_status=401,
        )
        self.assertNotIn(raw_secret, err.safe_message)
        self.assertNotIn("Bearer sk-", err.safe_message)

    # ------------------------------------------------------------------
    # 41. GeneratorExit Not Converted to Provider Error
    # ------------------------------------------------------------------
    def test_41_generator_exit_not_converted_to_provider_error(self) -> None:
        """Assert GeneratorExit during generator.close() propagates naturally and is not caught as error."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"data: {\"choices\": [{\"delta\": {\"content\": \"hi\"}}]}\n\n"

        with patch("urllib.request.urlopen", return_value=mock_resp):
            gen = transport.post_json_stream("chat/completions", {"model": "m"})
            first = next(gen)
            self.assertEqual(first["choices"][0]["delta"]["content"], "hi")
            # Closing the generator must cleanly close without yielding an error event
            gen.close()

    # ------------------------------------------------------------------
    # 42. generator.close Closes HTTP Response Safely
    # ------------------------------------------------------------------
    def test_42_generator_close_closes_http_response_safely(self) -> None:
        """Assert generator.close() triggers finally block and calls resp.close()."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"data: {\"choices\": [{\"delta\": {\"content\": \"hello\"}}]}\n\n"

        with patch("urllib.request.urlopen", return_value=mock_resp):
            gen = transport.post_json_stream("chat/completions", {"model": "m"})
            next(gen)
            gen.close()

        mock_resp.close.assert_called()

    # ------------------------------------------------------------------
    # 43. KeyboardInterrupt Propagates Without Swallowing
    # ------------------------------------------------------------------
    def test_43_keyboard_interrupt_propagates_without_swallowing(self) -> None:
        """Assert KeyboardInterrupt is not caught and converted into ModelStreamError."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                list(transport.post_json_stream("chat/completions", {"model": "m"}))

    # ------------------------------------------------------------------
    # 44. SystemExit Propagates Without Swallowing
    # ------------------------------------------------------------------
    def test_44_system_exit_propagates_without_swallowing(self) -> None:
        """Assert SystemExit is not caught and converted into ModelStreamError."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                list(transport.post_json_stream("chat/completions", {"model": "m"}))

    # ------------------------------------------------------------------
    # 45. Synchronous post_json ValueError Not Synthesized as HTTP 500
    # ------------------------------------------------------------------
    def test_45_sync_post_json_valueerror_not_synthesized_as_http500(self) -> None:
        """Assert unexpected ValueError in post_json re-raises instead of synthesizing provider HTTP 500."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=ValueError("Unexpected internal bug")):
            with self.assertRaises(ValueError):
                transport.post_json("chat/completions", {"model": "m"})

    # ------------------------------------------------------------------
    # 46. Generic Adapter: Visible Content + Silent EOF -> Truncation
    # ------------------------------------------------------------------
    def test_46_generic_adapter_content_plus_silent_eof_yields_truncation_without_fallback(self) -> None:
        """Assert universal gateway enforces STREAM_TRUNCATED when generic custom adapter emits content then silently ends."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_a",
            deltas=[
                StreamDelta(content="Hello from custom adapter!", finish_reason=None, provider="generic_a", model_name="m1"),
                # Silent EOF without terminal finish_reason
            ],
        )
        adapter_b = GenericMockStreamingAdapter(
            provider_name_val="generic_b",
            deltas=[
                StreamDelta(content="B SHOULD NEVER BE CALLED", finish_reason="stop", provider="generic_b", model_name="m2"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_a", display_name="Gen A"))
        reg.register_provider(ProviderDefinition(provider_id="generic_b", display_name="Gen B"))
        reg._injected_adapters["generic_a"] = adapter_a
        reg._injected_adapters["generic_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="generic_a", model_id="m1"),
                ModelTarget(provider_id="generic_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(deltas[0].content, "Hello from custom adapter!")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "STREAM_TRUNCATED")
        self.assertEqual(deltas[-1].error.category, "STREAM_PROTOCOL")
        self.assertFalse(deltas[-1].error.retryable)
        self.assertEqual(deltas[-1].provider, "generic_a")

    # ------------------------------------------------------------------
    # 47. Generic Adapter: Silent EOF Before Content -> Fallback
    # ------------------------------------------------------------------
    def test_47_generic_adapter_silent_eof_before_content_allows_fallback(self) -> None:
        """Assert universal gateway falls back to candidate B when generic custom adapter silently ends before content."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_a",
            deltas=[],  # Silent EOF without deltas or terminal signal
        )
        adapter_b = GenericMockStreamingAdapter(
            provider_name_val="generic_b",
            deltas=[
                StreamDelta(content="Recovered by Generic B", finish_reason="stop", provider="generic_b", model_name="m2"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_a", display_name="Gen A"))
        reg.register_provider(ProviderDefinition(provider_id="generic_b", display_name="Gen B"))
        reg._injected_adapters["generic_a"] = adapter_a
        reg._injected_adapters["generic_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="generic_a", model_id="m1"),
                ModelTarget(provider_id="generic_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        content = "".join(d.content for d in deltas)
        self.assertEqual(content, "Recovered by Generic B")
        self.assertEqual(deltas[-1].finish_reason, "stop")

    # ------------------------------------------------------------------
    # 48. Generic Adapter: Empty Stop Yields EMPTY_RESPONSE and Allows Fallback
    # ------------------------------------------------------------------
    def test_48_generic_adapter_empty_stop_yields_empty_response_and_allows_fallback(self) -> None:
        """Assert universal gateway treats custom adapter finish_reason='stop' with 0 content as EMPTY_RESPONSE and falls back."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_a",
            deltas=[
                StreamDelta(content="", finish_reason="stop", provider="generic_a", model_name="m1"),
            ],
        )
        adapter_b = GenericMockStreamingAdapter(
            provider_name_val="generic_b",
            deltas=[
                StreamDelta(content="Fallback B success", finish_reason="stop", provider="generic_b", model_name="m2"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_a", display_name="Gen A"))
        reg.register_provider(ProviderDefinition(provider_id="generic_b", display_name="Gen B"))
        reg._injected_adapters["generic_a"] = adapter_a
        reg._injected_adapters["generic_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="generic_a", model_id="m1"),
                ModelTarget(provider_id="generic_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        content = "".join(d.content for d in deltas)
        self.assertEqual(content, "Fallback B success")

    # ------------------------------------------------------------------
    # 49. Generic Adapter: Content + Stop -> Success
    # ------------------------------------------------------------------
    def test_49_generic_adapter_content_plus_stop_yields_success(self) -> None:
        """Assert generic adapter yielding content followed by finish_reason='stop' succeeds with 0 errors."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_a",
            deltas=[
                StreamDelta(content="Hello world.", finish_reason=None, provider="generic_a", model_name="m1"),
                StreamDelta(content="", finish_reason="stop", provider="generic_a", model_name="m1"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_a", display_name="Gen A"))
        reg._injected_adapters["generic_a"] = adapter_a

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="generic_a", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "Hello world.")
        self.assertEqual(deltas[1].finish_reason, "stop")
        self.assertIsNone(deltas[1].error)

    # ------------------------------------------------------------------
    # 50. Generic Adapter: Content + Error -> Exact Error Preserved Without Fallback
    # ------------------------------------------------------------------
    def test_50_generic_adapter_content_plus_error_preserves_error_without_fallback(self) -> None:
        """Assert generic adapter emitting content then an explicit error delta preserves exact error without fallback."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_a",
            deltas=[
                StreamDelta(content="Partial text...", finish_reason=None, provider="generic_a", model_name="m1"),
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="generic_a",
                    model_name="m1",
                    error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="Quota exhausted mid-stream", retryable=False, http_status=429),
                ),
            ],
        )
        adapter_b = GenericMockStreamingAdapter(
            provider_name_val="generic_b",
            deltas=[StreamDelta(content="SHOULD NOT RUN", finish_reason="stop", provider="generic_b", model_name="m2")],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_a", display_name="Gen A"))
        reg.register_provider(ProviderDefinition(provider_id="generic_b", display_name="Gen B"))
        reg._injected_adapters["generic_a"] = adapter_a
        reg._injected_adapters["generic_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="generic_a", model_id="m1"),
                ModelTarget(provider_id="generic_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(deltas[0].content, "Partial text...")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")
        self.assertEqual(deltas[-1].provider, "generic_a")

    # ------------------------------------------------------------------
    # 51. Generic Adapter Arbitrary Exception Does Not Leak Secret
    # ------------------------------------------------------------------
    def test_51_generic_adapter_arbitrary_exception_does_not_leak_secret(self) -> None:
        """Assert universal gateway boundary never exposes arbitrary exception text or secrets in safe_message."""
        raw_secret_leak = "database connection failure; api_key=sk-SUPER-SECRET-XYZ; password=hunter2"
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="generic_secret",
            exception_to_raise=RuntimeError(raw_secret_leak),
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="generic_secret", display_name="Gen Secret"))
        reg._injected_adapters["generic_secret"] = adapter_a

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic_secret", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="generic_secret", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "STREAM_INTERNAL_ERROR")
        self.assertEqual(err.category, "INTERNAL")
        # Must NOT contain raw secret, password, or key text
        self.assertNotIn("sk-SUPER-SECRET-XYZ", err.safe_message)
        self.assertNotIn("hunter2", err.safe_message)
        self.assertNotIn("api_key=", err.safe_message)
        self.assertNotIn("database connection failure", err.safe_message)

    # ------------------------------------------------------------------
    # 52. Sync-Degradation Arbitrary Exception Does Not Leak Secret
    # ------------------------------------------------------------------
    def test_52_sync_degradation_arbitrary_exception_does_not_leak_secret(self) -> None:
        """Assert synchronous degradation adapter exception never exposes arbitrary text or secrets in safe_message."""
        raw_secret_leak = "internal auth crash: secret=sk-HIDDEN-123456"
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="sync_secret",
            exception_to_raise=RuntimeError(raw_secret_leak),
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_secret", display_name="Sync Secret"))
        reg._injected_adapters["sync_secret"] = sync_adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_secret", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_secret", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "STREAM_INTERNAL_ERROR")
        self.assertEqual(err.category, "INTERNAL")
        self.assertNotIn("sk-HIDDEN-123456", err.safe_message)
        self.assertNotIn("secret=", err.safe_message)
        self.assertNotIn("internal auth crash", err.safe_message)

    # ------------------------------------------------------------------
    # 53. OpenAI Adapter Truncation Not Double-Wrapped
    # ------------------------------------------------------------------
    def test_53_already_structured_openai_truncation_not_doubled(self) -> None:
        """Assert OpenAICompatibleProviderAdapter STREAM_TRUNCATED yields exactly 1 terminal delta."""
        t_a = MockTransport(events=[
            {"choices": [{"delta": {"content": "Visible start."}}]},
            # Stream socket drops here
        ])
        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg._injected_adapters["prov_a"] = adapter_a

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_a", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "Visible start.")
        self.assertEqual(deltas[1].finish_reason, "error")
        self.assertEqual(deltas[1].error.code, "STREAM_TRUNCATED")

    # ------------------------------------------------------------------
    # 54. OpenAI Adapter EMPTY_RESPONSE Not Double-Wrapped
    # ------------------------------------------------------------------
    def test_54_already_structured_openai_empty_response_not_doubled(self) -> None:
        """Assert OpenAICompatibleProviderAdapter EMPTY_RESPONSE yields exactly 1 terminal delta."""
        t_a = MockTransport(events=[{"_done": True}])
        adapter_a = self._make_adapter(provider_id="prov_a", transport=t_a)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", display_name="Prov A"))
        reg._injected_adapters["prov_a"] = adapter_a

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_a", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertEqual(deltas[0].error.code, "EMPTY_RESPONSE")


    # ------------------------------------------------------------------
    # 55. PermissionError with "timed out" in message is INTERNAL, NOT TIMEOUT
    # ------------------------------------------------------------------
    def test_55_permission_error_with_timeout_prose_is_internal(self) -> None:
        """Assert PermissionError containing 'timed out' text is classified as INTERNAL, NOT TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.read.side_effect = PermissionError("Local disk operation timed out")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 56. FileNotFoundError with "network timed out" in message is INTERNAL
    # ------------------------------------------------------------------
    def test_56_filenotfound_error_with_timeout_prose_is_internal(self) -> None:
        """Assert FileNotFoundError containing 'network connection timed out' text is classified as INTERNAL."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=FileNotFoundError("Local socket file network connection timed out")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 57. ETIMEDOUT OSError is TIMEOUT
    # ------------------------------------------------------------------
    def test_57_etimedout_oserror_is_timeout(self) -> None:
        """Assert raw OSError with errno=ETIMEDOUT is classified as TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=OSError(errno.ETIMEDOUT, "Connection timed out")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))
        self.assertEqual(err_evt.get("status_code"), 408)

    # ------------------------------------------------------------------
    # 58. EACCES OSError with Network Prose is INTERNAL
    # ------------------------------------------------------------------
    def test_58_eacces_oserror_with_network_prose_is_internal(self) -> None:
        """Assert raw OSError with errno=EACCES and network-like prose is classified as INTERNAL, NOT NETWORK."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=OSError(errno.EACCES, "connection reset by peer")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 59. Structured Adapter Error Secret Normalization
    # ------------------------------------------------------------------
    def test_59_adapter_structured_error_secret_normalization(self) -> None:
        """Assert custom adapter error containing raw credentials is sanitized at public gateway boundary."""
        adapter_a = GenericMockStreamingAdapter(
            provider_name_val="fake",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="fake",
                    model_name="fake",
                    error=ModelStreamError(
                        code="AUTH_ERROR",
                        category="AUTHENTICATION",
                        safe_message="Authorization: Bearer abcdefghijklmnop api_key=sk-SUPER-SECRET password=hunter2",
                        retryable=False,
                        http_status=401,
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="fake", display_name="Fake Prov"))
        reg._injected_adapters["fake"] = adapter_a

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="fake", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="fake", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "AUTH_ERROR")
        self.assertEqual(err.category, "AUTHENTICATION")
        self.assertEqual(err.http_status, 401)

        serialized = str(deltas)
        self.assertNotIn("abcdefghijklmnop", serialized)
        self.assertNotIn("sk-SUPER-SECRET", serialized)
        self.assertNotIn("hunter2", serialized)

    # ------------------------------------------------------------------
    # 60. Sync Metadata safe_message Secret Normalization
    # ------------------------------------------------------------------
    def test_60_sync_metadata_safe_message_secret_normalization(self) -> None:
        """Assert sync adapter metadata safe_message containing credentials is sanitized at public gateway boundary."""
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="sync_leak",
            status=ModelResponseStatus.ERROR,
            error_msg="Generic failure",
            metadata={
                "error_code": "RATE_LIMITED",
                "error_category": "RATE_LIMIT",
                "retryable": True,
                "http_status": 429,
                "safe_message": "password=hunter2 api_key=sk-ABC123456",
            },
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_leak", display_name="Sync Leak"))
        reg._injected_adapters["sync_leak"] = sync_adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_leak", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_leak", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        err = deltas[0].error
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "RATE_LIMITED")
        self.assertEqual(err.category, "RATE_LIMIT")
        self.assertEqual(err.http_status, 429)

        serialized = str(deltas)
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("sk-ABC123456", serialized)

    # ------------------------------------------------------------------
    # 61. Sync SUCCESS Empty Content Becomes EMPTY_RESPONSE
    # ------------------------------------------------------------------
    def test_61_sync_success_empty_content_becomes_empty_response(self) -> None:
        """Assert sync degradation returning status=SUCCESS with empty content becomes EMPTY_RESPONSE and falls back."""
        adapter_a = MockSyncOnlyAdapter(provider_name_val="sync_a", content="", status=ModelResponseStatus.SUCCESS)
        adapter_b = MockSyncOnlyAdapter(provider_name_val="sync_b", content="Recovered by B", status=ModelResponseStatus.SUCCESS)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_a", display_name="Sync A"))
        reg.register_provider(ProviderDefinition(provider_id="sync_b", display_name="Sync B"))
        reg._injected_adapters["sync_a"] = adapter_a
        reg._injected_adapters["sync_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="sync_a", model_id="m1"),
                ModelTarget(provider_id="sync_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "Recovered by B")
        self.assertEqual(deltas[0].finish_reason, "stop")
        self.assertEqual(deltas[0].provider, "sync_b")

    # ------------------------------------------------------------------
    # 62. Sync SUCCESS Non-Empty Content Stays Success
    # ------------------------------------------------------------------
    def test_62_sync_success_non_empty_content_stays_success(self) -> None:
        """Assert sync degradation returning status=SUCCESS with valid content succeeds cleanly."""
        adapter = MockSyncOnlyAdapter(provider_name_val="sync_ok", content="Hello sync success", status=ModelResponseStatus.SUCCESS)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="sync_ok", display_name="Sync OK"))
        reg._injected_adapters["sync_ok"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="sync_ok", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="sync_ok", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "Hello sync success")
        self.assertEqual(deltas[0].finish_reason, "stop")
        self.assertIsNone(deltas[0].error)

    # ------------------------------------------------------------------
    # 63. Sync SUCCESS with finish_reason='error' Becomes Structured Error
    # ------------------------------------------------------------------
    def test_63_sync_success_with_error_finish_reason_becomes_structured_error(self) -> None:
        """Assert sync response with status=SUCCESS but finish_reason='error' emits structured PROVIDER_RESPONSE_ERROR."""
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="sync_err",
            content="Partial content before abort",
            status=ModelResponseStatus.SUCCESS,
        )
        # Force finish_reason to error
        with patch.object(sync_adapter, "generate", return_value=ModelResponse(
            request_id="req-1",
            provider="sync_err",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content="Partial content before abort",
            finish_reason="error",
        )):
            reg = ProviderRegistry()
            reg.register_provider(ProviderDefinition(provider_id="sync_err", display_name="Sync Err"))
            reg._injected_adapters["sync_err"] = sync_adapter

            policy = ModelPolicy(
                global_target=ModelTarget(provider_id="sync_err", model_id="m1"),
                fallback_chain=[ModelTarget(provider_id="sync_err", model_id="m1")],
                free_only_mode=False,
            )

            gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
            deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

            self.assertEqual(len(deltas), 1)
            self.assertEqual(deltas[0].finish_reason, "error")
            self.assertIsNotNone(deltas[0].error)
            self.assertEqual(deltas[0].error.code, "PROVIDER_RESPONSE_ERROR")

    # ------------------------------------------------------------------
    # 64. First Delta Content + Error None Synthesizes Structured Error
    # ------------------------------------------------------------------
    def test_64_first_delta_content_plus_error_none_synthesizes_structured_error(self) -> None:
        """Assert first delta having content + finish_reason='error' and error=None synthesizes structured error."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="gen_prov",
            deltas=[
                StreamDelta(content="Partial content...", finish_reason="error", provider="gen_prov", model_name="m1", error=None),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="gen_prov", display_name="Gen Prov"))
        reg._injected_adapters["gen_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gen_prov", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="gen_prov", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "Partial content...")
        self.assertIsNone(deltas[0].finish_reason)

        self.assertEqual(deltas[1].finish_reason, "error")
        self.assertIsNotNone(deltas[1].error)
        self.assertEqual(deltas[1].error.code, "PROVIDER_RESPONSE_ERROR")
        self.assertFalse(deltas[1].error.retryable)

    # ------------------------------------------------------------------
    # 65. First Delta Content + Structured Error Preserves Machine Fields
    # ------------------------------------------------------------------
    def test_65_first_delta_content_plus_structured_error_preserves_machine_fields(self) -> None:
        """Assert first delta with content + structured error preserves machine fields and sanitizes safe_message."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="gen_prov",
            deltas=[
                StreamDelta(
                    content="Partial content...",
                    finish_reason="error",
                    provider="gen_prov",
                    model_name="m1",
                    error=ModelStreamError(
                        code="RATE_LIMITED",
                        category="RATE_LIMIT",
                        safe_message="Quota hit; password=secret123",
                        retryable=False,
                        http_status=429,
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="gen_prov", display_name="Gen Prov"))
        reg._injected_adapters["gen_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gen_prov", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="gen_prov", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "Partial content...")
        self.assertEqual(deltas[1].finish_reason, "error")
        self.assertEqual(deltas[1].error.code, "RATE_LIMITED")
        self.assertEqual(deltas[1].error.category, "RATE_LIMIT")
        self.assertEqual(deltas[1].error.http_status, 429)
        self.assertNotIn("secret123", str(deltas))

    # ------------------------------------------------------------------
    # 66. Candidate Provider Spoof Cannot Cross Gateway
    # ------------------------------------------------------------------
    def test_66_candidate_provider_spoof_cannot_cross_gateway(self) -> None:
        """Assert adapter cannot spoof candidate provider name across public StreamDeltas."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="spoofed_prov",
            deltas=[
                StreamDelta(content="Hello", finish_reason=None, provider="spoofed_prov", model_name="spoofed_model"),
                StreamDelta(content="", finish_reason="stop", provider="spoofed_prov", model_name="spoofed_model"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_real", display_name="Real Prov"))
        reg._injected_adapters["prov_real"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_real", model_id="model_real"),
            fallback_chain=[ModelTarget(provider_id="prov_real", model_id="model_real")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        for delta in deltas:
            self.assertEqual(delta.provider, "prov_real")
            self.assertEqual(delta.model_name, "model_real")

    # ------------------------------------------------------------------
    # 67. Candidate Model Spoof on Error Terminal Cannot Cross Gateway
    # ------------------------------------------------------------------
    def test_67_candidate_model_spoof_on_error_terminal_cannot_cross_gateway(self) -> None:
        """Assert adapter cannot spoof model_name on error terminal delta."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="spoofed_prov",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="spoofed_prov",
                    model_name="spoofed_model",
                    error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="bad key", retryable=False),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_real", display_name="Real Prov"))
        reg._injected_adapters["prov_real"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_real", model_id="model_real"),
            fallback_chain=[ModelTarget(provider_id="prov_real", model_id="model_real")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].provider, "prov_real")
        self.assertEqual(deltas[0].model_name, "model_real")
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertEqual(deltas[0].error.code, "AUTH_ERROR")

    # ------------------------------------------------------------------
    # 68. Error Terminal Totality Invariant
    # ------------------------------------------------------------------
    def test_68_error_terminal_totality_invariant(self) -> None:
        """Assert finish_reason='error' ALWAYS implies delta.error is not None across representative stream tests."""
        test_deltas: List[StreamDelta] = [
            StreamDelta(content="", finish_reason="error", error=None),
            StreamDelta(content="text", finish_reason="error", error=None),
        ]
        for raw_delta in test_deltas:
            norm_delta = normalize_public_stream_delta(raw_delta, "cand_prov", "cand_model")
            self.assertEqual(norm_delta.finish_reason, "error")
            self.assertIsNotNone(norm_delta.error)
            self.assertIsInstance(norm_delta.error, ModelStreamError)
            self.assertEqual(norm_delta.provider, "cand_prov")
            self.assertEqual(norm_delta.model_name, "cand_model")


    # ------------------------------------------------------------------
    # 69. Zero-Delta Generic Generator -> STREAM_TRUNCATED (Single Candidate)
    # ------------------------------------------------------------------
    def test_69_zero_delta_generic_generator_is_stream_truncated_single_candidate(self) -> None:
        """Assert single candidate generic adapter ending with 0 deltas yields STREAM_TRUNCATED."""
        adapter = GenericMockStreamingAdapter(provider_name_val="gen_empty", deltas=[])

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="gen_empty", display_name="Gen Empty"))
        reg._injected_adapters["gen_empty"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gen_empty", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="gen_empty", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "STREAM_TRUNCATED")
        self.assertEqual(deltas[0].error.category, "STREAM_PROTOCOL")
        self.assertTrue(deltas[0].error.retryable)

    # ------------------------------------------------------------------
    # 70. Zero-Delta Generic Generator -> Fallback Succeeds with B
    # ------------------------------------------------------------------
    def test_70_zero_delta_generic_generator_fallback_succeeds(self) -> None:
        """Assert generic adapter ending with 0 deltas triggers fallback to candidate B, preserving internal error."""
        adapter_a = GenericMockStreamingAdapter(provider_name_val="gen_a", deltas=[])
        adapter_b = GenericMockStreamingAdapter(
            provider_name_val="gen_b",
            deltas=[StreamDelta(content="Candidate B output", finish_reason="stop", provider="gen_b", model_name="m2")],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="gen_a", display_name="Gen A"))
        reg.register_provider(ProviderDefinition(provider_id="gen_b", display_name="Gen B"))
        reg._injected_adapters["gen_a"] = adapter_a
        reg._injected_adapters["gen_b"] = adapter_b

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gen_a", model_id="m1"),
            fallback_chain=[
                ModelTarget(provider_id="gen_a", model_id="m1"),
                ModelTarget(provider_id="gen_b", model_id="m2"),
            ],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "Candidate B output")
        self.assertEqual(deltas[0].finish_reason, "stop")
        self.assertIsNone(deltas[0].error)
        self.assertEqual(deltas[0].provider, "gen_b")

    # ------------------------------------------------------------------
    # 71. Explicit Empty Stop Remains EMPTY_RESPONSE
    # ------------------------------------------------------------------
    def test_71_explicit_empty_stop_remains_empty_response(self) -> None:
        """Assert valid terminal stop with 0 content is classified as EMPTY_RESPONSE."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="gen_stop",
            deltas=[StreamDelta(content="", finish_reason="stop", provider="gen_stop", model_name="m1")],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="gen_stop", display_name="Gen Stop"))
        reg._injected_adapters["gen_stop"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gen_stop", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="gen_stop", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "EMPTY_RESPONSE")
        self.assertEqual(deltas[0].error.category, "RESPONSE_ERROR")
        self.assertTrue(deltas[0].error.retryable)

    # ------------------------------------------------------------------
    # 72. Quoted JSON api_key Redacted
    # ------------------------------------------------------------------
    def test_72_quoted_json_api_key_redacted(self) -> None:
        """Assert JSON quoted api_key is cleanly redacted without leaking secret."""
        raw = '{"api_key": "sk-JSON-SECRET-123456"}'
        sanitized = sanitize_secrets(raw)
        self.assertNotIn("sk-JSON-SECRET-123456", sanitized)
        self.assertIn('"api_key":', sanitized)

    # ------------------------------------------------------------------
    # 73. Quoted Password Redacted
    # ------------------------------------------------------------------
    def test_73_quoted_password_redacted(self) -> None:
        """Assert single-quoted password is cleanly redacted without leaking secret."""
        raw = "{'password': 'hunter2'}"
        sanitized = sanitize_secrets(raw)
        self.assertNotIn("hunter2", sanitized)
        self.assertIn("'password':", sanitized)

    # ------------------------------------------------------------------
    # 74. Authorization Basic Credential Redacted
    # ------------------------------------------------------------------
    def test_74_authorization_basic_credential_redacted(self) -> None:
        """Assert Authorization: Basic base64 credentials are fully redacted."""
        raw = "Authorization: Basic dXNlcjpwYXNzd29yZA=="
        sanitized = sanitize_secrets(raw)
        self.assertNotIn("dXNlcjpwYXNzd29yZA==", sanitized)
        self.assertIn("Authorization: Basic", sanitized)

    # ------------------------------------------------------------------
    # 75. Query-String Access Token Redacted
    # ------------------------------------------------------------------
    def test_75_query_string_access_token_redacted(self) -> None:
        """Assert query-string access_token parameter is redacted while preserving remaining parameters."""
        raw = "https://example.test/?access_token=mytoken123456&x=1"
        sanitized = sanitize_secrets(raw)
        self.assertNotIn("mytoken123456", sanitized)
        self.assertIn("x=1", sanitized)

    # ------------------------------------------------------------------
    # 76. Non-Error Content Delta Cannot Carry Error Object Publicly
    # ------------------------------------------------------------------
    def test_76_non_error_content_delta_cannot_carry_error_object_publicly(self) -> None:
        """Assert content delta with finish_reason=None has delta.error stripped to None."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="leak_prov",
            deltas=[
                StreamDelta(
                    content="hello",
                    finish_reason=None,
                    provider="leak_prov",
                    model_name="m1",
                    error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="api_key=sk-MUST-NOT-CROSS"),
                ),
                StreamDelta(content="", finish_reason="stop", provider="leak_prov", model_name="m1"),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="leak_prov", display_name="Leak Prov"))
        reg._injected_adapters["leak_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="leak_prov", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="leak_prov", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "hello")
        self.assertIsNone(deltas[0].finish_reason)
        self.assertIsNone(deltas[0].error)

        serialized = str(deltas)
        self.assertNotIn("sk-MUST-NOT-CROSS", serialized)

    # ------------------------------------------------------------------
    # 77. Normal Terminal Cannot Carry Stray Error Object Publicly
    # ------------------------------------------------------------------
    def test_77_normal_terminal_cannot_carry_stray_error_object_publicly(self) -> None:
        """Assert normal stop terminal has delta.error stripped to None."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="leak_prov",
            deltas=[
                StreamDelta(
                    content="hello",
                    finish_reason="stop",
                    provider="leak_prov",
                    model_name="m1",
                    error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="secret=xyz"),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="leak_prov", display_name="Leak Prov"))
        reg._injected_adapters["leak_prov"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="leak_prov", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="leak_prov", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "hello")
        self.assertEqual(deltas[0].finish_reason, "stop")
        self.assertIsNone(deltas[0].error)
        self.assertNotIn("secret=xyz", str(deltas))

    # ------------------------------------------------------------------
    # 78. Malicious error.code Secret Fails Closed
    # ------------------------------------------------------------------
    def test_78_malicious_error_code_secret_fails_closed(self) -> None:
        """Assert untrusted adapter error.code containing secret fails closed to PROVIDER_RESPONSE_ERROR."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="fake",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="fake",
                    model_name="m1",
                    error=ModelStreamError(
                        code="api_key=sk-CODE-SECRET",
                        category="RESPONSE_ERROR",
                        safe_message="clean message",
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="fake", display_name="Fake Prov"))
        reg._injected_adapters["fake"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="fake", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="fake", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].error.code, "PROVIDER_RESPONSE_ERROR")
        self.assertNotIn("sk-CODE-SECRET", str(deltas))

    # ------------------------------------------------------------------
    # 79. Malicious error.category Secret Fails Closed
    # ------------------------------------------------------------------
    def test_79_malicious_error_category_secret_fails_closed(self) -> None:
        """Assert untrusted adapter error.category containing secret fails closed to RESPONSE_ERROR."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="fake",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="fake",
                    model_name="m1",
                    error=ModelStreamError(
                        code="RATE_LIMITED",
                        category="password=hunter2",
                        safe_message="clean message",
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="fake", display_name="Fake Prov"))
        reg._injected_adapters["fake"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="fake", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="fake", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].error.category, "RESPONSE_ERROR")
        self.assertNotIn("hunter2", str(deltas))

    # ------------------------------------------------------------------
    # 80. Malformed http_status Secret Fails Closed
    # ------------------------------------------------------------------
    def test_80_malformed_http_status_secret_fails_closed(self) -> None:
        """Assert non-integer / string secret in http_status fails closed to None."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="fake",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="fake",
                    model_name="m1",
                    error=ModelStreamError(
                        code="RATE_LIMITED",
                        category="RATE_LIMIT",
                        safe_message="clean message",
                        http_status="token=abcdef123456",  # Malformed string value
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="fake", display_name="Fake Prov"))
        reg._injected_adapters["fake"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="fake", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="fake", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertIsNone(deltas[0].error.http_status)
        self.assertNotIn("abcdef123456", str(deltas))

    # ------------------------------------------------------------------
    # 81. Legitimate AUTH_ERROR Fields Preserved
    # ------------------------------------------------------------------
    def test_81_legitimate_auth_error_fields_preserved(self) -> None:
        """Assert canonical AUTH_ERROR preserves machine fields (code, category, retryable, http_status)."""
        adapter = GenericMockStreamingAdapter(
            provider_name_val="fake",
            deltas=[
                StreamDelta(
                    content="",
                    finish_reason="error",
                    provider="fake",
                    model_name="m1",
                    error=ModelStreamError(
                        code="AUTH_ERROR",
                        category="AUTHENTICATION",
                        safe_message="Invalid authentication key.",
                        retryable=False,
                        http_status=401,
                    ),
                ),
            ],
        )

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="fake", display_name="Fake Prov"))
        reg._injected_adapters["fake"] = adapter

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="fake", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="fake", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
        deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].error.code, "AUTH_ERROR")
        self.assertEqual(deltas[0].error.category, "AUTHENTICATION")
        self.assertFalse(deltas[0].error.retryable)
        self.assertEqual(deltas[0].error.http_status, 401)

    # ------------------------------------------------------------------
    # 82. URLError Plain Text Does NOT Become TIMEOUT
    # ------------------------------------------------------------------
    def test_82_urlerror_plain_text_does_not_become_timeout(self) -> None:
        """Assert URLError with plain string 'timed out' does NOT become TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertFalse(err_evt.get("is_timeout"))
        self.assertTrue(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))

    # ------------------------------------------------------------------
    # 83. URLError(socket.timeout) Becomes TIMEOUT
    # ------------------------------------------------------------------
    def test_83_urlerror_socket_timeout_becomes_timeout(self) -> None:
        """Assert URLError wrapping socket.timeout becomes TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(socket.timeout("The read operation timed out"))):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))
        self.assertEqual(err_evt.get("status_code"), 408)

    # ------------------------------------------------------------------
    # 84. URLError(ETIMEDOUT) Becomes TIMEOUT
    # ------------------------------------------------------------------
    def test_84_urlerror_etimedout_becomes_timeout(self) -> None:
        """Assert URLError wrapping OSError(ETIMEDOUT) becomes TIMEOUT."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(OSError(errno.ETIMEDOUT, "Connection timed out"))):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))
        self.assertFalse(err_evt.get("is_internal"))
        self.assertEqual(err_evt.get("status_code"), 408)

    # ------------------------------------------------------------------
    # 85. URLError(PermissionError) is INTERNAL (Not Network, Not Timeout)
    # ------------------------------------------------------------------
    def test_85_urlerror_permission_error_is_internal(self) -> None:
        """Assert URLError wrapping PermissionError is INTERNAL, not network, not timeout."""
        transport = OpenAICompatibleTransport(base_url="https://api.test.com/v1", api_key="sk-test")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(PermissionError("timed out"))):
            events = list(transport.post_json_stream("chat/completions", {"model": "m"}))

        self.assertEqual(len(events), 1)
        err_evt = events[0]
        self.assertTrue(err_evt.get("_error"))
        self.assertTrue(err_evt.get("is_internal"))
        self.assertFalse(err_evt.get("is_timeout"))
        self.assertFalse(err_evt.get("is_network"))

    # ------------------------------------------------------------------
    # 86. Every Public Non-Error Delta Has error is None
    # ------------------------------------------------------------------
    def test_86_every_public_non_error_delta_has_error_none(self) -> None:
        """Assert normalize_public_stream_delta guarantees delta.error is None for all non-error finish_reasons."""
        non_error_deltas = [
            StreamDelta(content="text", finish_reason=None, error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="secret")),
            StreamDelta(content="", finish_reason="stop", error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="secret")),
            StreamDelta(content="", finish_reason="length", error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="secret")),
        ]
        for raw_d in non_error_deltas:
            norm_d = normalize_public_stream_delta(raw_d, "prov", "m1")
            self.assertIsNone(norm_d.error)
            self.assertEqual(norm_d.provider, "prov")
            self.assertEqual(norm_d.model_name, "m1")

    # ------------------------------------------------------------------
    # 87. Every Public Error Terminal Has error is ModelStreamError
    # ------------------------------------------------------------------
    def test_87_every_public_error_terminal_has_error_is_modelstreamerror(self) -> None:
        """Assert normalize_public_stream_delta guarantees delta.error is ModelStreamError when finish_reason='error'."""
        error_deltas = [
            StreamDelta(content="", finish_reason="error", error=None),
            StreamDelta(content="text", finish_reason="error", error=None),
            StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="msg")),
        ]
        for raw_d in error_deltas:
            norm_d = normalize_public_stream_delta(raw_d, "prov", "m1")
            self.assertEqual(norm_d.finish_reason, "error")
            self.assertIsNotNone(norm_d.error)
            self.assertIsInstance(norm_d.error, ModelStreamError)
            self.assertEqual(norm_d.provider, "prov")
            self.assertEqual(norm_d.model_name, "m1")


    # ------------------------------------------------------------------
    # CONTRACT ASSERTION HELPERS
    # ------------------------------------------------------------------
    def assert_public_delta_contract(
        self,
        delta: StreamDelta,
        expected_provider: str,
        expected_model: str,
    ) -> None:
        """Assert single public StreamDelta satisfies all public contract invariants."""
        self.assertEqual(delta.provider, expected_provider)
        self.assertEqual(delta.model_name, expected_model)

        if delta.finish_reason == "error":
            self.assertIsNotNone(delta.error)
            self.assertIsInstance(delta.error, ModelStreamError)
            self.assertIn(delta.error.code, CANONICAL_STREAM_ERROR_CODES)
            self.assertIn(delta.error.category, CANONICAL_STREAM_ERROR_CATEGORIES)
            self.assertIsInstance(delta.error.retryable, bool)
            self.assertIs(type(delta.error.retryable), bool)
            if delta.error.http_status is not None:
                self.assertIsInstance(delta.error.http_status, int)
                self.assertGreaterEqual(delta.error.http_status, 100)
                self.assertLessEqual(delta.error.http_status, 599)
            self.assertLessEqual(len(delta.error.safe_message), MAX_SAFE_MESSAGE_LEN)
        else:
            self.assertIsNone(delta.error)

    def assert_public_stream_contract(
        self,
        deltas: List[StreamDelta],
        expected_provider: str,
        expected_model: str,
    ) -> None:
        """Assert full sequence of public StreamDeltas adheres strictly to public contract."""
        self.assertGreater(len(deltas), 0)
        terminal_indices = [i for i, d in enumerate(deltas) if d.finish_reason is not None]
        self.assertLessEqual(len(terminal_indices), 1)

        for i, d in enumerate(deltas):
            self.assert_public_delta_contract(d, expected_provider, expected_model)
            if d.finish_reason is not None:
                self.assertEqual(i, len(deltas) - 1, "Terminal finish_reason must only appear on last delta")

    # ------------------------------------------------------------------
    # 88. HTTP 400 Native and Sync Canonical BAD_REQUEST Equivalence
    # ------------------------------------------------------------------
    def test_88_http400_native_and_sync_canonical_bad_request(self) -> None:
        """Assert HTTP 400 in both native streaming and sync degradation paths produces INVALID_REQUEST / BAD_REQUEST / 400."""
        # 1. Native streaming path
        t_native = MockTransport(events=[{"_error": True, "status_code": 400, "body": "Invalid model parameter"}])
        adapter_native = self._make_adapter(provider_id="prov_400_native", transport=t_native)

        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_400_native", display_name="Prov 400 Native"))
        reg._injected_adapters["prov_400_native"] = adapter_native

        policy_native = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_400_native", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_400_native", model_id="m1")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy_native, free_only_mode=False)
        deltas_native = list(gw.generate_stream(self._make_request(), model_policy=policy_native))

        self.assertEqual(len(deltas_native), 1)
        self.assertEqual(deltas_native[0].finish_reason, "error")
        err_native = deltas_native[0].error
        self.assertIsNotNone(err_native)
        self.assertEqual(err_native.code, "INVALID_REQUEST")
        self.assertEqual(err_native.category, "BAD_REQUEST")
        self.assertFalse(err_native.retryable)
        self.assertEqual(err_native.http_status, 400)

        # 2. Sync degradation path
        sync_adapter = MockSyncOnlyAdapter(
            provider_name_val="prov_400_sync",
            status=ModelResponseStatus.ERROR,
            error_msg="Invalid prompt schema",
            metadata={"error_code": "INVALID_REQUEST", "error_category": "BAD_REQUEST", "retryable": False, "http_status": 400},
        )
        reg.register_provider(ProviderDefinition(provider_id="prov_400_sync", display_name="Prov 400 Sync"))
        reg._injected_adapters["prov_400_sync"] = sync_adapter

        policy_sync = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_400_sync", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_400_sync", model_id="m1")],
            free_only_mode=False,
        )

        deltas_sync = list(gw.generate_stream(self._make_request(), model_policy=policy_sync))
        self.assertEqual(len(deltas_sync), 1)
        self.assertEqual(deltas_sync[0].finish_reason, "error")
        err_sync = deltas_sync[0].error
        self.assertIsNotNone(err_sync)
        self.assertEqual(err_sync.code, "INVALID_REQUEST")
        self.assertEqual(err_sync.category, "BAD_REQUEST")
        self.assertFalse(err_sync.retryable)
        self.assertEqual(err_sync.http_status, 400)

    # ------------------------------------------------------------------
    # 89. Strict retryable Type Validation Matrix
    # ------------------------------------------------------------------
    def test_89_strict_retryable_type_validation_matrix(self) -> None:
        """Assert normalize_public_stream_error accepts ONLY actual bool and fails closed to False for everything else."""
        valid_cases = [
            (True, True),
            (False, False),
        ]
        for input_val, expected_val in valid_cases:
            err = ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="msg", retryable=input_val)
            norm = normalize_public_stream_error(err)
            self.assertIs(norm.retryable, expected_val)
            self.assertIsInstance(norm.retryable, bool)

        malformed_cases = [
            "true", "false", "TRUE", "FALSE", 1, 0, None, {}, [], [True], {"retryable": True}
        ]
        for bad_val in malformed_cases:
            err = ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="msg", retryable=bad_val)  # type: ignore
            norm = normalize_public_stream_error(err)
            self.assertIs(norm.retryable, False)
            self.assertIsInstance(norm.retryable, bool)

    # ------------------------------------------------------------------
    # 90. Short Bearer and Basic Credential Fuzz Matrix
    # ------------------------------------------------------------------
    def test_90_short_bearer_and_basic_credential_fuzz_matrix(self) -> None:
        """Assert Bearer and Basic credentials of ANY length are cleanly redacted."""
        test_inputs = [
            ("Bearer x", "[REDACTED_TOKEN]", "x"),
            ("Bearer abc", "[REDACTED_TOKEN]", "abc"),
            ("Bearer abc123", "[REDACTED_TOKEN]", "abc123"),
            ("Authorization: Bearer abc123", "[REDACTED_TOKEN]", "abc123"),
            ("authorization: bearer shortkey", "[REDACTED_TOKEN]", "shortkey"),
            ("Authorization: Basic x", "[REDACTED_BASIC_AUTH]", "x"),
            ("Authorization: Basic abc", "[REDACTED_BASIC_AUTH]", "abc"),
            ("Authorization: Basic dXNlcjpwYXNz", "[REDACTED_BASIC_AUTH]", "dXNlcjpwYXNz"),
            ("Basic dXNlcjpwYXNz", "[REDACTED_BASIC_AUTH]", "dXNlcjpwYXNz"),
            ("Bearer secret-token-long-123456789", "[REDACTED_TOKEN]", "secret-token-long-123456789"),
        ]
        for raw_text, expected_tag, secret_val in test_inputs:
            sanitized = sanitize_secrets(raw_text)
            self.assertNotIn(secret_val, sanitized)
            self.assertIn(expected_tag, sanitized)

    # ------------------------------------------------------------------
    # 91. Malformed http_status Matrix
    # ------------------------------------------------------------------
    def test_91_malformed_http_status_matrix(self) -> None:
        """Assert http_status is strictly bounded to integer [100, 599] or None."""
        valid_statuses = [100, 200, 400, 401, 403, 404, 429, 500, 503, 599]
        for st in valid_statuses:
            err = ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="msg", http_status=st)
            norm = normalize_public_stream_error(err)
            self.assertEqual(norm.http_status, st)

        invalid_statuses = [0, 99, 600, 1000, -1, "401", "token=SECRET", [401], {"status": 401}]
        for bad_st in invalid_statuses:
            err = ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="msg", http_status=bad_st)  # type: ignore
            norm = normalize_public_stream_error(err)
            self.assertIsNone(norm.http_status)

    # ------------------------------------------------------------------
    # 92. Machine Field Secret Matrix
    # ------------------------------------------------------------------
    def test_92_machine_field_secret_matrix(self) -> None:
        """Assert arbitrary secrets placed inside machine fields fail closed and are not exposed."""
        err = ModelStreamError(
            code="api_key=sk-INJECTED-CODE-SECRET",
            category="password=INJECTED-CATEGORY-SECRET",
            safe_message="clean safe message",
            http_status="token=INJECTED-STATUS-SECRET",  # type: ignore
            retryable="true",  # type: ignore
        )
        norm = normalize_public_stream_error(err)

        self.assertEqual(norm.code, "PROVIDER_RESPONSE_ERROR")
        self.assertEqual(norm.category, "RESPONSE_ERROR")
        self.assertIsNone(norm.http_status)
        self.assertIs(norm.retryable, False)

        serialized = str(norm)
        self.assertNotIn("INJECTED-CODE-SECRET", serialized)
        self.assertNotIn("INJECTED-CATEGORY-SECRET", serialized)
        self.assertNotIn("INJECTED-STATUS-SECRET", serialized)

    # ------------------------------------------------------------------
    # 93. Canonical Vocabulary Consistency Audit
    # ------------------------------------------------------------------
    def test_93_canonical_vocabulary_consistency_audit(self) -> None:
        """Assert every production error code and category produced across A1 belongs to canonical sets."""
        for err_code in ProviderErrorCode:
            mapped_stream_err = classify_transport_to_stream_error(
                status_code=400 if err_code == ProviderErrorCode.CONFIG_ERROR else None,
                headers={},
                body_str="error",
                provider_name="test",
                is_timeout=(err_code == ProviderErrorCode.TIMEOUT),
                is_network_err=(err_code == ProviderErrorCode.NETWORK_ERROR),
                is_internal_err=(err_code == ProviderErrorCode.OTHER),
            )
            self.assertIn(mapped_stream_err.code, CANONICAL_STREAM_ERROR_CODES)
            self.assertIn(mapped_stream_err.category, CANONICAL_STREAM_ERROR_CATEGORIES)

        # Check BAD_REQUEST explicitly in canonical categories
        self.assertIn("BAD_REQUEST", CANONICAL_STREAM_ERROR_CATEGORIES)
        self.assertIn("INVALID_REQUEST", CANONICAL_STREAM_ERROR_CODES)

    # ------------------------------------------------------------------
    # 94. Adversarial Adapter Matrix (18 Deterministic Behaviors)
    # ------------------------------------------------------------------
    def test_94_adversarial_adapter_matrix_18_cases(self) -> None:
        """Assert UniversalModelGateway normalizes all 18 adversarial adapter behaviors into legal public contract."""
        test_matrix = [
            # 1. Provider spoof
            ([StreamDelta(content="Hello", finish_reason="stop", provider="spoofed_p", model_name="spoofed_m")], False, 1),
            # 2. Model spoof
            ([StreamDelta(content="Hello", finish_reason="stop", provider="prov_real", model_name="spoofed_m")], False, 1),
            # 3. Code with secret
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="api_key=sk-123", category="RESPONSE_ERROR", safe_message="clean"))], True, 1),
            # 4. Category with secret
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="password=xyz", safe_message="clean"))], True, 1),
            # 5. Malformed http_status
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="clean", http_status="abc"))], True, 1),
            # 6. Malformed retryable="false"
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="clean", retryable="false"))], True, 1),
            # 7. Error object on content delta
            ([StreamDelta(content="hello", finish_reason=None, error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="leak")), StreamDelta(content="", finish_reason="stop")], False, 2),
            # 8. Error object on normal stop
            ([StreamDelta(content="hello", finish_reason="stop", error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="leak"))], False, 1),
            # 9. finish_reason="error" with error=None
            ([StreamDelta(content="", finish_reason="error", error=None)], True, 1),
            # 10. Content + error terminal
            ([StreamDelta(content="partial", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="quota hit"))], True, 2),
            # 11. Zero deltas
            ([], True, 1),
            # 12. Content then silent EOF
            ([StreamDelta(content="partial content", finish_reason=None)], True, 2),
            # 13. Explicit empty stop
            ([StreamDelta(content="", finish_reason="stop")], True, 1),
            # 16. Structured AUTH_ERROR
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="invalid key", retryable=False, http_status=401))], True, 1),
            # 17. Structured RATE_LIMITED
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="limit hit", retryable=True, http_status=429))], True, 1),
            # 18. Unknown code/category
            ([StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="UNKNOWN_CUSTOM_XYZ", category="CUSTOM_CATEGORY", safe_message="custom"))], True, 1),
        ]

        for deltas_in, is_error_expected, expected_count in test_matrix:
            adapter = GenericMockStreamingAdapter(provider_name_val="prov_real", deltas=deltas_in)
            reg = ProviderRegistry()
            reg.register_provider(ProviderDefinition(provider_id="prov_real", display_name="Prov Real"))
            reg._injected_adapters["prov_real"] = adapter

            policy = ModelPolicy(
                global_target=ModelTarget(provider_id="prov_real", model_id="model_real"),
                fallback_chain=[ModelTarget(provider_id="prov_real", model_id="model_real")],
                free_only_mode=False,
            )

            gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
            public_deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

            self.assertEqual(len(public_deltas), expected_count)
            self.assert_public_stream_contract(public_deltas, "prov_real", "model_real")

    # ------------------------------------------------------------------
    # 95. Terminal State Matrix
    # ------------------------------------------------------------------
    def test_95_terminal_state_matrix(self) -> None:
        """Assert all 8 combinations in terminal state matrix deterministically yield legal outcomes."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_real", display_name="Prov Real"))
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_real", model_id="model_real"),
            fallback_chain=[ModelTarget(provider_id="prov_real", model_id="model_real")],
            free_only_mode=False,
        )

        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)

        # 1. No content / no terminal (silent EOF) -> STREAM_TRUNCATED (retryable=True)
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[])
        d1 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d1[0].error.code, "STREAM_TRUNCATED")
        self.assertTrue(d1[0].error.retryable)

        # 2. Content / no terminal (silent EOF after output) -> STREAM_TRUNCATED (retryable=False)
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[StreamDelta(content="Hello")])
        d2 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d2[0].content, "Hello")
        self.assertEqual(d2[1].error.code, "STREAM_TRUNCATED")
        self.assertFalse(d2[1].error.retryable)

        # 3. No content / stop -> EMPTY_RESPONSE (retryable=True)
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[StreamDelta(content="", finish_reason="stop")])
        d3 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d3[0].error.code, "EMPTY_RESPONSE")
        self.assertTrue(d3[0].error.retryable)

        # 4. Content / stop -> SUCCESS
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[StreamDelta(content="text", finish_reason="stop")])
        d4 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d4[0].content, "text")
        self.assertEqual(d4[0].finish_reason, "stop")
        self.assertIsNone(d4[0].error)

        # 5. No content / error -> Structured error preserved
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[StreamDelta(content="", finish_reason="error", error=ModelStreamError(code="AUTH_ERROR", category="AUTHENTICATION", safe_message="bad key", http_status=401))])
        d5 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d5[0].error.code, "AUTH_ERROR")
        self.assertEqual(d5[0].error.http_status, 401)

        # 6. Content / error -> Content delta then error delta
        reg._injected_adapters["prov_real"] = GenericMockStreamingAdapter("prov_real", deltas=[StreamDelta(content="partial", finish_reason="error", error=ModelStreamError(code="RATE_LIMITED", category="RATE_LIMIT", safe_message="quota", http_status=429))])
        d6 = list(gw.generate_stream(self._make_request(), model_policy=policy))
        self.assertEqual(d6[0].content, "partial")
        self.assertEqual(d6[1].error.code, "RATE_LIMITED")
        self.assertEqual(d6[1].error.http_status, 429)

    # ------------------------------------------------------------------
    # 96. Sync Metadata retryable Strict Type Validation (Production Path)
    # ------------------------------------------------------------------
    def test_96_sync_metadata_retryable_strict_type_validation_production_path(self) -> None:
        """Assert stream_unsupported -> generate() sync degradation strictly validates retryable metadata type."""
        cases = [
            # (raw_retryable_input, expected_public_retryable)
            ("false", False),  # Case A
            ("true", False),   # Case B
            (1, False),        # Case C
            (True, True),      # Case D
            (False, False),    # Case E
            (0, False),
            (None, False),
            ({}, False),
            ([], False),
        ]

        for raw_val, expected_bool in cases:
            sync_adapter = MockSyncOnlyAdapter(
                provider_name_val="sync_retryable_test",
                status=ModelResponseStatus.ERROR,
                error_msg="Rate limit reached",
                metadata={
                    "error_code": "RATE_LIMITED",
                    "error_category": "RATE_LIMIT",
                    "retryable": raw_val,
                    "http_status": 429,
                },
            )

            reg = ProviderRegistry()
            reg.register_provider(ProviderDefinition(provider_id="sync_retryable_test", display_name="Sync Test"))
            reg._injected_adapters["sync_retryable_test"] = sync_adapter

            policy = ModelPolicy(
                global_target=ModelTarget(provider_id="sync_retryable_test", model_id="m1"),
                fallback_chain=[ModelTarget(provider_id="sync_retryable_test", model_id="m1")],
                free_only_mode=False,
            )

            gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=False)
            deltas = list(gw.generate_stream(self._make_request(), model_policy=policy))

            self.assertEqual(len(deltas), 1)
            self.assertEqual(deltas[0].finish_reason, "error")
            err = deltas[0].error
            self.assertIsNotNone(err)
            self.assertEqual(err.code, "RATE_LIMITED")
            self.assertEqual(err.category, "RATE_LIMIT")
            self.assertEqual(err.http_status, 429)
            self.assertIs(err.retryable, expected_bool)
            self.assertIsInstance(err.retryable, bool)


if __name__ == "__main__":
    unittest.main()
