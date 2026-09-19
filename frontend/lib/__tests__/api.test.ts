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
  it('prefixes each Pydantic validation message with the field it came from', async () => {
    // ROUND 1 finding 8 changed this contract, and this fixture is the argument
    // for it: TWO fields fail with the IDENTICAL message, so the msg-only format
    // this test used to pin rendered as
    //   "Input should be greater than 0; Input should be greater than 0"
    // — the same sentence twice, naming neither field. Useless to the operator
    // reading it, and indistinguishable from a single duplicated error.
    //
    // The 'body' frame is stripped because it is constant noise in a UI string.
    mockFetchOnce(422, {
      detail: [
        { loc: ['body', 'strike'], msg: 'Input should be greater than 0', type: 'greater_than' },
        { loc: ['body', 'premium'], msg: 'Input should be greater than 0', type: 'greater_than' },
      ],
    });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow(
      'strike: Input should be greater than 0; premium: Input should be greater than 0',
    );
  });

  it('strips only the LEADING frame, so a field genuinely named "body" survives', async () => {
    // ROUND 2 finding 1. The first version of this filter dropped 'body' and
    // 'query' at EVERY depth, and this app has a field literally named `body`:
    // NoteIn (backend/app/routers/symbol_notes.py), posted to by api.ts's
    // updateSymbolNote. A 422 there returns loc ["body","body"], the blanket
    // filter ate both, and the operator got the bare "Field required" — exactly
    // the defect this prefixing exists to remove, on a live endpoint.
    mockFetchOnce(422, {
      detail: [{ loc: ['body', 'body'], msg: 'Field required', type: 'missing' }],
    });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('422: body: Field required');
  });

  it('strips every FastAPI frame, not just body and query', async () => {
    // Otherwise a path-param 422 renders as "path.symbol: ..." while a body one
    // renders as "symbol: ..." — the same rule applied two ways.
    mockFetchOnce(422, {
      detail: [{ loc: ['path', 'symbol'], msg: 'Input should be a valid string', type: 'string_type' }],
    });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('422: symbol: Input should be a valid string');
  });

  it('joins a nested loc into a dotted path', async () => {
    mockFetchOnce(422, {
      detail: [{ loc: ['body', 'targets', 0, 'targetPrice'], msg: 'Input should be greater than 0', type: 'greater_than' }],
    });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('targets.0.targetPrice: Input should be greater than 0');
  });

  it('falls back to the bare msg when loc carries no field path', async () => {
    // loc of just ['body'] strips to nothing — the prefix must be omitted
    // rather than rendered as an empty "': '".
    mockFetchOnce(422, { detail: [{ loc: ['body'], msg: 'malformed body', type: 'value_error' }] });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('422: malformed body');
  });

  it('handles a missing loc entirely', async () => {
    // Not every 422 shape carries loc; the prefix is additive, never required.
    mockFetchOnce(422, { detail: [{ msg: 'something failed', type: 'value_error' }] });
    await expect(api.getStockQuote('AAPL')).rejects.toThrow('422: something failed');
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
