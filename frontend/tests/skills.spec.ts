import { expect, test, type Page } from '@playwright/test';

const session = { session_id: 'skill-session', conversation_id: 7, agent_key: 'assistant',
  agent_name: 'Assistant', title: '技能测试', label: '技能测试', cwd: null, project: null };

async function mockApi(page: Page, disabled = false) {
  const prompts: string[] = [];
  await page.context().addCookies([{ name: 'auth_token', value: 'test-only', url: 'http://127.0.0.1:4100' }]);
  await page.addInitScript(value => localStorage.setItem('workspace_active_session', JSON.stringify(value)), session);
  await page.route('http://localhost:8000/**', async route => {
    const url = new URL(route.request().url());
    const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    let body: any = {};
    if (url.pathname.endsWith('/skills')) {
      expect(url.searchParams.get('session_id')).toBe(session.session_id);
      body = { skills: [{ key: 'overleaf-rt:overleaf-login', name: 'overleaf-login', kind: 'command',
        description: '登录 Overleaf', argument_hint: '[overleaf-url] [host-name]',
        unavailable_reason: disabled ? '请先为智能体绑定工具：overleaf_list_hosts' : null }] };
    } else if (url.pathname.endsWith('/chat/stream')) {
      prompts.push(route.request().postDataJSON().question);
      return route.fulfill({ headers: cors, contentType: 'text/event-stream', body:
        `data: ${JSON.stringify({ type: 'traj/open', node: { id: 'skill-node', kind: 'skill', status: 'loaded',
          turn: 1, step: 1, name: 'overleaf-rt:overleaf-login', arguments: 'https://www.overleaf.com' } })}\n\n` +
        `data: ${JSON.stringify({ type: 'done', answer: '请按提示在本机终端登录。', session_id: session.session_id })}\n\n` });
    } else if (url.pathname.endsWith('/messages/window')) body = { items: [], has_more: false, next_before_id: null };
    else if (url.pathname.endsWith('/messages')) body = [];
    else if (url.pathname === '/api/workspace/sessions') body = { items: [session] };
    else if (url.pathname.endsWith('/sandbox_mode')) body = { mode: 'workspace-write', effective: 'workspace-write' };
    else if (url.pathname.endsWith('/recovery')) body = { status: 'completed', can_resume: false };
    else if (url.pathname.endsWith('/files')) body = { entries: [], path: '', truncated: false };
    else if (url.pathname === '/api/agents') body = [{ key: 'assistant', name: 'Assistant' }];
    else if (url.pathname === '/api/chat/conversations/7') body = { id: 7, session_id: session.session_id };
    else if (url.pathname.endsWith('/projects') || url.pathname === '/api/chat/conversations') body = { items: [] };
    await route.fulfill({ json: body, headers: cors });
  });
  return prompts;
}

test('keyboard selection inserts the command, sends original arguments, and shows compact skill status', async ({ page }) => {
  const prompts = await mockApi(page);
  await page.goto('/dashboard/workspace');
  const input = page.getByRole('textbox', { name: '消息输入' });
  await input.fill('/overleaf');
  await expect(page.getByRole('option', { name: /overleaf-login/ })).toBeVisible();
  await input.press('Enter');
  await expect(input).toHaveValue('/overleaf-login ');
  expect(prompts).toEqual([]);
  await expect(page.getByText('参数：[overleaf-url] [host-name]', { exact: true })).toBeVisible();
  await input.fill('/overleaf-login https://www.overleaf.com');
  await input.press('Enter');
  await expect.poll(() => prompts).toEqual(['/overleaf-login https://www.overleaf.com']);
  await expect(page.getByTestId('skill-loaded')).toContainText('已加载技能');
  await expect(page.getByText('请按提示在本机终端登录。', { exact: true })).toBeVisible();
});

test('missing tool bindings remain visible with an explanation and cannot be picked', async ({ page }) => {
  const prompts = await mockApi(page, true);
  await page.goto('/dashboard/workspace');
  const input = page.getByRole('textbox', { name: '消息输入' });
  await input.fill('/overleaf');
  const option = page.getByRole('option', { name: /overleaf-login/ });
  await expect(option).toHaveAttribute('aria-disabled', 'true');
  await expect(option).toContainText('请先为智能体绑定工具');
  await option.click({ force: true });
  await expect(input).toHaveValue('/overleaf');
  await input.press('Escape');
  await expect(page.getByRole('listbox', { name: '技能与命令' })).toHaveCount(0);
  expect(prompts).toEqual([]);
});

test('reopening the slash menu discovers a skill installed during chat', async ({ page }) => {
  const prompts = await mockApi(page);
  let requests = 0;
  await page.route('http://localhost:8000/api/agents/assistant/skills*', async route => {
    requests++;
    const entry = prompts.length
      ? { key: 'installed:demo', name: 'demo', description: '刚安装的技能' }
      : { key: 'platform:skill-installer', name: 'skill-installer', description: '安装外部技能' };
    await route.fulfill({ headers: { 'access-control-allow-origin': '*' }, json: {
      skills: [{ ...entry, kind: 'skill', argument_hint: '', unavailable_reason: null }],
    } });
  });
  await page.goto('/dashboard/workspace');
  const input = page.getByRole('textbox', { name: '消息输入' });
  await input.fill('/skill-installer demo');
  await input.press('Enter');
  await expect.poll(() => prompts).toEqual(['/skill-installer demo']);
  await input.fill('/demo');
  await expect(page.getByRole('option', { name: /demo/ })).toBeVisible();
  expect(requests).toBeGreaterThan(1);
});
