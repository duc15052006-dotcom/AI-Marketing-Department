"""Regression tests for provider-neutral ResourceLimiter authority.

The runtime limiter must not infer concurrency policy from provider names.
Provider-specific limits are allowed only through explicit configuration.
"""

from __future__ import annotations

import unittest

from runtime.queue import ResourceLimiter


class TestResourceLimiterAuthorityV1(unittest.TestCase):
    def test_provider_names_do_not_select_implicit_concurrency_policy(self) -> None:
        limiter = ResourceLimiter(default_max_concurrent_calls=1)
        provider_ids = ("xkiro", "gemini", "web", "analytics", "custom_provider")

        for provider_id in provider_ids:
            limiter.register_provider(provider_id)

        states = limiter.get_provider_states()
        for provider_id in provider_ids:
            self.assertEqual(
                states[provider_id]["max_concurrent_calls"],
                1,
                msg=f"provider name '{provider_id}' must not imply a hidden concurrency policy",
            )

    def test_explicit_provider_limit_remains_authoritative(self) -> None:
        limiter = ResourceLimiter(default_max_concurrent_calls=1)
        limiter.register_provider("xkiro")
        limiter.register_provider("custom_provider")

        limiter.set_provider_limit("xkiro", 7)

        states = limiter.get_provider_states()
        self.assertEqual(states["xkiro"]["max_concurrent_calls"], 7)
        self.assertEqual(states["custom_provider"]["max_concurrent_calls"], 1)


if __name__ == "__main__":
    unittest.main()
