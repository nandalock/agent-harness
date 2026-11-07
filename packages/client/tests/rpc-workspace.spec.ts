import { expect, test } from '@playwright/test';

test('workspace page calls business services through /api/rpc', async ({ page }) => {
  const methods: string[] = [];
  page.on('request', request => {
    if (!request.url().includes('/api/rpc')) return;
    try {
      const body = request.postDataJSON() as { method?: string };
      if (body.method) methods.push(body.method);
    } catch {
      // A malformed request is not the contract this test observes.
    }
  });
  await page.goto('/dashboard/workspace');
  await expect.poll(() => methods.includes('workspace.sessions.list')).toBe(true);
  expect(methods).toContain('agent.list');
});
