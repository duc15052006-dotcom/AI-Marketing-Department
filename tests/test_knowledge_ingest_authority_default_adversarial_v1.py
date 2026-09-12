"""Adversarial regression for knowledge-ingest authority defaulting.

The HTTP API must not silently escalate omitted or malformed authority metadata
above the KnowledgeIngestionRequest contract default.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Tuple

from app_api import server as app_server
from app_api.server import APP_BACKEND, DepartmentAPIHandler
from knowledge.models import AuthorityLevel


class KnowledgeIngestAuthorityDefaultAdversarialV1Tests(unittest.TestCase):
    """Protect the API boundary from implicit Tier-1 authority escalation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DepartmentAPIHandler)
        cls.port = int(cls.server.server_address[1])
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5.0)

    def _post(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/knowledge/ingest",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {app_server.GLOBAL_API_SESSION_TOKEN}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_omitted_or_malformed_authority_never_silently_escalates_to_tier1(self) -> None:
        """Missing/invalid API authority must fall back to the ingestion contract's Tier 2."""
        cases = (
            ("omitted", None),
            ("malformed", "ATTACKER_SUPPLIED_NOT_A_REAL_TIER"),
        )

        for label, authority in cases:
            with self.subTest(label=label):
                payload: Dict[str, Any] = {
                    "title": f"Authority boundary {label}",
                    "source_name": f"Authority Boundary {label}",
                    "source_type": "MARKET_RESEARCH",
                    "content": f"Adversarial authority boundary marker: {label}.",
                    "format": "MARKDOWN",
                    "scope": f"SCOPE_AUTHORITY_BOUNDARY_{label.upper()}",
                }
                if authority is not None:
                    payload["authority_level"] = authority

                code, data = self._post(payload)
                self.assertEqual(code, 200)
                self.assertTrue(data["success"])

                document = APP_BACKEND.knowledge_repo.get_document(data["document_id"])
                self.assertIsNotNone(document)
                assert document is not None
                self.assertEqual(
                    document.authority_level,
                    AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                    "API input without a valid explicit authority must not become canonical Tier 1",
                )

                source = APP_BACKEND.knowledge_repo.get_source(document.source_id)
                self.assertIsNotNone(source)
                assert source is not None
                self.assertEqual(source.authority_score, 0.85)


if __name__ == "__main__":
    unittest.main()
