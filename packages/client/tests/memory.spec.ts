import { expect, test } from '@playwright/test';

test('workspace context usage links to the scoped Markdown editor', async ({ page }) => {
  const session = { session_id: 'session-one', conversation_id: 1, agent_key: 'alpha', agent_name: 'Alpha',
    title: '论文笔记', label: '论文笔记', entries: 0, project: null };
  const usage = { event_seq: 7, model: 'test', used_tokens: 8000, context_window: 10000, input_budget: 9000,
    compact_at: 7200, compactions: 0, compacted: false };
  let markdown = '原有笔记';
  await page.addInitScript(active => localStorage.setItem('workspace_active_session', JSON.stringify(active)), session);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/plugins' || path.startsWith('/api/plugins/client/')) return route.fallback();
    const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' };
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    const respond = (json: unknown) => route.fulfill({ json, headers });
    if (path === '/api/rpc') {
      const { id, method } = request.postDataJSON();
      const items = method === 'workspace.sessions.list' ? [session] : [];
      return respond({ jsonrpc: '2.0', id, result: { items } });
    }
    if (path.endsWith('/chat/live')) return route.fulfill({ status: 204, headers });
    if (path.endsWith('/chat/stream')) {
      const events = [
        { type: 'context/usage', usage: { ...usage, event_seq: 10, used_tokens: 1800, compactions: 1, compacted: true } },
        { type: 'done', answer: '已处理', session_id: session.session_id },
      ];
      return route.fulfill({ headers, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    if (path === '/api/memory/agents') return respond([{ agent_key: 'alpha', name: 'Alpha' }]);
    if (path.endsWith('/draft')) return respond({ markdown: '## 决定\n先整理证据' });
    if (path === `/api/memory/sessions/${session.session_id}`) {
      if (request.method() === 'PUT') markdown = request.postDataJSON().markdown;
      return respond({ markdown, summary: '已阅读三篇论文', usage });
    }
    return respond({ items: [], messages: [] });
  });

  await page.goto('/dashboard/workspace');
  await expect(page.getByRole('button', { name: '上下文用量 80%' })).toBeVisible();
  const composer = page.getByRole('textbox', { name: '消息输入' });
  await composer.fill('继续');
  await composer.press('Enter');
  await page.getByRole('button', { name: '上下文用量 18%' }).click();
  await expect(page.getByText('已压缩 1 次', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '查看会话记忆' }).click();

  const editor = page.getByRole('textbox', { name: 'SESSION.md' });
  await expect(editor).toHaveValue('原有笔记');
  await expect(page.getByText('已阅读三篇论文')).toBeVisible();
  await page.getByRole('button', { name: '生成会话笔记草稿' }).click();
  await page.getByRole('button', { name: '加入笔记' }).click();
  await page.getByRole('button', { name: '保存笔记' }).click();
  await expect(page.getByRole('status').filter({ hasText: '已保存' })).toBeVisible();
  expect(markdown).toContain('原有笔记\n\n## 决定');
});
