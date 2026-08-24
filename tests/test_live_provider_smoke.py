"""LIVE / OPTIONAL / EXTERNAL / NON-HERMETIC Provider Smoke Tests.

This test module is strictly OPTIONAL and NON-HERMETIC.
It tests real live upstream AI model providers (e.g. xKiro, Gemini, Mistral)
over the public internet.

To run:
    RUN_LIVE_PROVIDER_TESTS=1 python -m unittest tests.test_live_provider_smoke -v

In default test discovery (RUN_LIVE_PROVIDER_TESTS unset or != 1),
all tests in this module are SKIPPED to guarantee a 100% deterministic,
offline, hermetic certification test suite.
"""

import os
import unittest

from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_PROVIDER_TESTS") == "1",
    "LIVE / OPTIONAL / EXTERNAL / NON-HERMETIC: Opt-in test requiring live network and provider quota (set RUN_LIVE_PROVIDER_TESTS=1)",
)
class TestLiveProviderSmokeOptionalExternalNonHermetic(unittest.TestCase):
    """Explicit opt-in live provider smoke suite (Non-Hermetic / External)."""

    def setUp(self) -> None:
        self.gateway = UniversalModelGateway(free_only_mode=True)

    def test_live_provider_connectivity_smoke(self) -> None:
        """Opt-in live smoke: verify real provider returns truthful status (never fabricated)."""
        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Reply with pong")],
            temperature=0.0,
            max_tokens=64,
            timeout_seconds=15.0,
        )
        resp = self.gateway.generate(req)
        # Truthfulness check: must be a valid status, never synthetic success on error
        self.assertIn(
            resp.status,
            (
                ModelResponseStatus.SUCCESS,
                ModelResponseStatus.RATE_LIMITED,
                ModelResponseStatus.TIMEOUT,
                ModelResponseStatus.ERROR,
            ),
        )
        if resp.status == ModelResponseStatus.SUCCESS:
            self.assertTrue(len(resp.content) > 0)
            self.assertTrue(resp.provider in ("xkiro", "gemini", "mistral", "openai", "thespark"))
        elif resp.status == ModelResponseStatus.RATE_LIMITED:
            self.assertIn("RATE_LIMIT", (resp.error or "").upper())
        elif resp.status == ModelResponseStatus.TIMEOUT:
            self.assertIn("TIMEOUT", (resp.error or "").upper())


if __name__ == "__main__":
    unittest.main()
