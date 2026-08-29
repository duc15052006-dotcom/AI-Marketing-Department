"""Second asserted migration for batch hardening.

Runs after apply_full_defect_batch_v1_r1.py.  It removes speculative media
execution from Creative and makes directly-invoked downstream stages truthful
NOT_REACHED states when an upstream stage already failed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str, count: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"BATCH_V2_DRIFT {path}: expected {count}, found {actual} for {old[:90]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# Helper used only for deterministic workflow state; it never calls a model/tool.
engine_path = ROOT / "runtime/engine.py"
engine = engine_path.read_text(encoding="utf-8")
anchor = "\n\nclass FiveAgentDepartmentRuntime:\n"
helper = '''\n\ndef first_failed_stage(context: RuntimeContext) -> Tuple[Optional[str], Optional[str]]:\n    """Return first authoritative failed stage/error without inventing a new cause."""\n    for key in ("cmo_initial", "intelligence", "strategist", "creative", "performance"):\n        out = context.stage_outputs.get(key, {})\n        if out.get("status") == "FAILED":\n            return key.upper(), str(out.get("error") or out.get("reason") or "STAGE_FAILED")\n    if context.status == RuntimeStatus.FAILED:\n        safe = context.working_state.get("last_model_error")\n        if isinstance(safe, dict):\n            return None, str(safe.get("code") or "WORKFLOW_FAILED")\n        return None, "WORKFLOW_FAILED"\n    return None, None\n'''
if "def first_failed_stage(" not in engine:
    if engine.count(anchor) != 1:
        raise RuntimeError("BATCH_V2_DRIFT runtime class anchor")
    engine = engine.replace(anchor, helper + anchor)
engine_path.write_text(engine, encoding="utf-8")

# Intelligence: guard before any search when full workflow upstream has failed.
anchor_intel = '''        k_res = self.knowledge_builder.build_context_for_agent("intelligence", query_text=context.objective)
'''
insert_intel = '''        failed_stage, failed_error = first_failed_stage(context)
        if failed_error and context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":
            output = {
                "stage": "INTELLIGENCE", "agent": "intelligence", "status": "NOT_REACHED",
                "reason": failed_error, "failed_stage": failed_stage, "market_findings": "",
                "search_receipt_id": None, "citations": [],
            }
            context.stage_outputs["intelligence"] = output
            context.create_checkpoint()
            return output

        k_res = self.knowledge_builder.build_context_for_agent("intelligence", query_text=context.objective)
'''
replace_exact("runtime/engine.py", anchor_intel, insert_intel)

old_intel_guard = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="INTELLIGENCE",
                    agent="INTELLIGENCE",
                    message="Giai đoạn Intelligence thất bại do giai đoạn trước gặp sự cố",
                    metadata={"error": "PREVIOUS_STAGE_FAILED"},
                )
            output = {
                "stage": "INTELLIGENCE",
                "agent": "intelligence",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "market_findings": "",
                "search_receipt_id": search_receipt.execution_id if search_receipt is not None else None,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["intelligence"] = output
            context.create_checkpoint()
            return output

'''
replace_exact("runtime/engine.py", old_intel_guard, "")

# Strategist: no work or false failure if Intelligence already failed.
anchor_strat = '''        k_res = self.knowledge_builder.build_context_for_agent("strategist", query_text=context.objective)
'''
insert_strat = '''        failed_stage, failed_error = first_failed_stage(context)
        if failed_error:
            output = {
                "stage": "STRATEGIST", "agent": "strategist", "status": "NOT_REACHED",
                "reason": failed_error, "failed_stage": failed_stage, "positioning": "",
                "target_segments": [], "value_propositions": [], "citations": [],
            }
            context.stage_outputs["strategist"] = output
            context.create_checkpoint()
            return output

        k_res = self.knowledge_builder.build_context_for_agent("strategist", query_text=context.objective)
'''
replace_exact("runtime/engine.py", anchor_strat, insert_strat)
old_strat = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("intelligence", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="STRATEGIST",
                    agent="STRATEGIST",
                    message="Giai đoạn Strategist thất bại do giai đoạn trước gặp sự cố",
                    metadata={"error": "PREVIOUS_STAGE_FAILED"},
                )
            output = {
                "stage": "STRATEGIST",
                "agent": "strategist",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "positioning": "",
                "target_segments": [],
                "value_propositions": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["strategist"] = output
            context.create_checkpoint()
            return output

'''
replace_exact("runtime/engine.py", old_strat, "")

# Creative: reasoning/specification first. No automatic image tool side effect and
# no mock/sandbox result represented as an actual render.
anchor_creative = '''        k_res = self.knowledge_builder.build_context_for_agent("creative", query_text=context.objective)
'''
insert_creative = '''        failed_stage, failed_error = first_failed_stage(context)
        if failed_error:
            output = {
                "stage": "CREATIVE", "agent": "creative", "status": "NOT_REACHED",
                "reason": failed_error, "failed_stage": failed_stage, "concept_name": None,
                "visual_asset_receipt": None, "creative_synthesis": "", "copy_headlines": [], "citations": [],
            }
            context.stage_outputs["creative"] = output
            context.create_checkpoint()
            return output

        k_res = self.knowledge_builder.build_context_for_agent("creative", query_text=context.objective)
'''
replace_exact("runtime/engine.py", anchor_creative, insert_creative)
old_media = '''        # Invoke ToolGateway for local image generation / asset preparation
        idem_key = f"{context.run_id}:creative:image_generation:hero"
        if idem_key in self._executed_tool_idempotency_keys:
            img_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            img_req = ToolRequest(
                run_id=context.run_id,
                agent_id="creative",
                capability_id="image_generation",
                parameters={"prompt": f"Hero marketing visual concept for {context.objective}"},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            img_receipt = self.tool_gateway.execute(img_req)
            self._executed_tool_idempotency_keys[idem_key] = img_receipt

        context.execution_receipt_refs.append(img_receipt.execution_id)
        self.lineage_inspector.add_receipt(img_receipt)
        if img_receipt.artifact_references:
            context.artifact_refs.extend(img_receipt.artifact_references)

        # Grounded Context Compilation with image tool receipt
        grounded_pkg = self.context_compiler.compile_grounded_package("creative", context, tool_receipts=[img_receipt])
'''
new_media = '''        # Creative stage produces an executable CreativeSpec first. Media creation
        # is an explicit later capability action; no speculative render is attempted.
        img_receipt = None
        grounded_pkg = self.context_compiler.compile_grounded_package("creative", context, tool_receipts=[])
'''
replace_exact("runtime/engine.py", old_media, new_media)
old_creative_guard = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("strategist", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="CREATIVE",
                    agent="CREATIVE",
                    message="Giai đoạn Creative thất bại do giai đoạn trước gặp sự cố",
                    metadata={"error": "PREVIOUS_STAGE_FAILED"},
                )
            output = {
                "stage": "CREATIVE",
                "agent": "creative",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "concept_name": "",
                "visual_asset_receipt": img_receipt.execution_id,
                "creative_synthesis": "",
                "copy_headlines": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["creative"] = output
            context.create_checkpoint()
            return output

'''
replace_exact("runtime/engine.py", old_creative_guard, "")
# Guard all remaining img_receipt output accesses.
engine = (ROOT / "runtime/engine.py").read_text(encoding="utf-8")
engine = engine.replace('"visual_asset_receipt": img_receipt.execution_id,', '"visual_asset_receipt": img_receipt.execution_id if img_receipt is not None else None,')
old_dump = '''        # COLLAB-06: expose the real asset receipt to the CreativeSpec builder.
        output["_img_receipt_dump"] = {
            "execution_id": img_receipt.execution_id,
            "capability_id": img_receipt.capability_id,
            "status": img_receipt.status.value,
            "execution_mode": img_receipt.execution_mode.value,
        }
'''
new_dump = '''        # Only attach a media receipt when a real explicit media action exists.
        if img_receipt is not None:
            output["_img_receipt_dump"] = {
                "execution_id": img_receipt.execution_id,
                "capability_id": img_receipt.capability_id,
                "status": img_receipt.status.value,
                "execution_mode": img_receipt.execution_mode.value,
            }
'''
if engine.count(old_dump) != 1:
    raise RuntimeError(f"BATCH_V2_DRIFT creative receipt dump {engine.count(old_dump)}")
engine = engine.replace(old_dump, new_dump)
(ROOT / "runtime/engine.py").write_text(engine, encoding="utf-8")

# Performance: preserve first failure as NOT_REACHED before any measurement call.
anchor_perf = '''        k_res = self.knowledge_builder.build_context_for_agent("performance", query_text=context.objective)
'''
insert_perf = '''        failed_stage, failed_error = first_failed_stage(context)
        if failed_error:
            output = {
                "stage": "PERFORMANCE", "agent": "performance", "status": "NOT_REACHED",
                "reason": failed_error, "failed_stage": failed_stage, "funnel_kpi": "",
                "experiment_blueprint": {}, "calc_receipt_id": None, "citations": [],
            }
            context.stage_outputs["performance"] = output
            context.create_checkpoint()
            return output

        k_res = self.knowledge_builder.build_context_for_agent("performance", query_text=context.objective)
'''
replace_exact("runtime/engine.py", anchor_perf, insert_perf)
old_perf_guard = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("creative", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="PERFORMANCE",
                    agent="PERFORMANCE",
                    message="Giai đoạn Performance thất bại do giai đoạn trước gặp sự cố",
                    metadata={"error": "PREVIOUS_STAGE_FAILED"},
                )
            output = {
                "stage": "PERFORMANCE",
                "agent": "performance",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "funnel_kpi": "",
                "experiment_blueprint": {},
                "calc_receipt_id": calc_receipt.execution_id if calc_receipt is not None else None,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["performance"] = output
            context.create_checkpoint()
            return output

'''
replace_exact("runtime/engine.py", old_perf_guard, "")

# Final CMO: preflight before STAGE_STARTED. Direct calls must never create a false
# Final CMO failure/start event after an upstream failure.
old_final_start = '''        context.current_stage = RuntimeStage.FINAL_CMO
        emitter = self._get_emitter(context)
        if emitter:
            emitter.emit(
                ProgressEventType.STAGE_STARTED,
                stage="FINAL_CMO",
                agent="CMO",
                message="Bắt đầu giai đoạn Final CMO (Governed Synthesis & GTM Plan)",
            )

        cmo_init = context.stage_outputs.get("cmo_initial", {})
        intel_out = context.stage_outputs.get("intelligence", {})
        strat_out = context.stage_outputs.get("strategist", {})
        crtv_out = context.stage_outputs.get("creative", {})
        perf_out = context.stage_outputs.get("performance", {})

        has_stage_failure = any(
            s.get("status") == "FAILED" for s in (cmo_init, intel_out, strat_out, crtv_out, perf_out)
        ) or context.status == RuntimeStatus.FAILED

        if has_stage_failure:
            fail_reason = "PREVIOUS_STAGE_FAILED"
            context.status = RuntimeStatus.FAILED
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="FINAL_CMO",
                    agent="CMO",
                    message="Giai đoạn Final CMO không thể thực hiện do giai đoạn trước gặp sự cố",
                    metadata={"error": "PREVIOUS_STAGE_FAILED"},
                )
            output = {
                "stage": "FINAL_CMO",
                "agent": "cmo",
                "status": "FAILED",
                "approval_status": "NOT_EVALUATED",
                "reason": fail_reason,
                "master_gtm_plan": {},
                "master_gtm_plan_markdown": f"# BÁO CÁO PHÊ DUYỆT THẤT BẠI — FIVE-AGENT DEPARTMENT\\n\\n**Trạng thái phê duyệt**: KHÔNG ĐƯỢC PHÊ DUYỆT ({fail_reason})\\n\\nKhông thể hoàn tất kế hoạch GTM do một hoặc nhiều giai đoạn chuyên môn trước đó gặp sự cố.",
            }
            context.stage_outputs["final_cmo"] = output
            context.create_checkpoint()
            return output

'''
new_final_start = '''        failed_stage, failed_error = first_failed_stage(context)
        if failed_error:
            output = {
                "stage": "FINAL_CMO", "agent": "cmo", "status": "NOT_REACHED",
                "approval_status": "NOT_EVALUATED", "reason": failed_error,
                "error": failed_error, "failed_stage": failed_stage,
                "master_gtm_plan": {},
                "master_gtm_plan_markdown": "# BÁO CÁO KHÔNG HOÀN TẤT\\n\\nFinal CMO chưa được thực thi vì một giai đoạn trước đã thất bại.",
            }
            context.stage_outputs["final_cmo"] = output
            context.create_checkpoint()
            return output

        context.current_stage = RuntimeStage.FINAL_CMO
        emitter = self._get_emitter(context)
        if emitter:
            emitter.emit(
                ProgressEventType.STAGE_STARTED,
                stage="FINAL_CMO",
                agent="CMO",
                message="Bắt đầu giai đoạn Final CMO (Governed Synthesis & GTM Plan)",
            )

        cmo_init = context.stage_outputs.get("cmo_initial", {})
        intel_out = context.stage_outputs.get("intelligence", {})
        strat_out = context.stage_outputs.get("strategist", {})
        crtv_out = context.stage_outputs.get("creative", {})
        perf_out = context.stage_outputs.get("performance", {})

'''
replace_exact("runtime/engine.py", old_final_start, new_final_start)

print("FULL_DEFECT_BATCH_V2_APPLIED")
