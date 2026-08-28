import { api } from '@/lib/api';

// api.ts has no `apiError` export — it's exercised indirectly through any
// public method that hits `get`/`post`. getStockQuote (a plain GET) is used
// here purely as a vehicle; nothing about its own behavior is under test.

function mockFetchOnce(status: number, body: unknown, bodyIsJson = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status,
    text: async () => (bodyIsJson ? JSON.stringify(body) : String(body)),
  }) as unknown as typeof fetch;
}

describe('apiError — FastAPI/Pydantic error body formatting', () => {
  it('joins msg fields from a Pydantic validation-error list instead of dumping raw JSON', async () => {
    mockFetchOnce(422, {
      detail: [
        { loc: ['body', 'strike'], msg: 'Input should be greater than 0', type: 'greater_than' },
        { loc: ['body', 'premium'], msg: 'Input should be greater than 0', type: 'greater_than' },
      ],
    });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow(
      'Input should be greater than 0; Input should be greater than 0',
    );
  });

  it('still uses a plain string detail unchanged', async () => {
    mockFetchOnce(404, { detail: 'position_not_found' });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('position_not_found');
  });

  it('falls back to the raw body when detail is a list with no usable msg field', async () => {
    mockFetchOnce(500, { detail: [{ loc: ['body'] }] });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow(/"loc"/);
  });

  it('falls back to the raw text when the body is not JSON at all', async () => {
    mockFetchOnce(500, 'Internal Server Error', false);
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('Internal Server Error');
  });
});
