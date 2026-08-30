from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one patch anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) Preserve an explicit Performance INCONCLUSIVE signal in the durable
# structured handoff/checkpoint. Explicit false may never erase a detector-
# derived true value.
# ---------------------------------------------------------------------------
replace_once(
    "runtime/engine.py",
    '''        output, _payload, _parse_status = self._finalize_stage_handoff(context, "performance", "performance", llm_perf, output)\n        if emitter:\n''',
    '''        output, _payload, _parse_status = self._finalize_stage_handoff(context, "performance", "performance", llm_perf, output)\n        # Structured Performance truth must survive into the durable handoff and\n        # checkpoint. An explicit True is authoritative as an inconclusive flag;\n        # explicit False never erases a deterministic detector-derived True.\n        if isinstance(_payload, dict) and _payload.get("performance_inconclusive") is True:\n            output["performance_inconclusive"] = True\n            perf_handoff = context.working_state.get("stage_handoffs", {}).get("performance")\n            if isinstance(perf_handoff, dict):\n                perf_handoff["performance_inconclusive"] = True\n        if emitter:\n''',
)


# ---------------------------------------------------------------------------
# 2) Model-level cost truth. A provider-wide FREE_TIER_ALLOWED declaration is
# not proof that every arbitrary model sold by that provider is free. Known
# model metadata is authoritative under an otherwise-free provider; unknown
# models fail closed. Provider PAID/DISABLED/UNKNOWN remain hard boundaries.
# ---------------------------------------------------------------------------
replace_once(
    "integrations/models/gateway.py",
    '''    def set_free_only_mode(self, enabled: bool) -> None:\n        """Toggle strict free-only cost governance."""\n        self._free_only_mode = enabled\n        self._model_policy.free_only_mode = enabled\n\n''',
    '''    def set_free_only_mode(self, enabled: bool) -> None:\n        """Toggle strict free-only cost governance."""\n        self._free_only_mode = enabled\n        self._model_policy.free_only_mode = enabled\n\n    def _resolve_candidate_cost_tier(self, cand_provider: str, cand_model: str, prov_def: Any, adapter: Any) -> CostPolicy:\n        """Resolve model cost with fail-closed, model-level truth semantics.\n\n        Provider-wide FREE_TIER_ALLOWED means only that the provider may expose\n        free models; it is never proof that an unregistered arbitrary model is\n        free. Explicit provider PAID/DISABLED/UNKNOWN remains a hard boundary.\n        CUSTOM_INJECTED adapters are an explicit dependency-injection/test lane\n        and may declare their own cost policy when no model metadata exists.\n        """\n        provider_tier = getattr(prov_def, "cost_policy", None) if prov_def is not None else None\n        if provider_tier in (CostPolicy.PAID, CostPolicy.DISABLED, CostPolicy.UNKNOWN):\n            return provider_tier\n\n        model_meta = self.model_registry.get_model(cand_provider, cand_model)\n        if model_meta is not None:\n            return model_meta.cost_tier\n\n        adapter_type = str(getattr(prov_def, "adapter_type", "")).upper() if prov_def is not None else ""\n        if adapter_type == "CUSTOM_INJECTED" and adapter is not None:\n            return getattr(adapter, "cost_policy", CostPolicy.UNKNOWN)\n\n        return CostPolicy.UNKNOWN\n\n''',
)

replace_once(
    "integrations/models/gateway.py",
    '''            model_meta = self.model_registry.get_model(cand_provider, cand_model)\n            # ProviderDefinition-declared cost policy is authoritative when a\n            # definition exists (including explicit UNKNOWN = unverified);\n            # model metadata is only a fallback for undefined providers.\n            if prov_def is not None:\n                cost_tier = prov_def.cost_policy\n            else:\n                cost_tier = (\n                    model_meta.cost_tier if model_meta\n                    else (adapter.cost_policy if adapter else CostPolicy.UNKNOWN)\n                )\n''',
    '''            cost_tier = self._resolve_candidate_cost_tier(cand_provider, cand_model, prov_def, adapter)\n''',
)

replace_once(
    "integrations/models/gateway.py",
    '''            # 3. Cost Policy Gate\n            if prov_def is not None:\n                cost_tier = prov_def.cost_policy\n            else:\n                cost_tier = adapter.cost_policy\n''',
    '''            # 3. Cost Policy Gate — model-level truth, fail closed for unknown models.\n            cost_tier = self._resolve_candidate_cost_tier(cand_provider, cand_model, prov_def, adapter)\n''',
)

# Sync adapter exception is an internal diagnostic, not public provider text.
replace_once(
    "integrations/models/gateway.py",
    '''                    error=f"ADAPTER_INVOCATION_EXCEPTION: {str(e)[:200]}",\n''',
    '''                    error=f"ADAPTER_INVOCATION_EXCEPTION: Adapter invocation failed ({type(e).__name__}).",\n''',
)

# ---------------------------------------------------------------------------
# 3) Test harnesses that explicitly intend a real connector or deterministic
# mock must bind it explicitly. Production defaults remain fail closed.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_phase6_1_v1_connectors_and_workspace.py",
    '''        self.tool_gateway.register_adapter(self.analytics_conn)\n''',
    '''        self.tool_gateway.register_adapter(\n            self.analytics_conn,\n            aliases=["analytics_adapter", "kpi_calc_adapter", "attribution_adapter", "stats_analysis_adapter", "data_retrieval_adapter"],\n        )\n''',
)

# Phase 5.1 foundation tests are about gateway governance/receipts, not whether
# a production media/search/publishing connector is configured. Make their
# simulated providers explicit instead of relying on production fake success.
replace_once(
    "tests/test_phase5_1_foundation.py",
    '''        self.gateway = ToolGateway(\n            capability_registry=self.cap_registry,\n            policy_engine=self.policy_engine,\n            receipt_repository=self.receipt_repo,\n        )\n        self.knowledge_repo = LocalKnowledgeRepository()\n''',
    '''        self.gateway = ToolGateway(\n            capability_registry=self.cap_registry,\n            policy_engine=self.policy_engine,\n            receipt_repository=self.receipt_repo,\n        )\n        # Explicit hermetic test providers. Production defaults intentionally\n        # fail closed when no real connector is configured.\n        self.gateway.register_adapter(MockToolAdapter(name="image_gen_adapter"))\n        self.gateway.register_adapter(MockToolAdapter(name="social_publish_adapter"))\n        self.gateway.register_adapter(MockToolAdapter(name="search_adapter"))\n        self.knowledge_repo = LocalKnowledgeRepository()\n''',
)

# Phase 5.2 E2E likewise opts into deterministic test tools explicitly.
replace_once(
    "tests/test_phase5_2_runtime_integration.py",
    '''        self.tool_gateway = ToolGateway(\n            capability_registry=self.cap_registry,\n            policy_engine=self.policy_engine,\n            receipt_repository=self.receipt_repo,\n        )\n        self.knowledge_repo = LocalKnowledgeRepository()\n''',
    '''        self.tool_gateway = ToolGateway(\n            capability_registry=self.cap_registry,\n            policy_engine=self.policy_engine,\n            receipt_repository=self.receipt_repo,\n        )\n        self.tool_gateway.register_adapter(MockToolAdapter(name="search_adapter"))\n        self.tool_gateway.register_adapter(MockToolAdapter(name="image_gen_adapter"))\n        self.tool_gateway.register_adapter(MockToolAdapter(name="kpi_calc_adapter"))\n        self.tool_gateway.register_adapter(MockToolAdapter(name="social_publish_adapter"))\n        self.knowledge_repo = LocalKnowledgeRepository()\n''',
)

print("batch2 regression-truth patch applied")
