"""Lineage Resolution and Provenance Tracking (Phase 5.2).

Provides end-to-end lineage tracing connecting final claims, agent outputs,
execution receipts, tool outputs, knowledge citations, and origin sources.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from knowledge.models import KnowledgeCitation
from schemas.base import BaseModel, Field
from tools.receipts import ExecutionReceipt


class LineageNode(BaseModel):
    """Individual node in an audit lineage trace."""
    node_id: str
    node_type: str  # CLAIM | AGENT_OUTPUT | CAPABILITY_RECEIPT | KNOWLEDGE_CITATION | SOURCE
    title: str
    details: Dict[str, Any] = Field(default_factory=dict)
    parent_ids: List[str] = Field(default_factory=list)


class LineageTrace(BaseModel):
    """Complete provenance chain linking a claim or output to foundational evidence."""
    target_claim: str
    valid: bool = True
    chain: List[LineageNode] = Field(default_factory=list)
    missing_links: List[str] = Field(default_factory=list)


class LineageInspector:
    """Audits and traces runtime lineage across receipts and citations."""

    def __init__(
        self,
        receipts: Optional[List[ExecutionReceipt]] = None,
        citations: Optional[List[KnowledgeCitation]] = None,
    ) -> None:
        self._receipts_by_id = {r.execution_id: r for r in (receipts or [])}
        self._citations_by_id = {c.citation_id: c for c in (citations or [])}

    def add_receipt(self, receipt: ExecutionReceipt) -> None:
        self._receipts_by_id[receipt.execution_id] = receipt

    def add_citation(self, citation: KnowledgeCitation) -> None:
        self._citations_by_id[citation.citation_id] = citation

    def get_all_citations(self) -> List[KnowledgeCitation]:
        return list(self._citations_by_id.values())

    def get_all_receipts(self) -> List[ExecutionReceipt]:
        return list(self._receipts_by_id.values())

    def trace_claim_to_receipt(self, claim: str, receipt_id: str) -> LineageTrace:
        """Trace an assertion back to an underlying tool execution receipt."""
        trace = LineageTrace(target_claim=claim)
        receipt = self._receipts_by_id.get(receipt_id)

        if not receipt:
            trace.valid = False
            trace.missing_links.append(f"EXECUTION_RECEIPT_NOT_FOUND: {receipt_id}")
            return trace

        # Build lineage chain
        trace.chain.append(
            LineageNode(
                node_id=f"CLAIM-{hash(claim)}",
                node_type="CLAIM",
                title=claim,
                parent_ids=[receipt.execution_id],
            )
        )
        trace.chain.append(
            LineageNode(
                node_id=receipt.execution_id,
                node_type="CAPABILITY_RECEIPT",
                title=f"{receipt.capability_id} via {receipt.provider}",
                details={
                    "status": receipt.status.value,
                    "request_hash": receipt.request_hash,
                    "result_hash": receipt.result_hash,
                    "completed_at": receipt.completed_at.isoformat(),
                },
                parent_ids=[receipt.provider],
            )
        )
        trace.chain.append(
            LineageNode(
                node_id=receipt.provider,
                node_type="PROVIDER",
                title=receipt.provider,
                details={"provider_name": receipt.provider},
            )
        )
        return trace

    def trace_claim_to_knowledge(self, claim: str, citation: KnowledgeCitation) -> LineageTrace:
        """Trace an assertion back to a verified knowledge citation and source."""
        trace = LineageTrace(target_claim=claim)
        trace.chain.append(
            LineageNode(
                node_id=f"CLAIM-{hash(claim)}",
                node_type="CLAIM",
                title=claim,
                parent_ids=[citation.citation_id],
            )
        )
        trace.chain.append(
            LineageNode(
                node_id=citation.citation_id,
                node_type="KNOWLEDGE_CITATION",
                title=f"Citation {citation.citation_id} (conf={citation.confidence})",
                details={
                    "knowledge_id": citation.knowledge_id,
                    "chunk_id": citation.chunk_id,
                    "source_id": citation.source_id,
                },
                parent_ids=[citation.knowledge_id],
            )
        )
        trace.chain.append(
            LineageNode(
                node_id=citation.knowledge_id,
                node_type="KNOWLEDGE_DOC",
                title=f"Knowledge Doc {citation.knowledge_id}",
                parent_ids=[citation.source_id],
            )
        )
        return trace
