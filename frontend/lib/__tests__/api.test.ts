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

// MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25). The UI tests for the four manual
// send paths reject the order call with a hand-written message; this pins that
// the REAL parse of the backend's 502 produces that shape, question included.
describe('manual broker order — IBKR confirmation question (502)', () => {
  const DETAIL =
    'IBKR did not place the order: it asked for a confirmation this app does not send. ' +
    'IBKR said: Are you sure you want to submit this order?';

  it('postStockOrder rejects with the status and the question', async () => {
    mockFetchOnce(502, { detail: DETAIL });
    await expect(api.postStockOrder({
      broker: 'ibkr_paper', symbol: 'AAPL', action: 'BUY', effect: 'OPEN', quantity: 1,
      order_type: 'LMT', limit_price: 150, tif: 'DAY',
    })).rejects.toThrow(`API /broker/stock-order → 502: ${DETAIL}`);
  });

  it('postOptionOrder rejects with the status and the question', async () => {
    mockFetchOnce(502, { detail: DETAIL });
    await expect(api.postOptionOrder({
      broker: 'ibkr_paper', symbol: 'AAPL', option_symbol: 'AAPL251017C00185000',
      action: 'BUY', effect: 'OPEN', quantity: 1, order_type: 'LMT', limit_price: 2.5, tif: 'DAY',
    })).rejects.toThrow(`API /broker/option-order → 502: ${DETAIL}`);
  });
});

// P1b-i -- the rec_id is client-generated and goes into the PATH, so it is
// URL-encoded, and the call is a DELETE whose non-2xx throws `→ NNN` (Step 7
// reads a `→ 404` as "already gone" on some notes).
describe('deletePortfolioPosition', () => {
  it('DELETEs the URL-encoded rec_id', async () => {
    const f = jest.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = f as unknown as typeof fetch;
    await api.deletePortfolioPosition('REC-1/a b');
    expect(f).toHaveBeenCalledWith('http://localhost:8000/api/portfolio/REC-1%2Fa%20b', { method: 'DELETE' });
  });

  it('throws `→ 404` when the row does not exist', async () => {
    mockFetchOnce(404, { detail: 'Position not found' });
    await expect(api.deletePortfolioPosition('REC-1')).rejects.toThrow('API /api/portfolio/REC-1 → 404: Position not found');
  });
});

// Step 6 sends the scan's recorded contract rules as one JSON query parameter;
// an empty or absent rule set sends nothing (the backend reads that as the YAML).
describe('getContracts contract_rules', () => {
  function mockOk() {
    const f = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    global.fetch = f as unknown as typeof fetch;
    return f;
  }

  it('sends the rules URL-encoded as JSON', async () => {
    const f = mockOk();
    await api.getContracts('XOM', 'C', { contract_rules: { min_volume: 20, max_bid_ask_spread_pct: 0.3 } });
    const url = new URL(f.mock.calls[0][0]);
    expect(JSON.parse(url.searchParams.get('contract_rules') as string))
      .toEqual({ min_volume: 20, max_bid_ask_spread_pct: 0.3 });
  });

  it('sends nothing for an empty or absent rule set', async () => {
    const f = mockOk();
    await api.getContracts('XOM', 'C', { contract_rules: {} });
    await api.getContracts('XOM', 'C', {});
    for (const [u] of f.mock.calls) expect(u).not.toContain('contract_rules');
  });
});

describe('watched contracts — grading on the wire (WATCHLIST-SCAN-CONTRACT-RULES)', () => {
  function mockOk(body: unknown = []) {
    const f = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body });
    global.fetch = f as unknown as typeof fetch;
    return f;
  }
  const bodyOf = (f: jest.Mock) => JSON.parse(f.mock.calls[0][1].body as string);

  it('addWatchedContract(id, null) sends "grading": null (clears a stale server grading)', async () => {
    const f = mockOk({ contract_id: 'X' });
    await api.addWatchedContract('XOM|190|2026-12-18|C', null);
    expect(bodyOf(f)).toEqual({ contract_id: 'XOM|190|2026-12-18|C', grading: null });
    expect(f.mock.calls[0][1].body).toContain('"grading":null');
  });

  it('addWatchedContract(id) sends no grading key', async () => {
    const f = mockOk({ contract_id: 'X' });
    await api.addWatchedContract('XOM|190|2026-12-18|C');
    expect(bodyOf(f)).toEqual({ contract_id: 'XOM|190|2026-12-18|C' });
    expect('grading' in bodyOf(f)).toBe(false);
  });

  it('addWatchedContract(id, g) sends the grading', async () => {
    const f = mockOk({ contract_id: 'X' });
    const g = { contract_rules: {}, hold_min_days: 20, hold_max_days: 25, stock_score: 72 };
    await api.addWatchedContract('XOM|190|2026-12-18|C', g);
    expect(bodyOf(f).grading).toEqual(g);
  });

  it('getContracts sends expiry and strikes exactly as the backend parses them', async () => {
    const f = mockOk();
    await api.getContracts('XOM', 'C', { expiry: '2026-12-18', strikes: [187, 190] });
    const u = f.mock.calls[0][0] as string;
    expect(u).toContain('&expiry=2026-12-18');
    expect(u).toContain('&strikes=187%2C190');
  });

  it('getContracts omits an empty strike list and an absent expiry', async () => {
    const f = mockOk();
    await api.getContracts('XOM', 'C', { strikes: [] });
    const u = f.mock.calls[0][0] as string;
    expect(u).not.toContain('strikes');
    expect(u).not.toContain('expiry');
  });
});


describe('original backtest client', () => {
  it('sends the opaque ID and exact symbol with cancellation', async () => {
    const artifact = {schema_version:1, artifact_id:'opaque'};
    global.fetch = jest.fn().mockResolvedValue({ok:true,json:async () => artifact});
    const signal = new AbortController().signal;
    await expect(api.getOriginalBacktest('opaque/id','BRK.B',signal)).resolves.toEqual(artifact);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/backtest-artifacts/opaque%2Fid?symbol=BRK.B'), {signal});
  });
  it.each([[404,'missing'],[410,'expired'],[422,'invalid_input'],[503,'storage_unavailable'],[500,'failed']])('retains HTTP %s as %s', async (status, reason) => {
    mockFetchOnce(status as number, {detail:'error'});
    await expect(api.getOriginalBacktest('id','AAA')).rejects.toMatchObject({status,reason});
  });
});
