/**
 * Secure Frontend Streaming Client.
 *
 * All traffic crosses the native Tauri bridge.  The frontend never receives
 * backend bearer credentials.  Provider/runtime failures stay structured from
 * Python SSE through Tauri into React; unexpected EOF is a protocol failure,
 * never a false completion.
 */

export interface RuntimeProgressData {
  run_id: string;
  sequence: number;
  event_type: string;
  mode?: string;
  stage?: string | null;
  agent?: string | null;
  message?: string;
  metadata?: Record<string, any>;
  timestamp?: number;
}

export interface StreamDeltaData {
  content: string;
  provider?: string;
  model_name?: string;
}

export interface StreamErrorData {
  code: string;
  category?: string;
  message: string;
  safe_message?: string;
  retryable: boolean;
  http_status?: number | null;
  provider?: string;
  model_name?: string;
  stage?: string;
  agent?: string;
}

export type StreamEvent =
  | { event: 'progress'; data: RuntimeProgressData }
  | { event: 'delta'; data: StreamDeltaData }
  | { event: 'complete'; data: Record<string, any> }
  | { event: 'error'; data: StreamErrorData };

export class TauriChannel<T = any> {
  id: number;
  onmessage: (response: T) => void;

  constructor(onmessage?: (response: T) => void) {
    this.onmessage = onmessage || (() => {});
    const internals = typeof window !== 'undefined' ? (window as any).__TAURI_INTERNALS__ : null;
    if (internals?.transformCallback) {
      this.id = internals.transformCallback((response: any) => {
        if (response && typeof response === 'object' && 'message' in response) {
          this.onmessage?.(response.message);
        } else if (response && typeof response === 'object' && response.end) {
          // Native channel end is not itself a successful terminal frame.
        } else {
          this.onmessage?.(response);
        }
      });
    } else {
      this.id = 0;
    }
  }

  toJSON() {
    return `__CHANNEL__:${this.id}`;
  }

  close() {
    const internals = typeof window !== 'undefined' ? (window as any).__TAURI_INTERNALS__ : null;
    if (internals?.callbacks && this.id && internals.callbacks[this.id]) {
      delete internals.callbacks[this.id];
    }
  }
}

export interface StreamChatTurnOptions {
  path: string;
  body?: any;
  headers?: Record<string, string>;
  onProgress?: (progress: RuntimeProgressData) => void;
  onDelta?: (delta: StreamDeltaData) => void;
  onComplete?: (complete: Record<string, any>) => void;
  onError?: (error: StreamErrorData) => void;
}

function isTauriEnvironment(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

function safeLocalTransportError(code: string, message: string): StreamErrorData {
  // Never reflect arbitrary native/network exception text; it may contain local
  // paths, headers, query strings, or implementation details.
  return {
    code,
    category: 'TRANSPORT',
    message,
    safe_message: message,
    retryable: false,
    http_status: null,
    provider: '',
    model_name: '',
    stage: '',
    agent: '',
  };
}

function normalizeRemoteError(data: any): StreamErrorData {
  const retryable = typeof data?.retryable === 'boolean' ? data.retryable : false;
  const status = Number.isInteger(data?.http_status) && data.http_status >= 100 && data.http_status <= 599
    ? data.http_status
    : null;
  const safeMessage = typeof data?.safe_message === 'string' && data.safe_message
    ? data.safe_message.slice(0, 500)
    : (typeof data?.message === 'string' && data.message ? data.message.slice(0, 500) : 'Lỗi không xác định từ dịch vụ AI.');
  return {
    code: typeof data?.code === 'string' && data.code ? data.code.slice(0, 80) : 'STREAM_ERROR',
    category: typeof data?.category === 'string' ? data.category.slice(0, 80) : 'RUNTIME',
    message: safeMessage,
    safe_message: safeMessage,
    retryable,
    http_status: status,
    provider: typeof data?.provider === 'string' ? data.provider.slice(0, 120) : '',
    model_name: typeof data?.model_name === 'string' ? data.model_name.slice(0, 160) : '',
    stage: typeof data?.stage === 'string' ? data.stage.slice(0, 80) : '',
    agent: typeof data?.agent === 'string' ? data.agent.slice(0, 80) : '',
  };
}

/** Executes one streaming chat turn with exactly one trusted terminal result. */
export async function streamChatTurn(options: StreamChatTurnOptions): Promise<void> {
  const { path, body, headers, onProgress, onDelta, onComplete, onError } = options;
  let isTerminal = false;

  const handleTerminalComplete = (data: Record<string, any>) => {
    if (isTerminal) return;
    isTerminal = true;
    channel.close();
    onComplete?.(data);
  };

  const handleTerminalError = (err: StreamErrorData) => {
    if (isTerminal) return;
    isTerminal = true;
    channel.close();
    onError?.(err);
  };

  const channel = new TauriChannel<StreamEvent>((event) => {
    if (isTerminal) return;
    if (!event || typeof event !== 'object' || !('event' in event)) {
      handleTerminalError(safeLocalTransportError('PROTOCOL_ERROR', 'Malformed stream event payload received from native bridge.'));
      return;
    }

    switch (event.event) {
      case 'progress':
        if (event.data) onProgress?.(event.data);
        break;
      case 'delta':
        if (event.data && typeof event.data.content === 'string') onDelta?.(event.data);
        break;
      case 'complete':
        handleTerminalComplete(event.data || {});
        break;
      case 'error':
        handleTerminalError(normalizeRemoteError(event.data));
        break;
      default:
        handleTerminalError(safeLocalTransportError('UNKNOWN_EVENT_TYPE', 'Unknown stream event type received from native bridge.'));
        break;
    }
  });

  if (!isTauriEnvironment()) {
    handleTerminalError(safeLocalTransportError('TAURI_UNAVAILABLE', 'Native desktop streaming requires the Tauri runtime.'));
    return;
  }

  const tauri = (window as any).__TAURI__;
  const internals = (window as any).__TAURI_INTERNALS__;
  const invokeFn = tauri?.core?.invoke || internals?.invoke;
  if (!invokeFn) {
    handleTerminalError(safeLocalTransportError('INVOKE_UNAVAILABLE', 'Tauri invoke function is unavailable.'));
    return;
  }

  const stringBody = body !== undefined && body !== null
    ? (typeof body === 'string' ? body : JSON.stringify(body))
    : null;

  try {
    await invokeFn('api_stream', {
      args: { path, body: stringBody, headers: headers || {} },
      channel,
    });

    // Native command resolved but Python never emitted COMPLETE/ERROR: this is
    // a truncated protocol, not success.
    if (!isTerminal) {
      handleTerminalError(safeLocalTransportError('STREAM_TRUNCATED', 'The native stream ended before a terminal response was received.'));
    }
  } catch (_rawError: any) {
    if (!isTerminal) {
      handleTerminalError(safeLocalTransportError('TRANSPORT_ERROR', 'The native streaming transport failed.'));
    }
  }
}
