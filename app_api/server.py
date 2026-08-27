"""AI Marketing Department Localhost Application API (App V1 Completion Patch).

Lightweight, high-performance HTTP API server binding strictly to 127.0.0.1.
Exposes Chat-First, Project Workspace, Session Knowledge, Run Queue, and Five-Agent Runtime.
Zero secret exposure to frontend.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def get_secure_session_token() -> str:
    """Generate a cryptographically fresh API session token (>=256 bits entropy) per process launch."""
    return secrets.token_urlsafe(32)


# Process-lifetime Local API Session Token (256-bit cryptographic entropy)
GLOBAL_API_SESSION_TOKEN: str = get_secure_session_token()

ALLOWED_LOCAL_ORIGINS: Set[str] = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}

PRODUCTION_ALLOWED_HOSTNAMES: Set[str] = {
    "127.0.0.1",
    "localhost",
    "::1",
}


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with allow_reuse_address=False to enforce exclusive port binding on Windows."""
    allow_reuse_address = False


def parse_and_validate_host(
    host_header: Optional[str],
    allowed_hostnames: Optional[Set[str]] = None,
    allow_testserver: bool = False,
) -> bool:
    """Structurally parse and validate Host header against loopback whitelist.

    Rejects:
    - Subdomains/suffixes (e.g. localhost.attacker.com, 127.0.0.1.evil.com)
    - Prefix hacks
    - 'testserver' in production (unless explicitly permitted via allow_testserver=True)
    - Malformed IPv6 hostnames
    """
    if not host_header:
        return False
    host_raw = host_header.strip()
    if not host_raw:
        return False

    target_allowed = allowed_hostnames or PRODUCTION_ALLOWED_HOSTNAMES

    if host_raw.startswith("["):
        # Bracketed IPv6: [::1] or [::1]:8765
        bracket_end = host_raw.find("]")
        if bracket_end == -1:
            return False
        hostname = host_raw[1:bracket_end].lower()
        port_part = host_raw[bracket_end + 1:]
        if port_part:
            if not port_part.startswith(":"):
                return False
            port_num = port_part[1:]
            if not port_num.isdigit():
                return False
    elif ":" in host_raw:
        # IPv4 or name with port: 127.0.0.1:8765 or localhost:8765
        parts = host_raw.split(":")
        if len(parts) != 2:
            return False
        hostname = parts[0].strip().lower()
        port_num = parts[1].strip()
        if not port_num.isdigit():
            return False
    else:
        # Hostname without port: 127.0.0.1 or localhost
        hostname = host_raw.lower()

    if hostname == "testserver":
        return allow_testserver

    return hostname in target_allowed


PUBLIC_LOCAL_HEALTH_PATHS: Set[str] = {
    "/api/health",
}

# Central Configuration Authority Bootstrap (PROD-CONFIG-01 / PROD-CONFIG-01RR)
from config.authority import get_runtime_config
get_runtime_config()

from chat.engine import ChatConversationEngine
from chat.knowledge import SessionKnowledgeStore
from chat.router import ConversationIntent, ConversationRouter
from chat.session import AttachmentType, ChatAttachment, ChatSessionManager
from integrations.models.config_service import GLOBAL_PROVIDER_CONFIG, ProviderConfigService
from connectors.analytics_connector import RealAnalyticsConnector
from connectors.file_connector import RealFileConnector
from connectors.publishing_connector import SandboxPublishingConnector
from connectors.registry import ConnectorRegistry
from connectors.web_connector import RealWebConnector
from knowledge.ingestion import IngestionFormat, KnowledgeIngestionRequest, KnowledgeLifecycleManager
from knowledge.models import AuthorityLevel, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.learning import LearningEvent, LocalLearningRepository
from memory.learning_operations import LearningOperatorService
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.operations import MemoryOperatorService
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import ApprovalState, RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.context_compiler import ContextCompiler
from runtime.engine import FiveAgentDepartmentRuntime, extract_explicit_user_constraints
from runtime.queue import ResourceLimiter, RunManager
from integrations.models.settings_manager import (
    ModelSettingsManager,
    ModelSettingsValidationError,
    StaleSettingsRevisionError,
)
from tools.capabilities import CapabilityRegistry, RiskLevel
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import (
    HumanApprovalRecord,
    PendingApprovalRecord,
    PendingApprovalStatus,
    PolicyEngine,
    compute_request_fingerprint,
)
from tools.tool_gateway import ToolGateway, ToolRequest
from workspace.business import BusinessRegistry, BusinessWorkspace
from workspace.operator import OperatorWorkspace
from workspace.project import ClaimOriginType, ProjectRegistry

logger = logging.getLogger("app_api")


class DepartmentAppBackend:
    """Singleton backend managing application runtime state, chats, and workspaces."""

    def __init__(self) -> None:
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.tool_gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )

        # Register real local connectors with capability provider aliases
        self.web_conn = RealWebConnector()
        self.file_conn = RealFileConnector()
        self.analytics_conn = RealAnalyticsConnector()
        self.publish_conn = SandboxPublishingConnector()

        self.tool_gateway.register_adapter(self.web_conn, aliases=["http_adapter", "search_adapter"])
        self.tool_gateway.register_adapter(self.file_conn, aliases=["file_io_adapter", "db_storage_adapter", "export_adapter"])
        self.tool_gateway.register_adapter(self.analytics_conn, aliases=["analytics_adapter", "kpi_calc_adapter", "attribution_adapter", "stats_analysis_adapter", "data_retrieval_adapter"])
        self.tool_gateway.register_adapter(self.publish_conn, aliases=["social_publish_adapter", "schedule_adapter", "ad_platform_adapter"])

        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.learning_repo = LocalLearningRepository()
        self.session_knowledge = SessionKnowledgeStore()
        self.context_compiler = ContextCompiler(
            session_knowledge=self.session_knowledge,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            capability_registry=self.cap_registry,
        )

        self.runtime = FiveAgentDepartmentRuntime(
            tool_gateway=self.tool_gateway,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            learning_repo=self.learning_repo,
            session_knowledge=self.session_knowledge,
            context_compiler=self.context_compiler,
        )

        self.conn_registry = ConnectorRegistry()
        self.biz_registry = BusinessRegistry()
        self.workspace = OperatorWorkspace(
            runtime=self.runtime,
            business_registry=self.biz_registry,
            connector_registry=self.conn_registry,
        )

        # Chat & Ephemeral Session Knowledge
        self.chat_mgr = ChatSessionManager()

        # Conversation Router & Direct Conversational Engine (Zero 5-Agent calls for general chat)
        self.conversation_router = ConversationRouter(model_gateway=self.runtime.model_gateway)
        self.chat_engine = ChatConversationEngine(
            model_gateway=self.runtime.model_gateway,
            session_knowledge=self.session_knowledge,
            knowledge_repo=self.knowledge_repo,
        )

        # Project Workspace & Promotion
        self.project_registry = ProjectRegistry(
            business_registry=self.biz_registry,
            knowledge_lifecycle=self.workspace.knowledge_lifecycle,
        )

        # Context Compiler & Multi-Run Queue
        self.resource_limiter = ResourceLimiter()
        self.run_manager = RunManager(
            runtime=self.runtime,
            max_workers=2,
            resource_limiter=self.resource_limiter,
        )

        # Authoritative Model & Provider Settings Manager (PROD-MODEL-SETTINGS-01)
        self.settings_manager = ModelSettingsManager(gateway=self.runtime.model_gateway)

        # Register Demo Workspace with explicit warning
        self.biz_registry.register_workspace(
            BusinessWorkspace(
                business_id="DEMO_BENCHMARK_CASE04",
                brand_name="CardioVital 360 (DEMO ONLY)",
                description="[NOT PRODUCTION DATA] Synthetic regulated benchmark scenario from Case 04.",
                industry="Demo Healthcare",
                knowledge_scope="SCOPE_DEMO_CASE04",
                memory_scope="SCOPE_DEMO_CASE04",
                approved_claims=["Demo sample claim"],
                default_constraints=["DEMO_ONLY_BENCHMARK_SCENARIO"],
            )
        )


APP_BACKEND = DepartmentAppBackend()


class DepartmentAPIHandler(BaseHTTPRequestHandler):
    """Localhost HTTP request dispatcher for React / Tauri desktop UI."""

    allow_testserver_for_testing: bool = False

    def _is_valid_host(self, host_header: Optional[str]) -> bool:
        return parse_and_validate_host(
            host_header=host_header,
            allowed_hostnames=PRODUCTION_ALLOWED_HOSTNAMES,
            allow_testserver=self.allow_testserver_for_testing,
        )

    def _is_allowed_origin(self, origin_header: Optional[str]) -> bool:
        if not origin_header:
            return True
        clean_origin = origin_header.strip().rstrip("/")
        return any(clean_origin == allowed.rstrip("/") for allowed in ALLOWED_LOCAL_ORIGINS)

    def _is_authenticated(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = self.headers.get("X-API-Token", "").strip()
        if not token:
            return False
        return hmac.compare_digest(token, GLOBAL_API_SESSION_TOKEN)

    def _set_cors_and_json(self, status_code: int = 200, length: Optional[int] = None) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")

        origin = self.headers.get("Origin")
        if origin:
            clean_origin = origin.strip().rstrip("/")
            if any(clean_origin == allowed.rstrip("/") for allowed in ALLOWED_LOCAL_ORIGINS):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Token")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self.send_response(400)
            self.end_headers()
            return

        origin = self.headers.get("Origin")
        if origin:
            clean_origin = origin.strip().rstrip("/")
            if not any(clean_origin == allowed.rstrip("/") for allowed in ALLOWED_LOCAL_ORIGINS):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error":"FORBIDDEN_ORIGIN"}')
                return

        self._set_cors_and_json(204)

    def _read_body_json(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            return json.loads(body.decode("utf-8"))
        return {}

    def _send_json(self, data: Any, status_code: int = 200) -> None:
        payload = json.dumps(data, default=str).encode("utf-8")
        self._set_cors_and_json(status_code, length=len(payload))
        self.wfile.write(payload)
        self.wfile.flush()

    def _execute_routed_turn(
        self,
        chat_id: str,
        user_text: str,
        parsed_attachments: List[ChatAttachment],
        session: Any,
        user_msg: Optional[ChatMessage] = None,
    ) -> None:
        try:
            decision = APP_BACKEND.conversation_router.route(
                message=user_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )

            # Route A: General Conversation (0 Five-Agent Calls)
            if decision.intent == ConversationIntent.GENERAL_CONVERSATION:
                res = APP_BACKEND.chat_engine.generate_chat_response(
                    session=session,
                    user_message=user_text,
                    attachments=parsed_attachments,
                    is_document_analysis=False,
                )
                status_val = "COMPLETED" if res.get("success", True) else "ERROR"
                resp_msg = APP_BACKEND.chat_mgr.add_assistant_response(
                    chat_id=chat_id,
                    content=res["content"],
                    status=status_val,
                )
                self._send_json(
                    {
                        "chat_id": chat_id,
                        "session": session.model_dump() if hasattr(session, "model_dump") else None,
                        "user_message": user_msg.model_dump() if user_msg else None,
                        "message": resp_msg.model_dump() if resp_msg else {},
                        "route": "GENERAL_CONVERSATION",
                        "intent": decision.intent.value,
                        "reason_code": decision.reason_code,
                        "five_agent_call_count": 0,
                    },
                    201,
                )
                return

            # Route B: Document Analysis (0 Five-Agent Calls)
            elif decision.intent == ConversationIntent.DOCUMENT_ANALYSIS:
                res = APP_BACKEND.chat_engine.generate_chat_response(
                    session=session,
                    user_message=user_text,
                    attachments=parsed_attachments,
                    is_document_analysis=True,
                )
                status_val = "COMPLETED" if res.get("success", True) else "ERROR"
                resp_msg = APP_BACKEND.chat_mgr.add_assistant_response(
                    chat_id=chat_id,
                    content=res["content"],
                    status=status_val,
                )
                self._send_json(
                    {
                        "chat_id": chat_id,
                        "session": session.model_dump() if hasattr(session, "model_dump") else None,
                        "user_message": user_msg.model_dump() if user_msg else None,
                        "message": resp_msg.model_dump() if resp_msg else {},
                        "route": "DOCUMENT_ANALYSIS",
                        "intent": decision.intent.value,
                        "reason_code": decision.reason_code,
                        "five_agent_call_count": 0,
                    },
                    201,
                )
                return

            # Route C: Full Supervised Five-Agent Marketing Workflow
            else:
                ctx, cmo_final, artifact = APP_BACKEND.runtime.run_workflow(
                    objective=user_text,
                    business_id=session.optional_business_id or "BIZ_AD_HOC_EXPLORATION",
                    chat_id=chat_id,
                    project_id=session.optional_project_id,
                    constraints=extract_explicit_user_constraints(user_text),
                )

                is_failed = (artifact.status == RuntimeStatus.FAILED) or (cmo_final.get("status") == "FAILED")
                status_val = "ERROR" if is_failed else "COMPLETED"
                final_markdown = cmo_final.get("master_gtm_plan_markdown") or ("⚠️ Không thể hoàn tất chiến dịch do lỗi kết nối mô hình." if is_failed else "Plan completed.")

                resp_msg = APP_BACKEND.chat_mgr.add_assistant_response(
                    chat_id=chat_id,
                    content=final_markdown,
                    status=status_val,
                    run_id=ctx.run_id,
                    agent_outputs=artifact.agent_outputs,
                )
                self._send_json(
                    {
                        "success": not is_failed,
                        "chat_id": chat_id,
                        "session": session.model_dump() if hasattr(session, "model_dump") else None,
                        "user_message": user_msg.model_dump() if user_msg else None,
                        "message": resp_msg.model_dump() if resp_msg else {},
                        "run_id": ctx.run_id,
                        "artifact_hash": artifact.final_artifact_hash,
                        "route": "MARKETING_WORKFLOW",
                        "intent": decision.intent.value,
                        "reason_code": decision.reason_code,
                        "five_agent_call_count": 5,
                    },
                    201,
                )
                return

        except Exception as ex:
            logger.exception(f"Execution error for chat {chat_id}: {ex}")
            err_msg = APP_BACKEND.chat_mgr.add_assistant_response(
                chat_id=chat_id,
                content=f"⚠️ Không thể hoàn tất phản hồi: {str(ex)}\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
                status="ERROR",
            )
            self._send_json(
                {
                    "chat_id": chat_id,
                    "session": session.model_dump() if hasattr(session, "model_dump") else None,
                    "user_message": user_msg.model_dump() if user_msg else None,
                    "message": err_msg.model_dump() if err_msg else {},
                    "error": str(ex),
                },
                201,
            )

    def do_GET(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self._send_json({"error": "INVALID_HOST", "message": "Host header is invalid or untrusted"}, 400)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if path not in PUBLIC_LOCAL_HEALTH_PATHS and not self._is_authenticated():
            self._send_json({"error": "UNAUTHORIZED", "message": "Valid API session token required"}, 401)
            return

        # 1. Minimal Public Health Check (Zero secret or operational leakage)
        if path == "/api/health":
            self._send_json({"status": "ok", "service": "AI Marketing Department API"})
            return

        # 2. System Status & Health
        elif path == "/api/system/status":
            self._send_json(
                {
                    "app_name": "AI Marketing Department",
                    "version": "1.0.0",
                    "app_backend_version": "1.0.0",
                    "build_id": "20260820-RELEASE-V1",
                    "status": "ONLINE",
                    "brain_version": "FIVE_AGENT_BRAIN_V1_RC3",
                    "permanent_agents": ["cmo", "intelligence", "strategist", "creative", "performance"],
                    "permanent_agent_count": 5,
                    "chat_sessions_count": len(APP_BACKEND.chat_mgr._sessions),
                    "projects_count": len(APP_BACKEND.project_registry._projects),
                    "workspaces_count": len(APP_BACKEND.biz_registry._workspaces),
                    "active_runs": len(APP_BACKEND.runtime._active_contexts),
                    "completed_runs": len(APP_BACKEND.runtime._completed_runs),
                }
            )
            return

        elif path in ("/api/system/health", "/api/connections"):
            health = APP_BACKEND.workspace.inspect_connector_health()
            health["app_backend_version"] = "1.0.0"
            health["build_id"] = "20260820-RELEASE-V1"
            health["providers"] = self._authoritative_provider_report()
            self._send_json(health)
            return

        elif path == "/api/system/providers/health":
            self._send_json(self._authoritative_provider_report())
            return

        elif path == "/api/system/diagnostics":
            diag = GLOBAL_PROVIDER_CONFIG.get_boot_diagnostics()
            # Overlay authoritative ModelSettings provider truth (enabled/model/
            # endpoint/credential) so diagnostics cannot report stale legacy values.
            try:
                mgr = APP_BACKEND.settings_manager
                for pid, entry in diag.get("providers", {}).items():
                    pdef = mgr.get_settings().providers.get(pid)
                    if pdef is not None:
                        entry["enabled"] = pdef.enabled
                        entry["model_present"] = bool(pdef.default_model)
                        entry["endpoint_present"] = bool(pdef.base_url) or pdef.adapter_type == "GEMINI_NATIVE"
                        entry["credential_present"] = mgr._secret_store.has_secret(pdef.credential_ref)
            except Exception:
                pass
            self._send_json(diag)
            return

        # Model & Provider Settings API (PROD-MODEL-SETTINGS-01)
        elif path in ("/api/settings/model", "/api/settings/models"):
            self._send_json(APP_BACKEND.settings_manager.get_safe_settings_dict())
            return

        # 2. Chat Sessions API
        elif path == "/api/chat/sessions":
            proj_id = query.get("project_id", [None])[0]
            biz_id = query.get("business_id", [None])[0]
            include_archived = query.get("include_archived", ["false"])[0].lower() in ("1", "true", "yes")
            sessions = APP_BACKEND.chat_mgr.list_sessions(project_id=proj_id, business_id=biz_id, include_archived=include_archived)
            self._send_json([s.model_dump() for s in sessions])
            return

        elif path.startswith("/api/chat/sessions/") and path.endswith("/messages"):
            chat_id = path.split("/")[-2]
            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            if session:
                self._send_json([m.model_dump() for m in session.messages])
            else:
                self._send_json({"error": "CHAT_NOT_FOUND"}, 404)
            return

        elif path.startswith("/api/chat/sessions/"):
            parts = path.split("/")
            chat_id = parts[4] if len(parts) > 4 else ""
            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            if session:
                self._send_json(session.model_dump())
            else:
                self._send_json({"error": "CHAT_NOT_FOUND"}, 404)
            return

        # 3. Projects API
        elif path == "/api/projects":
            biz_id = query.get("business_id", [None])[0]
            projs = APP_BACKEND.project_registry.list_projects(business_id=biz_id)
            self._send_json([p.model_dump() for p in projs])
            return

        elif path.startswith("/api/projects/"):
            proj_id = path.split("/")[-1]
            proj = APP_BACKEND.project_registry.get_project(proj_id)
            if proj:
                self._send_json(proj.model_dump())
            else:
                self._send_json({"error": "PROJECT_NOT_FOUND"}, 404)
            return

        # 4. Business Workspaces
        elif path == "/api/workspaces":
            workspaces = APP_BACKEND.biz_registry.list_workspaces()
            out = []
            for w in workspaces:
                is_demo = "DEMO" in w.business_id or "BENCHMARK" in w.business_id
                out.append(
                    {
                        "business_id": w.business_id,
                        "brand_name": w.brand_name,
                        "description": w.description,
                        "industry": w.industry,
                        "is_demo_benchmark": is_demo,
                        "warning": "NOT PRODUCTION DATA" if is_demo else None,
                        "knowledge_scope": w.knowledge_scope,
                        "memory_scope": w.memory_scope,
                        "approved_claims_count": len(w.approved_claims),
                    }
                )
            self._send_json(out)
            return

        # 5. Run Queue API
        elif path == "/api/queue/runs":
            runs = APP_BACKEND.run_manager.list_runs()
            self._send_json([r.model_dump() for r in runs])
            return

        elif path == "/api/queue/providers":
            states = APP_BACKEND.resource_limiter.get_provider_states()
            self._send_json(states)
            return

        # 6. Knowledge Management (with Scopes: SESSION, PROJECT, BRAND, GLOBAL)
        elif path == "/api/knowledge":
            scope = query.get("scope", [None])[0]
            if scope:
                # Explicit scope composition: requested scope + GLOBAL
                docs = APP_BACKEND.knowledge_repo.list_documents(scope=scope)
                if scope != "GLOBAL":
                    global_docs = APP_BACKEND.knowledge_repo.list_documents(scope="GLOBAL")
                    seen = {d.knowledge_id for d in docs}
                    docs = docs + [d for d in global_docs if d.knowledge_id not in seen]
            else:
                docs = APP_BACKEND.knowledge_repo.list_documents()
            out = []
            for d in docs:
                out.append(
                    {
                        "knowledge_id": d.knowledge_id,
                        "title": d.title,
                        "source_type": d.source_type.value,
                        "authority_level": d.authority_level.value,
                        "version": d.version,
                        "freshness": d.freshness,
                        "scope": d.scope,
                        "chunks_count": len(d.chunks),
                        "content_preview": d.content[:150],
                        "updated_at": d.updated_at.isoformat(),
                    }
                )
            self._send_json(out)
            return

        # 7. Memory Management
        elif path == "/api/memory":
            scope = query.get("scope", [None])[0]
            mems = APP_BACKEND.workspace.memory_ops.list_memories_for_operator(scope=scope)
            self._send_json(mems)
            return

        # 8. Learning Events
        elif path == "/api/learning":
            learnings = APP_BACKEND.workspace.learning_ops.list_learnings_for_operator()
            self._send_json(learnings)
            return

        # 9. Approvals
        elif path == "/api/approvals":
            pending = []
            seen_pending_ids = set()
            for p in APP_BACKEND.tool_gateway.policy_engine.list_pending_approvals(status=PendingApprovalStatus.PENDING):
                seen_pending_ids.add(p.pending_approval_id)
                pending.append(
                    {
                        "pending_approval_id": p.pending_approval_id,
                        "run_id": p.run_id,
                        "business_id": p.business_id,
                        "capability_id": p.capability_id,
                        "action_type": p.capability_id,
                        "parameters": p.parameters,
                        "request_fingerprint": p.request_fingerprint,
                        "created_at": p.created_at,
                        "expires_at": p.expires_at,
                        "status": p.status.value,
                        "risk_level": p.risk_level.value if hasattr(p.risk_level, "value") else str(p.risk_level),
                    }
                )
            for rid, ctx in APP_BACKEND.runtime._active_contexts.items():
                if ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:
                    # Check if already listed via PolicyEngine
                    if not any(item.get("run_id") == rid for item in pending):
                        pending.append(
                            {
                                "pending_approval_id": f"PENDING-{rid}",
                                "run_id": rid,
                                "business_id": ctx.business_id,
                                "objective": ctx.objective,
                                "pending_since": ctx.created_at.isoformat(),
                                "action_type": "social_publishing",
                                "capability_id": "social_publishing",
                                "risk_level": "CRITICAL",
                                "status": "PENDING",
                            }
                        )
            self._send_json(pending)
            return

        elif path.startswith("/api/approvals/"):
            target_id = path.split("/")[-1]
            policy = APP_BACKEND.tool_gateway.policy_engine
            p = policy.get_pending_approval(target_id)
            if not p:
                pendings_for_run = policy.list_pending_approvals(run_id=target_id, status=PendingApprovalStatus.PENDING)
                if pendings_for_run:
                    p = pendings_for_run[0]
            if p:
                self._send_json(
                    {
                        "pending_approval_id": p.pending_approval_id,
                        "run_id": p.run_id,
                        "business_id": p.business_id,
                        "capability_id": p.capability_id,
                        "action_type": p.capability_id,
                        "parameters": p.parameters,
                        "request_fingerprint": p.request_fingerprint,
                        "created_at": p.created_at,
                        "expires_at": p.expires_at,
                        "status": p.status.value,
                        "risk_level": p.risk_level.value if hasattr(p.risk_level, "value") else str(p.risk_level),
                    }
                )
            else:
                self._send_json({"error": "PENDING_APPROVAL_NOT_FOUND", "message": "Pending approval record not found"}, 404)
            return

        # 10. Activity Receipts
        elif path == "/api/activity/receipts":
            run_id = query.get("run_id", [""])[0]
            receipts = APP_BACKEND.receipt_repo.list_receipts_for_run(run_id) if run_id else list(APP_BACKEND.receipt_repo._receipts.values())
            out = []
            for r in receipts:
                out.append(
                    {
                        "execution_id": r.execution_id,
                        "run_id": r.run_id,
                        "agent_id": r.agent_id,
                        "capability_id": r.capability_id,
                        "provider": r.provider,
                        "status": r.status.value,
                        "latency_ms": r.latency_ms,
                        "completed_at": r.completed_at.isoformat(),
                    }
                )
            self._send_json(out)
            return

        self._send_json({"error": "NOT_FOUND"}, 404)

    def do_PUT(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self._send_json({"error": "INVALID_HOST", "message": "Host header is invalid or untrusted"}, 400)
            return

        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin):
            self._send_json({"error": "FORBIDDEN_ORIGIN", "message": "Untrusted cross-origin request rejected"}, 403)
            return

        if not self._is_authenticated():
            self._send_json({"error": "UNAUTHORIZED", "message": "Valid API session token required"}, 401)
            return

        self._send_json({"error": "NOT_FOUND"}, 404)

    def do_PATCH(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self._send_json({"error": "INVALID_HOST", "message": "Host header is invalid or untrusted"}, 400)
            return

        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin):
            self._send_json({"error": "FORBIDDEN_ORIGIN", "message": "Untrusted cross-origin request rejected"}, 403)
            return

        if not self._is_authenticated():
            self._send_json({"error": "UNAUTHORIZED", "message": "Valid API session token required"}, 401)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body_json()

        if path.startswith("/api/chat/sessions/"):
            chat_id = path.split("/")[-1]
            title = body.get("title")
            archived = body.get("archived")
            status = body.get("status")
            project_id = body.get("project_id")
            business_id = body.get("business_id")
            updated = APP_BACKEND.chat_mgr.update_session(
                chat_id=chat_id,
                title=title,
                archived=archived,
                status=status,
                project_id=project_id,
                business_id=business_id,
            )
            if updated:
                self._send_json(updated.model_dump())
            else:
                self._send_json({"error": "CHAT_NOT_FOUND"}, 404)
            return

        self._send_json({"error": "NOT_FOUND"}, 404)

    def do_DELETE(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self._send_json({"error": "INVALID_HOST", "message": "Host header is invalid or untrusted"}, 400)
            return

        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin):
            self._send_json({"error": "FORBIDDEN_ORIGIN", "message": "Untrusted cross-origin request rejected"}, 403)
            return

        if not self._is_authenticated():
            self._send_json({"error": "UNAUTHORIZED", "message": "Valid API session token required"}, 401)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/chat/sessions/"):
            chat_id = path.split("/")[-1]
            ok = APP_BACKEND.chat_mgr.delete_session(chat_id)
            if ok:
                self._send_json({"success": True, "deleted_chat_id": chat_id})
            else:
                self._send_json({"error": "CHAT_NOT_FOUND"}, 404)
            return

        elif path.startswith("/api/settings/providers/"):
            pid = path.split("/")[-1]
            query = urllib.parse.parse_qs(parsed.query)
            raw_rev = query.get("expected_revision", [None])[0]
            if raw_rev is None or not str(raw_rev).strip().isdigit():
                self._send_json({"error": "MISSING_SETTINGS_REVISION", "message": "MISSING_SETTINGS_REVISION: expected_revision query parameter is required for all Settings mutations."}, 400)
                return
            try:
                APP_BACKEND.settings_manager.delete_provider(pid, expected_revision=int(raw_rev))
                self._send_json({"status": "DELETED", "provider_id": pid,
                                 "settings_revision": APP_BACKEND.settings_manager.get_settings().settings_revision})
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e), "current_revision": e.current_revision}, 409)
            except (ModelSettingsValidationError, ValueError) as e:
                self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
            return

        self._send_json({"error": "NOT_FOUND"}, 404)

    def _authoritative_provider_report(self) -> List[Dict[str, Any]]:
        """Provider health/status report built from AUTHORITATIVE ModelSettings
        and the live ProviderRegistry (not legacy GLOBAL_PROVIDER_CONFIG values)
        so user-facing diagnostics always match committed Settings."""
        mgr = APP_BACKEND.settings_manager
        settings = mgr.get_settings()
        report: List[Dict[str, Any]] = []
        for pid, pdef in settings.providers.items():
            has_cred = False
            try:
                has_cred = mgr._secret_store.has_secret(pdef.credential_ref)
            except Exception:
                has_cred = False
            live_def = APP_BACKEND.runtime.model_gateway.provider_registry.get_provider(pid)
            report.append({
                "provider": pid,
                "enabled": bool(live_def.enabled) if live_def else pdef.enabled,
                "credential_present": has_cred,
                "configured": bool(pdef.enabled and has_cred and pdef.default_model),
                "health": ("AVAILABLE" if (pdef.enabled and has_cred) else ("DISABLED" if not pdef.enabled else "NO_CREDENTIAL")),
                "model": pdef.default_model,
                "base_url": pdef.base_url,
                "timeout_seconds": pdef.timeout_seconds,
                "cost_policy": getattr(getattr(pdef, "cost_policy", None), "value", str(pdef.cost_policy)),
                "last_error_category": None,
            })
        return report

    def do_POST(self) -> None:
        host = self.headers.get("Host", "")
        if not self._is_valid_host(host):
            self._send_json({"error": "INVALID_HOST", "message": "Host header is invalid or untrusted"}, 400)
            return

        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin):
            self._send_json({"error": "FORBIDDEN_ORIGIN", "message": "Untrusted cross-origin request rejected"}, 403)
            return

        if not self._is_authenticated():
            self._send_json({"error": "UNAUTHORIZED", "message": "Valid API session token required"}, 401)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body_json()

        def _require_expected_revision() -> int:
            """Settings concurrency contract: every persisted mutation MUST carry
            the caller's observed revision. Localhost is not a revision authority."""
            raw = body.get("expected_revision")
            if raw is None or (isinstance(raw, str) and not raw.strip().isdigit()):
                raise ValueError("MISSING_SETTINGS_REVISION: expected_revision is required for all Settings mutations.")
            return int(raw)

        # 0. Model & Provider Settings API (PROD-MODEL-SETTINGS-01)
        if path in ("/api/settings/model", "/api/settings/models"):
            try:
                expected_rev = _require_expected_revision()
                APP_BACKEND.settings_manager.update_settings(
                    updates=body,
                    expected_revision=expected_rev,
                )
                self._send_json(APP_BACKEND.settings_manager.get_safe_settings_dict())
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e), "current_revision": e.current_revision}, 409)
            except ValueError as e:
                if "MISSING_SETTINGS_REVISION" in str(e):
                    self._send_json({"error": "MISSING_SETTINGS_REVISION", "message": str(e)}, 400)
                else:
                    self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
            except (ModelSettingsValidationError, Exception) as e:
                if isinstance(e, (ModelSettingsValidationError, ValueError)):
                    self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
                else:
                    logger.error(f"Failed to update model settings: {e}")
                    self._send_json({"error": "SETTINGS_UPDATE_FAILED", "message": "Failed to update model settings."}, 500)
            return

        elif path == "/api/settings/providers/upsert":
            secret = body.get("api_key")
            try:
                expected_rev = _require_expected_revision()
                provider_data = {k: v for k, v in body.items()
                                 if k not in ("expected_revision",)}
                pdef = APP_BACKEND.settings_manager.upsert_provider(
                    provider_data=provider_data,
                    secret=secret,
                    expected_revision=expected_rev,
                )
                mgr = APP_BACKEND.settings_manager
                has_cred = mgr._secret_store.has_secret(pdef.credential_ref)
                safe = ModelSettingsManager.sanitize_provider_response(pdef)
                safe["has_credential"] = has_cred
                safe["is_configured"] = pdef.enabled and has_cred and bool(pdef.default_model)
                safe["settings_revision"] = mgr.get_settings().settings_revision
                self._send_json(safe)
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e), "current_revision": e.current_revision}, 409)
            except ValueError as e:
                if "MISSING_SETTINGS_REVISION" in str(e):
                    self._send_json({"error": "MISSING_SETTINGS_REVISION", "message": str(e)}, 400)
                else:
                    self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
            except (ModelSettingsValidationError, Exception) as e:
                if isinstance(e, (ModelSettingsValidationError, ValueError)):
                    self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
                else:
                    logger.error(f"Failed to upsert provider: {e}")
                    self._send_json({"error": "PROVIDER_UPSERT_FAILED", "message": "Failed to save provider."}, 500)
            return

        elif path.startswith("/api/settings/providers/") and path.endswith("/enable"):
            pid = path.split("/")[-2]
            try:
                expected_rev = _require_expected_revision()
                pdef = APP_BACKEND.settings_manager.enable_provider(pid, expected_revision=expected_rev)
                safe = ModelSettingsManager.sanitize_provider_response(pdef)
                safe["settings_revision"] = APP_BACKEND.settings_manager.get_settings().settings_revision
                self._send_json(safe)
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e)}, 409)
            except ValueError as e:
                code = "MISSING_SETTINGS_REVISION" if "MISSING_SETTINGS_REVISION" in str(e) else "VALIDATION_ERROR"
                self._send_json({"error": code, "message": str(e)}, 400)
            except Exception as e:
                self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
            return

        elif path.startswith("/api/settings/providers/") and path.endswith("/disable"):
            pid = path.split("/")[-2]
            try:
                expected_rev = _require_expected_revision()
                pdef = APP_BACKEND.settings_manager.disable_provider(pid, expected_revision=expected_rev)
                safe = ModelSettingsManager.sanitize_provider_response(pdef)
                safe["settings_revision"] = APP_BACKEND.settings_manager.get_settings().settings_revision
                self._send_json(safe)
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e)}, 409)
            except ValueError as e:
                code = "MISSING_SETTINGS_REVISION" if "MISSING_SETTINGS_REVISION" in str(e) else "VALIDATION_ERROR"
                self._send_json({"error": code, "message": str(e)}, 400)
            except Exception as e:
                self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
            return

        elif path.startswith("/api/settings/providers/") and path.endswith("/delete"):
            pid = path.split("/")[-2]
            try:
                expected_rev = _require_expected_revision()
                APP_BACKEND.settings_manager.delete_provider(pid, expected_revision=expected_rev)
                self._send_json({"status": "DELETED", "provider_id": pid,
                                 "settings_revision": APP_BACKEND.settings_manager.get_settings().settings_revision})
            except StaleSettingsRevisionError as e:
                self._send_json({"error": "STALE_SETTINGS_REVISION", "message": str(e), "current_revision": e.current_revision}, 409)
            except ValueError as e:
                code = "MISSING_SETTINGS_REVISION" if "MISSING_SETTINGS_REVISION" in str(e) else "VALIDATION_ERROR"
                self._send_json({"error": code, "message": str(e)}, 400)
            except (ModelSettingsValidationError, Exception) as e:
                if isinstance(e, (ModelSettingsValidationError, ValueError)):
                    self._send_json({"error": "VALIDATION_ERROR", "message": str(e)}, 400)
                else:
                    logger.error(f"Failed to delete provider: {e}")
                    self._send_json({"error": "PROVIDER_DELETE_FAILED", "message": "Failed to delete provider."}, 500)
            return

        elif path in ("/api/settings/models/test", "/api/settings/providers/test"):
            res = APP_BACKEND.settings_manager.test_connection(body)
            # Connection test responses carry only safe status metadata.
            forbidden = {"credential", "credential_ref", "authorization", "api_key", "secret"}
            self._send_json({k: v for k, v in res.items() if str(k).lower() not in forbidden})
            return

        # 1. Create / Manage Chat Sessions
        if path in ("/api/chat/sessions/first_turn", "/api/chat/sessions/first_message", "/api/chat/sessions/new/messages"):
            user_text = body.get("content", "").strip()
            raw_attachments = body.get("attachments", [])
            proj_id = body.get("project_id")
            biz_id = body.get("business_id")

            clean_title = user_text.split("\n")[0][:30] if user_text else (
                raw_attachments[0].get("filename_or_url", "New Chat") if raw_attachments else "New Chat"
            )
            session = APP_BACKEND.chat_mgr.create_session(
                title=clean_title,
                project_id=proj_id,
                business_id=biz_id,
            )
            chat_id = session.chat_id

            parsed_attachments: List[ChatAttachment] = []
            for att in raw_attachments:
                att_obj = ChatAttachment(
                    chat_id=chat_id,
                    filename_or_url=att.get("filename_or_url", "attachment.txt"),
                    attachment_type=AttachmentType[att.get("type", "TEXT").upper()] if att.get("type", "TEXT").upper() in AttachmentType.__members__ else AttachmentType.TEXT,
                    content=att.get("content", ""),
                )
                parsed_attachments.append(att_obj)
                APP_BACKEND.session_knowledge.index_attachment(att_obj)

            user_msg = APP_BACKEND.chat_mgr.add_user_message(chat_id, user_text, attachments=parsed_attachments)

            auto_execute = body.get("auto_execute", True)
            if auto_execute:
                self._execute_routed_turn(chat_id, user_text, parsed_attachments, session, user_msg=user_msg)
            else:
                self._send_json({"session": session.model_dump(), "user_message": user_msg.model_dump() if user_msg else None}, 201)
            return

        elif path == "/api/chat/sessions":
            title = body.get("title", "New Chat")
            proj_id = body.get("project_id")
            biz_id = body.get("business_id")
            session = APP_BACKEND.chat_mgr.create_session(title=title, project_id=proj_id, business_id=biz_id)
            self._send_json(session.model_dump(), 201)
            return

        elif path.endswith("/messages") and "/api/chat/sessions/" in path:
            chat_id = path.split("/")[-2]
            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            user_text = body.get("content", "")

            if not session or chat_id in ("new", "null", "undefined", ""):
                clean_title = user_text.strip().split("\n")[0][:30] if user_text.strip() else "New Chat"
                session = APP_BACKEND.chat_mgr.create_session(title=clean_title)
                chat_id = session.chat_id

            raw_attachments = body.get("attachments", [])
            parsed_attachments: List[ChatAttachment] = []

            for att in raw_attachments:
                att_obj = ChatAttachment(
                    chat_id=chat_id,
                    filename_or_url=att.get("filename_or_url", "attachment.txt"),
                    attachment_type=AttachmentType[att.get("type", "TEXT").upper()] if att.get("type", "TEXT").upper() in AttachmentType.__members__ else AttachmentType.TEXT,
                    content=att.get("content", ""),
                )
                parsed_attachments.append(att_obj)
                APP_BACKEND.session_knowledge.index_attachment(att_obj)

            # Record and persist user message immediately
            user_msg = APP_BACKEND.chat_mgr.add_user_message(chat_id, user_text, attachments=parsed_attachments)

            # Auto-title on first message
            if session.title in ("New Chat", "Cuộc trò chuyện mới", "New Conversation") and user_text.strip():
                clean_title = user_text.strip().split("\n")[0][:30]
                if clean_title:
                    APP_BACKEND.chat_mgr.update_session(chat_id, title=clean_title)

            auto_execute = body.get("auto_execute", True)
            if auto_execute:
                self._execute_routed_turn(chat_id, user_text, parsed_attachments, session, user_msg=user_msg)
            else:
                self._send_json({"status": "MESSAGE_RECEIVED", "message_id": user_msg.message_id if user_msg else None}, 201)
            return

        elif "/messages/" in path and path.endswith("/edit"):
            # POST /api/chat/sessions/<chat_id>/messages/<message_id>/edit
            parts = path.split("/")
            chat_id = parts[parts.index("sessions") + 1]
            msg_id = parts[parts.index("messages") + 1]
            new_text = body.get("content", "").strip()

            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            if not session:
                self._send_json({"error": "Session not found"}, 404)
                return

            updated_msg = APP_BACKEND.chat_mgr.update_message(msg_id, new_text, chat_id=chat_id)
            if not updated_msg:
                self._send_json({"error": "Message not found or does not belong to this session"}, 404)
                return

            # Re-execute continuation from this edited message with 0 duplicate user messages
            self._execute_routed_turn(chat_id, new_text, getattr(updated_msg, "attachments", []), session)
            return

        elif ("/messages/" in path and path.endswith("/regenerate")) or (path.endswith("/regenerate") and "/sessions/" in path):
            # POST /api/chat/sessions/<chat_id>/messages/<message_id>/regenerate OR /sessions/<chat_id>/regenerate
            parts = path.split("/")
            chat_id = parts[parts.index("sessions") + 1]
            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            if not session:
                self._send_json({"error": "Session not found"}, 404)
                return

            # Find the target user message to regenerate
            user_msgs = [m for m in session.messages if m.role in (ChatRole.USER, "user")]
            if not user_msgs:
                self._send_json({"error": "No user message to regenerate"}, 400)
                return

            target_user_msg = user_msgs[-1]
            self._execute_routed_turn(chat_id, target_user_msg.content, target_user_msg.attachments, session)
            return

        elif path.endswith("/retry") and "/api/chat/sessions/" in path:
            # POST /api/chat/sessions/<chat_id>/retry
            chat_id = path.split("/")[-2]
            session = APP_BACKEND.chat_mgr.get_session(chat_id)
            if not session:
                self._send_json({"error": "Session not found"}, 404)
                return

            user_msgs = [m for m in session.messages if m.role in (ChatRole.USER, "user")]
            if not user_msgs:
                self._send_json({"error": "No user message to retry"}, 400)
                return

            target_user_msg = user_msgs[-1]
            self._execute_routed_turn(chat_id, target_user_msg.content, target_user_msg.attachments, session)
            return

        # 2. Chat Promotion Endpoints
        elif path.endswith("/promote_to_project") and "/api/chat/sessions/" in path:
            chat_id = path.split("/")[-2]
            proj_name = body.get("project_name", "Promoted Project")
            desc = body.get("description", "")
            proj = APP_BACKEND.project_registry.promote_chat_to_project(chat_id=chat_id, project_name=proj_name, description=desc)
            self._send_json(proj.model_dump(), 201)
            return

        elif path.endswith("/promote_to_brand") and "/api/chat/sessions/" in path:
            chat_id = path.split("/")[-2]
            brand_name = body.get("brand_name", "Promoted Brand")
            industry = body.get("industry", "General")
            facts = body.get("extracted_facts", [])
            brand = APP_BACKEND.project_registry.promote_chat_to_brand(chat_id=chat_id, brand_name=brand_name, industry=industry, extracted_facts=facts)
            self._send_json(brand.model_dump() if hasattr(brand, "model_dump") else brand.__dict__, 201)
            return

        # 3. Create Project
        elif path == "/api/projects":
            name = body.get("project_name", "New Project")
            desc = body.get("description", "")
            biz_id = body.get("business_id")
            proj = APP_BACKEND.project_registry.create_project(name=name, description=desc, business_id=biz_id)
            self._send_json(proj.model_dump(), 201)
            return

        # 4. Create Business Workspace
        elif path == "/api/workspaces":
            biz_id = body.get("business_id", f"BIZ_{datetime.now().strftime('%Y%m%d%H%M%S')}")
            workspace = BusinessWorkspace(
                business_id=biz_id,
                brand_name=body.get("brand_name", "Untitled Brand"),
                description=body.get("description", ""),
                industry=body.get("industry", "General"),
                markets=body.get("markets", ["GLOBAL"]),
                products=body.get("products", []),
                audiences=body.get("audiences", []),
                brand_rules=body.get("brand_rules", {}),
                approved_claims=body.get("approved_claims", []),
                prohibited_claims=body.get("prohibited_claims", []),
                default_constraints=body.get("default_constraints", []),
                knowledge_scope=body.get("knowledge_scope", f"SCOPE_{biz_id}"),
                memory_scope=body.get("memory_scope", f"SCOPE_{biz_id}"),
            )
            APP_BACKEND.biz_registry.register_workspace(workspace)
            self._send_json({"success": True, "business_id": workspace.business_id, "brand_name": workspace.brand_name}, 201)
            return

        # 5. Ingest Persistent Knowledge
        elif path == "/api/knowledge/ingest":
            fmt_str = body.get("format", "MARKDOWN").upper()
            fmt = IngestionFormat[fmt_str] if fmt_str in IngestionFormat.__members__ else IngestionFormat.MARKDOWN
            req = KnowledgeIngestionRequest(
                source_name=body.get("source_name", "User Document"),
                source_type=SourceType[body.get("source_type", "BRAND_GUIDELINE")] if body.get("source_type") in SourceType.__members__ else SourceType.BRAND_GUIDELINE,
                content_or_path=body.get("content", ""),
                format=fmt,
                title=body.get("title", ""),
                scope=body.get("scope", "GLOBAL"),
                authority_level=AuthorityLevel[body.get("authority_level", "TIER_1_CANONICAL_GROUND_TRUTH")] if body.get("authority_level") in AuthorityLevel.__members__ else AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            )
            res = APP_BACKEND.workspace.knowledge_lifecycle.ingest(req)
            self._send_json({"success": res.success, "document_id": res.document_id, "chunk_count": res.chunk_count, "error": res.error})
            return

        # 6. Campaign Run Creation & Supervised Execution
        elif path == "/api/campaigns":
            biz_id = body.get("business_id", "BIZ_PRODUCTION_USER_01")
            objective = body.get("objective", "Launch campaign")
            campaign_id = body.get("campaign_id")
            ctx = APP_BACKEND.workspace.create_run(business_id=biz_id, objective=objective, campaign_id=campaign_id)
            self._send_json({"success": True, "run_id": ctx.run_id, "status": ctx.status.value}, 201)
            return

        elif path == "/api/campaigns/execute_supervised":
            biz_id = body.get("business_id", "BIZ_PRODUCTION_USER_01")
            objective = body.get("objective", "Execute campaign")
            auto_approve = body.get("auto_approve_token")
            if auto_approve:
                self._send_json(
                    {
                        "error": "AUTO_APPROVAL_FORBIDDEN",
                        "message": "Auto-approval of human-gated actions is not permitted. Use explicit human approval via the approvals API.",
                    },
                    403,
                )
                return
            artifact = APP_BACKEND.workspace.execute_supervised_campaign(
                business_id=biz_id,
                objective=objective,
            )
            self._send_json(
                {
                    "success": artifact.status == RuntimeStatus.COMPLETED,
                    "run_id": artifact.run_id,
                    "status": artifact.status.value,
                    "artifact_hash": artifact.final_artifact_hash,
                    "stages_completed": list(artifact.agent_outputs.keys()),
                }
            )
            return

        elif path.endswith("/pause") and "/api/campaigns/" in path:
            run_id = path.split("/")[-2]
            ok = APP_BACKEND.workspace.pause_run(run_id)
            self._send_json({"success": ok, "status": "PAUSED"})
            return

        elif path.endswith("/resume") and "/api/campaigns/" in path:
            run_id = path.split("/")[-2]
            ok = APP_BACKEND.workspace.resume_run(run_id)
            self._send_json({"success": ok, "status": "RUNNING"})
            return

        elif path.endswith("/cancel") and "/api/campaigns/" in path:
            run_id = path.split("/")[-2]
            ok = APP_BACKEND.workspace.cancel_run(run_id)
            self._send_json({"success": ok, "status": "CANCELLED"})
            return

        # 7. Memory Operations (Approve / Reject Promotion)
        elif path.endswith("/approve") and "/api/memory/" in path:
            mem_id = path.split("/")[-2]
            mem = APP_BACKEND.workspace.memory_ops.approve_promotion(mem_id, operator_notes=body.get("notes", ""))
            self._send_json({"success": mem is not None, "memory_id": mem_id})
            return

        elif path.endswith("/reject") and "/api/memory/" in path:
            mem_id = path.split("/")[-2]
            mem = APP_BACKEND.workspace.memory_ops.reject_promotion(mem_id, reason=body.get("reason", ""))
            self._send_json({"success": mem is not None, "memory_id": mem_id})
            return

        # 8. Learning Operations (Approve / Retest)
        elif path.endswith("/approve") and "/api/learning/" in path:
            event_id = path.split("/")[-2]
            mem = APP_BACKEND.workspace.learning_ops.approve_learning_promotion(event_id)
            self._send_json({"success": mem is not None, "promoted_memory_id": mem.memory_id if mem else None})
            return

        elif path.endswith("/retest") and "/api/learning/" in path:
            event_id = path.split("/")[-2]
            ok = APP_BACKEND.workspace.learning_ops.schedule_retest(event_id, reason=body.get("reason", ""))
            self._send_json({"success": ok, "event_id": event_id})
            return

        # 9. Run Queue Submission
        elif path == "/api/queue/runs":
            obj = body.get("objective", "Ad-hoc task")
            biz_id = body.get("business_id")
            proj_id = body.get("project_id")
            chat_id = body.get("chat_id")
            auto_tok = body.get("auto_approve_token")
            if auto_tok:
                self._send_json(
                    {
                        "error": "AUTO_APPROVAL_FORBIDDEN",
                        "message": "Auto-approval of human-gated actions is not permitted. Use explicit human approval via the approvals API.",
                    },
                    403,
                )
                return
            item = APP_BACKEND.run_manager.enqueue_run(
                objective=obj,
                business_id=biz_id,
                project_id=proj_id,
                chat_id=chat_id,
            )
            self._send_json(item.model_dump(), 202)
            return

        # 10. Approvals
        elif path in ("/api/approvals/create", "/api/approvals/issue"):
            # Direct client manufacture of human approval authority is strictly forbidden.
            # Actions requiring human approval must be proposed by deterministic runtime/policy as pending approvals.
            self._send_json(
                {
                    "error": "DIRECT_APPROVAL_FORBIDDEN",
                    "message": "Direct creation of approval authority is forbidden. Actions must originate as server-side pending proposals.",
                },
                403,
            )
            return

        elif path.endswith("/approve") and "/api/approvals/" in path:
            target_id = path.split("/")[-2]
            approved_by = body.get("approved_by", "Executive Operator")

            policy = APP_BACKEND.tool_gateway.policy_engine
            # Look up pending approval either by pending_approval_id or by run_id
            pending = policy.get_pending_approval(target_id)
            if not pending:
                pendings_for_run = policy.list_pending_approvals(run_id=target_id, status=PendingApprovalStatus.PENDING)
                if pendings_for_run:
                    pending = pendings_for_run[0]

            if not pending:
                self._send_json(
                    {
                        "error": "PENDING_APPROVAL_NOT_FOUND",
                        "message": f"No pending action found matching identifier '{target_id}'",
                    },
                    404,
                )
                return

            # Prevent caller from tampering with or overriding server-side pending action parameters
            if "capability_id" in body and body["capability_id"] and body["capability_id"] != pending.capability_id:
                self._send_json(
                    {
                        "error": "APPROVAL_TAMPERING_REJECTED",
                        "message": "Cannot alter capability_id during approval",
                    },
                    400,
                )
                return
            if "parameters" in body and body["parameters"] is not None:
                provided_fp = compute_request_fingerprint(
                    capability_id=pending.capability_id,
                    parameters=body["parameters"],
                    run_id=pending.run_id,
                    business_id=pending.business_id,
                )
                if provided_fp != pending.request_fingerprint:
                    self._send_json(
                        {
                            "error": "APPROVAL_TAMPERING_REJECTED",
                            "message": "Cannot alter action parameters during approval",
                        },
                        400,
                    )
                    return
            if "run_id" in body and body["run_id"] and body["run_id"] != pending.run_id:
                self._send_json(
                    {
                        "error": "APPROVAL_TAMPERING_REJECTED",
                        "message": "Cannot alter run_id during approval",
                    },
                    400,
                )
                return
            if "business_id" in body and body["business_id"] and body["business_id"] != pending.business_id:
                self._send_json(
                    {
                        "error": "APPROVAL_TAMPERING_REJECTED",
                        "message": "Cannot alter business_id during approval",
                    },
                    400,
                )
                return

            ok, record, msg = policy.approve_pending_action(
                pending_approval_id=pending.pending_approval_id,
                approved_by=approved_by,
            )
            if not ok or not record:
                self._send_json(
                    {
                        "error": msg,
                        "message": f"Failed to approve pending action: {msg}",
                    },
                    400,
                )
                return

            # If an active run context exists and was waiting for approval, resume it
            if pending.run_id in APP_BACKEND.runtime._active_contexts:
                ctx = APP_BACKEND.runtime._active_contexts[pending.run_id]
                ctx.approval_refs.append(record.approval_token)
                APP_BACKEND.runtime.request_publish_action(ctx, platform="linkedin", approval_token=record.approval_token)

            self._send_json(
                {
                    "success": True,
                    "status": "APPROVED",
                    "pending_approval_id": pending.pending_approval_id,
                    "approval_token": record.approval_token,
                    "capability_id": record.capability_id,
                    "run_id": record.run_id,
                },
                200,
            )
            return

        elif path.endswith("/reject") and "/api/approvals/" in path:
            target_id = path.split("/")[-2]
            reason = body.get("reason", "Rejected by operator")
            policy = APP_BACKEND.tool_gateway.policy_engine
            pending = policy.get_pending_approval(target_id)
            if not pending:
                pendings_for_run = policy.list_pending_approvals(run_id=target_id, status=PendingApprovalStatus.PENDING)
                if pendings_for_run:
                    pending = pendings_for_run[0]

            if not pending:
                self._send_json(
                    {
                        "error": "PENDING_APPROVAL_NOT_FOUND",
                        "message": f"No pending action found matching identifier '{target_id}'",
                    },
                    404,
                )
                return

            ok, msg = policy.reject_pending_action(pending.pending_approval_id, reason=reason)
            if not ok:
                self._send_json(
                    {
                        "error": msg,
                        "message": f"Failed to reject pending action: {msg}",
                    },
                    400,
                )
                return

            if pending.run_id in APP_BACKEND.runtime._active_contexts:
                APP_BACKEND.workspace.reject_gated_action(run_id=pending.run_id, reason=reason)

            self._send_json({"success": True, "status": "REJECTED", "pending_approval_id": pending.pending_approval_id})
            return

        # 11. Analytics Ingestion
        elif path == "/api/analytics/import":
            camp_id = body.get("campaign_id", "CAMP_USER_01")
            records = body.get("records", [])
            count = APP_BACKEND.analytics_conn.ingest_campaign_metrics(camp_id, records)
            self._send_json({"success": True, "campaign_id": camp_id, "records_ingested": count})
            return

        self._send_json({"error": "NOT_FOUND"}, 404)


def run_server(
    port: Optional[int] = None,
    host: Optional[str] = None,
    emit_bootstrap: bool = False,
) -> None:
    """Launch localhost-only Department Application API server."""
    # CLI Argument Parsing Support
    if port is None:
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    pass
    if host is None:
        for i, arg in enumerate(sys.argv):
            if arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]

    from config.authority import get_runtime_config
    runtime = get_runtime_config()
    target_host = host if host is not None else runtime.api_host
    target_port = port if port is not None else runtime.api_port
    from config.env_loader import parse_int, validate_loopback_host
    valid_host = validate_loopback_host(str(target_host), setting_name="API_HOST")
    valid_port = parse_int(target_port, default=8765, min_val=1, max_val=65535, setting_name="API_PORT")
    server_address = (valid_host, valid_port)
    try:
        httpd = ExclusiveThreadingHTTPServer(server_address, DepartmentAPIHandler)
    except OSError as bind_err:
        logger.error(f"Failed to bind API server to {valid_host}:{valid_port}: {bind_err}")
        sys.exit(1)

    # Secure Launcher/Desktop UI Bootstrap Handshake (PROD-UIAUTH-01)
    should_emit_bootstrap = (
        emit_bootstrap
        or "--emit-bootstrap" in sys.argv
        or os.environ.get("EMIT_UIAUTH_BOOTSTRAP") == "1"
    )
    if should_emit_bootstrap:
        bootstrap_data = {
            "token": GLOBAL_API_SESSION_TOKEN,
            "host": valid_host,
            "port": valid_port,
        }
        # Single-line framed output flushed directly to captured parent pipe
        print(f"UIAUTH_BOOTSTRAP_V1:{json.dumps(bootstrap_data)}", flush=True)

    logger.info(f"AI Marketing Department API running at http://{valid_host}:{valid_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
        logger.info("API server stopped.")


if __name__ == "__main__":
    run_server()
