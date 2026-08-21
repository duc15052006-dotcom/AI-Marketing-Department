"""Business and Brand Workspace Abstraction (Phase 6.1).

Defines isolated business scopes, brand rules, approved/prohibited claims,
and multi-brand isolation boundaries to prevent data leakage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field


class BusinessWorkspace(BaseModel):
    """Isolated tenant workspace defining brand context, rules, and scope boundaries."""
    business_id: str = Field(..., description="Unique tenant ID, e.g. 'BIZ_CARDIOVITAL'")
    brand_name: str = Field(..., description="Human-readable brand name")
    description: str = ""
    industry: str = "Healthcare / Telehealth"
    markets: List[str] = Field(default_factory=lambda: ["US", "GLOBAL"])
    products: List[str] = Field(default_factory=list)
    audiences: List[str] = Field(default_factory=list)
    brand_rules: Dict[str, Any] = Field(default_factory=dict)
    approved_claims: List[str] = Field(default_factory=list)
    prohibited_claims: List[str] = Field(default_factory=list)
    default_constraints: List[str] = Field(default_factory=list)
    knowledge_scope: str = Field(default="GLOBAL")
    memory_scope: str = Field(default="GLOBAL")
    connector_policy: Dict[str, Any] = Field(default_factory=dict)

    def calculate_workspace_hash(self) -> str:
        """Compute SHA-256 fingerprint of the workspace definition."""
        raw = f"{self.business_id}:{self.brand_name}:{self.knowledge_scope}:{self.memory_scope}:{json.dumps(self.approved_claims)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BusinessRegistry:
    """Registry managing active business workspaces and tenant isolation."""

    def __init__(self) -> None:
        self._workspaces: Dict[str, BusinessWorkspace] = {}

    def register_workspace(self, workspace: BusinessWorkspace) -> None:
        self._workspaces[workspace.business_id.lower()] = workspace

    def get_workspace(self, business_id: str) -> Optional[BusinessWorkspace]:
        return self._workspaces.get(business_id.lower())

    def list_workspaces(self) -> List[BusinessWorkspace]:
        return list(self._workspaces.values())
