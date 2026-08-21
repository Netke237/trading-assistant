import { scanPortfolio, type AlertPosition } from '@/lib/alertEngine';
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

  it('fires PREMIUM_STOP when pnlPct crosses the 60% stop threshold', () => {
    const position = makePosition({ pnlPct: -65 });  // beyond -60% threshold
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(true);
  });

  it('does NOT fire PREMIUM_STOP when loss is below threshold', () => {
    const position = makePosition({ pnlPct: -50 });  // not yet at -60%
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
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
