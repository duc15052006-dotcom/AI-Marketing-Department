"""Connector Architecture Models (Phase 6.1).

Defines provider-neutral connector descriptors, capability bindings, credential statuses,
health metrics, and authentication types for the ToolGateway connector layer.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from tools.capabilities import RiskLevel


class AuthenticationType(str, Enum):
    """Authentication mechanism for external and local connectors."""
    NONE = "NONE"
    API_KEY = "API_KEY"
    BEARER_TOKEN = "BEARER_TOKEN"
    OAUTH2 = "OAUTH2"
    LOCAL_FILESYSTEM = "LOCAL_FILESYSTEM"


class ReadWriteMode(str, Enum):
    """Operational access mode for a connector."""
    READ_ONLY = "READ_ONLY"
    WRITE_ONLY = "WRITE_ONLY"
    READ_WRITE = "READ_WRITE"


class ConnectorHealthStatus(str, Enum):
    """Health and operational state of a connector."""
    AVAILABLE = "AVAILABLE"
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    RATE_LIMITED = "RATE_LIMITED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class CredentialState(str, Enum):
    """Credential presence and validity state without exposing secret values."""
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ConnectorCredentialStatus(BaseModel):
    """Sanitized representation of connector credentials."""
    connector_id: str
    credential_env_names: List[str] = Field(default_factory=list)
    state: CredentialState = CredentialState.UNKNOWN
    last_verified: Optional[datetime] = None
    detail: str = ""


class ConnectorCapabilityBinding(BaseModel):
    """Binding between a connector and a specific capability ID."""
    capability_id: str
    is_primary: bool = True
    priority_order: int = 1


class ConnectorDescriptor(BaseModel):
    """Comprehensive declaration of a provider-neutral connector."""
    connector_id: str = Field(..., description="Unique connector ID, e.g. 'conn_web_http'")
    provider: str = Field(..., description="Provider name or vendor, e.g. 'system_http', 'xkiro', 'gemini'")
    capability_ids: List[str] = Field(default_factory=list, description="Supported capability IDs")
    authentication_type: AuthenticationType = AuthenticationType.NONE
    credential_env_names: List[str] = Field(default_factory=list, description="Required environment variable names")
    read_write_mode: ReadWriteMode = ReadWriteMode.READ_ONLY
    risk_level: RiskLevel = RiskLevel.LOW
    health_status: ConnectorHealthStatus = ConnectorHealthStatus.AVAILABLE
    last_health_check: Optional[datetime] = None
    rate_limit_state: Dict[str, Any] = Field(default_factory=dict)
    supported_operations: List[str] = Field(default_factory=list)
    configuration_metadata: Dict[str, Any] = Field(default_factory=dict)

    def calculate_descriptor_hash(self) -> str:
        """Compute SHA-256 hash of descriptor metadata."""
        raw = f"{self.connector_id}:{self.provider}:{self.read_write_mode.value}:{json.dumps(self.capability_ids)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
