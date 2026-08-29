/**
 * Deterministic production streaming state helpers.
 *
 * Invariants:
 * - exactly five permanent logical agents;
 * - exactly six workflow stages; FINAL_CMO is the CMO second pass;
 * - first reached failure is truthful; unreached later stages are NOT_REACHED;
 * - failed/local temporary turns survive backend refresh.
 */

export type AgentId = 'cmo' | 'intelligence' | 'strategist' | 'creative' | 'performance';
export type StageId = 'CMO_INITIAL' | 'INTELLIGENCE' | 'STRATEGIST' | 'CREATIVE' | 'PERFORMANCE' | 'FINAL_CMO';
export type StageStatus = 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'FAILED' | 'NOT_REACHED';

export interface PublicStreamErrorLike {
  code?: string;
  category?: string;
  safe_message?: string;
  message?: string;
  stage?: string;
  agent?: string;
  retryable?: boolean;
  http_status?: number | null;
  provider?: string;
  model_name?: string;
}

export interface WorkflowStageState {
  stage: StageId;
  agent: AgentId;
  label: string;
  status: StageStatus;
  detail?: string;
}

export interface AgentLiveState {
  status: 'READY' | 'WORKING' | 'ERROR';
  detail: string;
}

export interface ChatMessageItem {
  message_id: string;
  role: 'user' | 'assistant' | 'system';
  sender_name: string;
  content: string;
  run_id?: string;
  status?: string;
  error_code?: string;
  error_detail?: string;
  attachments?: Array<{ attachment_id: string; filename_or_url: string; attachment_type: string }>;
}

export interface ChatSessionItem {
  chat_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: string;
  optional_project_id?: string | null;
  optional_business_id?: string | null;
  messages: ChatMessageItem[];
}

export const CANONICAL_WORKFLOW_STAGES: Array<{ stage: StageId; agent: AgentId; label: string }> = [
  { stage: 'CMO_INITIAL', agent: 'cmo', label: 'CMO Initial Analysis' },
  { stage: 'INTELLIGENCE', agent: 'intelligence', label: 'Market & Competitor Intelligence' },
  { stage: 'STRATEGIST', agent: 'strategist', label: 'Strategy & Positioning' },
  { stage: 'CREATIVE', agent: 'creative', label: 'Creative & Copy Direction' },
  { stage: 'PERFORMANCE', agent: 'performance', label: 'Performance & Media Planning' },
  { stage: 'FINAL_CMO', agent: 'cmo', label: 'Final CMO Synthesis' },
];

const AGENT_IDS: AgentId[] = ['cmo', 'intelligence', 'strategist', 'creative', 'performance'];

export function createInitialWorkflowStages(): WorkflowStageState[] {
  return CANONICAL_WORKFLOW_STAGES.map((s) => ({ ...s, status: 'PENDING' }));
}

export function createDefaultAgentStates(): Record<AgentId, AgentLiveState> {
  return {
    cmo: { status: 'READY', detail: 'Strategy governance & master synthesis' },
    intelligence: { status: 'READY', detail: 'Market intelligence & evidence mining' },
    strategist: { status: 'READY', detail: 'Positioning architectures & messaging' },
    creative: { status: 'READY', detail: 'Concepts, hooks & script synthesis' },
    performance: { status: 'READY', detail: 'Analytics, attribution & allocation' },
  };
}

export function canSubmitTurn(isProcessing: boolean, chatInput: string, attachmentsCount: number): boolean {
  return !isProcessing && Boolean(chatInput.trim().length > 0 || attachmentsCount > 0);
}

export function createAssistantPlaceholder(assistantMsgId: string): ChatMessageItem {
  return { message_id: assistantMsgId, role: 'assistant', sender_name: 'AI Assistant', content: '', status: 'STREAMING' };
}

export function applyDeltaToSessions(
  sessions: ChatSessionItem[],
  targetChatIds: string[],
  assistantMsgId: string,
  deltaText: string
): ChatSessionItem[] {
  const targetSet = new Set(targetChatIds.filter(Boolean));
  return sessions.map((s) => targetSet.has(s.chat_id) ? {
    ...s,
    messages: s.messages.map((m) => m.message_id === assistantMsgId ? { ...m, content: m.content + deltaText } : m),
  } : s);
}

export function applyProgressToWorkflow(
  currentStages: WorkflowStageState[],
  progress: { event_type: string; stage?: string | null; agent?: string | null; message?: string }
): WorkflowStageState[] {
  if (!progress.stage) return currentStages;
  const rawStage = progress.stage.toUpperCase() as StageId;
  if (!CANONICAL_WORKFLOW_STAGES.some((s) => s.stage === rawStage)) return currentStages;
  const isFailed = progress.event_type.includes('FAILED') || progress.event_type.includes('ERROR');
  const isCompleted = progress.event_type.includes('COMPLETED');
  const isStarted = progress.event_type.includes('STARTED');
  return currentStages.map((st) => st.stage === rawStage ? {
    ...st,
    status: isFailed ? 'FAILED' : isCompleted ? 'COMPLETED' : isStarted ? 'ACTIVE' : st.status,
    detail: progress.message || st.detail,
  } : st);
}

export function applyProgressToAgents(
  currentAgents: Record<string, AgentLiveState>,
  progress: { event_type: string; agent?: string | null; message?: string }
): Record<string, AgentLiveState> {
  if (!progress.agent) return currentAgents;
  const rawAgent = progress.agent.toLowerCase() as AgentId;
  if (!AGENT_IDS.includes(rawAgent)) return currentAgents;
  const isFailed = progress.event_type.includes('FAILED') || progress.event_type.includes('ERROR');
  const isCompleted = progress.event_type.includes('COMPLETED');
  const isStarted = progress.event_type.includes('STARTED');
  return {
    ...currentAgents,
    [rawAgent]: {
      status: isFailed ? 'ERROR' : isCompleted ? 'READY' : isStarted ? 'WORKING' : currentAgents[rawAgent]?.status || 'READY',
      detail: progress.message || currentAgents[rawAgent]?.detail || '',
    },
  };
}

export function applyTerminalErrorToAgents(
  currentAgents: Record<string, AgentLiveState>,
  error?: PublicStreamErrorLike
): Record<string, AgentLiveState> {
  const failedAgent = (error?.agent || '').toLowerCase() as AgentId;
  const hasAuthoritativeAgent = AGENT_IDS.includes(failedAgent);
  const updated: Record<string, AgentLiveState> = {};
  for (const [key, state] of Object.entries(currentAgents)) {
    if ((hasAuthoritativeAgent && key === failedAgent) || (!hasAuthoritativeAgent && state.status === 'WORKING')) {
      updated[key] = { ...state, status: 'ERROR', detail: error?.safe_message || error?.message || state.detail || 'Execution stopped' };
    } else if (state.status === 'WORKING') {
      // A terminal run error must never leave another agent stuck in WORKING.
      updated[key] = { ...state, status: 'READY' };
    } else {
      updated[key] = state;
    }
  }
  return updated;
}

export function applyTerminalCompleteToSessions(
  sessions: ChatSessionItem[],
  turnChatId: string,
  assignedChatId: string,
  assistantMsgId: string,
  completePayload: { chat_id?: string; run_id?: string; session?: { title?: string } }
): { sessions: ChatSessionItem[]; finalChatId: string } {
  const finalChatId = completePayload.chat_id || assignedChatId || turnChatId;
  const finalTitle = completePayload.session?.title;
  const updatedSessions = sessions.map((s) => {
    if (s.chat_id !== turnChatId && s.chat_id !== assignedChatId && s.chat_id !== finalChatId) return s;
    return {
      ...s,
      chat_id: finalChatId,
      title: finalTitle || s.title,
      messages: s.messages.map((m) => m.message_id === assistantMsgId ? {
        ...m,
        status: 'COMPLETED',
        run_id: completePayload.run_id || m.run_id,
      } : m),
      updated_at: new Date().toISOString(),
    };
  });
  return { sessions: updatedSessions, finalChatId };
}

export function applyTerminalErrorToSessions(
  sessions: ChatSessionItem[],
  targetChatIds: string[],
  assistantMsgId: string,
  errorMessage: string,
  errorCode?: string,
  errorDetail?: string
): ChatSessionItem[] {
  const targetSet = new Set(targetChatIds.filter(Boolean));
  return sessions.map((s) => !targetSet.has(s.chat_id) ? s : {
    ...s,
    messages: s.messages.map((m) => m.message_id === assistantMsgId ? {
      ...m,
      status: 'ERROR',
      content: m.content || errorMessage,
      error_code: errorCode || 'REQUEST_FAILED',
      error_detail: errorDetail || errorMessage,
    } : m),
    updated_at: new Date().toISOString(),
  });
}

export function applyTerminalErrorToStages(
  currentStages: WorkflowStageState[],
  error?: PublicStreamErrorLike
): WorkflowStageState[] {
  const requestedStage = (error?.stage || '').toUpperCase() as StageId;
  let failedIndex = CANONICAL_WORKFLOW_STAGES.findIndex((s) => s.stage === requestedStage);
  if (failedIndex < 0) failedIndex = currentStages.findIndex((s) => s.status === 'ACTIVE');

  // A transport failure before any stage is reached must not invent a failed agent stage.
  if (failedIndex < 0) return currentStages;

  return currentStages.map((st, idx) => {
    if (idx === failedIndex) {
      return { ...st, status: 'FAILED', detail: error?.safe_message || error?.message || st.detail };
    }
    if (idx > failedIndex && (st.status === 'PENDING' || st.status === 'ACTIVE')) {
      return { ...st, status: 'NOT_REACHED', detail: st.detail || 'Not reached because an earlier stage failed.' };
    }
    return st;
  });
}

export function mergeBackendSessionsWithLocal(
  localSessions: ChatSessionItem[],
  backendSessions: ChatSessionItem[]
): ChatSessionItem[] {
  const backendMap = new Map<string, ChatSessionItem>();
  backendSessions.forEach((bs) => backendMap.set(bs.chat_id, bs));
  const merged: ChatSessionItem[] = [];
  const processedBackendIds = new Set<string>();

  for (const ls of localSessions) {
    if (ls.chat_id.startsWith('CHAT-TEMP-')) {
      merged.push(ls);
      continue;
    }
    const backendMatch = backendMap.get(ls.chat_id);
    if (backendMatch) {
      processedBackendIds.add(ls.chat_id);
      const hasLocalActiveOrFailedTurn = ls.messages.some((m) => m.status === 'ERROR' || m.status === 'STREAMING');
      if (hasLocalActiveOrFailedTurn || ls.messages.length > backendMatch.messages.length) {
        merged.push({ ...backendMatch, title: backendMatch.title || ls.title, messages: ls.messages });
      } else {
        merged.push(backendMatch);
      }
    } else {
      merged.push(ls);
    }
  }

  backendSessions.forEach((bs) => {
    if (!processedBackendIds.has(bs.chat_id)) merged.push(bs);
  });
  return merged;
}
