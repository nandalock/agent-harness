'use client';

import { useEffect, useState, type CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import { T, S } from '@/app/theme';
import { draftSessionNotes, fetchMemory, fetchMemoryAgents, saveMemory, type MemoryAgent, type MemoryDocument } from '@/lib/memory';
import { fetchWorkspaceSessions, type WorkspaceSession } from '../workspace/_components/useWorkspace';

const panel: CSSProperties = { background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: S.base };
const field: CSSProperties = { background: T.bg, color: T.text, border: `1px solid ${T.border}`, borderRadius: 6, padding: 8 };
const limit = 6000;

function MemoryEditor({ scope, id }: { scope: 'agents' | 'sessions'; id: string }) {
  const [document, setDocument] = useState<MemoryDocument>();
  const [markdown, setMarkdown] = useState('');
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchMemory(scope, id, controller.signal).then(result => {
      if (!controller.signal.aborted) { setDocument(result); setMarkdown(result.markdown); }
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [scope, id]);

  async function save() {
    setSaving(true);
    setError('');
    try { setDocument(await saveMemory(scope, id, markdown)); setSaved(true); }
    catch (err) { setError(err instanceof Error ? err.message : '保存失败'); }
    finally { setSaving(false); }
  }

  async function generate() {
    setGenerating(true);
    setError('');
    try { setDraft((await draftSessionNotes(id)).markdown); }
    catch (err) { setError(err instanceof Error ? err.message : '生成草稿失败'); }
    finally { setGenerating(false); }
  }

  function acceptDraft() {
    const combined = [markdown.trimEnd(), draft].filter(Boolean).join('\n\n');
    if (combined.length > limit) { setError('笔记空间不足，请先删减现有内容'); return; }
    setMarkdown(combined);
    setDraft('');
    setSaved(false);
    setError('');
  }

  const session = scope === 'sessions';
  const filename = session ? 'SESSION.md' : 'MEMORY.md';
  return (
    <section style={{ ...panel, marginTop: S.base }}>
      <h3 style={{ marginTop: 0 }}>{filename}</h3>
      <p style={{ color: T.secondary }}>
        {session ? '只在当前会话使用。可记录任务目标、关键决定和接下来要做的事。'
          : '同一智能体的新旧会话都会读取这份 Markdown。适合记录长期偏好和工作约定。'}
      </p>
      {error && <p role="alert" style={{ color: T.danger }}>{error}</p>}
      {!document && !error && <p role="status">正在读取记忆…</p>}
      {document && (
        <>
          <textarea aria-label={filename} rows={10} value={markdown} maxLength={limit} disabled={saving}
            placeholder={session ? '## 目标\n\n## 关键决定\n\n## 下一步' : '## 长期偏好\n\n## 工作约定'}
            style={{ ...field, width: '100%', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'monospace' }}
            onChange={event => { setMarkdown(event.target.value); setSaved(false); }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: S.sm, marginTop: S.sm }}>
            <button type="button" onClick={save} disabled={saving || markdown === document.markdown}>
              {saving ? '保存中…' : '保存笔记'}
            </button>
            <span style={{ color: T.secondary }}>{markdown.length} / {limit}</span>
            {saved && <span role="status">已保存</span>}
            {session && <button type="button" disabled={generating} onClick={generate}>
              {generating ? '正在生成…' : '生成会话笔记草稿'}
            </button>}
          </div>
          {draft && <div style={{ ...panel, marginTop: S.sm }}>
            <ReactMarkdown>{draft}</ReactMarkdown>
            <button type="button" onClick={acceptDraft}>加入笔记</button>{' '}
            <button type="button" onClick={() => setDraft('')}>丢弃草稿</button>
          </div>}
          {session && (
            <div style={{ borderTop: `1px solid ${T.border}`, marginTop: S.base, paddingTop: S.sm }}>
              <h3>最近一次自动压缩摘要</h3>
              {document.usage && (
                <p style={{ color: T.secondary }}>
                  已压缩 {document.usage.compactions} 次 · 上次模型请求约 {document.usage.used_tokens.toLocaleString()} tokens
                </p>
              )}
              {document.summary ? <ReactMarkdown>{document.summary}</ReactMarkdown> : <p>这段会话还没有触发压缩。</p>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function MemoryPage() {
  const router = useRouter();
  const [agents, setAgents] = useState<MemoryAgent[]>([]);
  const [sessions, setSessions] = useState<WorkspaceSession[]>([]);
  const [agentKey, setAgentKey] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sessionError, setSessionError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([fetchMemoryAgents(controller.signal), fetchWorkspaceSessions()]).then(([agentResult, sessionResult]) => {
      if (controller.signal.aborted) return;
      const requested = new URLSearchParams(window.location.search).get('session');
      const listedAgents = agentResult.status === 'fulfilled' ? agentResult.value : [];
      const listedSessions = sessionResult.status === 'fulfilled' ? sessionResult.value : [];
      const target = listedSessions.find(item => item.session_id === requested);
      setAgents(listedAgents);
      setSessions(listedSessions);
      setAgentKey(target?.agent_key || listedAgents[0]?.agent_key || '');
      setSessionId(target?.session_id || '');
      if (agentResult.status === 'rejected') setError('无法读取智能体列表');
      if (sessionResult.status === 'rejected') setSessionError('无法读取会话列表');
      setLoading(false);
    });
    return () => controller.abort();
  }, []);

  const visibleSessions = sessions.filter(item => item.agent_key === agentKey);
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>记忆管理</h2>
      <p style={{ color: T.secondary }}>按智能体查看长期记忆，或选择会话查看任务笔记和自动压缩摘要。</p>
      <div style={{ ...panel, display: 'flex', flexWrap: 'wrap', gap: S.base }}>
        <label>智能体 <select value={agentKey} style={field} disabled={loading || !agents.length}
          onChange={event => { setAgentKey(event.target.value); setSessionId(''); }}>
          {!agents.length && <option value="">{loading ? '加载中…' : '暂无智能体'}</option>}
          {agents.map(agent => <option value={agent.agent_key} key={agent.agent_key}>{agent.name}</option>)}
        </select></label>
        <label>记忆范围 <select value={sessionId} style={{ ...field, maxWidth: 350 }} disabled={!agentKey}
          onChange={event => setSessionId(event.target.value)}>
          <option value="">智能体长期记忆</option>
          {visibleSessions.map(item => <option value={item.session_id} key={item.session_id}>{item.title}</option>)}
        </select></label>
      </div>
      {error && <p role="alert">{error}</p>}
      {sessionError && <p role="alert">{sessionError}</p>}
      {agentKey && <MemoryEditor key={sessionId ? `session:${sessionId}` : `agent:${agentKey}`}
        scope={sessionId ? 'sessions' : 'agents'} id={sessionId || agentKey} />}
      <div style={{ display: 'flex', gap: S.base, marginTop: S.base }}>
        <button type="button" onClick={() => router.push('/dashboard/memory/users')}>用户画像</button>
        <button type="button" onClick={() => router.push('/dashboard/memory/debug')}>压缩调试</button>
      </div>
    </div>
  );
}
