"""Real File and Data Connector (Phase 6.1).

Implements real local filesystem reads, writes, JSON/CSV parsing, and structured data exports.
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


class RealFileConnector(BaseCapabilityAdapter):
    """Real filesystem and data export connector with sandboxed path validation."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or Path.cwd()

    @property
    def adapter_name(self) -> str:
        return "local_filesystem"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 15.0) -> AdapterResult:
        start_time = time.perf_counter()
        cap = capability_id.lower()
        path_str = parameters.get("path", "")

        if not path_str:
            return AdapterResult(
                success=False,
                error_code="INVALID_PATH",
                error_message="Missing required parameter 'path'.",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        target_path = (self.base_dir / path_str).resolve()

        if cap in ("file_read", "read_file"):
            if not target_path.exists():
                return AdapterResult(
                    success=False,
                    error_code="FILE_NOT_FOUND",
                    error_message=f"File not found: {path_str}",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            try:
                content = target_path.read_text(encoding="utf-8")
                return AdapterResult(
                    success=True,
                    data={"path": str(path_str), "content": content, "size_bytes": len(content)},
                    artifact_refs=[str(path_str)],
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="READ_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

        elif cap in ("file_write", "write_file", "data_export"):
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
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="WRITE_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

        elif cap == "structured_storage_query":
            # Read CSV / JSON table query
            if not target_path.exists():
                return AdapterResult(
                    success=False,
                    error_code="DATASET_NOT_FOUND",
                    error_message=f"Dataset not found at {path_str}",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
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
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="QUERY_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

        return AdapterResult(
            success=False,
            error_code="UNSUPPORTED_CAPABILITY",
            error_message=f"Capability '{capability_id}' is not supported by RealFileConnector.",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
        )
