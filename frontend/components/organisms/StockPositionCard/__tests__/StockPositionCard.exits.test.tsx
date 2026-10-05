import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is about the fat-fingered-target
// validation, not the method-pick gate, so its fixture below stamps a
// satisfied pick or the new `pickMissing` check leaves the button disabled
// before the validation under test is ever reached.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

// api + heavy children are modules (not stores) — mocking them is correct.
jest.mock('@/lib/api', () => ({
  api: {
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockFirstPassage: jest.fn(),
    getStructuralStop: jest.fn(),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

/** entry 150, stop 145 → risk = 5. Every expected value below is derived from these. */
function makeCard(targets?: number[]): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: targets?.length ? targets[0] : 160, rr_ratio: 2, atr: 3, detail: {},
      ...(targets ? { targets } : {}),
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
      expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 80, stock_status: 'PASS',
    shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High',
    sentiment: null, fundamentals: null,
  };
}

// File-scoped reset, run before EVERY test regardless of describe block. A
// pick seeded by one describe's own `beforeEach` otherwise survives into a
// LATER describe in this same file (the store is a module-level singleton),
// and a picked Ladder renders its T1/T2/T3 rows in the method-pick control,
// colliding with this file's own unrelated `getByText('T1')` lookups in the
// sell-to-close-allocation suite below. Each describe block that needs a
// satisfied pick re-seeds it in its own `beforeEach`, which runs AFTER this
// one.
beforeEach(() => {
  useScanStore.setState({
    stockScanResult: null,
    stocksCardEdits: {
      scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
    },
  });
});

describe('StockPositionCard — exit ladder seeding', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => jest.clearAllMocks());

  it('seeds T1/T2/T3 from the backend ladder, not a client-side 2R/3R', () => {
    // A deliberately non-R-shaped ladder: 155 is 1R, 162 is 2.4R, 170 is 4R.
    // No flat multiple of risk reproduces this, so matching it can only come
    // from strategy.targets.
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // T1 renders twice — once in the sizing grid ("T1 TARGET") and once in the
    // sell-to-close plan row.
    expect(screen.getAllByText('155.00')).toHaveLength(2);
    expect(screen.getByText('162.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();

    // The retired client-side invention: with entry 150 and risk 5 the old
    // defaultOverlay produced T2 = entry + 2R = 160 and T3 = entry + 3R = 165
    // regardless of what the strategy actually targeted. Neither may appear.
    expect(screen.queryByText('160.00')).toBeNull();
    expect(screen.queryByText('165.00')).toBeNull();
  });

  it('falls back to R steps past target_price when the ladder is absent', () => {
    // A scan result rehydrated from localStorage before `targets` existed.
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);

    // T1 = target_price = 160 (= entry + 2R for this fixture).
    expect(screen.getAllByText('160.00')).toHaveLength(2);
    // Missing rungs step ONE MORE R past the previous rung — 165 then 170 — NOT
    // 2R/3R measured from entry. Measuring from entry can place T2 behind a
    // strategy-derived T1, and stockPositionLevels() sorts nearest-first into
    // the portfolio, so the persisted targets[0] (the only rung TP_HIT fires on)
    // would stop being the rung the card labelled T1.
    expect(screen.getByText('165.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();
  });

  it('treats an empty ladder as absent (?.length, not ??)', () => {
    // `targets: []` must take the same path as `targets: undefined` — a `??`
    // would keep the empty array and leave every rung undefined.
    render(<StockPositionCard card={makeCard([])} strategyKey="pullback_ema" />);
    expect(screen.getAllByText('160.00')).toHaveLength(2);
    expect(screen.getByText('165.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();
    expect(screen.queryByText('NaN')).toBeNull();
  });
});

// ─── Approach B affordances ───────────────────────────────────────────────────

const mockEstimate = api.getStockFirstPassage as jest.Mock;
const mockStructural = api.getStructuralStop as jest.Mock;

function estimateFixture(modelCaveat: string | null = null) {
  return {
    targets: [
      { price: 155, probability: 0.62, expectedDays: 4 },
      { price: 162, probability: 0.31, expectedDays: 8 },
      { price: 170, probability: 0.0, expectedDays: null },
    ],
    invalidation: { probability: 0.28, expectedDays: 6 },
    horizonDays: 10,
    modelCaveat,
  };
}

async function clickButton(name: RegExp) {
  if (name.test('Add to Portfolio')) fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }));
  });
}

describe('StockPositionCard — first-passage Estimate', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    mockEstimate.mockReset();
    mockStructural.mockReset();
  });
  afterEach(() => jest.clearAllMocks());

  it('renders one row per target with its probability and expected days', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    await clickButton(/^estimate$/i);

    expect(await screen.findByText('62%')).toBeTruthy();
    expect(screen.getByText('31%')).toBeTruthy();
    // A zero-probability rung says "unlikely" rather than "~0d", which would
    // read as "it happens on day zero".
    expect(screen.getByText('unlikely')).toBeTruthy();
    expect(screen.getByText('~4d')).toBeTruthy();
    // Stop-out row.
    expect(screen.getByText('28%')).toBeTruthy();
  });

  it('always states the holding window, in trading days', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    // A probability without its window is meaningless — this must never become
    // optional chrome. "trading days", not "days": the window is a bar count.
    expect(await screen.findByText(/within 10 trading days/i)).toBeTruthy();
  });

  it('sends the EDITED overlay, not the pristine signal', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);

    expect(mockEstimate).toHaveBeenCalledTimes(1);
    expect(mockEstimate.mock.calls[0][0]).toMatchObject({
      symbol: 'AAPL',
      direction: 'Bullish',
      strategy: 'pullback_ema',
      stock_price: 150,
      stop_price: 145,
      targets: [155, 162, 170],
    });
  });

  it('renders the GBM caveat verbatim when the backend sets one', async () => {
    const caveat = 'Approximate for mean-reversion strategies: drift is assumed constant.';
    mockEstimate.mockResolvedValue(estimateFixture(caveat));
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="mean_reversion_bb" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText(caveat)).toBeTruthy();
  });

  it('renders no caveat when the backend sets none', async () => {
    const caveat = 'Approximate for mean-reversion strategies: drift is assumed constant.';
    mockEstimate.mockResolvedValue(estimateFixture(null));
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="breakout_base" />);
    await clickButton(/^estimate$/i);
    await screen.findByText('62%');
    expect(screen.queryByText(caveat)).toBeNull();
  });
});

describe('StockPositionCard — Check structure', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
    mockEstimate.mockReset();
    mockStructural.mockReset();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({}),
    }) as unknown as typeof fetch;
  });
  afterEach(() => jest.clearAllMocks());

  it('carries the checked structural level into the added position', async () => {
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();

    await clickButton(/add to portfolio/i);

    await waitFor(() => {
      expect(usePortfolioStore.getState().positions).toHaveLength(1);
    });
    // This is what makes STRUCTURAL_STOP_BREACHED able to fire for a stock
    // position — it was previously reachable only from the options path.
    expect(usePortfolioStore.getState().positions[0].structuralStop).toBe(143.25);
  });

  it('leaves structuralStop null when the user never checked structure', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/add to portfolio/i);
    await waitFor(() => {
      expect(usePortfolioStore.getState().positions).toHaveLength(1);
    });
    expect(usePortfolioStore.getState().positions[0].structuralStop).toBeNull();
    expect(mockStructural).not.toHaveBeenCalled();
  });

  it('reports a symbol with no structural level instead of rendering nothing', async () => {
    mockStructural.mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/check structure/i);
    expect(await screen.findByText(/no structural level found/i)).toBeTruthy();
  });

  it('renders distancePct next to the structural stop price, matching the options TradeCard format', async () => {
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();
    expect(screen.getByText('(-4.5% away)')).toBeTruthy();
  });
});

// ─── Overlay edits invalidate stale on-demand results ────────────────────────
//
// A displayed Estimate/Check-structure result is a snapshot computed against
// the overlay values AT THE MOMENT the button was clicked. An earlier
// adversarial audit round caught the card silently keeping a stale
// probability/expected-days on screen next to a since-edited entry/stop/target
// — implying they were computed together when they weren't. `patch()` now
// clears whichever result depends on what just changed.

async function editField(label: string, newValue: string) {
  // The Sizing-grid EditableField for this label is always the FIRST match —
  // it renders unconditionally near the top of the tree, above the on-demand
  // result sections that can render their own same-labelled (but read-only)
  // rows once an Estimate/Check-structure result is showing (e.g. "STOP").
  const cell = screen.getAllByText(label)[0].closest('div') as HTMLElement;
  fireEvent.click(within(cell).getByRole('button'));
  const input = within(cell).getByRole('spinbutton');
  fireEvent.change(input, { target: { value: newValue } });
  fireEvent.blur(input);
}

describe('StockPositionCard — overlay edits invalidate stale on-demand results', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    mockEstimate.mockReset();
    mockStructural.mockReset();
  });
  afterEach(() => jest.clearAllMocks());

  it('clears a displayed Estimate result when STOP is edited afterward', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText('62%')).toBeTruthy();

    await editField('STOP', '140');

    // The stale estimate — computed against the OLD stop — must not remain
    // next to the new value, silently implying they were computed together.
    expect(screen.queryByText('62%')).toBeNull();
    expect(screen.queryByText('unlikely')).toBeNull();
  });

  it('clears a displayed Estimate result when T1 TARGET is edited afterward', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText('62%')).toBeTruthy();

    await editField('T1 TARGET', '158');

    expect(screen.queryByText('62%')).toBeNull();
  });

  it('clears a displayed structural-stop result when ENTRY is edited afterward', async () => {
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();

    await editField('ENTRY', '152');

    // 143.25 was checked against the OLD entry (150); it must not survive as
    // if it were still the level for the new entry.
    expect(screen.queryByText('143.25')).toBeNull();
  });

  it('does NOT clear a displayed structural-stop result when STOP is edited (structural is entry-only)', async () => {
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();

    await editField('STOP', '140');

    // Check-structure only ever sent overlay.entry as its reference price, so
    // an edit to STOP alone must not invalidate it.
    expect(screen.getByText('143.25')).toBeTruthy();
  });

  it('does NOT clear a displayed Estimate result when SHARES is edited (irrelevant to the estimate inputs)', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText('62%')).toBeTruthy();

    await editField('SHARES', '50');

    expect(screen.getByText('62%')).toBeTruthy();
  });

  it('editing ENTRY clears BOTH the Estimate and the structural-stop result', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText('62%')).toBeTruthy();
    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();

    await editField('ENTRY', '152');

    expect(screen.queryByText('62%')).toBeNull();
    expect(screen.queryByText('143.25')).toBeNull();
  });
});

// ─── Sell-to-close share allocation never exceeds total shares ──────────────
//
// Each T1/T2/T3 row's share count is editable independently, so nothing
// previously stopped sharesT1+T2+T3 from exceeding the position's total
// shares — which would tell buildPaperStockPosition's contractsToSell to
// sell more shares across the ladder than the position actually holds.

async function editRungShares(id: 'T1' | 'T2' | 'T3', newValue: string) {
  // The row label ("T1"/"T2"/"T3") only appears here in the Sell-to-close
  // plan — the Estimate result's own "T1"/"T2"/"T3" rows are absent unless
  // Estimate has been clicked, which these tests never do.
  const label = screen.getByText(id);
  const row = label.closest('div')!.parentElement as HTMLElement;
  // Price and shares are both clickable (role="button"); RR/return% are not.
  // Shares is the second.
  const buttons = within(row).getAllByRole('button');
  fireEvent.click(buttons[1]);
  const input = within(row).getByRole('spinbutton');
  fireEvent.change(input, { target: { value: newValue } });
  fireEvent.blur(input);
}

describe('StockPositionCard — sell-to-close share allocation is clamped to total shares', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => jest.clearAllMocks());

  it('clamps a rung whose own edit would push the allocation over total shares', async () => {
    // makeCard's 30 shares default to 10/10/10 across T1/T2/T3 (see
    // defaultOverlay: s1 = s2 = floor(30/3) = 10, s3 = 30 - 10 - 10 = 10).
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // Push T1's own share count up so T1(25) + T2(10) + T3(10) = 45 > 30.
    await editRungShares('T1', '25');

    // T1 must be clamped down to what's left after T2/T3 (30 - 10 - 10 = 10),
    // not left at 25 (which would oversell) and not silently shrinking T2/T3
    // (which the user never touched).
    const t1Row = screen.getByText('T1').closest('div')!.parentElement as HTMLElement;
    expect(within(t1Row).getByText('10')).toBeTruthy();
  });

  it('scales every rung down proportionally when total SHARES is reduced below the existing allocation', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // 10/10/10 across T1/T2/T3 -> reduce total shares to 15 (half).
    await editField('SHARES', '15');

    const t1Row = screen.getByText('T1').closest('div')!.parentElement as HTMLElement;
    const t2Row = screen.getByText('T2').closest('div')!.parentElement as HTMLElement;
    const t3Row = screen.getByText('T3').closest('div')!.parentElement as HTMLElement;
    const t1 = Number(within(t1Row).getAllByRole('button')[1].textContent);
    const t2 = Number(within(t2Row).getAllByRole('button')[1].textContent);
    const t3 = Number(within(t3Row).getAllByRole('button')[1].textContent);
    expect(t1 + t2 + t3).toBeLessThanOrEqual(15);
    expect(t1 + t2 + t3).toBe(15); // T3 absorbs the rounding remainder, nothing is dropped
  });

  it('scales every rung UP proportionally when total SHARES is increased beyond the existing allocation', async () => {
    // A fifth independent audit round found the mirror gap: the shrink case
    // above was fixed, but growing SHARES left the rungs unchanged, silently
    // leaving the added shares with no planned exit rung at all.
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // 10/10/10 across T1/T2/T3 (sum 30) -> raise total shares to 60 (double).
    await editField('SHARES', '60');

    const t1Row = screen.getByText('T1').closest('div')!.parentElement as HTMLElement;
    const t2Row = screen.getByText('T2').closest('div')!.parentElement as HTMLElement;
    const t3Row = screen.getByText('T3').closest('div')!.parentElement as HTMLElement;
    const t1 = Number(within(t1Row).getAllByRole('button')[1].textContent);
    const t2 = Number(within(t2Row).getAllByRole('button')[1].textContent);
    const t3 = Number(within(t3Row).getAllByRole('button')[1].textContent);
    expect(t1).toBe(20);
    expect(t2).toBe(20);
    expect(t3 + t1 + t2).toBe(60); // T3 absorbs the rounding remainder, nothing is left uncovered
  });

  it('does not clamp when the allocation already fits within total shares', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // 10/10/10 -> edit T1 down to 5; 5+10+10 = 25 <= 30, no clamping needed.
    await editRungShares('T1', '5');

    const t1Row = screen.getByText('T1').closest('div')!.parentElement as HTMLElement;
    expect(within(t1Row).getByText('5')).toBeTruthy();
  });
});

// ─── Add to Portfolio rejects a target on the wrong side of entry ───────────
//
// stockPositionLevels() silently drops such a rung (and the shares allocated
// to it) with no signal that anything happened. An adversarial audit round
// flagged this as a real gap since EditableField's save() has no side check —
// Add to Portfolio must warn and refuse rather than silently truncate the
// sell-to-close plan.

describe('StockPositionCard — Add to Portfolio rejects a fat-fingered target', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
  });
  afterEach(() => jest.clearAllMocks());

  it('blocks the add and reports which target is on the wrong side of entry', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // entry=150; edit T1 to 145 (behind entry for a Bullish position).
    await editField('T1 TARGET', '145');
    await clickButton(/add to portfolio/i);

    expect(await screen.findByText(/145\.00 is on the wrong side of entry/i)).toBeTruthy();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('adds normally once the bad target is corrected', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    await editField('T1 TARGET', '145');
    await clickButton(/add to portfolio/i);
    expect(await screen.findByText(/wrong side of entry/i)).toBeTruthy();

    await editField('T1 TARGET', '155');
    await clickButton(/add to portfolio/i);

    await waitFor(() => {
      expect(usePortfolioStore.getState().positions).toHaveLength(1);
    });
    expect(screen.queryByText(/wrong side of entry/i)).toBeNull();
  });
});

// New ephemeral execution records must not leak between independent test scans.
beforeEach(() => useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0 }));
