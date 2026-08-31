# Connections / Secret Profiles v1

This package separates safe connection metadata from credential material.

## Boundary

- `ConnectionProfile` may be persisted or listed in UI because it contains only metadata and an opaque `secret_ref`.
- Actual credentials are resolved through a `SecretProvider` only after enabled and business/project/brand scope checks pass.
- `SecretValue` redacts `str()` and `repr()` and requires explicit `reveal()` at the execution boundary.
- `EnvironmentSecretProvider` is read-only.
- `InMemorySecretProvider` is ephemeral and intended for tests/runtime composition, not persistence.
- No five-agent integration is performed in this batch.

## Example reference shapes

- `env:OPENAI_API_KEY`
- `memory:test-openai-key`
- future providers may use references such as `keyring:brand/openai` or `vault:marketing/openai`

Never place API keys, access tokens, refresh tokens, passwords, private keys, or client secrets inside profile metadata or endpoint URLs.
