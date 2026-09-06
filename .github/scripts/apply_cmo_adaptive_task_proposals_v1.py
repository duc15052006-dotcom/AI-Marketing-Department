from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")

old_import = "from runtime.dependency_scheduler import DependencyAwareScheduler, RuntimeTaskSpec\n"
new_import = "from runtime.dependency_scheduler import AdaptiveTaskCompiler, DependencyAwareScheduler, RuntimeTaskSpec\n"
if text.count(old_import) != 1:
    raise SystemExit(f"DEPENDENCY_IMPORT_ANCHOR_MISMATCH: {text.count(old_import)}")
text = text.replace(old_import, new_import, 1)

helper_anchor = '''_FORBIDDEN_AUTO_PUBLISH_PHRASES = (
    "auto-publish", "automatic publishing", "publish immediately",
    "tự động đăng", "đăng tự động", "đăng ngay lập tức",
)


def extract_explicit_user_constraints(raw_text: str) -> List[str]:
'''
helper_replacement = '''_FORBIDDEN_AUTO_PUBLISH_PHRASES = (
    "auto-publish", "automatic publishing", "publish immediately",
    "tự động đăng", "đăng tự động", "đăng ngay lập tức",
)

_ADAPTIVE_TASK_PROPOSAL_BLOCK_RE = re.compile(
    r"<ADAPTIVE_TASK_PROPOSALS>\\s*(?P<payload>.*?)\\s*</ADAPTIVE_TASK_PROPOSALS>",
    re.IGNORECASE | re.DOTALL,
)
_MAX_ADAPTIVE_TASK_PROPOSALS = 12
_MAX_ADAPTIVE_TASK_INSTRUCTION_CHARS = 2000


def _extract_adaptive_task_proposals(raw_text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Extract untrusted CMO task proposals without granting scheduling authority.

    Only ``kind`` and human-readable ``instruction`` are transported. Any model
    fields that resemble runtime authority (dependencies, resource scopes,
    side-effect flags, agent identity, parallel hints, etc.) are discarded here
    and are independently reconstructed by ``AdaptiveTaskCompiler`` later.
    Malformed or multiple proposal blocks fail closed to an empty proposal set.
    """

    if not isinstance(raw_text, str):
        return "", []

    matches = list(_ADAPTIVE_TASK_PROPOSAL_BLOCK_RE.finditer(raw_text))
    clean_text = _ADAPTIVE_TASK_PROPOSAL_BLOCK_RE.sub("", raw_text).strip()
    if len(matches) != 1:
        return clean_text, []

    try:
        payload = json.loads(matches[0].group("payload"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return clean_text, []

    if not isinstance(payload, list):
        return clean_text, []

    proposals: List[Dict[str, str]] = []
    for raw in payload[:_MAX_ADAPTIVE_TASK_PROPOSALS]:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        instruction = raw.get("instruction", "")
        if not isinstance(kind, str) or not kind.strip():
            continue
        if not isinstance(instruction, str):
            instruction = ""
        proposals.append(
            {
                "kind": kind.strip(),
                "instruction": instruction.strip()[:_MAX_ADAPTIVE_TASK_INSTRUCTION_CHARS],
            }
        )
    return clean_text, proposals


def extract_explicit_user_constraints(raw_text: str) -> List[str]:
'''
if text.count(helper_anchor) != 1:
    raise SystemExit(f"HELPER_ANCHOR_MISMATCH: {text.count(helper_anchor)}")
text = text.replace(helper_anchor, helper_replacement, 1)

old_cmo_prompt = '''        sys_prompt = (
            "You are the Chief Marketing Officer (CMO) and Executive Master Orchestrator of the Five-Agent AI Marketing Department.\\n"
            "Decompose the user's commercial marketing objective into clear, structured delegation directives for:\\n"
            "- Intelligence: Competitor & market research focus\\n"
            "- Strategist: Value proposition & audience positioning\\n"
            "- Creative: High-converting hooks & multimedia concept directions\\n"
            "- Performance: KPI tree, attribution model & budget allocation\\n"
            "Mirror the language of the user objective (Vietnamese/English)."
        )
'''
new_cmo_prompt = '''        sys_prompt = (
            "You are the Chief Marketing Officer (CMO) and Executive Master Orchestrator of the Five-Agent AI Marketing Department.\\n"
            "Decompose the user's commercial marketing objective into clear, structured delegation directives for:\\n"
            "- Intelligence: Competitor & market research focus\\n"
            "- Strategist: Value proposition & audience positioning\\n"
            "- Creative: High-converting hooks & multimedia concept directions\\n"
            "- Performance: KPI tree, attribution model & budget allocation\\n"
            "Mirror the language of the user objective (Vietnamese/English).\\n"
            "After the strategic prose, append exactly one <ADAPTIVE_TASK_PROPOSALS> JSON block containing a JSON array. "
            "Each item may contain only a task kind and a human-readable instruction. Choose only useful kinds from: "
            "intelligence.market, intelligence.competitors, intelligence.customers, strategist.positioning, "
            "creative.angles, performance.plan, cmo.final. Do not provide dependencies, parallel/sequential hints, "
            "resource scopes, side-effect flags, or agent identity; runtime code owns all scheduling authority.\\n"
            "Example format: <ADAPTIVE_TASK_PROPOSALS>[{\\\"kind\\\":\\\"intelligence.market\\\",\\\"instruction\\\":\\\"Research category demand\\\"}]</ADAPTIVE_TASK_PROPOSALS>"
        )
'''
if text.count(old_cmo_prompt) != 1:
    raise SystemExit(f"CMO_PROMPT_ANCHOR_MISMATCH: {text.count(old_cmo_prompt)}")
text = text.replace(old_cmo_prompt, new_cmo_prompt, 1)

old_cmo_output_anchor = '''        output = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "COMPLETED",
            "strategic_intent": strip_handoff_block(llm_output),
            "delegation_plan": {
'''
new_cmo_output_anchor = '''        clean_cmo_output, adaptive_task_proposals = _extract_adaptive_task_proposals(llm_output)

        output = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "COMPLETED",
            "strategic_intent": strip_handoff_block(clean_cmo_output),
            "adaptive_task_proposals": adaptive_task_proposals,
            "delegation_plan": {
'''
if text.count(old_cmo_output_anchor) != 1:
    raise SystemExit(f"CMO_OUTPUT_ANCHOR_MISMATCH: {text.count(old_cmo_output_anchor)}")
text = text.replace(old_cmo_output_anchor, new_cmo_output_anchor, 1)

old_finalize = '''        output, _payload, _parse_status = self._finalize_stage_handoff(
            context, "cmo_initial", "cmo", llm_output, output, delegation=output.get("delegation_plan"),
        )
'''
new_finalize = '''        output, _payload, _parse_status = self._finalize_stage_handoff(
            context, "cmo_initial", "cmo", clean_cmo_output, output, delegation=output.get("delegation_plan"),
        )
'''
if text.count(old_finalize) != 1:
    raise SystemExit(f"CMO_FINALIZE_ANCHOR_MISMATCH: {text.count(old_finalize)}")
text = text.replace(old_finalize, new_finalize, 1)

old_research_block = '''        # Runtime-owned research decomposition. These acquisition tasks have
        # known, isolated write scopes, so the dependency scheduler may execute
        # them in one parallel wave. Worker threads return receipts only; all
        # RuntimeContext and lineage mutation stays on this caller thread.
        research_tasks = (
            RuntimeTaskSpec(
                task_id="intelligence-market",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.market"}),
                task_kind="intelligence.market",
                instruction=f"{context.objective} market landscape trends demand",
            ),
            RuntimeTaskSpec(
                task_id="intelligence-competitors",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.competitors"}),
                task_kind="intelligence.competitors",
                instruction=f"{context.objective} competitors alternatives benchmarks",
            ),
            RuntimeTaskSpec(
                task_id="intelligence-customers",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.customers"}),
                task_kind="intelligence.customers",
                instruction=f"{context.objective} customer motivations pain points objections",
            ),
        )
        research_scheduler = DependencyAwareScheduler(max_workers=3)
        research_plan = research_scheduler.plan(research_tasks)
'''
new_research_block = '''        # CMO/model output may propose WHAT trusted work is useful, but the
        # runtime remains the sole scheduling authority. ``AdaptiveTaskCompiler``
        # reconstructs dependencies/resource scopes from code-owned templates and
        # ignores every model-supplied scheduling field.
        cmo_stage_output = context.stage_outputs.get("cmo_initial", {})
        proposals_present = (
            isinstance(cmo_stage_output, dict)
            and "adaptive_task_proposals" in cmo_stage_output
        )
        rejected_kinds: Tuple[str, ...] = ()

        if proposals_present:
            compiled_plan = AdaptiveTaskCompiler().compile(
                cmo_stage_output.get("adaptive_task_proposals")
            )
            rejected_kinds = compiled_plan.rejected_kinds
            intelligence_kind_order = {
                "intelligence.market": 10,
                "intelligence.competitors": 20,
                "intelligence.customers": 30,
            }
            research_tasks = tuple(
                sorted(
                    (task for task in compiled_plan.tasks if task.agent_id == "intelligence"),
                    key=lambda task: (
                        intelligence_kind_order.get(task.task_kind, 999),
                        task.task_id,
                    ),
                )
            )
            if research_tasks:
                research_mode = "ADAPTIVE_CMO_PROPOSAL"
            else:
                # Fail closed: an explicit but unusable proposal set never gains
                # parallel authority. Preserve one legacy sequential search so
                # downstream stages still receive a minimum research attempt.
                research_mode = "SEQUENTIAL_FALLBACK"
                research_tasks = (
                    RuntimeTaskSpec(
                        task_id="intelligence-legacy-fallback",
                        agent_id="intelligence",
                        reads=frozenset({"objective", "grounded_context"}),
                        writes=frozenset({"isolated.intelligence.legacy"}),
                        task_kind="intelligence.legacy_fallback",
                        instruction=context.objective,
                    ),
                )
        else:
            # Backward-compatibility only for pre-feature/manual RuntimeContext
            # fixtures that do not contain the proposal key at all. Real CMO
            # execution now always writes the key, including [] on fail-closed
            # parse, so production missing/malformed proposals take the branch
            # above and execute one sequential fallback search.
            research_mode = "LEGACY_TRUSTED_DEFAULT"
            research_tasks = (
                RuntimeTaskSpec(
                    task_id="intelligence-market",
                    agent_id="intelligence",
                    reads=frozenset({"objective", "grounded_context"}),
                    writes=frozenset({"isolated.intelligence.market"}),
                    task_kind="intelligence.market",
                    instruction=f"{context.objective} market landscape trends demand",
                ),
                RuntimeTaskSpec(
                    task_id="intelligence-competitors",
                    agent_id="intelligence",
                    reads=frozenset({"objective", "grounded_context"}),
                    writes=frozenset({"isolated.intelligence.competitors"}),
                    task_kind="intelligence.competitors",
                    instruction=f"{context.objective} competitors alternatives benchmarks",
                ),
                RuntimeTaskSpec(
                    task_id="intelligence-customers",
                    agent_id="intelligence",
                    reads=frozenset({"objective", "grounded_context"}),
                    writes=frozenset({"isolated.intelligence.customers"}),
                    task_kind="intelligence.customers",
                    instruction=f"{context.objective} customer motivations pain points objections",
                ),
            )

        research_scheduler = DependencyAwareScheduler(
            max_workers=max(1, min(3, len(research_tasks)))
        )
        research_plan = research_scheduler.plan(research_tasks)
        context.working_state["intelligence_adaptive_task_plan"] = {
            "mode": research_mode,
            "selected_task_kinds": [task.task_kind for task in research_tasks],
            "rejected_kinds": list(rejected_kinds),
            "waves": [list(wave) for wave in research_plan.waves],
        }
'''
if text.count(old_research_block) != 1:
    raise SystemExit(f"RESEARCH_BLOCK_ANCHOR_MISMATCH: {text.count(old_research_block)}")
text = text.replace(old_research_block, new_research_block, 1)

old_query = '''        def run_research_task(task: RuntimeTaskSpec) -> ExecutionReceipt:
            query = task.instruction
'''
new_query = '''        def run_research_task(task: RuntimeTaskSpec) -> ExecutionReceipt:
            query = task.instruction or context.objective
'''
if text.count(old_query) != 1:
    raise SystemExit(f"RESEARCH_QUERY_ANCHOR_MISMATCH: {text.count(old_query)}")
text = text.replace(old_query, new_query, 1)

path.write_text(text, encoding="utf-8")
