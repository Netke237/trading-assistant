import { test as base, expect } from '@playwright/test';
import { setupApiMocks } from './api-mocks';
import { setupRejectMocks } from './api-mocks-reject';

export * from '@playwright/test';

export const test = base.extend({
  page: async ({ page }, use) => {
    await setupApiMocks(page);
    await use(page);
  },
});

export const testReject = base.extend({
  page: async ({ page }, use) => {
    await setupRejectMocks(page);
    await use(page);
  },
});

export { expect };
