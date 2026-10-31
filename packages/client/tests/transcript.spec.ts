import { expect, test, type Page } from '@playwright/test';

async function overlaps(page: Page) {
  return page.locator('[data-message-key]').evaluateAll(elements => {
    const rows = elements.map(element => ({
      index: Number((element as HTMLElement).dataset.index),
      rect: element.getBoundingClientRect(),
    })).sort((left, right) => left.index - right.index);
    return rows.slice(1).flatMap((row, index) => {
      const previous = rows[index];
      return row.index === previous.index + 1 && row.rect.top < previous.rect.bottom - 1
        ? [{ before: previous.index, after: row.index, overlap: previous.rect.bottom - row.rect.top }]
        : [];
    });
  });
}

async function expectSeparated(page: Page) {
  await expect(page.locator('[data-message-key]').first()).toBeAttached();
  await expect.poll(() => overlaps(page)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/tests/fixtures/transcript.html');
  await expectSeparated(page);
});

test('messages retain measured heights when the sidebar changes width', async ({ page }) => {
  await page.getByTestId('virtual-transcript').evaluate(element => { element.scrollTop = element.scrollHeight / 2; });
  await page.waitForTimeout(200);
  for (let repeat = 0; repeat < 4; repeat++) {
    await page.getByRole('button', { name: '切换侧栏' }).click();
    // Let both the row and container ResizeObservers complete their delivery.
    await page.waitForTimeout(150);
    await expectSeparated(page);
  }
});

test('a late viewport resize cannot leave messages positioned at estimated heights', async ({ page }) => {
  // Exercise the observer ordering race: row sizes arrive before the viewport
  // invalidates its width-dependent cache. Layout must work in either order.
  await page.addInitScript(() => {
    const Native = window.ResizeObserver;
    window.ResizeObserver = class extends Native {
      constructor(callback: ResizeObserverCallback) {
        super((entries, observer) => {
          if (entries.some(entry => entry.target.getAttribute('data-testid') === 'virtual-transcript')) {
            setTimeout(() => callback(entries, observer), 30);
          } else {
            callback(entries, observer);
          }
        });
      }
    };
  });
  await page.reload();
  await expectSeparated(page);
  await page.getByRole('button', { name: '切换侧栏' }).click();
  await page.waitForTimeout(200);
  await expectSeparated(page);
});

test('streamed markdown and disclosure expansion keep subsequent messages below', async ({ page }) => {
  const last = page.locator('[data-row-id="5"]');
  const originalHeight = (await last.boundingBox())!.height;
  await page.getByRole('button', { name: '流式追加正文' }).click();
  await expect.poll(async () => (await last.boundingBox())!.height).toBeGreaterThan(originalHeight);
  await expectSeparated(page);
  const disclosure = page.getByText('思考', { exact: true }).last();
  await disclosure.click();
  await expectSeparated(page);
  await page.getByRole('button', { name: '追加消息' }).click();
  await expectSeparated(page);
  await page.setViewportSize({ width: 720, height: 900 });
  await page.waitForTimeout(150);
  await expectSeparated(page);
});

async function visibleAnchor(page: Page) {
  return page.getByTestId('virtual-transcript').evaluate(scroll => {
    const top = scroll.getBoundingClientRect().top;
    const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-row-id]'))
      .find(element => element.getBoundingClientRect().bottom > top + 1)!;
    return { id: row.dataset.rowId!, top: row.getBoundingClientRect().top };
  });
}

test('virtualization and the reading anchor survive prepended history', async ({ page }) => {
  await page.goto('/tests/fixtures/transcript.html?count=100');
  await expectSeparated(page);
  await page.getByTestId('virtual-transcript').evaluate(element => { element.scrollTop = element.scrollHeight / 2; });
  await page.waitForTimeout(200);
  const anchor = await visibleAnchor(page);
  await page.getByRole('button', { name: '加载历史' }).click();
  await expectSeparated(page);
  await expect.poll(async () => {
    const row = await page.locator(`[data-row-id="${anchor.id}"]`).boundingBox();
    return row ? Math.abs(row.y - anchor.top) : Infinity;
  }).toBeLessThan(5);
  expect(await page.locator('[data-message-key]').count()).toBeLessThan(25);
});

test('streaming preserves an older reading position and latest-message navigation', async ({ page }) => {
  await page.goto('/tests/fixtures/transcript.html?count=100');
  await expectSeparated(page);
  const scroll = page.getByTestId('virtual-transcript');
  await scroll.evaluate(element => { element.scrollTop = element.scrollHeight / 2; });
  await page.waitForTimeout(200);
  const anchor = await visibleAnchor(page);
  await page.getByRole('button', { name: '流式追加正文' }).click();
  await expectSeparated(page);
  await expect.poll(async () => Math.abs((await page.locator(`[data-row-id="${anchor.id}"]`).boundingBox())!.y - anchor.top)).toBeLessThan(5);
  await page.getByRole('button', { name: '回到最新消息' }).click();
  await expect.poll(() => scroll.evaluate(element => element.scrollHeight - element.scrollTop - element.clientHeight)).toBeLessThan(48);
  await expectSeparated(page);
});
