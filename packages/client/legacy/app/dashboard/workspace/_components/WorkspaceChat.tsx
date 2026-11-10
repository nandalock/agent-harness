'use client';

// WorkspaceChat —— 中栏对话（日志流布局）
//
// 版面取自参考项目 ui-conversation / ui-chat：
//   内容轴 clamp(680px,64%,920px) 居中，输入卡比消息列宽 32px（→ 同一根轴上的
//   两级内缩，见下方 ROOT 与 transcript 的 padding 差）
//   用户消息 = 右对齐 r22 气泡，时间 hover 才现身
//   助手回合 = 无气泡全宽分组，交给 AgentTurn 投影成日志流
//
// 实时 SSE 保持在父组件；历史按消息游标分页，VirtualTranscript 只挂载视口附近
// 的回合。工具轨迹由后端按事件指针关联；虚拟行卸载不影响正在执行的任务。
//
// 每轮 done → onTurnDone()：页面据此刷新侧栏会话列表与右栏文件树。

import { useEffect, useRef, useState } from 'react';
import RecoveryBanner from '@/app/agents/_components/RecoveryBanner';
import VirtualTranscript, { type TranscriptHandle } from '@/components/VirtualTranscript';
import { useOlderMessages } from '@/components/useOlderMessages';
import { fetchHistoryPage, messageKey, type ChatMessage } from '@/lib/chatHistory';
import { fetchMemory, type ContextUsage } from '@/lib/memory';
import { Fish, PanelRight, ShieldAlert } from 'lucide-react';
import { W, R, WS, CHAT_COLUMN } from '../theme';
import { useTrajectoryBatch } from '@/app/agents/_components/useTrajectoryBatch';
import {
  type TrajNode, type UsageRow, type TraceSummary,
  answerTextOf,
} from '@/lib/trajectory';
import AgentTurn from './AgentTurn';
import Composer from './Composer';
import { attachLiveRun, cancelLiveRun } from './useWorkspace';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const TENANT_ID = 1;
const H = { 'X-Tenant-ID': String(TENANT_ID) };

const TURN_GAP = 20;   // 回合之间的呼吸；回合内部各区块的间距由 AgentTurn 自管

type ChatMsg = ChatMessage;

/** 一轮 SSE 的累积结果；新发送和 attach 共用。 */
interface RunOutcome {
  completed: boolean;
  finalAnswer: string;
  trace?: TraceSummary;
  legacyThink: string;
  legacyAns: string;
  aborted: boolean;
}

interface PendingApproval {
  approvalId: string;
  tool: string;
  reason: string;
  metadata: Record<string, any>;
}

/** 中栏的活动会话：侧栏选中项，或「新建会话」草稿（conversation_id/session_id 为 null，首问后补上）。 */
export interface ActiveSession {
  agent_key: string;
  conversation_id: number | null;
  session_id: string | null;
  label: string;
}

interface Props {
  session: ActiveSession | null;
  onTurnDone: () => void;   // 每轮完成：刷新侧栏 + 文件树（模型这一轮可能落了文件）
  uploading: boolean;
  uploadError: string | null;
  onUpload: (files: File[]) => void;
  sandboxMode: string;
  onModeChange: (mode: string) => void;
  rightOpen: boolean;
  onToggleRight: () => void;
  /** 空态发出首问后由页面交接下来的一条待发消息（见下方「首问交接」）。 */
  pendingQuestion?: { text: string; key: string } | null;
  onPendingQuestionConsumed?: () => void;
}

/** 头部小圆点：运行中/空闲 */
function HeaderDot({ active }: { active: boolean }) {
  return (
    <span className="ws-round" style={{
      width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
      background: active ? W.ongoing : W.tertiary,
      boxShadow: active ? `0 0 0 3px ${W.ongoing}29` : 'none',
    }} />
  );
}

export default function WorkspaceChat({ session, onTurnDone, uploading, uploadError, onUpload, sandboxMode, onModeChange, rightOpen, onToggleRight, pendingQuestion, onPendingQuestionConsumed }: Props) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sending, setSending] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState('');
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const { nodes: trajNodes, nodesRef, enqueue, forceFlush, reset } = useTrajectoryBatch();
  const [liveUsage, setLiveUsage] = useState<UsageRow[]>([]);
  const [contextUsage, setContextUsage] = useState<{ sessionId: string; usage?: ContextUsage }>();
  const usageRef = useRef<UsageRow[]>([]);
  // 当前在飞的 SSE 观看连接。abort 它只是 detach（后端继续跑）；停止必须走 /chat/cancel。
  const stopRef = useRef<AbortController | null>(null);
  // 回到会话时重新接上后台轮次的观看连接
  const attachRef = useRef<AbortController | null>(null);
  // steer 撞上「本轮刚收口」（409）：把这条留到本轮收尾后再当新消息发（见 commitOutcome）
  const deferSendRef = useRef<string | null>(null);
  const transcriptRef = useRef<TranscriptHandle>(null);
  const liveId = useRef('');
  const older = useOlderMessages(session?.conversation_id ?? null, setMessages);
  // 首问交接：consumedKey 记「哪条已认领」，historySettled 是「历史加载完了」的闸
  const consumedKeyRef = useRef<string | null>(null);
  const [historySettled, setHistorySettled] = useState(false);

  function updateContextUsage(sessionId: string, usage?: ContextUsage) {
    setContextUsage(previous => {
      if (previous?.sessionId === sessionId && (previous.usage?.event_seq ?? 0) > (usage?.event_seq ?? 0)) {
        return previous;
      }
      return { sessionId, usage };
    });
  }

  useEffect(() => {
    const sessionId = session?.session_id;
    if (!sessionId) return;
    const controller = new AbortController();
    fetchMemory('sessions', sessionId, controller.signal).then(document => {
      if (!controller.signal.aborted) updateContextUsage(sessionId, document.usage ?? undefined);
    }).catch(() => { /* Memory can be disabled for this profile. */ });
    return () => controller.abort();
  }, [session?.session_id]);

  // ── 会话切换：最近 50 条消息及对应回合的轨迹 ──
  useEffect(() => {
    reset();
    setApprovals([]);
    setMessages([]);
    setSending(false);          // 旧会话的观看连接即将被 cleanup 断开，先回到空闲
    setLiveUsage([]);
    usageRef.current = [];
    setHistorySettled(false);   // 首问要等本轮历史加载落定（见下方首问 effect）
    if (!session?.conversation_id) { setLoadingHistory(false); setHistorySettled(true); return; }
    const { conversation_id } = session;
    const controller = new AbortController();
    let cancelled = false;
    (async () => {
      setLoadingHistory(true);
      try {
        const page = await fetchHistoryPage(conversation_id, controller.signal);
        if (!cancelled) { setMessages(page.messages); older.acceptPage(page); }
      } catch { if (!cancelled) older.setError('历史加载失败'); }
      finally {
        if (!cancelled) { setLoadingHistory(false); setHistorySettled(true); }
      }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [session?.conversation_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // 切会话 / 卸载：只断开观看连接。后台轮次归 LiveRunRegistry 所有，不随页面消失。
  useEffect(() => {
    return () => {
      stopRef.current?.abort();
      attachRef.current?.abort();
    };
  }, [session?.session_id]);

  // 历史落定后，若该会话有后台轮次，接上快照和后续增量（切页面回来 / 刷新回来）。
  useEffect(() => {
    if (!historySettled || !session?.session_id || !session.agent_key) return;
    // 空态首问马上会自己开一条 /chat/stream；此时去 attach 会和它抢同一条流。
    if (pendingQuestion) return;
    // 进入这个会话时先按空闲渲染；确认有后台轮次后再点亮「运行中」。
    setSending(false);
    setRecoveryNotice('');
    const controller = new AbortController();
    attachRef.current = controller;
    stopRef.current = controller;
    (async () => {
      try {
        const response = await attachLiveRun(
          session.agent_key, session.session_id!, session.conversation_id, controller.signal,
        );
        // 用户在这条 GET 在飞的时候按了发送：以那条新流为准，不再重复接。
        if (!response || controller.signal.aborted || stopRef.current !== controller) {
          controller.abort();
          return;
        }
        liveId.current = crypto.randomUUID();
        reset();
        setApprovals([]);
        usageRef.current = [];
        setLiveUsage([]);
        setSending(true);
        setRecoveryNotice('');
        const outcome = await consumeStream(response, controller);
        if (!controller.signal.aborted) commitOutcome(outcome);
      } catch {
        if (!controller.signal.aborted && attachRef.current === controller) setSending(false);
      } finally {
        const ownsCurrentStream = stopRef.current === controller;
        if (ownsCurrentStream) stopRef.current = null;
        if (attachRef.current === controller) {
          attachRef.current = null;
          // 只清理自己；若已有新的发送接管，别把它的状态压掉。
          if (ownsCurrentStream) setSending(false);
        }
      }
    })();
    return () => { controller.abort(); };
  }, [historySettled, session?.agent_key, session?.session_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // ── 首问交接：空态发来的第一条消息，等历史落定后恰好发一次 ──
  //
  // 两道闸缺一不可：
  //  - historySettled —— 历史加载的 setMessages(空数组) 会冲掉 handleSend 刚追加的
  //    用户气泡。新会话的历史一定是空的，所以必须等它落定再发。顺带解决 StrictMode：
  //    挂载时的 effect 双执行都发生在 historySettled 尚为 false 时，两次都提前返回；
  //    真正的发送发生在 setHistorySettled(true) 触发的**更新** effect 上（dev 不双执行）。
  //  - consumedKeyRef —— 认领是同步语句，先于 handleSend 的任何 await。即便某天
  //    effect 被执行两次，第二次看到 key 已认领直接跳过。key 用新 session_id，天然唯一。
  useEffect(() => {
    if (!pendingQuestion || !historySettled) return;
    if (consumedKeyRef.current === pendingQuestion.key) return;
    consumedKeyRef.current = pendingQuestion.key;
    onPendingQuestionConsumed?.();   // 父级同步清空 → 本 effect 再跑时幂等
    handleSend(pendingQuestion.text);
  }, [pendingQuestion, historySettled]);   // eslint-disable-line react-hooks/exhaustive-deps

  const liveAnsText = answerTextOf(trajNodes);

  /** 停止生成：显式取消后台轮次。abort 流只是 detach，任务会继续跑。 */
  async function handleStop() {
    if (!session?.session_id || !sending) return;
    try {
      const cancelled = await cancelLiveRun(session.agent_key, session.session_id);
      if (!cancelled) {
        // 刚好已经结束（没有活动轮次）：断开观看连接即可
        stopRef.current?.abort();
        attachRef.current?.abort();
        setSending(false);
      }
    } catch {
      // 取消请求失败：至少先 detach，避免 UI 卡在「运行中」；后台任务最终会落库
      stopRef.current?.abort();
      attachRef.current?.abort();
      setSending(false);
    }
  }

  /** 消费一条 SSE 流（新发送 / attach 共用）；事件格式与后端 /chat/stream 一致。 */
  async function consumeStream(response: Response, controller: AbortController): Promise<RunOutcome> {
    let finalAnswer = '';
    let completed = false;
    let doneTrace: TraceSummary | undefined;
    let legacyThink = '';
    let legacyAns = '';
    let contextSessionId = session?.session_id;
    const updateContext = (usage: ContextUsage | undefined) => {
      if (usage && contextSessionId && !controller.signal.aborted) {
        updateContextUsage(contextSessionId, usage);
      }
    };
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        let ev: any;
        try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
        switch (ev.type) {
          case 'live/snapshot': {
            contextSessionId = ev.session_id || contextSessionId;
            updateContext(ev.context_usage);
            // 回到正在跑的会话：先清空实时投影，再用后端快照重建，之后继续吃增量。
            reset();
            for (const node of Array.isArray(ev.nodes) ? ev.nodes : []) {
              enqueue({ type: 'traj/open', node } as any);
            }
            usageRef.current = Array.isArray(ev.usage) ? [...ev.usage] : [];
            setLiveUsage(usageRef.current);
            const pending = Array.isArray(ev.pending_approvals) ? ev.pending_approvals : [];
            setApprovals(pending.map((p: any) => {
              const d = p?.data || {};
              return {
                approvalId: d.approval_id, tool: p?.tool || '',
                reason: d.reason || '', metadata: d.metadata || {},
              };
            }).filter((a: PendingApproval) => !!a.approvalId));
            break;
          }
          case 'session/ready':
            contextSessionId = ev.session_id || contextSessionId;
            break;
          case 'context/usage':
            updateContext(ev.usage);
            break;
          case 'traj/open':
          case 'traj/delta':
          case 'traj/update':
          case 'traj/close':
            enqueue(ev as any);
            break;
          case 'usage': {
            const row = { ...ev } as UsageRow;
            usageRef.current = [...usageRef.current, row];
            setLiveUsage(usageRef.current);
            break;
          }
          case 'approval.request': {
            const d = ev.data || {};
            if (!d.approval_id) break;
            setApprovals(prev => [
              ...prev.filter(p => p.approvalId !== d.approval_id),
              { approvalId: d.approval_id, tool: ev.tool || '', reason: d.reason || '', metadata: d.metadata || {} },
            ]);
            break;
          }
          case 'sandbox.escalation':
            if (ev.data?.approval_id) {
              const doneId = ev.data.approval_id;
              setApprovals(prev => prev.filter(p => p.approvalId !== doneId));
            }
            break;
          case 'user': {
            // 运行中输入被**认领**了（后端 user/message → UI 帧）：把自己那条「待投递」
            // 翻成已投递。没有对应气泡的（inject 之类不是本页发的）补一条，别静默丢。
            const mid = typeof ev.msg_id === 'string' ? ev.msg_id : undefined;
            const content = typeof ev.content === 'string' ? ev.content : '';
            setMessages(prev => {
              const hit = mid ? prev.findIndex(m => m.role === 'user' && m.msgId === mid) : -1;
              if (hit < 0) {
                return [...prev, {
                  role: 'user', content,
                  time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
                }];
              }
              const next = [...prev];
              next[hit] = { ...next[hit], pending: false };
              return next;
            });
            break;
          }
          case 'thinking':
            legacyThink += ev.delta;
            break;
          case 'text':
          case 'answer':
            legacyAns += ev.delta;
            break;
          case 'error':
            finalAnswer = ev.message || '任务执行失败，请稍后重试';
            break;
          case 'recovery':
            setRecoveryNotice(ev.message || '已恢复上次进度。');
            break;
          case 'done':
            completed = true;
            if (ev.answer) finalAnswer = ev.answer;
            doneTrace = ev.trace;
            break;
        }
      }
    }
    return {
      completed, finalAnswer, trace: doneTrace,
      legacyThink, legacyAns, aborted: controller.signal.aborted,
    };
  }

  /** 收口：落本地 agent 气泡并刷新侧栏。aborted = 只是离页 detach，不落本地消息。 */
  function commitOutcome(outcome: RunOutcome) {
    forceFlush();
    setSending(false);
    if (outcome.aborted) return;
    const nodes = nodesRef.current;
    const ansText = answerTextOf(nodes);
    const content = outcome.finalAnswer || ansText || outcome.legacyAns
      || (outcome.completed ? '抱歉，暂时无法处理。' : '连接中断，已保存的进度可以继续。');
    setMessages(prev => [...prev, {
      id: liveId.current, role: 'agent', content,
      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      nodes: nodes.length ? nodes : undefined,
      usage: usageRef.current.length ? usageRef.current : undefined,
      thinking: outcome.legacyThink || undefined,
      trace: outcome.trace,
    }]);
    onTurnDone();   // 本轮可能落了文件：侧栏 + 文件树一起刷新

    // steer 撞上「本轮刚收口」时攒下的那条：现在这一轮真的结束了，当新消息发出去
    const deferred = deferSendRef.current;
    if (deferred) {
      deferSendRef.current = null;
      void handleSend(deferred);
    }
  }

  async function handleSend(q: string, resumeFrom?: number) {
    if (!session) return;
    // 运行中：发送 = 并入当前轮（不另起一条 SSE 流，见 handleSteer）
    if (sending) return handleSteer(q);
    const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    liveId.current = crypto.randomUUID();
    setMessages(prev => [...prev, { role: 'user', content: q, time: now }]);
    transcriptRef.current?.scrollToEnd();
    setSending(true);
    setRecoveryNotice('');
    setLiveUsage([]); usageRef.current = [];
    reset();
    setApprovals([]);
    // 观看连接：abort 只 detach，后台任务继续；停止走 handleStop → /chat/cancel。
    const controller = new AbortController();
    stopRef.current = controller;
    let outcome: RunOutcome | null = null;
    try {
      // 两个 id 恒存在：会话一律先在空态经 POST /workspace/sessions 建好再进聊天
      const body: any = { question: q };
      if (session.conversation_id != null) body.conversation_id = session.conversation_id;
      if (session.session_id != null) body.session_id = session.session_id;
      if (resumeFrom != null) body.source_turn_start_seq = resumeFrom;
      const endpoint = resumeFrom != null ? 'chat/resume/stream' : 'chat/stream';
      const r = await fetch(`${API}/api/agents/${session.agent_key}/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...H },
        body: JSON.stringify(body), signal: controller.signal,
      });
      if (!r.ok || !r.body) {
        let message = `请求失败（HTTP ${r.status}）`;
        try { message = (await r.json()).detail || message; } catch { /* keep */ }
        throw new Error(message);
      }
      outcome = await consumeStream(r, controller);
    } catch (e: any) {
      if (controller.signal.aborted) {
        // 离页 detach：后台继续跑，回来时 attach / 历史消息就是答案
        outcome = { completed: false, finalAnswer: '', legacyThink: '', legacyAns: '', aborted: true };
      } else {
        outcome = {
          completed: false,
          finalAnswer: e?.message && !/^HTTP/.test(e.message) ? e.message : '请求失败，请稍后重试。',
          legacyThink: '', legacyAns: '', aborted: false,
        };
      }
    } finally {
      if (stopRef.current === controller) stopRef.current = null;
      if (outcome) commitOutcome(outcome);
      else { forceFlush(); setSending(false); }
    }
  }

  // 运行中输入：把这条喂给**已经开着的那条 SSE 流**（POST /chat/steer 回 202 + msg_id）。
  // 先乐观上屏成「待投递」，等那条流回一帧 type=user（同一个 msg_id）才翻成已投递 ——
  // 「已受理」和「已进上下文」不是一回事，UI 不替后端撒谎。
  async function handleSteer(q: string) {
    if (!session) return;
    const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const body: any = { session_id: session.session_id ?? '', question: q };
    if (session.conversation_id != null) body.conversation_id = session.conversation_id;
    transcriptRef.current?.scrollToEnd();
    try {
      const r = await fetch(`${API}/api/agents/${session.agent_key}/chat/steer`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...H },
        body: JSON.stringify(body),
      });
      // 409 = 这一轮刚收口（我们按「发送中」投，但它已经结束了）：不留一条投不进去的
      // 气泡，等本轮流收尾后当新消息发 —— 用户看到的仍是「我发了这句话，它在处理」。
      if (r.status === 409) {
        deferSendRef.current = q;
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const { msg_id } = await r.json();
      setMessages(prev => [...prev, { role: 'user', content: q, time: now, msgId: msg_id, pending: true }]);
    } catch {
      setMessages(prev => [...prev, {
        role: 'agent', time: now,
        content: '这条消息没能并进当前轮，请重新发送。',
      }]);
    }
  }

  async function resolveApproval(approvalId: string, decision: 'allow-once' | 'reject') {
    setApprovals(prev => prev.filter(p => p.approvalId !== approvalId));
    try {
      await fetch(`${API}/api/agents/approvals/${approvalId}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
    } catch { /* 已超时/断连：卡片已收起 */ }
  }

  const showEmpty = !loadingHistory && messages.length === 0 && !sending;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, fontFamily: W.font, background: W.bg }}>

      {/* 顶栏：会话标题 + 运行指示 + 右栏开合 */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: WS.sm, height: 48, padding: `0 ${WS.base}px`,
        flexShrink: 0, borderBottom: `0.5px solid ${W.borderSoft}`,
      }}>
        <HeaderDot active={sending} />
        <span style={{
          fontSize: 14, fontWeight: 500, color: W.text,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {session ? (session.label || session.session_id?.slice(0, 8)) : '工作区'}
        </span>
        {sending && <span style={{ fontSize: 13, color: W.tertiary, flexShrink: 0 }}>运行中</span>}
        <div style={{ flex: 1 }} />
        <button onClick={onToggleRight} title={rightOpen ? '收起文件面板' : '展开文件面板'}
          className="ws-btn ws-round"
          style={iconBtn}>
          <PanelRight size={16} />
        </button>
      </header>

      <RecoveryBanner api={API} tenantId={Number(H['X-Tenant-ID'])} sessionId={session?.session_id ?? null} busy={sending}
        onContinue={source => { void handleSend('继续上次任务', source); }} />
      {sending && recoveryNotice && <div role="status" style={{ padding: '8px 16px', fontSize: 13, color: W.tertiary }}>{recoveryNotice}</div>}

      {/* 内容轴：消息列与输入卡共用同一根居中轴，输入卡靠 seat 的 padding 差外扩 32px */}
      <div style={{
        flex: 1, minHeight: 0, width: '100%', maxWidth: CHAT_COLUMN, margin: '0 auto',
        display: 'flex', flexDirection: 'column',
      }}>

        {/* 消息区 */}
        <VirtualTranscript key={session?.conversation_id ?? 'draft'} ref={transcriptRef}
          loading={loadingHistory} hasMore={older.hasMore} loadingOlder={older.loadingOlder}
          error={older.error} onLoadOlder={older.loadOlder}
          style={{ padding: `${WS.base}px ${WS.base}px ${WS.sm}px` }}>

          {/* 会话内空态：与 DSH 的 conversation hero 同一形态（鱼 + 标题居中） */}
          {showEmpty && (
            <div key="empty" className="ws-chat-empty">
              <span className="ws-chat-empty-mark"><Fish size={30} strokeWidth={1.7} /></span>
              <div className="ws-chat-empty-title">minidsh</div>
            </div>
          )}

          {messages.map(msg => msg.role === 'user' ? (
            <div key={messageKey(msg)} className="ws-hover-host"
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginBottom: TURN_GAP }}>
              <div className="ws-round" style={{
                maxWidth: '78%', background: W.surfaceHi, color: W.text,
                borderRadius: R.xl, padding: '10px 16px',
                fontSize: 14, lineHeight: '22px', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                // 待投递：已受理、模型还没看到 —— 压一档透明度，别让它看起来跟已投递的一样
                opacity: msg.pending ? 0.62 : 1,
              }}>{msg.content}</div>
              <span className="ws-on-hover" style={{ fontSize: 12, color: W.dimmed, marginTop: 6, paddingRight: 4 }}>
                {msg.pending ? '待投递 · ' : ''}{msg.time}
              </span>
            </div>
          ) : (
            <div key={messageKey(msg)} style={{ marginBottom: TURN_GAP }}>
              <AgentTurn
                nodes={msg.nodes}
                content={msg.content}
                usage={msg.usage}
                trace={msg.trace}
                legacyThinking={msg.thinking}
                time={msg.time}
              />
            </div>
          ))}

          {/* 实时回合 */}
          {sending && (
            <div key={`message:${liveId.current}`} style={{ marginBottom: TURN_GAP }}>
              <AgentTurn nodes={trajNodes} content={liveAnsText} usage={liveUsage} running />
            </div>
          )}
        </VirtualTranscript>

        {/* 输入卡：与消息列同轴，向外多占 32px（harness 的 composer-card 关系） */}
        <div className="ws-composer-seat" style={{ paddingBottom: WS.base }}>
          {/* 审批卡片：后端工具调用挂起中，不裁决会等到超时 */}
          {approvals.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: WS.sm, marginBottom: WS.sm }}>
              {approvals.map(a => (
                <div key={a.approvalId} style={{
                  borderRadius: R.md, background: W.surface,
                  boxShadow: `0 0 0 0.5px ${W.warning}66, 0 4px 16px rgba(0,0,0,0.35)`,
                  padding: `${WS.md}px ${WS.base}px`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                    <ShieldAlert size={14} color={W.warning} />
                    <span style={{ fontSize: 13, fontWeight: 500, color: W.text }}>
                      模型申请提权：{a.metadata.from ?? '?'} → {a.metadata.to ?? '?'}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, lineHeight: '22px', color: W.secondary, whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: WS.sm }}>
                    {a.metadata.justification || a.reason || '（未给理由）'}
                  </div>
                  <div style={{ fontSize: 12, lineHeight: '20px', color: W.dimmed, marginBottom: WS.md }}>
                    只放行这一次 {a.tool} 调用；不裁决将等待至超时（超时按不可用处理）
                  </div>
                  <div style={{ display: 'flex', gap: WS.sm }}>
                    <button onClick={() => resolveApproval(a.approvalId, 'allow-once')}
                      className="ws-round" style={primaryBtn}>允许一次</button>
                    <button onClick={() => resolveApproval(a.approvalId, 'reject')}
                      className="ws-btn ws-round" style={outlineBtn}>拒绝</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <Composer
            agentKey={session?.agent_key}
            sessionId={session?.session_id}
            contextUsage={contextUsage?.sessionId === session?.session_id ? contextUsage?.usage : undefined}
            memoryAvailable={contextUsage?.sessionId === session?.session_id}
            disabled={!session}   /* 发送中不禁用：那时的发送语义是「并入当前轮」（steer） */
            sending={sending}
            onStop={() => { void handleStop(); }}
            uploading={uploading}
            uploadError={uploadError}
            onSend={handleSend}
            onUpload={onUpload}
            sandboxMode={sandboxMode}
            onModeChange={onModeChange}
          />
        </div>
      </div>
    </div>
  );
}

// ── 局部按钮样式（几何内联、颜色走 token）──

// 背景一律交给 .ws-btn* 持有：行内 background 会压死 :hover 蒙层
const iconBtn: React.CSSProperties = {
  width: 28, height: 28, borderRadius: 999, flexShrink: 0,
  color: W.secondary,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

// 主按钮：黑白反转，不用品牌蓝 —— 参考实现里蓝只留给链接与信息态
const primaryBtn: React.CSSProperties = {
  height: 32, padding: '0 16px', borderRadius: 999, border: 'none',
  background: W.primary, color: W.primaryText, fontSize: 13, fontWeight: 500,
  cursor: 'pointer', fontFamily: 'inherit',
};

const outlineBtn: React.CSSProperties = {
  height: 32, padding: '0 16px', borderRadius: 999,
  border: `0.5px solid ${W.borderStrong}`,
  color: W.text, fontSize: 13, fontFamily: 'inherit',
};
