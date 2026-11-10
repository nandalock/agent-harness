const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ContextUsage {
  event_seq: number;
  model: string;
  used_tokens: number;
  context_window: number;
  input_budget: number;
  compact_at: number;
  compactions: number;
  compacted: boolean;
}

export interface MemoryDocument {
  markdown: string;
  summary?: string;
  usage?: ContextUsage | null;
}

export interface MemoryAgent {
  agent_key: string;
  name: string;
}

async function requestMemory<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}/api/memory/${path}`, {
    ...options,
    headers: { 'X-Tenant-ID': '1', ...options?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : `记忆服务请求失败（${response.status}）`);
  }
  return response.json();
}

export function fetchMemoryAgents(signal?: AbortSignal) {
  return requestMemory<MemoryAgent[]>('agents', { signal });
}

export function fetchMemory(scope: 'agents' | 'sessions', id: string, signal?: AbortSignal) {
  return requestMemory<MemoryDocument>(`${scope}/${encodeURIComponent(id)}`, { signal });
}

export function saveMemory(scope: 'agents' | 'sessions', id: string, markdown: string) {
  return requestMemory<MemoryDocument>(`${scope}/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ markdown }),
  });
}

export function draftSessionNotes(id: string) {
  return requestMemory<{ markdown: string }>(`sessions/${encodeURIComponent(id)}/draft`, { method: 'POST' });
}
