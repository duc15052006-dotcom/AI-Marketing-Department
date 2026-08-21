"""Connector Registry and Health Management (Phase 6.1).

Central registry for managing connector descriptors, safe credential discovery,
health diagnostics, and fallback policies without secret leakage.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from connectors.models import (
    AuthenticationType,
    ConnectorCredentialStatus,
    ConnectorDescriptor,
    ConnectorHealthStatus,
    CredentialState,
    ReadWriteMode,
)
from tools.capabilities import RiskLevel

logger = logging.getLogger("connector_registry")


class ConnectorRegistry:
    """Registry managing connector lifecycle, health checks, and fallback chains."""

    def __init__(self) -> None:
        self._connectors: Dict[str, ConnectorDescriptor] = {}
        self._credential_statuses: Dict[str, ConnectorCredentialStatus] = {}
        self._fallback_chains: Dict[str, List[str]] = {}
        self._load_builtin_connectors()

    def register_connector(self, descriptor: ConnectorDescriptor) -> None:
        """Register or update a connector descriptor."""
        cid = descriptor.connector_id.lower()
        self._connectors[cid] = descriptor
        self.refresh_connector_health(cid)
        logger.info(f"Registered connector '{descriptor.connector_id}' for provider '{descriptor.provider}'")

    def get_connector(self, connector_id: str) -> Optional[ConnectorDescriptor]:
        """Retrieve connector by ID."""
        return self._connectors.get(connector_id.lower())

    def list_connectors(self) -> List[ConnectorDescriptor]:
        """List all registered connectors."""
        return list(self._connectors.values())

    def set_fallback_chain(self, capability_id: str, connector_ids: List[str]) -> None:
        """Configure priority fallback chain of connectors for a capability."""
        self._fallback_chains[capability_id.lower()] = [cid.lower() for cid in connector_ids]

    def get_fallback_chain(self, capability_id: str) -> List[str]:
        """Get configured connector fallback chain for a capability."""
        return self._fallback_chains.get(capability_id.lower(), [])

    def refresh_connector_health(self, connector_id: str) -> ConnectorHealthStatus:
        """Inspect credentials and environment safely without exposing secret values."""
        cid = connector_id.lower()
        conn = self._connectors.get(cid)
        if not conn:
            return ConnectorHealthStatus.UNAVAILABLE

        now = datetime.now(timezone.utc)
        conn.last_health_check = now

        # Check credentials if required
        if conn.authentication_type in (AuthenticationType.API_KEY, AuthenticationType.BEARER_TOKEN, AuthenticationType.OAUTH2):
            env_vars = conn.credential_env_names
            missing_vars = [v for v in env_vars if not os.environ.get(v)]

            if missing_vars:
                conn.health_status = ConnectorHealthStatus.MISSING_CREDENTIAL
                self._credential_statuses[cid] = ConnectorCredentialStatus(
                    connector_id=cid,
                    credential_env_names=env_vars,
                    state=CredentialState.MISSING,
                    last_verified=now,
                    detail=f"Missing required env vars: {', '.join(missing_vars)}",
                )
                return ConnectorHealthStatus.MISSING_CREDENTIAL
            else:
                conn.health_status = ConnectorHealthStatus.AVAILABLE
                self._credential_statuses[cid] = ConnectorCredentialStatus(
                    connector_id=cid,
                    credential_env_names=env_vars,
                    state=CredentialState.AVAILABLE,
                    last_verified=now,
                    detail="All credentials present in environment",
                )
                return ConnectorHealthStatus.AVAILABLE
        elif conn.health_status == ConnectorHealthStatus.DISABLED:
            return ConnectorHealthStatus.DISABLED
        else:
            conn.health_status = ConnectorHealthStatus.AVAILABLE
            self._credential_statuses[cid] = ConnectorCredentialStatus(
                connector_id=cid,
                state=CredentialState.AVAILABLE,
                last_verified=now,
                detail="No external credentials required",
            )
            return ConnectorHealthStatus.AVAILABLE

    def list_connector_health(self) -> Dict[str, Dict[str, Any]]:
        """Return diagnostic health summary for all connectors (zero secret exposure)."""
        health_summary = {}
        for cid, conn in self._connectors.items():
            self.refresh_connector_health(cid)
            cred = self._credential_statuses.get(cid)
            health_summary[conn.connector_id] = {
                "provider": conn.provider,
                "health_status": conn.health_status.value,
                "read_write_mode": conn.read_write_mode.value,
                "credential_state": cred.state.value if cred else "UNKNOWN",
                "capabilities": conn.capability_ids,
                "last_checked": conn.last_health_check.isoformat() if conn.last_health_check else None,
            }
        return health_summary

    def resolve_executable_connector(self, capability_id: str, is_write: bool = False) -> Optional[ConnectorDescriptor]:
        """Resolve available connector for a capability, enforcing no-fallback rule on external writes."""
        cap_id = capability_id.lower()
        chain = self.get_fallback_chain(cap_id)

        if not chain:
            # Match directly
            candidates = [c for c in self._connectors.values() if cap_id in [cid.lower() for cid in c.capability_ids]]
        else:
            candidates = [self._connectors[cid] for cid in chain if cid in self._connectors]

        if is_write:
            # Strictly prohibited from automatic cross-provider fallback on external writes
            primary = candidates[0] if candidates else None
            if primary and primary.health_status == ConnectorHealthStatus.AVAILABLE:
                return primary
            return None

        # Read / generation fallback
        for conn in candidates:
            self.refresh_connector_health(conn.connector_id)
            if conn.health_status == ConnectorHealthStatus.AVAILABLE:
                return conn

        return None

    def _load_builtin_connectors(self) -> None:
        """Register the baseline V1 connector suite."""
        # 1. Web / Observation Connector
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_web_reader",
                provider="system_http_reader",
                capability_ids=["web_search", "read_page", "structured_data_retrieval"],
                authentication_type=AuthenticationType.NONE,
                read_write_mode=ReadWriteMode.READ_ONLY,
                risk_level=RiskLevel.LOW,
                supported_operations=["http_get", "html_parse", "metadata_extract"],
            )
        )

        # 2. File / Data Connector
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_file_system",
                provider="local_filesystem",
                capability_ids=["file_read", "file_write", "structured_storage_query", "data_export"],
                authentication_type=AuthenticationType.LOCAL_FILESYSTEM,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.LOW,
                supported_operations=["read_text", "write_text", "read_json", "write_json", "read_csv", "export_bundle"],
            )
        )

        # 3. Model / Creative Support Connectors
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_model_xkiro",
                provider="xkiro",
                capability_ids=["text_generation_support"],
                authentication_type=AuthenticationType.API_KEY,
                credential_env_names=["XKIRO_API_KEY"],
                read_write_mode=ReadWriteMode.READ_ONLY,
                risk_level=RiskLevel.LOW,
                supported_operations=["chat_completions"],
            )
        )
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_model_gemini",
                provider="gemini",
                capability_ids=["text_generation_support"],
                authentication_type=AuthenticationType.API_KEY,
                credential_env_names=["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                read_write_mode=ReadWriteMode.READ_ONLY,
                risk_level=RiskLevel.LOW,
                supported_operations=["generate_content"],
            )
        )

        # 4. Image & Video Connectors (Provider-Neutral with Safe Mock Fallback)
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_image_generator",
                provider="local_image_mock",
                capability_ids=["image_generation", "image_editing"],
                authentication_type=AuthenticationType.NONE,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.MEDIUM,
                supported_operations=["generate_mockup", "edit_asset"],
            )
        )
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_video_generator",
                provider="local_video_mock",
                capability_ids=["video_generation", "video_editing_rendering"],
                authentication_type=AuthenticationType.NONE,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.MEDIUM,
                supported_operations=["render_sequence", "edit_clips"],
            )
        )

        # 5. Analytics Connector
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_analytics_engine",
                provider="local_analytics",
                capability_ids=["analytics_retrieval", "kpi_calculation", "attribution_data_access", "experiment_result_analysis"],
                authentication_type=AuthenticationType.NONE,
                read_write_mode=ReadWriteMode.READ_ONLY,
                risk_level=RiskLevel.LOW,
                supported_operations=["compute_roas", "calculate_cac", "stats_test"],
            )
        )

        # 6. Publishing Connector (Sandbox / Mock Only in Phase 6.1)
        self.register_connector(
            ConnectorDescriptor(
                connector_id="conn_publishing_sandbox",
                provider="sandbox_publisher",
                capability_ids=["social_publishing", "content_scheduling", "platform_operations"],
                authentication_type=AuthenticationType.NONE,
                read_write_mode=ReadWriteMode.WRITE_ONLY,
                risk_level=RiskLevel.CRITICAL,
                health_status=ConnectorHealthStatus.AVAILABLE,
                supported_operations=["sandbox_publish", "sandbox_schedule"],
                configuration_metadata={"mode": "SANDBOX_MOCK_ONLY", "real_publishing_disabled": True},
            )
        )

        # Setup default fallback chains
        self.set_fallback_chain("text_generation_support", ["conn_model_xkiro", "conn_model_gemini"])
