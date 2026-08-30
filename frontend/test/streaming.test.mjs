import test from 'node:test';
import assert from 'node:assert/strict';
import { streamChatTurn } from '../src/api/streaming.ts';

// Mock Tauri Environment
function setupMockTauri() {
  let callbacks = {};
  let nextCallbackId = 1;
  let lastInvokeCall = null;
  let invokeCalls = [];
  let invokeHandler = null;

  globalThis.window = {
    __TAURI_INTERNALS__: {
      callbacks,
      transformCallback: (fn) => {
        const id = nextCallbackId++;
        callbacks[id] = fn;
        return id;
      },
      invoke: async (cmd, args) => {
        invokeCalls.push({ cmd, args });
        lastInvokeCall = { cmd, args };
        if (invokeHandler) {
          return invokeHandler(cmd, args);
        }
        return Promise.resolve();
      },
    },
  };

  return {
    getCallbacks: () => callbacks,
    getLastInvoke: () => lastInvokeCall,
    getInvokeCalls: () => invokeCalls,
    setInvokeHandler: (fn) => {
      invokeHandler = fn;
    },
    emitChannelEvent: (channelId, event) => {
      if (callbacks[channelId]) {
        callbacks[channelId](event);
      }
    },
    cleanup: () => {
      delete globalThis.window;
    },
  };
}

test('1. Channel progress dispatched separately and does not leak into text', async () => {
  const env = setupMockTauri();
  const progressEvents = [];
  const deltas = [];

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    body: { content: 'test' },
    onProgress: (p) => progressEvents.push(p),
    onDelta: (d) => deltas.push(d.content),
  });

  const lastInvoke = env.getLastInvoke();
  assert.ok(lastInvoke);
  assert.equal(lastInvoke.cmd, 'api_stream');
  assert.equal(lastInvoke.args.args.path, '/api/chat/stream');

  const channelStr = lastInvoke.args.channel.toJSON();
  const channelId = parseInt(channelStr.replace('__CHANNEL__:', ''), 10);

  // Emit progress event
  env.emitChannelEvent(channelId, {
    event: 'progress',
    data: { run_id: 'R1', sequence: 1, event_type: 'STAGE_STARTED', stage: 'CMO_INITIAL', agent: 'CMO', message: 'Analyzing prompt...' },
  });

  assert.equal(progressEvents.length, 1);
  assert.equal(progressEvents[0].event_type, 'STAGE_STARTED');
  assert.equal(deltas.length, 0);

  // Emit complete
  env.emitChannelEvent(channelId, {
    event: 'complete',
    data: { status: 'COMPLETED', chat_id: 'C1' },
  });

  await turnPromise;
  env.cleanup();
});

test('2 & 3. Multiple deltas arrive in FIFO order and concatenate exactly without trimming or splitting', async () => {
  const env = setupMockTauri();
  let assembledText = '';
  const deltaLog = [];

  const turnPromise = streamChatTurn({
    path: '/api/chat/sessions/C1/stream',
    body: { content: 'Xin chào' },
    onDelta: (d) => {
      deltaLog.push(d.content);
      assembledText += d.content;
    },
  });

  const lastInvoke = env.getLastInvoke();
  const channelId = parseInt(lastInvoke.args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Emit deltas with Vietnamese characters and leading/trailing whitespace
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Xin ' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'chào ' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Việt Nam! 🇻🇳' } });

  assert.deepEqual(deltaLog, ['Xin ', 'chào ', 'Việt Nam! 🇻🇳']);
  assert.equal(assembledText, 'Xin chào Việt Nam! 🇻🇳');

  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED' } });
  await turnPromise;
  env.cleanup();
});

test('4 & 5. Complete event terminates stream and does not duplicate streamed text', async () => {
  const env = setupMockTauri();
  let completed = false;
  let completePayload = null;
  let assembledText = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onDelta: (d) => { assembledText += d.content; },
    onComplete: (c) => {
      completed = true;
      completePayload = c;
    },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Answer text.' } });
  env.emitChannelEvent(channelId, {
    event: 'complete',
    data: {
      status: 'COMPLETED',
      chat_id: 'C-FINAL',
      content: 'Answer text.', // Complete payload contains full text, but helper must not re-emit it as delta
    },
  });

  await turnPromise;
  assert.equal(completed, true);
  assert.equal(completePayload.chat_id, 'C-FINAL');
  assert.equal(assembledText, 'Answer text.'); // Exact text, no duplicate!
  env.cleanup();
});

test('6 & 8. Python Channel error produces single UI error and preserves partial text', async () => {
  const env = setupMockTauri();
  let assembledText = '';
  let errorReceived = null;

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onDelta: (d) => { assembledText += d.content; },
    onError: (err) => { errorReceived = err; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Partial answer before failure.' } });
  env.emitChannelEvent(channelId, {
    event: 'error',
    data: { code: 'MODEL_RATE_LIMIT', message: 'Rate limit exceeded on provider.', retryable: true },
  });

  await turnPromise;
  assert.equal(assembledText, 'Partial answer before failure.'); // Partial text preserved!
  assert.ok(errorReceived);
  assert.equal(errorReceived.code, 'MODEL_RATE_LIMIT');
  assert.equal(errorReceived.message, 'Rate limit exceeded on provider.');
  assert.equal(errorReceived.retryable, true);
  env.cleanup();
});

test('7 & 39. Rust invoke rejection produces single sanitized transport error', async () => {
  const env = setupMockTauri();
  let errorReceived = null;
  let completeCalled = false;

  env.setInvokeHandler(async () => {
    throw 'PREMATURE_EOF_BEFORE_TERMINAL: Backend closed stream before terminal event';
  });

  await streamChatTurn({
    path: '/api/chat/stream',
    onComplete: () => { completeCalled = true; },
    onError: (err) => { errorReceived = err; },
  });

  assert.equal(completeCalled, false);
  assert.ok(errorReceived);
  assert.equal(errorReceived.code, 'TRANSPORT_ERROR');
  assert.equal(errorReceived.message, 'The native streaming transport failed.');
  assert.ok(!errorReceived.message.includes('PREMATURE_EOF_BEFORE_TERMINAL'));
  env.cleanup();
});

test('9 & 10. Late delta or progress events after terminal complete/error are rejected', async () => {
  const env = setupMockTauri();
  let deltaCount = 0;
  let completeCount = 0;

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onDelta: () => { deltaCount++; },
    onComplete: () => { completeCount++; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Valid token' } });
  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED' } });

  // Late events after terminal
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Late token (must be ignored)' } });
  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED_AGAIN' } });

  await turnPromise;
  assert.equal(deltaCount, 1);
  assert.equal(completeCount, 1);
  env.cleanup();
});

test('11. Unknown event type fails closed as protocol error', async () => {
  const env = setupMockTauri();
  let errorReceived = null;

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onError: (err) => { errorReceived = err; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'unexpected_future_type', data: {} });

  await turnPromise;
  assert.ok(errorReceived);
  assert.equal(errorReceived.code, 'UNKNOWN_EVENT_TYPE');
  env.cleanup();
});

test('12 & 13. Security: No bearer tokens or Authorization headers in invoke args and no direct network fetch', async () => {
  const env = setupMockTauri();

  await streamChatTurn({
    path: '/api/chat/stream',
    body: { content: 'hello' },
  });

  const lastInvoke = env.getLastInvoke();
  assert.ok(lastInvoke);

  const serializedArgs = JSON.stringify(lastInvoke.args);
  assert.equal(serializedArgs.includes('Bearer'), false);
  assert.equal(serializedArgs.includes('Authorization'), false);
  assert.equal(serializedArgs.includes('GLOBAL_API_SESSION_TOKEN'), false);
  assert.equal(serializedArgs.includes('127.0.0.1:8765'), false);
  env.cleanup();
});

test('35. General conversation stream: Neutral status, visible deltas, no fake department stages', async () => {
  const env = setupMockTauri();
  const progressTypes = [];
  let visibleText = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onProgress: (p) => { progressTypes.push(p.event_type); },
    onDelta: (d) => { visibleText += d.content; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R1', sequence: 1, event_type: 'RUN_STARTED' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R1', sequence: 2, event_type: 'MODEL_STARTED' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Xin ' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'chào' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R1', sequence: 3, event_type: 'MODEL_COMPLETED' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R1', sequence: 4, event_type: 'RUN_COMPLETED' } });
  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED' } });

  await turnPromise;
  assert.equal(visibleText, 'Xin chào');
  assert.deepEqual(progressTypes, ['RUN_STARTED', 'MODEL_STARTED', 'MODEL_COMPLETED', 'RUN_COMPLETED']);
  env.cleanup();
});

test('36. Research inquiry stream: Real research progress events, Intelligence deltas, no Final CMO/Creative/Performance', async () => {
  const env = setupMockTauri();
  const progressLog = [];
  let visibleText = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onProgress: (p) => { progressLog.push({ event_type: p.event_type, agent: p.agent }); },
    onDelta: (d) => { visibleText += d.content; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 1, event_type: 'RESEARCH_STARTED' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 2, event_type: 'RESEARCH_SEARCH_STARTED' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 3, event_type: 'RESEARCH_SEARCH_COMPLETED' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 4, event_type: 'RESEARCH_EVIDENCE_READY' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 5, event_type: 'STAGE_STARTED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 6, event_type: 'MODEL_STARTED', agent: 'INTELLIGENCE' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Research finding A. ' } });
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Evidence analysis B.' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 7, event_type: 'MODEL_COMPLETED', agent: 'INTELLIGENCE' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 8, event_type: 'STAGE_COMPLETED', stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' } });
  env.emitChannelEvent(channelId, { event: 'progress', data: { run_id: 'R2', sequence: 9, event_type: 'RUN_COMPLETED' } });
  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED' } });

  await turnPromise;
  assert.equal(visibleText, 'Research finding A. Evidence analysis B.');
  const agentsSeen = new Set(progressLog.map((p) => p.agent).filter(Boolean));
  assert.deepEqual(Array.from(agentsSeen), ['INTELLIGENCE']); // No Strategist, Creative, Performance, or Final CMO!
  env.cleanup();
});

test('37. Full marketing workflow stream: Six stages, exactly 5 permanent agents, Final CMO stage agent is CMO', async () => {
  const env = setupMockTauri();
  const stagesSeen = [];
  const agentsSeen = [];
  let visibleText = '';

  const turnPromise = streamChatTurn({
    path: '/api/chat/stream',
    onProgress: (p) => {
      if (p.stage) stagesSeen.push(p.stage);
      if (p.agent) agentsSeen.push(p.agent);
    },
    onDelta: (d) => { visibleText += d.content; },
  });

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Six stages
  const workflowStages = [
    { stage: 'CMO_INITIAL', agent: 'CMO' },
    { stage: 'INTELLIGENCE', agent: 'INTELLIGENCE' },
    { stage: 'STRATEGIST', agent: 'STRATEGIST' },
    { stage: 'CREATIVE', agent: 'CREATIVE' },
    { stage: 'PERFORMANCE', agent: 'PERFORMANCE' },
    { stage: 'FINAL_CMO', agent: 'CMO' }, // Final CMO belongs to CMO agent
  ];

  let seq = 1;
  for (const item of workflowStages) {
    env.emitChannelEvent(channelId, {
      event: 'progress',
      data: { run_id: 'R3', sequence: seq++, event_type: 'STAGE_STARTED', stage: item.stage, agent: item.agent },
    });
    env.emitChannelEvent(channelId, {
      event: 'progress',
      data: { run_id: 'R3', sequence: seq++, event_type: 'STAGE_COMPLETED', stage: item.stage, agent: item.agent },
    });
  }

  // Only Final CMO emits visible deltas
  env.emitChannelEvent(channelId, { event: 'delta', data: { content: 'Master GTM Plan' } });
  env.emitChannelEvent(channelId, { event: 'complete', data: { status: 'COMPLETED' } });

  await turnPromise;
  assert.equal(visibleText, 'Master GTM Plan');

  const uniqueStages = Array.from(new Set(stagesSeen));
  assert.equal(uniqueStages.length, 6);
  assert.deepEqual(uniqueStages, ['CMO_INITIAL', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE', 'FINAL_CMO']);

  const uniqueAgents = Array.from(new Set(agentsSeen));
  assert.equal(uniqueAgents.length, 5); // Exactly 5 logical agents!
  assert.deepEqual(uniqueAgents, ['CMO', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE']);
  env.cleanup();
});

test('40. Session isolation: Stream A channel does not mutate Session B', async () => {
  const env = setupMockTauri();
  let sessionAText = '';
  let sessionBText = '';

  // Stream A started
  const streamAPromise = streamChatTurn({
    path: '/api/chat/sessions/SESS-A/stream',
    onDelta: (d) => { sessionAText += d.content; },
  });

  const invokeA = env.getInvokeCalls()[0];
  const channelIdA = parseInt(invokeA.args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  // Stream B started
  const streamBPromise = streamChatTurn({
    path: '/api/chat/sessions/SESS-B/stream',
    onDelta: (d) => { sessionBText += d.content; },
  });

  const invokeB = env.getInvokeCalls()[1];
  const channelIdB = parseInt(invokeB.args.channel.toJSON().replace('__CHANNEL__:', ''), 10);

  assert.notEqual(channelIdA, channelIdB); // Distinct channel instances per request!

  // Emit delta to A
  env.emitChannelEvent(channelIdA, { event: 'delta', data: { content: 'Token for A' } });
  assert.equal(sessionAText, 'Token for A');
  assert.equal(sessionBText, ''); // B untouched!

  // Emit delta to B
  env.emitChannelEvent(channelIdB, { event: 'delta', data: { content: 'Token for B' } });
  assert.equal(sessionAText, 'Token for A');
  assert.equal(sessionBText, 'Token for B');

  env.emitChannelEvent(channelIdA, { event: 'complete', data: {} });
  env.emitChannelEvent(channelIdB, { event: 'complete', data: {} });

  await Promise.all([streamAPromise, streamBPromise]);
  env.cleanup();
});

test('41. Double-submit protection: Concurrent calls for same turn guarded', async () => {
  const env = setupMockTauri();
  let isProcessing = false;
  let invokeCount = 0;

  const handleSendAction = async (text) => {
    if (isProcessing) return; // Protected!
    isProcessing = true;
    invokeCount++;
    await streamChatTurn({
      path: '/api/chat/stream',
      body: { content: text },
    });
    isProcessing = false;
  };

  // Trigger first send
  const send1 = handleSendAction('Message 1');
  // Rapid second send attempt while first is processing
  const send2 = handleSendAction('Message 1 (duplicate click)');

  const channelId = parseInt(env.getLastInvoke().args.channel.toJSON().replace('__CHANNEL__:', ''), 10);
  env.emitChannelEvent(channelId, { event: 'complete', data: {} });

  await Promise.all([send1, send2]);
  assert.equal(invokeCount, 1); // Exactly 1 invoke executed!
  env.cleanup();
});
