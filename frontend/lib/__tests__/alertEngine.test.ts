import { scanPortfolio, TIME_STOP_DTE, type AlertPosition } from '@/lib/alertEngine';
import type { AlertType } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';

function makePosition(overrides: Partial<AlertPosition> = {}): AlertPosition {
  // Defaults currentStockPrice to currentPrice so pre-existing tests that don't care about the
  // premium-vs-stock-price distinction keep exercising STOP_REACHED/TP_HIT via an explicit
  // currentStockPrice, not the (now-guarded) fallback. Tests that DO care pass currentStockPrice
  // explicitly in overrides, which wins over this default.
  const currentPrice = overrides.currentPrice ?? 90;
  return {
    recId: 'r1',
    symbol: 'NVDA',
    contract: 'NVDA|100|2026-12-18|C',
    currentPrice,
    currentStockPrice: currentPrice,
    entryPrice: 5,
    stop: 95,          // currentPrice 90 <= stop 95  => STOP_REACHED
    targets: [],
    dteRemaining: 30,
    dteTotal: 60,
    pnlPct: 0,
    direction: 'Bullish',
    ...overrides,
  };
}

// Keep the old alias for the existing test
const pos = makePosition;

describe('scanPortfolio', () => {
  it('fires STOP_REACHED even when the symbol is flagged as a scan conflict', () => {
    useScanStore.getState().setConflictedSymbols(['NVDA']);
    const out = scanPortfolio([pos()]);
    expect(out.some((a) => a.symbol === 'NVDA' && a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('STOP_REACHED reason includes the triggering price, not just the stop', () => {
    // Deliberately non-default values (makePosition defaults to currentPrice:
    // 90, stop: 95) so this test can't pass by coincidentally matching them.
    const out = scanPortfolio([pos({ currentPrice: 80, stop: 85 })]);
    const stopAlert = out.find((a) => a.alertType === 'STOP_REACHED');
    expect(stopAlert?.reason).toContain('$85.00');
    expect(stopAlert?.reason).toContain('$80.00');
  });

  it('fires STRUCTURAL_STOP_BREACHED when price crosses the structural stop', () => {
    const out = scanPortfolio([pos({ stop: null, structuralStop: 92, currentPrice: 90 })]);
    expect(out.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(true);
  });

  it('does NOT fire STRUCTURAL_STOP_BREACHED when unset — optional, unlike stop', () => {
    const out = scanPortfolio([pos({ structuralStop: undefined, currentPrice: 1 })]);
    expect(out.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(false);
  });

  it('fires STRUCTURAL_STOP_BREACHED for a Bearish position when price rises above it, not below', () => {
    const above = scanPortfolio([pos({ direction: 'Bearish', stop: null, structuralStop: 100, currentPrice: 101 })]);
    expect(above.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(true);
    const below = scanPortfolio([pos({ direction: 'Bearish', stop: null, structuralStop: 100, currentPrice: 99 })]);
    expect(below.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(false);
  });

  it('STRUCTURAL_STOP_BREACHED reason includes the triggering price and the structural level', () => {
    const out = scanPortfolio([pos({ stop: null, structuralStop: 85, currentPrice: 80 })]);
    const alert = out.find((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED');
    expect(alert?.reason).toContain('$85.00');
    expect(alert?.reason).toContain('$80.00');
    expect(alert?.kind).toBe('Critical');
  });

  // These three drive PREMIUM_STOP through the OPTION PRICE, not through
  // `pnlPct`, because that is what both engines now compare. Driving it through
  // pnlPct is how the two came to disagree: portfolio.py rounds pnlPct to 2dp,
  // so a position the backend had not stopped out could still cross a rounded
  // −60.00 here and raise an in-app toast with no backend alert behind it.
  // entryPrice 5 at 60% => the stop fires at $2.00.
  it('fires PREMIUM_STOP when the option price reaches entry x (1 - pct)', () => {
    const position = makePosition({ entryPrice: 5, currentPrice: 1.75 });
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(true);
  });

  it('fires exactly AT the threshold, and not a cent above it — the boundary the two engines used to disagree on', () => {
    // The backend's comparison is `opt_price <= entry * (1 - pct)`. At entry
    // $5.00 and pct 0.30 that is $3.50. A quote of $3.5001 is NOT a stop-out
    // there — but its pnlPct is −29.998, which rounds to −30.00 and used to
    // fire here.
    const at = scanPortfolio([makePosition({ entryPrice: 5, currentPrice: 3.50, pnlPct: -30 })], { premiumStopPct: 0.30 });
    expect(at.some(r => r.alertType === 'PREMIUM_STOP')).toBe(true);
    const justAbove = scanPortfolio([makePosition({ entryPrice: 5, currentPrice: 3.5001, pnlPct: -30 })], { premiumStopPct: 0.30 });
    expect(justAbove.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
  });

  it('does NOT fire PREMIUM_STOP when loss is below threshold', () => {
    const position = makePosition({ entryPrice: 5, currentPrice: 2.50 });
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
  });

  it('does NOT fire PREMIUM_STOP when the quote fetch failed', () => {
    // A missing quote reaches the engine as a PRICE OF ZERO, not as null:
    // portfolio.py writes `quote.get("price") or 0.0` and portfolioStore's
    // fromBackend does `p.currentPrice ?? 0`. `0 <= entry * (1 - pct)` is true
    // for every position, so an unguarded comparison raised a Critical toast
    // for the whole portfolio on every 30s cycle whenever the market was shut
    // or the broker was down — reading "down 0.0%", with no backend alert
    // behind it, because alert_generator.py guards on `opt_price is not None`.
    //
    // Not a hazard this comparison inherited: the `pnlPct <= -60` test it
    // replaced read `0 <= -60` on the same input and stayed silent.
    const dead = makePosition({ entryPrice: 5, currentPrice: 0, pnlPct: 0 });
    const results = scanPortfolio([dead], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
  });

  it('records the price and the threshold it fired against', () => {
    // The backend logs both for this alert type (`price=opt_price,
    // reference_value=threshold_price`). Leaving them undefined gave
    // position_alert_history two different row shapes for one alert type
    // depending on which engine wrote it.
    const position = makePosition({ entryPrice: 5, currentPrice: 1.75 });
    const hit = scanPortfolio([position], { premiumStopPct: 0.60 })
      .find(r => r.alertType === 'PREMIUM_STOP')!;
    expect(hit.price).toBe(1.75);
    expect(hit.referenceValue).toBeCloseTo(2.00, 10);
  });

  it('stores the threshold rounded the way Python round(x, 4) does, including an exact tie (P2-22)', () => {
    // entry 2.0625 at 50% -> threshold 1.03125 exactly, a binary tie at 4dp.
    // Python stores round(1.03125, 4) = 1.0312 (half-to-even); Math.round gave 1.0313.
    const tie = scanPortfolio([makePosition({ entryPrice: 2.0625, currentPrice: 1.0 })], { premiumStopPct: 0.5 })
      .find(r => r.alertType === 'PREMIUM_STOP')!;
    expect(tie.referenceValue).toBe(1.0312);
  });

  it('fires STOP_REACHED for a Bearish position when price rises above stop, not below', () => {
    const short = makePosition({ direction: 'Bearish', stop: 95, currentPrice: 100 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('does NOT fire STOP_REACHED for a Bearish position when price falls below stop', () => {
    const short = makePosition({ direction: 'Bearish', stop: 95, currentPrice: 90 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('fires TP_HIT for a Bearish position when price falls to target, not rises', () => {
    const short = makePosition({
      direction: 'Bearish', currentPrice: 80,
      targets: [{ id: 't1', stockPrice: 85, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(true);
  });

  it('does NOT fire TP_HIT for a Bearish position when price rises toward target', () => {
    const short = makePosition({
      direction: 'Bearish', currentPrice: 120,
      targets: [{ id: 't1', stockPrice: 85, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('does NOT fire STOP_REACHED for a Bearish position with no stop set (stop=null)', () => {
    // AlertPosition.stop is now genuinely nullable end-to-end (portfolioStore.ts
    // no longer coerces a null backend stop to 0) — `stop: 0` is a real $0 stop,
    // not an "unset" sentinel, so the guard checks `!= null` rather than `> 0`.
    // Without this guard, a Bearish position with no stop would satisfy
    // currentPrice >= 0 on virtually every poll, firing a spurious Critical
    // alert continuously (found during audit of this plan).
    const short = makePosition({ direction: 'Bearish', stop: null, currentPrice: 150 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('does NOT fire STOP_REACHED for a Bullish position with no stop set (stop=null)', () => {
    // Symmetric to the Bearish stop=null guard above — for a long position this
    // was already coincidentally safe (currentPrice <= 0 is never true for a
    // real price), but this test makes that safety explicit instead of relying
    // on it remaining a coincidence (flagged during adversarial review of this plan).
    const long = makePosition({ direction: 'Bullish', stop: null, currentPrice: 150 });
    const out = scanPortfolio([long]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('fires STOP_REACHED for a Bearish position with a real $0 stop (stop=0 is not "unset")', () => {
    // Guards against silently reintroducing the old stop>0 workaround, which
    // treated a genuine $0 stop the same as "no stop set".
    const short = makePosition({ direction: 'Bearish', stop: 0, currentPrice: 150 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('populates price/referenceValue/direction/contract on TP_HIT and STOP_REACHED', () => {
    const withTarget = makePosition({
      currentPrice: 100, stop: 90, direction: 'Bullish',
      targets: [{ id: 't1', stockPrice: 95, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([withTarget]);
    const tpHit = out.find((a) => a.alertType === 'TP_HIT');
    expect(tpHit).toMatchObject({
      price: 100, referenceValue: 95, direction: 'Bullish', contract: withTarget.contract,
    });
  });

  it('populates referenceValue (days) and note on EVENT_RISK, with no price', () => {
    const withEvent = makePosition({ nextEventDays: 2, nextEventLabel: 'Earnings' });
    const out = scanPortfolio([withEvent]);
    const eventRisk = out.find((a) => a.alertType === 'EVENT_RISK');
    expect(eventRisk).toMatchObject({ referenceValue: 2, note: 'Earnings' });
    expect(eventRisk?.price).toBeUndefined();
  });

  // currentStockPrice: an option position's `currentPrice` is the PREMIUM, not comparable to
  // `stop` (always a stock price) — see alertEngine.ts's STOP_REACHED comment. These tests cover
  // the fix directly; every test above this point relies on makePosition()'s default, which
  // mirrors currentStockPrice to currentPrice so it isn't exercising the premium/stock distinction.
  it('does NOT fire STOP_REACHED on an option position with no currentStockPrice (fresh open, or a stuck quote fetch)', () => {
    // The FTNT case: currentPrice is still the entry premium ($14), currentStockPrice is unset —
    // either because the position was just opened and no live underlying quote has landed yet,
    // or because the quote fetch has been failing outright. Either way, without the
    // hasReferencePrice guard the premium gets compared against the stock-price stop and
    // falsely breaches it.
    const position = makePosition({
      currentPrice: 14.18,       // option premium, not a stock price
      currentStockPrice: undefined,
      stop: 146.27,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('does NOT fire TP_HIT on an option position with no currentStockPrice', () => {
    // currentPrice (10) is set ABOVE the target (8) deliberately: without the hasReferencePrice
    // guard, the old fallback (currentStockPrice ?? currentPrice) would use the premium as
    // referencePrice and satisfy `10 >= 8`, firing a false TP_HIT — so this actually fails if
    // the guard regresses, unlike a premium-below-target value which passes either way.
    const position = makePosition({
      currentPrice: 10,
      currentStockPrice: undefined,
      targets: [{ id: 't1', stockPrice: 8, contractsToSell: 1, status: 'PENDING' }],
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('does NOT fire STRUCTURAL_STOP_BREACHED on an option position with no currentStockPrice', () => {
    const position = makePosition({
      currentPrice: 5,
      currentStockPrice: undefined,
      stop: null,
      structuralStop: 100,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(false);
  });

  it('does NOT fire STOP_REACHED on an option position when currentStockPrice is literally 0', () => {
    // Nothing in the backend currently sends currentStockPrice: 0 (a failed fetch omits the
    // field entirely) — but hasReferencePrice treats 0 the same as unset for both branches on
    // purpose, so this pins that in case a future change ever does send a literal 0.
    const position = makePosition({
      currentPrice: 5,
      currentStockPrice: 0,
      stop: 140,
      direction: 'Bullish',   // 0 <= 140 would satisfy a Bullish STOP_REACHED without the guard
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('does NOT fire STOP_REACHED on a stock position when currentPrice is 0 (failed quote fetch)', () => {
    // portfolioStore.ts coerces a missing/failed price to 0 (`p.currentPrice ?? 0`) — 0 is never
    // a real stock price, and without the isStock branch of hasReferencePrice this would satisfy
    // `0 <= stop` for essentially any Bullish stop and fire immediately.
    const position = makePosition({
      contract: 'NVDA|STOCK',
      currentPrice: 0,
      stop: 95,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('does NOT fire TP_HIT on a stock position when currentPrice is 0 (failed quote fetch)', () => {
    // Same isStock branch of hasReferencePrice as the STOP_REACHED case above, covered
    // separately since TP_HIT/STOP_REACHED/STRUCTURAL_STOP_BREACHED could regress independently.
    const position = makePosition({
      contract: 'NVDA|STOCK',
      currentPrice: 0,
      targets: [{ id: 't1', stockPrice: 8, contractsToSell: 1, status: 'PENDING' }],
      direction: 'Bearish',   // 0 <= 8 would satisfy a Bearish TP_HIT without the guard
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('does NOT fire STRUCTURAL_STOP_BREACHED on a stock position when currentPrice is 0 (failed quote fetch)', () => {
    const position = makePosition({
      contract: 'NVDA|STOCK',
      currentPrice: 0,
      stop: null,
      structuralStop: 95,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STRUCTURAL_STOP_BREACHED')).toBe(false);
  });

  it('does NOT fire TIME_STOP on a stock position, even with the real-world default dteRemaining of 0', () => {
    // Round-7 re-audit finding: dteRemaining defaults/coerces to 0 for every
    // stock position (paperTrade.ts's buildPaperStockPosition, portfolioStore.ts's
    // `?? 0` sync, and the backend schema default — portfolio.py's router only
    // derives it from a contract's expiry for an options-shaped contract string),
    // so `dteRemaining <= 3` was unconditionally true for a stock position without
    // the isStock guard, firing TIME_STOP on every open stock position forever.
    // Deliberately does NOT override dteRemaining, to catch a regression at the
    // real-world default rather than a hand-picked low value.
    const position = makePosition({ contract: 'NVDA|STOCK' });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'TIME_STOP')).toBe(false);
  });

  it('still fires TIME_STOP on an option position within 3 DTE', () => {
    const position = makePosition({ dteRemaining: 1 });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'TIME_STOP')).toBe(true);
  });

  it('fires TIME_STOP at exactly TIME_STOP_DTE and not one day before it (P2-03)', () => {
    expect(TIME_STOP_DTE).toBe(3);
    const fires = (dteRemaining: number) =>
      scanPortfolio([makePosition({ dteRemaining })]).some((a) => a.alertType === 'TIME_STOP');
    expect(fires(TIME_STOP_DTE)).toBe(true);
    expect(fires(TIME_STOP_DTE + 1)).toBe(false);
  });

  it('uses currentStockPrice, not the option premium, for STOP_REACHED on an option position', () => {
    // Premium (currentPrice) is far below any realistic stop — if the bug were still present
    // this would fire immediately. The real stock price is what must be compared.
    const position = makePosition({
      currentPrice: 5,          // option premium — NOT comparable to a stock-price stop
      currentStockPrice: 150,   // live underlying price
      stop: 140,                // Bullish: breached when stock price <= stop
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false); // 150 > 140, not breached
  });

  it('fires STOP_REACHED using currentStockPrice when the underlying actually breaches the stop', () => {
    const position = makePosition({
      currentPrice: 5,
      currentStockPrice: 130,   // now below stop
      stop: 140,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    const alert = out.find((a) => a.alertType === 'STOP_REACHED');
    expect(alert).toBeDefined();
    expect(alert?.price).toBe(130);           // reports the stock price, not the premium
    expect(alert?.reason).toContain('$130.00');
  });

  it('uses currentPrice (not currentStockPrice) for STOP_REACHED on a stock position', () => {
    const position = makePosition({
      contract: 'NVDA|STOCK',
      currentPrice: 90,
      currentStockPrice: 999,   // must be ignored for a stock leg
      stop: 95,
      direction: 'Bullish',
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true); // 90 <= 95
  });

  // TP_HIT has the identical premium-vs-stock-price bug as STOP_REACHED above — same fix,
  // same referencePrice. These tests mirror the currentStockPrice tests above.
  it('uses currentStockPrice, not the option premium, for TP_HIT on an option position', () => {
    // Premium (currentPrice) is far below the target — if the bug were still present this
    // would fire immediately for a Bearish position. The real stock price is what must be used.
    const short = makePosition({
      direction: 'Bearish',
      currentPrice: 5,          // option premium — NOT comparable to a stock-price target
      currentStockPrice: 160,   // live underlying price — above the target, not hit
      targets: [{ id: 't1', stockPrice: 150, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false); // 160 > 150, not hit
  });

  it('fires TP_HIT using currentStockPrice when the underlying actually hits the target', () => {
    const short = makePosition({
      direction: 'Bearish',
      currentPrice: 5,
      currentStockPrice: 140,   // now at/below target
      targets: [{ id: 't1', stockPrice: 150, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert).toBeDefined();
    expect(alert?.price).toBe(140);           // reports the stock price, not the premium
    expect(alert?.reason).toContain('$140.00');
  });

  it('uses currentPrice (not currentStockPrice) for TP_HIT on a stock position', () => {
    const position = makePosition({
      contract: 'NVDA|STOCK',
      currentPrice: 155,
      currentStockPrice: 5,     // must be ignored for a stock leg
      targets: [{ id: 't1', stockPrice: 150, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([position]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(true); // 155 >= 150
  });

  it('fires TP_HIT for a Bullish option position via currentStockPrice when the premium alone would never trigger it', () => {
    // Under the old bug, a Bullish option's premium (currentPrice) essentially never satisfies
    // `>= target.stockPrice`, so a real target hit was silently never flagged (under-firing,
    // not a false positive — the opposite failure mode from the Bearish case above).
    const position = makePosition({
      direction: 'Bullish',
      currentPrice: 5,          // premium — would never satisfy >= 150 under the old bug
      currentStockPrice: 155,   // live underlying price — has hit the target
      targets: [{ id: 't1', stockPrice: 150, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([position]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert).toBeDefined();
    expect(alert?.price).toBe(155);
    expect(alert?.reason).toContain('$155.00');
  });
});

/* ------------------------------------------------------------------------ *
 * Feature D — per-position alert overrides + active TP method
 * (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
 *
 * Backend mirror: backend/tests/test_alert_overrides.py. A rule proved here
 * should have a counterpart there.
 * ------------------------------------------------------------------------ */

const ALL_TYPES: AlertType[] = [
  'TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP',
  'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE', 'SCAN_COMPLETE', 'SCAN_FAILED',
  'TIME_STOP_APPROACHING', 'EARNINGS_APPROACHING', 'EXPIRATION_APPROACHING',
];

describe('scanPortfolio — global enabledTypes gating (the toast-gating bugfix)', () => {
  it('still fires every type when enabledTypes is not supplied at all', () => {
    // The pre-Feature-D contract: a caller that never passes enabledTypes must
    // not have every one of its alerts silently muted.
    const out = scanPortfolio([makePosition()]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('suppresses a type the user turned off globally', () => {
    const out = scanPortfolio([makePosition()], {
      enabledTypes: ALL_TYPES.filter((t) => t !== 'STOP_REACHED'),
    });
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('leaves the other types firing when one is globally off', () => {
    const out = scanPortfolio(
      [makePosition({ dteRemaining: 1 })],
      { enabledTypes: ALL_TYPES.filter((t) => t !== 'STOP_REACHED') },
    );
    const types = out.map((a) => a.alertType);
    expect(types).not.toContain('STOP_REACHED');
    expect(types).toContain('TIME_STOP');
  });

  it('suppresses everything when the enabled list is empty', () => {
    const out = scanPortfolio([makePosition({ dteRemaining: 1, pnlPct: -80 })], { enabledTypes: [] });
    expect(out).toEqual([]);
  });
});

describe('scanPortfolio — per-position alert overrides', () => {
  it('an explicit false beats a globally-enabled type', () => {
    const out = scanPortfolio(
      [makePosition({ alertOverrides: { STOP_REACHED: false } })],
      { enabledTypes: ALL_TYPES },
    );
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('an explicit true beats a globally-disabled type', () => {
    const out = scanPortfolio(
      [makePosition({ alertOverrides: { STOP_REACHED: true } })],
      { enabledTypes: ALL_TYPES.filter((t) => t !== 'STOP_REACHED') },
    );
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('an absent key inherits the global decision, both ways', () => {
    const on = scanPortfolio([makePosition({ alertOverrides: {} })], { enabledTypes: ALL_TYPES });
    expect(on.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);

    const off = scanPortfolio([makePosition({ alertOverrides: {} })], {
      enabledTypes: ALL_TYPES.filter((t) => t !== 'STOP_REACHED'),
    });
    expect(off.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('an override on one type does not leak to the others', () => {
    const out = scanPortfolio(
      [makePosition({ dteRemaining: 1, alertOverrides: { STOP_REACHED: false } })],
      { enabledTypes: ALL_TYPES },
    );
    const types = out.map((a) => a.alertType);
    expect(types).not.toContain('STOP_REACHED');
    expect(types).toContain('TIME_STOP');
  });

  it('an override on one position does not leak to another', () => {
    const out = scanPortfolio(
      [
        makePosition({ recId: 'muted', alertOverrides: { STOP_REACHED: false } }),
        makePosition({ recId: 'loud' }),
      ],
      { enabledTypes: ALL_TYPES },
    );
    const stopAlerts = out.filter((a) => a.alertType === 'STOP_REACHED');
    expect(stopAlerts).toHaveLength(1);
    expect(stopAlerts[0].recId).toBe('loud');
  });

  it('a non-bool stored override value is treated as absent, not truthy', () => {
    // Mirrors the backend's effective_enabled, which does the same
    // isinstance(value, bool) check — a hand-edited/corrupted JSON value like
    // the string "off" must not silently force the type on just because it's
    // not strictly falsy.
    const out = scanPortfolio(
      [makePosition({ alertOverrides: { STOP_REACHED: 'off' as unknown as boolean } })],
      { enabledTypes: ALL_TYPES.filter((t) => t !== 'STOP_REACHED') },
    );
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('covers every position-scoped type', () => {
    const position = makePosition({
      // currentPrice is the OPTION price (what PREMIUM_STOP compares); the
      // stock-price-driven alerts read currentStockPrice, which is why these
      // two are now deliberately different numbers. entryPrice 5 at 60% => the
      // premium stop fires at $2.00.
      currentPrice: 1.0,
      currentStockPrice: 160,
      stop: 165,
      structuralStop: 165,
      targets: [{ id: 't1', stockPrice: 150, contractsToSell: 1, status: 'PENDING' }],
      pnlPct: -80,
      dteRemaining: 1,
      nextEventDays: 1,
      nextEventLabel: 'Earnings',
    });
    // Sanity: with no overrides this position raises all six.
    const loud = scanPortfolio([position], { enabledTypes: ALL_TYPES });
    expect(new Set(loud.map((a) => a.alertType)).size).toBe(6);

    const muted = scanPortfolio(
      [{
        ...position,
        alertOverrides: {
          TP_HIT: false, STOP_REACHED: false, STRUCTURAL_STOP_BREACHED: false,
          PREMIUM_STOP: false, TIME_STOP: false, EVENT_RISK: false,
        },
      }],
      { enabledTypes: ALL_TYPES },
    );
    expect(muted).toEqual([]);
  });
});

describe('scanPortfolio — active TP method / resolved TP snapshot', () => {
  const withTp = (overrides: Partial<AlertPosition>) => makePosition({
    stop: null,
    currentPrice: 165,
    currentStockPrice: 165,
    targets: [{ id: 't1', stockPrice: 200, contractsToSell: 1, status: 'PENDING' }],
    ...overrides,
  });

  it('compares against resolvedTpPrice instead of the ladder target', () => {
    const out = scanPortfolio([withTp({ resolvedTpPrice: 160, activeTpMethod: 'exit_plan_2r' })]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert).toBeDefined();               // 165 >= 160, though the ladder says 200
    expect(alert?.referenceValue).toBe(160);
  });

  it('holds the alert back when the snapshot sits beyond the ladder target', () => {
    const out = scanPortfolio([withTp({
      targets: [{ id: 't1', stockPrice: 160, contractsToSell: 1, status: 'PENDING' }],
      resolvedTpPrice: 200,
      activeTpMethod: 'exit_plan_3r',
    })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('names the method that fired in the reason line', () => {
    const out = scanPortfolio([withTp({ resolvedTpPrice: 160, activeTpMethod: 'exit_plan_2r' })]);
    expect(out.find((a) => a.alertType === 'TP_HIT')?.reason).toContain('(2R exit plan)');
  });

  it('leaves the ladder reason line unchanged', () => {
    const out = scanPortfolio([withTp({
      targets: [{ id: 't1', stockPrice: 160, contractsToSell: 1, status: 'PENDING' }],
      activeTpMethod: 'ladder',
    })]);
    const reason = out.find((a) => a.alertType === 'TP_HIT')?.reason;
    expect(reason).toBe('Target reached — NVDA at $165.00');
  });

  it('falls back to the ladder when a non-ladder method has no snapshot stamped', () => {
    // A mis-set position must keep alerting, not go silent — and must not
    // claim the un-stamped method supplied the price.
    const out = scanPortfolio([withTp({
      targets: [{ id: 't1', stockPrice: 160, contractsToSell: 1, status: 'PENDING' }],
      resolvedTpPrice: null,
      activeTpMethod: 'exit_plan_2r',
    })]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert?.referenceValue).toBe(160);
    expect(alert?.reason).not.toContain('exit plan');
  });

  it('falls back to the ladder and does not mislabel on a stray negative resolvedTpPrice', () => {
    // Backend regression guard (round-9 audit finding): a >0 check is
    // required, not just != null — 0 falls back correctly, but truthiness
    // alone would treat a negative snapshot as "set" and mislabel a
    // ladder-sourced fire with the (unused) exit-plan method name. Pins the
    // frontend side of the same guard, which the backend fix didn't have an
    // explicit negative-value test for on this side.
    const out = scanPortfolio([withTp({
      targets: [{ id: 't1', stockPrice: 160, contractsToSell: 1, status: 'PENDING' }],
      resolvedTpPrice: -50,
      activeTpMethod: 'exit_plan_2r',
    })]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert?.referenceValue).toBe(160);
    expect(alert?.reason).not.toContain('exit plan');
  });

  it('fires off the snapshot alone when the position has no ladder targets', () => {
    const out = scanPortfolio([withTp({ targets: [], resolvedTpPrice: 160, activeTpMethod: 'monte_carlo' })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(true);
  });

  it('raises no TP_HIT when neither a snapshot nor a ladder target exists', () => {
    const out = scanPortfolio([withTp({ targets: [], resolvedTpPrice: null })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('is direction-aware for a Bearish snapshot', () => {
    const hit = scanPortfolio([withTp({
      direction: 'Bearish', targets: [], resolvedTpPrice: 170, activeTpMethod: 'exit_plan_2r',
    })]);
    expect(hit.some((a) => a.alertType === 'TP_HIT')).toBe(true);   // 165 <= 170

    const quiet = scanPortfolio([withTp({
      direction: 'Bearish', targets: [], resolvedTpPrice: 160, activeTpMethod: 'exit_plan_2r',
    })]);
    expect(quiet.some((a) => a.alertType === 'TP_HIT')).toBe(false); // 165 > 160
  });

  it('still suppresses a snapshot-driven TP_HIT the position has muted', () => {
    const out = scanPortfolio(
      [withTp({ resolvedTpPrice: 160, activeTpMethod: 'exit_plan_2r', alertOverrides: { TP_HIT: false } })],
      { enabledTypes: ALL_TYPES },
    );
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('never fires off a snapshot while no live reference price exists', () => {
    // The hasReferencePrice guard must still win — an option leg with no live
    // underlying quote yet must not compare its premium against the snapshot.
    const out = scanPortfolio([withTp({
      currentPrice: 5, currentStockPrice: undefined, targets: [],
      resolvedTpPrice: 4, activeTpMethod: 'exit_plan_2r',
    })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });
});

describe('scanPortfolio — a zero resolved TP price is not a target', () => {
  const zeroTp = (overrides: Partial<AlertPosition> = {}) => makePosition({
    stop: null,
    currentPrice: 165,
    currentStockPrice: 165,
    activeTpMethod: 'monte_carlo',
    resolvedTpPrice: 0,
    ...overrides,
  });

  it('falls back to the ladder rather than firing on every tick', () => {
    // The option-side Monte Carlo mapping turns a target with no stockPrice
    // into 0. Read as a real level, `165 >= 0` is true forever.
    const out = scanPortfolio([zeroTp({
      targets: [{ id: 't1', stockPrice: 200, contractsToSell: 1, status: 'PENDING' }],
    })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('raises nothing at all when the ladder is empty too', () => {
    expect(scanPortfolio([zeroTp({ targets: [] })]).some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('does not claim the method supplied the price when it falls back', () => {
    const out = scanPortfolio([zeroTp({
      targets: [{ id: 't1', stockPrice: 160, contractsToSell: 1, status: 'PENDING' }],
    })]);
    const alert = out.find((a) => a.alertType === 'TP_HIT');
    expect(alert?.referenceValue).toBe(160);
    expect(alert?.reason).not.toContain('Monte Carlo');
  });

  it('a zero ladder target (no snapshot at all, default "ladder" method) does not fire on every tick', () => {
    // Distinct from the cases above: no activeTpMethod/resolvedTpPrice at all —
    // this is the plain pre-Feature-D ladder path with a genuinely zero first
    // target, which the frontend's `> 0` guard must also cover, not just the
    // resolvedTpPrice snapshot path. Mirrors the backend's
    // test_a_zero_ladder_target_does_not_fire_tp_hit.
    const out = scanPortfolio([makePosition({
      stop: null,
      currentPrice: 165,
      currentStockPrice: 165,
      targets: [{ id: 't1', stockPrice: 0, contractsToSell: 1, status: 'PENDING' }],
    })]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });
});

// ── ALERT-THRESHOLD-STAMP-2026-09-05 ────────────────────────────────────────
//
// The Alerts page used to resolve a fired row's percentage live off the
// position on every render, so editing a position's stop afterwards silently
// relabelled its history with a threshold those alerts never used. The engine
// stamps the fraction it actually fired at.
describe('PREMIUM_STOP stamps the threshold it fired at', () => {
  const fired = (position: AlertPosition, globalPct: number) =>
    scanPortfolio([position], { premiumStopPct: globalPct })
      .find((r) => r.alertType === 'PREMIUM_STOP');

  it('stamps the GLOBAL fraction for a position that inherits it', () => {
    const r = fired(makePosition({ entryPrice: 5, currentPrice: 1.75 }), 0.60);
    expect(r?.premiumStopPct).toBe(0.60);
  });

  it("stamps the POSITION's own fraction, not the global, when it is pinned", () => {
    // The whole point. entry $5 pinned at 30% fires at $3.50; the global 60%
    // would have armed at $2.00 and is not what this alert used.
    const r = fired(
      makePosition({ entryPrice: 5, currentPrice: 3.50, premiumStopPct: 0.30 }),
      0.60,
    );
    expect(r?.premiumStopPct).toBe(0.30);
  });

  it('agrees with the referenceValue beside it — one alert, one threshold', () => {
    // referenceValue is the threshold PRICE, premiumStopPct the fraction. If
    // they disagreed, the row's own two halves would describe different stops.
    const r = fired(
      makePosition({ entryPrice: 5, currentPrice: 3.50, premiumStopPct: 0.30 }),
      0.60,
    );
    expect(r?.referenceValue).toBeCloseTo(5 * (1 - r!.premiumStopPct!), 4);
  });

  it('stamps an unrounded server-derived fraction without flattening it', () => {
    // A per-position fraction is premiumStopDollar / entryPrice and almost
    // never lands on a round number. The lossy Math.round on the old label was
    // already fixed; storage must not reintroduce it.
    const r = fired(
      makePosition({ entryPrice: 5.2, currentPrice: 1.0, premiumStopPct: 0.7554 }),
      0.60,
    );
    expect(r?.premiumStopPct).toBe(0.7554);
  });

  it('leaves the field off every other alert type', () => {
    // Only PREMIUM_STOP has a threshold percentage; a stamp anywhere else
    // would be a number with no meaning.
    const results = scanPortfolio(
      [makePosition({ entryPrice: 5, currentPrice: 1.75, stop: 95, currentStockPrice: 90 })],
      { premiumStopPct: 0.60 },
    );
    for (const r of results.filter((x) => x.alertType !== 'PREMIUM_STOP')) {
      expect(r.premiumStopPct).toBeUndefined();
    }
  });
});

// ── STOP-SEMANTICS-2026-10-02 ───────────────────────────────────────────────
import { percentStopThresholdPrice, pythonRound4 } from '@/lib/premiumStop';

describe('STOP-SEMANTICS -- a short stock stop fires on a RISE', () => {
  // Far-away stop and no targets, so only PREMIUM_STOP can fire.
  const stockPos = (direction: 'Bullish' | 'Bearish', currentPrice: number) => makePosition({
    contract: 'NVDA|STOCK', direction, entryPrice: 100, currentPrice, currentStockPrice: currentPrice,
    stop: direction === 'Bearish' ? 1000 : 1, premiumStopPct: 0.1, dteRemaining: 0, dteTotal: 0,
  });
  const premium = (p: AlertPosition) => scanPortfolio([p]).filter((r) => r.alertType === 'PREMIUM_STOP');
  const t = percentStopThresholdPrice(100, 0.1, true);   // 110.00000000000001 -- the COMPUTED one

  it('fires at the computed threshold and not a hair below it', () => {
    const [a] = premium(stockPos('Bearish', t));
    expect(a).toBeDefined();
    expect(premium(stockPos('Bearish', 110))).toEqual([]);   // 110.00 < 110.00000000000001 (N6)
  });

  it('does not fire on a fall (the old rule)', () => {
    expect(premium(stockPos('Bearish', 85))).toEqual([]);
  });

  it('a price-only reason, the direction-aware referenceValue, and the stamped side', () => {
    const [a] = premium(stockPos('Bearish', 112.5));
    expect(a!.reason).toBe('Stock stop — NVDA at $112.50');
    expect(a!.referenceValue).toBe(pythonRound4(t));
    expect(a!.stopSide).toBe('short-stock');
  });

  it('regression guard: a long stock is unchanged', () => {
    const [a] = premium(stockPos('Bullish', 90));
    expect(a!.stopSide).toBe('long-stock');
    expect(a!.reason).toMatch(/^Premium stop — NVDA down/);
    expect(premium(stockPos('Bullish', 120))).toEqual([]);
  });

  it('regression guard: a Bearish OPTION (a long put) still fires on a fall', () => {
    const put = (currentPrice: number) => makePosition({
      contract: 'NVDA|100|2026-12-18|P', direction: 'Bearish', entryPrice: 5, currentPrice,
      currentStockPrice: 100, stop: 1000, premiumStopPct: 0.1,
    });
    const [a] = premium(put(4.4));
    expect(a!.stopSide).toBe('option');
    expect(premium(put(5.6))).toEqual([]);
  });
});
