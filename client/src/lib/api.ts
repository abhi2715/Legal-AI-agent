// VITE_BACKEND_URL wins when set (Vercel → Settings → Environment Variables).
// Without it, production builds use the Render service and dev uses the local server.
const PROD_BACKEND = 'https://legal-ai-project.onrender.com';
const BASE = (import.meta.env.VITE_BACKEND_URL || (import.meta.env.PROD ? PROD_BACKEND : 'http://127.0.0.1:5001')).replace(/\/$/, '');

function userId(): string {
  try {
    let id = localStorage.getItem('lexiscan.user');
    if (!id) {
      id = `u-${crypto.randomUUID().slice(0, 12)}`;
      localStorage.setItem('lexiscan.user', id);
    }
    return id;
  } catch {
    return 'local';
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function headers(extra?: Record<string, string>): Record<string, string> {
  return { 'X-User-Id': userId(), ...extra };
}

async function parseError(resp: Response): Promise<ApiError> {
  let message = `Request failed (${resp.status})`;
  try {
    const body = await resp.json();
    if (typeof body.detail === 'string') message = body.detail;
    else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ');
  } catch {
    /* non-JSON error */
  }
  return new ApiError(resp.status, message);
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, {
      method: init.method ?? (init.body !== undefined ? 'POST' : 'GET'),
      headers: headers(init.body !== undefined ? { 'Content-Type': 'application/json' } : undefined),
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the LexiScan server. Is the backend running?');
  }
  if (!resp.ok) throw await parseError(resp);
  return resp.json() as Promise<T>;
}

export async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.set('file', file);
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, { method: 'POST', headers: headers(), body: form });
  } catch {
    throw new ApiError(0, 'Cannot reach the LexiScan server. Is the backend running?');
  }
  if (!resp.ok) throw await parseError(resp);
  return resp.json() as Promise<T>;
}

export async function download(path: string, filename: string): Promise<void> {
  const resp = await fetch(`${BASE}${path}`, { headers: headers() });
  if (!resp.ok) throw await parseError(resp);
  saveBlob(await resp.blob(), filename);
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface StreamHandlers {
  onNode?: (data: { node: string; trace: import('./types').TraceEntry[] }) => void;
  onState?: (data: import('./types').RunState) => void;
  onError?: (message: string) => void;
}

/** POST that returns Server-Sent Events: LangGraph progress streamed node by node. */
export async function stream(path: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    handlers.onError?.('Cannot reach the LexiScan server. Is the backend running?');
    return;
  }
  if (!resp.ok || !resp.body) {
    handlers.onError?.((await parseError(resp)).message);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = 'message';
      let data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7);
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      if (!data) continue;
      const parsed = JSON.parse(data);
      if (event === 'node') handlers.onNode?.(parsed);
      else if (event === 'state') handlers.onState?.(parsed);
      else if (event === 'error') handlers.onError?.(parsed.message);
    }
  }
}

export const backendUrl = BASE;
