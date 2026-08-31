from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ANCHOR_COUNT_MISMATCH {path}: expected 1, got {count}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "runtime/engine.py"

replace_once(
    path,
    "from knowledge.models import KnowledgeCitation\n",
    "from knowledge.models import AuthorityLevel, KnowledgeCitation\n",
)

helper_anchor = """        return knowledge_result, memory_result\n\n    def _get_emitter(self, context: Optional[RuntimeContext] = None, run_id: Optional[str] = None) -> Optional[ProgressEmitter]:\n"""
helper_replacement = """        return knowledge_result, memory_result\n\n    def _reconcile_grounded_stage_provenance(\n        self,\n        context: RuntimeContext,\n        grounded_pkg: GroundedContextPackage,\n        knowledge_result: Optional[KnowledgeRetrievalResult] = None,\n        memory_result: Optional[MemoryRetrievalResult] = None,\n    ) -> None:\n        \"\"\"Make stage audit refs exactly match persistent evidence accepted by ContextCompiler.\n\n        Legacy builders remain useful for backward-compatible stage result objects,\n        but they are not an evidence authority. GroundedContextPackage is the\n        authoritative model-input boundary, so RuntimeContext refs, LineageInspector,\n        and stage citation lists must be rebuilt from its accepted knowledge/memory IDs.\n        \"\"\"\n        grounded_knowledge_ids: List[str] = []\n        grounded_memory_ids: List[str] = []\n        seen_knowledge_ids: Set[str] = set()\n        seen_memory_ids: Set[str] = set()\n\n        for item in grounded_pkg.evidence_items:\n            metadata = item.metadata if isinstance(item.metadata, dict) else {}\n            knowledge_id = str(metadata.get(\"knowledge_id\") or \"\").strip()\n            memory_id = str(metadata.get(\"memory_id\") or \"\").strip()\n            if knowledge_id and knowledge_id not in seen_knowledge_ids:\n                seen_knowledge_ids.add(knowledge_id)\n                grounded_knowledge_ids.append(knowledge_id)\n            if memory_id and memory_id not in seen_memory_ids:\n                seen_memory_ids.add(memory_id)\n                grounded_memory_ids.append(memory_id)\n\n        if knowledge_result is not None:\n            existing_citations = {\n                citation.knowledge_id: citation for citation in knowledge_result.citations\n            }\n            grounded_documents = []\n            grounded_citations = []\n            for knowledge_id in grounded_knowledge_ids:\n                document = self.knowledge_repo.get_document(knowledge_id) if self.knowledge_repo else None\n                if document is None:\n                    continue\n                citation = existing_citations.get(knowledge_id)\n                if citation is None:\n                    chunk = document.chunks[0] if document.chunks else None\n                    citation = KnowledgeCitation(\n                        knowledge_id=document.knowledge_id,\n                        chunk_id=chunk.chunk_id if chunk else None,\n                        source_id=document.source_id,\n                        claim_ref=document.title,\n                        confidence=(\n                            1.0\n                            if document.authority_level == AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH\n                            else 0.85\n                        ),\n                    )\n                grounded_documents.append(document)\n                grounded_citations.append(citation)\n\n            knowledge_result.documents = grounded_documents\n            knowledge_result.citations = grounded_citations\n            knowledge_result.retrieved_count = len(grounded_documents)\n            for citation in grounded_citations:\n                context.knowledge_refs.append(citation.citation_id)\n                self.lineage_inspector.add_citation(citation)\n\n        if memory_result is not None:\n            grounded_memories = []\n            for memory_id in grounded_memory_ids:\n                memory = self.memory_repo.get_memory(memory_id) if self.memory_repo else None\n                if memory is not None:\n                    grounded_memories.append(memory)\n\n            memory_result.memories = grounded_memories\n            memory_result.retrieved_count = len(grounded_memories)\n            for memory in grounded_memories:\n                context.memory_refs.append(memory.memory_id)\n\n    def _get_emitter(self, context: Optional[RuntimeContext] = None, run_id: Optional[str] = None) -> Optional[ProgressEmitter]:\n"""
replace_once(path, helper_anchor, helper_replacement)

replace_once(
    path,
    """        k_res, m_res = self._build_stage_lineage_context(\"cmo\", context, include_memory=True)\n\n        for c in k_res.citations:\n            context.knowledge_refs.append(c.citation_id)\n            self.lineage_inspector.add_citation(c)\n        for m in m_res.memories:\n            context.memory_refs.append(m.memory_id)\n\n        # Grounded Context Compilation\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"cmo\", context)\n""",
    """        k_res, m_res = self._build_stage_lineage_context(\"cmo\", context, include_memory=True)\n\n        # Grounded Context Compilation is the authoritative model-input boundary.\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"cmo\", context)\n        self._reconcile_grounded_stage_provenance(context, grounded_pkg, k_res, m_res)\n""",
)

replace_once(
    path,
    """        k_res, _ = self._build_stage_lineage_context(\"intelligence\", context, include_memory=False)\n        for c in k_res.citations:\n            context.knowledge_refs.append(c.citation_id)\n            self.lineage_inspector.add_citation(c)\n\n        # Invoke ToolGateway for search observation\n""",
    """        k_res, _ = self._build_stage_lineage_context(\"intelligence\", context, include_memory=False)\n\n        # Invoke ToolGateway for search observation\n""",
)
replace_once(
    path,
    """        # Grounded Context Compilation with actual Tool Receipt content\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"intelligence\", context, tool_receipts=[search_receipt])\n""",
    """        # Grounded Context Compilation with actual Tool Receipt content.\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"intelligence\", context, tool_receipts=[search_receipt])\n        self._reconcile_grounded_stage_provenance(context, grounded_pkg, k_res)\n""",
)

replace_once(
    path,
    """        k_res, m_res = self._build_stage_lineage_context(\"strategist\", context, include_memory=True)\n\n        for c in k_res.citations:\n            context.knowledge_refs.append(c.citation_id)\n            self.lineage_inspector.add_citation(c)\n        for m in m_res.memories:\n            context.memory_refs.append(m.memory_id)\n\n        # Grounded Context Compilation\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"strategist\", context)\n""",
    """        k_res, m_res = self._build_stage_lineage_context(\"strategist\", context, include_memory=True)\n\n        # Grounded Context Compilation is the authoritative model-input boundary.\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"strategist\", context)\n        self._reconcile_grounded_stage_provenance(context, grounded_pkg, k_res, m_res)\n""",
)

replace_once(
    path,
    """        k_res, _ = self._build_stage_lineage_context(\"creative\", context, include_memory=False)\n        for c in k_res.citations:\n            context.knowledge_refs.append(c.citation_id)\n            self.lineage_inspector.add_citation(c)\n\n        # Invoke ToolGateway for local image generation / asset preparation\n""",
    """        k_res, _ = self._build_stage_lineage_context(\"creative\", context, include_memory=False)\n\n        # Invoke ToolGateway for local image generation / asset preparation\n""",
)
replace_once(
    path,
    """        # Grounded Context Compilation with image tool receipt\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"creative\", context, tool_receipts=[img_receipt])\n""",
    """        # Grounded Context Compilation with image tool receipt.\n        grounded_pkg = self.context_compiler.compile_grounded_package(\"creative\", context, tool_receipts=[img_receipt])\n        self._reconcile_grounded_stage_provenance(context, grounded_pkg, k_res)\n""",
)

replace_once(
    path,
    """        k_res, m_res = self._build_stage_lineage_context(\"performance\", context, include_memory=True)\n\n        for c in k_res.citations:\n            context.knowledge_refs.append(c.citation_id)\n            self.lineage_inspector.add_citation(c)\n        for m in m_res.memories:\n            context.memory_refs.append(m.memory_id)\n\n        # Retrieve observed campaign telemetry through ToolGateway. A REAL\n""",
    """        k_res, m_res = self._build_stage_lineage_context(\"performance\", context, include_memory=True)\n\n        # Retrieve observed campaign telemetry through ToolGateway. A REAL\n""",
)
replace_once(
    path,
    """        grounded_pkg = self.context_compiler.compile_grounded_package(\n            \"performance\", context, tool_receipts=grounded_receipts\n        )\n""",
    """        grounded_pkg = self.context_compiler.compile_grounded_package(\n            \"performance\", context, tool_receipts=grounded_receipts\n        )\n        self._reconcile_grounded_stage_provenance(context, grounded_pkg, k_res, m_res)\n""",
)

print("PR91 candidate patch applied")
