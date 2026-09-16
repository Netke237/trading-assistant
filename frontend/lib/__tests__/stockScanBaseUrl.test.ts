import { stockScanFailureReason } from '@/lib/stockScan';

/*
 * The hint has to name the address the app actually calls. It used to
 * hardcode "port 8000", which is wrong in every deployment that sets
 * NEXT_PUBLIC_API_URL — a commit about not telling the user false things
 * about the backend. The rest of this module's tests mock API_BASE_URL to the
 * default localhost:8000, so re-hardcoding that literal would keep them all
 * green; this file is the one that would fail.
 */
jest.mock('@/lib/api', () => ({
  api: { postStockScan: jest.fn(), getLastStockScanStatus: jest.fn() },
  API_BASE_URL: 'https://trading.example.test:9443',
}));

describe('stockScanFailureReason — backend address in the hint', () => {
  it('names the configured base URL, not a hardcoded localhost port', () => {
    expect(stockScanFailureReason(new TypeError('Failed to fetch')))
      .toBe('Failed to fetch (could not reach the backend at https://trading.example.test:9443)');
  });
});
