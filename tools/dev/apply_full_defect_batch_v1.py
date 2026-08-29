"""Asserted production migration for the full defect hardening batch.

This script is deliberately source-shape-sensitive.  It aborts on drift rather
than applying a broad/ambiguous replacement.  It touches only production code
that has already been audited on phase/agent-hardening-v2.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"BATCH_PATCH_DRIFT {path}: expected {count}, found {actual} for {old[:100]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# ToolGateway: arbitrary adapter exceptions must never become public/persisted
# exception strings.  Preserve exception TYPE only in a fixed safe message.
# ---------------------------------------------------------------------------
replace_exact(
    "tools/tool_gateway.py",
    """        adapter_res = None
        last_exc = None
        try:
            for attempt in range(max_retries + 1):
                try:
                    adapter_res = adapter.execute(
                        capability_id=cap.capability_id,
                        parameters=request.parameters,
                        timeout_seconds=timeout,
                        run_id=request.run_id,
                        business_id=request.business_id or "",
                        project_id=request.project_id or "",
                    )
                except Exception as e:
                    adapter_res = None
                    last_exc = e
""",
    """        adapter_res = None
        last_exc_type = ""
        try:
            for attempt in range(max_retries + 1):
                try:
                    adapter_res = adapter.execute(
                        capability_id=cap.capability_id,
                        parameters=request.parameters,
                        timeout_seconds=timeout,
                        run_id=request.run_id,
                        business_id=request.business_id or "",
                        project_id=request.project_id or "",
                    )
                except (KeyboardInterrupt, SystemExit, GeneratorExit):
                    raise
                except Exception as exc:
                    adapter_res = None
                    last_exc_type = type(exc).__name__
                    logger.warning("Tool adapter %s raised %s", adapter.adapter_name, last_exc_type)
""",
)
replace_exact(
    "tools/tool_gateway.py",
    """            err_code = adapter_res.error_code if adapter_res else "EXECUTION_EXCEPTION"
            err_msg = adapter_res.error_message if adapter_res else str(last_exc)
""",
    """            err_code = adapter_res.error_code if adapter_res else "EXECUTION_EXCEPTION"
            err_msg = (
                adapter_res.error_message
                if adapter_res
                else "Tool execution failed inside the connector boundary."
            )
""",
)

# ---------------------------------------------------------------------------
# Model cost truth: per-model metadata outranks provider-level marketing tier.
# Unknown model cost fails closed.  A provider-level FREE tier is not proof that
# every model offered by an aggregator is free.
# ---------------------------------------------------------------------------
insert_after = '''def normalize_public_stream_delta(
    delta: StreamDelta,
    cand_provider: str,
    cand_model: str,
) -> StreamDelta:
'''
gateway_path = ROOT / "integrations/models/gateway.py"
gateway = gateway_path.read_text(encoding="utf-8")
idx = gateway.find(insert_after)
if idx < 0:
    raise RuntimeError("BATCH_PATCH_DRIFT gateway helper anchor missing")
helper_anchor = "\n\nclass ProviderHealth(str, Enum):"
helper_pos = gateway.find(helper_anchor, idx)
if helper_pos < 0:
    raise RuntimeError("BATCH_PATCH_DRIFT gateway ProviderHealth anchor missing")
helper = '''\n\ndef resolve_effective_model_cost_policy(\n    model_meta: Optional[ModelMetadata],\n    provider_definition: Optional[ProviderDefinition],\n    adapter: Optional[BaseModelAdapter],\n) -> CostPolicy:\n    """Return the only cost tier safe to enforce for one concrete model.\n\n    Verified model metadata is strongest.  Provider PAID/UNKNOWN may safely\n    constrain all models.  Provider FREE_TIER_ALLOWED is not sufficient proof\n    for an unknown model (aggregators can mix free and paid models), therefore\n    unknown concrete models fail closed as UNKNOWN.\n    """\n    if model_meta is not None:\n        return model_meta.cost_tier\n    if provider_definition is not None:\n        if provider_definition.cost_policy in (CostPolicy.PAID, CostPolicy.UNKNOWN):\n            return provider_definition.cost_policy\n        return CostPolicy.UNKNOWN\n    if adapter is not None and getattr(adapter, "cost_policy", CostPolicy.UNKNOWN) in (CostPolicy.PAID, CostPolicy.UNKNOWN):\n        return adapter.cost_policy\n    return CostPolicy.UNKNOWN\n'''
if "def resolve_effective_model_cost_policy(" not in gateway:
    gateway = gateway[:helper_pos] + helper + gateway[helper_pos:]
gateway_path.write_text(gateway, encoding="utf-8")

replace_exact(
    "integrations/models/gateway.py",
    """            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            # ProviderDefinition-declared cost policy is authoritative when a
            # definition exists (including explicit UNKNOWN = unverified);
            # model metadata is only a fallback for undefined providers.
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = (
                    model_meta.cost_tier if model_meta
                    else (adapter.cost_policy if adapter else CostPolicy.UNKNOWN)
                )
""",
    """            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            cost_tier = resolve_effective_model_cost_policy(model_meta, prov_def, adapter)
""",
)
replace_exact(
    "integrations/models/gateway.py",
    """            # 3. Cost Policy Gate
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = adapter.cost_policy
""",
    """            # 3. Cost Policy Gate — concrete model truth outranks provider tier.
            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            cost_tier = resolve_effective_model_cost_policy(model_meta, prov_def, adapter)
""",
)
replace_exact(
    "integrations/models/gateway.py",
    """            try:
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
""",
    """            try:
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
""",
)

# ---------------------------------------------------------------------------
# Runtime: wire bounded multi-search/page-read research into production.
# Keep the first canonical ObservationRecord for the existing evidence pipeline,
# while supplying verified REAL page text separately to Intelligence synthesis.
# ---------------------------------------------------------------------------
replace_exact(
    "runtime/engine.py",
    "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\n",
    "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\nfrom runtime.research_loop import BoundedResearchLoop\n",
)

old_research = '''        # Invoke ToolGateway for search observation
        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_STARTED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Bắt đầu tìm kiếm dữ liệu thị trường qua ToolGateway",
                metadata={"capability": "web_search"},
            )

        idem_key = f"{context.run_id}:intelligence:web_search:{context.objective}"
        if idem_key in self._executed_tool_idempotency_keys:
            search_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            search_req = ToolRequest(
                run_id=context.run_id,
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": context.objective},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            search_receipt = self.tool_gateway.execute(search_req)
            self._executed_tool_idempotency_keys[idem_key] = search_receipt

        context.execution_receipt_refs.append(search_receipt.execution_id)
        self.lineage_inspector.add_receipt(search_receipt)

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Hoàn tất tìm kiếm dữ liệu thị trường",
                metadata={"execution_id": search_receipt.execution_id, "status": search_receipt.status.value},
            )

        # Grounded Context Compilation with actual Tool Receipt content
        grounded_pkg = self.context_compiler.compile_grounded_package("intelligence", context, tool_receipts=[search_receipt])
'''
new_research = '''        # Bounded evidence-oriented research loop: multi-query discovery then
        # REAL source reads. Search snippets remain discovery signals only.
        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_STARTED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Bắt đầu nghiên cứu nhiều nguồn qua ToolGateway",
                metadata={"capability": "web_search+read_page"},
            )

        research_depth = str(context.working_state.get("research_depth") or "STANDARD").upper()
        research_exec = BoundedResearchLoop(self.tool_gateway).execute(
            run_id=context.run_id,
            agent_id="intelligence",
            objective=context.objective,
            business_id=context.business_id,
            project_id=context.project_id,
            chat_id=context.chat_id,
            depth=research_depth,
        )
        all_research_receipts = list(research_exec.search_receipts) + list(research_exec.page_receipts)
        for receipt in all_research_receipts:
            if receipt.execution_id not in context.execution_receipt_refs:
                context.execution_receipt_refs.append(receipt.execution_id)
            self.lineage_inspector.add_receipt(receipt)

        search_receipt = next(
            (r for r in research_exec.search_receipts if getattr(r, "observation_record", None) is not None),
            research_exec.search_receipts[0] if research_exec.search_receipts else None,
        )
        context.working_state["research_depth"] = research_depth
        context.working_state["research_search_count"] = len(research_exec.search_receipts)
        context.working_state["research_real_page_count"] = research_exec.real_page_count
        context.working_state["research_source_urls"] = list(research_exec.source_urls)
        context.working_state["research_backend_errors"] = list(research_exec.backend_errors)

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Hoàn tất tìm kiếm và đọc nguồn nghiên cứu",
                metadata={
                    "search_count": len(research_exec.search_receipts),
                    "real_page_count": research_exec.real_page_count,
                    "depth": research_depth,
                },
            )

        # Existing generic context compiler receives all receipts, while canonical
        # evidence conversion below consumes only a real ObservationRecord.
        grounded_pkg = self.context_compiler.compile_grounded_package(
            "intelligence", context, tool_receipts=all_research_receipts
        )
'''
replace_exact("runtime/engine.py", old_research, new_research)

# Canonical observation conversion must tolerate complete search degradation.
replace_exact(
    "runtime/engine.py",
    '''        canonical_obs_data = getattr(search_receipt, "observation_record", None)
        if canonical_obs_data is not None and search_receipt.status == ExecutionStatus.SUCCESS:
''',
    '''        canonical_obs_data = getattr(search_receipt, "observation_record", None) if search_receipt is not None else None
        if canonical_obs_data is not None and search_receipt is not None and search_receipt.status == ExecutionStatus.SUCCESS:
''',
)
replace_exact(
    "runtime/engine.py",
    '''        prompt_parts = [f"Objective: {context.objective}", f"CMO Directive: {cmo_intent}"]
        if research_grounding_section:
            prompt_parts.append(research_grounding_section)
        prompt_parts.append(evidence_section)
''',
    '''        prompt_parts = [f"Objective: {context.objective}", f"CMO Directive: {cmo_intent}"]
        page_context = research_exec.render_page_context()
        if page_context:
            prompt_parts.append(page_context)
        if research_grounding_section:
            prompt_parts.append(research_grounding_section)
        prompt_parts.append(evidence_section)
''',
)
# Two output/failure sites expect search_receipt to exist.
engine_path = ROOT / "runtime/engine.py"
engine = engine_path.read_text(encoding="utf-8")
engine = engine.replace('"search_receipt_id": search_receipt.execution_id,', '"search_receipt_id": search_receipt.execution_id if search_receipt is not None else None,')
engine_path.write_text(engine, encoding="utf-8")

# Research fast path accepts explicit depth and never leaks raw exception text.
replace_exact(
    "runtime/engine.py",
    '''        project_id: Optional[str] = None,
        progress_sink: Optional[ProgressSink] = None,
        text_delta_sink: Optional[Callable[[str], None]] = None,
    ) -> Tuple[RuntimeContext, Dict[str, Any], DepartmentRunArtifact]:
        """Research-only fast path: Intelligence stage only, no full workflow.
''',
    '''        project_id: Optional[str] = None,
        progress_sink: Optional[ProgressSink] = None,
        text_delta_sink: Optional[Callable[[str], None]] = None,
        research_depth: str = "STANDARD",
    ) -> Tuple[RuntimeContext, Dict[str, Any], DepartmentRunArtifact]:
        """Research-only fast path: Intelligence stage only, no full workflow.
''',
)
replace_exact(
    "runtime/engine.py",
    '''        emitter = self._get_emitter(context)
        if emitter:
''',
    '''        context.working_state["research_depth"] = str(research_depth or "STANDARD").upper()
        emitter = self._get_emitter(context)
        if emitter:
''',
    count=1,
)
old_research_except = '''        except Exception as exc:
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
new_research_except = '''        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exc:
            logger.exception("Unhandled research inquiry exception type=%s run=%s", type(exc).__name__, context.run_id)
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
replace_exact("runtime/engine.py", old_research_except, new_research_except)

# Full workflow unhandled exception must also fail closed with no raw traceback text.
old_run_except = '''            else:
                logger.exception(f"Unhandled exception during run {context.run_id}: {exc}")
                context.status = RuntimeStatus.FAILED
                context.risk_flags.append(f"UNHANDLED_RUNTIME_EXCEPTION: {str(exc)}")
                cmo_final = {
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
new_run_except = '''            else:
                logger.exception("Unhandled runtime exception type=%s run=%s", type(exc).__name__, context.run_id)
                context.status = RuntimeStatus.FAILED
                stage_name = str(getattr(getattr(context, "current_stage", None), "value", getattr(context, "current_stage", "")))
                safe_error = internal_runtime_error(stage=stage_name, agent="CMO")
                context.working_state["last_model_error"] = safe_error.model_dump()
                context.risk_flags.append("UNHANDLED_RUNTIME_EXCEPTION")
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
replace_exact("runtime/engine.py", old_run_except, new_run_except)

# ---------------------------------------------------------------------------
# Server: pass explicit resolver depth to both research paths.
# ---------------------------------------------------------------------------
server_path = ROOT / "app_api/server.py"
server = server_path.read_text(encoding="utf-8")
needle = '''                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                    )
'''
replacement = '''                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                        research_depth=str((decision.metadata or {}).get("research_depth") or "STANDARD"),
                    )
'''
if server.count(needle) != 1:
    raise RuntimeError(f"BATCH_PATCH_DRIFT server streaming research depth: {server.count(needle)}")
server = server.replace(needle, replacement)
needle2 = '''                    chat_id=chat_id,
                    project_id=session.optional_project_id,
                )

                is_failed = intel_out.get("status") == "FAILED"
'''
replacement2 = '''                    chat_id=chat_id,
                    project_id=session.optional_project_id,
                    research_depth=str((decision.metadata or {}).get("research_depth") or "STANDARD"),
                )

                is_failed = intel_out.get("status") == "FAILED"
'''
if server.count(needle2) != 1:
    raise RuntimeError(f"BATCH_PATCH_DRIFT server sync research depth: {server.count(needle2)}")
server = server.replace(needle2, replacement2)
server_path.write_text(server, encoding="utf-8")

print("FULL_DEFECT_BATCH_V1_APPLIED")
