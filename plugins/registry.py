"""Safe plugin discovery, lifecycle, capability export, and executor binding."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from plugins.models import PluginManifest, PluginRecord, PluginState, PluginToolDeclaration
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CostPolicy,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)


_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,95}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginRegistryError(RuntimeError):
    pass


class PluginNotFoundError(PluginRegistryError):
    pass


class PluginDisabledError(PluginRegistryError):
    pass


class PluginCollisionError(PluginRegistryError):
    pass


class PluginExecutorNotBoundError(PluginRegistryError):
    pass


Executor = Callable[[Dict[str, Any], Optional[Any]], Any]


class PluginRegistry:
    """Registry for declarative, namespaced plugins.

    Security properties:
    - manifests never contain executable Python import paths;
    - plugin IDs and tool names are globally namespaced;
    - a manifest cannot execute until trusted code explicitly binds an executor;
    - disabled/quarantined plugins fail closed.
    """

    def __init__(self) -> None:
        self._records: Dict[str, PluginRecord] = {}
        self._executors: Dict[str, Executor] = {}

    @staticmethod
    def capability_id(plugin_id: str, tool_name: str) -> str:
        return f"plugin.{plugin_id}.{tool_name}"

    @staticmethod
    def _validate_manifest(manifest: PluginManifest) -> None:
        if not _PLUGIN_ID_RE.fullmatch(manifest.plugin_id):
            raise ValueError("plugin_id must match ^[a-z][a-z0-9_-]{1,63}$")
        if not _VERSION_RE.fullmatch(manifest.version):
            raise ValueError("version must be semantic version-like, e.g. 1.0.0")
        if manifest.api_version != "1":
            raise ValueError(f"unsupported plugin api_version: {manifest.api_version}")

        seen = set()
        for tool in manifest.tools:
            if not _TOOL_NAME_RE.fullmatch(tool.name):
                raise ValueError(f"invalid plugin tool name: {tool.name}")
            if tool.name in seen:
                raise PluginCollisionError(f"duplicate tool '{tool.name}' in plugin '{manifest.plugin_id}'")
            seen.add(tool.name)
            PluginRegistry._validate_tool_policy(tool)

    @staticmethod
    def _validate_tool_policy(tool: PluginToolDeclaration) -> None:
        try:
            CapabilityCategory(tool.category)
            EvidenceRole(tool.evidence_role)
            RiskLevel(tool.risk_level)
            for permission in tool.required_permissions:
                PermissionLevel(permission)
        except ValueError as exc:
            raise ValueError(f"invalid policy value for plugin tool '{tool.name}': {exc}") from exc

        high_impact = tool.risk_level in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}
        external = any(
            p in {
                PermissionLevel.EXTERNAL_WRITE.value,
                PermissionLevel.PUBLISH.value,
                PermissionLevel.FINANCIAL_OR_HIGH_RISK.value,
            }
            for p in tool.required_permissions
        )
        if (high_impact or external) and not tool.human_approval_required:
            raise ValueError(
                f"plugin tool '{tool.name}' is high-impact/external but human_approval_required is false"
            )

    @staticmethod
    def _fingerprint(manifest: PluginManifest) -> str:
        payload = json.dumps(manifest.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def register(self, manifest: PluginManifest, *, enabled: bool = False) -> PluginRecord:
        self._validate_manifest(manifest)
        pid = manifest.plugin_id
        if pid in self._records:
            raise PluginCollisionError(f"plugin '{pid}' is already registered")

        new_ids = {self.capability_id(pid, tool.name) for tool in manifest.tools}
        overlap = new_ids & set(self.list_capability_ids())
        if overlap:
            raise PluginCollisionError(f"capability collision: {sorted(overlap)}")

        record = PluginRecord(
            manifest=manifest,
            state=PluginState.ENABLED if enabled else PluginState.DISABLED,
            fingerprint=self._fingerprint(manifest),
        )
        self._records[pid] = record
        return record

    def unregister(self, plugin_id: str) -> None:
        if plugin_id not in self._records:
            raise PluginNotFoundError(plugin_id)
        del self._records[plugin_id]
        prefix = f"plugin.{plugin_id}."
        for capability_id in [cid for cid in self._executors if cid.startswith(prefix)]:
            del self._executors[capability_id]

    def get(self, plugin_id: str) -> PluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise PluginNotFoundError(plugin_id)
        return record

    def list_plugins(self) -> List[PluginRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRecord:
        record = self.get(plugin_id)
        if record.state == PluginState.QUARANTINED and enabled:
            raise PluginDisabledError(f"plugin '{plugin_id}' is quarantined")
        record.state = PluginState.ENABLED if enabled else PluginState.DISABLED
        return record

    def quarantine(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        record.state = PluginState.QUARANTINED
        return record

    def bind_executor(self, plugin_id: str, tool_name: str, executor: Executor) -> str:
        record = self.get(plugin_id)
        if tool_name not in {tool.name for tool in record.manifest.tools}:
            raise PluginNotFoundError(f"tool '{tool_name}' not declared by plugin '{plugin_id}'")
        if not callable(executor):
            raise TypeError("executor must be callable")
        capability_id = self.capability_id(plugin_id, tool_name)
        self._executors[capability_id] = executor
        return capability_id

    def execute(self, capability_id: str, parameters: Dict[str, Any], context: Optional[Any] = None) -> Any:
        plugin_id, tool_name = self._parse_capability_id(capability_id)
        record = self.get(plugin_id)
        if record.state != PluginState.ENABLED:
            raise PluginDisabledError(f"plugin '{plugin_id}' is not enabled")
        if tool_name not in {tool.name for tool in record.manifest.tools}:
            raise PluginNotFoundError(capability_id)
        executor = self._executors.get(capability_id)
        if executor is None:
            raise PluginExecutorNotBoundError(capability_id)
        return executor(dict(parameters), context)

    @staticmethod
    def _parse_capability_id(capability_id: str) -> Tuple[str, str]:
        parts = capability_id.split(".")
        if len(parts) != 3 or parts[0] != "plugin":
            raise PluginNotFoundError(capability_id)
        return parts[1], parts[2]

    def list_capability_ids(self, *, enabled_only: bool = False) -> List[str]:
        result: List[str] = []
        for record in self.list_plugins():
            if enabled_only and record.state != PluginState.ENABLED:
                continue
            pid = record.manifest.plugin_id
            result.extend(self.capability_id(pid, tool.name) for tool in record.manifest.tools)
        return sorted(result)

    def capability_descriptors(self, *, enabled_only: bool = True) -> List[CapabilityDescriptor]:
        """Export plugin tools into the existing platform CapabilityDescriptor contract."""
        descriptors: List[CapabilityDescriptor] = []
        for record in self.list_plugins():
            if enabled_only and record.state != PluginState.ENABLED:
                continue
            for tool in record.manifest.tools:
                descriptors.append(
                    CapabilityDescriptor(
                        capability_id=self.capability_id(record.manifest.plugin_id, tool.name),
                        name=f"{record.manifest.name}: {tool.name}",
                        category=CapabilityCategory(tool.category),
                        evidence_role=EvidenceRole(tool.evidence_role),
                        description=tool.description,
                        input_schema=dict(tool.input_schema),
                        output_schema=dict(tool.output_schema),
                        required_permissions=[PermissionLevel(p) for p in tool.required_permissions],
                        risk_level=RiskLevel(tool.risk_level),
                        human_approval_required=tool.human_approval_required,
                        supported_agents=list(tool.supported_agents),
                        provider=f"plugin:{record.manifest.plugin_id}",
                        availability="AVAILABLE" if record.state == PluginState.ENABLED else "UNAVAILABLE",
                        cost_policy=CostPolicy.FREE_LOCAL,
                        timeout_policy=tool.timeout_seconds,
                    )
                )
        return descriptors
