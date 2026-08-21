# Desktop Application State Model (UI_STATE_MODEL.md)

## 1. Overview & Architectural Principles

The frontend state management follows a deterministic, unidirectional data flow (Redux/Zustand pattern) synchronized with backend agent streams via WebSockets/Server-Sent Events (SSE).

```
┌──────────────────────────────────────────────────────────────────┐
│                         ROOT UI STATE                            │
├───────────────────┬───────────────────┬──────────────────────────┤
│ WorkspaceState    │ NavigationState   │ ChatStreamState          │
├───────────────────┼───────────────────┼──────────────────────────┤
│ AgentRosterState  │ ModelRouterState  │ AutonomyGovernanceState  │
├───────────────────┴───────────────────┴──────────────────────────┤
│                       InspectorPanelState                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Typed State Schemas

### 2.1 WorkspaceState
```typescript
interface WorkspaceState {
  workspaceId: string;                 // e.g. "WS-NEXUS-01"
  workspaceName: string;               // e.g. "Nexus Corp Workspace"
  activeBrandId: string;               // e.g. "BRAND-001"
  activeProductId: string;             // e.g. "PROD-CRM-01" (STRICT ISOLATION KEY)
  availableProducts: Array<{
    id: string;
    name: string;
    category: string;
    workspacePath: string;
  }>;
}
```

### 2.2 NavigationState
```typescript
type ScreenType =
  | "CHAT_WORKSPACE"
  | "AGENT_MANAGEMENT"
  | "PRODUCT_WORKSPACE"
  | "CAMPAIGN_WORKSPACE"
  | "CREATIVE_STUDIO"
  | "ANALYTICS_REPORTS"
  | "SETTINGS_PERMISSIONS";

interface NavigationState {
  activeScreen: ScreenType;
  sidebarCollapsed: boolean;
  activeThreadId: string | null;
  unreadApprovalCount: number;
}
```

### 2.3 ChatStreamState
```typescript
type MessageType =
  | "USER_PROMPT"
  | "AGENT_TEXT"
  | "DELEGATION_PREVIEW"
  | "RESEARCH_CARD"
  | "STRATEGY_CARD"
  | "CREATIVE_CONCEPT_CARD"
  | "VIDEO_JOB_CARD"
  | "APPROVAL_REQUEST_CARD"
  | "ANALYTICS_CARD"
  | "LEARNING_CARD";

interface ChatMessage {
  id: string;
  threadId: string;
  senderRole: "USER" | "CMO" | "INTELLIGENCE" | "STRATEGIST" | "CREATIVE" | "PERFORMANCE";
  type: MessageType;
  content: string;
  payload?: Record<string, any>;        // Typed schema payload (e.g. ResearchReport, TimelineManifest)
  epistemicBreakdown?: Array<{
    tier: "FACT" | "OBSERVATION" | "INFERENCE" | "HYPOTHESIS";
    statement: string;
    confidence: number;
    evidenceIds: string[];
  }>;
  taskId?: string;
  timestamp: string;
}

interface ChatStreamState {
  threads: Record<string, {
    id: string;
    title: string;
    productId: string;
    createdAt: string;
    updatedAt: string;
  }>;
  activeMessages: ChatMessage[];
  streamingNodes: Array<{
    agentId: string;
    stepDescription: string;
    status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
    progressPct?: number;
  }>;
  isStreaming: boolean;
}
```

### 2.4 AgentRosterState (Exactly 5 Permanent Agents)
```typescript
type AgentStatus = "IDLE" | "REASONING" | "EXECUTING_TOOL" | "AWAITING_APPROVAL" | "ERROR";

interface AgentRuntimeInfo {
  agentId: "cmo" | "intelligence" | "strategist" | "creative" | "performance";
  name: string;
  status: AgentStatus;
  activeTaskId: string | null;
  whitelistedTools: string[];
  enabledTools: string[];
  assignedModelOverride?: string;
}

interface AgentRosterState {
  agents: Record<string, AgentRuntimeInfo>;
}
```

### 2.5 ModelRouterState
```typescript
interface ModelRouterState {
  routingStrategy: "AUTO" | "COST_OPTIMIZED" | "PERFORMANCE_OPTIMIZED" | "MANUAL_PINNED";
  activeDefaultModel: string;          // e.g. "claude-3-5-sonnet-20241022"
  fallbackChain: string[];             // e.g. ["claude-3-5-sonnet", "gpt-4o", "gemini-2.0-flash"]
  providerStatus: {
    openai: boolean;
    anthropic: boolean;
    gemini: boolean;
    local: boolean;
  };
}
```

### 2.6 AutonomyGovernanceState
```typescript
type AutonomyMode = "MANUAL" | "SUPERVISED" | "AUTONOMOUS";

interface PendingApprovalRequest {
  id: string;
  taskId: string;
  agentId: string;
  actionType: "MUTATE_BUDGET" | "PUBLISH_LIVE" | "DESTRUCTIVE_OP" | "CREDENTIAL_UPDATE";
  summary: string;
  impactMetrics: {
    budgetUsd?: number;
    targetChannel?: string;
    riskScore: number;
  };
  payload: Record<string, any>;
  createdAt: string;
}

interface AutonomyGovernanceState {
  autonomyMode: AutonomyMode;           // Default: "SUPERVISED"
  pendingApprovals: PendingApprovalRequest[];
  maxDailyBudgetSpend: number;
  maxDailyChangePct: number;
}
```

### 2.7 InspectorPanelState
```typescript
type InspectorTab = "EPISTEMIC_TREE" | "EVIDENCE_SOURCES" | "TASK_TRACE" | "TOOL_CONTROLS" | "RAW_SCHEMA";

interface InspectorPanelState {
  isOpen: boolean;
  activeTab: InspectorTab;
  inspectingTaskId: string | null;
  inspectingEntityId: string | null;
  inspectingEntityData: Record<string, any> | null;
}
```
