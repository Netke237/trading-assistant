import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'phase1-e2e.spec.ts',
  timeout: 300_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-integration-report' }]],

  use: {
    baseURL: 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'on',
  },

  projects: [
    {
      name: 'chromium-e2e',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
