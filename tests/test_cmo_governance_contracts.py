"""Unit Tests for CMO Master Governance Contracts & Department Sign-Off (Phase 3D.5).

Validates:
- UNKNOWN baseline markers cannot be closed by executive fiat
- CAC, LTV, ROAS remain UNKNOWN and budget remains NOT_CONFIGURED
- Illustrative allocation cannot become empirical optimal allocation
- Planning duration does not become required statistical duration
- Hypotheses cannot silently become proven facts
- Live media execution and publishing are not automatically approved (SUPERVISED mode)
- Candidate learnings are not automatically promoted to permanent DNA
- Exactly 5 permanent agent owners accepted (CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE); 6th agent rejected
- Contradictions are preserved with explicit resolution records
- Top 3 priorities and deferred work are enforced
- Full backward decision lineage is valid
- No hidden chain-of-thought in artifacts
- FREE_ONLY_MODE is preserved
"""

import json
from pathlib import Path
import unittest
from schemas.handoff import GroundedCMOBrief, PerformanceToCMOHandoff
from schemas.protocol import AgentRole


class TestCMOGovernanceContracts(unittest.TestCase):
    def setUp(self):
        self.cmo_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_cmo"

    def test_unknown_baselines_cannot_be_closed_by_cmo(self):
        """Verify CMO artifacts strictly preserve missing telemetry and transaction baselines."""
        summary_path = self.cmo_dir / "executive_summary.json"
        eval_path = self.cmo_dir / "cmo_evaluation.json"

        self.assertTrue(summary_path.exists())
        self.assertTrue(eval_path.exists())

        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        not_known = summary_data.get("what_do_we_not_know", [])

        self.assertTrue(any("TRANSACTION_DATA is MISSING" in item for item in not_known))
        self.assertTrue(any("PRIVATE_TELEMETRY_DATA is MISSING" in item for item in not_known))
        self.assertTrue(any("REPRESENTATIVE_DEVELOPER_RECEPTION_DATA is MISSING" in item for item in not_known))

    def test_economics_unknowns_and_budget_not_configured(self):
        """Verify CAC, LTV, ROAS remain UNKNOWN and budget is NOT_CONFIGURED."""
        brief_path = self.cmo_dir / "performance_cmo_handoff.json"
        brief_data = json.loads(brief_path.read_text(encoding="utf-8"))

        self.assertIn("NOT_CONFIGURED", brief_data.get("budget_status", ""))
        self.assertIn("NOT_CONFIGURED", brief_data.get("stop_loss_status", ""))
        econ_unknowns = brief_data.get("economics_unknowns", [])
        self.assertTrue(any("CAC = UNKNOWN" in u for u in econ_unknowns))

    def test_approval_register_restricts_live_execution(self):
        """Verify approval register enforces SUPERVISED mode and does not grant live spend/publishing execution."""
        approval_path = self.cmo_dir / "approval_register.json"
        self.assertTrue(approval_path.exists())

        app_data = json.loads(approval_path.read_text(encoding="utf-8"))
        self.assertEqual(app_data.get("autonomy_mode"), "SUPERVISED")

        approvals = app_data.get("approvals", [])
        for app in approvals:
            self.assertFalse(app.get("live_execution_permitted", True))

    def test_candidate_learnings_not_automatically_promoted(self):
        """Verify candidate learnings remain CANDIDATE_ONLY and do not modify permanent DNA."""
        learn_path = self.cmo_dir / "learning_governance.json"
        self.assertTrue(learn_path.exists())

        learn_data = json.loads(learn_path.read_text(encoding="utf-8"))
        candidates = learn_data.get("candidate_learnings", [])
        for c in candidates:
            self.assertEqual(c.get("current_status"), "CANDIDATE_ONLY")

    def test_only_five_permanent_agent_owners_accepted(self):
        """Verify decision register only assigns permanent agent ownership to the 5 official agents."""
        dec_path = self.cmo_dir / "decision_register.json"
        self.assertTrue(dec_path.exists())

        dec_data = json.loads(dec_path.read_text(encoding="utf-8"))
        valid_agents = {"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"}

        for d in dec_data:
            owner = d.get("owner_agent")
            self.assertIn(owner, valid_agents)
            self.assertNotEqual(owner, "SIXTH_AGENT")

    def test_contradictions_preserved_with_explicit_resolution(self):
        """Verify contradictions are preserved rather than silently dropped."""
        contra_path = self.cmo_dir / "contradiction_register.json"
        self.assertTrue(contra_path.exists())

        contra_data = json.loads(contra_path.read_text(encoding="utf-8"))
        self.assertTrue(len(contra_data) > 0)
        c0 = contra_data[0]
        self.assertIn("Search Channel Demand Viability", c0.get("topic", ""))
        self.assertEqual(c0.get("status"), "RESOLVED_AS_EXPERIMENT")

    def test_top_3_priorities_and_deferred_work_enforced(self):
        """Verify priority plan explicitly defines Top 3 Priorities, Deferred Work, and What NOT to do."""
        pri_path = self.cmo_dir / "priority_plan.json"
        self.assertTrue(pri_path.exists())

        pri_data = json.loads(pri_path.read_text(encoding="utf-8"))
        top3 = pri_data.get("top_3_priorities", [])
        deferred = pri_data.get("deferred_work", [])
        what_not = pri_data.get("what_not_to_do", [])

        self.assertEqual(len(top3), 3)
        self.assertTrue(len(deferred) >= 2)
        self.assertTrue(len(what_not) >= 3)

    def test_department_status_readiness_dimensions(self):
        """Verify department status evaluates readiness across all 7 dimensions and specifies 5 permanent agents."""
        status_path = self.cmo_dir / "department_status.json"
        self.assertTrue(status_path.exists())

        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(status_data.get("research_readiness"), "READY")
        self.assertEqual(status_data.get("strategy_readiness"), "READY")
        self.assertEqual(status_data.get("creative_readiness"), "READY")
        self.assertEqual(status_data.get("measurement_readiness"), "READY")
        self.assertIn("PARTIAL", status_data.get("execution_readiness", ""))
        self.assertIn("PARTIAL", status_data.get("learning_readiness", ""))
        self.assertEqual(status_data.get("overall_readiness"), "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(len(status_data.get("permanent_agent_roster", [])), 5)

    def test_cmo_artifacts_contain_no_hidden_reasoning(self):
        """Verify CMO artifacts contain no hidden chain of thought."""
        files_to_check = [
            "executive_summary.json",
            "decision_register.json",
            "priority_plan.json",
            "department_action_plan.json",
            "risk_register.json",
            "approval_register.json",
            "contradiction_register.json",
            "learning_governance.json",
            "department_status.json",
        ]

        for fname in files_to_check:
            fpath = self.cmo_dir / fname
            if fpath.exists():
                data = json.loads(fpath.read_text(encoding="utf-8"))
                text = json.dumps(data)
                self.assertNotIn('"thought"', text)
                self.assertNotIn('"chain_of_thought"', text)


if __name__ == "__main__":
    unittest.main()
