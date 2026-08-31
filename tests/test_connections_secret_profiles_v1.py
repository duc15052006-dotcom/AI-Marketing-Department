from __future__ import annotations

import unittest

from connections.manager import (
    ConnectionAlreadyExistsError,
    ConnectionDisabledError,
    ConnectionManager,
    ConnectionScopeDeniedError,
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
    SecretProviderError,
    SecretValue,
)


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return True

    def get(self, secret_ref: str) -> SecretValue:
        self.calls += 1
        return SecretValue("TOP-SECRET")


class ConnectionsSecretProfilesV1Tests(unittest.TestCase):
    def _profile(self, **updates):
        data = {
            "connection_id": "conn-openai-brand-a",
            "provider": "openai",
            "display_name": "Brand A OpenAI",
            "secret_ref": "memory:openai-brand-a",
            "endpoint": "https://api.example.test/v1",
            "business_id": "biz-1",
            "project_ids": ("project-1",),
            "brand_ids": ("brand-a",),
            "metadata": {"region": "global", "labels": ["marketing", "ai"]},
        }
        data.update(updates)
        return ConnectionProfile(**data)

    def test_profile_contains_reference_not_plaintext_secret(self):
        raw_secret = "sk-test-super-secret-value"
        provider = InMemorySecretProvider({"memory:openai-brand-a": raw_secret})
        manager = ConnectionManager(provider)
        profile = self._profile()
        manager.register(profile)

        serialized = repr(profile.to_safe_dict())
        self.assertNotIn(raw_secret, serialized)
        self.assertNotIn(raw_secret, repr(profile))

        resolved = manager.resolve(
            profile.connection_id,
            business_id="biz-1",
            project_id="project-1",
            brand_id="brand-a",
        )
        self.assertEqual(resolved.secret.reveal(), raw_secret)
        self.assertNotIn(raw_secret, repr(resolved))
        self.assertNotIn(raw_secret, str(resolved.secret))
        self.assertNotIn(raw_secret, repr(resolved.secret))

    def test_raw_secret_reference_is_rejected(self):
        with self.assertRaises(ConnectionProfileError):
            self._profile(secret_ref="sk-test-super-secret-value")

    def test_secret_shaped_metadata_is_rejected_recursively(self):
        for metadata in (
            {"api_key": "raw"},
            {"auth": {"access-token": "raw"}},
            {"nested": [{"client secret": "raw"}]},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(UnsafeConnectionProfileError):
                    self._profile(metadata=metadata)

    def test_endpoint_embedded_credentials_are_rejected(self):
        with self.assertRaises(UnsafeConnectionProfileError):
            self._profile(endpoint="https://user:password@example.test/v1")
        with self.assertRaises(UnsafeConnectionProfileError):
            self._profile(endpoint="https://example.test/v1?access_token=raw")

    def test_metadata_is_immutable_after_validation(self):
        profile = self._profile(metadata={"nested": {"region": "global"}})
        with self.assertRaises(TypeError):
            profile.metadata["api_key"] = "raw"
        with self.assertRaises(TypeError):
            profile.metadata["nested"]["api_key"] = "raw"

    def test_disabled_connection_fails_before_secret_resolution(self):
        provider = _CountingProvider()
        manager = ConnectionManager(provider)
        manager.register(self._profile(enabled=False))
        with self.assertRaises(ConnectionDisabledError):
            manager.resolve(
                "conn-openai-brand-a",
                business_id="biz-1",
                project_id="project-1",
                brand_id="brand-a",
            )
        self.assertEqual(provider.calls, 0)

    def test_scope_denial_fails_before_secret_resolution(self):
        provider = _CountingProvider()
        manager = ConnectionManager(provider)
        manager.register(self._profile())

        denied_contexts = (
            {"business_id": "biz-other", "project_id": "project-1", "brand_id": "brand-a"},
            {"business_id": "biz-1", "project_id": "project-other", "brand_id": "brand-a"},
            {"business_id": "biz-1", "project_id": "project-1", "brand_id": "brand-other"},
            {"business_id": None, "project_id": "project-1", "brand_id": "brand-a"},
            {"business_id": "biz-1", "project_id": None, "brand_id": "brand-a"},
            {"business_id": "biz-1", "project_id": "project-1", "brand_id": None},
        )
        for context in denied_contexts:
            with self.subTest(context=context):
                with self.assertRaises(ConnectionScopeDeniedError):
                    manager.resolve("conn-openai-brand-a", **context)
        self.assertEqual(provider.calls, 0)

    def test_duplicate_registration_requires_explicit_replace(self):
        manager = ConnectionManager(_CountingProvider())
        manager.register(self._profile())
        with self.assertRaises(ConnectionAlreadyExistsError):
            manager.register(self._profile(display_name="replacement"))
        replaced = manager.register(self._profile(display_name="replacement"), replace=True)
        self.assertEqual(replaced.display_name, "replacement")

    def test_environment_provider_is_read_only_resolution(self):
        provider = EnvironmentSecretProvider({"TEST_SERVICE_TOKEN": "env-secret-value"})
        secret = provider.get("env:TEST_SERVICE_TOKEN")
        self.assertEqual(secret.reveal(), "env-secret-value")
        self.assertEqual(str(secret), "***")
        with self.assertRaises(SecretNotFoundError):
            provider.get("env:MISSING")

    def test_composite_provider_routes_and_rejects_ambiguity(self):
        env = EnvironmentSecretProvider({"TOKEN": "env-value"})
        memory = InMemorySecretProvider({"memory:token": "memory-value"})
        composite = CompositeSecretProvider([env, memory])
        self.assertEqual(composite.get("env:TOKEN").reveal(), "env-value")
        self.assertEqual(composite.get("memory:token").reveal(), "memory-value")

        class _DuplicateEnvProvider:
            def can_resolve(self, secret_ref: str) -> bool:
                return secret_ref.startswith("env:")

            def get(self, secret_ref: str) -> SecretValue:
                return SecretValue("duplicate")

        ambiguous = CompositeSecretProvider([env, _DuplicateEnvProvider()])
        with self.assertRaises(SecretProviderError):
            ambiguous.get("env:TOKEN")


if __name__ == "__main__":
    unittest.main()
