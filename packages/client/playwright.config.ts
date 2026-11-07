import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  // Each worker builds plugin bundles through the dev server on first use.
  timeout: 90_000,
  workers: 2,
  expect: { timeout: 15_000 },
  use: {
    baseURL: 'http://127.0.0.1:4175',
    viewport: { width: 1280, height: 900 },
    navigationTimeout: 60_000,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4175 --strictPort',
    url: 'http://127.0.0.1:4175',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    // Tests have no backend; skip the catalog round trip unless a test injects
    // `window.__DSH_PLUGIN_CATALOG__` explicitly.
    env: { ...(process.env as Record<string, string>), VITE_PLUGIN_CATALOG: 'off' },
  },
});
