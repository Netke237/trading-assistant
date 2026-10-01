import { parseApiError, statusOf } from '@/lib/apiError';

describe('apiError — reading api.ts thrown messages', () => {
  it('reads the status and detail of `API <path> → <status>: <detail>`', () => {
    const e = new Error('API /api/watched-contracts → 422: grading.contract_rules: Value error');
    expect(statusOf(e)).toBe(422);
    expect(parseApiError(e).detail).toBe('grading.contract_rules: Value error');
  });

  it('reads a status with no detail', () => {
    expect(statusOf(new Error('API /api/x → 500'))).toBe(500);
  });

  it('is null for anything else (network failure, plain strings)', () => {
    expect(statusOf(new TypeError('Failed to fetch'))).toBeNull();
    expect(statusOf('boom')).toBeNull();
    expect(statusOf(undefined)).toBeNull();
  });
});
