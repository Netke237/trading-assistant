import { api } from '@/lib/api';
import { stockScanFailureReason } from '@/lib/stockScan';

/*
 * The one test that pins the cross-file coupling everything else assumes: the
 * `API <path> → <status>: <detail>` shape that api.ts's apiError() throws and
 * that stockScan.ts's API_ERROR regex splits. Every other suite hands
 * stockScanFailureReason a hand-written string of that shape, so changing the
 * arrow, the separator or the spacing in apiError() would leave them all green
 * while every backend-supplied detail silently started being treated as a
 * non-API error — losing the status line and, for a TypeError, gaining a
 * backend-unreachable hint it has no business showing.
 *
 * Deliberately NOT mocking '@/lib/api': the real formatter has to run.
 */
const originalFetch = global.fetch;

function respondWith(status: number, body: unknown): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  }) as unknown as typeof fetch;
}

afterEach(() => { global.fetch = originalFetch; });

describe('stockScanFailureReason over a real apiError() throw', () => {
  it("keeps the backend's own detail from a string-detail rejection", async () => {
    respondWith(422, { detail: 'rsi_oversold must be < 50' });

    const err = await api.postStockScan({} as never).catch((e: unknown) => e);

    expect(stockScanFailureReason(err))
      .toBe('API /api/stock-scan → 422: rsi_oversold must be < 50');
  });

  it("keeps Pydantic's joined validation messages", async () => {
    respondWith(422, { detail: [{ loc: ['body', 'horizon'], msg: 'field required', type: 'missing' }] });

    const err = await api.postStockScan({} as never).catch((e: unknown) => e);

    expect(stockScanFailureReason(err)).toBe('API /api/stock-scan → 422: field required');
  });

  it('collapses a gateway HTML body to the status line', async () => {
    respondWith(502, '<html>\n<head><title>502 Bad Gateway</title></head>\n<body>nginx</body>\n</html>');

    const err = await api.postStockScan({} as never).catch((e: unknown) => e);

    expect(stockScanFailureReason(err))
      .toBe('API /api/stock-scan → 502: the server returned an error page, not JSON');
  });

  it('never appends the unreachable hint to a response the backend actually sent', async () => {
    respondWith(500, { detail: 'scorer blew up' });

    const err = await api.postStockScan({} as never).catch((e: unknown) => e);

    expect(stockScanFailureReason(err)).not.toContain('could not reach the backend');
  });
});
