export type AgentRole = 'cmo' | 'intelligence' | 'strategist' | 'creative' | 'performance';

export type AgentStatus = 'IDLE' | 'THINKING' | 'RUNNING_TOOL' | 'WAITING_APPROVAL' | 'COMPLETED' | 'ERROR';

export interface SystemStatus {
  app_name: string;
  version: string;
  status: string;
  brain_version: string;
  permanent_agents: string[];
  permanent_agent_count: number;
  active_runs: number;
  completed_runs: number;
}

export interface ConnectorHealthItem {
  provider: string;
  health_status: 'AVAILABLE' | 'MISSING_CREDENTIAL' | 'RATE_LIMITED' | 'DEGRADED' | 'DISABLED' | 'UNAVAILABLE';
  read_write_mode: 'READ_ONLY' | 'WRITE_ONLY' | 'READ_WRITE';
  credential_state: string;
  capabilities: string[];
  last_checked?: string;
}

export interface BusinessWorkspace {
  business_id: string;
  brand_name: string;
  description: string;
  industry: string;
  is_demo_benchmark?: boolean;
  warning?: string | null;
  knowledge_scope: string;
  memory_scope: string;
  approved_claims_count: number;
}

export interface CampaignRun {
  run_id: string;
  business_id?: string;
  status: string;
  current_stage: string;
  objective?: string;
  completed_stages?: string[];
  checkpoints_count?: number;
  receipts_count?: number;
  artifact_hash?: string;
  stage_outputs?: Record<string, any>;
}

export interface KnowledgeDocumentItem {
  knowledge_id: string;
  title: string;
  source_type: string;
  authority_level: string;
  version: number;
  freshness: string;
  scope: string;
  chunks_count: number;
  content_preview: string;
  updated_at: string;
}

export interface MemoryItemView {
  memory_id: string;
  memory_type: string;
  agent_source: string;
  promotion_level: string;
  confidence: number;
  content_preview: string;
  evidence_count: number;
  created_at: string;
  review_date?: string | null;
  is_stale: boolean;
}

export interface LearningEventItem {
  event_id: string;
  campaign_id: string;
  hypothesis: string;
  primary_metric: string;
  result: Record<string, any>;
  decision: string;
  confidence: number;
  lesson: string;
  promotion_status: string;
  retest_required: boolean;
}

export interface PendingApprovalItem {
  run_id: string;
  business_id: string;
  objective: string;
  pending_since: string;
  action_type: string;
  risk_level: string;
}

export interface ExecutionReceiptItem {
  execution_id: string;
  run_id: string;
  agent_id: string;
  capability_id: string;
  provider: string;
  status: string;
  latency_ms: number;
  completed_at: string;
}
