"""Regression coverage for cold-import governance/model circular dependency."""

from __future__ import annotations

import subprocess
import sys
import unittest


class TestGovernanceImportCycle11(unittest.TestCase):
    def _run_cold_import(self, statement: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", statement],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_model_base_can_be_first_import_in_fresh_interpreter(self) -> None:
        result = self._run_cold_import(
            "from integrations.models.base import BaseModelAdapter; print(BaseModelAdapter.__name__)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BaseModelAdapter", result.stdout)
        self.assertNotIn("partially initialized module", result.stderr)

    def test_governance_runtime_exports_remain_backward_compatible(self) -> None:
        result = self._run_cold_import(
            "from governance import GovernedExecutionPipeline, PreHandoffAuditReport; "
            "print(GovernedExecutionPipeline.__name__, PreHandoffAuditReport.__name__)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GovernedExecutionPipeline", result.stdout)
        self.assertIn("PreHandoffAuditReport", result.stdout)

    def test_redaction_submodule_can_be_imported_without_loading_runtime_engine(self) -> None:
        result = self._run_cold_import(
            "import sys; from governance.redaction import sanitize_sensitive_text; "
            "assert 'governance.runtime_engine' not in sys.modules; "
            "print(sanitize_sensitive_text('Bearer secret-token'))"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[REDACTED_TOKEN]", result.stdout)


if __name__ == "__main__":
    unittest.main()
