import { expect, test } from '@playwright/test';

test('primary navigation is composed from plugins in declared order', async ({ page }) => {
  await page.goto('/dashboard/knowledge');
  await expect(page.locator('[data-nav-id]')).toHaveCount(8, { timeout: 15_000 });
  const ids = await page
    .locator('[data-nav-id]')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-nav-id')));
  expect(ids).toEqual([
    'chat',
    'knowledge',
    'agents',
    'mcp',
    'integrations',
    'memory',
    'workflow',
    'workspace',
  ]);
});

test('route metadata selects the shell layout', async ({ page }) => {
  await page.goto('/dashboard/knowledge');
  await expect(page.locator('[data-layout]')).toHaveAttribute('data-layout', 'standard', {
    timeout: 30_000,
  });

  // Client-side navigation exercises the same route metadata without a reload.
  await page.locator('[data-nav-id="mcp"]').click();
  await expect(page.locator('[data-layout]')).toHaveAttribute('data-layout', 'flush', {
    timeout: 15_000,
  });
});

test('keepAlive routes stay mounted when navigating away', async ({ page }) => {
  await page.goto('/dashboard/chat');
  const chat = page.locator('[data-keepalive="/dashboard/chat"]');
  await expect(chat).toHaveCSS('display', 'contents', { timeout: 30_000 });

  await page.locator('[data-nav-id="knowledge"]').click();
  await expect(chat).toHaveCSS('display', 'none');

  await page.locator('[data-nav-id="chat"]').click();
  await expect(chat).toHaveCSS('display', 'contents');
});

test('layout options are declared by the route, not the shell', async ({ page }) => {
  await page.goto('/dashboard/knowledge');
  await expect(page.locator('[data-nav-id="workspace"]')).toBeVisible();
  const options = await page.evaluate(() => ({
    workspace: (window as any).__DSH_KERNEL__.router.options('/dashboard/workspace').layout,
    workflow: (window as any).__DSH_KERNEL__.router.options('/dashboard/workflow/42').layout,
  }));
  expect(options.workspace.mode).toBe('immersive');
  expect(options.workspace.sidebar).toBe('collapsed');
  expect(options.workspace.navTheme).toBe('workspace');
  expect(options.workflow.mode).toBe('canvas');
  expect(options.workflow.sidebar).toBe('collapsed');
});
