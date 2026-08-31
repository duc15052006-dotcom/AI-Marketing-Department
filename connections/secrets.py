"""Secret resolution adapters for connection profiles.

Connections does not own a second credential vault. Production resolution is
adapted to the repository's existing ``SecureSecretStore`` authority, which
already provides Windows DPAPI persistence, opaque versioned ``STORE:`` refs,
``ENV:`` refs, and fail-closed behavior.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from integrations.models.secret_store import GLOBAL_SECRET_STORE


class SecretProviderError(RuntimeError):
    """Base class for safe secret-provider failures."""


class SecretNotFoundError(SecretProviderError):
    """Raised when a referenced secret cannot be resolved."""


class UnsupportedSecretReferenceError(SecretProviderError):
    """Raised when no configured provider owns a secret reference scheme."""


class SecretValue:
    """Small wrapper that prevents accidental plaintext logging/repr output."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise SecretNotFoundError("Secret value is empty or unavailable.")
        self._value = value

    def reveal(self) -> str:
        """Explicit execution-boundary access to the plaintext secret."""
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(***)"

    def __str__(self) -> str:
        return "***"


class SecretProvider(Protocol):
    """Connection-facing provider contract for resolving opaque references."""

    def can_resolve(self, secret_ref: str) -> bool:
        ...

    def get(self, secret_ref: str) -> SecretValue:
        ...


class SecureStoreSecretProvider:
    """Adapter over the repository's authoritative SecureSecretStore interface.

    The wrapped store may be ``GLOBAL_SECRET_STORE`` in production or the
    existing ``InMemorySecretStore`` test double under explicit dependency
    injection. This class never persists credentials itself.
    """

    _SUPPORTED_PREFIXES = ("STORE:", "ENV:")

    def __init__(self, secret_store=None) -> None:
        self._secret_store = secret_store if secret_store is not None else GLOBAL_SECRET_STORE

    def can_resolve(self, secret_ref: str) -> bool:
        if not isinstance(secret_ref, str):
            return False
        ref = secret_ref.strip()
        return any(ref.startswith(prefix) and len(ref) > len(prefix) for prefix in self._SUPPORTED_PREFIXES)

    def get(self, secret_ref: str) -> SecretValue:
        if not self.can_resolve(secret_ref):
            raise UnsupportedSecretReferenceError(
                "SecureStoreSecretProvider only accepts canonical STORE: or ENV: references."
            )
        value = self._secret_store.get_secret(secret_ref.strip())
        if not value:
            raise SecretNotFoundError(f"Secret reference '{secret_ref}' could not be resolved.")
        return SecretValue(value)


class CompositeSecretProvider:
    """Route a secret reference to exactly one configured provider.

    This is an extension point for future OS/keyring/vault integrations without
    changing ConnectionManager. It does not introduce another persistence
    authority by itself.
    """

    def __init__(self, providers: Sequence[SecretProvider]) -> None:
        self._providers = tuple(providers)

    def can_resolve(self, secret_ref: str) -> bool:
        return any(provider.can_resolve(secret_ref) for provider in self._providers)

    def get(self, secret_ref: str) -> SecretValue:
        matches = [provider for provider in self._providers if provider.can_resolve(secret_ref)]
        if not matches:
            raise UnsupportedSecretReferenceError(f"No SecretProvider is configured for reference '{secret_ref}'.")
        if len(matches) > 1:
            raise SecretProviderError(f"Multiple SecretProviders claim reference '{secret_ref}'; refusing ambiguous resolution.")
        return matches[0].get(secret_ref)
