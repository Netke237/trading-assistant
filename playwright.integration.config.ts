import { defineConfig, devices } from '@playwright/test'
import path from 'path'

export default defineConfig({
  testDir: './e2e/integration',
  timeout: 240_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-integration-report' }]],

  globalSetup: path.resolve('./e2e/integration/fixtures/real-backend.ts'),
  globalTeardown: path.resolve('./e2e/integration/fixtures/real-backend.ts'),

  use: {
    baseURL: 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3001',
    cwd: './frontend',
    reuseExistingServer: true,
    timeout: 60_000,
  },

  projects: [
    {
      name: 'chromium-integration',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
