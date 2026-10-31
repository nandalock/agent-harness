'use client';

// Workspace —— 三栏工作区页（对齐 DeepSeek Harness web UI 布局）
//
//  左 280：会话列表（按 agent 分组 + 搜索 + 新建）
//  中 弹性：对话 + 工具时间线 + composer（上传 / 沙箱模式切换 / 发送）
//  右 380：文件树（懒加载）↕ 预览（PDF/图片/MD/代码/文本）
//
// 页面是共享状态的唯一持有者：选中会话、上传、文件树刷新信号、沙箱模式。
// 每轮对话完成 → 刷新侧栏列表（label/时间/文件数变了）+ 文件树（模型落了文件）。
// 「新建会话」是本地草稿（无 conversation/session id），首问 done 后升级为正式会话。

import { useCallback, useEffect, useRef, useState } from 'react';
import { W, WS, wsThemeCss } from './theme';
import './workspace.css';
import WorkspaceSidebar from './_components/WorkspaceSidebar';
import WorkspaceChat, { type ActiveSession } from './_components/WorkspaceChat';
import FileTreePanel from './_components/FileTreePanel';
import dynamic from 'next/dynamic';
const FilePreviewPanel = dynamic(() => import('./_components/FilePreviewPanel'), {
  ssr: false, loading: () => <div style={{ padding: 16 }}>加载预览…</div>,
});
import WorkspaceEmpty from './_components/WorkspaceEmpty';
import ResizeHandle from './_components/ResizeHandle';
import {
  type WorkspaceSession, type FileEntry, type CreatedSession,
  fetchWorkspaceSessions, uploadFiles, fetchSandboxMode, setSandboxMode,
  renameWorkspaceSession, renameWorkspaceProject, deleteWorkspaceProject,
} from './_components/useWorkspace';

const LS_KEY = 'workspace_active_session';
const LS_LEFT_WIDTH = 'workspace_left_width';
const LS_RIGHT_WIDTH = 'workspace_right_width';

// 大组件的拖拽边界。中心列保底 420，右侧最大 760（DSH 的 rightbar 上限
// 是视口 70%，这里再按页面实际宽度收一次，防止窄屏把对话压没）。
const LEFT_MIN = 220;
const LEFT_MAX = 420;
const RIGHT_MIN = 300;
const RIGHT_MAX = 760;
const CENTER_MIN = 420;

function clampWidth(px: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(px)));
}

function readStoredWidth(key: string, fallback: number, min: number, max: number): number {
  if (typeof window === 'undefined') return fallback;
  const raw = localStorage.getItem(key);
  const value = raw === null ? NaN : Number(raw);
  return Number.isFinite(value) ? clampWidth(value, min, max) : fallback;
}

function loadSavedActive(): ActiveSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export default function WorkspacePage() {
  const [sessions, setSessions] = useState<WorkspaceSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [active, setActive] = useState<ActiveSession | null>(null);
  // 空态发出首问后交接给 WorkspaceChat 的一条待发消息。key = 新 session_id，
  // 供聊天侧认领时去重（StrictMode 恰好一次，见 WorkspaceChat 的首问 effect）。
  const [pendingQuestion, setPendingQuestion] = useState<{ text: string; key: string } | null>(null);
  // 右栏
  const [tab, setTab] = useState<'files' | 'preview'>('files');
  const [selFile, setSelFile] = useState<{ path: string; entry: FileEntry } | null>(null);
  const [treeRefresh, setTreeRefresh] = useState(0);
  const [rightOpen, setRightOpen] = useState(true);
  // 上传 / 沙箱模式
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [sandboxMode, setSandboxModeState] = useState('workspace-write');

  // ── 大组件宽度（会话列表 / 文件面板）──
  // 只拖这两个侧栏；中间对话列是 flex 弹性，不单独拖。宽度持久化到 localStorage。
  const rootRef = useRef<HTMLDivElement>(null);
  const [leftWidth, setLeftWidth] = useState(() =>
    readStoredWidth(LS_LEFT_WIDTH, 280, LEFT_MIN, LEFT_MAX));
  const [rightWidth, setRightWidth] = useState(() =>
    readStoredWidth(LS_RIGHT_WIDTH, 380, RIGHT_MIN, RIGHT_MAX));
  const leftStart = useRef(0);
  const rightStart = useRef(0);
  const widthsRef = useRef({ leftWidth, rightWidth, rightOpen });
  widthsRef.current = { leftWidth, rightWidth, rightOpen };

  /** 页面实际宽度（不含 dashboard 左侧导航），拖拽时用它算中心列保底。 */
  function frameWidth(): number {
    return rootRef.current?.getBoundingClientRect().width
      ?? (typeof window === 'undefined' ? 1600 : window.innerWidth);
  }

  function maxLeftWidth(): number {
    const available = frameWidth() - (rightOpen ? rightWidth : 0) - CENTER_MIN - 16;
    return Math.max(LEFT_MIN, Math.min(LEFT_MAX, available));
  }

  function maxRightWidth(): number {
    const available = frameWidth() - leftWidth - CENTER_MIN - 16;
    return Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, available));
  }

  function startLeftResize() { leftStart.current = leftWidth; }
  function dragLeft(dx: number) {
    setLeftWidth(clampWidth(leftStart.current + dx, LEFT_MIN, maxLeftWidth()));
  }
  function startRightResize() { rightStart.current = rightWidth; }
  function dragRight(dx: number) {
    setRightWidth(clampWidth(rightStart.current - dx, RIGHT_MIN, maxRightWidth()));
  }

  // 窗口变化 / 展开右栏后，已保存的宽度可能挤掉中心列 —— 收紧一次。
  useEffect(() => {
    function onResize() {
      const { leftWidth: l, rightWidth: r, rightOpen: open } = widthsRef.current;
      const frame = frameWidth();
      const maxL = Math.max(LEFT_MIN, Math.min(LEFT_MAX, frame - (open ? r : 0) - CENTER_MIN - 16));
      const maxR = Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, frame - l - CENTER_MIN - 16));
      setLeftWidth(v => clampWidth(v, LEFT_MIN, maxL));
      setRightWidth(v => clampWidth(v, RIGHT_MIN, maxR));
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // 拖拽结束 150ms 后落盘，避免 pointermove 每一帧都写 localStorage。
  useEffect(() => {
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(LS_LEFT_WIDTH, String(leftWidth));
        localStorage.setItem(LS_RIGHT_WIDTH, String(rightWidth));
      } catch { /* ignore */ }
    }, 150);
    return () => clearTimeout(timer);
  }, [leftWidth, rightWidth]);

  // ── 本地变更的序号与墓碑 ──
  //
  // 这个页面没有服务端推送，列表全靠主动拉。风险因此只剩一种：**移除项目**发出
  // 去的 DELETE 与一份**更早发起**的列表请求交错 —— 那份响应是在移除之前生成的，
  // 里面还有这个项目，照它渲染刚删掉的行就「诈尸」了。
  //
  // mutationSeq 记本地变更的次数。一份响应回来时，若它**发起时**的序号已经落后
  // 于当前序号，说明它不认识那次变更，得用 tombstone 把它里面的这个项目压成
  // 未分组；否则它就是权威，墓碑可以退休（服务端已经不再认得这个 id 了）。
  const mutationSeq = useRef(0);
  const tombstones = useRef<Set<number>>(new Set());

  /** 落库列表 + 把活动会话的标题同步成服务端值。
   *
   *  同步这步不是锦上添花：标题是**后端异步换的**（fallback 先出，LLM 版随后替换），
   *  前端不跟着走的话，顶栏会一直显示会话刚打开时那个旧标题。
   *
   *  `startedAt` 是这份响应**发起时**的 mutationSeq，见上面的墓碑说明。 */
  const applySessions = useCallback((list: WorkspaceSession[], startedAt: number) => {
    let items = list.filter(s => s.agent_key);  // 非 agent 通道会话无法续聊，不进列表
    if (startedAt < mutationSeq.current) {
      items = items.map(s => s.project && tombstones.current.has(s.project.id)
        ? { ...s, project: null } : s);
    } else {
      tombstones.current.clear();
    }
    setSessions(items);
    setActive(prev => {
      if (!prev) return prev;
      const hit = items.find(s => s.session_id === prev.session_id);
      return hit && hit.title !== prev.label ? { ...prev, label: hit.title } : prev;
    });
  }, []);

  const loadSessions = useCallback(async () => {
    const startedAt = mutationSeq.current;
    try {
      applySessions(await fetchWorkspaceSessions(), startedAt);
    } catch {
      /* 拉不到就保持现状，下一次刷新会补上 */
    } finally {
      setLoadingSessions(false);
    }
  }, [applySessions]);

  // 挂载：拉会话列表 + 恢复上次选中会话
  useEffect(() => {
    loadSessions();
    const saved = loadSavedActive();
    if (saved?.agent_key) setActive(saved);
  }, [loadSessions]);

  const refreshSessions = loadSessions;

  // 选中会话变化：持久化 + 拉它的沙箱模式；清掉右栏旧选中
  useEffect(() => {
    if (!active) return;
    try { localStorage.setItem(LS_KEY, JSON.stringify(active)); } catch { /* ignore */ }
    setSelFile(null);
    if (active.session_id) {
      fetchSandboxMode(active.session_id)
        .then(m => setSandboxModeState(m.effective))
        .catch(() => {});
    }
  }, [active]);

  function selectSession(s: WorkspaceSession) {
    if (!s.agent_key) return;
    setActive({
      agent_key: s.agent_key,
      conversation_id: s.conversation_id,
      session_id: s.session_id,
      // title 恒非空（后端保证），不用再写 label 兜底；label 现在只用于提示
      label: s.title,
    });
  }

  /** 侧栏改名：写一条 user 源标题事件（后端会**钉住**它），成功后刷新列表。
   *
   *  必须用后端返回的规范化标题刷新，而不是把用户输入直接塞进本地状态 ——
   *  后端会去掉控制符并截到 80 字节，本地先改会让「显示值」和「库里值」短暂分叉。 */
  async function handleRename(sessionId: string, title: string) {
    const saved = await renameWorkspaceSession(sessionId, title);
    setSessions(prev => prev.map(s => s.session_id === sessionId
      ? { ...s, title: saved, title_source: 'user' as const }
      : s));
    // 改的正是当前打开的会话 → 顶栏标题也跟上
    setActive(prev => (prev && prev.session_id === sessionId ? { ...prev, label: saved } : prev));
    refreshSessions();
  }

  /** 项目改名：只改登记里的显示名（目录、会话都不动）。改完本地先同步上，
   *  再拉一次列表对齐（其它标签页 / 别人的改动也一并带回来）。 */
  async function handleRenameProject(projectId: number, title: string) {
    const saved = await renameWorkspaceProject(projectId, title);
    setSessions(prev => prev.map(s => (s.project && s.project.id === projectId
      ? { ...s, project: { ...s.project, label: saved } }
      : s)));
    loadSessions();
  }

  /** **移除项目登记**。后端只删账目那一行；这里把本地投影一起改掉。
   *
   *  两件事的次序是有意的：先发 DELETE（失败就直接抛给弹窗，本地一个字节都不动），
   *  成功后**立即本地摘掉**这个分组 —— 它的会话改成未分组，而不是从列表里消失
   *  （会话还在，只是没有归属了）。不等服务端推送也不等重新拉列表：那样中间会有
   *  一帧「点了确认但行还在」。
   *
   *  然后给这个 id 立墓碑，挡住那些更早发起、此刻才回来的列表响应（见 mutationSeq）。
   */
  async function handleRemoveProject(projectId: number) {
    await deleteWorkspaceProject(projectId);
    mutationSeq.current += 1;
    tombstones.current.add(projectId);
    setSessions(prev => prev.map(s => (s.project && s.project.id === projectId
      ? { ...s, project: null }
      : s)));
    loadSessions();
  }

  /** 侧栏「新建」：清空选中回到空态（聊天框居中显示，在那里选 agent + 文件夹）。 */
  function newSession() {
    setActive(null);
    setSelFile(null);
    // 一并清掉持久化的选中：否则刷新会复活旧会话，回不到空态
    try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
  }

  /** 空态提交首问：会话已在后端建好（cwd 已绑定所选文件夹），切到聊天并交出这条消息。 */
  function handleFirstQuestion(s: CreatedSession, question: string) {
    setActive({
      agent_key: s.agent_key,
      conversation_id: s.conversation_id,
      session_id: s.session_id,
      label: s.label,
    });
    setPendingQuestion({ text: question, key: s.session_id });
    refreshSessions();
    setSelFile(null);
  }

  // 每轮对话完成：刷新侧栏（label/时间/文件数可能变了）+ 文件树（模型落了文件）。
  // 早先这里还有「草稿会话首问带回正式 id → 升级」一支，现在会话一律先在后端建好
  // （空态的 POST /sessions）再进聊天，不存在没有 id 的活动会话，故已移除。
  function handleTurnDone() {
    refreshSessions();
    setTreeRefresh(v => v + 1);
  }

  async function handleUpload(files: File[]) {
    if (!active?.session_id) return;   // 草稿还没 session：上传入口天然禁用
    setUploading(true); setUploadError(null);
    try {
      await uploadFiles(active.session_id, files);
      refreshSessions();               // entries 计数变了
      setTreeRefresh(v => v + 1);      // 文件树出现新文件
    } catch (e: any) {
      setUploadError(e?.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  async function handleModeChange(mode: string) {
    if (!active?.session_id) return;
    setSandboxModeState(mode);   // 乐观更新
    try {
      await setSandboxMode(active.session_id, mode);
    } catch {
      // 失败回滚到服务端值
      fetchSandboxMode(active.session_id).then(m => setSandboxModeState(m.effective)).catch(() => {});
    }
  }

  function handleSelectFile(path: string, entry: FileEntry) {
    setSelFile({ path, entry });
    setTab('preview');
  }

  return (
    <div ref={rootRef} className="ws-root" style={{ display: 'flex', height: '100%', background: W.bg, color: W.text, fontFamily: W.font, overflow: 'hidden' }}>
      {/* 主题变量：由 theme.ts 的 W 生成，workspace.css 消费。走 dangerouslySetInnerHTML
          是因为 <style>{str}</style> 的文本子节点 SSR 端会转义引号、客户端不转义，
          两边文本不一致会 hydrate 崩页（font/mono 里有引号）。 */}
      <style dangerouslySetInnerHTML={{ __html: wsThemeCss }} />

      {/* 左栏（宽度可拖） */}
      <WorkspaceSidebar
        width={leftWidth}
        sessions={sessions}
        selectedId={active?.session_id ?? null}
        onSelect={selectSession}
        onNew={newSession}
        onRefresh={refreshSessions}
        onRename={handleRename}
        onRenameProject={handleRenameProject}
        onRemoveProject={handleRemoveProject}
        loading={loadingSessions}
      />
      <ResizeHandle side="left" label="调整会话列表宽度"
        onStart={startLeftResize} onDrag={dragLeft} onEnd={() => {}} />

      {/* 中栏：左右 16px 是内容轴的最小呼吸位；宽度由两侧拖拽结果决定 */}
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', padding: `0 ${WS.base}px` }}>
        {active ? (
          <WorkspaceChat
            session={active}
            onTurnDone={handleTurnDone}
            uploading={uploading}
            uploadError={uploadError}
            onUpload={handleUpload}
            sandboxMode={sandboxMode}
            onModeChange={handleModeChange}
            rightOpen={rightOpen}
            onToggleRight={() => setRightOpen(v => !v)}
            pendingQuestion={pendingQuestion}
            onPendingQuestionConsumed={() => setPendingQuestion(null)}
          />
        ) : (
          <WorkspaceEmpty onCreated={handleFirstQuestion} />
        )}
      </div>

      {/* 右栏：文件 / 预览 tab + 内容（顶栏按钮收起/展开，宽度可拖） */}
      {rightOpen && (
        <ResizeHandle side="right" label="调整文件面板宽度"
          onStart={startRightResize} onDrag={dragRight} onEnd={() => {}} />
      )}
      <div style={{
        width: rightOpen ? rightWidth : 0,
        flexShrink: 0,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        background: W.panel,
        overflow: 'hidden',
        borderLeft: rightOpen ? `0.5px solid ${W.borderSoft}` : 'none',
      }}>
        <div style={{ display: 'flex', gap: WS.xs, padding: `${WS.sm}px ${WS.md}px`, flexShrink: 0 }}>
          {(['files', 'preview'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className="ws-item ws-round" data-active={tab === t}
              style={{
                height: 28, padding: '0 12px', borderRadius: 16,
                color: tab === t ? W.text : W.tertiary, fontSize: 13, fontFamily: 'inherit',
              }}>
              {t === 'files' ? '文件' : '预览'}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, minHeight: 0, display: tab === 'files' ? 'flex' : 'none', flexDirection: 'column' }}>
          <FileTreePanel
            sessionId={active?.session_id ?? null}
            refreshSignal={treeRefresh}
            selectedPath={selFile?.path ?? null}
            onSelectFile={handleSelectFile}
          />
        </div>
        <div style={{ flex: 1, minHeight: 0, display: tab === 'preview' ? 'flex' : 'none', flexDirection: 'column' }}>
          {rightOpen && tab === 'preview' && <FilePreviewPanel
            sessionId={active?.session_id ?? null}
            path={selFile?.path ?? null}
            entry={selFile?.entry ?? null}
          />}
        </div>
      </div>
    </div>
  );
}
