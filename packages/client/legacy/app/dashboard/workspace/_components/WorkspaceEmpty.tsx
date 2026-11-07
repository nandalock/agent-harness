'use client';

// WorkspaceEmpty —— 中栏空态，版面按 DSH 的 conversation hero：
//
//   ╭ minidsh ╮                  （居中，26/32，权重 500，左侧品牌鱼）
//       新建项目 chip            （卡片上方一行，左对齐）
//   ┌────────────────────────┐
//   │ 描述你想要构建的内容…     │  （输入卡，r22，max-width 720）
//   │              [智能体] [↑] │
//   └────────────────────────┘
//       提示 / 错误                （12/18 caption）
//
// 项目选择：点「新建项目」优先打开**本机系统文件夹对话框**（Host 返回真实
// 绝对路径）；Docker/远程/对话框失败时退回服务端目录浏览器（DSH browse）。
// 项目 cwd 直接是所选目录（POST /sessions 的 folder_path；挂载模式用 folder
// 值）。内联输入作为最后兜底：绝对路径直接作为 cwd，普通名称才落到工作区根。
// 必须选项目才能建会话，没有自动分配目录的捷径。

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowUp, Bot, ChevronDown, Fish, FolderOpen, FolderPlus, Loader2 } from 'lucide-react';
import { W } from '../theme';
import DirectoryBrowser, { type BrowsePick } from './DirectoryBrowser';
import { remote } from '@/lib/remote';
import {
  createWorkspaceSession, ensureWorkspaceFolder, pickHostWorkspaceFolder,
  type CreatedSession,
} from './useWorkspace';

type AgentsStatus = 'loading' | 'ready' | 'error';

interface Props {
  /** 会话建好之后：交回创建结果与用户输入的首条消息，由页面切到聊天并发出。 */
  onCreated: (s: CreatedSession, question: string) => void;
}

export default function WorkspaceEmpty({ onCreated }: Props) {
  const [agents, setAgents] = useState<{ key: string; name: string; agentType: string }[]>([]);
  const [agentsStatus, setAgentsStatus] = useState<AgentsStatus>('loading');
  const [agentKey, setAgentKey] = useState('');
  // 选中的智能体是否具备可用的模型配置（model / base_url / api_key）。
  // unknown/error 不拦发送；只有明确缺失才拦住并显示配置入口。
  const [agentModel, setAgentModel] = useState<'unknown' | 'ready' | 'missing' | 'error'>('unknown');

  // 项目文件夹：浏览器目录选择器只给名字，后端按名字建 / 选目录
  const [pickingFolder, setPickingFolder] = useState(false);
  const [hostPath, setHostPath] = useState('');
  // 本机选择器返回的真实绝对路径；优先于名称映射
  const [folderPath, setFolderPath] = useState<string | null>(null);
  // 交给 POST /sessions 的 folder 值，由后端翻译（目录名 + 浏览根名），前端不拼
  const [folderValue, setFolderValue] = useState<string | null>(null);
  // 模型在这个位置写入是否需要授权（读根内 = 需要）
  const [writable, setWritable] = useState(true);

  const [question, setQuestion] = useState('');
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState('');
  // 原生目录对话框不可用时的手动输入行（不依赖 window.prompt）
  const [manualOpen, setManualOpen] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualErr, setManualErr] = useState('');
  // 远程 / Docker 的服务端目录浏览对话框
  const [browserOpen, setBrowserOpen] = useState(false);

  const agentsReady = agentsStatus === 'ready' && agents.length > 0;
  const folderLabel = pickingFolder ? '创建项目…' : (folderPath || hostPath || '新建项目');
  // 必须先有项目文件夹才能建会话；不再有「自动分配目录」这条默认路径
  const folderBlocked = !folderValue && !folderPath;
  const needsApproval = !folderPath && !writable && !!folderValue;
  const projectReady = agentsReady && agentModel !== 'missing' && !folderBlocked && !needsApproval;

  const loadAgents = useCallback(async () => {
    setAgentsStatus('loading');
    try {
      const result = await remote.agent.list();
      const items = (result.items || [])
        .map(a => ({ key: a.key, name: a.name || a.key, agentType: a.agent_type || 'agent' }));
      setAgents(items);
      // 内置的 default 优先选中；用户已选的 agent 仍然保留
      const preferred = items.find(a => a.key === 'default') ?? items[0];
      setAgentKey(k => (k && items.some(a => a.key === k)) ? k : (preferred?.key || ''));
      setAgentsStatus('ready');
    } catch {
      setAgentsStatus('error');
    }
  }, []);

  useEffect(() => { void loadAgents(); }, [loadAgents]);

  // 选中 agent 后检查模型配置：没有 model/base_url/api_key 时发送按钮会拦住，
  // 并给出去 Agent 配置页的链接——否则用户只会收到一句无信息的兜底回复。
  // router 的模型在 l3_llm / 目标 agent 里，不在这个检查范围。
  useEffect(() => {
    if (!agentKey) { setAgentModel('unknown'); return; }
    const agent = agents.find(a => a.key === agentKey);
    if (agent?.agentType === 'router') { setAgentModel('ready'); return; }
    let cancelled = false;
    setAgentModel('unknown');
    void (async () => {
      try {
        const d = await remote.agent.getConfig({ agent_key: agentKey });
        if (cancelled) return;
        const cfg = d.config || {};
        const filled = (v: unknown) => typeof v === 'string' && v.trim() !== '';
        // 后端把 DB + 环境变量解析后的有效视图放在 model_info；老后端没有这个
        // 字段时退回看 DB 三个字段。
        const effective = d.model_info;
        const ready = effective && typeof effective.configured === 'boolean'
          ? effective.configured === true
          : filled(cfg.model) && filled(cfg.base_url) && filled(cfg.api_key);
        setAgentModel(ready ? 'ready' : 'missing');
      } catch {
        if (!cancelled) setAgentModel('error');
      }
    })();
    return () => { cancelled = true; };
  }, [agentKey, agents]);

  /** 按名字创建 / 打开项目（目录选择器与手动输入共用同一条后端链路）。 */
  async function createProjectByName(raw: string | null | undefined): Promise<boolean> {
    const name = (raw || '').trim();
    if (!name) return false;
    setPickingFolder(true); setErr('');
    try {
      const choice = await ensureWorkspaceFolder(name);
      setFolderPath(null);
      setHostPath(choice.hostPath);
      setFolderValue(choice.folder);
      setWritable(choice.writable);
      setManualOpen(false);
      setManualName('');
      setManualErr('');
      return true;
    } catch (e: any) {
      setErr(e?.message || String(e));
      return false;
    } finally {
      setPickingFolder(false);
    }
  }

  /** 本机绝对路径项目：cwd 直接用它，不再按名字复制到 ~/.minidsh/workspaces。 */
  function applyProjectPath(path: string) {
    setFolderPath(path);
    setHostPath(path);
    setFolderValue(null);
    setWritable(true);
    setManualOpen(false);
    setManualName('');
    setManualErr('');
    setErr('');
  }

  function handleBrowsePick(pick: BrowsePick) {
    setBrowserOpen(false);
    if (pick.mode === 'local') { applyProjectPath(pick.path); return; }
    if (!pick.folder) { setErr('该目录不能作为项目（不在可用的工作区根内）'); return; }
    setFolderPath(null);
    setHostPath(pick.path);
    setFolderValue(pick.folder);
    setWritable(pick.writable);
    setManualOpen(false);
    setManualName('');
    setManualErr('');
    setErr('');
  }

  function openManualInput() {
    if (pickingFolder) return;
    setBrowserOpen(false);
    setManualOpen(true);
    setManualErr('');
    setErr('');
  }

  async function submitManual() {
    const name = manualName.trim();
    if (!name) { setManualErr('请输入项目名称或路径'); return; }
    // 绝对路径直接作为项目的 cwd；普通名称仍走工作区根的同名目录
    if (/^([a-zA-Z]:[\\/]|\\\\|\/)/.test(name)) {
      applyProjectPath(name);
      return;
    }
    if (name.includes('/') || name.includes('\\') || name === '.' || name === '..') {
      setManualErr('名称不能含 / 或 \\，也不能是 . 或 ..');
      return;
    }
    setManualErr('');
    await createProjectByName(name);
  }

  /** 选项目文件夹：本机系统对话框优先；远程/容器/失败时退回服务端目录浏览。 */
  async function chooseFolder() {
    if (pickingFolder) return;
    setPickingFolder(true); setErr('');
    try {
      const host = await pickHostWorkspaceFolder();
      if (host.status === 'picked') { applyProjectPath(host.path); return; }
      if (host.status === 'cancelled') return;
      setBrowserOpen(true);
    } catch {
      // 系统对话框启动失败也退回 browse，而不是只留一个错误
      setBrowserOpen(true);
    } finally {
      setPickingFolder(false);
    }
  }

  async function submit() {
    const q = question.trim();
    if (!q || !agentKey || !agentsReady || creating || pickingFolder) return;
    if (agentModel === 'missing') return;
    // 还没有项目：把用户带到手动输入行，而不是按 Enter 没反应
    if (!folderValue && !folderPath) { openManualInput(); return; }
    setCreating(true); setErr('');
    try {
      const s = await createWorkspaceSession(agentKey, folderValue, folderPath);
      onCreated(s, q);            // 成功后本组件随 active 变更卸载
    } catch (e: any) {
      setErr(e?.message || String(e));   // 失败留在空态：消息内容保留，可改选项重试
      setCreating(false);
    }
  }

  // 没有项目时按钮仍可点：点击会把用户带到项目输入行，而不是一个无反应的禁用键
  const canSend = !!question.trim() && agentsReady && agentModel !== 'missing'
    && !creating && !pickingFolder;

  return (
    <div className="ws-empty">
      <div className="ws-empty-stack">
        <div className="ws-hero">
          <span className="ws-hero-mark"><Fish size={30} strokeWidth={1.7} /></span>
          <span>minidsh</span>
        </div>

        {/* 项目 chip：只有「新建项目」这一条路，不再有自动分配目录 */}
        <div className="ws-workspace-row">
          <button onClick={chooseFolder} disabled={pickingFolder}
            title="新建项目（打开系统文件夹选择器，返回真实路径）"
            className="ws-btn ws-round ws-workspace-chip">
            {pickingFolder
              ? <Loader2 size={16} className="ws-spin" />
              : folderValue ? <FolderOpen size={16} /> : <FolderPlus size={16} />}
            <span className="ws-workspace-label">{folderLabel}</span>
            {needsApproval && <span className="ws-readonly">只读</span>}
            <ChevronDown size={12} className="ws-workspace-chevron" />
          </button>
          {!folderValue && !pickingFolder && !manualOpen && (
            <button onClick={openManualInput} title="直接输入项目名称"
              className="ws-btn ws-round ws-manual-create">
              输入路径/名称
            </button>
          )}
        </div>

        {manualOpen && (
          <div className="ws-manual-row">
            <input
              autoFocus
              value={manualName}
              onChange={e => { setManualName(e.target.value); setManualErr(''); }}
              onKeyDown={e => {
                if (e.nativeEvent.isComposing) return;
                if (e.key === 'Enter') { e.preventDefault(); void submitManual(); }
                if (e.key === 'Escape') { setManualOpen(false); setManualName(''); setManualErr(''); }
              }}
              placeholder="项目名称，或绝对路径（如 D:/projects/foo）"
              aria-label="项目名称"
              className="ws-manual-input"
              disabled={pickingFolder}
            />
            <button onClick={() => void submitManual()} disabled={!manualName.trim() || pickingFolder}
              className="ws-btn ws-btn-primary ws-round ws-manual-action">
              {pickingFolder ? '创建中…' : '创建'}
            </button>
            <button onClick={() => { setManualOpen(false); setManualName(''); setManualErr(''); }}
              className="ws-btn ws-round ws-manual-action" style={{ color: 'var(--ws-dimmed)' }}>
              取消
            </button>
          </div>
        )}
        {manualErr && <div className="ws-empty-error">{manualErr}</div>}

        {/* 输入卡：DSH InputBar 的 hero 形态 */}
        <div className="ws-empty-card">
          <textarea
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
            }}
            placeholder="描述你想要构建的内容…"
            disabled={creating}
            rows={Math.min(14, Math.max(1, question.split('\n').length))}
            className="ws-empty-input ws-round"
          />
          <div className="ws-empty-toolbar">
            <div style={{ flex: 1 }} />
            <label className="ws-agent-pill" title="选择智能体">
              <Bot size={14} color={W.tertiary} />
              <select
                className="ws-agent-select"
                value={agentKey}
                onChange={e => setAgentKey(e.target.value)}
                disabled={!agentsReady}
                aria-label="选择智能体"
              >
                {agentsStatus === 'loading' && <option value="">加载中…</option>}
                {agentsStatus === 'error' && <option value="">加载失败</option>}
                {agentsStatus === 'ready' && agents.length === 0 && <option value="">暂无智能体</option>}
                {agents.map(a => <option key={a.key} value={a.key}>{a.name}</option>)}
              </select>
              <ChevronDown size={12} color={W.dimmed} />
            </label>
            <button onClick={submit} disabled={!canSend}
              title={folderBlocked ? '先新建项目（点击打开项目输入）' : '创建会话并发送（Enter）'}
              className="ws-send ws-round"
              style={{
                width: 34, height: 34, borderRadius: 999, flexShrink: 0,
                color: canSend ? '#fff' : W.dimmed,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
              {creating ? <Loader2 size={16} className="ws-spin" /> : <ArrowUp size={17} />}
            </button>
          </div>
        </div>

        {(agentsStatus === 'error' || (agentsStatus === 'ready' && agents.length === 0)
          || agentModel === 'missing' || folderBlocked || needsApproval || projectReady) && (
          <div className="ws-empty-hint">
            {agentsStatus === 'error' ? (
              <>
                <span>智能体加载失败</span>
                <button onClick={loadAgents} className="ws-link-btn">重试</button>
              </>
            ) : agents.length === 0 ? (
              <>
                <span>还没有智能体，</span>
                <Link href="/dashboard/agents" className="ws-link">先去创建一个</Link>
                <span>再开始</span>
              </>
            ) : agentModel === 'missing' ? (
              <>
                <span>该智能体还没有配置模型，</span>
                <Link href={`/agents/${agentKey}`} className="ws-link">去配置</Link>
                <span>后再发送</span>
              </>
            ) : folderBlocked ? (
              <>
                <span>先新建项目，或点</span>
                <button onClick={openManualInput} className="ws-link-btn">输入路径/名称</button>
              </>
            ) : needsApproval ? '该位置默认只读，模型写入时会向你申请批准'
              : '项目已就绪，发送第一条消息后会出现在左侧'}
          </div>
        )}

        {err && <div className="ws-empty-error">{err}</div>}
      </div>

      <DirectoryBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
        onPick={handleBrowsePick}
        onManual={openManualInput}
      />
    </div>
  );
}
