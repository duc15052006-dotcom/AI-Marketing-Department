/**
 * Production Stream State Management (PROD-STREAMING-IMPLEMENTATION-01-B5-R2 / PROD-UAT-CHAT-ERROR-PERSISTENCE-01).
 *
 * Pure, deterministic state helpers and transitions for React streaming chat.
 *
 * Invariants:
 * 1. Exactly 5 Logical Agents: CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE.
 * 2. Exactly 6 Workflow Stages: CMO_INITIAL, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE, FINAL_CMO.
 * 3. FINAL_CMO belongs to the CMO agent (not a 6th agent).
 * 4. Error preserves truthful stage history (completed remain COMPLETED, active becomes FAILED, unreached remain PENDING).
 * 5. Exactly one assistant placeholder per turn; deltas concatenate without trimming/duplication.
 * 6. Session migration from temporary ID to authoritative backend real ID preserves messages atomically.
 * 7. Error persistence: failed turns and unpersisted TEMP sessions survive backend refresh.
 */

export type AgentId = 'cmo' | 'intelligence' | 'strategist' | 'creative' | 'performance';

export type StageId =
  | 'CMO_INITIAL'
  | 'INTELLIGENCE'
  | 'STRATEGIST'
  | 'CREATIVE'
  | 'PERFORMANCE'
  | 'FINAL_CMO';

export type StageStatus = 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'FAILED';

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
  attachments?: Array<{
    attachment_id: string;
    filename_or_url: string;
    attachment_type: string;
  }>;
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

export function createInitialWorkflowStages(): WorkflowStageState[] {
  return CANONICAL_WORKFLOW_STAGES.map((s) => ({
    stage: s.stage,
    agent: s.agent,
    label: s.label,
    status: 'PENDING',
  }));
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

/**
 * Checks submission eligibility before performing any message insertion or network invoke.
 */
export function canSubmitTurn(isProcessing: boolean, chatInput: string, attachmentsCount: number): boolean {
  if (isProcessing) return false;
  return Boolean(chatInput.trim().length > 0 || attachmentsCount > 0);
}

/**
 * Instantiates exactly one assistant placeholder message for a new streaming turn.
 */
export function createAssistantPlaceholder(assistantMsgId: string): ChatMessageItem {
  return {
    message_id: assistantMsgId,
    role: 'assistant',
    sender_name: 'AI Assistant',
    content: '',
    status: 'STREAMING',
  };
}

/**
 * Appends streaming delta text directly to the assistant message in the matching session.
 */
export function applyDeltaToSessions(
  sessions: ChatSessionItem[],
  targetChatIds: string[],
  assistantMsgId: string,
  deltaText: string
): ChatSessionItem[] {
  const targetSet = new Set(targetChatIds.filter(Boolean));
  return sessions.map((s) => {
    if (!targetSet.has(s.chat_id)) return s;
    return {
      ...s,
      messages: s.messages.map((m) => {
        if (m.message_id !== assistantMsgId) return m;
        return {
          ...m,
          content: m.content + deltaText,
        };
      }),
    };
  });
}

/**
 * Updates 6-stage workflow presentation state based on trusted runtime progress events.
 */
export function applyProgressToWorkflow(
  currentStages: WorkflowStageState[],
  progress: { event_type: string; stage?: string | null; agent?: string | null; message?: string }
): WorkflowStageState[] {
  if (!progress.stage) return currentStages;

  const rawStage = progress.stage.toUpperCase() as StageId;
  const isKnownStage = CANONICAL_WORKFLOW_STAGES.some((s) => s.stage === rawStage);
  if (!isKnownStage) return currentStages;

  const isFailed = progress.event_type.includes('FAILED') || progress.event_type.includes('ERROR');
  const isCompleted = progress.event_type.includes('COMPLETED');
  const isStarted = progress.event_type.includes('STARTED');

  return currentStages.map((st) => {
    if (st.stage !== rawStage) return st;
    return {
      ...st,
      status: isFailed ? 'FAILED' : isCompleted ? 'COMPLETED' : isStarted ? 'ACTIVE' : st.status,
      detail: progress.message || st.detail,
    };
  });
}

/**
 * Updates 5 permanent agent live states based on trusted runtime progress events.
 */
export function applyProgressToAgents(
  currentAgents: Record<string, AgentLiveState>,
  progress: { event_type: string; agent?: string | null; message?: string }
): Record<string, AgentLiveState> {
  if (!progress.agent) return currentAgents;

  const rawAgent = progress.agent.toLowerCase() as AgentId;
  if (!['cmo', 'intelligence', 'strategist', 'creative', 'performance'].includes(rawAgent)) {
    return currentAgents;
  }

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

/**
 * Ensures any working agent is transitioned to ERROR (if it was active) on terminal error,
 * guaranteeing no agent remains stuck in WORKING.
 */
export function applyTerminalErrorToAgents(
  currentAgents: Record<string, AgentLiveState>
): Record<string, AgentLiveState> {
  const updated: Record<string, AgentLiveState> = {};
  for (const [key, state] of Object.entries(currentAgents)) {
    if (state.status === 'WORKING') {
      updated[key] = { ...state, status: 'ERROR', detail: state.detail || 'Execution stopped' };
    } else {
      updated[key] = state;
    }
  }
  return updated;
}

/**
 * Finalizes assistant placeholder and adopts authoritative backend session ID without duplicating text.
 */
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
    if (s.chat_id !== turnChatId && s.chat_id !== assignedChatId && s.chat_id !== finalChatId) {
      return s;
    }
    return {
      ...s,
      chat_id: finalChatId,
      title: finalTitle || s.title,
      messages: s.messages.map((m) => {
        if (m.message_id !== assistantMsgId) return m;
        return {
          ...m,
          status: 'COMPLETED',
          run_id: completePayload.run_id || m.run_id,
        };
      }),
      updated_at: new Date().toISOString(),
    };
  });

  return { sessions: updatedSessions, finalChatId };
}

/**
 * Handles terminal error: preserves partial streamed text if present, sets status to ERROR,
 * and attaches safe error diagnostic code and detail.
 */
export function applyTerminalErrorToSessions(
  sessions: ChatSessionItem[],
  targetChatIds: string[],
  assistantMsgId: string,
  errorMessage: string,
  errorCode?: string,
  errorDetail?: string
): ChatSessionItem[] {
  const targetSet = new Set(targetChatIds.filter(Boolean));
  return sessions.map((s) => {
    if (!targetSet.has(s.chat_id)) return s;
    return {
      ...s,
      messages: s.messages.map((m) => {
        if (m.message_id !== assistantMsgId) return m;
        return {
          ...m,
          status: 'ERROR',
          content: m.content ? m.content : errorMessage,
          error_code: errorCode || 'REQUEST_FAILED',
          error_detail: errorDetail || errorMessage,
        };
      }),
      updated_at: new Date().toISOString(),
    };
  });
}

/**
 * Preserves truthful stage failure history:
 * - Active stage becomes FAILED.
 * - Completed stages remain COMPLETED.
 * - Unreached stages remain PENDING.
 */
export function applyTerminalErrorToStages(currentStages: WorkflowStageState[]): WorkflowStageState[] {
  return currentStages.map((st) => {
    if (st.status === 'ACTIVE') {
      return { ...st, status: 'FAILED' };
    }
    return st;
  });
}

/**
 * Merges authoritative backend sessions with local sessions, guaranteeing:
 * 1. Unpersisted local temporary sessions (e.g. CHAT-TEMP-*) are NEVER deleted by backend refresh.
 * 2. Unpersisted / failed messages in existing sessions are retained and not wiped out by older backend state.
 * 3. Migrated / persisted sessions adopt backend data cleanly without duplicating items.
 */
export function mergeBackendSessionsWithLocal(
  localSessions: ChatSessionItem[],
  backendSessions: ChatSessionItem[]
): ChatSessionItem[] {
  const backendMap = new Map<string, ChatSessionItem>();
  for (const bs of backendSessions) {
    backendMap.set(bs.chat_id, bs);
  }

  const merged: ChatSessionItem[] = [];
  const processedBackendIds = new Set<string>();

  for (const ls of localSessions) {
    if (ls.chat_id.startsWith('CHAT-TEMP-')) {
      // Retain unpersisted / failed local TEMP sessions
      merged.push(ls);
      continue;
    }

    const backendMatch = backendMap.get(ls.chat_id);
    if (backendMatch) {
      processedBackendIds.add(ls.chat_id);
      // Check if local session contains unpersisted/failed/streaming messages that backend does not have
      const hasLocalActiveOrFailedTurn = ls.messages.some(
        (m) => m.status === 'ERROR' || m.status === 'STREAMING'
      );
      if (hasLocalActiveOrFailedTurn || ls.messages.length > backendMatch.messages.length) {
        merged.push({
          ...backendMatch,
          title: backendMatch.title || ls.title,
          messages: ls.messages,
        });
      } else {
        merged.push(backendMatch);
      }
    } else {
      merged.push(ls);
    }
  }

  for (const bs of backendSessions) {
    if (!processedBackendIds.has(bs.chat_id)) {
      merged.push(bs);
    }
  }

  return merged;
}
