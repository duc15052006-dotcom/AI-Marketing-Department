"""Provider-neutral connection profiles and secret resolution.

This package intentionally does not integrate with the five agents yet. It is a
shared platform primitive that keeps connection metadata separate from secret
material.
"""

from connections.manager import (
    ConnectionAlreadyExistsError,
    ConnectionDisabledError,
    ConnectionManager,
    ConnectionNotFoundError,
    ConnectionScopeDeniedError,
    ResolvedConnection,
)
from connections.models import (
    ConnectionProfile,
    ConnectionProfileError,
    UnsafeConnectionProfileError,
)
from connections.secrets import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    InMemorySecretProvider,
    SecretNotFoundError,
    SecretProvider,
    SecretProviderError,
    SecretValue,
    UnsupportedSecretReferenceError,
)

__all__ = [
    "CompositeSecretProvider",
    "ConnectionAlreadyExistsError",
    "ConnectionDisabledError",
    "ConnectionManager",
    "ConnectionNotFoundError",
    "ConnectionProfile",
    "ConnectionProfileError",
    "ConnectionScopeDeniedError",
    "EnvironmentSecretProvider",
    "InMemorySecretProvider",
    "ResolvedConnection",
    "SecretNotFoundError",
    "SecretProvider",
    "SecretProviderError",
    "SecretValue",
    "UnsafeConnectionProfileError",
    "UnsupportedSecretReferenceError",
]
