"""Provider-neutral connection profiles and secret resolution.

This package intentionally does not integrate with the five agents yet. It is a
shared platform primitive that keeps connection metadata separate from secret
material.
"""

from connections.manager import ConnectionManager, ResolvedConnection
from connections.models import ConnectionProfile
from connections.secrets import (
    EnvironmentSecretProvider,
    InMemorySecretProvider,
    SecretNotFoundError,
    SecretProvider,
    SecretValue,
)

__all__ = [
    "ConnectionManager",
    "ConnectionProfile",
    "EnvironmentSecretProvider",
    "InMemorySecretProvider",
    "ResolvedConnection",
    "SecretNotFoundError",
    "SecretProvider",
    "SecretValue",
]
