from pathlib import Path
import subprocess
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# Phase 1A: Final CMO is now model call 7 because Performance uses two internal passes.
p = Path('tests/test_phase1a_runtime_integrity.py')
t = p.read_text(encoding='utf-8')
t = replace_once(
    t,
    '            if call_count[0] <= 5:\n                # Stages 1-5 (CMO initial, Intel, Strat, Crtv, Perf) succeed',
    '            if call_count[0] <= 6:\n                # Calls 1-6 succeed: CMO initial, Intelligence, Content, Creative, Performance 5A, Performance 5B',
    'phase1a success-call boundary',
)
t = replace_once(
    t,
    '            # Stage 6 CMO Final fails',
    '            # Call 7 / Stage 6 Final CMO fails',
    'phase1a final-cmo comment',
)
p.write_text(t, encoding='utf-8')

# Phase 1B: six logical stages now produce seven model requests because Performance is 5A + 5B.
p = Path('tests/test_phase1b_grounded_context.py')
t = p.read_text(encoding='utf-8')
t = t.replace('Model request forensics across all 6 stages', 'Model request forensics across all 6 logical stages (7 model calls with Performance 5A/5B)', 1)
t = replace_once(
    t,
    '        """Capture and verify model requests across all six stages with grounded context."""',
    '        """Capture all six logical stages; Performance contributes two model requests (5A/5B)."""',
    'phase1b forensics docstring',
)
t = replace_once(t, '        out3 = self.runtime.execute_stage_strategist(ctx)', '        out3 = self.runtime.execute_stage_content(ctx)', 'phase1b canonical content call 1')
t = replace_once(t, '        self.assertEqual(len(self.mock_adapter.captured_requests), 6)', '        self.assertEqual(len(self.mock_adapter.captured_requests), 7)', 'phase1b request count 1')
t = replace_once(
    t,
    '        stage_names = ["CMO Initial", "Intelligence", "Strategist", "Creative", "Performance", "Final CMO"]',
    '        stage_names = ["CMO Initial", "Intelligence", "Content", "Creative", "Performance 5A", "Performance 5B", "Final CMO"]',
    'phase1b stage names',
)
t = replace_once(
    t,
    '        # Stage 4 Creative (GENERATIVE) and Stage 5 Performance (COMPUTATION) produce non-observation receipts\n        # which must NOT compile into EvidenceItems\n        self.assertEqual(forensics_rows[3]["tool_count"], 0)\n        self.assertEqual(forensics_rows[4]["tool_count"], 0)',
    '        # Creative and both internal Performance passes must not turn non-observation receipts into EvidenceItems.\n        self.assertEqual(forensics_rows[3]["tool_count"], 0)\n        self.assertEqual(forensics_rows[4]["tool_count"], 0)\n        self.assertEqual(forensics_rows[5]["tool_count"], 0)',
    'phase1b tool evidence assertions',
)
t = replace_once(
    t,
    '        """Verify evidence markers appear in bounded non-recursive counts across all 6 stages."""',
    '        """Verify evidence markers stay bounded across 6 logical stages / 7 model requests."""',
    'phase1b duplication docstring',
)
t = replace_once(t, '        self.runtime.execute_stage_strategist(ctx)', '        self.runtime.execute_stage_content(ctx)', 'phase1b canonical content call 2')
t = replace_once(t, '        self.assertEqual(len(self.mock_adapter.captured_requests), 6)', '        self.assertEqual(len(self.mock_adapter.captured_requests), 7)', 'phase1b request count 2')
p.write_text(t, encoding='utf-8')

subprocess.run([sys.executable, '-m', 'py_compile', 'tests/test_phase1a_runtime_integrity.py', 'tests/test_phase1b_grounded_context.py'], check=True)
subprocess.run([
    sys.executable, '-m', 'unittest', '-v',
    'tests.test_phase1a_runtime_integrity',
    'tests.test_phase1b_grounded_context',
    'tests.test_performance_two_pass_32',
    'tests.test_conditional_approval_no_deploy_55',
], check=True)

# Clean temporary automation before committing.
Path('.github/workflows/candidate-fix-perf-two-pass-regressions.yml').unlink(missing_ok=True)
Path('scripts/_candidate_fix_perf_two_pass_regressions.py').unlink(missing_ok=True)
subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
subprocess.run(['git', 'add', '-A'], check=True)
subprocess.run(['git', 'commit', '-m', 'test(runtime): align regression contracts with Performance 5A/5B'], check=True)
subprocess.run(['git', 'push', 'origin', 'HEAD:integration/final-main-reconciliation-v1'], check=True)
