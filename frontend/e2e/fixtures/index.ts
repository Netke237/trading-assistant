import { test as base, expect } from '@playwright/test';
import { setupApiMocks } from './api-mocks';
import { setupRejectMocks } from './api-mocks-reject';
import { attachConsoleGuard } from './console-guard';

export * from '@playwright/test';

export const test = base.extend({
  page: async ({ page }, use) => {
    await setupApiMocks(page);
    attachConsoleGuard(page);
    await use(page);
  },
});

export const testReject = base.extend({
  page: async ({ page }, use) => {
    await setupRejectMocks(page);
    attachConsoleGuard(page);
    await use(page);
  },
});

export { expect };
