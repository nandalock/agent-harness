import { expect, test } from '@playwright/test';

test('slots must be declared and list entries render in order', async ({ page }) => {
  await page.goto('/dashboard');
  const result = await page.evaluate(() => {
    const kernel = (window as any).__DSH_KERNEL__;
    kernel.slots.declare('test.list');
    kernel.slots.register('test.list', { id: 'late', order: 20 }, () => null);
    kernel.slots.register('test.list', { id: 'early', order: 10 }, () => null);
    const order = kernel.slots.entries('test.list').map((entry: { id: string }) => entry.id);

    let undeclared = '';
    try {
      kernel.slots.register('test.missing', 'x', () => null);
    } catch (error) {
      undeclared = String(error);
    }

    kernel.slots.declare('test.single', { kind: 'single' });
    kernel.slots.register('test.single', 'one', () => null);
    let duplicate = '';
    try {
      kernel.slots.register('test.single', 'two', () => null);
    } catch (error) {
      duplicate = String(error);
    }

    return { order, undeclared, duplicate };
  });

  expect(result.order).toEqual(['early', 'late']);
  expect(result.undeclared).toContain('is not declared');
  expect(result.duplicate).toContain('already has an entry');
});

test('route child slots are declared with the route', async ({ page }) => {
  await page.goto('/dashboard');
  const declaration = await page.evaluate(() =>
    (window as any).__DSH_KERNEL__.slots.declaration('workflow.inspector'),
  );
  expect(declaration.kind).toBe('single');
});

test('the shell renders contributions into declared page slots', async ({ page }) => {
  await page.goto('/dashboard/knowledge');
  await page.evaluate(() => {
    const kernel = (window as any).__DSH_KERNEL__;
    kernel.slots.register('page.actions', 'test.action', () =>
      kernel.react.createElement('button', { 'data-testid': 'injected-action' }, '注入动作'),
    );
  });
  await expect(page.getByTestId('injected-action')).toBeVisible();
});
