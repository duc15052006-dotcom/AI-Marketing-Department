/**
 * Secure Frontend API Client (PROD-UIAUTH-01).
 *
 * Provides a unified transport layer for both:
 * 1. Tauri Native Desktop: Routes requests via native IPC `api_request`, where
 *    the Rust host attaches the session bearer token outside JavaScript memory.
 * 2. Vite Browser / Dev: Routes requests via relative `/api/...` paths to the
 *    Vite server proxy, which injects the downstream Authorization header.
 *
 * Invariant: JavaScript never holds, stores, or transmits raw runtime bearer tokens.
 */

export interface ApiClientResponse<T = any> {
  ok: boolean;
  status: number;
  data: T;
  headers: Record<string, string>;
  rawResponse?: Response;
}

interface TauriApiResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

function isTauriEnvironment(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

async function invokeTauriApiRequest(
  method: string,
  path: string,
  body?: any,
  headers?: Record<string, string>
): Promise<Response> {
  const tauri = (window as any).__TAURI__;
  const internals = (window as any).__TAURI_INTERNALS__;
  const invokeFn = tauri?.core?.invoke || internals?.invoke;

  if (!invokeFn) {
    throw new Error('Tauri environment detected but invoke API is unavailable');
  }

  const stringBody = body !== undefined && body !== null ? (typeof body === 'string' ? body : JSON.stringify(body)) : null;

  const res: TauriApiResponse = await invokeFn('api_request', {
    args: {
      method: method.toUpperCase(),
      path,
      body: stringBody,
      headers: headers || {},
    },
  });

  return new Response(res.body, {
    status: res.status,
    headers: new Headers(res.headers),
  });
}

/**
 * Unified fetch wrapper that transparently routes through Tauri IPC in desktop mode
 * or through the authenticated Vite dev proxy in browser mode.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  // Normalize path to guarantee relative /api/... format
  let cleanPath = path;
  if (cleanPath.startsWith('http://127.0.0.1:8765') || cleanPath.startsWith('http://localhost:8765')) {
    cleanPath = cleanPath.replace(/^http:\/\/(127\.0\.0\.1|localhost):8765/, '');
  }

  if (isTauriEnvironment()) {
    const method = init?.method || 'GET';
    const body = init?.body;
    const headers: Record<string, string> = {};
    if (init?.headers) {
      if (init.headers instanceof Headers) {
        init.headers.forEach((val, key) => {
          headers[key] = val;
        });
      } else if (Array.isArray(init.headers)) {
        for (const [k, v] of init.headers) {
          headers[k] = v;
        }
      } else {
        Object.assign(headers, init.headers);
      }
    }
    return invokeTauriApiRequest(method, cleanPath, body, headers);
  }

  return window.fetch(cleanPath, init);
}

export async function apiGet<T = any>(path: string): Promise<T> {
  const res = await apiFetch(path, { method: 'GET' });
  if (!res.ok) {
    throw new Error(`API GET ${path} failed with status ${res.status}`);
  }
  return res.json();
}

export async function apiPost<T = any>(path: string, body?: any): Promise<T> {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    throw new Error(`API POST ${path} failed (${res.status}): ${errText}`);
  }
  return res.json();
}

/**
 * Initiates native desktop human confirmation for a consequential pending action.
 * In desktop mode: delegates to Tauri native IPC command `review_pending_approval`.
 */
export async function reviewPendingApproval(pendingId: string): Promise<any> {
  if (isTauriEnvironment()) {
    const tauri = (window as any).__TAURI__;
    const internals = (window as any).__TAURI_INTERNALS__;
    const invokeFn = tauri?.core?.invoke || internals?.invoke;
    if (!invokeFn) {
      throw new Error('Tauri invoke API unavailable');
    }
    const res: TauriApiResponse = await invokeFn('review_pending_approval', {
      args: { pending_id: pendingId },
    });
    if (res.status !== 200) {
      throw new Error(`Native approval failed (${res.status}): ${res.body}`);
    }
    return JSON.parse(res.body);
  }

  // In browser/Vite dev mode: approval decisions are blocked by policy
  throw new Error('APPROVAL_REQUIRES_NATIVE_DESKTOP: Consequential human approval requires Tauri desktop shell.');
}
