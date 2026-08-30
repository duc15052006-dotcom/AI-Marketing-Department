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
  applyTerminalErrorToAgents,
  mergeBackendSessionsWithLocal,
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

test('7. Mid-workflow failure: completed stages stay COMPLETED, failing stage is FAILED, later stages are NOT_REACHED', () => {
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

// =========================================================================
// NEW ERROR PERSISTENCE & SESSION SURVIVAL TESTS (PROD-UAT-CHAT-ERROR-PERSISTENCE-01)
// =========================================================================

test('13. TEST 1: First-turn transport error before any delta retains TEMP session, user message, and assistant error', () => {
  const tempSessions = [
    {
      chat_id: 'CHAT-TEMP-999',
      title: 'New Chat',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Chiến lược marketing Q4' },
        createAssistantPlaceholder('MSG-A-1'),
      ],
    },
  ];

  const failedSessions = applyTerminalErrorToSessions(
    tempSessions,
    ['CHAT-TEMP-999'],
    'MSG-A-1',
    'Lỗi kết nối native bridge.',
    'TRANSPORT_ERROR',
    'Native IPC connection disconnected'
  );

  assert.equal(failedSessions.length, 1);
  assert.equal(failedSessions[0].chat_id, 'CHAT-TEMP-999');
  assert.equal(failedSessions[0].messages.length, 2);
  assert.equal(failedSessions[0].messages[0].content, 'Chiến lược marketing Q4'); // User message retained!
  assert.equal(failedSessions[0].messages[1].status, 'ERROR'); // Assistant marked ERROR!
  assert.equal(failedSessions[0].messages[1].error_code, 'TRANSPORT_ERROR');
  assert.equal(failedSessions[0].messages[1].error_detail, 'Native IPC connection disconnected');
});

test('14. TEST 2: First-turn Python Channel error before any delta retains same persistence', () => {
  const tempSessions = [
    {
      chat_id: 'CHAT-TEMP-888',
      title: 'Ad-Hoc Turn',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Phân tích đối thủ' },
        createAssistantPlaceholder('MSG-A-1'),
      ],
    },
  ];

  const failedSessions = applyTerminalErrorToSessions(
    tempSessions,
    ['CHAT-TEMP-888'],
    'MSG-A-1',
    'Provider unavailable: xkiro endpoint timed out',
    'PROVIDER_UNAVAILABLE',
    'xkiro deepseek-v4-pro returned HTTP 504 Gateway Timeout'
  );

  assert.equal(failedSessions.length, 1);
  const asst = failedSessions[0].messages[1];
  assert.equal(asst.status, 'ERROR');
  assert.equal(asst.error_code, 'PROVIDER_UNAVAILABLE');
  assert.equal(asst.error_detail, 'xkiro deepseek-v4-pro returned HTTP 504 Gateway Timeout');
  assert.equal(failedSessions[0].messages[0].content, 'Phân tích đối thủ');
});

test('15. TEST 3: First-turn partial delta then error retains partial assistant text and safe error', () => {
  let sessions = [
    {
      chat_id: 'CHAT-TEMP-777',
      title: 'Prompt',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Viết lời chào' },
        createAssistantPlaceholder('MSG-A-1'),
      ],
    },
  ];

  sessions = applyDeltaToSessions(sessions, ['CHAT-TEMP-777'], 'MSG-A-1', 'Xin chào quý khách, tôi là');

  sessions = applyTerminalErrorToSessions(
    sessions,
    ['CHAT-TEMP-777'],
    'MSG-A-1',
    'Luồng phản hồi bị gián đoạn.',
    'STREAM_INTERRUPTED',
    'Socket connection closed by remote peer before complete'
  );

  const asst = sessions[0].messages[1];
  assert.equal(asst.status, 'ERROR');
  assert.equal(asst.content, 'Xin chào quý khách, tôi là'); // Partial content intact!
  assert.equal(asst.error_code, 'STREAM_INTERRUPTED');
  assert.equal(asst.error_detail, 'Socket connection closed by remote peer before complete');
});

test('16. TEST 4: Failed TEMP session followed by backend/session refresh is NOT silently removed', () => {
  const localSessions = [
    {
      chat_id: 'CHAT-TEMP-FAILED-1',
      title: 'Failed Initial Exploration',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Khảo sát thị trường' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'Lỗi', status: 'ERROR', error_code: 'PROVIDER_UNAVAILABLE' },
      ],
    },
  ];

  // Backend has existing older chats (or empty list) and has no record of CHAT-TEMP-FAILED-1
  const backendSessions = [
    {
      chat_id: 'CHAT-PERSISTED-100',
      title: 'Older Persisted Chat',
      created_at: '2026-08-29T10:00:00Z',
      updated_at: '2026-08-29T10:00:00Z',
      status: 'ACTIVE',
      messages: [],
    },
  ];

  const merged = mergeBackendSessionsWithLocal(localSessions, backendSessions);

  assert.equal(merged.length, 2); // Both the local failed TEMP chat and backend chat exist!
  const failedTemp = merged.find((s) => s.chat_id === 'CHAT-TEMP-FAILED-1');
  assert.ok(failedTemp);
  assert.equal(failedTemp.messages.length, 2);
  assert.equal(failedTemp.messages[0].content, 'Khảo sát thị trường');
  assert.equal(failedTemp.messages[1].status, 'ERROR');
});

test('17. TEST 5: Successful TEMP→REAL migration produces exactly one session and messages once', () => {
  const tempSessions = [
    {
      chat_id: 'CHAT-TEMP-555',
      title: 'Temp Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'First message' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'First response', status: 'STREAMING' },
      ],
    },
  ];

  const { sessions: migrated } = applyTerminalCompleteToSessions(
    tempSessions,
    'CHAT-TEMP-555',
    'CHAT-TEMP-555',
    'MSG-A-1',
    { chat_id: 'CHAT-REAL-777', session: { title: 'Authoritative Title' } }
  );

  // Now simulate subsequent backend refresh with the newly created backend session
  const backendSessions = [
    {
      chat_id: 'CHAT-REAL-777',
      title: 'Authoritative Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'First message' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI Assistant', content: 'First response', status: 'COMPLETED' },
      ],
    },
  ];

  const merged = mergeBackendSessionsWithLocal(migrated, backendSessions);

  assert.equal(merged.length, 1); // Exactly one session!
  assert.equal(merged[0].chat_id, 'CHAT-REAL-777');
  assert.equal(merged[0].messages.length, 2); // Exactly 2 messages!
});

test('18. TEST 6: Second-turn failure in real session retains real session, user turn, and error', () => {
  let sessions = [
    {
      chat_id: 'CHAT-REAL-123',
      title: 'Brand Campaign',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Turn 1 user' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI', content: 'Turn 1 answer', status: 'COMPLETED' },
        { message_id: 'MSG-U-2', role: 'user', sender_name: 'You', content: 'Turn 2 user prompt' },
        createAssistantPlaceholder('MSG-A-2'),
      ],
    },
  ];

  sessions = applyTerminalErrorToSessions(
    sessions,
    ['CHAT-REAL-123'],
    'MSG-A-2',
    'API Rate Limit Exceeded',
    'RATE_LIMIT_EXCEEDED',
    'Too many requests to upstream model gateway'
  );

  assert.equal(sessions[0].messages.length, 4);
  assert.equal(sessions[0].messages[2].content, 'Turn 2 user prompt');
  assert.equal(sessions[0].messages[3].status, 'ERROR');
  assert.equal(sessions[0].messages[3].error_code, 'RATE_LIMIT_EXCEEDED');

  // Backend session at this point only contains Turn 1
  const backendSessions = [
    {
      chat_id: 'CHAT-REAL-123',
      title: 'Brand Campaign',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Turn 1 user' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI', content: 'Turn 1 answer', status: 'COMPLETED' },
      ],
    },
  ];

  const merged = mergeBackendSessionsWithLocal(sessions, backendSessions);
  assert.equal(merged[0].messages.length, 4); // Failed turn 2 user & assistant messages are preserved!
  assert.equal(merged[0].messages[3].status, 'ERROR');
});

test('19. TEST 7: Error details safe code and message are preserved', () => {
  const sessions = [
    {
      chat_id: 'CHAT-1',
      title: 'Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [createAssistantPlaceholder('MSG-A-1')],
    },
  ];

  const updated = applyTerminalErrorToSessions(
    sessions,
    ['CHAT-1'],
    'MSG-A-1',
    'Sanitized user-facing message',
    'MODEL_GATEWAY_TIMEOUT',
    'Upstream gateway timed out after 30000ms'
  );

  const msg = updated[0].messages[0];
  assert.equal(msg.status, 'ERROR');
  assert.equal(msg.error_code, 'MODEL_GATEWAY_TIMEOUT');
  assert.equal(msg.error_detail, 'Upstream gateway timed out after 30000ms');
});

test('20. TEST 8: Secret-like raw fields are not present in error diagnostics', () => {
  const sessions = [
    {
      chat_id: 'CHAT-1',
      title: 'Title',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [createAssistantPlaceholder('MSG-A-1')],
    },
  ];

  const updated = applyTerminalErrorToSessions(
    sessions,
    ['CHAT-1'],
    'MSG-A-1',
    'Connection to AI gateway failed',
    'TRANSPORT_ERROR',
    'HTTP 502 Bad Gateway'
  );

  const jsonStr = JSON.stringify(updated);
  assert.ok(!jsonStr.includes('Bearer '));
  assert.ok(!jsonStr.includes('GLOBAL_API_SESSION_TOKEN'));
  assert.ok(!jsonStr.includes('secrets.vault'));
});

test('21. TEST 9: Manual retry only: canSubmitTurn prevents automatic concurrent turn submission', () => {
  assert.equal(canSubmitTurn(true, 'Retry message', 0), false); // When active/processing, automatic second invocation is blocked!
  assert.equal(canSubmitTurn(false, 'Retry message', 0), true); // Manual retry permitted when idle!
});

test('22. TEST 10: New unrelated session refresh cannot mutate or remove failed turn in active session', () => {
  const localSessions = [
    {
      chat_id: 'CHAT-FAILED-SESSION',
      title: 'Session With Error',
      created_at: '2026-08-29T12:00:00Z',
      updated_at: '2026-08-29T12:00:00Z',
      status: 'ACTIVE',
      messages: [
        { message_id: 'MSG-U-1', role: 'user', sender_name: 'You', content: 'Important question' },
        { message_id: 'MSG-A-1', role: 'assistant', sender_name: 'AI', content: 'Partial response', status: 'ERROR', error_code: 'STREAM_ERROR' },
      ],
    },
  ];

  const backendSessions = [
    {
      chat_id: 'CHAT-UNRELATED-200',
      title: 'Completely Different Chat',
      created_at: '2026-08-29T12:30:00Z',
      updated_at: '2026-08-29T12:30:00Z',
      status: 'ACTIVE',
      messages: [],
    },
  ];

  const merged = mergeBackendSessionsWithLocal(localSessions, backendSessions);

  assert.equal(merged.length, 2);
  const target = merged.find((s) => s.chat_id === 'CHAT-FAILED-SESSION');
  assert.ok(target);
  assert.equal(target.messages.length, 2);
  assert.equal(target.messages[0].content, 'Important question');
  assert.equal(target.messages[1].status, 'ERROR');
  assert.equal(target.messages[1].content, 'Partial response');
});

// ============================================================
// TAURI v2 IPC CHANNEL ENVELOPE UNWRAPPING TESTS (PROD-TAURI-CHANNEL-ENVELOPE-01)
// ============================================================
import { streamChatTurn } from '../src/api/streaming.ts';

function setupMockTauriEnv() {
  let callbacks = {};
  let nextCallbackId = 1;
  let lastInvokeCall = null;

  globalThis.window = {
    __TAURI_INTERNALS__: {
      callbacks,
      transformCallback: (fn) => {
        const id = nextCallbackId++;
        callbacks[id] = fn;
        return id;
      },
      invoke: async (cmd, args) => {
        lastInvokeCall = { cmd, args };
        return Promise.resolve();
      },
    },
  };

  return {
    getLastInvoke: () => lastInvokeCall,
    emitChannelEvent: (channelId, raw) => {
      if (callbacks[channelId]) {
        callbacks[channelId](raw);
      }
    },
    cleanup: () => {
      delete globalThis.window;
    },
  };
}

test('23. TEST 11: Tauri envelope { message: validProgressEvent, index } dispatches valid progress', async () => {
  const env = setupMockTauriEnv();
  const progressList = [];

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onProgress: (p) => progressList.push(p),
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Native Tauri v2 delivers { message: <StreamMessage>, index: 0 }
  env.emitChannelEvent(channelId, {
    message: {
      event: 'progress',
      data: {
        run_id: 'R-100',
        sequence: 1,
        event_type: 'RUN_STARTED',
        message: 'Bắt đầu xử lý tin nhắn',
      },
    },
    index: 0,
  });

  assert.equal(progressList.length, 1);
  assert.equal(progressList[0].event_type, 'RUN_STARTED');
  assert.equal(progressList[0].message, 'Bắt đầu xử lý tin nhắn');

  // Complete
  env.emitChannelEvent(channelId, {
    message: { event: 'complete', data: {} },
    index: 1,
  });

  await turnPromise;
  env.cleanup();
});

test('24. TEST 12: Tauri envelope { message: validDeltaEvent, index } dispatches exact delta', async () => {
  const env = setupMockTauriEnv();
  let gathered = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onDelta: (d) => { gathered += d.content; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, {
    message: { event: 'delta', data: { content: 'Xin chào' } },
    index: 0,
  });
  env.emitChannelEvent(channelId, {
    message: { event: 'delta', data: { content: ' bạn!' } },
    index: 1,
  });

  assert.equal(gathered, 'Xin chào bạn!');

  env.emitChannelEvent(channelId, {
    message: { event: 'complete', data: {} },
    index: 2,
  });

  await turnPromise;
  env.cleanup();
});

test('25. TEST 13: Tauri envelope { message: completeEvent, index } finishes stream with exactly one complete', async () => {
  const env = setupMockTauriEnv();
  let completeCount = 0;

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onComplete: () => { completeCount++; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, {
    message: { event: 'complete', data: { status: 'COMPLETED' } },
    index: 0,
  });

  // Late frame after complete
  env.emitChannelEvent(channelId, {
    message: { event: 'delta', data: { content: 'late delta' } },
    index: 1,
  });

  await turnPromise;
  assert.equal(completeCount, 1);
  env.cleanup();
});

test('26. TEST 14: Malformed envelope fails closed with PROTOCOL_ERROR', async () => {
  const env = setupMockTauriEnv();
  let errorObj = null;

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onError: (err) => { errorObj = err; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Missing event property inside message payload -> fails closed
  env.emitChannelEvent(channelId, {
    message: { invalid_field: 123 },
    index: 0,
  });

  await turnPromise;
  assert.ok(errorObj);
  assert.equal(errorObj.code, 'PROTOCOL_ERROR');
  env.cleanup();
});

test('27. TEST 15: Plain direct event compatibility works seamlessly', async () => {
  const env = setupMockTauriEnv();
  let gathered = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onDelta: (d) => { gathered += d.content; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Direct un-enveloped event
  env.emitChannelEvent(channelId, {
    event: 'delta',
    data: { content: 'Direct payload' },
  });

  assert.equal(gathered, 'Direct payload');

  env.emitChannelEvent(channelId, {
    event: 'complete',
    data: {},
  });

  await turnPromise;
  env.cleanup();
});

test('28. TEST 16: RUN_FAILED transitions active agent to ERROR without leaving it stuck in WORKING', () => {
  let agents = createDefaultAgentStates();

  // Agent starts working
  agents = applyProgressToAgents(agents, {
    event_type: 'STAGE_STARTED',
    stage: 'CMO_INITIAL',
    agent: 'CMO',
    message: 'Bắt đầu phân tích sơ bộ (CMO)',
  });
  assert.equal(agents.cmo.status, 'WORKING');
  assert.equal(agents.intelligence.status, 'READY');

  // Agent fails
  agents = applyProgressToAgents(agents, {
    event_type: 'RUN_FAILED',
    stage: 'CMO_INITIAL',
    agent: 'CMO',
    message: 'Giai đoạn CMO Initial thất bại: MODEL_PROVIDER_FAILURE',
  });

  // CMO must NOT remain stuck in WORKING!
  assert.equal(agents.cmo.status, 'ERROR');
  assert.match(agents.cmo.detail, /MODEL_PROVIDER_FAILURE/);

  // Unrelated never-started agents remain in READY!
  assert.equal(agents.intelligence.status, 'READY');
  assert.equal(agents.strategist.status, 'READY');
  assert.equal(agents.creative.status, 'READY');
  assert.equal(agents.performance.status, 'READY');
});

test('29. TEST 17: applyTerminalErrorToAgents ensures no agent remains WORKING on terminal failure', () => {
  let agents = createDefaultAgentStates();
  agents.cmo.status = 'WORKING';
  agents.cmo.detail = 'Connecting to model...';

  const cleaned = applyTerminalErrorToAgents(agents);
  assert.equal(cleaned.cmo.status, 'ERROR');
  assert.equal(cleaned.intelligence.status, 'READY');
});

test('30. TEST 18: applyProgressToWorkflow handles RUN_FAILED for failing stage and preserves unreached stages as PENDING', () => {
  let stages = createInitialWorkflowStages();

  // CMO_INITIAL starts
  stages = applyProgressToWorkflow(stages, {
    event_type: 'STAGE_STARTED',
    stage: 'CMO_INITIAL',
    agent: 'CMO',
  });
  assert.equal(stages[0].status, 'ACTIVE');

  // CMO_INITIAL fails
  stages = applyProgressToWorkflow(stages, {
    event_type: 'RUN_FAILED',
    stage: 'CMO_INITIAL',
    agent: 'CMO',
    message: 'Giai đoạn CMO Initial thất bại',
  });

  assert.equal(stages[0].status, 'FAILED');
  assert.equal(stages[1].status, 'PENDING'); // Intelligence
  assert.equal(stages[2].status, 'PENDING'); // Strategist
  assert.equal(stages[3].status, 'PENDING'); // Creative
  assert.equal(stages[4].status, 'PENDING'); // Performance
  assert.equal(stages[5].status, 'PENDING'); // Final CMO remains PENDING!
});

test('31. TEST 19: Full workflow early failure maintains truthful 6-stage history with zero Final CMO execution', () => {
  let stages = createInitialWorkflowStages();

  // CMO starts and fails
  stages = applyProgressToWorkflow(stages, { event_type: 'STAGE_STARTED', stage: 'CMO_INITIAL', agent: 'CMO' });
  stages = applyProgressToWorkflow(stages, { event_type: 'RUN_FAILED', stage: 'CMO_INITIAL', agent: 'CMO' });

  // Terminal stream error occurs
  stages = applyTerminalErrorToStages(stages);

  assert.equal(stages.length, 6);
  assert.equal(stages[0].stage, 'CMO_INITIAL');
  assert.equal(stages[0].status, 'FAILED');

  for (let i = 1; i < 6; i++) {
    assert.equal(stages[i].status, 'PENDING', `Stage ${stages[i].stage} must remain PENDING`);
  }
});

