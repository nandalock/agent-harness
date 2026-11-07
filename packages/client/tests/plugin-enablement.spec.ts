import { expect, test } from '@playwright/test';

test('the backend plugin catalog filters frontend bundles and navigation', async ({ page }) => {
  const requested: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/plugins/workflow/')) requested.push(request.url());
  });

  await page.addInitScript(() => {
    (window as any).__DSH_PLUGIN_CATALOG__ = [
      'agent-platform.http-api',
      'agent-platform.chat',
      'agent-platform.memory',
      'agent-platform.mcp-manager',
      'agent-platform.api-agents',
      'agent-platform.api-workspace',
      'agent-platform.faq',
      'agent-platform.xianyu',
    ];
  });

  await page.goto('/dashboard/knowledge', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-nav-id="chat"]')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-nav-id="workflow"]')).toHaveCount(0);

  const result = await page.evaluate(() => ({
    options: (window as any).__DSH_KERNEL__.router.options('/dashboard/workflow'),
    enabled: (window as any).__DSH_KERNEL__.plugins.enabled,
  }));
  expect(result.options.shell).toBe('bare');
  expect(result.enabled).not.toContain('agent-platform.workflow');
  expect(requested).toEqual([]);
});
