# Connections / Secret Profiles v1

This package separates safe connection metadata from credential material.

## Boundary

- `ConnectionProfile` may be persisted or listed in UI because it contains only metadata and an opaque `secret_ref`.
- Connections does **not** create another production credential vault.
- `SecureStoreSecretProvider` adapts the existing `integrations.models.secret_store.SecureSecretStore` authority used by Model Settings.
- Actual credentials are resolved only after enabled and business/project/brand scope checks pass.
- `SecretValue` redacts `str()` and `repr()` and requires explicit `reveal()` at the execution boundary.
- The existing `InMemorySecretStore` remains the explicit dependency-injection test double; Connections does not replace it.
- No five-agent or Dynamic Tool Gateway integration is performed in this batch.

## Supported authoritative reference shapes

- `STORE:<credential-id>:<version>` for the existing versioned secure store
- `ENV:OPENAI_API_KEY` for the existing environment-reference path

`CompositeSecretProvider` remains only an extension/routing point for a future OS keyring or external vault adapter; it stores nothing itself.

Never place API keys, access tokens, refresh tokens, passwords, private keys, client secrets, or request query parameters inside profile metadata or endpoint URLs.
