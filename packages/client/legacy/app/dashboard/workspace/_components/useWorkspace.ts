'use client';

// useWorkspace —— 工作区页的数据层（RPC 业务调用 + 传输型 HTTP）
//
// 业务读写（会话/项目/文件树/文件夹/沙箱模式）走 JSON-RPC：
//   remote.workspace.* / remote.session.sandboxMode.* → POST /api/rpc
// 只有浏览器原生的传输型接口保留 HTTP：
//   GET  /api/workspace/{sid}/file       预览 / 下载
//   POST /api/workspace/{sid}/upload     多文件上传
//   GET  /api/workspace/browse           服务端目录浏览
//   POST /api/workspace/folder-picker    本机系统目录对话框
//
// 预览接口需要 X-Tenant-ID 头，<iframe>/<img> 直接指 URL 发不出自定义头，
// 所以预览一律 fetch → Blob → objectURL（本文件导出 fetchPreview 供分发）。

import { remote } from '@/lib/remote';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const TENANT_ID = 1;
const H = { 'X-Tenant-ID': String(TENANT_ID) };

/** 非 2xx → 抛后端的人话 detail；拿不到 JSON body 才退回 HTTP 状态码。 */
async function throwHttp(r: Response): Promise<never> {
  let detail = `HTTP ${r.status}`;
  try { detail = (await r.json()).detail || detail; } catch { /* 保持状态码 */ }
  throw new Error(detail);
}

/** 新建条目的类型（后端 ENTRY_KINDS 的镜像）。 */
export type EntryKind = 'file' | 'dir';

/** 会话的**项目归属**（= 项目注册表里那一行账目）。后端 `_project_for` 的镜像。
 *
 *  身份是 `key`（规范化后的路径**字符串**），不是 `label`：两个不同目录可以同名
 *  （都叫 test1），它们仍是两个项目；同一个目录改了显示名也仍是一个项目。
 *  因此 key 才能拿去当 React key / 折叠状态的键。
 *
 *  `id` 是注册表主键，只用于**改 / 删**这两个动作 —— 别拿它当身份：移除再重新
 *  登记同一目录会拿到新 id，而 key（路径）不变。 */
export interface WorkspaceProject {
  id: number;
  key: string;
  label: string;
  path: string;
  sort_order: number;
}

/** 标题来源：fallback = 首条消息前导词；provider = LLM 生成；user = 用户改名（已钉住）。
 *  null = 还没生成过（新会话 / 首条是纯图片），此时 title 回落成旧标签。 */
export type TitleSource = 'fallback' | 'provider' | 'user' | null;

export interface WorkspaceSession {
  session_id: string;
  agent_key: string | null;
  /** 智能体的显示名（后端查 agent_definitions）；查不到时后端回落成 key */
  agent_name: string | null;
  conversation_id: number;
  /** 会话标题，**恒非空**（后端保证）：侧栏第三层显示的就是它 */
  title: string;
  title_source: TitleSource;
  /** null = 落「未分组」虚拟桶（没有 cwd / 项目目录已被删掉） */
  project: WorkspaceProject | null;
  /** 旧标签（customer_name / channel / sid 前 8 位）。标题没生成过时的回落值，
   *  现在只在提示里用得到 —— 显示一律走 title。 */
  label: string;
  channel: string | null;
  updated_at: string | null;
  entries: number;
}

export interface FileEntry {
  name: string;
  is_dir: boolean;
  size: number;
  mtime: string | null;
  is_link: boolean;
  outside: boolean;   // 指向工作区外的符号链接：不可下钻
  /** 在该目录里写入**是否无需授权**（落在 SANDBOX_WRITE_ROOTS 写根内）。
   *  只有文件选择器会带这个字段（文件树不带）。两类根都能当工作区——读根里的
   *  目录可选，只是会话默认只读、模型写入时任要过一次升权审批；这个标志如今
   *  只影响措辞，不拦选择。 */
  writable?: boolean;
}

export interface SandboxModeInfo {
  override: string | null;
  default: string | null;
  effective: string;
}

export const SANDBOX_MODE_LABELS: Record<string, string> = {
  'read-only': '只读',
  'workspace-write': '标准模式',
  'danger-full-access': '完全访问',
};

export async function fetchWorkspaceSessions(): Promise<WorkspaceSession[]> {
  const result = await remote.workspace.sessions.list();
  return (result.items || []) as WorkspaceSession[];
}

/** 给会话改名。后端写一条 `user` 源的 `session/title` 事件 —— **改名即钉住**，
 *  此后自动生成（fallback / LLM）都不再改它。
 *
 *  返回的是**规范化之后**的标题（去了控制符、截到 80 字节），不是传进去的原串：
 *  显示必须用返回值，否则会出现「刚打完是一回事、刷新后变样」。
 *  标题里塞 ANSI / 零宽字符是预期内的输入，后端清洗后 400 才是真错误（净化为空）。 */
export async function renameWorkspaceSession(sessionId: string, title: string): Promise<string> {
  const result = await remote.workspace.sessions.rename({ session_id: sessionId, title });
  return result.title;
}

/** 给项目改名。返回**服务端规范化之后**的标题 —— 显示必须用它，不能拿用户输入
 *  顶替，否则会出现「刚打完是一回事、刷新后变样」。 */
export async function renameWorkspaceProject(projectId: number, title: string): Promise<string> {
  const result = await remote.workspace.projects.update({ project_id: projectId, title });
  return result.project.label;
}

/** **移除项目登记**（后端只删账目那一行）。
 *
 *  不删目录、不删文件、不删会话行、不删事件日志 —— 它的会话随即显示在「未分组」
 *  下。移除可逆（能重新添加同一目录），但旧会话不会回来，手工排序也不再保留。
 *  未知 id / 别的租户 → 404（后端 `throwHttp` 会把人话带出来）。 */
export async function deleteWorkspaceProject(projectId: number): Promise<void> {
  await remote.workspace.projects.remove({ project_id: projectId });
}

export async function fetchDir(sessionId: string, path: string): Promise<{ entries: FileEntry[]; truncated: boolean; writable: boolean }> {
  const d = await remote.workspace.files.list({ session_id: sessionId, path });
  return { entries: (d.entries || []) as FileEntry[], truncated: !!d.truncated, writable: d.writable !== false };
}

/** 在**会话工作区**的某个目录里新建空文件 / 目录（即时落盘）。返回新建的条目。
 *
 *  只建空条目：内容得靠上传覆盖或让模型写（后端有意只开这两个窄写入口）。 */
export async function createWorkspaceEntry(
  sessionId: string, dirPath: string, name: string, kind: EntryKind,
): Promise<FileEntry> {
  const result = await remote.workspace.files.create({
    session_id: sessionId, path: dirPath, name, type: kind,
  });
  return result.entry as FileEntry;
}

/** 按名字创建 / 打开工作区文件夹（`showDirectoryPicker()` 的落点）。
 *
 *  浏览器只交出文件夹名，交不出绝对路径；后端据此在工作区根下 mkdir / 打开
 *  同名目录，并返回可直接交给 POST /sessions 的 folder 值。 */
export interface WorkspaceFolderChoice {
  path: string;
  hostPath: string;
  folder: string;
  writable: boolean;
}

/** 服务端目录浏览（DSH browse 后端）：只列目录，路径由后端给。 */
export interface BrowseEntry {
  name: string;
  path: string;
  hidden: boolean;
}

export interface BrowseListing {
  path: string;
  entries: BrowseEntry[];
  home: string;
  crumbs: { label: string; path: string }[];
  truncated: boolean;
  canCreate: boolean;
  folder: string | null;
  writable: boolean;
  mode: 'local' | 'mounted';
}

export async function browseDirectory(path?: string): Promise<BrowseListing> {
  const q = path ? `?path=${encodeURIComponent(path)}` : '';
  const r = await fetch(`${API}/api/workspace/browse${q}`, { headers: H });
  if (!r.ok) await throwHttp(r);
  const d = await r.json();
  return {
    path: d.path as string,
    entries: (d.entries || []) as BrowseEntry[],
    home: (d.home || '') as string,
    crumbs: (d.crumbs || []) as { label: string; path: string }[],
    truncated: d.truncated === true,
    canCreate: d.can_create === true,
    folder: (d.folder ?? null) as string | null,
    writable: d.writable !== false,
    mode: d.mode === 'mounted' ? 'mounted' : 'local',
  };
}

export async function createBrowseDirectory(path: string, name: string): Promise<BrowseEntry> {
  const r = await fetch(`${API}/api/workspace/browse/mkdir`, {
    method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, name }),
  });
  if (!r.ok) await throwHttp(r);
  return (await r.json()).entry as BrowseEntry;
}

/** 本机系统文件夹选择器（返回真实绝对路径，不经过浏览器名称映射）。 */
export type HostFolderPick =
  | { status: 'picked'; path: string }
  | { status: 'cancelled' }
  | { status: 'unavailable'; message: string };

export async function pickHostWorkspaceFolder(): Promise<HostFolderPick> {
  const r = await fetch(`${API}/api/workspace/folder-picker`, {
    method: 'POST', headers: H,
  });
  if (r.status === 409 || r.status === 503) {
    let message = '本机文件夹选择器不可用';
    try { message = (await r.json()).detail || message; } catch { /* ignore */ }
    return { status: 'unavailable', message };
  }
  if (!r.ok) await throwHttp(r);
  const d = await r.json();
  return d.path ? { status: 'picked', path: d.path } : { status: 'cancelled' };
}

export async function ensureWorkspaceFolder(name: string): Promise<WorkspaceFolderChoice> {
  const d = await remote.workspace.folder.ensure({ name });
  return {
    path: d.path,
    hostPath: d.host_path || d.path,
    folder: d.folder,
    writable: d.writable !== false,
  };
}

/** 预览：fetch → Blob。调用方按 blob.type 分发渲染（pdf→iframe / image→img / text→文本）。 */
export async function fetchPreview(sessionId: string, path: string, signal?: AbortSignal): Promise<Blob> {
  const r = await fetch(
    `${API}/api/workspace/${sessionId}/file?path=${encodeURIComponent(path)}&inline=1`,
    { headers: H, signal },
  );
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.blob();
}

export function downloadUrl(sessionId: string, path: string): string {
  return `${API}/api/workspace/${sessionId}/file?path=${encodeURIComponent(path)}`;
}

/** 多文件上传 → .dsh-drops/。返回成功落盘的列表（后端整批校验失败时一个不落盘）。 */
export async function uploadFiles(sessionId: string, files: File[]): Promise<{ name: string; path: string; size: number }[]> {
  const fd = new FormData();
  for (const f of files) fd.append('files', f, f.name);
  const r = await fetch(`${API}/api/workspace/${sessionId}/upload`, { method: 'POST', headers: H, body: fd });
  if (!r.ok) await throwHttp(r);
  const d = await r.json();
  return d.uploaded || [];
}

export interface CreatedSession {
  session_id: string;
  conversation_id: number;
  agent_key: string;
  agent_name: string;
  label: string;
  folder: string | null;
}

/** 新建绑定了工作文件夹的会话。
 *
 *  ``folder`` 是后端工作区根下的名称映射；``folderPath`` 是本机选择器返回的
 *  真实绝对路径（local 后端优先用它，不再复制到 ~/.minidsh/workspaces）。
 */
export async function createWorkspaceSession(
  agentKey: string, folder: string | null, folderPath: string | null = null,
): Promise<CreatedSession> {
  const d = await remote.workspace.sessions.create({
    agent_key: agentKey, folder: folder ?? '', folder_path: folderPath ?? '',
  });
  return d.session as CreatedSession;
}

/** 重新接上正在后台跑的那一轮（切走页面 / 刷新后回来）。
 *
 *  204 = 该会话当前没有运行中的轮次，历史消息里已经有最终回复。
 *  200 = SSE：首帧是 `live/snapshot`（当前轨迹 + 待审批），随后是实时事件。 */
export async function attachLiveRun(
  agentKey: string, sessionId: string, conversationId: number | null, signal: AbortSignal,
): Promise<Response | null> {
  const query = new URLSearchParams({ session_id: sessionId });
  if (conversationId != null) query.set('conversation_id', String(conversationId));
  const r = await fetch(
    `${API}/api/agents/${encodeURIComponent(agentKey)}/chat/live?${query}`,
    { headers: H, signal },
  );
  if (r.status === 204) return null;
  if (!r.ok) await throwHttp(r);
  return r;
}

/** 显式停止当前轮。断开 SSE 不会停止任务，只有这个入口会。 */
export async function cancelLiveRun(agentKey: string, sessionId: string): Promise<boolean> {
  const r = await fetch(`${API}/api/agents/${encodeURIComponent(agentKey)}/chat/cancel`, {
    method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!r.ok) await throwHttp(r);
  const d = await r.json();
  return d.cancelled === true;
}

export async function fetchSandboxMode(sessionId: string): Promise<SandboxModeInfo> {
  const d = await remote.session.sandboxMode.get({ session_id: sessionId });
  return {
    override: d.override ?? null,
    default: d.default ?? null,
    effective: d.effective,
  };
}

export async function setSandboxMode(sessionId: string, mode: string): Promise<void> {
  await remote.session.sandboxMode.set({ session_id: sessionId, mode });
}

/** DSH 侧栏风格相对时间：今天 HH:mm / 昨天 / MM-DD / YYYY-MM-DD */
export function fmtRelTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
  const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, now)) return hm;
  if (sameDay(d, yesterday)) return '昨天';
  if (d.getFullYear() === now.getFullYear()) return `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 目录/文件的绝对显示大小（目录为 '-'）。 */
export function fmtSize(bytes: number, isDir: boolean): string {
  if (isDir) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
