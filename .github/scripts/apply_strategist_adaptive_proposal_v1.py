from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")

strategy_anchor = '''        # Dynamic LLM Strategy
        sys_prompt = (
'''
strategy_replacement = '''        # CMO/model output may recommend WHAT Strategist should focus on, but
        # AdaptiveTaskCompiler remains the scheduling/dependency authority. This
        # block intentionally runs only after the mandatory Intelligence gate
        # above, so a proposal can never bypass top-level stage dependencies.
        cmo_stage_output = context.stage_outputs.get("cmo_initial", {})
        raw_adaptive_proposals = (
            cmo_stage_output.get("adaptive_task_proposals")
            if isinstance(cmo_stage_output, dict)
            else None
        )
        compiled_adaptive_plan = AdaptiveTaskCompiler().compile(raw_adaptive_proposals)
        strategist_tasks = tuple(
            task
            for task in compiled_adaptive_plan.tasks
            if task.task_kind == "strategist.positioning" and task.agent_id == "strategist"
        )
        strategist_task = strategist_tasks[0] if strategist_tasks else None
        strategist_focus = (
            strategist_task.instruction[:_MAX_ADAPTIVE_TASK_INSTRUCTION_CHARS].strip()
            if strategist_task and strategist_task.instruction
            else ""
        )
        context.working_state["strategist_adaptive_task_plan"] = {
            "mode": "TRUSTED_CMO_PROPOSAL" if strategist_task else "DEFAULT_STAGE_POLICY",
            "selected_task_kind": strategist_task.task_kind if strategist_task else None,
            "selected_task_id": strategist_task.task_id if strategist_task else None,
            "runtime_dependencies": sorted(strategist_task.depends_on) if strategist_task else [],
            "rejected_kinds": list(compiled_adaptive_plan.rejected_kinds),
            "compiled_waves": [list(wave) for wave in compiled_adaptive_plan.execution_plan.waves],
            "ignored_duplicate_count": max(0, len(strategist_tasks) - 1),
        }

        # Dynamic LLM Strategy
        sys_prompt = (
'''
if text.count(strategy_anchor) != 1:
    raise SystemExit(f"STRATEGY_ANCHOR_MISMATCH: {text.count(strategy_anchor)}")
text = text.replace(strategy_anchor, strategy_replacement, 1)

prompt_anchor = '''        intel_findings = context.stage_outputs.get("intelligence", {}).get("market_findings", "")
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Objective: {context.objective}\\nIntelligence Research: {intel_findings}\\n\\n{evidence_section}".strip()
        user_prompt = self._append_governance_block(context, user_prompt)
'''
prompt_replacement = '''        intel_findings = context.stage_outputs.get("intelligence", {}).get("market_findings", "")
        evidence_section = grounded_pkg.render_prompt_section()
        prompt_parts = [
            f"Objective: {context.objective}",
            f"Intelligence Research: {intel_findings}",
        ]
        if strategist_focus:
            prompt_parts.append(
                "CMO Adaptive Task Focus (model recommendation, not authority): "
                + strategist_focus
            )
        prompt_parts.append(evidence_section)
        user_prompt = "\\n\\n".join(prompt_parts).strip()
        user_prompt = self._append_governance_block(context, user_prompt)
'''
if text.count(prompt_anchor) != 1:
    raise SystemExit(f"STRATEGIST_PROMPT_ANCHOR_MISMATCH: {text.count(prompt_anchor)}")
text = text.replace(prompt_anchor, prompt_replacement, 1)

path.write_text(text, encoding="utf-8")
