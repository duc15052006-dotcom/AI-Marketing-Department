"""Publishing Connector Contract and Sandbox (Phase 6.1).

Defines the formal social and ad platform publishing interface contract
with a strict sandbox mock implementation (no live public social posting in this phase).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


class SandboxPublishingConnector(BaseCapabilityAdapter):
    """Sandbox publisher for social media, ad platforms, and scheduling operations."""

    def __init__(self, mode: str = "SANDBOX_MOCK_ONLY") -> None:
        self.mode = mode
        self._published_records: List[Dict[str, Any]] = []

    @property
    def adapter_name(self) -> str:
        return "sandbox_publisher"

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 15.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        start_time = time.perf_counter()
        platform = parameters.get("platform", "generic")
        content = parameters.get("content", "")
        post_id = f"SANDBOX-PUB-{uuid.uuid4().hex[:8].upper()}"

        record = {
            "post_id": post_id,
            "capability": capability_id,
            "platform": platform,
            "content_preview": content[:100],
            "mode": self.mode,
            "published_at": time.time(),
        }
        self._published_records.append(record)

        return AdapterResult(
            success=True,
            data={
                "post_id": post_id,
                "platform": platform,
                "status": "SANDBOX_PUBLISHED",
                "mode": self.mode,
                "message": "Asset queued and simulated in sandbox environment. Zero public accounts touched.",
            },
            artifact_refs=[post_id],
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            execution_mode=ExecutionMode.SANDBOX,
        )
