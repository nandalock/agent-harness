'use client';

import { useCallback, useEffect, useState } from 'react';

export interface SkillEntry {
  key: string;
  name: string;
  description: string;
  kind: 'skill' | 'command';
  argument_hint: string;
  unavailable_reason: string | null;
}

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function useSkillCatalog(agentKey?: string, sessionId?: string | null, tenantId = 1) {
  const [entries, setEntries] = useState<SkillEntry[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setEntries([]); setError('');
    if (!agentKey) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    fetch(`${API}/api/agents/${encodeURIComponent(agentKey)}/skills${query}`, {
      signal: controller.signal, headers: { 'X-Tenant-ID': String(tenantId) },
    }).then(async response => {
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '技能目录加载失败');
      if (!Array.isArray(body.skills)) throw new Error('技能目录格式无效');
      if (!controller.signal.aborted) setEntries(body.skills);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err.message || '技能目录加载失败');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [agentKey, sessionId, tenantId, revision]);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  return { entries, loading, error, refresh };
}

export function SlashSkillMenu({ entries, selected, loading, error, onPick, onRetry,
  background, color, muted }: {
  entries: SkillEntry[]; selected: number; loading: boolean; error: string;
  onPick: (entry: SkillEntry) => void; onRetry: () => void;
  background: string; color: string; muted: string;
}) {
  return <div role="listbox" aria-label="技能与命令" style={{ margin: '0 10px 4px', padding: 4,
    background, borderRadius: 10, maxHeight: 240, overflowY: 'auto', color }}>
    {loading ? <div style={{ padding: 8, fontSize: 13 }}>正在加载技能…</div>
      : error ? <button type="button" onClick={onRetry} style={{ padding: 8, color, background: 'transparent', border: 0 }}>技能加载失败 · 重试</button>
        : !entries.length ? <div style={{ padding: 8, fontSize: 13, color: muted }}>没有匹配的技能</div>
          : entries.map((entry, index) => <button type="button" role="option" aria-selected={selected === index}
            aria-disabled={!!entry.unavailable_reason} key={entry.key}
            onMouseDown={event => event.preventDefault()} onClick={() => !entry.unavailable_reason && onPick(entry)}
            title={entry.unavailable_reason || entry.description}
            style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px', border: 0,
              color, borderRadius: 8, background: selected === index ? 'rgba(128,128,128,.16)' : 'transparent',
              opacity: entry.unavailable_reason ? 0.6 : 1, cursor: entry.unavailable_reason ? 'default' : 'pointer' }}>
            <span style={{ fontSize: 13 }}>/{entry.name} <span style={{ color: muted }}>{entry.argument_hint}</span></span>
            <span style={{ display: 'block', fontSize: 12, color: muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {entry.unavailable_reason || entry.description}
            </span>
          </button>)}
  </div>;
}
