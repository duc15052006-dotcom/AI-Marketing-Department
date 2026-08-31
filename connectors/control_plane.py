"""Connector-to-Connection authority bridge.

This module makes ``ConnectionManager`` the credential/scope authority for
credentialed connectors without changing legacy ConnectorRegistry call sites yet.
Metadata status checks never resolve secrets. Plaintext credential access happens
only at the explicit ``resolve_for_execution`` boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from connections.manager import (
    ConnectionDisabledError,
    ConnectionManager,
    ConnectionScopeDeniedError,
    ResolvedConnection,
)
from connections.models import ConnectionProfile
from connectors.models import AuthenticationType, ConnectorDescriptor, ConnectorHealthStatus
from connectors.registry import ConnectorRegistry


class ConnectorControlPlaneError(RuntimeError):
    """Base error for connector/connection authority failures."""


class ConnectorNotFoundError(ConnectorControlPlaneError):
    pass


class ConnectorBindingError(ConnectorControlPlaneError):
    pass


class ConnectorProviderMismatchError(ConnectorBindingError):
    pass


class ConnectorAmbiguousBindingError(ConnectorBindingError):
    pass


class ConnectorAuthorityState(str, Enum):
    LOCAL_AVAILABLE = "LOCAL_AVAILABLE"
    CONFIGURED_UNVERIFIED = "CONFIGURED_UNVERIFIED"
    MISSING_BINDING = "MISSING_BINDING"
    CONNECTION_DISABLED = "CONNECTION_DISABLED"
    SCOPE_DENIED = "SCOPE_DENIED"
    AMBIGUOUS_BINDING = "AMBIGUOUS_BINDING"
    CONNECTOR_DISABLED = "CONNECTOR_DISABLED"


@dataclass(frozen=True)
class ConnectorBinding:
    connector_id: str
    connection_id: str

    def to_safe_dict(self) -> Dict[str, str]:
        return {
            "connector_id": self.connector_id,
            "connection_id": self.connection_id,
        }


@dataclass(frozen=True)
class ConnectorAuthorityStatus:
    connector_id: str
    provider: str
    state: ConnectorAuthorityState
    connection_id: Optional[str] = None
    credential_resolved: bool = False
    detail: str = ""

    def to_safe_dict(self) -> Dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "provider": self.provider,
            "state": self.state.value,
            "connection_id": self.connection_id,
            "credential_resolved": self.credential_resolved,
            "detail": self.detail,
        }


@dataclass(frozen=True, repr=False)
class ResolvedConnectorAccess:
    """Execution-boundary connector selection with optional credential access."""

    descriptor: ConnectorDescriptor
    connection: Optional[ResolvedConnection]
    local_no_auth: bool

    def __repr__(self) -> str:
        connection_id = self.connection.profile.connection_id if self.connection else None
        return (
            "ResolvedConnectorAccess("
            f"connector_id={self.descriptor.connector_id!r}, "
            f"provider={self.descriptor.provider!r}, "
            f"connection_id={connection_id!r}, credential=***)"
        )


class ConnectorControlPlane:
    """Scope-aware bridge from connector descriptors to ConnectionManager.

    The registry remains the descriptor/capability catalog. ConnectionManager is
    the sole credential authority for authenticated connectors. Legacy
    ``credential_env_names`` are deliberately ignored by this control plane.
    """

    _NO_SECRET_AUTH = {AuthenticationType.NONE, AuthenticationType.LOCAL_FILESYSTEM}

    def __init__(self, connector_registry: ConnectorRegistry, connection_manager: ConnectionManager) -> None:
        self.connector_registry = connector_registry
        self.connection_manager = connection_manager
        self._bindings: Dict[str, Set[str]] = {}

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").strip().lower()

    def _descriptor(self, connector_id: str) -> ConnectorDescriptor:
        descriptor = self.connector_registry.get_connector(connector_id)
        if descriptor is None:
            raise ConnectorNotFoundError(f"Connector '{connector_id}' is not registered.")
        return descriptor

    @classmethod
    def _requires_connection(cls, descriptor: ConnectorDescriptor) -> bool:
        return descriptor.authentication_type not in cls._NO_SECRET_AUTH

    @staticmethod
    def _profile_specificity(profile: ConnectionProfile) -> int:
        """Prefer an exact scoped account over a broader/global account."""
        score = 0
        if profile.business_id is not None:
            score += 4
        if profile.project_ids:
            score += 2
        if profile.brand_ids:
            score += 1
        return score

    @staticmethod
    def _assert_provider_match(descriptor: ConnectorDescriptor, profile: ConnectionProfile) -> None:
        if descriptor.provider.strip().lower() != profile.provider.strip().lower():
            raise ConnectorProviderMismatchError(
                f"Connector '{descriptor.connector_id}' provider does not match connection '{profile.connection_id}'."
            )

    def bind(self, connector_id: str, connection_id: str) -> ConnectorBinding:
        descriptor = self._descriptor(connector_id)
        if not self._requires_connection(descriptor):
            raise ConnectorBindingError(
                f"Connector '{descriptor.connector_id}' does not require an external credential binding."
            )
        profile = self.connection_manager.get(connection_id)
        self._assert_provider_match(descriptor, profile)
        cid = self._normalize(descriptor.connector_id)
        self._bindings.setdefault(cid, set()).add(profile.connection_id)
        return ConnectorBinding(connector_id=descriptor.connector_id, connection_id=profile.connection_id)

    def unbind(self, connector_id: str, connection_id: str) -> bool:
        cid = self._normalize(connector_id)
        bound = self._bindings.get(cid)
        if not bound or connection_id not in bound:
            return False
        bound.remove(connection_id)
        if not bound:
            self._bindings.pop(cid, None)
        return True

    def list_bindings(self, connector_id: Optional[str] = None) -> List[ConnectorBinding]:
        if connector_id is None:
            connector_ids = sorted(self._bindings)
        else:
            descriptor = self._descriptor(connector_id)
            connector_ids = [self._normalize(descriptor.connector_id)]
        result: List[ConnectorBinding] = []
        for cid in connector_ids:
            descriptor = self._descriptor(cid)
            for connection_id in sorted(self._bindings.get(cid, set())):
                result.append(
                    ConnectorBinding(
                        connector_id=descriptor.connector_id,
                        connection_id=connection_id,
                    )
                )
        return result

    def _authorized_candidates(
        self,
        descriptor: ConnectorDescriptor,
        *,
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> Tuple[List[ConnectionProfile], int, int]:
        candidates: List[ConnectionProfile] = []
        disabled = 0
        denied = 0
        for connection_id in sorted(self._bindings.get(self._normalize(descriptor.connector_id), set())):
            try:
                profile = self.connection_manager.authorize_profile(
                    connection_id,
                    business_id=business_id,
                    project_id=project_id,
                    brand_id=brand_id,
                )
            except ConnectionDisabledError:
                disabled += 1
                continue
            except ConnectionScopeDeniedError:
                denied += 1
                continue
            self._assert_provider_match(descriptor, profile)
            candidates.append(profile)
        return candidates, disabled, denied

    def _select_profile(
        self,
        descriptor: ConnectorDescriptor,
        *,
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
        connection_id: Optional[str],
    ) -> ConnectionProfile:
        bound = self._bindings.get(self._normalize(descriptor.connector_id), set())
        if connection_id is not None:
            if connection_id not in bound:
                raise ConnectorBindingError(
                    f"Connection '{connection_id}' is not bound to connector '{descriptor.connector_id}'."
                )
            profile = self.connection_manager.authorize_profile(
                connection_id,
                business_id=business_id,
                project_id=project_id,
                brand_id=brand_id,
            )
            self._assert_provider_match(descriptor, profile)
            return profile

        candidates, disabled, denied = self._authorized_candidates(
            descriptor,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        if not candidates:
            if not bound:
                raise ConnectorBindingError(
                    f"Connector '{descriptor.connector_id}' has no ConnectionManager binding."
                )
            if disabled and not denied:
                raise ConnectionDisabledError(
                    f"All bound connections for connector '{descriptor.connector_id}' are disabled."
                )
            raise ConnectionScopeDeniedError(
                f"No bound connection for connector '{descriptor.connector_id}' is authorized in the requested scope."
            )

        best_score = max(self._profile_specificity(profile) for profile in candidates)
        best = [profile for profile in candidates if self._profile_specificity(profile) == best_score]
        if len(best) != 1:
            raise ConnectorAmbiguousBindingError(
                f"Connector '{descriptor.connector_id}' has multiple equally specific authorized connections; choose connection_id explicitly."
            )
        return best[0]

    def get_status(
        self,
        connector_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> ConnectorAuthorityStatus:
        """Return credential-authority status without resolving any secret."""
        descriptor = self._descriptor(connector_id)
        if descriptor.health_status == ConnectorHealthStatus.DISABLED:
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.CONNECTOR_DISABLED,
                detail="Connector descriptor is disabled.",
            )
        if not self._requires_connection(descriptor):
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.LOCAL_AVAILABLE,
                credential_resolved=False,
                detail="Connector requires no external credential binding.",
            )

        try:
            profile = self._select_profile(
                descriptor,
                business_id=business_id,
                project_id=project_id,
                brand_id=brand_id,
                connection_id=connection_id,
            )
        except ConnectorAmbiguousBindingError:
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.AMBIGUOUS_BINDING,
                detail="Multiple equally specific authorized connections exist; explicit selection is required.",
            )
        except ConnectionDisabledError:
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.CONNECTION_DISABLED,
                detail="Bound connection is disabled.",
            )
        except ConnectionScopeDeniedError:
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.SCOPE_DENIED,
                detail="No bound connection is authorized in the requested scope.",
            )
        except ConnectorBindingError:
            return ConnectorAuthorityStatus(
                connector_id=descriptor.connector_id,
                provider=descriptor.provider,
                state=ConnectorAuthorityState.MISSING_BINDING,
                detail="Connector has no ConnectionManager binding for this selection.",
            )

        return ConnectorAuthorityStatus(
            connector_id=descriptor.connector_id,
            provider=descriptor.provider,
            state=ConnectorAuthorityState.CONFIGURED_UNVERIFIED,
            connection_id=profile.connection_id,
            credential_resolved=False,
            detail="Connection metadata is enabled and scope-authorized; credential value has not been resolved.",
        )

    def resolve_for_execution(
        self,
        connector_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> ResolvedConnectorAccess:
        """Resolve credential material only at the explicit execution boundary.

        This method does not execute the connector. Consequential actions must
        still travel through Dynamic ToolGateway/approval/receipt controls.
        """
        descriptor = self._descriptor(connector_id)
        if descriptor.health_status == ConnectorHealthStatus.DISABLED:
            raise ConnectorControlPlaneError(
                f"Connector '{descriptor.connector_id}' is disabled."
            )
        if not self._requires_connection(descriptor):
            return ResolvedConnectorAccess(
                descriptor=descriptor,
                connection=None,
                local_no_auth=True,
            )

        profile = self._select_profile(
            descriptor,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
            connection_id=connection_id,
        )
        resolved = self.connection_manager.resolve(
            profile.connection_id,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        return ResolvedConnectorAccess(
            descriptor=descriptor,
            connection=resolved,
            local_no_auth=False,
        )
