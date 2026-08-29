/**
 * Secure Frontend Streaming Client.
 *
 * Traffic is Tauri IPC only. The browser never holds backend bearer tokens or
 * provider credentials. Exactly one terminal outcome is accepted.
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
  safe_message?: string;
  message: string;
  retryable?: boolean;
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
          // Native channel end is not success by itself. api_stream must still
          // deliver an explicit COMPLETE or ERROR event before invoke resolves.
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

function boundedString(value: unknown, fallback = '', max = 500): string {
  return typeof value === 'string' && value ? value.slice(0, max) : fallback;
}

function normalizeStreamError(data: any): StreamErrorData {
  const safeMessage = boundedString(data?.safe_message, '', 500) || boundedString(data?.message, 'Không thể hoàn tất yêu cầu.', 500);
  return {
    code: boundedString(data?.code || data?.error, 'STREAM_ERROR', 80),
    category: boundedString(data?.category, 'INTERNAL', 80),
    safe_message: safeMessage,
    message: safeMessage,
    retryable: typeof data?.retryable === 'boolean' ? data.retryable : false,
    http_status: Number.isInteger(data?.http_status) && data.http_status >= 100 && data.http_status <= 599 ? data.http_status : null,
    provider: boundedString(data?.provider, '', 120),
    model_name: boundedString(data?.model_name, '', 160),
    stage: boundedString(data?.stage, '', 80),
    agent: boundedString(data?.agent, '', 80),
  };
}

/** Execute one streaming turn over the Tauri v2 Channel. */
export async function streamChatTurn(options: StreamChatTurnOptions): Promise<void> {
  const { path, body, headers, onProgress, onDelta, onComplete, onError } = options;
  let isTerminal = false;
  let sawVisibleDelta = false;

  let channel: TauriChannel<StreamEvent>;

  const handleTerminalComplete = (data: Record<string, any>) => {
    if (isTerminal) return;
    isTerminal = true;
    channel?.close();
    onComplete?.(data);
  };

  const handleTerminalError = (err: StreamErrorData) => {
    if (isTerminal) return;
    isTerminal = true;
    channel?.close();
    onError?.(normalizeStreamError(err));
  };

  channel = new TauriChannel<StreamEvent>((event) => {
    if (isTerminal) return;

    if (!event || typeof event !== 'object' || !('event' in event)) {
      handleTerminalError({
        code: 'PROTOCOL_ERROR',
        category: 'STREAM_PROTOCOL',
        message: 'Malformed stream event received from the native bridge.',
        retryable: false,
      });
      return;
    }

    switch (event.event) {
      case 'progress':
        if (event.data) onProgress?.(event.data);
        break;
      case 'delta':
        if (event.data && typeof event.data.content === 'string' && event.data.content) {
          sawVisibleDelta = true;
          onDelta?.(event.data);
        }
        break;
      case 'complete':
        handleTerminalComplete(event.data || {});
        break;
      case 'error':
        handleTerminalError(normalizeStreamError(event.data));
        break;
      default:
        handleTerminalError({
          code: 'UNKNOWN_EVENT_TYPE',
          category: 'STREAM_PROTOCOL',
          message: 'Unknown stream event type received from native bridge.',
          retryable: false,
        });
        break;
    }
  });

  if (!isTauriEnvironment()) {
    handleTerminalError({
      code: 'TAURI_UNAVAILABLE',
      category: 'CONFIGURATION',
      message: 'Native desktop streaming requires the Tauri runtime.',
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
      category: 'CONFIGURATION',
      message: 'Tauri invoke is unavailable.',
      retryable: false,
    });
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

    // Explicit terminal event is mandatory. Native EOF is never success.
    if (!isTerminal) {
      handleTerminalError({
        code: 'STREAM_TRUNCATED',
        category: 'STREAM_PROTOCOL',
        message: 'The response stream ended before a terminal event was received.',
        retryable: !sawVisibleDelta,
      });
    }
  } catch (_rawError: any) {
    if (!isTerminal) {
      handleTerminalError({
        code: 'TRANSPORT_ERROR',
        category: 'NETWORK',
        message: 'The native streaming transport failed.',
        retryable: !sawVisibleDelta,
      });
    }
  }
}
