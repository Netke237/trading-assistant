import {
  runStockScan, stockPositionCardKey, stockScanFailureReason,
  STOCK_SCAN_SETTINGS_INVALID, SCAN_RISK_ZERO_MESSAGE,
} from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import { useRiskStore } from '@/lib/riskStore';
import { useScanParamsStore, NO_OVERRIDES } from '@/lib/scanParamsStore';
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

  it('keeps a newer still-running scan untouched by an older failure', async () => {
    let rejectFirst!: (error: Error) => void;
    (api.postStockScan as jest.Mock)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }))
      .mockImplementationOnce(() => new Promise(() => {}));
    const first = runStockScan('pullback_ema');
    void runStockScan('ma_crossover');
    rejectFirst(new Error('API /api/stock-scan → 422: run one'));
    expect(await first).toBeNull();
    expect(useScanStore.getState().stockScanError).toBeNull();
    expect(useScanStore.getState().scanState).toBe('SCANNING');
    expect(useScanStore.getState().activeStrategy).toBe('ma_crossover');
  });

  it('keeps the newest completed result and paired request when an older run fails last', async () => {
    let rejectFirst!: (error: Error) => void;
    (api.postStockScan as jest.Mock)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }))
      .mockResolvedValueOnce({ scan_id: 'S-2', timestamp: 't', rejected: [], candidates: [] });
    const first = runStockScan('pullback_ema');
    await runStockScan('ma_crossover');
    rejectFirst(new Error('API /api/stock-scan → 500: run one'));
    await first;
    expect(useScanStore.getState().scanState).toBe('COMPLETED');
    expect(useScanStore.getState().stockScanError).toBeNull();
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('S-2');
    expect(useScanStore.getState().stockScanRequest?.strategy).toBe('ma_crossover');
  });

  it('never applies superseded-run metadata when newer metadata requests failed', async () => {
    // "Latest issued wins" discarded a good response whenever a later request
    // failed, leaving the meta at neither run's answer — the staleness the
    // refresh exists to prevent, on exactly the flaky backends where it
    // matters.
    //
    // All three requests must be IN FLIGHT TOGETHER. A fixture that lets each
    // rejection settle before the next run is issued cannot tell the two
    // implementations apart: handing a token back one step per rejection
    // restores it in full when the rejections are sequential, so that version
    // passes too. Deferred rejectors, settled only once all three runs are
    // issued, is what discriminates.
    (api.postStockScan as jest.Mock).mockResolvedValue(
      { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] },
    );
    const pending: Array<{ resolve: (v: unknown) => void; reject: (e: unknown) => void }> = [];
    (api.getLastStockScanStatus as jest.Mock).mockImplementation(
      () => new Promise((resolve, reject) => { pending.push({ resolve, reject }); }),
    );

    await runStockScan('pullback_ema');    // issues refresh #1
    await runStockScan('ma_crossover');    // #2
    await runStockScan('breakout_base');   // #3
    expect(pending).toHaveLength(3);

    pending[1]!.reject(new Error('boom'));
    pending[2]!.reject(new Error('boom again'));
    await Promise.resolve();
    await Promise.resolve();
    pending[0]!.resolve({ status: 'completed', updated_at: null, strategy: 'pullback_ema' });
    await Promise.resolve();
    await Promise.resolve();

    expect(useScanStore.getState().lastStockScanStatus).not.toBe('completed');
    expect(useScanStore.getState().lastStockScanStrategy).not.toBe('pullback_ema');
  });

  it('still reaches FAILED when the reason write is what threw', async () => {
    // The store writes in the catch are guarded ONE EACH, not as a pair:
    // zustand applies the in-memory update and then writes storage, so a
    // QuotaExceededError out of the first write would skip the second — and
    // the second is what re-enables the Run button. Nothing pinned this split
    // before; a single try around both passed the whole suite.
    (api.postStockScan as jest.Mock).mockRejectedValue(new Error('API /api/stock-scan → 500: boom'));
    // Swapped through setState, not jest.spyOn: zustand copies the current
    // state object's methods into the next one, so a spy survives its own
    // mockRestore() (which writes the original back onto the OLD object) and
    // leaks a throwing store write into every later case.
    const original = useScanStore.getState().setStockScanError;
    useScanStore.setState(
      { setStockScanError: () => { throw new Error('QuotaExceededError'); } } as never,
    );

    try {
      await runStockScan('pullback_ema');
      expect(useScanStore.getState().scanState).toBe('FAILED');
    } finally {
      useScanStore.setState({ setStockScanError: original } as never);
    }
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
    // STOCKS-HORIZON-T1 H5: the multi fields are overrides (null = follow the
    // backend profile, not sent); set them so the forwarding is observable.
    useScanParamsStore.setState({
      meanReversionVariants: ['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily'],
      meanReversionMinConfirm: 2, vwapLookback: 20, vwapDeviationPct: 0.02,
    });

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
    useScanParamsStore.setState({ ...NO_OVERRIDES });
  });

  describe('a throw while building the request (moved from Step 5, A5d)', () => {
    let consoleError: jest.SpyInstance;
    beforeEach(() => { consoleError = jest.spyOn(console, 'error').mockImplementation(() => {}); });
    afterEach(() => consoleError.mockRestore());

    it('confidenceGate: null stores the settings message, posts nothing, logs once', async () => {
      useSettingsStore.setState({ confidenceGate: null } as never);
      expect(await runStockScan('breakout_base')).toBeNull();
      expect(api.postStockScan).not.toHaveBeenCalled();
      expect(useScanStore.getState().stockScanError).toBe(STOCK_SCAN_SETTINGS_INVALID);
      expect(useScanStore.getState().scanState).toBe('FAILED');
      expect(consoleError).toHaveBeenCalledTimes(1);
      expect(consoleError.mock.calls[0][0]).toBe('runStockScan: building the stock-scan request failed');
      expect(consoleError.mock.calls[0][1]).toBeInstanceOf(TypeError);
    });

    it('a malformed non-null gate { enabled: true } gets the same message', async () => {
      useSettingsStore.setState({ confidenceGate: { enabled: true } } as never);
      await runStockScan('breakout_base');
      expect(useScanStore.getState().stockScanError).toBe(STOCK_SCAN_SETTINGS_INVALID);
    });

    it('a 0% max loss keeps its own message and is not logged', async () => {
      // Restore the store's real value (riskStore's DEFAULT_LIMITS, 0.0375),
      // read before the change rather than guessed.
      const priorMaxLoss = useRiskStore.getState().limits.maxLossPerTradePct;
      useRiskStore.setState((s) => ({ limits: { ...s.limits, maxLossPerTradePct: 0 } }));
      try {
        await runStockScan('breakout_base');
        expect(useScanStore.getState().stockScanError).toBe(SCAN_RISK_ZERO_MESSAGE);
        expect(consoleError).not.toHaveBeenCalled();
      } finally {
        useRiskStore.setState((s) => ({ limits: { ...s.limits, maxLossPerTradePct: priorMaxLoss } }));
      }
    });

    it('a store write failing BEFORE the build keeps its own text, not the settings message', async () => {
      const original = useScanStore.getState().setStockScanResult;
      useScanStore.setState({ setStockScanResult: () => { throw new Error('QuotaExceededError'); } } as never);
      try {
        await runStockScan('breakout_base');
        expect(useScanStore.getState().stockScanError).toBe('QuotaExceededError');
        expect(consoleError).not.toHaveBeenCalled();
      } finally {
        useScanStore.setState({ setStockScanResult: original } as never);
      }
    });

    it('an invalid strategy override reports the specific validation message instead of broad reset guidance', async () => {
      useScanParamsStore.setState({ pullbackTolerancePct: 0 });
      await runStockScan('pullback_ema');
      expect(useScanStore.getState().stockScanError).toContain('Pullback tolerance must be greater than 0%');
      expect(consoleError).not.toHaveBeenCalled();
    });
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
    // `instanceof Error` is realm-bound exactly as `instanceof TypeError` is,
    // so an error from an iframe, a vm context or a fetch polyfill built
    // elsewhere used to lose BOTH its message and the hint. A plain object
    // stands in for it: it passes no `instanceof` check at all.
    const foreign = { name: 'TypeError', message: 'Failed to fetch' };
    expect(stockScanFailureReason(foreign))
      .toBe('Failed to fetch (could not reach the backend at http://localhost:8000)');
  });

  it('reads a cause that is not an Error', () => {
    // `cause` is unconstrained by spec — a string or `{ code }` is common.
    expect(stockScanFailureReason(new TypeError('fetch failed', { cause: 'ECONNREFUSED' })))
      .toBe('fetch failed — ECONNREFUSED (could not reach the backend at http://localhost:8000)');
    expect(stockScanFailureReason(new TypeError('fetch failed', { cause: { code: 'ENOTFOUND' } })))
      .toBe('fetch failed — ENOTFOUND (could not reach the backend at http://localhost:8000)');
  });

  it('does not compose a dangling dash when only the cause has text', () => {
    expect(stockScanFailureReason(new Error('', { cause: new Error('ECONNREFUSED') })))
      .toBe('ECONNREFUSED');
  });

  it("keeps a detail that merely mentions markup", () => {
    // The probe is anchored: an unanchored one threw away every detail that
    // CONTAINED a tag — including the backend explaining that a symbol column
    // must not contain one.
    expect(stockScanFailureReason(new Error('API /api/stock-scan → 422: symbol must not contain <html> tags')))
      .toBe('API /api/stock-scan → 422: symbol must not contain <html> tags');
  });

  it('substitutes a non-HTML markup error page too', () => {
    // A load balancer's XML body and a bare fragment are the same problem as
    // the nginx page; enumerating HTML tag names missed both.
    expect(stockScanFailureReason(new Error(`API /api/stock-scan → 502: <?xml version="1.0"?><Error><Code>Timeout</Code>${'z'.repeat(400)}`)))
      .toBe('API /api/stock-scan → 502: the server returned an error page, not JSON');
    expect(stockScanFailureReason(new Error('API /api/stock-scan → 502: <h1>502 Bad Gateway</h1>')))
      .toBe('API /api/stock-scan → 502: the server returned an error page, not JSON');
  });

  it('does not mistake a front-end chunk-load failure for an unreachable backend', () => {
    // webpack/Next.js raise this TypeError for a stale asset, not the API host.
    expect(stockScanFailureReason(new TypeError(
      'Failed to fetch dynamically imported module: https://app.example/_next/chunk.js',
    ))).toBe('Failed to fetch dynamically imported module: https://app.example/_next/chunk.js');
  });

  it('does not mistake our own TypeError that merely contains a network word', () => {
    // Word boundaries did not close this: `\bnetwork\s?error\b` still matches
    // the identifier in `api.networkError is not a function`, because the dot
    // before it is a boundary. The whole message has to be the engine's, not
    // contain it.
    expect(stockScanFailureReason(new TypeError('api.networkError is not a function')))
      .toBe('api.networkError is not a function');
    expect(stockScanFailureReason(new TypeError("Cannot read properties of undefined (reading 'networkError')")))
      .toBe("Cannot read properties of undefined (reading 'networkError')");
  });

  it("recognises each engine's own wording for a request that got no response", () => {
    for (const message of [
      'Failed to fetch',                                   // Chrome / WebKit
      'fetch failed',                                      // undici
      'Load failed',                                       // Safari
      'NetworkError when attempting to fetch resource.',   // Firefox
    ]) {
      expect(stockScanFailureReason(new TypeError(message)))
        .toContain('(could not reach the backend at http://localhost:8000)');
    }
  });

  it('never cuts a clamped reason mid-character', () => {
    // The emoji has to STRADDLE the cut or this proves nothing. The head is 27
    // characters and the clamp keeps 199, so 171 filler characters put the
    // emoji at UTF-16 units 198–199: a UTF-16 slice(0, 199) keeps its high
    // surrogate alone, which renders as the replacement character. A
    // code-point slice keeps the whole emoji or drops it whole.
    const head = 'API /api/stock-scan → 500: ';
    expect(head).toHaveLength(27);
    const out = stockScanFailureReason(new Error(`${head}${'a'.repeat(171)}😀tail`));

    expect(out.endsWith('…')).toBe(true);
    expect(out).toContain('😀');
    expect(/[\uD800-\uDBFF]$/.test(out.slice(0, -1))).toBe(false);
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

  it('replaces a markup error page with the status line rather than 200 chars of it', () => {
    // apiError() falls back to the raw response text, so a proxy's 502 page
    // arrives as the detail. Clamping it alone still put markup in front of
    // the user; only the status line means anything to them.
    const html = `API /api/stock-scan → 502: <html>\n  <head><title>502 Bad Gateway</title></head>\n  <body>${'x'.repeat(500)}</body>\n</html>`;
    expect(stockScanFailureReason(new Error(html)))
      .toBe('API /api/stock-scan → 502: the server returned an error page, not JSON');
  });

  it('collapses and clamps a long multi-line plain-text detail', () => {
    // Real newlines and tabs in the fixture — the previous version built its
    // input from a repeated single-line string, so the "collapses" half of the
    // name held vacuously and dropping oneLine() would not have failed it.
    const out = stockScanFailureReason(new Error(
      `API /api/stock-scan → 500: traceback:\n\tline one\n\tline two ${'boom '.repeat(200)}`,
    ));
    expect(out.length).toBeLessThanOrEqual(200);
    expect(out.endsWith('…')).toBe(true);
    expect(out).not.toMatch(/[\n\t]/);
    expect(out).toContain('traceback: line one line two');
  });

  it('clamps the detail but never the hint', () => {
    // Clamping the composed string kept 200 chars of "Failed to fetch xxxxx…"
    // and truncated the hint away — the actionable half of the message.
    // A long undici `cause` (a TLS chain, a multi-address ECONNREFUSED) is the
    // real shape here: the engine's own message is short, the detail after it
    // is not.
    const out = stockScanFailureReason(
      new TypeError('fetch failed', { cause: new Error(`connect ECONNREFUSED ${'1.2.3.4:8000, '.repeat(40)}`) }),
    );
    expect(out.length).toBeLessThanOrEqual(200);
    expect(out).toContain('(could not reach the backend at http://localhost:8000)');
    expect(out).toContain('…');
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
