"""Provider-neutral connection profiles and secret resolution.

This package intentionally does not integrate with the five agents yet. It is a
shared platform primitive that keeps connection metadata separate from secret
material and reuses the repository's authoritative SecureSecretStore.
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
    SecretNotFoundError,
    SecretProvider,
    SecretProviderError,
    SecretValue,
    SecureStoreSecretProvider,
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
    "ResolvedConnection",
    "SecretNotFoundError",
    "SecretProvider",
    "SecretProviderError",
    "SecretValue",
    "SecureStoreSecretProvider",
    "UnsafeConnectionProfileError",
    "UnsupportedSecretReferenceError",
]
