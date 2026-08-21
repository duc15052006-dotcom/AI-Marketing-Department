"""Project Workspace & Chat-to-Brand Promotion Engine for AI Marketing Department.

Implements lightweight Projects (sitting between temporary Chats and formal Brands),
and selective, governed promotion of verified chat facts into persistent Knowledge.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from knowledge.ingestion import IngestionFormat, KnowledgeIngestionRequest, KnowledgeLifecycleManager
from knowledge.models import AuthorityLevel, SourceType
from workspace.business import BusinessRegistry, BusinessWorkspace


class ClaimOriginType(str, Enum):
    USER_PROVIDED = "USER_PROVIDED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    WEB_OBSERVATION = "WEB_OBSERVATION"
    UNVERIFIED = "UNVERIFIED"


@dataclass
class ProjectWorkspace:
    """Lightweight project grouping multiple chats, temporary attachments, and runs."""

    project_name: str
    project_id: str = field(default_factory=lambda: f"PROJ-{uuid.uuid4().hex[:8].upper()}")
    description: str = ""
    optional_business_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chat_ids: List[str] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)
    knowledge_scope: str = ""

    def __post_init__(self) -> None:
        if not self.knowledge_scope:
            self.knowledge_scope = f"SCOPE_PROJ_{self.project_id}"

    def model_dump(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "description": self.description,
            "optional_business_id": self.optional_business_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "chat_ids": self.chat_ids,
            "run_ids": self.run_ids,
            "knowledge_scope": self.knowledge_scope,
        }


class ProjectRegistry:
    """Manages project workspaces and selective promotion into persistent storage."""

    def __init__(
        self,
        business_registry: Optional[BusinessRegistry] = None,
        knowledge_lifecycle: Optional[KnowledgeLifecycleManager] = None,
    ) -> None:
        self._projects: Dict[str, ProjectWorkspace] = {}
        self.biz_registry = business_registry or BusinessRegistry()
        self.knowledge_lifecycle = knowledge_lifecycle

    def create_project(self, name: str, description: str = "", business_id: Optional[str] = None) -> ProjectWorkspace:
        proj = ProjectWorkspace(
            project_name=name,
            description=description,
            optional_business_id=business_id,
        )
        self._projects[proj.project_id] = proj
        return proj

    def get_project(self, project_id: str) -> Optional[ProjectWorkspace]:
        return self._projects.get(project_id)

    def list_projects(self, business_id: Optional[str] = None) -> List[ProjectWorkspace]:
        projs = list(self._projects.values())
        if business_id:
            projs = [p for p in projs if p.optional_business_id == business_id]
        return sorted(projs, key=lambda p: p.updated_at, reverse=True)

    def promote_chat_to_project(self, chat_id: str, project_name: str, description: str = "") -> ProjectWorkspace:
        """Create a new project workspace linked to the given chat thread."""
        proj = self.create_project(name=project_name, description=description)
        proj.chat_ids.append(chat_id)
        return proj

    def promote_chat_to_brand(
        self,
        chat_id: str,
        brand_name: str,
        industry: str,
        extracted_facts: List[Dict[str, Any]],
    ) -> BusinessWorkspace:
        """Selectively promote verified facts from a chat into a brand workspace."""
        approved_claims: List[str] = []
        prohibited_claims: List[str] = []
        products: List[Dict[str, Any]] = []

        for item in extracted_facts:
            origin = item.get("origin", ClaimOriginType.UNVERIFIED.value)
            text = item.get("text", "")
            # Only USER_PROVIDED or SOURCE_VERIFIED items can become approved claims
            if origin in (ClaimOriginType.USER_PROVIDED.value, ClaimOriginType.SOURCE_VERIFIED.value):
                if item.get("is_prohibited"):
                    prohibited_claims.append(text)
                elif item.get("is_product"):
                    products.append({"name": text, "price": item.get("price", "")})
                else:
                    approved_claims.append(text)

        biz_id = f"BIZ_{brand_name.upper().replace(' ', '_')}_{uuid.uuid4().hex[:6].upper()}"
        workspace = BusinessWorkspace(
            business_id=biz_id,
            brand_name=brand_name,
            industry=industry,
            products=products,
            approved_claims=approved_claims,
            prohibited_claims=prohibited_claims,
            knowledge_scope=f"SCOPE_BIZ_{biz_id}",
            memory_scope=f"SCOPE_BIZ_{biz_id}",
        )
        self.biz_registry.register_workspace(workspace)
        return workspace
