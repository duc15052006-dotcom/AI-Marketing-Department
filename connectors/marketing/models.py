"""Provider-neutral external marketing action contracts.

This module defines the safe request/policy boundary for future Meta, TikTok,
Google, and other marketing platform connectors. It deliberately performs no
network I/O and never resolves credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from governance.redaction import REDACTED_SENSITIVE_KEYS, sanitize_sensitive_payload
from tools.capabilities import PermissionLevel, RiskLevel


class ExternalMarketingContractError(ValueError):
    """Base error for invalid external-marketing contracts."""


class UnsafeMarketingPayloadError(ExternalMarketingContractError):
    """Raised when request payload contains credential-shaped fields."""


class UnsupportedMarketingCapabilityError(ExternalMarketingContractError):
    """Raised when a capability is outside the governed marketing surface."""


class MarketingEffect(str, Enum):
    READ = "READ"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    PUBLISH = "PUBLISH"
    FINANCIAL_OR_HIGH_RISK = "FINANCIAL_OR_HIGH_RISK"


class MarketingExecutionMode(str, Enum):
    CONTRACT_ONLY = "CONTRACT_ONLY"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"


@dataclass(frozen=True)
class MarketingCapabilityPolicy:
    capability_id: str
    effect: MarketingEffect
    required_permissions: Tuple[PermissionLevel, ...]
    risk_level: RiskLevel
    approval_required: bool

    @property
    def is_write(self) -> bool:
        return self.effect is not MarketingEffect.READ


MARKETING_CAPABILITY_POLICIES: Mapping[str, MarketingCapabilityPolicy] = MappingProxyType(
    {
        "analytics_retrieval": MarketingCapabilityPolicy(
            capability_id="analytics_retrieval",
            effect=MarketingEffect.READ,
            required_permissions=(PermissionLevel.READ_ONLY, PermissionLevel.ANALYTICS),
            risk_level=RiskLevel.LOW,
            approval_required=False,
        ),
        "social_publishing": MarketingCapabilityPolicy(
            capability_id="social_publishing",
            effect=MarketingEffect.PUBLISH,
            required_permissions=(PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE),
            risk_level=RiskLevel.CRITICAL,
            approval_required=True,
        ),
        "content_scheduling": MarketingCapabilityPolicy(
            capability_id="content_scheduling",
            effect=MarketingEffect.EXTERNAL_WRITE,
            required_permissions=(PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE),
            risk_level=RiskLevel.HIGH,
            approval_required=True,
        ),
        "platform_operations": MarketingCapabilityPolicy(
            capability_id="platform_operations",
            effect=MarketingEffect.FINANCIAL_OR_HIGH_RISK,
            required_permissions=(
                PermissionLevel.FINANCIAL_OR_HIGH_RISK,
                PermissionLevel.EXTERNAL_WRITE,
            ),
            risk_level=RiskLevel.CRITICAL,
            approval_required=True,
        ),
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{7,191}$")
_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "auth_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "credential",
    "private_key",
    "session_token",
)


def _required_identifier(name: str, value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _IDENTIFIER_RE.fullmatch(normalized):
        raise ExternalMarketingContractError(
            f"{name} must be a non-empty identifier containing only letters, numbers, '.', '_', ':', '/', or '-'."
        )
    return normalized


def _optional_identifier(name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return _required_identifier(name, normalized)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in REDACTED_SENSITIVE_KEYS or any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _validate_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _is_sensitive_key(key):
                raise UnsafeMarketingPayloadError(
                    f"Credential-shaped field '{path}.{key}' is forbidden; use ConnectionManager/SecretProvider instead."
                )
            _validate_payload(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            _validate_payload(child, f"{path}[{index}]")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(child) for child in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    if isinstance(value, frozenset):
        return sorted((_thaw(child) for child in value), key=repr)
    return value


def policy_for(capability_id: str) -> MarketingCapabilityPolicy:
    normalized = str(capability_id or "").strip().lower()
    try:
        return MARKETING_CAPABILITY_POLICIES[normalized]
    except KeyError as exc:
        raise UnsupportedMarketingCapabilityError(
            f"Capability '{capability_id}' is not part of the governed external-marketing contract."
        ) from exc


@dataclass(frozen=True)
class ExternalMarketingRequest:
    """Immutable request metadata for an external marketing platform action.

    Connection selection is explicit for every external call. Write requests also
    require an idempotency key before they can be prepared for a future execution
    path. Approval artifacts are intentionally not modelled here: trusted approval
    context belongs to DynamicToolGateway, outside model-controlled parameters.
    """

    request_id: str
    run_id: str
    connector_id: str
    connection_id: str
    capability_id: str
    action: str
    resource_type: str
    business_id: str
    project_id: Optional[str] = None
    brand_id: Optional[str] = None
    resource_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _required_identifier("request_id", self.request_id))
        object.__setattr__(self, "run_id", _required_identifier("run_id", self.run_id))
        object.__setattr__(self, "connector_id", _required_identifier("connector_id", self.connector_id))
        object.__setattr__(self, "connection_id", _required_identifier("connection_id", self.connection_id))
        object.__setattr__(self, "business_id", _required_identifier("business_id", self.business_id))
        object.__setattr__(self, "project_id", _optional_identifier("project_id", self.project_id))
        object.__setattr__(self, "brand_id", _optional_identifier("brand_id", self.brand_id))
        object.__setattr__(self, "resource_id", _optional_identifier("resource_id", self.resource_id))

        capability = str(self.capability_id or "").strip().lower()
        policy = policy_for(capability)
        object.__setattr__(self, "capability_id", capability)

        action = str(self.action or "").strip().lower()
        resource_type = str(self.resource_type or "").strip().lower()
        if not action or not _IDENTIFIER_RE.fullmatch(action):
            raise ExternalMarketingContractError("action must be a safe non-empty platform-neutral identifier.")
        if not resource_type or not _IDENTIFIER_RE.fullmatch(resource_type):
            raise ExternalMarketingContractError("resource_type must be a safe non-empty identifier.")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "resource_type", resource_type)

        key = self.idempotency_key
        if key is not None:
            key = str(key).strip()
            if not _IDEMPOTENCY_RE.fullmatch(key):
                raise ExternalMarketingContractError(
                    "idempotency_key must be 8-192 safe identifier characters."
                )
            object.__setattr__(self, "idempotency_key", key)
        if policy.is_write and not key:
            raise ExternalMarketingContractError(
                f"IDEMPOTENCY_KEY_REQUIRED: capability '{capability}' is an external write."
            )

        raw_payload = dict(self.payload or {})
        _validate_payload(raw_payload)
        object.__setattr__(self, "payload", _freeze(raw_payload))

    @property
    def policy(self) -> MarketingCapabilityPolicy:
        return policy_for(self.capability_id)

    def fingerprint(self) -> str:
        canonical = {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "connector_id": self.connector_id,
            "connection_id": self.connection_id,
            "capability_id": self.capability_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "brand_id": self.brand_id,
            "idempotency_key": self.idempotency_key,
            "payload": _thaw(self.payload),
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_safe_dict(self) -> Dict[str, Any]:
        return sanitize_sensitive_payload(
            {
                "request_id": self.request_id,
                "run_id": self.run_id,
                "connector_id": self.connector_id,
                "connection_id": self.connection_id,
                "capability_id": self.capability_id,
                "action": self.action,
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
                "business_id": self.business_id,
                "project_id": self.project_id,
                "brand_id": self.brand_id,
                "idempotency_key": self.idempotency_key,
                "payload": _thaw(self.payload),
                "request_fingerprint": self.fingerprint(),
            }
        )


@dataclass(frozen=True)
class MarketingConnectorSpec:
    """Metadata-only declaration for a future provider implementation."""

    connector_id: str
    provider: str
    supported_capabilities: Tuple[str, ...]
    execution_mode: MarketingExecutionMode = MarketingExecutionMode.CONTRACT_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_id", _required_identifier("connector_id", self.connector_id))
        provider = _required_identifier("provider", self.provider).lower()
        object.__setattr__(self, "provider", provider)
        capabilities = tuple(dict.fromkeys(str(item).strip().lower() for item in self.supported_capabilities if str(item).strip()))
        if not capabilities:
            raise ExternalMarketingContractError("supported_capabilities must not be empty.")
        for capability_id in capabilities:
            policy_for(capability_id)
        object.__setattr__(self, "supported_capabilities", capabilities)

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "provider": self.provider,
            "supported_capabilities": list(self.supported_capabilities),
            "execution_mode": self.execution_mode.value,
        }
