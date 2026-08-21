"""Unit Tests for Creative Claim Discipline & Deterministic Patch Rules (Phase 3D.3.1).

Validates:
- UNSUPPORTED_AIRGAP_CLAIM is detected on 'air-gapped'
- UNSUPPORTED_CONVERSION_LANGUAGE is detected on 'conversion velocity'
- UNSUPPORTED_ECONOMIC_ABSOLUTE is detected on 'infinite iteration'
- UNSUPPORTED_QUALITY_ADJECTIVE is detected on 'seamless'
- UNSUPPORTED_COMPATIBILITY_FEATURE is detected on unsupported OpenAI SDK 1-line redirection
- Corrected creative artifacts pass all discipline rules
- Performance handoff preserves all unknown baseline gaps
"""

import json
from pathlib import Path
import unittest
from evaluations.patch_creative_claim_discipline import audit_text_for_discipline


class TestCreativeClaimDiscipline(unittest.TestCase):
    def test_unsupported_airgap_detected(self):
        """Verify auditor catches ungrounded 'air-gapped' claims."""
        text_invalid = "Demonstrates air-gapped terminal execution."
        text_valid = "Demonstrates local offline terminal execution."

        issues_invalid = audit_text_for_discipline(text_invalid)
        issues_valid = audit_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_AIRGAP_CLAIM" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_AIRGAP_CLAIM" for iss in issues_valid))

    def test_unsupported_conversion_language_detected(self):
        """Verify auditor catches ungrounded 'immediate conversion velocity' assertions."""
        text_invalid = "Offers immediate developer conversion velocity."
        text_valid = "Supports a testable developer onboarding/acquisition hypothesis."

        issues_invalid = audit_text_for_discipline(text_invalid)
        issues_valid = audit_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_CONVERSION_LANGUAGE" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_CONVERSION_LANGUAGE" for iss in issues_valid))

    def test_unsupported_economic_absolute_detected(self):
        """Verify auditor catches 'infinite iteration' claims."""
        text_invalid = "Predictable Zero-Token Cost for Infinite Local Iteration"
        text_valid = "Predictable Zero-Token Cost for Local Prompt Iteration without Per-Request Hosted API Charges"

        issues_invalid = audit_text_for_discipline(text_invalid)
        issues_valid = audit_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_ECONOMIC_ABSOLUTE" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_ECONOMIC_ABSOLUTE" for iss in issues_valid))

    def test_unsupported_quality_adjective_detected(self):
        """Verify auditor catches unproven 'seamless' quality adjectives."""
        text_invalid = "Shows pulling and switching model tags seamlessly."
        text_valid = "Shows pulling and switching model tags in local CLI workflow."

        issues_invalid = audit_text_for_discipline(text_invalid)
        issues_valid = audit_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_QUALITY_ADJECTIVE" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_QUALITY_ADJECTIVE" for iss in issues_valid))

    def test_unsupported_compatibility_feature_detected(self):
        """Verify auditor catches unsupported OpenAI SDK 1-line redirection claims."""
        text_invalid = "How to point your existing OpenAI Python SDK script to a free local endpoint in 1 line."
        text_valid = "How to connect your Python scripts to a local model endpoint on localhost:11434 with standard HTTP requests."

        issues_invalid = audit_text_for_discipline(text_invalid)
        issues_valid = audit_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_COMPATIBILITY_FEATURE" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_COMPATIBILITY_FEATURE" for iss in issues_valid))

    def test_corrected_artifacts_pass_all_discipline_rules(self):
        """Verify that all corrected creative artifacts in evaluations/live/grounded_creative/ pass cleanly."""
        creative_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_creative"
        files_to_check = [
            "creative_territories.json",
            "creative_angles.json",
            "creative_hooks.json",
            "creative_copy.json",
            "video_script.json",
            "storyboard.json",
            "shot_list.json",
            "creative_variants.json",
            "creative_claims.json",
            "performance_handoff_candidate.json",
        ]

        for fname in files_to_check:
            fpath = creative_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                issues = audit_text_for_discipline(content)
                self.assertEqual(len(issues), 0, f"Discipline issues found in {fname}: {issues}")

    def test_performance_handoff_preserves_unknown_baselines(self):
        """Verify performance candidate handoff preserves all unknown baseline markers."""
        creative_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_creative"
        perf_path = creative_dir / "performance_handoff_candidate.json"
        self.assertTrue(perf_path.exists())

        data = json.loads(perf_path.read_text(encoding="utf-8"))
        unknown_baselines = data.get("unknown_baselines", [])

        self.assertIn("TRANSACTION_DATA = MISSING", unknown_baselines)
        self.assertIn("REPRESENTATIVE_DEVELOPER_RECEPTION_DATA = MISSING", unknown_baselines)
        self.assertIn("PRIVATE_TELEMETRY_DATA = MISSING", unknown_baselines)


if __name__ == "__main__":
    unittest.main()
