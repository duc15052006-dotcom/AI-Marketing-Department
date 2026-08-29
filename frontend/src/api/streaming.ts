/**
 * Secure Frontend Streaming Client (PROD-STREAMING-IMPLEMENTATION-01-B5).
 *
 * Bridges the certified Tauri v2 native `api_stream` Channel to the React UI.
 *
 * Invariants:
 * 1. ZERO direct network/HTTP requests to Python backend. All traffic passes through Tauri IPC `api_stream`.
 * 2. JavaScript NEVER holds, receives, or transmits backend bearer tokens or API keys.
 * 3. Enforces a strict terminal lifecycle: exactly ONE terminal outcome (`COMPLETE` or `ERROR`).
 * 4. Preserves exact FIFO delta concatenation without token splitting or artificial formatting.
 * 5. Handles both Python Channel errors and Rust command invocation rejections with single sanitized UI errors.
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
}

export interface StreamErrorData {
  code: string;
  message: string;
  retryable?: boolean;
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
      this.id = internals.transformCallback((response: T) => {
        if (this.onmessage) {
          this.onmessage(response);
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

/**
 * Executes a streaming chat turn over Tauri v2 Channel.
 * Guarantees exactly one terminal callback (onComplete or onError) and enforces FIFO ordering.
 */
export async function streamChatTurn(options: StreamChatTurnOptions): Promise<void> {
  const { path, body, headers, onProgress, onDelta, onComplete, onError } = options;

  let isTerminal = false;

  const handleTerminalComplete = (data: Record<string, any>) => {
    if (isTerminal) return;
    isTerminal = true;
    channel.close();
    if (onComplete) {
      onComplete(data);
    }
  };

  const handleTerminalError = (err: StreamErrorData) => {
    if (isTerminal) return;
    isTerminal = true;
    channel.close();
    if (onError) {
      onError(err);
    }
  };

  const channel = new TauriChannel<StreamEvent>((event) => {
    if (isTerminal) {
      // Reject any late frames after stream has terminated
      return;
    }

    if (!event || typeof event !== 'object' || !('event' in event)) {
      handleTerminalError({
        code: 'PROTOCOL_ERROR',
        message: 'Malformed stream event payload received from native bridge.',
        retryable: false,
      });
      return;
    }

    switch (event.event) {
      case 'progress':
        if (onProgress && event.data) {
          onProgress(event.data);
        }
        break;

      case 'delta':
        if (onDelta && event.data && typeof event.data.content === 'string') {
          onDelta(event.data);
        }
        break;

      case 'complete':
        handleTerminalComplete(event.data || {});
        break;

      case 'error':
        handleTerminalError({
          code: event.data?.code || 'STREAM_ERROR',
          message: event.data?.message || 'Lỗi không xác định từ dịch vụ AI.',
          retryable: event.data?.retryable ?? false,
        });
        break;

      default:
        // Unknown event type: fail closed
        handleTerminalError({
          code: 'UNKNOWN_EVENT_TYPE',
          message: `Unknown stream event type received: ${(event as any).event}`,
          retryable: false,
        });
        break;
    }
  });

  // Verify Tauri runtime availability
  if (!isTauriEnvironment()) {
    handleTerminalError({
      code: 'TAURI_UNAVAILABLE',
      message: 'Native desktop streaming requires Tauri runtime environment.',
      retryable: false,
    });
    return;
  }

  const tauri = (window as any).__TAURI__;
  const internals = (window as any).__TAURI_INTERNALS__;
  const invokeFn = tauri?.core?.invoke || internals?.invoke;

  if (!invokeFn) {
    handleTerminalError({
      code: 'INVOKE_UNAVAILABLE',
      message: 'Tauri invoke function is unavailable.',
      retryable: false,
    });
    return;
  }

  const stringBody = body !== undefined && body !== null
    ? (typeof body === 'string' ? body : JSON.stringify(body))
    : null;

  try {
    await invokeFn('api_stream', {
      args: {
        path,
        body: stringBody,
        headers: headers || {},
      },
      channel,
    });

    // If invoke resolves without receiving complete/error on channel (e.g. unexpected EOF),
    // ensure the stream does not hang in active state.
    if (!isTerminal) {
      handleTerminalComplete({});
    }
  } catch (rawError: any) {
    // Rust command rejection before or during streaming (transport/network/header limit/frame limit failure)
    if (!isTerminal) {
      const errStr = typeof rawError === 'string' ? rawError : (rawError?.message || 'Lỗi kết nối stream native.');
      handleTerminalError({
        code: 'TRANSPORT_ERROR',
        message: errStr,
        retryable: false,
      });
    }
  }
}
