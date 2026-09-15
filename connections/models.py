"""Safe, serializable metadata for external service connections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit


class ConnectionProfileError(ValueError):
    """Base error for invalid connection profile metadata."""


class UnsafeConnectionProfileError(ConnectionProfileError):
    """Raised when a profile appears to contain raw secret material."""


_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "passwd",
    "authorization",
    "bearer",
    "private_key",
    "secret_key",
    "secret_value",
    "credential",
    "token",
    "secret",
)
_SECRET_REF_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*:[^\s:][^\s]*$", re.IGNORECASE)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _validate_public_metadata(value: Any, path: str = "metadata") -> None:
    """Reject secret-shaped fields recursively before they can enter a profile."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _is_sensitive_key(key):
                raise UnsafeConnectionProfileError(
                    f"Raw credential field '{path}.{key}' is not allowed; store it in a SecretProvider and keep only secret_ref."
                )
            _validate_public_metadata(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            _validate_public_metadata(child, f"{path}[{index}]")


def _freeze_public_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_public_metadata(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_public_metadata(child) for child in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_public_metadata(child) for child in value)
    return value


def _thaw_public_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_public_metadata(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_public_metadata(child) for child in value]
    if isinstance(value, frozenset):
        return sorted((_thaw_public_metadata(child) for child in value), key=repr)
    return value


def _validate_endpoint(endpoint: Optional[str]) -> None:
    if endpoint is None or not endpoint.strip():
        return
    parsed = urlsplit(endpoint)
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeConnectionProfileError("Endpoint must not embed username/password credentials.")
    if parsed.query or parsed.fragment:
        raise UnsafeConnectionProfileError(
            "Connection endpoint must be a base endpoint without query parameters or fragments; request parameters belong at execution time."
        )


@dataclass(frozen=True)
class ConnectionProfile:
    """Non-secret connection metadata safe for persistence, logs, and UI lists.

    ``secret_ref`` is an opaque, scheme-based locator such as
    ``env:OPENAI_API_KEY`` or ``keyring:brand/openai``. It must never be the
    credential value itself.
    """

    connection_id: str
    provider: str
    display_name: str
    secret_ref: str
    endpoint: Optional[str] = None
    enabled: bool = True
    business_id: Optional[str] = None
    project_ids: Tuple[str, ...] = ()
    brand_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("connection_id", "provider", "display_name", "secret_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ConnectionProfileError(f"{field_name} must be a non-empty string.")

        if not _SECRET_REF_PATTERN.fullmatch(self.secret_ref):
            raise ConnectionProfileError(
                "secret_ref must be a scheme-based locator such as env:OPENAI_API_KEY; raw credentials are not accepted."
            )

        _validate_endpoint(self.endpoint)
        _validate_public_metadata(self.metadata)

        object.__setattr__(self, "project_ids", tuple(dict.fromkeys(self.project_ids)))
        object.__setattr__(self, "brand_ids", tuple(dict.fromkeys(self.brand_ids)))
        object.__setattr__(self, "metadata", _freeze_public_metadata(dict(self.metadata)))

    def with_updates(self, **updates: Any) -> "ConnectionProfile":
        """Return a validated replacement profile."""
        return replace(self, **updates)

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize profile metadata without resolving or exposing any secret."""
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "secret_ref": self.secret_ref,
            "endpoint": self.endpoint,
            "enabled": self.enabled,
            "business_id": self.business_id,
            "project_ids": list(self.project_ids),
            "brand_ids": list(self.brand_ids),
            "metadata": _thaw_public_metadata(self.metadata),
        }

    def __repr__(self) -> str:
        return (
            "ConnectionProfile("
            f"connection_id={self.connection_id!r}, provider={self.provider!r}, "
            f"display_name={self.display_name!r}, secret_ref={self.secret_ref!r}, "
            f"endpoint={self.endpoint!r}, enabled={self.enabled!r}, "
            f"business_id={self.business_id!r}, project_ids={self.project_ids!r}, "
            f"brand_ids={self.brand_ids!r}, metadata_keys={tuple(self.metadata.keys())!r})"
        )
