import { expect, test, type Page } from '@playwright/test';

const catalog = [
  { key: 'local:weekly', name: 'weekly', description: '整理本周工作报告', source: 'local', kind: 'skill',
    tools: [] as string[],
    argument_hint: '', model_invocable: true, user_invocable: true, unavailable_reason: null },
  { key: 'overleaf-rt:overleaf', name: 'overleaf', description: '管理 Overleaf 项目、文档和评论，按需读取参考说明', source: 'overleaf-rt', kind: 'skill',
    package_key: 'overleaf-rt', package_name: 'overleaf', binding_key: '@package/overleaf-rt',
    aliases: ['overleaf-editing', 'overleaf-rt:overleaf-editing', 'overleaf-comments', 'overleaf-rt:overleaf-comments'],
    tools: ['overleaf_read_doc', 'overleaf_edit_doc', 'overleaf_list_comments'],
    argument_hint: '', model_invocable: true, user_invocable: true, unavailable_reason: null },
];

const agents = [
  { key: 'alpha', name: 'Alpha', desc: '测试智能体' },
  { key: 'beta', name: 'Beta' },
];

async function mockAgentSettings(page: Page, overrides: Record<string, unknown> = {}) {
  const state = {
    configs: {
      alpha: { provider: 'deepseek', model: 'deepseek-chat', system_prompt: '保留提示词', max_steps: 9,
        session_enabled: false, skill_install_enabled: false, custom_setting: { preserve: true },
        skills_enabled: true, enabled_skills: null, ...overrides } as Record<string, unknown>,
      beta: { skills_enabled: true, enabled_skills: ['local:weekly'] } as Record<string, unknown>,
    } as Record<string, Record<string, unknown>>,
    bindings: [] as string[],
    failCatalog: false,
    failConfig: false,
    catalogRequests: 0,
    saves: 0,
    manualSaves: 0,
    availableTools: ['overleaf_read_doc', 'overleaf_edit_doc', 'overleaf_list_comments'],
  };
  function automaticTools(key: string) {
    const config = state.configs[key];
    const result: Record<string, string[]> = {};
    if (config.skills_enabled === false) return result;
    const names = config.enabled_skills as string[] | null;
    const selected = catalog.filter(entry => names == null || names.some(name =>
      name === entry.key || name === entry.name || ('binding_key' in entry && name === entry.binding_key)
      || entry.aliases?.includes(name)));
    for (const entry of selected) for (const tool of entry.tools) {
      const owner = 'package_name' in entry ? entry.package_name! : entry.name;
      result[tool] = [...new Set([...(result[tool] || []), owner])];
    }
    if (selected.length) result.skill = ['技能加载'];
    return result;
  }
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/plugins' || path.startsWith('/api/plugins/client/')) return route.fallback();
    const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' };
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    const respond = (json: unknown, status = 200) => route.fulfill({ status, json, headers });
    if (path === '/api/rpc') {
      const { id, method, params } = request.postDataJSON();
      const result = (value: unknown) => respond({ jsonrpc: '2.0', id, result: value });
      if (method === 'agent.list') {
        return result({ items: agents });
      }
      if (method === 'agent.getConfig') {
        if (state.failConfig) {
          return respond({ jsonrpc: '2.0', id, error: { code: -32603, message: '读取智能体配置失败' } });
        }
        const key = params.agent_key;
        return result({ agent_key: key, config: state.configs[key], cache_policy: {}, model_info: {} });
      }
      if (method === 'agent.saveConfig') {
        const key = params.agent_key;
        state.configs[key] = params.config;
        state.saves++;
        return result({ agent_key: key, config: state.configs[key], cache_policy: {} });
      }
      return respond({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } });
    }
    if (/\/skills\/catalog$/.test(path)) {
      state.catalogRequests++;
      if (state.failCatalog) return respond({ detail: 'failed' }, 503);
      return respond({ available: true, skills: catalog.map(entry => {
        return { ...entry, tools_ready: entry.tools.every(name => state.availableTools.includes(name)) };
      }) });
    }
    if (path === '/api/agents') return respond(agents);
    if (path === '/api/mcp/tools/all') return respond([
      ...['skill', 'skill_install'].map(name => ({ name, description: name, plugin_id: 'skill-tools', plugin_name: 'agent-platform.skill-tools' })),
      ...state.availableTools.map(name => ({ name, description: name, plugin_id: 'overleaf', plugin_name: 'agent-platform.overleaf-mcp' })),
      { name: 'echo', description: 'Echo', plugin_id: 'extras', plugin_name: 'agent-platform.extras' },
    ]);
    if (path === '/api/tools/bindings') return respond({ alpha: state.bindings });
    if (path === '/api/tools/bindings/alpha') {
      if (request.method() === 'GET') {
        const automatic = automaticTools('alpha');
        return respond({ manual_tools: state.bindings, automatic_tools: automatic,
          tools: [...new Set([...state.bindings, ...Object.keys(automatic)])] });
      }
      state.manualSaves++;
      state.bindings = request.postDataJSON();
      return respond({ ok: true });
    }
    if (path === '/api/tools/capabilities/sandbox') return respond({ enabled: true });
    if (path === '/api/chat/conversations') return respond({ items: [] });
    return respond({});
  });
  return state;
}

async function openConfig(page: Page, key = 'alpha') {
  await page.goto(`/agents/${key}`);
  await expect(page.getByRole('region', { name: '技能绑定' }).getByRole('checkbox', { name: /weekly/ })).toBeVisible();
}

async function saveConfig(page: Page) {
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect(page.getByText('保存成功', { exact: true })).toBeVisible();
}

test.setTimeout(60_000);

test('empty, selected and disabled skills persist without replacing other agent settings', async ({ page }) => {
  const state = await mockAgentSettings(page);
  await openConfig(page);
  const skills = page.getByRole('region', { name: '技能绑定' });
  await expect(skills.getByRole('radio', { name: '全部技能包（含新增）' })).toBeChecked();
  await expect(skills.getByText('已选 2/2 包', { exact: true })).toBeVisible();
  await skills.getByRole('button', { name: '清空选择' }).click();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual([]);
  expect(state.configs.alpha).toMatchObject({ provider: 'deepseek', max_steps: 9, session_enabled: false,
    skill_install_enabled: false, custom_setting: { preserve: true } });
  await page.reload();
  await expect(skills.getByRole('checkbox', { name: /weekly/ })).not.toBeChecked();
  await skills.getByRole('checkbox', { name: /weekly/ }).check();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['local:weekly']);
  await skills.getByRole('checkbox', { name: '启用技能', exact: true }).uncheck();
  await saveConfig(page);
  await page.reload();
  await expect(skills.getByRole('checkbox', { name: '启用技能', exact: true })).not.toBeChecked();
  await expect(skills.getByRole('checkbox', { name: /weekly/ })).toBeChecked();
  await expect(skills.getByRole('checkbox', { name: /weekly/ })).toBeDisabled();
  expect(state.configs.alpha.skills_enabled).toBe(false);
  expect(state.configs.beta.enabled_skills).toEqual(['local:weekly']);
});

test('Overleaf is a single skill entry without separate reference bindings', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: [] });
  state.availableTools = [];
  await openConfig(page);
  const skills = page.getByRole('region', { name: '技能绑定' });
  const overleaf = skills.getByRole('checkbox', { name: 'overleaf', exact: true });
  await expect(overleaf).toBeEnabled();
  await expect(skills.getByRole('checkbox', { name: /overleaf-/ })).toHaveCount(0);
  await expect(skills.getByText('包含 2 项能力', { exact: true })).toHaveCount(0);
  await expect(skills.getByText('overleaf-editing', { exact: true })).toHaveCount(0);
  await expect(skills.getByText('overleaf-comments', { exact: true })).toHaveCount(0);
  await expect(skills.getByText('管理 Overleaf 项目、文档和评论，按需读取参考说明', { exact: true })).toBeVisible();
  await overleaf.check();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['@package/overleaf-rt']);
  await page.reload();
  await expect(overleaf).toBeChecked();
  await expect(skills.getByText('已选 1/2 包', { exact: true })).toBeVisible();
  await skills.getByRole('radio', { name: '全部技能包（含新增）' }).check();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toBeNull();
});

test('editing selections retains skills whose providers are currently unavailable', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: ['weekly', 'offline:missing'] });
  await openConfig(page);
  const skills = page.getByRole('region', { name: '技能绑定' });
  await expect(skills.getByRole('checkbox', { name: /未发现：offline:missing/ })).toBeChecked();
  await skills.getByRole('checkbox', { name: /weekly/ }).uncheck();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['offline:missing']);
});

test('saving a skill package refreshes automatic tool bindings without manual requests', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: [] });
  state.failCatalog = true;
  await page.goto('/agents/alpha');
  const skills = page.getByRole('region', { name: '技能绑定' });
  await expect(skills.getByRole('alert')).toContainText('技能目录加载失败');
  state.failCatalog = false;
  await skills.getByRole('button', { name: '重试' }).click();
  await expect(skills.getByRole('checkbox', { name: 'overleaf', exact: true })).toBeVisible();
  const before = state.catalogRequests;
  await skills.getByRole('checkbox', { name: 'overleaf', exact: true }).check();
  await saveConfig(page);
  await expect.poll(() => state.catalogRequests).toBeGreaterThan(before);
  await page.getByText('overleaf-mcp · overleaf', { exact: true }).click();
  for (const name of state.availableTools) {
    await expect(page.getByRole('checkbox', { name, exact: true })).toBeChecked();
    await expect(page.getByRole('checkbox', { name, exact: true })).toBeDisabled();
  }
  expect(state.bindings).toEqual([]);
  expect(state.manualSaves).toBe(0);
});

test('removing a skill preserves manual tools and does not persist its automatic grants', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: [] });
  state.bindings = ['overleaf_read_doc'];
  await openConfig(page);
  const skills = page.getByRole('region', { name: '技能绑定' });
  await skills.getByRole('checkbox', { name: 'overleaf', exact: true }).check();
  await saveConfig(page);
  await page.getByText('overleaf-mcp · overleaf', { exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'overleaf_edit_doc', exact: true })).toBeDisabled();
  await page.getByText('extras', { exact: true }).click();
  await page.getByRole('checkbox', { name: 'echo', exact: true }).check();
  await expect.poll(() => state.manualSaves).toBe(1);
  expect(state.bindings).toEqual(['overleaf_read_doc', 'echo']);
  await skills.getByRole('checkbox', { name: 'overleaf', exact: true }).uncheck();
  await saveConfig(page);
  await expect(page.getByRole('checkbox', { name: 'overleaf_read_doc', exact: true })).toBeEnabled();
  await expect(page.getByRole('checkbox', { name: 'overleaf_read_doc', exact: true })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'overleaf_edit_doc', exact: true })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'echo', exact: true })).toBeChecked();
});

test('legacy names select the canonical skill and retain unrelated missing skills', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: ['overleaf-rt:overleaf-comments', 'offline:missing'] });
  await openConfig(page);
  const skills = page.getByRole('region', { name: '技能绑定' });
  const overleaf = skills.getByRole('checkbox', { name: 'overleaf', exact: true });
  await expect(overleaf).toBeChecked();
  await expect(skills.getByText('原配置仅启用了部分内容，勾选后整包生效。', { exact: true })).toHaveCount(0);
  expect(state.configs.alpha.enabled_skills).toEqual(['overleaf-rt:overleaf-comments', 'offline:missing']);
  await overleaf.uncheck();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['offline:missing']);
  await overleaf.check();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['offline:missing', '@package/overleaf-rt']);
  await page.reload();
  await expect(overleaf).toBeChecked();
  await overleaf.uncheck();
  await saveConfig(page);
  expect(state.configs.alpha.enabled_skills).toEqual(['offline:missing']);
});

test('configuration load failures prevent saving a default over existing bindings', async ({ page }) => {
  const state = await mockAgentSettings(page, { enabled_skills: ['local:weekly'] });
  state.failConfig = true;
  await page.goto('/agents/alpha');
  await expect(page.getByRole('alert')).toHaveText('读取智能体配置失败');
  await expect(page.getByRole('button', { name: '保存配置', exact: true })).toBeDisabled();
  expect(state.saves).toBe(0);
});
