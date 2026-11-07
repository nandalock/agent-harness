/** Capture the real frontend with isolated example responses, without a database.
 * Start packages/client on 4176, then: node scripts/capture-readme.mjs
 * Requires the client's npm dependencies and an installed Playwright browser.
 */
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../packages/client/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const output = fileURLToPath(new URL('../docs/images/', import.meta.url));
await mkdir(output, { recursive: true });
const agents = [
  { key: 'research', name: '研究助手', desc: '阅读项目资料，整理研究笔记与可交付文档。', status: 'active', agent_type: 'agent' },
  { key: 'coding', name: '代码助手', desc: '在会话工作区中阅读代码、运行工具并验证修改。', status: 'active', agent_type: 'agent' },
  { key: 'support', name: '知识库助手', desc: '结合知识库与工具，为团队解答常见问题。', status: 'draft', agent_type: 'agent' },
];
const project = { id: 1, key: '/demo/research', label: '研究笔记', path: '/demo/research', sort_order: 0 };
const sessions = ['整理插件系统的设计说明', '阅读资料与生成研究提纲', '检查技能与工具的协作方式'].map((title, i) => ({
  session_id: `demo-${i + 1}`, agent_key: 'research', agent_name: '研究助手', conversation_id: i + 1,
  title, title_source: 'user', project, label: title, channel: 'agent:research',
  updated_at: '2026-11-04T09:30:00+08:00', entries: 4,
}));
const files = ['architecture.md', 'research-notes.md', 'references', 'README.md'].map((name, i) => ({
  name, is_dir: i === 2, size: i === 2 ? 0 : 2048, mtime: '2026-11-04T09:30:00+08:00', is_link: false, outside: false,
}));
const catalog = [
  { key: 'overleaf-rt:overleaf', name: 'overleaf', source: 'overleaf-rt', kind: 'skill',
    description: '阅读与编辑 Overleaf 文档、管理评论和编译，按任务加载参考说明。',
    package_key: 'overleaf-rt', package_name: 'overleaf', binding_key: '@package/overleaf-rt' },
  { key: 'local:research-notes', name: 'research-notes', source: 'local', kind: 'skill',
    description: '把阅读材料整理成结构清晰、可追溯来源的研究笔记。' },
].map(e => ({ ...e, tools: [], argument_hint: '', model_invocable: true, user_invocable: true, unavailable_reason: null }));
const nodes = [
  ['start', 'start', '开始', '用户消息输入', 65],
  ['research', 'agent', '资料整理', '研究助手 · 提取问题与上下文', 330],
  ['review', 'agent', '检查与归纳', '代码助手 · 核对结果与依据', 610],
  ['end', 'end', '结束', '返回最终结果', 895],
].map(([id, nodeType, label, description, x]) => ({ id, type: 'custom', position: { x, y: 220 },
  data: { nodeType, label, description, config: { agent_key: id === 'review' ? 'coding' : 'research' } } }));
const edges = nodes.slice(1).map((node, i) => ({ id: `edge-${i}`, source: nodes[i].id, target: node.id, type: 'custom' }));
const config = { provider: 'deepseek', model: 'deepseek-chat', base_url: 'https://api.deepseek.com', api_key: '',
  system_prompt: '你是研究助手。先阅读当前项目的资料，再使用已绑定的技能与工具完成任务。说明依据，输出可直接使用的 Markdown 文档。',
  skills_enabled: true, enabled_skills: null, session_enabled: true, max_steps: 12, max_tokens: 4096 };
const messages = [
  { id: 1, role: 'user', content: '请整理这个项目的插件架构，说明技能、工具和会话之间如何协作。', created_at: '2026-11-04T09:29:00+08:00' },
  { id: 2, role: 'assistant', content: '## 插件协作方式\n\n项目通过 **PluginRuntime** 加载插件，按服务依赖完成装配。\n\n- **技能**：先展示摘要，需要时再读取完整说明与参考资料。\n- **工具**：由插件注册到统一工具服务，Agent Loop 根据任务调用。\n- **会话**：记录消息、工具调用和结果，供历史展示与恢复使用。\n\n### 一次任务的执行\n\n用户消息 → 技能目录 → 按需加载 → 工具执行 → 写入会话事件。\n\n设计说明已整理为 `architecture.md`，可以在右侧文件面板中查看。', created_at: '2026-11-04T09:30:00+08:00' },
];
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, locale: 'zh-CN', reducedMotion: 'reduce' });
  await context.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/plugins' || path.startsWith('/api/plugins/client/')) return route.fallback();
    const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' };
    const json = data => route.fulfill({ json: data, headers });
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path === '/api/rpc') {
      const { method, id } = request.postDataJSON();
      const result = {
        'agent.list': { items: agents }, 'agent.getConfig': { config, cache_policy: {} },
        'workspace.sessions.list': { items: sessions }, 'workspace.projects.list': { items: [project] },
        'workspace.files.list': { entries: files, truncated: false, writable: true },
        'session.sandboxMode.get': { override: null, default: 'workspace-write', effective: 'workspace-write' },
        'session.recovery': { status: 'idle', can_resume: false },
        'session.trajectory': { nodes: [], usage: [], summary: {} },
      }[method] ?? {};
      return json({ jsonrpc: '2.0', id, result });
    }
    if (path === '/api/workflows/1') return json({ id: 1, name: '研究资料整理流程', nodes, edges, status: 'draft' });
    if (path === '/api/agents') return json(agents);
    if (path === '/api/chat/conversations/1/messages/window') return json({
      items: messages.map(m => ({ ...m, role: m.role === 'user' ? 'customer' : 'agent' })),
      has_more: false, next_before_id: null,
    });
    if (path === '/api/chat/conversations/1') return json({ id: 1, messages, agent_key: 'research', session_id: 'demo-1' });
    if (path.includes('/chat/attach') || path.endsWith('/chat/live')) return route.fulfill({ status: 204, headers });
    if (path.endsWith('/skills/catalog') || path.endsWith('/skills')) return json({ available: true, skills: catalog });
    if (path === '/api/tools/bindings/research') return json({ manual_tools: ['python', 'powershell'], tools: ['python', 'powershell', 'skill'], automatic_tools: { skill: ['技能加载'] } });
    if (path === '/api/tools/capabilities/sandbox') return json({ enabled: true });
    if (path === '/api/mcp/tools/all') return json([
      ...['python', 'powershell', 'bash'].map(name => ({ name, description: name, plugin_id: 'sandbox-tools', plugin_name: 'agent-platform.sandbox-tools' })),
      ...['skill', 'skill_install'].map(name => ({ name, description: name, plugin_id: 'skill-tools', plugin_name: 'agent-platform.skill-tools' })),
    ]);
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'text/markdown', body: '# 插件架构\n\n技能、工具与会话通过插件服务协作。', headers });
    return json({ items: [], models: [], nodes: [], enabled: true });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('workspace_active_session', JSON.stringify({
    agent_key: 'research', conversation_id: 1, session_id: 'demo-1', label: '整理插件系统的设计说明',
  })));
  const base = process.env.README_BASE_URL || 'http://127.0.0.1:4176';
  async function capture(path, filename, ready) {
    await page.goto(base + path);
    await expect(page.getByText(ready, { exact: false }).first()).toBeVisible({ timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1000);
    await page.screenshot({ path: output + filename, animations: 'disabled' });
    console.log('Captured ' + filename);
  }
  await capture('/dashboard/workspace', 'workspace.png', '插件协作方式');
  await page.setViewportSize({ width: 1440, height: 720 });
  await capture('/dashboard/agents', 'agents.png', '代码助手');
  await capture('/dashboard/workflow/1', 'workflow.png', '检查与归纳');
  await page.setViewportSize({ width: 1000, height: 1000 });
  await page.goto(base + '/agents/research');
  const skillRegion = page.getByRole('region', { name: '技能绑定' });
  await skillRegion.scrollIntoViewIfNeeded();
  await expect(skillRegion.getByRole('checkbox', { name: 'overleaf', exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: output + 'agent-settings.png', animations: 'disabled' });
  console.log('Captured agent-settings.png');
  if (errors.length) throw new Error('Frontend errors: ' + [...new Set(errors)].join('; '));
} finally {
  await browser.close();
}
