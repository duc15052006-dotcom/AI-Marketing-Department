"""Secret resolution abstractions for connection profiles.

No production secret is persisted by this module. Environment-backed resolution
is read-only; the in-memory provider exists for tests and ephemeral runtime use.
"""

from __future__ import annotations

import os
from typing import Dict, Mapping, Optional, Protocol, Sequence


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
    """Provider contract for resolving an opaque secret reference."""

    def can_resolve(self, secret_ref: str) -> bool:
        ...

    def get(self, secret_ref: str) -> SecretValue:
        ...


class EnvironmentSecretProvider:
    """Read-only provider for ``env:VARIABLE_NAME`` references."""

    prefix = "env:"

    def __init__(self, environ: Optional[Mapping[str, str]] = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def can_resolve(self, secret_ref: str) -> bool:
        return isinstance(secret_ref, str) and secret_ref.startswith(self.prefix)

    def get(self, secret_ref: str) -> SecretValue:
        if not self.can_resolve(secret_ref):
            raise UnsupportedSecretReferenceError("EnvironmentSecretProvider only accepts env: references.")
        variable_name = secret_ref[len(self.prefix):]
        if not variable_name:
            raise SecretNotFoundError("Environment secret reference is missing a variable name.")
        value = self._environ.get(variable_name)
        if not value:
            raise SecretNotFoundError(f"Secret reference '{secret_ref}' could not be resolved.")
        return SecretValue(value)


class InMemorySecretProvider:
    """Ephemeral provider for tests/local composition; never persists values."""

    prefix = "memory:"

    def __init__(self, values: Optional[Mapping[str, str]] = None) -> None:
        self._values: Dict[str, str] = {}
        for ref, value in (values or {}).items():
            self.set(ref, value)

    def can_resolve(self, secret_ref: str) -> bool:
        return isinstance(secret_ref, str) and secret_ref.startswith(self.prefix)

    def set(self, secret_ref: str, value: str) -> None:
        if not self.can_resolve(secret_ref) or not secret_ref[len(self.prefix):]:
            raise UnsupportedSecretReferenceError("InMemorySecretProvider requires memory:<name> references.")
        if not isinstance(value, str) or not value:
            raise ValueError("Secret value must be a non-empty string.")
        self._values[secret_ref] = value

    def delete(self, secret_ref: str) -> None:
        self._values.pop(secret_ref, None)

    def get(self, secret_ref: str) -> SecretValue:
        if not self.can_resolve(secret_ref):
            raise UnsupportedSecretReferenceError("InMemorySecretProvider only accepts memory: references.")
        value = self._values.get(secret_ref)
        if not value:
            raise SecretNotFoundError(f"Secret reference '{secret_ref}' could not be resolved.")
        return SecretValue(value)


class CompositeSecretProvider:
    """Route a secret reference to exactly one scheme-aware provider."""

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
