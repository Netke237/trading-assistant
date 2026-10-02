/**
 * P2 (premium stop & position editing) -- EditDrawer items P2-01, P2-04,
 * P2-11, P2-12, P2-13, R2-3, R2-7/R4-1. Plan:
 * docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md
 */
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditDrawer } from '../EditDrawer';
import { api } from '@/lib/api';
import { useSettingsStore } from '@/lib/settingsStore';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
    getExitPlan: jest.fn(),
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: '2026-08-27T00:00:00Z' }),
  },
}));

const noop = () => {};
const option = (o: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  symbol: 'AAPL', contract: 'AAPL 220C 05/16', direction: 'Bullish',
  entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
  entryPrice: 4.2, currentPrice: 4.5, currentStockPrice: 195,
  pnlDollar: 30, pnlPct: 7.1, stop: 185, targets: [], status: 'PASS',
  delta: 0.5, contracts: 2, recId: 'REC-P2',
  tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
  ...o,
});
const stock = (o: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
  entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
  entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
  stop: 182, targets: [
    { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
    { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
  ],
  status: 'PASS', contracts: 10, recId: 'REC-P2S',
  tradeCardSnapshot: { stock_score: 78, horizon: 'Swing (5–15d)', strategy: { strategy: 'pullback_ema' } },
  ...o,
});
const drawer = (position: PortfolioPosition, onChange: (p: Partial<PortfolioPosition>) => void = noop) =>
  render(<EditDrawer position={position} onClose={noop} onChange={onChange} onRemove={noop} />);

function LiveDrawer({ initial, onPatch }: {
  initial: PortfolioPosition; onPatch: (p: Partial<PortfolioPosition>) => void;
}) {
  const [pos, setPos] = useState(initial);
  return (
    <EditDrawer position={pos} onClose={noop} onRemove={noop}
      onChange={(patch) => { onPatch(patch); setPos((c) => ({ ...c, ...patch })); }} />
  );
}

beforeEach(() => { useSettingsStore.setState({ premiumStopPct: 0.6 }); });

describe('P2-01 -- a typed 0 in Current price points at closing at $0', () => {
  it('refuses 0 with the close-at-$0 message and writes nothing', () => {
    const onChange = jest.fn();
    drawer(option(), onChange);
    const price = screen.getByLabelText(/Current price/) as HTMLInputElement;
    fireEvent.change(price, { target: { value: '0' } });
    fireEvent.blur(price);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/to mark it worthless, close the position at \$0 \(Close button\)/)).toBeInTheDocument();
  });
});

describe('P2-04 -- a stored ratio outside the band is shown, not changed (Q9)', () => {
  it.each([[0.075, '7.5%'], [0.995, '99.5%']])('cautions at %s', (pct, label) => {
    const onChange = jest.fn();
    drawer(option({ premiumStopPct: pct }), onChange);
    expect(screen.getByText(new RegExp(`Stored at ${label.replace('.', '\\.')} of the fill — outside the 10%–99%.*It fires as stored\\.`))).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
  it('says nothing at 45%', () => {
    drawer(option({ premiumStopPct: 0.45 }));
    expect(screen.queryByText(/of the fill — outside/)).not.toBeInTheDocument();
  });
});

describe('P2-11 -- stop range without a live underlying is the hull of stop and scan ranges', () => {
  const typeStop = (initial: PortfolioPosition, value: string) => {
    const onPatch = jest.fn();
    render(<LiveDrawer initial={initial} onPatch={onPatch} />);
    const stopInput = screen.getByDisplayValue(String(initial.stop)) as HTMLInputElement;
    fireEvent.change(stopInput, { target: { value } });
    fireEvent.blur(stopInput);
    return onPatch;
  };
  const noLive = { currentStockPrice: undefined } as Partial<PortfolioPosition>;
  it('stop 14 / scan 145 -> 140 accepted', () => {
    expect(typeStop(option({ ...noLive, stop: 14, scanStockPrice: 145 }), '140')).toHaveBeenCalledWith({ stop: 140 });
  });
  it('stop 400 / scan 50 -> 380 accepted (refused against the scan range alone)', () => {
    expect(typeStop(option({ ...noLive, stop: 400, scanStockPrice: 50 }), '380')).toHaveBeenCalledWith({ stop: 380 });
  });
  it('stop 140 / scan 145 -> 1400 refused', () => {
    expect(typeStop(option({ ...noLive, stop: 140, scanStockPrice: 145 }), '1400')).not.toHaveBeenCalled();
    expect(screen.getByText(/Must be between 28\.00 and 435\.00/)).toBeInTheDocument();
  });
  it('a live underlying still decides alone', () => {
    expect(typeStop(option({ currentStockPrice: 145, stop: 400, scanStockPrice: 50 }), '500')).not.toHaveBeenCalled();
  });
});

describe('P2-12 -- a Monte Carlo re-run keeps the rung the user picked', () => {
  const stockRun = (targets: number[]) => (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
    targets: targets.map((price) => ({ price, probability: 0.5, expectedDays: 8 })),
    invalidation: { probability: 0.15, expectedDays: null }, horizonDays: 10, modelCaveat: null,
  });

  it('MC active, stamped at T2 -> the re-run stamps the new T2, and the selector shows it', async () => {
    stockRun([206, 216]);
    const onPatch = jest.fn();
    render(<LiveDrawer initial={stock({ activeTpMethod: 'monte_carlo', resolvedTpPrice: 215 })} onPatch={onPatch} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({ resolvedTpPrice: 216 })));
    expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toHaveTextContent('$216.00');
  });

  it('with 2R active, the Monte Carlo option still offers T1 and nothing is stamped', async () => {
    stockRun([206, 216]);
    const onChange = jest.fn();
    drawer(stock({ activeTpMethod: 'exit_plan_2r', resolvedTpPrice: 210 }), onChange);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toHaveTextContent('$206.00'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('option path: target % settings change between runs -> the label is gone, nearest price wins', async () => {
    const optRun = (rows: [number, number][]) => (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: rows.map(([pct, stockPrice]) => ({ pct, stockPrice, probability: 0.5, expectedDays: 5 })),
      invalidation: { probability: 0.2, expectedDays: null },
    });
    optRun([[0.25, 200], [0.5, 210]]);
    const onPatch = jest.fn();
    render(<LiveDrawer initial={option({ activeTpMethod: 'monte_carlo', resolvedTpPrice: 210 })} onPatch={onPatch} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({ resolvedTpPrice: 210 })));
    onPatch.mockClear();
    optRun([[0.3, 202], [0.6, 212]]);   // new labels T30%/T60%: 'T50%' no longer exists
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({ resolvedTpPrice: 212 })));
  });
});

describe('P2-13 -- a stock position names its percent stop as a stock level', () => {
  it('own and inherited', () => {
    const { unmount } = drawer(stock({ premiumStopPct: 0.45 }));
    expect(screen.getByText('Stock stop — fires 45% below entry')).toBeInTheDocument();
    unmount();
    drawer(stock({ premiumStopPct: null }));
    expect(screen.getByText('Stock stop — fires 60% (global) below entry')).toBeInTheDocument();
  });
  it('an option keeps "Premium stop"', () => {
    drawer(option({ premiumStopPct: 0.45 }));
    expect(screen.getByText('Premium stop — 45%')).toBeInTheDocument();
  });
});

describe('R2-3 / R2-7 / R4-1 -- stops that cannot fire are called out, and only those', () => {
  it('sub-cent threshold: a STORED 99% on a $0.50 entry (saved before the refusal)', () => {
    drawer(option({ entryPrice: 0.5, premiumStopPct: 0.99 }));
    expect(screen.getByText('Stored before sub-cent stops were refused; it can never fire — set a lower percent.')).toBeInTheDocument();
  });
  it('sub-cent threshold: an INHERITED global that is sub-cent at this entry', () => {
    useSettingsStore.setState({ premiumStopPct: 0.9 });
    drawer(option({ entryPrice: 0.05, premiumStopPct: null }));
    expect(screen.getByText('At this entry the global stop fires below $0.01 and can never fire — pin a lower percent.')).toBeInTheDocument();
  });
  it('no sub-cent caution at 99% on a $2.00 entry', () => {
    drawer(option({ entryPrice: 2, premiumStopPct: 0.99 }));
    expect(screen.queryByText(/below \$0\.01/)).not.toBeInTheDocument();
  });
  it('inherited global of 1.0 says the global can never fire (and not the sub-cent line)', () => {
    useSettingsStore.setState({ premiumStopPct: 1.0 });
    drawer(option({ premiumStopPct: null }));
    expect(screen.getByText('The global stop is 100% and can never fire — lower it in Settings.')).toBeInTheDocument();
    expect(screen.queryByText(/below \$0\.01/)).not.toBeInTheDocument();
  });
  it('inherited global of 0.995 makes no never-fires claim about the global', () => {
    useSettingsStore.setState({ premiumStopPct: 0.995 });
    drawer(option({ entryPrice: 10, premiumStopPct: null }));
    expect(screen.queryByText(/The global stop is 100%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/can never fire/)).not.toBeInTheDocument();
  });
});

// ── STOP-SEMANTICS-2026-10-02 ───────────────────────────────────────────────
describe('STOP-SEMANTICS -- a short stock stop fires on a RISE; a sub-cent stop is refused', () => {
  const short = (o: Partial<PortfolioPosition> = {}) => stock({ direction: 'Bearish', ...o });

  it('a short names its stop "above entry"; a long keeps "below entry"', () => {
    const { unmount } = drawer(short({ premiumStopPct: 0.45 }));
    expect(screen.getByText('Stock stop — fires 45% above entry')).toBeInTheDocument();
    unmount();
    drawer(stock({ premiumStopPct: 0.45 }));
    expect(screen.getByText('Stock stop — fires 45% below entry')).toBeInTheDocument();
  });

  it("a short's preview is the rise-side firing price", () => {
    // 190 x 1.45 = 275.5 -> fires at stock $275.50 (a long fires at $104.50).
    drawer(short({ premiumStopPct: 0.45 }));
    expect(screen.getByText('Fires at stock $275.50.')).toBeInTheDocument();
    expect(screen.queryByText('Fires at stock $104.50.')).not.toBeInTheDocument();
  });

  it('commit refuses a sub-cent stop with the reason and writes nothing', () => {
    const onChange = jest.fn();
    drawer(option({ entryPrice: 0.05, premiumStopPct: 0.5 }), onChange);
    const input = screen.getByLabelText('Premium stop percent') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '90' } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText('At this entry a 90% stop fires below $0.01 and could never fire — kept the previous value.')).toBeInTheDocument();
    expect(input.value).toBe('50');
  });

  it('a short at a sub-penny entry is never refused and never called sub-cent', () => {
    const onChange = jest.fn();
    drawer(short({ entryPrice: 0.05, premiumStopPct: 0.5 }), onChange);
    const input = screen.getByLabelText('Premium stop percent') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '90' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith({ premiumStopPct: 0.9 });
    expect(screen.queryByText(/below \$0\.01/)).not.toBeInTheDocument();
  });

  it('a global of 100% is not called never-firing for a short (it fires at 2x entry)', () => {
    useSettingsStore.setState({ premiumStopPct: 1.0 });
    drawer(short({ premiumStopPct: null }));
    expect(screen.queryByText(/The global stop is 100% and can never fire/)).not.toBeInTheDocument();
  });
});
