"""Adversarial regression for observed-URL provenance credential persistence."""

import tempfile
import unittest
from pathlib import Path

from knowledge.file_manager import KnowledgeFileManager


class KnowledgeObservedUrlProvenanceSecretsV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.manager = KnowledgeFileManager(Path(self.tempdir.name))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _stored_locator(self, url: str) -> str:
        result = self.manager.ingest_observed_url(
            url,
            "Observed customer discussion content with enough detail.",
            source_name="observed-research",
        )
        self.assertTrue(result.success)
        document = self.manager.repository.get_document(result.knowledge_id or "")
        self.assertIsNotNone(document)
        source = self.manager.repository.get_source(document.source_id)
        self.assertIsNotNone(source)
        return source.source_url_or_path

    def test_observed_url_provenance_strips_userinfo_and_query_secrets(self) -> None:
        locator = self._stored_locator(
            "https://alice:supersecret@example.com/research"
            "?api_key=query-secret-999&topic=decor&token=token-secret-888#section"
        )

        self.assertNotIn("alice", locator)
        self.assertNotIn("supersecret", locator)
        self.assertNotIn("query-secret-999", locator)
        self.assertNotIn("token-secret-888", locator)
        self.assertIn("https://example.com/research", locator)
        self.assertIn("topic=decor", locator)
        self.assertIn("api_key=[REDACTED]", locator)
        self.assertIn("token=[REDACTED]", locator)
        self.assertTrue(locator.endswith("#section"))

    def test_benign_observed_url_provenance_is_preserved(self) -> None:
        url = "https://example.com/research?topic=decor&page=2#results"
        self.assertEqual(self._stored_locator(url), url)


if __name__ == "__main__":
    unittest.main()
