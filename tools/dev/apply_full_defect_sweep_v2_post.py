"""Post migration for the full V2 defect sweep.

Executed after apply_full_defect_sweep_v2_r4.py.  Covers defects found during
second-pass audit: raw runtime exception reflection, speculative Creative media
execution, direct downstream false failures, and sync adapter exception detail.
All edits are asserted against the expected post-R4 source shape.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str, count: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"POST_SWEEP_DRIFT {path}: expected {count}, found {actual}: {old[:90]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# ----- Sync model adapter exception: fixed public detail, type-only log. -----
replace_exact(
    "integrations/models/gateway.py",
    '''            try:
                resp = adapter.generate(req_copy)
            except Exception as e:
                resp = ModelResponse(
                    request_id=norm_req.request_id,
                    provider=cand_provider,
                    model_name=cand_model,
                    status=ModelResponseStatus.ERROR,
                    error=f"ADAPTER_INVOCATION_EXCEPTION: {str(e)[:200]}",
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
''',
    '''            try:
                resp = adapter.generate(req_copy)
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except Exception as exc:
                logger.warning("Model adapter %s raised %s", cand_provider, type(exc).__name__)
                resp = ModelResponse(
                    request_id=norm_req.request_id,
                    provider=cand_provider,
                    model_name=cand_model,
                    status=ModelResponseStatus.ERROR,
                    error="ADAPTER_INVOCATION_EXCEPTION: Internal provider adapter failure.",
                    metadata={
                        "error_code": "STREAM_INTERNAL_ERROR",
                        "error_category": "INTERNAL",
                        "safe_message": "Internal provider adapter failure.",
                        "retryable": False,
                        "http_status": None,
                    },
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
''',
)

# ----- Deterministic first-failure lookup for direct stage invocation. -----
engine_path = ROOT / "runtime/engine.py"
engine = engine_path.read_text(encoding="utf-8")
class_anchor = "\n\nclass FiveAgentDepartmentRuntime:\n"
helper = '''\n\ndef first_failed_stage(context: RuntimeContext) -> Tuple[Optional[str], Optional[str]]:\n    """Return the first real failed stage and its authoritative safe error code."""\n    for key in ("cmo_initial", "intelligence", "strategist", "creative", "performance"):\n        out = context.stage_outputs.get(key, {})\n        if out.get("status") == "FAILED":\n            return key.upper(), str(out.get("error") or out.get("reason") or "STAGE_FAILED")\n    if context.status == RuntimeStatus.FAILED:\n        public_error = context.working_state.get("last_model_error")\n        if isinstance(public_error, dict):\n            return None, str(public_error.get("code") or "WORKFLOW_FAILED")\n        return None, "WORKFLOW_FAILED"\n    return None, None\n'''
if "def first_failed_stage(" not in engine:
    if engine.count(class_anchor) != 1:
        raise RuntimeError("POST_SWEEP_DRIFT runtime class anchor")
    engine = engine.replace(class_anchor, helper + class_anchor)
engine_path.write_text(engine, encoding="utf-8")

# ----- Intelligence guard before research side effects. -----
replace_exact(
    "runtime/engine.py",
    '''        k_res = self.knowledge_builder.build_context_for_agent("intelligence", query_text=context.objective)
''',
    '''        failed_stage, failed_error = first_failed_stage(context)
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
''',
)
old_intel_previous = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":
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
                "search_receipt_id": search_receipt.execution_id,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["intelligence"] = output
            context.create_checkpoint()
            return output

'''
replace_exact("runtime/engine.py", old_intel_previous, "")

# ----- Strategist guard before retrieval/context work. -----
replace_exact(
    "runtime/engine.py",
    '''        k_res = self.knowledge_builder.build_context_for_agent("strategist", query_text=context.objective)
''',
    '''        failed_stage, failed_error = first_failed_stage(context)
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
''',
)
old_strat_previous = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("intelligence", {}).get("status") == "FAILED":
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
replace_exact("runtime/engine.py", old_strat_previous, "")

# ----- Creative: produce specification first; never auto-render a speculative hero. -----
replace_exact(
    "runtime/engine.py",
    '''        k_res = self.knowledge_builder.build_context_for_agent("creative", query_text=context.objective)
''',
    '''        failed_stage, failed_error = first_failed_stage(context)
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
''',
)
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
replace_exact(
    "runtime/engine.py", old_media,
    '''        # Creative emits a truthful executable specification. Media creation is
        # a separate explicit capability action after concept approval.
        img_receipt = None
        grounded_pkg = self.context_compiler.compile_grounded_package("creative", context, tool_receipts=[])
''',
)
old_creative_previous = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("strategist", {}).get("status") == "FAILED":
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
replace_exact("runtime/engine.py", old_creative_previous, "")
engine = engine_path.read_text(encoding="utf-8")
engine = engine.replace('"visual_asset_receipt": img_receipt.execution_id,', '"visual_asset_receipt": img_receipt.execution_id if img_receipt is not None else None,')
old_dump = '''        # COLLAB-06: expose the real asset receipt to the CreativeSpec builder.
        output["_img_receipt_dump"] = {
            "execution_id": img_receipt.execution_id,
            "capability_id": img_receipt.capability_id,
            "status": img_receipt.status.value,
            "execution_mode": img_receipt.execution_mode.value,
        }
'''
new_dump = '''        if img_receipt is not None:
            output["_img_receipt_dump"] = {
                "execution_id": img_receipt.execution_id,
                "capability_id": img_receipt.capability_id,
                "status": img_receipt.status.value,
                "execution_mode": img_receipt.execution_mode.value,
            }
'''
if engine.count(old_dump) != 1:
    raise RuntimeError(f"POST_SWEEP_DRIFT creative receipt dump: {engine.count(old_dump)}")
engine_path.write_text(engine.replace(old_dump, new_dump), encoding="utf-8")

# ----- Performance guard before measurement side effects. -----
replace_exact(
    "runtime/engine.py",
    '''        k_res = self.knowledge_builder.build_context_for_agent("performance", query_text=context.objective)
''',
    '''        failed_stage, failed_error = first_failed_stage(context)
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
''',
)
old_perf_previous = '''        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("creative", {}).get("status") == "FAILED":
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
replace_exact("runtime/engine.py", old_perf_previous, "")

# ----- Final CMO direct call: preflight before any start/failure event. -----
old_final = '''        context.current_stage = RuntimeStage.FINAL_CMO
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
new_final = '''        failed_stage, failed_error = first_failed_stage(context)
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
replace_exact("runtime/engine.py", old_final, new_final)

# ----- Full workflow exception: no raw exception in state/UI, Final CMO not reached. -----
old_run_tail = '''                cmo_final = {
                    "stage": "FINAL_CMO",
                    "agent": "cmo",
                    "status": "FAILED",
                    "approval_status": "NOT_EVALUATED",
                    "reason": f"UNHANDLED_RUNTIME_EXCEPTION: {str(exc)}",
                    "master_gtm_plan": {},
                    "master_gtm_plan_markdown": f"# BÁO CÁO PHÊ DUYỆT THẤT BẠI — FIVE-AGENT DEPARTMENT\\n\\n**Trạng thái phê duyệt**: KHÔNG ĐƯỢC PHÊ DUYỆT (UNHANDLED_RUNTIME_EXCEPTION)\\n\\nLỗi hệ thống trong quá trình thực thi pipeline: {str(exc)}",
                }
                context.stage_outputs["final_cmo"] = cmo_final
                context.create_checkpoint()
                if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                    stage_obj = runtime_stage_to_progress_stage(context.current_stage)
                    emitter.emit(
                        ProgressEventType.RUN_FAILED,
                        stage=stage_obj,
                        agent="CMO",
                        message=f"Quy trình thực thi gặp lỗi: {str(exc)}",
                        metadata={"error": str(exc)},
                    )
'''
new_run_tail = '''                stage_name = str(getattr(getattr(context, "current_stage", None), "value", getattr(context, "current_stage", "")))
                safe_error = internal_runtime_error(stage=stage_name, agent="CMO")
                context.working_state["last_model_error"] = safe_error.model_dump()
                cmo_final = {
                    "stage": "FINAL_CMO",
                    "agent": "cmo",
                    "status": "NOT_REACHED",
                    "approval_status": "NOT_EVALUATED",
                    "reason": safe_error.code,
                    "error": safe_error.code,
                    "failed_stage": stage_name,
                    "master_gtm_plan": {},
                    "master_gtm_plan_markdown": "# BÁO CÁO KHÔNG HOÀN TẤT — FIVE-AGENT DEPARTMENT\\n\\nQuy trình dừng do lỗi nội bộ an toàn. Final CMO chưa được thực thi.",
                }
                context.stage_outputs["final_cmo"] = cmo_final
                context.create_checkpoint()
                if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                    stage_obj = runtime_stage_to_progress_stage(context.current_stage)
                    emitter.emit(
                        ProgressEventType.RUN_FAILED,
                        stage=stage_obj,
                        agent=None,
                        message="Quy trình thực thi gặp lỗi nội bộ.",
                        metadata={"error": safe_error.model_dump()},
                    )
'''
replace_exact("runtime/engine.py", old_run_tail, new_run_tail)

# ----- Research fast-path exception: fixed safe error only. -----
old_research_exc = '''        except Exception as exc:
            logger.exception(f"Unhandled exception during research inquiry {context.run_id}: {exc}")
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"RESEARCH_INQUIRY_UNHANDLED_EXCEPTION: {str(exc)}")
            if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="INTELLIGENCE",
                    agent="INTELLIGENCE",
                    message=f"Truy vấn nghiên cứu thất bại: {str(exc)}",
                    metadata={"error": str(exc)},
                )
            final_output = {
                "stage": "INTELLIGENCE_ONLY",
                "agent": "intelligence",
                "status": "FAILED",
                "master_gtm_plan_markdown": f"⚠️ Lỗi hệ thống nghiên cứu: {str(exc)}",
                "research_findings": "",
            }
'''
new_research_exc = '''        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exc:
            logger.error("Unhandled research exception for run %s: %s", context.run_id, type(exc).__name__)
            context.status = RuntimeStatus.FAILED
            safe_error = internal_runtime_error(stage="INTELLIGENCE", agent="INTELLIGENCE")
            context.working_state["last_model_error"] = safe_error.model_dump()
            context.risk_flags.append("RESEARCH_INQUIRY_UNHANDLED_EXCEPTION")
            if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    stage="INTELLIGENCE",
                    agent="INTELLIGENCE",
                    message="Truy vấn nghiên cứu thất bại do lỗi nội bộ.",
                    metadata={"error": safe_error.model_dump()},
                )
            final_output = {
                "stage": "INTELLIGENCE_ONLY",
                "agent": "intelligence",
                "status": "FAILED",
                "error": safe_error.code,
                "master_gtm_plan_markdown": "⚠️ Không thể hoàn tất nghiên cứu do lỗi nội bộ.",
                "research_findings": "",
            }
'''
replace_exact("runtime/engine.py", old_research_exc, new_research_exc)

print("FULL_DEFECT_SWEEP_V2_POST_APPLIED")
