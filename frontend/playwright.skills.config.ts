import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'skills.spec.ts',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:4100',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'node node_modules/next/dist/bin/next dev -p 4100',
    url: 'http://127.0.0.1:4100/login',
    env: { NEXT_DIST_DIR: '.next-build', NEXT_TELEMETRY_DISABLED: '1' },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
