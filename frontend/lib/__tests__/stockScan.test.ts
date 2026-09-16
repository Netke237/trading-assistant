import { runStockScan, stockPositionCardKey, stockScanFailureReason } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: { postStockScan: jest.fn(), getLastStockScanStatus: jest.fn() },
  API_BASE_URL: 'http://localhost:8000',
}));

describe('runStockScan', () => {
  beforeEach(() => {
    (api.postStockScan as jest.Mock).mockReset();
    (api.getLastStockScanStatus as jest.Mock).mockReset();
    (api.getLastStockScanStatus as jest.Mock).mockResolvedValue(
      { status: 'idle', updated_at: null, strategy: null },
    );
    useScanStore.setState({
      context: { universe: 'NAS100', direction: 'Bullish', horizon: 'Swing (5–15d)' },
      scanOverrides: {},
      stockScanResult: null,
      previousStockScanResult: null,
      activeStrategy: null,
      scanState: 'IDLE',
      stockScanError: null,
    } as any);
    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
  });

  it('calls postStockScan with the strategy + universe and stores the result', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    expect(api.postStockScan).toHaveBeenCalledTimes(1);
    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.strategy).toBe('pullback_ema');
    expect(arg.universe).toEqual(['NAS100']);
    expect(arg.direction).toBe('Bullish');
    expect(arg.horizon).toBe('Swing');
    expect(useScanStore.getState().stockScanResult).toEqual(fake);
    expect(useScanStore.getState().activeStrategy).toBe('pullback_ema');
  });

  it('sets scanState FAILED when the API throws', async () => {
    (api.postStockScan as jest.Mock).mockRejectedValue(new Error('boom'));
    await runStockScan('pullback_ema');
    expect(useScanStore.getState().scanState).toBe('FAILED');
  });

  it("parks the backend's own reason in stockScanError when the request is rejected", async () => {
    // The defect this closes: the catch swallowed the error entirely, so a 422
    // telling the user exactly which parameter the backend refused surfaced as
    // "is the backend running on port 8000?" — pointing at a backend that was
    // running and had just answered.
    (api.postStockScan as jest.Mock).mockRejectedValue(
      new Error('API /api/stock-scan → 422: rsi_oversold must be < 50'),
    );

    await runStockScan('pullback_ema');

    expect(useScanStore.getState().stockScanError)
      .toBe('API /api/stock-scan → 422: rsi_oversold must be < 50');
  });

  it('keeps the backend-unreachable hint for a transport failure', async () => {
    (api.postStockScan as jest.Mock).mockRejectedValue(new TypeError('Failed to fetch'));

    await runStockScan('pullback_ema');

    expect(useScanStore.getState().stockScanError)
      .toBe('Failed to fetch (could not reach the backend at http://localhost:8000)');
  });

  it('has the reason readable the moment it resolves, even while the status refresh hangs', async () => {
    // The ordering this whole design rests on, and the one the call sites'
    // own tests cannot see because they mock runStockScan out. The last-run
    // status refresh used to be AWAITED in the finally: the reason was
    // unreadable until that second round trip finished, and a backend that
    // accepts the socket then hangs — modelled here by a promise that never
    // settles — meant it never became readable at all.
    (api.postStockScan as jest.Mock).mockRejectedValue(
      new Error('API /api/stock-scan → 500: scorer blew up'),
    );
    (api.getLastStockScanStatus as jest.Mock).mockReturnValue(new Promise(() => {}));

    await runStockScan('pullback_ema');

    expect(useScanStore.getState().scanState).toBe('FAILED');
    expect(useScanStore.getState().stockScanError).toBe('API /api/stock-scan → 500: scorer blew up');
  });

  it("a concurrent run cannot steal the earlier run's reason before its caller reads it", async () => {
    // The impatient re-click: run 2 starts (clearing stockScanError
    // synchronously) while run 1's request is still in flight. Run 1's reason
    // must still be what its own caller reads when it resolves. Distinct
    // rejections on purpose — with the same text on both, this assertion
    // cannot tell whose reason it got.
    let rejectFirst: (e: Error) => void = () => {};
    (api.postStockScan as jest.Mock)
      .mockImplementationOnce(() => new Promise((_res, rej) => { rejectFirst = rej; }))
      .mockImplementationOnce(() => new Promise(() => {}));   // run 2 never settles

    const first = runStockScan('pullback_ema');
    const second = runStockScan('pullback_ema');              // the re-click
    expect(useScanStore.getState().stockScanError).toBeNull();   // run 2 cleared it

    rejectFirst(new Error('API /api/stock-scan → 422: run one'));
    await first;

    expect(useScanStore.getState().stockScanError).toBe('API /api/stock-scan → 422: run one');
    void second;
  });

  it('does not let an earlier run\'s last-run status overwrite a later one', async () => {
    // The status refresh is fire-and-forget now, so two overlapping runs have
    // two responses in flight with no ordering of their own — and run 1's
    // landing last would pin TopBar/Settings to the older scan, the staleness
    // the refresh exists to prevent.
    (api.postStockScan as jest.Mock).mockResolvedValue(
      { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] },
    );
    let releaseFirst: (v: unknown) => void = () => {};
    (api.getLastStockScanStatus as jest.Mock)
      .mockImplementationOnce(() => new Promise((resolve) => { releaseFirst = resolve; }))
      .mockResolvedValue({ status: 'completed', updated_at: null, strategy: 'ma_crossover' });

    await runStockScan('pullback_ema');    // run 1 — status still pending
    await runStockScan('ma_crossover');    // run 2 — status resolves
    releaseFirst({ status: 'idle', updated_at: null, strategy: 'pullback_ema' });
    await Promise.resolve();
    await Promise.resolve();

    expect(useScanStore.getState().lastStockScanStatus).toBe('completed');
    expect(useScanStore.getState().lastStockScanStrategy).toBe('ma_crossover');
  });

  it('clears a previous failure reason on the next run, including one that succeeds', async () => {
    (api.postStockScan as jest.Mock).mockRejectedValue(new Error('API /api/stock-scan → 500: boom'));
    await runStockScan('pullback_ema');
    expect(useScanStore.getState().stockScanError).not.toBeNull();

    (api.postStockScan as jest.Mock).mockResolvedValue(
      { scan_id: 'S-2', timestamp: 't', rejected: [], candidates: [] },
    );
    await runStockScan('pullback_ema');

    // A stale reason left here would caption the NEXT failure — or, read by a
    // caller that only checks a null return, the next success.
    expect(useScanStore.getState().stockScanError).toBeNull();
  });

  it('sends the full Settings default ATR pair for this horizon when no override is set', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(3.0); // swing default
    expect(arg.confidence_atr_mult_stop).toBe(1.5);
  });

  it('ignores a lone confidence_atr_mult_target override (without a stop) rather than sending a mismatched pair', async () => {
    // Regression: resolving target/stop independently would send the lone
    // override's target paired with the Settings default's stop, silently
    // producing a pair the user never actually configured together and
    // bypassing the backend's both-or-neither guard (which only nulls a pair
    // when it receives an explicit None on one side, not two valid numbers).
    useScanStore.setState({ scanOverrides: { confidence_atr_mult_target: 4.0 } } as any);
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(3.0); // full fallback to swing default, not 4.0
    expect(arg.confidence_atr_mult_stop).toBe(1.5);
  });

  it('uses both override values together when both target and stop are set', async () => {
    useScanStore.setState({
      scanOverrides: { confidence_atr_mult_target: 4.0, confidence_atr_mult_stop: 2.0 },
    } as any);
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(4.0);
    expect(arg.confidence_atr_mult_stop).toBe(2.0);
  });

  it('forwards mean-reversion-multi params only when that strategy is selected (H4)', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('mean_reversion_multi');
    const multiArg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(multiArg.mean_reversion_variants).toEqual(
      expect.arrayContaining(['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily'])
    );
    expect(multiArg.mean_reversion_min_confirmations).toBe(2);
    expect(multiArg.vwap_lookback).toBe(20);
    expect(multiArg.vwap_deviation_pct).toBe(0.02);

    (api.postStockScan as jest.Mock).mockClear();
    await runStockScan('pullback_ema');
    const singleArg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(singleArg.mean_reversion_variants).toBeUndefined();
    expect(singleArg.mean_reversion_min_confirmations).toBeUndefined();
  });
});

describe('stockPositionCardKey', () => {
  function card(overrides: Partial<{ symbol: string; entry: number; stop: number; target: number; targets: number[] }> = {}): PositionCardData {
    const { symbol = 'AAPL', entry = 150, stop = 145, target = 160, targets } = overrides;
    return {
      symbol,
      strategy: {
        entry_price: entry, stop_price: stop, target_price: target,
        ...(targets ? { targets } : {}),
      } as PositionCardData['strategy'],
    } as PositionCardData;
  }

  it('changes when the signal changes for the same symbol', () => {
    // The exact scenario an adversarial audit round found: a card stays open
    // (openSymbol) across a same-symbol Run Scan, so the key must change
    // whenever the recomputed signal actually differs, or React reuses the
    // component and its overlay state goes stale.
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ entry: 152 }));
    expect(before).not.toBe(after);
  });

  it('stays the same when the signal is unchanged, even across re-renders', () => {
    expect(stockPositionCardKey(card())).toBe(stockPositionCardKey(card()));
  });

  it('differs by symbol alone when entry/stop/target coincide', () => {
    expect(stockPositionCardKey(card({ symbol: 'AAPL' })))
      .not.toBe(stockPositionCardKey(card({ symbol: 'MSFT' })));
  });

  it('changes when only the stop moves', () => {
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ stop: 143 }));
    expect(before).not.toBe(after);
  });

  it('changes when only the target moves', () => {
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ target: 165 }));
    expect(before).not.toBe(after);
  });

  it('changes when T2/T3 change even though entry/stop/target[0] are identical', () => {
    // A third independent audit round's exact repro: resolve_multi_signal can
    // return the same entry/stop/targets[0] across two scans (e.g. a
    // re-scan that adds a third confirming variant whose own rung is
    // farther than the already-tightest one) while targets[1]/[2] differ.
    // Keying on target_price alone (== targets[0]) would miss this and leave
    // the card un-remounted with a stale T2/T3.
    const before = stockPositionCardKey(card({ target: 103, targets: [103.0, 106.0] }));
    const after  = stockPositionCardKey(card({ target: 103, targets: [103.0, 106.0, 110.0] }));
    expect(before).not.toBe(after);
  });

  it('falls back to target_price when targets is absent or empty, matching defaultOverlay()', () => {
    // `?.length`, not `??` — an empty array must fall back too, same
    // convention StockPositionCard's defaultOverlay() already follows.
    const absent = stockPositionCardKey(card({ target: 160 }));
    const empty  = stockPositionCardKey(card({ target: 160, targets: [] }));
    const single = stockPositionCardKey(card({ target: 160, targets: [160] }));
    expect(absent).toBe(empty);
    expect(absent).toBe(single);
  });
});

describe('stockScanFailureReason', () => {
  it('passes an api.ts-formatted error through untouched', () => {
    expect(stockScanFailureReason(new Error('API /api/stock-scan → 500: boom')))
      .toBe('API /api/stock-scan → 500: boom');
  });

  it('appends the backend hint to a fetch transport failure, naming the real base URL', () => {
    expect(stockScanFailureReason(new TypeError('Failed to fetch')))
      .toBe('Failed to fetch (could not reach the backend at http://localhost:8000)');
  });

  it('withholds the hint from a TypeError that is our own broken code, not a transport failure', () => {
    // The shape that shipped in round 1 of this file's audit: a partially
    // mocked api module rejects with `api.postStockScan is not a function`,
    // a TypeError — and the user was told to go check their backend.
    expect(stockScanFailureReason(new TypeError('api.postStockScan is not a function')))
      .toBe('api.postStockScan is not a function');
  });

  it('recognises a transport failure from another realm', () => {
    // `instanceof TypeError` is realm-bound: an error from an iframe or a
    // fetch polyfill built in another context fails it and the hint silently
    // stops appearing. Matched on `name` instead.
    const foreign = new Error('Failed to fetch');
    foreign.name = 'TypeError';
    expect(stockScanFailureReason(foreign))
      .toBe('Failed to fetch (could not reach the backend at http://localhost:8000)');
  });

  it("surfaces undici's cause, where the real transport error hides", () => {
    // Node/undici rejects with a bare "fetch failed" and puts ECONNREFUSED in
    // `cause` — the only part that actually explains anything.
    const err = new TypeError('fetch failed', { cause: new Error('connect ECONNREFUSED 127.0.0.1:8000') });
    expect(stockScanFailureReason(err)).toBe(
      'fetch failed — connect ECONNREFUSED 127.0.0.1:8000 (could not reach the backend at http://localhost:8000)',
    );
  });

  it('does NOT claim the backend is unreachable for an error that proves it answered', () => {
    // A 200 whose body is not JSON throws a SyntaxError out of res.json().
    // The backend plainly answered, so repeating "is the backend reachable?"
    // here would be the same misdirection this change exists to remove.
    expect(stockScanFailureReason(new SyntaxError('Unexpected token < in JSON at position 0')))
      .toBe('Unexpected token < in JSON at position 0');
    expect(stockScanFailureReason('socket hang up')).toBe('socket hang up');
  });

  it('withholds the hint from a TypeError thrown before the request was sent', () => {
    // Our own request-building code throwing a TypeError must not borrow the
    // network hint — nothing was ever sent, so the backend is not the suspect.
    expect(stockScanFailureReason(new TypeError("Cannot read properties of undefined (reading 'swing')"), false))
      .toBe("Cannot read properties of undefined (reading 'swing')");
  });

  it('replaces an HTML error page with the status line rather than 200 chars of markup', () => {
    // apiError() falls back to the raw response text, so a proxy's 502 page
    // arrives as the detail. Clamping it alone still put markup in front of
    // the user; only the status line means anything to them.
    const html = `API /api/stock-scan → 502: <html>\n  <head><title>502 Bad Gateway</title></head>\n  <body>${'x'.repeat(500)}</body>\n</html>`;
    expect(stockScanFailureReason(new Error(html)))
      .toBe('API /api/stock-scan → 502: the server returned an HTML error page');
  });

  it('collapses and clamps a long plain-text detail', () => {
    const out = stockScanFailureReason(new Error(`API /api/stock-scan → 500: ${'boom '.repeat(200)}`));
    expect(out).toHaveLength(200);
    expect(out.endsWith('…')).toBe(true);
    expect(out).not.toContain('\n');
  });

  it('clamps the composed string, hint included', () => {
    // Clamping only the raw message let a long one plus the hint compose well
    // past MAX_REASON_CHARS — the overflow the clamp exists for.
    const out = stockScanFailureReason(new TypeError(`Failed to fetch ${'x'.repeat(400)}`));
    expect(out.length).toBeLessThanOrEqual(200);
  });

  it('never renders an empty reason', () => {
    // `throw new Error()` and `throw undefined` both reach here with nothing
    // to show; an empty string would render as a dangling "Scan failed — ".
    expect(stockScanFailureReason(new Error(''))).toBe('unknown error');
    expect(stockScanFailureReason(undefined)).toBe('unknown error');
    // An empty TypeError is not a recognisable transport failure either, so it
    // gets no hint — it gets the honest fallback.
    expect(stockScanFailureReason(new TypeError(''))).toBe('unknown error');
  });
});
