"""Integrations Models Package.

Exports base interfaces, provider adapters (Gemini, OpenAI, TheSpark), agent loader,
invocation bridge, and multi-agent workflow orchestrator.
"""

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.agent_loader import AgentDefinition, AgentLoader, PERMANENT_AGENT_IDS
from integrations.models.cost_governance import CostGovernanceConfig, CostTracker
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.invocation import AgentRunResult, invoke_agent, parse_and_validate_agent_json
from integrations.models.openai_adapter import OpenAIProviderAdapter
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.thespark_adapter import TheSparkProviderAdapter
from integrations.models.orchestrator import (
    WorkflowDefinition,
    WorkflowExecutionSummary,
    WorkflowOrchestrator,
    WorkflowStep,
)
from integrations.models.registry import (
    AgentId,
    ConnectionTestResult,
    ConnectionTestStatus,
    ModelMetadata,
    ModelPolicy,
    ModelRegistry,
    ModelTarget,
    ProviderConfig,
    ProviderDefinition,
    ProviderProtocol,
    ProviderRegistry,
    ProviderRegistrySnapshot,
    normalize_agent_id,
    validate_base_url,
)
from integrations.models.transport import OpenAICompatibleTransport, classify_transport_error, sanitize_secrets
from integrations.models.profiles import ModelProfile, ProfileManager
from integrations.models.gateway import UniversalModelGateway, ProviderHealth
from integrations.models.router import ModelRouter

__all__ = [
    "BaseModelAdapter",
    "CostPolicy",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelResponseStatus",
    "ModelRole",
    "ModelUsage",
    "AgentDefinition",
    "AgentLoader",
    "PERMANENT_AGENT_IDS",
    "CostGovernanceConfig",
    "CostTracker",
    "GeminiProviderAdapter",
    "OpenAIProviderAdapter",
    "OpenAICompatibleProviderAdapter",
    "TheSparkProviderAdapter",
    "AgentRunResult",
    "invoke_agent",
    "parse_and_validate_agent_json",
    "WorkflowDefinition",
    "WorkflowExecutionSummary",
    "WorkflowOrchestrator",
    "WorkflowStep",
    "ProviderRegistry",
    "ProviderDefinition",
    "ProviderConfig",
    "ProviderProtocol",
    "ModelRegistry",
    "ModelMetadata",
    "ModelTarget",
    "AgentId",
    "normalize_agent_id",
    "ModelPolicy",
    "ConnectionTestStatus",
    "ConnectionTestResult",
    "ProviderRegistrySnapshot",
    "validate_base_url",
    "ModelProfile",
    "ProfileManager",
    "UniversalModelGateway",
    "ProviderHealth",
    "ModelRouter",
    "OpenAICompatibleTransport",
    "classify_transport_error",
    "sanitize_secrets",
]
