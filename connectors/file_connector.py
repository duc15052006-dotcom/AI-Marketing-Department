"""Real File and Data Connector (Phase 6.1).

Implements real local filesystem reads, writes, JSON/CSV parsing, and structured data exports.
Hardened with strict filesystem sandbox containment (PROD-FS-01).
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.filesystem_guard import FilesystemSecurityError, resolve_safe_path
from tools.receipts import ExecutionMode


class RealFileConnector(BaseCapabilityAdapter):
    """Real filesystem and data export connector with sandboxed path validation."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = (base_dir or Path.cwd()).resolve()

    @property
    def adapter_name(self) -> str:
        return "local_filesystem"

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
        cap = capability_id.lower()
        path_str = parameters.get("path", "")

        if not path_str or not isinstance(path_str, str):
            return AdapterResult(
                success=False,
                error_code="INVALID_PATH",
                error_message="Missing or invalid required parameter 'path'.",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        if cap in ("file_read", "read_file"):
            try:
                target_path = resolve_safe_path(self.base_dir, path_str, operation="read")
            except FilesystemSecurityError as e:
                return AdapterResult(
                    success=False,
                    error_code=e.error_code,
                    error_message=e.message,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

            try:
                content = target_path.read_text(encoding="utf-8")
                return AdapterResult(
                    success=True,
                    data={"path": str(path_str), "content": content, "size_bytes": len(content)},
                    artifact_refs=[str(path_str)],
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="READ_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        elif cap in ("file_write", "write_file", "data_export"):
            try:
                target_path = resolve_safe_path(self.base_dir, path_str, operation="write")
            except FilesystemSecurityError as e:
                return AdapterResult(
                    success=False,
                    error_code=e.error_code,
                    error_message=e.message,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

            content = parameters.get("content", "")
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, (dict, list)):
                    target_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
                else:
                    target_path.write_text(str(content), encoding="utf-8")

                return AdapterResult(
                    success=True,
                    data={"path": str(path_str), "status": "WRITTEN", "bytes_written": len(str(content))},
                    artifact_refs=[str(path_str)],
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="WRITE_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        elif cap == "structured_storage_query":
            try:
                target_path = resolve_safe_path(self.base_dir, path_str, operation="read")
            except FilesystemSecurityError as e:
                err_code = "DATASET_NOT_FOUND" if e.error_code == "FILE_NOT_FOUND" else e.error_code
                return AdapterResult(
                    success=False,
                    error_code=err_code,
                    error_message=e.message,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

            try:
                if target_path.suffix.lower() == ".json":
                    data = json.loads(target_path.read_text(encoding="utf-8"))
                    rows = data if isinstance(data, list) else [data]
                elif target_path.suffix.lower() == ".csv":
                    with open(target_path, mode="r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                else:
                    rows = [{"raw": target_path.read_text(encoding="utf-8")}]

                return AdapterResult(
                    success=True,
                    data={"dataset": path_str, "row_count": len(rows), "rows": rows[:100]},
                    artifact_refs=[str(path_str)],
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="QUERY_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        return AdapterResult(
            success=False,
            error_code="UNSUPPORTED_CAPABILITY",
            error_message=f"Capability '{capability_id}' is not supported by RealFileConnector.",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
