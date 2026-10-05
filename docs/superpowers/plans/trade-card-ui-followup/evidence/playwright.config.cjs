const path = require('node:path');
const { defineConfig } = require(path.join(process.cwd(), 'node_modules/@playwright/test'));
module.exports = defineConfig({
  testDir: path.join(process.cwd(), 'e2e/tests'),
  testMatch: 'trade-card-ui-followup.spec.ts',
  timeout: 60000, workers: 1,
  use: { baseURL: 'http://localhost:3001', launchOptions: { executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] } },
  reporter: 'list',
});
