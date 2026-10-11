/**
 * STOCK-PRES-P5-PREBREAKOUT Task 2 — the Pre-Breakout page in the Options
 * layout: "How this page works" (M14), the side "Scan" column (M4, M5),
 * "What you can do" (M15); every printed threshold equals the one the backend
 * applied to the rows shown (plan rounds 1-2: F1, F3, R2-1, R2-2, R2-3) and
 * Set Alert uses the clicked row's direction (F2).
 * Plan: docs/superpowers/plans/2026-10-11-stock-pres-p5-prebreakout-plan.md
 */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import Step4PreBreakoutPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { api } from '@/lib/api';
import { __resetScanThresholdsForTests } from '../scanThresholds';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-prebreakout',
}));
jest.mock('@/lib/api', () => ({
  api: { prebreakoutScan: jest.fn(), fibPullbackScan: jest.fn(), postStockScan: jest.fn() },
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));
jest.mock('@/components/organisms/CompositeAlertDialog', () => ({
  CompositeAlertDialog: ({ symbol, direction }: { symbol: string; direction: string }) =>
    require('react').createElement('div', {
      'data-testid': 'alert-dialog', 'data-symbol': symbol, 'data-direction': direction,
    }),
}));
// CSS modules map to an empty object under Jest; name Data's tone classes so
// the Fib Distance cell's tone can be asserted.
jest.mock('@/components/primitives/Data.module.css', () => ({
  tonePass: 'tonePass',
  toneCaution: 'toneCaution',
}));

const m = (f: unknown) => f as jest.Mock;

const PB_ROW = {
  symbol: 'AMZN', direction: 'Bullish', confidence: 53,
  metrics: { atr_ratio: 0.62, range_ratio: 1.84, vol_ratio: 0.71, proximity_pct: 0.9, swing_level: 201.4 },
};
const FIB_ROW = {
  symbol: 'PG', direction: 'Bullish', fib_level_hit: '61.8', fib_dist_pct: 1.8, at_level: true, confidence: 80,
};

const EXPLANATION =
  'Three scans. Results are for watching and alerts; there is no trade card for this scanner (exits not designed yet).';
const WHAT_YOU_CAN_DO = '☆ Watch, 📈 Open in Chart (new tab), Set Alert. No trade card.';

function setDirection(direction: 'Bullish' | 'Bearish') {
  useScanStore.setState({ context: { universe: 'SP500', direction, horizon: 'Swing (5–15d)' } } as never);
}

/** The number input inside the panel <label> whose caption is `caption`. */
function input(caption: string): HTMLInputElement {
  return screen.getByText(caption).closest('label')!.querySelector('input')!;
}
function type(caption: string, value: string) {
  fireEvent.change(input(caption), { target: { value } });
}
function fibLevelBox(level: string): HTMLInputElement {
  return screen.getByText(level).closest('label')!.querySelector('input')!;
}
const runScan = () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' }));
const toFib = () => fireEvent.click(screen.getByRole('button', { name: 'Fib Pullback' }));
const atrTitle = () => screen.getByText('0.62').getAttribute('title') ?? '';
const proximityTitle = () => screen.getByText('0.9').getAttribute('title') ?? '';
const fibDistance = () => screen.getByText('1.8%');

async function scanPreBreakout() {
  m(api.prebreakoutScan).mockResolvedValueOnce([PB_ROW]);
  runScan();
  await screen.findByText('0.62');
}
async function scanFib() {
  m(api.fibPullbackScan).mockResolvedValueOnce([FIB_ROW]);
  runScan();
  await screen.findByText('1.8%');
}
/** Leave the page and come back: params reset to defaults, rows kept in the store. */
function remount(unmount: () => void) {
  unmount();
  return render(<Step4PreBreakoutPage />);
}
const lastPreBreakoutOverride = () => m(api.prebreakoutScan).mock.calls.at(-1)![2] as Record<string, unknown>;
const lastFibOverride = () => m(api.fibPullbackScan).mock.calls.at(-1)![2] as Record<string, unknown>;

beforeEach(() => {
  __resetScanThresholdsForTests();
  m(api.prebreakoutScan).mockReset();
  m(api.fibPullbackScan).mockReset();
  m(api.postStockScan).mockReset();
  useUniverseStore.setState({ pick: 'SP500' } as never);
  useScanStore.setState({ preBreakoutResults: [], fibPullbackResults: [] } as never);
  setDirection('Bullish');
});

describe('How this page works (M14)', () => {
  it('is a collapsed <summary> and its text is in the document', () => {
    render(<Step4PreBreakoutPage />);
    const summary = screen.getByText('How this page works');
    expect(summary.tagName).toBe('SUMMARY');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(EXPLANATION)).toBeInTheDocument();
  });
});

describe('Side column "Scan" (M4, M5, M15)', () => {
  it('Pre-Breakout: textarea, Run Scan and the Pre-Breakout panel are in the aside; the table is not', () => {
    useScanStore.setState({ preBreakoutResults: [PB_ROW] } as never);
    render(<Step4PreBreakoutPage />);
    const aside = screen.getByRole('complementary', { name: 'Scan' });
    expect(within(aside).getByRole('heading', { name: 'Scan' })).toBeInTheDocument();
    expect(within(aside).getByPlaceholderText(
      'Leave blank to use universe (S&P 500) · or enter specific symbols to override',
    )).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'Run Scan' })).toBeInTheDocument();
    expect(within(aside).getByText('Scan parameters')).toBeInTheDocument();
    expect(within(aside).getByText('ATR compression ratio')).toBeInTheDocument();
    expect(within(aside).getByRole('heading', { name: 'What you can do' })).toBeInTheDocument();
    expect(within(aside).getByText(WHAT_YOU_CAN_DO)).toBeInTheDocument();
    // one textarea / Run Scan, as today
    expect(screen.getAllByPlaceholderText(/Leave blank to use universe/)).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Run Scan' })).toHaveLength(1);
    // the table and the mode description are in the main column
    expect(screen.getByText('ATR Ratio')).toBeInTheDocument();
    expect(within(aside).queryByText('ATR Ratio')).toBeNull();
    expect(within(aside).queryByText('0.62')).toBeNull();
    expect(within(aside).queryByText(/Stocks coiling near a key resistance level/)).toBeNull();
  });

  it('Pullback: the "Scan parameters" block with its Reset is in the aside; the description is not', () => {
    render(<Step4PreBreakoutPage />);
    fireEvent.click(screen.getByRole('button', { name: /^Pullback to EMA/ }));
    const aside = screen.getByRole('complementary', { name: 'Scan' });
    expect(within(aside).getByText('Scan parameters')).toBeInTheDocument();
    expect(within(aside).getByText('Signal MA — EMA 50')).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'Reset to defaults' })).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'Run Scan' })).toBeInTheDocument();
    expect(within(aside).queryByText('ATR compression ratio')).toBeNull();
    expect(screen.getByText(/Trending stocks that have pulled back to EMA 50/)).toBeInTheDocument();
    expect(within(aside).queryByText(/Trending stocks that have pulled back/)).toBeNull();
  });

  it('Fib: the Fib panel is in the aside; the table is not', () => {
    useScanStore.setState({ fibPullbackResults: [FIB_ROW] } as never);
    render(<Step4PreBreakoutPage />);
    toFib();
    const aside = screen.getByRole('complementary', { name: 'Scan' });
    expect(within(aside).getByText('Scan parameters')).toBeInTheDocument();
    expect(within(aside).getByText('Tolerance')).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'Reset to defaults' })).toBeInTheDocument();
    expect(within(aside).queryByText('ATR compression ratio')).toBeNull();
    expect(screen.getByText('Fib Level')).toBeInTheDocument();
    expect(within(aside).queryByText('Fib Level')).toBeNull();
    expect(within(aside).queryByText('1.8%')).toBeNull();
  });
});

describe('Thresholds follow the scan that produced the rows (gate case)', () => {
  it('Pre-Breakout: ATR 0.70 scanned, page left and re-entered → the tooltip still says 0.70', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    type('ATR compression ratio', '0.7');
    await scanPreBreakout();
    expect(lastPreBreakoutOverride().atr_compression_ratio).toBe(0.7);
    expect(atrTitle()).toContain('Must be below 0.70 to pass');
    remount(unmount);
    expect(input('ATR compression ratio')).toHaveValue(0.85); // params back to defaults
    expect(atrTitle()).toContain('Must be below 0.70 to pass');
    expect(atrTitle()).not.toContain('0.85');
  });

  it('Fib: tolerance 2% scanned, remount → Distance tooltip ≤2.0% and a 1.8% row is pass-toned', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    toFib();
    type('Tolerance', '2');
    await scanFib();
    expect(lastFibOverride().fib_tolerance_pct).toBe(0.02);
    remount(unmount);
    toFib();
    expect(input('Tolerance')).toHaveValue(1.5);
    expect(fibDistance().getAttribute('title')).toContain('≤2.0% (the tolerance band');
    expect(fibDistance()).toHaveClass('tonePass');
    expect(fibDistance()).not.toHaveClass('toneCaution');
  });

  it('with no scan this page load the tooltips read the live params, as today', () => {
    useScanStore.setState({ preBreakoutResults: [PB_ROW], fibPullbackResults: [FIB_ROW] } as never);
    render(<Step4PreBreakoutPage />);
    expect(atrTitle()).toContain('Current ATR ÷ 20-bar average ATR.');
    expect(atrTitle()).toContain('Must be below 0.85 to pass');
    expect(screen.getByText('0.71').getAttribute('title')).toContain('Must be below 0.90 to pass');
    expect(proximityTitle()).toContain('Must be within 8.0% to pass');
    toFib();
    expect(fibDistance().getAttribute('title')).toContain('≤1.5% (the tolerance band');
    expect(fibDistance()).toHaveClass('toneCaution');
  });

  it('a param change while a scan is pending: rows pair with the params they were judged on', async () => {
    render(<Step4PreBreakoutPage />);
    type('ATR compression ratio', '0.7');
    let resolve!: (rows: unknown) => void;
    m(api.prebreakoutScan).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    runScan();
    expect(lastPreBreakoutOverride().atr_compression_ratio).toBe(0.7);
    type('ATR compression ratio', '0.8');
    expect(useScanStore.getState().preBreakoutResults).toEqual([]);
    await act(async () => { resolve([PB_ROW]); });
    expect(atrTitle()).toContain('Must be below 0.70 to pass');
  });
});

describe('Off-step values are printed as applied (F3)', () => {
  it('ATR 0.875, range bars 10.5, range × ATR 2.75, proximity 7.25 %', async () => {
    render(<Step4PreBreakoutPage />);
    type('ATR compression ratio', '0.875');
    type('Range lookback bars', '10.5');
    type('Range / ATR multiplier', '2.75');
    type('Proximity to key level', '7.25');
    await scanPreBreakout();
    const o = lastPreBreakoutOverride();
    expect(o.atr_compression_ratio).toBe(0.875);
    expect(o.range_atr_mult).toBe(2.75);
    expect(o.resistance_proximity_pct).toBe(0.0725);
    expect(o.range_lookback_bars).toBe(10); // R2-3: integer keys stored truncated
    expect(atrTitle()).toContain('Must be below 0.875 to pass');
    expect(proximityTitle()).toContain('Must be within 7.25% to pass');
  });
});

describe('Round-2 cases (R2-1, R2-2, R2-3)', () => {
  it('R2-1: Fib levels [50] scanned → remount → the description reads (50%); with no Fib rows (38.2%, 61.8%)', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    toFib();
    expect(screen.getByText(/a key Fibonacci level \(38\.2%, 61\.8%\) after/)).toBeInTheDocument();
    fireEvent.click(fibLevelBox('50%'));
    fireEvent.click(fibLevelBox('38.2%'));
    fireEvent.click(fibLevelBox('61.8%'));
    await scanFib();
    expect(lastFibOverride().fib_levels).toEqual([50]);
    remount(unmount);
    toFib();
    expect(screen.getByText(/a key Fibonacci level \(50%\) after/)).toBeInTheDocument();
    act(() => useScanStore.getState().setFibPullbackResults([]));
    expect(screen.getByText(/a key Fibonacci level \(38\.2%, 61\.8%\) after/)).toBeInTheDocument();
  });

  it('R2-2: ATR average lookback 30 → the panel help line and, after a remount, the tooltip say 30-bar', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    expect(screen.getByText(/fraction of the 20-bar average ATR\./)).toBeInTheDocument();
    type('ATR average lookback', '30');
    expect(screen.getByText(/fraction of the 30-bar average ATR\./)).toBeInTheDocument();
    await scanPreBreakout();
    expect(lastPreBreakoutOverride().atr_avg_lookback).toBe(30);
    remount(unmount);
    expect(atrTitle()).toContain('Current ATR ÷ 30-bar average ATR.');
    // the Vol tooltip's 20-bar is the backend's fixed volume average
    expect(screen.getByText('0.71').getAttribute('title')).toContain('Last bar volume ÷ 20-bar average volume.');
  });

  it('R2-3: range bars typed 10.5 → the input shows 10 and the request carries 10', async () => {
    render(<Step4PreBreakoutPage />);
    type('Range lookback bars', '10.5');
    expect(input('Range lookback bars')).toHaveValue(10);
    await scanPreBreakout();
    expect(lastPreBreakoutOverride().range_lookback_bars).toBe(10);
  });

  it('R2-3: other integer keys are truncated on store too', async () => {
    render(<Step4PreBreakoutPage />);
    type('ATR average lookback', '25.9');
    type('Swing lookback', '55.5');
    expect(input('ATR average lookback')).toHaveValue(25);
    expect(input('Swing lookback')).toHaveValue(55);
    await scanPreBreakout();
    expect(lastPreBreakoutOverride().atr_avg_lookback).toBe(25);
    expect(lastPreBreakoutOverride().swing_lookback).toBe(55);
    toFib();
    type('Swing lookback', '120.5');
    type('EMA trend filter', '20.5');
    expect(input('Swing lookback')).toHaveValue(120);
    expect(input('EMA trend filter')).toHaveValue(20);
    await scanFib();
    expect(lastFibOverride().fib_swing_lookback).toBe(120);
    expect(lastFibOverride().ema_filter_period).toBe(20);
  });

  it('R2-3: proximity typed 7.25 keeps "7.25", sends 0.0725, the tooltip says 7.25%', async () => {
    render(<Step4PreBreakoutPage />);
    type('Proximity to key level', '7.25');
    expect(input('Proximity to key level')).toHaveValue(7.25);
    await scanPreBreakout();
    expect(lastPreBreakoutOverride().resistance_proximity_pct).toBe(0.0725);
    expect(proximityTitle()).toContain('Must be within 7.25% to pass');
  });

  it('R2-3: Fib tolerance typed 1.25 keeps "1.25" and sends 0.0125', async () => {
    render(<Step4PreBreakoutPage />);
    toFib();
    type('Tolerance', '1.25');
    expect(input('Tolerance')).toHaveValue(1.25);
    await scanFib();
    expect(lastFibOverride().fib_tolerance_pct).toBe(0.0125);
    expect(fibDistance().getAttribute('title')).toContain('≤1.25% (the tolerance band');
  });
});

describe('The Pre-Breakout description follows the scan (F1)', () => {
  it('proximity 12 % scanned → remount → "12.0%" while the rows show; "8.0%" with no rows', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    expect(screen.getByText(/close within 8\.0% of swing high\./)).toBeInTheDocument();
    type('Proximity to key level', '12');
    expect(screen.getByText(/close within 12\.0% of swing high\./)).toBeInTheDocument(); // live, no rows
    await scanPreBreakout();
    remount(unmount);
    expect(screen.getByText(/close within 12\.0% of swing high\./)).toBeInTheDocument();
    act(() => useScanStore.getState().setPreBreakoutResults([]));
    expect(screen.getByText(/close within 8\.0% of swing high\./)).toBeInTheDocument();
  });
});

describe('Set Alert uses the clicked row\'s direction (F2)', () => {
  it('Pre-Breakout: Bullish rows kept after a switch to Bearish save a Bullish watch', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    await scanPreBreakout();
    expect(m(api.prebreakoutScan).mock.calls[0][1]).toBe('Bullish');
    unmount(); // leave the page, switch to Bearish on Step 3, come back
    setDirection('Bearish');
    render(<Step4PreBreakoutPage />);
    expect(screen.getByText(/· Bearish$/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Set Alert' }));
    const dialog = screen.getByTestId('alert-dialog');
    expect(dialog).toHaveAttribute('data-symbol', 'AMZN');
    expect(dialog).toHaveAttribute('data-direction', 'Bullish');
  });

  it('Fib "+": Bullish rows kept after a switch to Bearish save a Bullish watch', async () => {
    const { unmount } = render(<Step4PreBreakoutPage />);
    toFib();
    await scanFib();
    unmount(); // leave the page, switch to Bearish on Step 3, come back
    setDirection('Bearish');
    render(<Step4PreBreakoutPage />);
    toFib();
    fireEvent.click(screen.getByTitle('Set alert'));
    const dialog = screen.getByTestId('alert-dialog');
    expect(dialog).toHaveAttribute('data-symbol', 'PG');
    expect(dialog).toHaveAttribute('data-direction', 'Bullish');
  });

  it('a row from the current context gets the same direction as today', async () => {
    setDirection('Bearish');
    render(<Step4PreBreakoutPage />);
    m(api.prebreakoutScan).mockResolvedValueOnce([{ ...PB_ROW, direction: 'Bearish' }]);
    runScan();
    await screen.findByText('0.62');
    fireEvent.click(screen.getByRole('button', { name: 'Set Alert' }));
    expect(screen.getByTestId('alert-dialog')).toHaveAttribute('data-direction', 'Bearish');
  });
});
