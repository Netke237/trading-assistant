// Phase G piece 5, build step 2 — spec tests 11, 11b, 12 and 15, against the
// real store. Spec: docs/superpowers/plans/2026-09-14-phase-g-per-trade-method-pick-spec.md §10.
//
// The rules themselves are unit-tested in cardEdits.test.ts. What is tested
// HERE is the property the stamp buys: that no scan-landing site needs wiring.

import { act } from '@testing-library/react';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits, selectCardEdits } from '@/lib/cardEdits';
import type { CardEditMode } from '@/lib/cardEdits';
import type { MethodPick } from '@/types/domain';
import type { ScanResult } from '@/lib/scanStore';
import type { StockScanResult } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn().mockRejectedValue(new Error('offline')),
  },
}));
import { api } from '@/lib/api';
import { runStockScan } from '@/lib/stockScan';

const AAPL_190 = 'AAPL|190|2027-01-15|C';
const AAPL_200 = 'AAPL|200|2027-01-15|C';

const pick = (method: MethodPick['method'] = 'monte_carlo'): MethodPick => ({
  method, rowStockPrice: 197.5, rowOptionPrice: 6.24,
  stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

const optionsResult = (scanId: string): ScanResult =>
  ({ scan_id: scanId, timestamp: '2026-09-14T10:00:00', candidates: [], rejected: [] });

const stockResult = (scanId: string): StockScanResult =>
  ({ scan_id: scanId, timestamp: '2026-09-14T10:00:00', candidates: [], rejected: [] });

/** What the card actually reads. Never `getState().optionsCardEdits`. */
const readEdits = (mode: CardEditMode) => selectCardEdits(useScanStore.getState(), mode);

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  act(() => {
    useScanStore.setState({
      scanResult: null, previousRun: null,
      stockScanResult: null, previousStockScanResult: null,
      pickedContracts: {},
      optionsCardEdits: emptyCardEdits(),
      stocksCardEdits: emptyCardEdits(),
    });
  });
});

// ---------------------------------------------------------------------------
// TEST 11 — the pick survives a step-6 -> step-7 round trip, and does not
// survive a new scan. Per mode, and through each scan entry point.
// ---------------------------------------------------------------------------
describe('spec test 11 — a pick survives navigation, never a new scan', () => {
  it('survives a step-6 -> step-7 round trip (options)', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
      useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_190, 2.71);
    });
    // Navigating step 6 -> step 7 unmounts and remounts the page. Nothing about
    // the store changes, so the read is the whole assertion: the edits that used
    // to die with the page's useState hooks now outlive it.
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
    expect(readEdits('options').entryLimit[AAPL_190]).toBe(2.71);
  });

  // RunScanButton:154 — `setScanResult(result)` is the whole options entry point.
  it('does NOT survive a new options scan landing via setScanResult', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
    });
    expect(readEdits('options').picks[AAPL_190]).toBeDefined();

    act(() => { useScanStore.getState().setScanResult(optionsResult('B')); });
    expect(readEdits('options').picks).toEqual({});
    expect(readEdits('options').entryLimit).toEqual({});
  });

  // lib/stockScan.ts:100 — reached from BOTH RunScanButton:90 and
  // step-4-stocks/page.tsx:179. The real function is exercised, not its setter,
  // because §5.1 twice described this path wrongly.
  it('does NOT survive a new stock scan landing via runStockScan', async () => {
    (api.postStockScan as jest.Mock).mockResolvedValue(stockResult('stk-B'));
    act(() => {
      useScanStore.setState({ stockScanResult: stockResult('stk-A') });
      useScanStore.getState().setCardEdit('stocks', 'picks', 'AAPL', pick('arithmetic'));
    });
    expect(readEdits('stocks').picks.AAPL).toBeDefined();

    await act(async () => { await runStockScan('pullback_ema'); });
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('stk-B');
    expect(readEdits('stocks').picks).toEqual({});
  });

  // step-5-strategy/page.tsx:245 — calls api.postStockScan then
  // setStockScanResult directly, bypassing runStockScan entirely.
  it('does NOT survive a new stock scan landing via setStockScanResult', () => {
    act(() => {
      useScanStore.setState({ stockScanResult: stockResult('stk-A') });
      useScanStore.getState().setCardEdit('stocks', 'invalidation', 'AAPL', 180);
    });
    act(() => { useScanStore.getState().setStockScanResult(stockResult('stk-B')); });
    expect(readEdits('stocks').invalidation).toEqual({});
  });

  // THE PROPERTY, stated directly. The stamp is evaluated at READ time against
  // whatever result is in the store, so invalidation does not depend on going
  // through a setter at all. A future entry point that assigns the result by
  // any means — including a raw setState this test uses to stand in for one —
  // invalidates the slice for free. That is why no reset call is wired
  // anywhere, and why adding one would be the regression.
  it('does NOT survive a result that lands without using either setter', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'premiumStop', AAPL_190, 3.12);
    });
    act(() => { useScanStore.setState({ scanResult: optionsResult('C') }); });
    expect(readEdits('options').premiumStop).toEqual({});
  });

  // A write under the NEW scan must not land beside the old scan's edits.
  it('resets rather than merges when the next write follows a new scan', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_190, 2.71);
      useScanStore.setState({ scanResult: optionsResult('B') });
      useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_200, 6.00);
    });
    expect(readEdits('options').entryLimit).toEqual({ [AAPL_200]: 6.00 });
  });

  // zustand replaces the whole state object on ANY set, so a `toBe` on the state
  // itself proves no set happened -- not merely that the slice came back equal.
  // The step-7 card reports its whole overlay on every patch, so an unchanged
  // write that still churned state would re-render every bare subscriber on
  // every keystroke.
  it('an unchanged write does not touch the store at all', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_190, 2.71);
    });
    const before = useScanStore.getState();
    act(() => { useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_190, 2.71); });
    expect(useScanStore.getState()).toBe(before);

    // ...and a write with no scan to stamp it with is equally inert.
    act(() => { useScanStore.setState({ scanResult: null }); });
    const noScan = useScanStore.getState();
    act(() => { useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_200, 6.00); });
    expect(useScanStore.getState()).toBe(noScan);
  });

  it('a stocks scan does not disturb options edits, or the reverse', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A'), stockScanResult: stockResult('stk-A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
      useScanStore.getState().setCardEdit('stocks', 'picks', 'MSFT', pick('ladder'));
    });
    act(() => { useScanStore.getState().setStockScanResult(stockResult('stk-B')); });
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
    expect(readEdits('stocks').picks).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// TEST 11b — unreadable after a different scan_id lands; still readable after
// StoreHydration restores the SAME result.
// ---------------------------------------------------------------------------
describe('spec test 11b — restoration is not invalidation', () => {
  it('is not readable once a result with a different scan_id lands', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
      useScanStore.getState().setScanResult(optionsResult('B'));
    });
    expect(readEdits('options').picks[AAPL_190]).toBeUndefined();
    // The slice is still physically there — it is the STAMP that hides it, and
    // that is what makes the behaviour independent of any reset call.
    expect(useScanStore.getState().optionsCardEdits.picks[AAPL_190]).toBeDefined();
  });

  // The half that stops the design from wiping every pick on every page load.
  // StoreHydration (components/StoreHydration/index.tsx:55, :67) re-lands the
  // recovered result through the very same setters a new scan uses.
  it('IS still readable after StoreHydration re-lands the same result', () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
    });
    // Recovery path: the persisted result was absent, so a fresh copy of the
    // SAME scan arrives from GET /api/scan/last — a different object, same id.
    act(() => { useScanStore.getState().setScanResult(optionsResult('A')); });
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
  });

  it('IS still readable after the stocks recovery path re-lands the same result', () => {
    act(() => {
      useScanStore.setState({ stockScanResult: stockResult('stk-A') });
      useScanStore.getState().setCardEdit('stocks', 'maxLossOverride', 'AAPL', { mode: 'dollar', value: 250 });
    });
    act(() => { useScanStore.getState().setStockScanResult(stockResult('stk-A')); });
    expect(readEdits('stocks').maxLossOverride.AAPL).toEqual({ mode: 'dollar', value: 250 });
  });

  // End to end through the persist layer: written, reloaded, still readable.
  it('survives a real rehydrate when the restored result still matches', async () => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
    });
    const written = localStorage.getItem('bamendjou-scan-store');
    expect(written).toContain(AAPL_190);

    // Wipe the in-memory store to stand in for a page reload, then put the blob
    // back: `persist` re-writes localStorage on every setState, so clearing the
    // store would otherwise overwrite the very blob under test.
    act(() => {
      useScanStore.setState({ scanResult: null, optionsCardEdits: emptyCardEdits() });
    });
    localStorage.setItem('bamendjou-scan-store', written as string);
    await act(async () => { await useScanStore.persist.rehydrate(); });

    expect(useScanStore.getState().scanResult?.scan_id).toBe('A');
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
  });
});

// ---------------------------------------------------------------------------
// TEST 12 — switching the contract in step 6 clears the pick for the old one.
// ---------------------------------------------------------------------------
describe('spec test 12 — a contract switch drops the outgoing pick', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({ scanResult: optionsResult('A') });
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick());
    });
  });

  it('clears the old contract’s pick', () => {
    act(() => { useScanStore.getState().setPickedContract('AAPL', AAPL_200); });
    expect(readEdits('options').picks[AAPL_190]).toBeUndefined();
    expect(useScanStore.getState().pickedContracts.AAPL).toBe(AAPL_200);
  });

  it('keeps a pick already made for the INCOMING contract', () => {
    act(() => {
      useScanStore.getState().setCardEdit('options', 'picks', AAPL_200, pick('ladder'));
      useScanStore.getState().setPickedContract('AAPL', AAPL_200);
    });
    expect(readEdits('options').picks[AAPL_200]).toEqual(pick('ladder'));
    expect(readEdits('options').picks[AAPL_190]).toBeUndefined();
  });

  // Re-clicking the contract already on screen must not throw the pick away.
  it('is a no-op when the same contract is re-selected', () => {
    act(() => { useScanStore.getState().setPickedContract('AAPL', AAPL_190); });
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
  });

  it('leaves another symbol’s pick alone', () => {
    act(() => {
      useScanStore.getState().setCardEdit('options', 'picks', 'MSFT|420|2026-06-18|C', pick('ladder'));
      useScanStore.getState().setPickedContract('AAPL', AAPL_200);
    });
    expect(readEdits('options').picks['MSFT|420|2026-06-18|C']).toEqual(pick('ladder'));
  });

  // The two typed price caches are contract-keyed too and deliberately survive:
  // switch back and the limit you typed for that contract is still yours.
  it('leaves the typed entry limit and premium stop for the old contract', () => {
    act(() => {
      useScanStore.getState().setCardEdit('options', 'entryLimit', AAPL_190, 2.71);
      useScanStore.getState().setCardEdit('options', 'premiumStop', AAPL_190, 3.12);
      useScanStore.getState().setPickedContract('AAPL', AAPL_200);
    });
    expect(readEdits('options').entryLimit[AAPL_190]).toBe(2.71);
    expect(readEdits('options').premiumStop[AAPL_190]).toBe(3.12);
  });
});

// ---------------------------------------------------------------------------
// TEST 15 — the persist migration.
// ---------------------------------------------------------------------------
describe('spec test 15 — a v15 payload rehydrates with both slices empty', () => {
  const seedV15 = () => localStorage.setItem('bamendjou-scan-store', JSON.stringify({
    version: 15,
    state: {
      scanResult: { scan_id: 'A', timestamp: 't', candidates: [], rejected: [] },
      previousRun: null, context: null, scanAt: null, scanDurationMs: null,
      pickedContracts: {}, scanState: 'COMPLETED', screenerMode: 'options',
      activeStrategy: null, stockScanResult: null, previousStockScanResult: null,
      stockScanAt: null, optionsScanAt: null, stockBasket: [],
      lastOptionsScanStatus: null, lastOptionsScanUpdatedAt: null,
      lastStockScanStatus: null, lastStockScanUpdatedAt: null, lastStockScanStrategy: null,
    },
  }));

  it('does not throw, and lands both slices empty with scanId null', async () => {
    seedV15();
    await act(async () => { await expect(useScanStore.persist.rehydrate()).resolves.not.toThrow(); });
    const s = useScanStore.getState();
    expect(s.optionsCardEdits).toEqual(emptyCardEdits());
    expect(s.stocksCardEdits).toEqual(emptyCardEdits());
    expect(s.optionsCardEdits.scanId).toBeNull();
    expect(s.stocksCardEdits.scanId).toBeNull();
  });

  // THE POINT OF THE TEST. A null stamp must read as EMPTY even though the
  // restored result's scan_id is a real one — never as "matches everything".
  it('reads a scanId:null slice as empty against a live scan', async () => {
    seedV15();
    await act(async () => { await useScanStore.persist.rehydrate(); });
    expect(useScanStore.getState().scanResult?.scan_id).toBe('A');
    expect(readEdits('options')).toEqual(emptyCardEdits());

    // And the same with no result at all, where `null === null` would match.
    act(() => { useScanStore.setState({ scanResult: null }); });
    expect(readEdits('options').picks).toEqual({});
  });

  it('rehydrates a blob whose slices are missing or malformed without throwing', async () => {
    localStorage.setItem('bamendjou-scan-store', JSON.stringify({
      version: 16,
      state: { scanResult: { scan_id: 'A', timestamp: 't', candidates: [], rejected: [] },
        optionsCardEdits: 'corrupt', stocksCardEdits: null },
    }));
    await act(async () => { await expect(useScanStore.persist.rehydrate()).resolves.not.toThrow(); });
    expect(useScanStore.getState().optionsCardEdits).toEqual(emptyCardEdits());
    expect(readEdits('options')).toEqual(emptyCardEdits());
    expect(() => readEdits('stocks')).not.toThrow();
  });

  it('a write after the migration lands under the restored scan and is readable', async () => {
    seedV15();
    await act(async () => { await useScanStore.persist.rehydrate(); });
    act(() => { useScanStore.getState().setCardEdit('options', 'picks', AAPL_190, pick()); });
    expect(readEdits('options').picks[AAPL_190]).toEqual(pick());
  });
});
