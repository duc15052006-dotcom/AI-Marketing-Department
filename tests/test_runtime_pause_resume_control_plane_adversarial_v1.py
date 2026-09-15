"""Runtime pause/resume must suspend actual stage progression, not only flip an enum."""
from __future__ import annotations
import os, threading, unittest
from unittest.mock import patch
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway

class RuntimePauseResumeControlPlaneAdversarialV1Tests(unittest.TestCase):
    @staticmethod
    def _runtime() -> FiveAgentDepartmentRuntime:
        return FiveAgentDepartmentRuntime(tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

    @staticmethod
    def _install_stage_probes(runtime, stage1_entered, release_stage1, stage2_entered):
        def stage1(ctx):
            stage1_entered.set(); release_stage1.wait(3); ctx.stage_outputs["cmo_initial"] = {"status": "SUCCESS"}; return ctx.stage_outputs["cmo_initial"]
        def stage2(ctx):
            stage2_entered.set(); ctx.stage_outputs["intelligence"] = {"status": "SUCCESS"}; return ctx.stage_outputs["intelligence"]
        def simple(name):
            def _stage(ctx, *args, **kwargs):
                ctx.stage_outputs[name] = {"status": "SUCCESS"}; return ctx.stage_outputs[name]
            return _stage
        runtime.execute_stage_cmo_initial = stage1
        runtime.execute_stage_intelligence = stage2
        runtime.execute_stage_content = simple("content")
        runtime.execute_stage_creative = simple("creative")
        runtime.execute_stage_performance = simple("performance")
        runtime.execute_stage_final_cmo = simple("final_cmo")
        runtime.complete_run = lambda ctx: object()

    def test_pause_blocks_next_stage_until_resume(self) -> None:
        env = {"AI_MARKETING_KNOWLEDGE_EPHEMERAL": "1", "AI_MARKETING_MEMORY_EPHEMERAL": "1", "AI_MARKETING_LEARNING_EPHEMERAL": "1"}
        with patch.dict(os.environ, env, clear=False):
            runtime = self._runtime(); ctx = runtime.start_run("pause probe")
            stage1_entered = threading.Event(); release_stage1 = threading.Event(); stage2_entered = threading.Event()
            self._install_stage_probes(runtime, stage1_entered, release_stage1, stage2_entered)
            worker = threading.Thread(target=lambda: runtime.execute_run(ctx), daemon=True); worker.start()
            self.assertTrue(stage1_entered.wait(2)); self.assertTrue(runtime.pause_run(ctx.run_id)); release_stage1.set()
            self.assertFalse(stage2_entered.wait(0.25), "Stage 2 advanced while run was PAUSED")
            self.assertTrue(runtime.resume_run(ctx.run_id)); self.assertTrue(stage2_entered.wait(2))
            worker.join(2); self.assertFalse(worker.is_alive())

    def test_cancel_wakes_paused_worker_without_advancing_next_stage(self) -> None:
        env = {"AI_MARKETING_KNOWLEDGE_EPHEMERAL": "1", "AI_MARKETING_MEMORY_EPHEMERAL": "1", "AI_MARKETING_LEARNING_EPHEMERAL": "1"}
        with patch.dict(os.environ, env, clear=False):
            runtime = self._runtime(); ctx = runtime.start_run("cancel paused probe")
            stage1_entered = threading.Event(); release_stage1 = threading.Event(); stage2_entered = threading.Event()
            self._install_stage_probes(runtime, stage1_entered, release_stage1, stage2_entered)
            worker = threading.Thread(target=lambda: runtime.execute_run(ctx), daemon=True); worker.start()
            self.assertTrue(stage1_entered.wait(2)); self.assertTrue(runtime.pause_run(ctx.run_id)); release_stage1.set()
            self.assertFalse(stage2_entered.wait(0.25)); self.assertTrue(runtime.cancel_run(ctx.run_id, reason="test cancel"))
            worker.join(2); self.assertFalse(worker.is_alive()); self.assertFalse(stage2_entered.is_set())

if __name__ == "__main__": unittest.main()
