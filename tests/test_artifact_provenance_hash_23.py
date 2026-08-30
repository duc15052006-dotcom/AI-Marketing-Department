from datetime import datetime, timezone
import unittest

from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeStatus


class ArtifactProvenanceHash23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)
        self.base = {
            "knowledge_used": ["DOC-001"],
            "memory_used": ["MEM-001"],
            "capabilities_used": ["web_search"],
            "artifacts": ["artifact://creative/001"],
            "lineage_summary": {"citations": ["CIT-001"]},
        }

    def _artifact(self, **overrides):
        data = dict(self.base)
        data.update(overrides)
        return DepartmentRunArtifact(
            run_id="RUN-PROVENANCE-HASH-23",
            objective="Seal provenance references",
            started_at=self.now,
            completed_at=self.now,
            status=RuntimeStatus.COMPLETED,
            **data,
        )

    def test_each_provenance_field_mutation_changes_artifact_hash(self):
        original = self._artifact()
        mutations = {
            "knowledge_used": ["DOC-TAMPERED"],
            "memory_used": ["MEM-TAMPERED"],
            "capabilities_used": ["social_publishing"],
            "artifacts": ["artifact://creative/tampered"],
            "lineage_summary": {"citations": ["CIT-TAMPERED"]},
        }

        for field_name, mutated_value in mutations.items():
            with self.subTest(field=field_name):
                tampered = self._artifact(**{field_name: mutated_value})
                self.assertNotEqual(
                    original.compute_artifact_hash(),
                    tampered.compute_artifact_hash(),
                    f"{field_name} must be inside the authoritative artifact integrity boundary.",
                )

    def test_equivalent_provenance_is_deterministic(self):
        first = self._artifact(lineage_summary={"b": 2, "a": 1})
        second = self._artifact(lineage_summary={"a": 1, "b": 2})
        self.assertEqual(first.compute_artifact_hash(), second.compute_artifact_hash())


if __name__ == "__main__":
    unittest.main()
