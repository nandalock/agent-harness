import { expect, test } from '@playwright/test';

test('only browser entries advertised by the backend are loaded', async ({ page }) => {
  const requested: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/plugins/client/')) requested.push(request.url());
  });
  await page.route('**/api/plugins', async (route) => {
    const response = await route.fetch();
    const catalog = await response.json();
    catalog.clients = catalog.clients.filter((entry: { id: string }) => entry.id !== '@app/plugin-workflow');
    await route.fulfill({ response, json: catalog });
  });

  await page.goto('/dashboard/knowledge', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-nav-id="chat"]')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-nav-id="workflow"]')).toHaveCount(0);

  const options = await page.evaluate(() => (window as any).__DSH_KERNEL__.router.options('/dashboard/workflow'));
  expect(options.shell).toBe('bare');
  expect(requested.some((url) => url.includes('@app/plugin-chat'))).toBe(true);
  expect(requested.some((url) => url.includes('@app/plugin-workflow'))).toBe(false);
});
