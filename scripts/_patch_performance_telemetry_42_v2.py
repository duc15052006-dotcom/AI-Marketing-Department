from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")
stage_start = text.index("    def execute_stage_performance(")
stage_end = text.index("    # ------------------------------------------------------------------\n    # Final CMO", stage_start)
before = text[:stage_start]
stage = text[stage_start:stage_end]
after = text[stage_end:]

old_tool_start = "        # Invoke ToolGateway for analytics calculation\n"
old_tool_end = '        prov_map = context.working_state.setdefault("provenance_index", {})\n'
if stage.count(old_tool_start) != 1 or stage.count(old_tool_end) != 1:
    raise SystemExit(
        f"TOOL_ANCHORS start={stage.count(old_tool_start)} end={stage.count(old_tool_end)}"
    )
a = stage.index(old_tool_start)
b = stage.index(old_tool_end, a)
new_tool_block = '''        # Retrieve observed campaign telemetry through ToolGateway. A REAL
        # analytics receipt may enter grounded evidence; NO_DATA and legacy
        # MOCK analytics remain auditable receipts but are never promoted as
        # empirical Performance evidence.
        idem_key = f"{context.run_id}:performance:analytics_retrieval:{context.campaign_id}"
        if idem_key in self._executed_tool_idempotency_keys:
            analytics_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            analytics_req = ToolRequest(
                run_id=context.run_id,
                agent_id="performance",
                capability_id="analytics_retrieval",
                parameters={"campaign_id": context.campaign_id},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            analytics_receipt = self.tool_gateway.execute(analytics_req)
            self._executed_tool_idempotency_keys[idem_key] = analytics_receipt

        context.execution_receipt_refs.append(analytics_receipt.execution_id)
        self.lineage_inspector.add_receipt(analytics_receipt)

        receipt_mode = getattr(analytics_receipt.execution_mode, "value", str(analytics_receipt.execution_mode)).upper()
        has_real_telemetry = (
            analytics_receipt.status == ExecutionStatus.SUCCESS and receipt_mode == "REAL"
        )
        if has_real_telemetry:
            telemetry_status = "REAL_AVAILABLE"
        elif analytics_receipt.status != ExecutionStatus.SUCCESS:
            error_code = analytics_receipt.error_class or analytics_receipt.status.value
            telemetry_status = f"NO_OBSERVED_DATA:{error_code}"
        else:
            telemetry_status = f"NON_REAL_TELEMETRY_IGNORED:{receipt_mode or 'UNKNOWN'}"

        grounded_receipts = [analytics_receipt] if has_real_telemetry else []
        grounded_pkg = self.context_compiler.compile_grounded_package(
            "performance", context, tool_receipts=grounded_receipts
        )
'''
stage = stage[:a] + new_tool_block + stage[b:]

import re
failed_pattern = re.compile(r'^                "calc_receipt_id": calc_receipt\.execution_id,$', re.MULTILINE)
completed_pattern = re.compile(r'^            "calc_receipt_id": calc_receipt\.execution_id,$', re.MULTILINE)
if len(failed_pattern.findall(stage)) != 2:
    raise SystemExit(f"FAILED_RECEIPT_FIELD_COUNT={len(failed_pattern.findall(stage))}")
if len(completed_pattern.findall(stage)) != 1:
    raise SystemExit(f"COMPLETED_RECEIPT_FIELD_COUNT={len(completed_pattern.findall(stage))}")
stage = failed_pattern.sub(
    '                "analytics_receipt_id": analytics_receipt.execution_id,\n'
    '                "analytics_data_status": telemetry_status,\n'
    '                "calc_receipt_id": None,',
    stage,
)
stage = completed_pattern.sub(
    '            "analytics_receipt_id": analytics_receipt.execution_id,\n'
    '            "analytics_data_status": telemetry_status,\n'
    '            "calc_receipt_id": None,',
    stage,
)

evidence_anchor = "        evidence_section = grounded_pkg.render_prompt_section()\n"
if stage.count(evidence_anchor) != 1:
    raise SystemExit(f"EVIDENCE_ANCHOR_COUNT={stage.count(evidence_anchor)}")
stage = stage.replace(
    evidence_anchor,
    '        evidence_section = (\n'
    '            f"OBSERVED TELEMETRY STATUS: {telemetry_status}\\n"\n'
    '            f"{grounded_pkg.render_prompt_section()}"\n'
    '        )\n',
    1,
)

updated = before + stage + after
if updated == text:
    raise SystemExit("NO_CHANGE")
path.write_text(updated, encoding="utf-8")
