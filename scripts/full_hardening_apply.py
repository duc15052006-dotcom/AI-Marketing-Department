from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"{path}: expected >= {minimum} matches, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# runtime/engine.py — preserve Gateway error truth, use canonical skills,
# remove fabricated performance measurement and raw exception leakage.
# ---------------------------------------------------------------------------
replace_once(
    "runtime/engine.py",
    "from runtime.memory_builder import MemoryContextBuilder\n",
    "from runtime.memory_builder import MemoryContextBuilder\n"
    "from runtime.agent_skills import render_agent_skill_context\n"
    "from runtime.public_errors import PublicRuntimeError, from_model_response, from_stream_delta, internal_runtime_error\n",
)
replace_once(
    "runtime/engine.py",
    "        self._executed_tool_idempotency_keys: Dict[str, ExecutionReceipt] = {}\n",
    "        self._executed_tool_idempotency_keys: Dict[str, ExecutionReceipt] = {}\n"
    "        self._public_errors: OrderedDict[str, Dict[str, Any]] = OrderedDict()\n",
)
replace_once(
    "runtime/engine.py",
    "    def _call_agent_llm(\n",
    '''    def _record_public_error(self, context: Optional[RuntimeContext], error: PublicRuntimeError) -> Dict[str, Any]:
        payload = error.model_dump()
        if context is not None:
            context.working_state.setdefault("public_error", payload)
            with self._lock:
                if context.run_id not in self._public_errors:
                    self._public_errors[context.run_id] = payload
                    while len(self._public_errors) > self.max_completed_runs_cache:
                        self._public_errors.popitem(last=False)
        return payload

    def get_public_error(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._public_errors.get(run_id)
            return dict(value) if value else None

    def _call_agent_llm(
''',
)
replace_once(
    "runtime/engine.py",
    "        # COLLAB-05: every stage may append the optional machine handoff block\n        # to the SAME single response (no second agent, no second model call).\n        system_instruction = system_instruction + HANDOFF_PROMPT_INSTRUCTION\n",
    "        # Canonical skills are production prompt authority for the five permanent agents.\n"
    "        system_instruction = system_instruction + \"\\n\\n\" + render_agent_skill_context(agent_name)\n"
    "        # COLLAB-05: optional machine handoff stays in the same response.\n"
    "        system_instruction = system_instruction + HANDOFF_PROMPT_INSTRUCTION\n",
)
replace_all(
    "runtime/engine.py",
    '                        f"RUN_PINNED_MODEL_CONFIGURATION_INVALID: Failed to reconstruct pinned ModelPolicy: {exc}"\n',
    '                        "RUN_PINNED_MODEL_CONFIGURATION_INVALID"\n',
    minimum=2,
)
replace_once(
    "runtime/engine.py",
    '                        f"RUN_PINNED_MODEL_CONFIGURATION_INVALID: Failed to reconstruct pinned ProviderRegistrySnapshot: {exc}"\n',
    '                        "RUN_PINNED_MODEL_CONFIGURATION_INVALID"\n',
)
replace_once(
    "runtime/engine.py",
    '''                chunks: List[str] = []
                had_error = False
                for delta in stream_gen:
                    if delta.content:
                        chunks.append(delta.content)
                        filter_sink.on_delta(delta.content)
                    if delta.finish_reason == "error":
                        had_error = True
                filter_sink.flush()
                if chunks and not had_error:
                    if emitter:
                        emitter.emit(
                            ProgressEventType.MODEL_COMPLETED,
                            stage=stage_obj,
                            agent=agent_upper,
                            message=f"Hoàn tất thực thi mô hình cho {agent_upper}",
                        )
                    return "".join(chunks).strip(), None
                err = "STREAM_GENERATION_FAILED"
                logger.warning(f"Agent {agent_name} LLM stream call failed: {err}")
                return None, err
''',
    '''                chunks: List[str] = []
                terminal_error_delta = None
                for delta in stream_gen:
                    if delta.content:
                        chunks.append(delta.content)
                        filter_sink.on_delta(delta.content)
                    if delta.finish_reason == "error":
                        terminal_error_delta = delta
                        break
                filter_sink.flush()
                if terminal_error_delta is None and chunks:
                    if emitter:
                        emitter.emit(
                            ProgressEventType.MODEL_COMPLETED,
                            stage=stage_obj,
                            agent=agent_upper,
                            message=f"Hoàn tất thực thi mô hình cho {agent_upper}",
                        )
                    return "".join(chunks).strip(), None

                stage_name = stage_obj.value if hasattr(stage_obj, "value") else str(stage_obj or "")
                if terminal_error_delta is not None:
                    public_err = from_stream_delta(terminal_error_delta, stage=stage_name, agent=agent_upper)
                else:
                    public_err = internal_runtime_error(stage=stage_name, agent=agent_upper)
                self._record_public_error(context, public_err)
                logger.warning("Agent %s model stream failed with %s", agent_name, public_err.code)
                return None, public_err.code
''',
)
replace_once(
    "runtime/engine.py",
    '''            err = resp.error or f"MODEL_RESPONSE_{resp.status.value}"
            logger.warning(f"Agent {agent_name} LLM call failed: {err}")
            return None, err
        except Exception as e:
            logger.warning(f"Agent {agent_name} LLM call exception: {e}")
            return None, str(e)
''',
    '''            stage_name = stage_obj.value if hasattr(stage_obj, "value") else str(stage_obj or "")
            public_err = from_model_response(resp, stage=stage_name, agent=agent_upper)
            self._record_public_error(context, public_err)
            logger.warning("Agent %s model call failed with %s", agent_name, public_err.code)
            return None, public_err.code
        except (GeneratorExit, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            stage_name = stage_obj.value if hasattr(stage_obj, "value") else str(stage_obj or "")
            public_err = internal_runtime_error(stage=stage_name, agent=agent_upper)
            self._record_public_error(context, public_err)
            logger.error("Agent %s model call failed at runtime boundary (%s)", agent_name, type(exc).__name__)
            return None, public_err.code
''',
)

# Performance must not invent a target or measurement. No KPI tool call occurs
# without real campaign metric inputs.
replace_once(
    "runtime/engine.py",
    '''        # Invoke ToolGateway for analytics calculation
        idem_key = f"{context.run_id}:performance:kpi_calculation:cac"
        if idem_key in self._executed_tool_idempotency_keys:
            calc_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            calc_req = ToolRequest(
                run_id=context.run_id,
                agent_id="performance",
                capability_id="kpi_calculation",
                parameters={"metric_name": "target_cac", "target_value": 150.0},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            calc_receipt = self.tool_gateway.execute(calc_req)
            self._executed_tool_idempotency_keys[idem_key] = calc_receipt

        context.execution_receipt_refs.append(calc_receipt.execution_id)
        self.lineage_inspector.add_receipt(calc_receipt)

        # Grounded Context Compilation with KPI calc tool receipt
        grounded_pkg = self.context_compiler.compile_grounded_package("performance", context, tool_receipts=[calc_receipt])
''',
    '''        # Planning and measurement are separate. This stage has no campaign
        # telemetry input by default, so it must not manufacture a target/metric
        # or invoke a KPI calculator with invented values.
        calc_receipt = None
        grounded_pkg = self.context_compiler.compile_grounded_package("performance", context, tool_receipts=[])
''',
)
replace_all("runtime/engine.py", '"calc_receipt_id": calc_receipt.execution_id,', '"calc_receipt_id": None,', minimum=3)

# Unexpected orchestration exceptions must never publish arbitrary exception text
# and Final CMO is NOT_REACHED unless it was actually executing.
replace_once(
    "runtime/engine.py",
    '''            else:
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
                    "master_gtm_plan_markdown": f"# BÁO CÁO PHÊ DUYỆT THẤT BẠI — FIVE-AGENT DEPARTMENT\n\n**Trạng thái phê duyệt**: KHÔNG ĐƯỢC PHÊ DUYỆT (UNHANDLED_RUNTIME_EXCEPTION)\n\nLỗi hệ thống trong quá trình thực thi pipeline: {str(exc)}",
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
''',
    '''            else:
                stage_obj = runtime_stage_to_progress_stage(context.current_stage)
                stage_name = stage_obj.value if hasattr(stage_obj, "value") else str(stage_obj or "")
                stage_to_agent = {
                    "CMO_INITIAL": "CMO", "INTELLIGENCE": "INTELLIGENCE", "STRATEGIST": "STRATEGIST",
                    "CREATIVE": "CREATIVE", "PERFORMANCE": "PERFORMANCE", "FINAL_CMO": "CMO",
                }
                failed_agent = stage_to_agent.get(stage_name, "")
                public_err = internal_runtime_error(stage=stage_name, agent=failed_agent)
                self._record_public_error(context, public_err)
                logger.error("Unhandled runtime exception in run %s (%s)", context.run_id, type(exc).__name__)
                context.status = RuntimeStatus.FAILED
                context.risk_flags.append("RUNTIME_INTERNAL_ERROR")
                final_was_reached = stage_name == "FINAL_CMO"
                cmo_final = {
                    "stage": "FINAL_CMO",
                    "agent": "cmo",
                    "status": "FAILED" if final_was_reached else "NOT_REACHED",
                    "approval_status": "NOT_EVALUATED",
                    "reason": public_err.code,
                    "error": public_err.code,
                    "failed_stage": stage_name or None,
                    "public_error": public_err.model_dump(),
                    "master_gtm_plan": {},
                    "master_gtm_plan_markdown": "# BÁO CÁO THỰC THI THẤT BẠI\n\nQuy trình dừng do lỗi runtime nội bộ. Không có bước Final CMO giả lập nào được thực thi.",
                }
                context.stage_outputs["final_cmo"] = cmo_final
                context.create_checkpoint()
                if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                    emitter.emit(
                        ProgressEventType.RUN_FAILED,
                        stage=stage_obj,
                        agent=failed_agent or None,
                        message="Quy trình thực thi gặp lỗi runtime nội bộ",
                        metadata={"error": public_err.model_dump()},
                    )
''',
)

# ---------------------------------------------------------------------------
# chat/engine.py — capability honesty + same-chat context + typed provider errors.
# ---------------------------------------------------------------------------
replace_once("chat/engine.py", "from typing import Any, Dict, List, Optional\n", "from typing import Any, Callable, Dict, List, Optional\n")
replace_once(
    "chat/engine.py",
    '            "- Never fabricate facts or make up private reasoning.\\n"\n',
    '            "- Never fabricate facts or make up private reasoning.\\n"\n'
    '            "- Never claim you sent email, launched ads, changed budgets, published content, edited an external account, or completed any external action unless an authorized tool execution receipt in this turn proves it. Otherwise describe it as a plan, draft, or capability that still requires execution.\\n"\n',
)
replace_once(
    "chat/engine.py",
    '''        history_msgs = [m for m in session.messages if m.content != user_message]
        recent_history = history_msgs[-8:]
''',
    '''        history_msgs = list(session.messages)
        if history_msgs:
            last = history_msgs[-1]
            last_role = last.role.value if hasattr(last.role, "value") else str(last.role)
            if last_role == ChatRole.USER.value and last.content == user_message:
                history_msgs = history_msgs[:-1]
        recent_history = history_msgs[-12:]
''',
)
replace_once(
    "chat/engine.py",
    "from runtime.progress import (\n",
    "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\nfrom runtime.progress import (\n",
)
replace_once(
    "chat/engine.py",
    '''            had_error = False
            error_detail = ""

            try:
                stream_gen = self.model_gateway.generate_stream(req)
                for delta in stream_gen:
                    if delta.provider:
                        last_provider = delta.provider
                    if delta.model_name:
                        last_model_name = delta.model_name
                    if delta.content:
                        chunks.append(delta.content)
                        text_delta_sink(delta.content)
                    if delta.finish_reason == "error":
                        had_error = True
                        error_detail = "Model provider streaming encountered an error."
            except Exception as ex:
                had_error = True
                error_detail = str(ex)

            if chunks and not had_error:
''',
    '''            public_error = None

            try:
                stream_gen = self.model_gateway.generate_stream(req)
                for delta in stream_gen:
                    if delta.provider:
                        last_provider = delta.provider
                    if delta.model_name:
                        last_model_name = delta.model_name
                    if delta.content:
                        chunks.append(delta.content)
                        text_delta_sink(delta.content)
                    if delta.finish_reason == "error":
                        public_error = from_stream_delta(delta, stage="GENERAL_CONVERSATION", agent="")
                        break
            except (GeneratorExit, KeyboardInterrupt, SystemExit):
                raise
            except Exception as ex:
                logger.error("General chat stream failed at runtime boundary (%s)", type(ex).__name__)
                public_error = internal_runtime_error(stage="GENERAL_CONVERSATION", agent="")

            if chunks and public_error is None:
''',
)
replace_once(
    "chat/engine.py",
    '''            sanitized_error = (
                "Không thể kết nối đến nhà cung cấp mô hình AI (Model Provider). Vui lòng kiểm tra cấu hình provider hoặc chọn model khác."
                if ("WinError" in error_detail or "HTTP 599" in error_detail or "refused" in error_detail.lower())
                else (error_detail or "Model provider streaming failed.")
            )
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    message=f"Không thể kết nối đến nhà cung cấp mô hình AI: {sanitized_error}",
                    metadata={"error": error_detail},
                )
            return {
                "success": False,
                "error": error_detail or sanitized_error,
                "content": f"⚠️ Không thể hoàn tất phản hồi: {sanitized_error}\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
            }
''',
    '''            if public_error is None:
                public_error = internal_runtime_error(stage="GENERAL_CONVERSATION", agent="")
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    message=public_error.safe_message,
                    metadata={"error": public_error.model_dump()},
                )
            return {
                "success": False,
                "error": public_error.code,
                "public_error": public_error.model_dump(),
                "content": f"⚠️ Không thể hoàn tất phản hồi: {public_error.safe_message}\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
            }
''',
)
replace_once(
    "chat/engine.py",
    '''        error_detail = resp.error or "Model provider is currently unavailable or quota limit reached."
        logger.warning(f"UniversalModelGateway chat generation error: {error_detail}")
''',
    '''        public_error = from_model_response(resp, stage="GENERAL_CONVERSATION", agent="")
        logger.warning("UniversalModelGateway chat generation failed with %s", public_error.code)
''',
)
replace_once(
    "chat/engine.py",
    '''        sanitized_error = (
            "Không thể kết nối đến nhà cung cấp mô hình AI (Model Provider). Vui lòng kiểm tra cấu hình provider hoặc chọn model khác."
            if ("WinError" in error_detail or "HTTP 599" in error_detail or "refused" in error_detail.lower())
            else error_detail
        )
        if emitter:
            emitter.emit(
                ProgressEventType.RUN_FAILED,
                message=f"Không thể kết nối đến nhà cung cấp mô hình AI: {sanitized_error}",
                metadata={"error": error_detail},
            )
        return {
            "success": False,
            "error": error_detail,
            "content": f"⚠️ Không thể hoàn tất phản hồi: {sanitized_error}\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
        }
''',
    '''        if emitter:
            emitter.emit(
                ProgressEventType.RUN_FAILED,
                message=public_error.safe_message,
                metadata={"error": public_error.model_dump()},
            )
        return {
            "success": False,
            "error": public_error.code,
            "public_error": public_error.model_dump(),
            "content": f"⚠️ Không thể hoàn tất phản hồi: {public_error.safe_message}\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
        }
''',
)

# ---------------------------------------------------------------------------
# app_api/server.py — follow-up resolution and structured safe errors.
# ---------------------------------------------------------------------------
replace_once(
    "app_api/server.py",
    "from chat.engine import ChatConversationEngine\n",
    "from chat.engine import ChatConversationEngine\nfrom chat.conversation_state import FollowupIntent, resolve_conversation_turn\n",
)
replace_once(
    "app_api/server.py",
    "from runtime.context_compiler import ContextCompiler\n",
    "from runtime.context_compiler import ContextCompiler\nfrom runtime.public_errors import internal_runtime_error\n",
)
# Resolve before each routing call (stream + sync).
old_route = '''                decision = APP_BACKEND.conversation_router.route(
                    message=user_text,
                    attachments=parsed_attachments,
                    chat_history=session.messages,
                    project_id=session.optional_project_id,
                    business_id=session.optional_business_id,
                )
'''
new_route = '''                resolved_turn = resolve_conversation_turn(session.messages, user_text)
                route_text = resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text
                decision = APP_BACKEND.conversation_router.route(
                    message=route_text,
                    attachments=parsed_attachments,
                    chat_history=session.messages,
                    project_id=session.optional_project_id,
                    business_id=session.optional_business_id,
                )
                if resolved_turn.followup_intent == FollowupIntent.TRANSFORM_EXISTING:
                    from chat.router import RoutingDecision
                    decision = RoutingDecision(ConversationIntent.GENERAL_CONVERSATION, 1.0, resolved_turn.reason_code)
                elif resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH:
                    from chat.router import RoutingDecision
                    decision = RoutingDecision(ConversationIntent.RESEARCH_INQUIRY, 1.0, resolved_turn.reason_code, {"research_depth": "DEEP"})
'''
replace_once("app_api/server.py", old_route, new_route)
old_route_sync = old_route.replace("                decision", "            decision").replace("                    message", "                message").replace("                    attachments", "                attachments").replace("                    chat_history", "                chat_history").replace("                    project_id", "                project_id").replace("                    business_id", "                business_id").replace("                )", "            )")
# The generated indentation transform is intentionally not used; patch exact sync block separately.
replace_once(
    "app_api/server.py",
    '''            decision = APP_BACKEND.conversation_router.route(
                message=user_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
''',
    '''            resolved_turn = resolve_conversation_turn(session.messages, user_text)
            route_text = resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text
            decision = APP_BACKEND.conversation_router.route(
                message=route_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
            if resolved_turn.followup_intent == FollowupIntent.TRANSFORM_EXISTING:
                from chat.router import RoutingDecision
                decision = RoutingDecision(ConversationIntent.GENERAL_CONVERSATION, 1.0, resolved_turn.reason_code)
            elif resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH:
                from chat.router import RoutingDecision
                decision = RoutingDecision(ConversationIntent.RESEARCH_INQUIRY, 1.0, resolved_turn.reason_code, {"research_depth": "DEEP"})
''',
)
# Research must execute the resolved objective when deepening.
replace_all(
    "app_api/server.py",
    "                        objective=user_text,\n",
    "                        objective=(resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text),\n",
    minimum=1,
)
replace_all(
    "app_api/server.py",
    "                    objective=user_text,\n",
    "                    objective=(resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text),\n",
    minimum=1,
)
# General/document errors should send the typed public error, not a flattened string.
replace_all(
    "app_api/server.py",
    '                        bridge.send_error(res.get("error") or "Execution failed")',
    '                        bridge.send_error(res.get("public_error") or internal_runtime_error(stage=decision.intent.value).model_dump())',
    minimum=2,
)
replace_once(
    "app_api/server.py",
    '                        bridge.send_error(intel_out.get("error") or "RESEARCH_FAILED")\n',
    '                        bridge.send_error(APP_BACKEND.runtime.get_public_error(ctx.run_id) or internal_runtime_error(stage="INTELLIGENCE", agent="INTELLIGENCE").model_dump())\n',
)
replace_once(
    "app_api/server.py",
    '''                        root_err = cmo_final.get("error") or cmo_final.get("reason") or "WORKFLOW_FAILED"
                        failed_stg = cmo_final.get("failed_stage")
                        if failed_stg and root_err and not str(root_err).startswith(failed_stg):
                            err_msg = f"{failed_stg}: {root_err}"
                        else:
                            err_msg = str(root_err)
                        bridge.send_error(err_msg)
''',
    '''                        bridge.send_error(
                            cmo_final.get("public_error")
                            or APP_BACKEND.runtime.get_public_error(ctx.run_id)
                            or internal_runtime_error(stage=cmo_final.get("failed_stage") or "").model_dump()
                        )
''',
)
replace_once(
    "app_api/server.py",
    '''            except Exception as ex:
                logger.exception(f"Streaming execution error for chat {chat_id}: {ex}")
                bridge.send_error(ex)
''',
    '''            except Exception as ex:
                logger.error("Streaming execution failed for chat %s (%s)", chat_id, type(ex).__name__)
                bridge.send_error(internal_runtime_error(stage="STREAMING_API").model_dump())
''',
)

# ---------------------------------------------------------------------------
# tools/adapters.py — mock adapters can never masquerade as real success.
# ---------------------------------------------------------------------------
replace_once(
    "tools/adapters.py",
    '''        # Mock / Provider-neutral search results
        results = [
            {"title": f"Market Research for {query}", "snippet": f"Verified qualitative insights regarding {query}", "url": f"https://example.com/research?q={query}"}
        ]
        return AdapterResult(
            success=True,
            data={"query": query, "results": results, "result_count": len(results)},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="SEARCH_PROVIDER_NOT_CONFIGURED",
            error_message="No real search provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        return AdapterResult(
            success=True,
            data={
                "url": url,
                "content_type": "text/html",
                "extracted_text": f"Simulated content extracted from {url}",
                "headings": ["Overview", "Key Findings"],
            },
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="HTTP_PROVIDER_NOT_CONFIGURED",
            error_message="No real webpage reader is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        return AdapterResult(
            success=True,
            data={"generated_copy": f"Drafted copy for: {prompt[:60]}...", "word_count": 42},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="TEXT_TOOL_NOT_CONFIGURED",
            error_message="No executable text-generation tool is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        asset_type = "video" if "video" in capability_id else "image"
        artifact_id = f"art-{asset_type}-{int(time.time())}"
        return AdapterResult(
            success=True,
            data={"asset_id": artifact_id, "asset_type": asset_type, "status": "RENDERED", "format": "png" if asset_type == "image" else "mp4"},
            artifact_refs=[artifact_id],
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        asset_type = "video" if "video" in capability_id else "image"
        return AdapterResult(
            success=False,
            data={"asset_type": asset_type, "status": "NOT_EXECUTED"},
            error_code="MEDIA_PROVIDER_NOT_CONFIGURED",
            error_message="No real media renderer is bound. A creative specification may be produced, but no asset was rendered.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        platform = parameters.get("platform", "generic")
        return AdapterResult(
            success=True,
            data={"publish_id": f"PUB-{int(time.time())}", "platform": platform, "status": "PUBLISHED_OR_QUEUED"},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.SANDBOX,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="PUBLISH_PROVIDER_NOT_CONFIGURED",
            error_message="No publishing connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        metric_name = parameters.get("metric_name", "roas")
        return AdapterResult(
            success=True,
            data={
                "metric": metric_name,
                "value": 3.45,
                "confidence_interval": [3.12, 3.78],
                "sample_size": 14200,
                "p_value": 0.012,
            },
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="ANALYTICS_PROVIDER_NOT_CONFIGURED",
            error_message="No real analytics dataset/provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '''        action = "read" if "read" in capability_id else "write"
        path = parameters.get("path", "workspace/output.txt")
        return AdapterResult(
            success=True,
            data={"path": path, "action": action, "bytes_processed": 1024},
            artifact_refs=[path],
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
    '''        return AdapterResult(
            success=False,
            error_code="FILE_PROVIDER_NOT_CONFIGURED",
            error_message="No real file connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''',
)
replace_once(
    "tools/adapters.py",
    '                "language": parameters.get("language", "en"),\n',
    '                "language": parameters.get("language") or ("vi" if any(ch in query.lower() for ch in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ") else "en"),\n',
)
replace_once(
    "tools/adapters.py",
    '''        except Exception as exc:
            return AdapterResult(
                success=False,
                error_code="OBSERVATION_GATEWAY_ERROR",
                error_message=str(exc),
''',
    '''        except Exception as exc:
            return AdapterResult(
                success=False,
                error_code="OBSERVATION_GATEWAY_ERROR",
                error_message=f"Observation gateway failed ({type(exc).__name__}).",
''',
)

# ToolGateway receipts cannot persist arbitrary exception strings.
replace_once(
    "tools/tool_gateway.py",
    '            err_msg = adapter_res.error_message if adapter_res else str(last_exc)\n',
    '            err_msg = adapter_res.error_message if adapter_res else (f"Adapter execution failed ({type(last_exc).__name__})." if last_exc else "Adapter execution failed.")\n',
)

# Real analytics: computed KPI is REAL when based on explicit caller inputs;
# attribution/experiment analysis without supplied observations is unavailable.
replace_once(
    "connectors/analytics_connector.py",
    '''                execution_mode=ExecutionMode.MOCK,
            )

        elif cap in ("attribution_data_access", "experiment_result_analysis"):
            return AdapterResult(
                success=True,
                data={
                    "attribution_model": "DATA_DRIVEN_MULTI_TOUCH",
                    "channel_weights": {"paid_search": 0.42, "paid_social": 0.38, "direct": 0.20},
                    "stat_sig": True,
                    "p_value": 0.008,
                },
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )
''',
    '''                execution_mode=ExecutionMode.REAL,
            )

        elif cap in ("attribution_data_access", "experiment_result_analysis"):
            return AdapterResult(
                success=False,
                error_code="MISSING_OBSERVED_DATA",
                error_message="Attribution or experiment conclusions require explicit observed campaign/experiment data.",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )
''',
)

# React should pass the structured terminal error to stage/agent reducers.
replace_once(
    "frontend/src/App.tsx",
    '''        setWorkflowStages((prev) => applyTerminalErrorToStages(prev));
        setAgentStates((prev) => applyTerminalErrorToAgents(prev));
''',
    '''        setWorkflowStages((prev) => applyTerminalErrorToStages(prev, err));
        setAgentStates((prev) => applyTerminalErrorToAgents(prev, err));
''',
)
# Prefer canonical safe_message from backend.
replace_once(
    "frontend/src/App.tsx",
    "        const safeDetail = err.message || 'Không thể nhận phản hồi từ backend.';\n",
    "        const safeDetail = err.safe_message || err.message || 'Không thể nhận phản hồi từ backend.';\n",
)

print("full hardening deterministic patch applied")
