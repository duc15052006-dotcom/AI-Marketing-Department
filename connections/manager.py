"""Connection registry and fail-closed scoped secret resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from connections.models import ConnectionProfile
from connections.secrets import SecretProvider, SecretValue, UnsupportedSecretReferenceError


class ConnectionManagerError(RuntimeError):
    """Base runtime error for connection management."""


class ConnectionAlreadyExistsError(ConnectionManagerError):
    """Raised when duplicate registration is attempted without explicit replace."""


class ConnectionNotFoundError(ConnectionManagerError):
    """Raised when a connection id is unknown."""


class ConnectionDisabledError(ConnectionManagerError):
    """Raised when a disabled connection is requested."""


class ConnectionScopeDeniedError(ConnectionManagerError):
    """Raised when caller context does not match the profile scope."""


@dataclass(frozen=True, repr=False)
class ResolvedConnection:
    """Execution-boundary connection containing a redaction-safe secret wrapper."""

    profile: ConnectionProfile
    secret: SecretValue

    def __repr__(self) -> str:
        return f"ResolvedConnection(profile={self.profile!r}, secret=***)"


class ConnectionManager:
    """Own connection metadata and resolve credentials only after scope checks."""

    def __init__(self, secret_provider: SecretProvider) -> None:
        self._secret_provider = secret_provider
        self._profiles: Dict[str, ConnectionProfile] = {}

    def register(self, profile: ConnectionProfile, *, replace: bool = False) -> ConnectionProfile:
        if not self._secret_provider.can_resolve(profile.secret_ref):
            raise UnsupportedSecretReferenceError(
                f"No configured SecretProvider accepts reference '{profile.secret_ref}'."
            )
        existing = self._profiles.get(profile.connection_id)
        if existing is not None and not replace:
            raise ConnectionAlreadyExistsError(
                f"Connection '{profile.connection_id}' already exists; pass replace=True for an explicit replacement."
            )
        self._profiles[profile.connection_id] = profile
        return profile

    def get(self, connection_id: str) -> ConnectionProfile:
        try:
            return self._profiles[connection_id]
        except KeyError as exc:
            raise ConnectionNotFoundError(f"Connection '{connection_id}' is not registered.") from exc

    def list_profiles(self, *, include_disabled: bool = True) -> List[ConnectionProfile]:
        profiles = list(self._profiles.values())
        if not include_disabled:
            profiles = [profile for profile in profiles if profile.enabled]
        return sorted(profiles, key=lambda profile: profile.connection_id)

    def disable(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id).with_updates(enabled=False)
        self._profiles[connection_id] = profile
        return profile

    def enable(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id).with_updates(enabled=True)
        self._profiles[connection_id] = profile
        return profile

    def remove(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id)
        del self._profiles[connection_id]
        return profile

    @staticmethod
    def _enforce_scope(
        profile: ConnectionProfile,
        *,
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> None:
        if profile.business_id is not None and business_id != profile.business_id:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested business scope."
            )
        if profile.project_ids and project_id not in profile.project_ids:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested project scope."
            )
        if profile.brand_ids and brand_id not in profile.brand_ids:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested brand scope."
            )

    def authorize_profile(
        self,
        connection_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ConnectionProfile:
        """Authorize profile metadata without resolving credential material.

        Health/control-plane code can use this method to enforce the exact same
        enabled/scope policy as ``resolve`` while proving that no SecretProvider
        lookup occurs merely to render status or choose an account.
        """
        profile = self.get(connection_id)
        if not profile.enabled:
            raise ConnectionDisabledError(f"Connection '{connection_id}' is disabled.")
        self._enforce_scope(
            profile,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        return profile

    def resolve(
        self,
        connection_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ResolvedConnection:
        """Resolve a connection after enabled/scope checks, never before them."""
        profile = self.authorize_profile(
            connection_id,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        secret = self._secret_provider.get(profile.secret_ref)
        return ResolvedConnection(profile=profile, secret=secret)
