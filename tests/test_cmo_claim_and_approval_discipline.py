"""Unit Tests for CMO Claim Resurrection & External Approval Consistency (Phase 3D.5.1).

Validates:
- Rejected upstream claims (drop-in compatibility, air-gapped, seamless, etc.) cannot reappear downstream
- Inherited claim constraint registry exists and enforces alternatives
- DESIGN_APPROVED does not grant live external execution authority
- NO_PAID_SPEND_REQUIRED != NO_APPROVAL_REQUIRED (zero-cost external actions require human approval)
- 'Launch' or 'deploy' cannot appear as authorized actions while approval is pending
- CMO decisions explicitly separate INTERNAL_GO, DESIGN_APPROVED, and READY_FOR_HUMAN_APPROVAL
- All corrected CMO artifacts pass governance and claim discipline checks
"""

import json
from pathlib import Path
import unittest
from evaluations.patch_cmo_governance_discipline import audit_cmo_text_for_discipline


class TestCMOClaimAndApprovalDiscipline(unittest.TestCase):
    def setUp(self):
        self.cmo_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_cmo"

    def test_rejected_upstream_claims_cannot_reappear_downstream(self):
        """Verify auditor catches resurrected upstream claims like drop-in compatibility and air-gapped."""
        text_invalid = "Ollama provides localhost:11434 drop-in integration and air-gapped execution."
        text_valid = "Ollama provides localhost:11434 REST API integration and local/offline model execution."

        issues_invalid = audit_cmo_text_for_discipline(text_invalid)
        issues_valid = audit_cmo_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "REJECTED_UPSTREAM_CLAIM_RESURRECTED" and "drop-in integration" in iss[1] for iss in issues_invalid))
        self.assertTrue(any(iss[0] == "REJECTED_UPSTREAM_CLAIM_RESURRECTED" and "air-gapped" in iss[1] for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "REJECTED_UPSTREAM_CLAIM_RESURRECTED" for iss in issues_valid))

    def test_inherited_claim_constraints_registry_exists_and_complete(self):
        """Verify inherited claim constraint registry exists and covers all required terms."""
        registry_path = self.cmo_dir / "inherited_claim_constraints.json"
        self.assertTrue(registry_path.exists())

        reg_data = json.loads(registry_path.read_text(encoding="utf-8"))
        terms = [c.get("term", "") for c in reg_data.get("constraints", [])]
        term_str = " ".join(terms).lower()

        self.assertIn("fastest", term_str)
        self.assertIn("friction-free", term_str)
        self.assertIn("zero data leakage", term_str)
        self.assertIn("air-gapped", term_str)
        self.assertIn("infinite iteration", term_str)
        self.assertIn("seamless", term_str)
        self.assertIn("immediate conversion velocity", term_str)
        self.assertIn("drop-in compatibility", term_str)

    def test_design_approved_does_not_imply_live_execution(self):
        """Verify DESIGN_APPROVED does not grant live external execution authority."""
        approval_path = self.cmo_dir / "approval_register.json"
        self.assertTrue(approval_path.exists())

        app_data = json.loads(approval_path.read_text(encoding="utf-8"))
        approvals = app_data.get("approvals", [])

        for app in approvals:
            self.assertFalse(app.get("live_execution_permitted", True))

    def test_zero_cost_external_action_requires_approval(self):
        """Verify NO_PAID_SPEND_REQUIRED != NO_APPROVAL_REQUIRED is explicitly enforced."""
        approval_path = self.cmo_dir / "approval_register.json"
        self.assertTrue(approval_path.exists())

        app_data = json.loads(approval_path.read_text(encoding="utf-8"))
        principles = " ".join(app_data.get("governance_principles", []))

        self.assertIn("NO_PAID_SPEND_REQUIRED != NO_APPROVAL_REQUIRED", principles)

    def test_launch_or_deploy_wording_cannot_appear_when_approval_pending(self):
        """Verify action plan and priority plan use 'prepare' rather than authorized 'launch/deploy'."""
        plan_path = self.cmo_dir / "department_action_plan.json"
        pri_path = self.cmo_dir / "priority_plan.json"
        self.assertTrue(plan_path.exists())
        self.assertTrue(pri_path.exists())

        plan_text = plan_path.read_text(encoding="utf-8")
        pri_text = pri_path.read_text(encoding="utf-8")

        issues_plan = audit_cmo_text_for_discipline(plan_text)
        issues_pri = audit_cmo_text_for_discipline(pri_text)

        self.assertEqual(len(issues_plan), 0, f"Issues in department_action_plan.json: {issues_plan}")
        self.assertEqual(len(issues_pri), 0, f"Issues in priority_plan.json: {issues_pri}")

    def test_cmo_decisions_separate_internal_go_and_ready_for_human_approval(self):
        """Verify decision register explicitly distinguishes INTERNAL_GO, DESIGN_APPROVED, and READY_FOR_HUMAN_APPROVAL."""
        dec_path = self.cmo_dir / "decision_register.json"
        self.assertTrue(dec_path.exists())

        dec_data = json.loads(dec_path.read_text(encoding="utf-8"))
        for d in dec_data:
            status = d.get("status", "")
            req_app = d.get("required_approval", "")
            if "GO" in status:
                self.assertIn("INTERNAL_GO", status)
                self.assertIn("DESIGN_APPROVED", status)
            if "TEST" in status:
                self.assertIn("READY_FOR_HUMAN_APPROVAL", status)

    def test_all_corrected_cmo_artifacts_pass_discipline_rules(self):
        """Verify all corrected CMO artifacts pass discipline checks with 0 remaining issues."""
        files_to_check = [
            "executive_summary.json",
            "decision_register.json",
            "priority_plan.json",
            "department_action_plan.json",
            "risk_register.json",
            "approval_register.json",
            "contradiction_register.json",
            "department_status.json",
        ]

        for fname in files_to_check:
            fpath = self.cmo_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                issues = audit_cmo_text_for_discipline(content)
                self.assertEqual(len(issues), 0, f"Discipline issues found in {fname}: {issues}")


if __name__ == "__main__":
    unittest.main()
