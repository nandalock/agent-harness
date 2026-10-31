import { type TrajNode, type UsageRow, type TraceSummary } from './trajectory';

export interface ChatMessage {
  id?: number | string;
  role: 'user' | 'agent';
  content: string;
  time: string;
  thinking?: string;
  nodes?: TrajNode[];
  usage?: UsageRow[];
  trace?: TraceSummary;
  msgId?: string;
  pending?: boolean;
}
const localKeys = new WeakMap<ChatMessage, string>();
let nextLocalKey = 0;
export function messageKey(message: ChatMessage) {
  if (message.id != null) return `message:${message.id}`;
  if (message.msgId) return `steer:${message.msgId}`;
  let key = localKeys.get(message);
  if (!key) { key = `local:${++nextLocalKey}`; localKeys.set(message, key); }
  return key;
}

export interface HistoryPage { messages: ChatMessage[]; hasMore: boolean; cursor: number | null }
export async function fetchHistoryPage(conversationId: number, signal: AbortSignal, before?: number | null): Promise<HistoryPage> {
  const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const query = new URLSearchParams({ size: '50' });
  if (before != null) query.set('before_id', String(before));
  const response = await fetch(`${api}/api/chat/conversations/${conversationId}/messages/window?${query}`,
    { headers: { 'X-Tenant-ID': '1' }, signal });
  if (!response.ok) throw new Error('历史加载失败');
  const page = await response.json();
  const messages = page.items.filter((m: any) => m.role === 'agent' || m.role === 'customer').map((m: any): ChatMessage => ({
    id: m.id, role: m.role === 'agent' ? 'agent' : 'user', content: m.content,
    time: m.created_at ? new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '',
    thinking: m.metadata?.thinking || undefined, trace: m.metadata?.trace || undefined,
    nodes: m.trajectory?.nodes, usage: m.trajectory?.usage,
  }));
  return { messages, hasMore: page.has_more, cursor: page.next_before_id };
}
