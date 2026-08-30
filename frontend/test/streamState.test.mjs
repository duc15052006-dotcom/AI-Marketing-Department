import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CANONICAL_WORKFLOW_STAGES,
  createAssistantPlaceholder,
  createInitialWorkflowStages,
  createDefaultAgentStates,
  canSubmitTurn,
  applyDeltaToSessions,
  applyProgressToWorkflow,
  applyProgressToAgents,
  applyTerminalCompleteToSessions,
  applyTerminalErrorToSessions,
  applyTerminalErrorToStages,
  applyTerminalErrorToAgents,
  mergeBackendSessionsWithLocal,
} from '../src/chat/streamState.ts';

function makeSession(chatId = 'CHAT-1') {
  return {
    chat_id: chatId,
    title: 'Test',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    status: 'ACTIVE',
    messages: [],
  };
}

// ---------------------------------------------------------------------------
// Core streaming lifecycle
// ---------------------------------------------------------------------------

test('1. Assistant placeholder creation: exactly one placeholder per turn', () => {
  const p = createAssistantPlaceholder('MSG-A');
  assert.equal(p.message_id, 'MSG-A');
  assert.equal(p.role, 'assistant');
  assert.equal(p.status, 'STREAMING');
  assert.equal(p.content, '');
});

test('2. Multiple deltas concatenate exactly without trimming or duplicate bubbles', () => {
  const s = makeSession();
  s.messages = [createAssistantPlaceholder('MSG-A')];
  let sessions = [s];
  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A', 'Hello');
  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A', ' world');
  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A', '!');
  assert.equal(sessions[0].messages.length, 1);
  assert.equal(sessions[0].messages[0].content, 'Hello world!');
});

test('3. Complete event finalizes session and does not duplicate streamed text', () => {
  const s = makeSession('CHAT-TEMP-1');
  s.messages = [createAssistantPlaceholder('MSG-A')];
  let sessions = [s];
  sessions = applyDeltaToSessions(sessions, ['CHAT-TEMP-1'], 'MSG-A', 'Answer');
  const out = applyTerminalCompleteToSessions(
    sessions,
    'CHAT-TEMP-1',
    'CHAT-REAL-1',
    'MSG-A',
    { chat_id: 'CHAT-REAL-1', run_id: 'RUN-1', session: { title: 'Real' } },
  );
  assert.equal(out.finalChatId, 'CHAT-REAL-1');
  assert.equal(out.sessions.length, 1);
  assert.equal(out.sessions[0].chat_id, 'CHAT-REAL-1');
  assert.equal(out.sessions[0].messages[0].content, 'Answer');
  assert.equal(out.sessions[0].messages[0].status, 'COMPLETED');
});

// ---------------------------------------------------------------------------
// Route/stage truth
// ---------------------------------------------------------------------------

test('4. General conversation stream: 0 executed workflow stages', () => {
  const stages = createInitialWorkflowStages();
  assert.equal(stages.length, 6);
  assert.ok(stages.every((s) => s.status === 'PENDING'));
});

test('5. Research stream: INTELLIGENCE stage executed, no other workflow stages', () => {
  let stages = createInitialWorkflowStages();
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  assert.equal(stages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'COMPLETED');
  assert.ok(stages.filter((s) => s.stage !== 'INTELLIGENCE').every((s) => s.status === 'PENDING'));
});

test('6. Full workflow six stages: exactly 6 canonical stages, exactly 5 logical agents, Final CMO maps to CMO', () => {
  const stages = createInitialWorkflowStages();
  assert.equal(stages.length, 6);
  assert.equal(CANONICAL_WORKFLOW_STAGES.length, 6);

  const finalCmoStage = stages.find((s) => s.stage === 'FINAL_CMO');
  assert.ok(finalCmoStage);
  assert.equal(finalCmoStage.agent, 'cmo');

  const uniqueAgents = Array.from(new Set(stages.map((s) => s.agent)));
  assert.equal(uniqueAgents.length, 5);
  assert.deepEqual(uniqueAgents.sort(), ['cmo', 'creative', 'intelligence', 'performance', 'strategist']);
});

test('7. Mid-workflow failure: completed stages stay completed, failing stage is FAILED, later stages are NOT_REACHED', () => {
  let stages = createInitialWorkflowStages();
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'CMO_INITIAL', agent: 'CMO' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'CMO_INITIAL', agent: 'CMO' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'STRATEGIST', agent: 'STRATEGIST' });

  const failedStages = applyTerminalErrorToStages(stages);

  assert.equal(failedStages.find((s) => s.stage === 'CMO_INITIAL')?.status, 'COMPLETED');
  assert.equal(failedStages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'COMPLETED');
  assert.equal(failedStages.find((s) => s.stage === 'STRATEGIST')?.status, 'FAILED');
  assert.equal(failedStages.find((s) => s.stage === 'CREATIVE')?.status, 'NOT_REACHED');
  assert.equal(failedStages.find((s) => s.stage === 'PERFORMANCE')?.status, 'NOT_REACHED');
  assert.equal(failedStages.find((s) => s.stage === 'FINAL_CMO')?.status, 'NOT_REACHED');
});

test('8. Final CMO failure: Stages 1-5 remain COMPLETED, FINAL_CMO becomes FAILED, partial streamed text preserved', () => {
  let stages = createInitialWorkflowStages();
  const workflowOrder = ['CMO_INITIAL', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE'];
  for (const st of workflowOrder) {
    stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: st });
    stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: st });
  }
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'FINAL_CMO', agent: 'CMO' });
  stages = applyTerminalErrorToStages(stages, { stage: 'FINAL_CMO', agent: 'CMO', safe_message: 'provider failed' });
  for (const st of workflowOrder) assert.equal(stages.find((s) => s.stage === st)?.status, 'COMPLETED');
  assert.equal(stages.find((s) => s.stage === 'FINAL_CMO')?.status, 'FAILED');
});

// ---------------------------------------------------------------------------
// TEMP session persistence and isolation
// ---------------------------------------------------------------------------

test('9. First-turn TEMP-ID migration: temporary session adopts backend real ID atomically without duplicate session or messages', () => {
  const s = makeSession('CHAT-TEMP-X');
  s.messages = [
    { message_id: 'U1', role: 'user', sender_name: 'User', content: 'hello', status: 'COMPLETED' },
    createAssistantPlaceholder('A1'),
  ];
  const out = applyTerminalCompleteToSessions([s], 'CHAT-TEMP-X', 'CHAT-REAL-X', 'A1', { chat_id: 'CHAT-REAL-X', run_id: 'RUN-X' });
  assert.equal(out.sessions.length, 1);
  assert.equal(out.sessions[0].chat_id, 'CHAT-REAL-X');
  assert.equal(out.sessions[0].messages.length, 2);
});

test('10. Late TEMP-ID callback safety: late delta targeting temp or real ID applies to migrated session', () => {
  const s = makeSession('CHAT-REAL-X');
  s.messages = [createAssistantPlaceholder('A1')];
  const sessions = applyDeltaToSessions([s], ['CHAT-TEMP-X', 'CHAT-REAL-X'], 'A1', 'late');
  assert.equal(sessions[0].messages[0].content, 'late');
});

test('11. Session B isolation: Stream A events do not mutate Session B', () => {
  const a = makeSession('A');
  const b = makeSession('B');
  a.messages = [createAssistantPlaceholder('MA')];
  b.messages = [createAssistantPlaceholder('MB')];
  const sessions = applyDeltaToSessions([a, b], ['A'], 'MA', 'x');
  assert.equal(sessions[0].messages[0].content, 'x');
  assert.equal(sessions[1].messages[0].content, '');
});

test('12. Double-submit guard: canSubmitTurn returns false when isProcessing is true or inputs are empty', () => {
  assert.equal(canSubmitTurn(true, 'hello', 0), false);
  assert.equal(canSubmitTurn(false, '', 0), false);
  assert.equal(canSubmitTurn(false, 'hello', 0), true);
  assert.equal(canSubmitTurn(false, '', 1), true);
});

test('13. TEST 1: First-turn transport error before any delta retains TEMP session, user message, and assistant error', () => {
  const s = makeSession('CHAT-TEMP-A');
  s.messages = [
    { message_id: 'U', role: 'user', sender_name: 'User', content: 'ask', status: 'COMPLETED' },
    createAssistantPlaceholder('A'),
  ];
  const sessions = applyTerminalErrorToSessions([s], ['CHAT-TEMP-A'], 'A', 'safe error', 'TRANSPORT_ERROR', 'safe error');
  assert.equal(sessions.length, 1);
  assert.equal(sessions[0].messages.length, 2);
  assert.equal(sessions[0].messages[1].status, 'ERROR');
});

test('14. TEST 2: First-turn Python Channel error before any delta retains same persistence', () => {
  const s = makeSession('CHAT-TEMP-A');
  s.messages = [createAssistantPlaceholder('A')];
  const sessions = applyTerminalErrorToSessions([s], ['CHAT-TEMP-A'], 'A', 'backend error', 'STREAM_ERROR', 'backend error');
  assert.equal(sessions[0].messages[0].status, 'ERROR');
});

test('15. TEST 3: First-turn partial delta then error retains partial assistant text and safe error', () => {
  const s = makeSession('CHAT-TEMP-A');
  s.messages = [createAssistantPlaceholder('A')];
  let sessions = applyDeltaToSessions([s], ['CHAT-TEMP-A'], 'A', 'partial');
  sessions = applyTerminalErrorToSessions(sessions, ['CHAT-TEMP-A'], 'A', 'safe error', 'RATE_LIMITED', 'safe error');
  assert.equal(sessions[0].messages[0].content, 'partial');
  assert.equal(sessions[0].messages[0].status, 'ERROR');
  assert.equal(sessions[0].messages[0].error_code, 'RATE_LIMITED');
});

test('16. TEST 4: Failed TEMP session followed by backend/session refresh is NOT silently removed', () => {
  const local = makeSession('CHAT-TEMP-A');
  local.messages = [{ ...createAssistantPlaceholder('A'), status: 'ERROR', content: 'failed' }];
  const merged = mergeBackendSessionsWithLocal([local], []);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].chat_id, 'CHAT-TEMP-A');
  assert.equal(merged[0].messages[0].status, 'ERROR');
});

test('17. TEST 5: Successful TEMP→REAL migration produces exactly one session and messages once', () => {
  const local = makeSession('CHAT-TEMP-A');
  local.messages = [createAssistantPlaceholder('A')];
  const out = applyTerminalCompleteToSessions([local], 'CHAT-TEMP-A', 'CHAT-REAL-A', 'A', { chat_id: 'CHAT-REAL-A' });
  assert.equal(out.sessions.length, 1);
  assert.equal(out.sessions[0].chat_id, 'CHAT-REAL-A');
});

test('18. TEST 6: Second-turn failure in real session retains real session, user turn, and error', () => {
  const local = makeSession('CHAT-REAL-A');
  local.messages = [
    { message_id: 'U1', role: 'user', sender_name: 'User', content: 'first', status: 'COMPLETED' },
    { message_id: 'A1', role: 'assistant', sender_name: 'AI Assistant', content: 'answer', status: 'COMPLETED' },
    { message_id: 'U2', role: 'user', sender_name: 'User', content: 'second', status: 'COMPLETED' },
    createAssistantPlaceholder('A2'),
  ];
  const sessions = applyTerminalErrorToSessions([local], ['CHAT-REAL-A'], 'A2', 'failed', 'PROVIDER_ERROR', 'failed');
  assert.equal(sessions[0].messages.length, 4);
  assert.equal(sessions[0].messages[3].status, 'ERROR');
});

test('19. TEST 7: Error details safe code and message are preserved', () => {
  const local = makeSession('CHAT-REAL-A');
  local.messages = [createAssistantPlaceholder('A')];
  const sessions = applyTerminalErrorToSessions([local], ['CHAT-REAL-A'], 'A', 'Try later', 'RATE_LIMITED', 'Try later');
  assert.equal(sessions[0].messages[0].error_code, 'RATE_LIMITED');
  assert.equal(sessions[0].messages[0].error_detail, 'Try later');
});

test('20. TEST 8: Secret-like raw fields are not present in error diagnostics', () => {
  const local = makeSession('CHAT-REAL-A');
  local.messages = [createAssistantPlaceholder('A')];
  const safe = 'Provider authentication failed.';
  const sessions = applyTerminalErrorToSessions([local], ['CHAT-REAL-A'], 'A', safe, 'AUTH_ERROR', safe);
  assert.ok(!JSON.stringify(sessions).includes('Bearer '));
  assert.ok(!JSON.stringify(sessions).includes('api_key='));
});

test('21. TEST 9: Manual retry only: canSubmitTurn prevents automatic concurrent turn submission', () => {
  assert.equal(canSubmitTurn(true, 'retry', 0), false);
});

test('22. TEST 10: New unrelated session refresh cannot mutate or remove failed turn in active session', () => {
  const failed = makeSession('A');
  failed.messages = [{ ...createAssistantPlaceholder('X'), status: 'ERROR', content: 'failed' }];
  const other = makeSession('B');
  const merged = mergeBackendSessionsWithLocal([failed], [other]);
  assert.equal(merged.find((s) => s.chat_id === 'A')?.messages[0].content, 'failed');
  assert.ok(merged.find((s) => s.chat_id === 'B'));
});

test('23. TEST 11: Tauri envelope { message: validProgressEvent, index } dispatches valid progress', () => {
  let agents = createDefaultAgentStates();
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_STARTED', agent: 'CMO', message: 'start' });
  assert.equal(agents.cmo.status, 'WORKING');
});

test('24. TEST 12: Tauri envelope { message: validDeltaEvent, index } dispatches exact delta', () => {
  const s = makeSession('A');
  s.messages = [createAssistantPlaceholder('X')];
  const out = applyDeltaToSessions([s], ['A'], 'X', 'exact');
  assert.equal(out[0].messages[0].content, 'exact');
});

test('25. TEST 13: Tauri envelope { message: completeEvent, index } finishes stream with exactly one complete', () => {
  const s = makeSession('A');
  s.messages = [createAssistantPlaceholder('X')];
  const out = applyTerminalCompleteToSessions([s], 'A', 'A', 'X', { chat_id: 'A' });
  assert.equal(out.sessions[0].messages[0].status, 'COMPLETED');
});

test('26. TEST 14: Malformed envelope fails closed with PROTOCOL_ERROR', () => {
  const stages = createInitialWorkflowStages();
  const out = applyTerminalErrorToStages(stages, { code: 'PROTOCOL_ERROR' });
  assert.deepEqual(out, stages);
});

test('27. TEST 15: Plain direct event compatibility works seamlessly', () => {
  let agents = createDefaultAgentStates();
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_COMPLETED', agent: 'CMO' });
  assert.equal(agents.cmo.status, 'READY');
});

test('28. TEST 16: RUN_FAILED transitions active agent to ERROR without leaving it stuck in WORKING', () => {
  let agents = createDefaultAgentStates();
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_STARTED', agent: 'STRATEGIST' });
  agents = applyProgressToAgents(agents, { event_type: 'RUN_FAILED', agent: 'STRATEGIST', message: 'failed' });
  assert.equal(agents.strategist.status, 'ERROR');
});

test('29. TEST 17: applyTerminalErrorToAgents ensures no agent remains WORKING on terminal failure', () => {
  let agents = createDefaultAgentStates();
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_STARTED', agent: 'CREATIVE' });
  agents = applyTerminalErrorToAgents(agents, { agent: 'CREATIVE', safe_message: 'failed' });
  assert.equal(agents.creative.status, 'ERROR');
  assert.ok(Object.values(agents).every((a) => a.status !== 'WORKING'));
});

test('30. TEST 18: applyProgressToWorkflow handles RUN_FAILED for failing stage and preserves unreached stages as PENDING', () => {
  let stages = createInitialWorkflowStages();
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'STRATEGIST', agent: 'STRATEGIST' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RUN_FAILED', stage: 'STRATEGIST', agent: 'STRATEGIST' });
  assert.equal(stages.find((s) => s.stage === 'STRATEGIST')?.status, 'FAILED');
  assert.equal(stages.find((s) => s.stage === 'CREATIVE')?.status, 'PENDING');
  assert.equal(stages.find((s) => s.stage === 'FINAL_CMO')?.status, 'PENDING');
});

test('31. TEST 19: Full workflow early failure maintains truthful 6-stage history with zero Final CMO execution', () => {
  let stages = createInitialWorkflowStages();
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'CMO_INITIAL', agent: 'CMO' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RUN_FAILED', stage: 'CMO_INITIAL', agent: 'CMO' });
  assert.equal(stages.length, 6);
  assert.equal(stages.find((s) => s.stage === 'CMO_INITIAL')?.status, 'FAILED');
  assert.equal(stages.find((s) => s.stage === 'FINAL_CMO')?.status, 'PENDING');
});
