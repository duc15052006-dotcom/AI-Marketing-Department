"""Pytest-only compatibility layer for historical suites.

This module intentionally does NOT alter production ToolGateway registration or
restore fake production adapters. It only exposes the old configurable
MockToolAdapter symbol to legacy tests that use it for deterministic retry /
timeout injection, and supplies typing aliases omitted by historical test
modules so collection can reach their actual assertions.
"""

from __future__ import annotations

import builtins
import time
from typing import Any, Dict, List, Tuple

import tools.adapters as _adapters
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


# Historical tests use these names in runtime-evaluated annotations without
# importing them. Keep compatibility strictly under pytest, never in runtime.
builtins.List = List
builtins.Tuple = Tuple
builtins.Any = Any


class MockToolAdapter(BaseCapabilityAdapter):
    """Explicit test double for retry, timeout and failure-path verification.

    A successful result is always marked ExecutionMode.MOCK, so no caller can
    mistake this deterministic test helper for real external execution.
    """

    def __init__(
        self,
        name: str = "mock_adapter",
        should_fail: bool = False,
        error_code: str = "INTERNAL_ERROR",
        error_message: str = "Mock error",
        delay_seconds: float = 0.0,
        fail_attempts: int = 0,
    ) -> None:
        self._name = name
        self._should_fail = bool(should_fail)
        self._error_code = error_code
        self._error_message = error_message
        self._delay_seconds = float(delay_seconds)
        self._fail_attempts = int(fail_attempts)
        self._current_attempts = 0

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        started = time.perf_counter()
        self._current_attempts += 1

        if self._delay_seconds > 0:
            time.sleep(min(self._delay_seconds, timeout_seconds))
            if self._delay_seconds > timeout_seconds:
                return AdapterResult(
                    success=False,
                    error_code="TIMEOUT",
                    error_message=f"Execution exceeded timeout limit of {timeout_seconds}s.",
                    latency_ms=timeout_seconds * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        if self._current_attempts <= self._fail_attempts or self._should_fail:
            return AdapterResult(
                success=False,
                error_code=self._error_code,
                error_message=self._error_message,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        return AdapterResult(
            success=True,
            data={"mock_output": "SUCCESS_PAYLOAD", "attempts": self._current_attempts},
            latency_ms=(time.perf_counter() - started) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


# Historical suites import this symbol from tools.adapters. Expose it only for
# the pytest process; source module and production registry remain fail-closed.
_adapters.MockToolAdapter = MockToolAdapter
