import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canSubmitTurn,
  createAssistantPlaceholder,
  createInitialWorkflowStages,
  createDefaultAgentStates,
  applyDeltaToSessions,
  applyProgressToWorkflow,
  applyProgressToAgents,
  applyTerminalCompleteToSessions,
  applyTerminalErrorToSessions,
  applyTerminalErrorToStages,
  CANONICAL_WORKFLOW_STAGES,
} from '../src/chat/streamState.ts';

test('1. Assistant placeholder creation: exactly one placeholder per turn', () => {
  const placeholder = createAssistantPlaceholder('MSG-A-123');
  assert.equal(placeholder.message_id, 'MSG-A-123');
  assert.equal(placeholder.role, 'assistant');
  assert.equal(placeholder.content, '');
  assert.equal(placeholder.status, 'STREAMING');
});

test('2. Multiple deltas concatenate exactly without trimming or duplicate bubbles', () => {
  const initialSessions = [
    {
      chat_id: 'CHAT-1',
      title: 'Test Chat',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Xin chào' },
        createAssistantPlaceholder('MSG-A-1'),
      ],
    },
  ];

  let sessions = applyDeltaToSessions(initialSessions, ['CHAT-1'], 'MSG-A-1', 'Xin ');
  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A-1', 'chào ');
  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A-1', 'Việt Nam!');

  const assistantMsg = sessions[0].messages.find((m) => m.message_id === 'MSG-A-1');
  assert.ok(assistantMsg);
  assert.equal(assistantMsg.content, 'Xin chào Việt Nam!');
  assert.equal(sessions[0].messages.length, 2); // Exactly 1 user + 1 assistant message!
});

test('3. Complete event finalizes session and does not duplicate streamed text', () => {
  const sessions = [
    {
      chat_id: 'CHAT-1',
      title: 'Original Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Hello' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'Assembled response text.', status: 'STREAMING' },
      ],
    },
  ];

  const completePayload = {
    chat_id: 'CHAT-1',
    run_id: 'RUN-999',
    session: { title: 'Updated Title' },
    content: 'Assembled response text.',
  };

  const { sessions: updatedSessions, finalChatId } = applyTerminalCompleteToSessions(
    sessions,
    'CHAT-1',
    'CHAT-1',
    'MSG-A-1',
    completePayload
  );

  assert.equal(finalChatId, 'CHAT-1');
  assert.equal(updatedSessions[0].title, 'Updated Title');
  const assistantMsg = updatedSessions[0].messages[1];
  assert.equal(assistantMsg.status, 'COMPLETED');
  assert.equal(assistantMsg.run_id, 'RUN-999');
  assert.equal(assistantMsg.content, 'Assembled response text.'); // Not duplicated!
});

test('4. General conversation stream: 0 executed workflow stages', () => {
  let stages = createInitialWorkflowStages();

  // General conversation emits RUN_STARTED, MODEL_STARTED, MODEL_COMPLETED, RUN_COMPLETED (no stage field)
  stages = applyProgressToWorkflow(stages, { event_type: 'RUN_STARTED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'MODEL_STARTED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'MODEL_COMPLETED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RUN_COMPLETED' });

  const executedStages = stages.filter((s) => s.status !== 'PENDING');
  assert.equal(executedStages.length, 0); // 0 executed workflow stages!
});

test('5. Research stream: INTELLIGENCE stage executed, no other workflow stages', () => {
  let stages = createInitialWorkflowStages();
  let agents = createDefaultAgentStates();

  stages = applyProgressToWorkflow(stages, { event_type: 'RESEARCH_STARTED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RESEARCH_SEARCH_STARTED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RESEARCH_SEARCH_COMPLETED' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RESEARCH_EVIDENCE_READY' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE', message: 'Analyzing data' });
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_STARTED', agent: 'INTELLIGENCE', message: 'Analyzing data' });

  assert.equal(stages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'ACTIVE');
  assert.equal(agents.intelligence.status, 'WORKING');

  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  agents = applyProgressToAgents(agents, { event_type: 'STAGE_COMPLETED', agent: 'INTELLIGENCE' });

  assert.equal(stages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'COMPLETED');
  assert.equal(agents.intelligence.status, 'READY');

  // Verify other stages remain PENDING
  const otherStages = stages.filter((s) => s.stage !== 'INTELLIGENCE');
  assert.ok(otherStages.every((s) => s.status === 'PENDING'));
});

test('6. Full workflow six stages: exactly 6 canonical stages, exactly 5 logical agents, Final CMO maps to CMO', () => {
  assert.equal(CANONICAL_WORKFLOW_STAGES.length, 6);
  const stages = createInitialWorkflowStages();
  assert.equal(stages.length, 6);

  const finalCmoStage = stages.find((s) => s.stage === 'FINAL_CMO');
  assert.ok(finalCmoStage);
  assert.equal(finalCmoStage.agent, 'cmo'); // Final CMO belongs to CMO agent!

  const uniqueAgents = Array.from(new Set(stages.map((s) => s.agent)));
  assert.equal(uniqueAgents.length, 5); // Exactly 5 logical agents!
  assert.deepEqual(uniqueAgents.sort(), ['cmo', 'creative', 'intelligence', 'performance', 'strategist']);
});

test('7. Mid-workflow failure: CMO_INITIAL and INTELLIGENCE remain COMPLETED, STRATEGIST becomes FAILED, later stages remain PENDING', () => {
  let stages = createInitialWorkflowStages();

  // Stage 1: CMO_INITIAL
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'CMO_INITIAL', agent: 'CMO' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'CMO_INITIAL', agent: 'CMO' });

  // Stage 2: INTELLIGENCE
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' });

  // Stage 3: STRATEGIST starts, then terminal failure occurs
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'STRATEGIST', agent: 'STRATEGIST' });

  assert.equal(stages.find((s) => s.stage === 'CMO_INITIAL')?.status, 'COMPLETED');
  assert.equal(stages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'COMPLETED');
  assert.equal(stages.find((s) => s.stage === 'STRATEGIST')?.status, 'ACTIVE');

  // Terminal error triggers applyTerminalErrorToStages
  const failedStages = applyTerminalErrorToStages(stages);

  assert.equal(failedStages.find((s) => s.stage === 'CMO_INITIAL')?.status, 'COMPLETED');
  assert.equal(failedStages.find((s) => s.stage === 'INTELLIGENCE')?.status, 'COMPLETED');
  assert.equal(failedStages.find((s) => s.stage === 'STRATEGIST')?.status, 'FAILED');
  assert.equal(failedStages.find((s) => s.stage === 'CREATIVE')?.status, 'PENDING');
  assert.equal(failedStages.find((s) => s.stage === 'PERFORMANCE')?.status, 'PENDING');
  assert.equal(failedStages.find((s) => s.stage === 'FINAL_CMO')?.status, 'PENDING');
});

test('8. Final CMO failure: Stages 1-5 remain COMPLETED, FINAL_CMO becomes FAILED, partial streamed text preserved', () => {
  let stages = createInitialWorkflowStages();

  const workflowOrder = ['CMO_INITIAL', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE'];
  for (const st of workflowOrder) {
    stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: st });
    stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_COMPLETED', stage: st });
  }

  // FINAL_CMO starts and deltas stream
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'FINAL_CMO', agent: 'CMO' });

  let sessions = [
    {
      chat_id: 'CHAT-1',
      title: 'Workflow Chat',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [createAssistantPlaceholder('MSG-A-1')],
    },
  ];

  sessions = applyDeltaToSessions(sessions, ['CHAT-1'], 'MSG-A-1', 'Partial final synthesis text');

  // Failure occurs
  stages = applyTerminalErrorToStages(stages);
  sessions = applyTerminalErrorToSessions(sessions, ['CHAT-1'], 'MSG-A-1', 'Provider connection lost');

  assert.equal(stages.find((s) => s.stage === 'FINAL_CMO')?.status, 'FAILED');
  for (const st of workflowOrder) {
    assert.equal(stages.find((s) => s.stage === st)?.status, 'COMPLETED');
  }

  const assistantMsg = sessions[0].messages[0];
  assert.equal(assistantMsg.status, 'ERROR');
  assert.equal(assistantMsg.content, 'Partial final synthesis text'); // Preserved!
});

test('9. First-turn TEMP-ID migration: temporary session adopts backend real ID atomically without duplicate session or messages', () => {
  const tempSessions = [
    {
      chat_id: 'CHAT-TEMP-123',
      title: 'Temporary Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Generate GTM strategy' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'GTM Plan Complete', status: 'STREAMING' },
      ],
    },
  ];

  const completePayload = {
    chat_id: 'CHAT-REAL-456',
    run_id: 'RUN-1',
    session: { title: 'Authoritative GTM Title' },
  };

  const { sessions: migratedSessions, finalChatId } = applyTerminalCompleteToSessions(
    tempSessions,
    'CHAT-TEMP-123',
    'CHAT-TEMP-123',
    'MSG-A-1',
    completePayload
  );

  assert.equal(finalChatId, 'CHAT-REAL-456');
  assert.equal(migratedSessions.length, 1); // Exactly 1 session!
  assert.equal(migratedSessions[0].chat_id, 'CHAT-REAL-456');
  assert.equal(migratedSessions[0].title, 'Authoritative GTM Title');
  assert.equal(migratedSessions[0].messages.length, 2); // Exactly 2 messages!
  assert.equal(migratedSessions[0].messages[1].status, 'COMPLETED');
});

test('10. Late TEMP-ID callback safety: late delta targeting temp or real ID applies to migrated session', () => {
  const sessions = [
    {
      chat_id: 'CHAT-REAL-456',
      title: 'Chat',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [{ message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'Initial', status: 'STREAMING' }],
    },
  ];

  // Target includes both turnChatId ('CHAT-TEMP-123') and assignedChatId ('CHAT-REAL-456')
  const updated = applyDeltaToSessions(sessions, ['CHAT-TEMP-123', 'CHAT-REAL-456'], 'MSG-A-1', ' + Late Delta');
  assert.equal(updated[0].messages[0].content, 'Initial + Late Delta');
});

test('11. Session B isolation: Stream A events do not mutate Session B', () => {
  const sessions = [
    {
      chat_id: 'SESSION-A',
      title: 'Chat A',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [{ message_id: 'MSG-A', role: 'assistant', sender_name: 'AI', content: 'Answer A', status: 'STREAMING' }],
    },
    {
      chat_id: 'SESSION-B',
      title: 'Chat B',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [{ message_id: 'MSG-B', role: 'assistant', sender_name: 'AI', content: 'Answer B', status: 'COMPLETED' }],
    },
  ];

  const mutated = applyDeltaToSessions(sessions, ['SESSION-A'], 'MSG-A', ' + Delta');
  assert.equal(mutated[0].messages[0].content, 'Answer A + Delta');
  assert.equal(mutated[1].messages[0].content, 'Answer B'); // Session B completely untouched!
});

test('12. Double-submit guard: canSubmitTurn returns false when isProcessing is true or inputs are empty', () => {
  assert.equal(canSubmitTurn(true, 'Hello', 0), false); // Guarded when processing!
  assert.equal(canSubmitTurn(false, '   ', 0), false); // Guarded when input is empty!
  assert.equal(canSubmitTurn(false, 'Valid input', 0), true); // Allowed!
  assert.equal(canSubmitTurn(false, '', 1), true); // Allowed with attachment!
});
