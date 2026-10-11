/**
 * STOCK-PRES-P5-PREBREAKOUT Task 3 — Pre-Breakout and Fib rows expand to
 * details: "Why it's a setup" (row values against the scanned thresholds,
 * M10), the confidence breakdown (P1 field, M11), the mini chart with price
 * lines (M12) and the Fib swing low / high with the level price computed as
 * `strategy_engine._fibonacci_pullback_detail` does (M13). No entry / stop /
 * target / exit / position wording (D14). The Pullback table gets no details.
 * Plan: docs/superpowers/plans/2026-10-11-stock-pres-p5-prebreakout-plan.md
 */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import Step4PreBreakoutPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { api } from '@/lib/api';
import { PREBREAKOUT_DEFAULTS } from '@/components/organisms/PreBreakoutParamsPanel';
import { __resetScanThresholdsForTests, rememberPreBreakoutScan } from '../scanThresholds';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-prebreakout',
}));
jest.mock('@/lib/api', () => ({
  api: {
    prebreakoutScan: jest.fn(), fibPullbackScan: jest.fn(), postStockScan: jest.fn(), getCandles: jest.fn(),
  },
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));
jest.mock('@/components/organisms/CompositeAlertDialog', () => ({ CompositeAlertDialog: () => null }));
const mockChart = jest.fn();
jest.mock('@/components/organisms/CandlestickChart', () => ({
  CandlestickChart: (props: unknown) => {
    mockChart(props);
    return require('react').createElement('div', { 'data-testid': 'mini-chart' });
  },
}));

const m = (f: unknown) => f as jest.Mock;

const BREAKDOWN = {
  fib_used: false,
  weights: { atr: 0.3, vol: 0.25, proximity: 0.45 },
  components: {
    atr: { score: 27.06, weight: 0.3, contribution: 8.12 },
    vol: { score: 21.11, weight: 0.25, contribution: 5.28 },
    proximity: { score: 88.75, weight: 0.45, contribution: 39.94 },
  },
  unrounded: 53.34,
  confidence: 53,
};
const AMZN = {
  symbol: 'AMZN', direction: 'Bullish', confidence: 53,
  metrics: { atr_ratio: 0.62, range_ratio: 1.84, vol_ratio: 0.71, proximity_pct: 0.9, swing_level: 201.4 },
  confidence_breakdown: BREAKDOWN,
};
const CRM = {
  symbol: 'CRM', direction: 'Bullish', confidence: 41,
  metrics: { atr_ratio: 0.8, range_ratio: 2.1, vol_ratio: 0.85, proximity_pct: 3.2, swing_level: 330 },
  confidence_breakdown: BREAKDOWN,
};
const FIB = {
  symbol: 'PG', direction: 'Bullish', fib_level_hit: '61.8', fib_dist_pct: 1.2, at_level: true, confidence: 80,
  fib_swing: { low: 152.1, high: 171.8 },
};

const CANDLES_AMZN = [{ time: 1, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }];
const CANDLES_CRM = [{ time: 2, open: 3, high: 4, low: 2.5, close: 3.5, volume: 20 }];

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const toggle = (symbol: string) => screen.getByRole('button', { name: new RegExp(`^(Show|Hide) details for ${symbol}$`) });
const expand = (symbol: string) => fireEvent.click(screen.getByRole('button', { name: `Show details for ${symbol}` }));
const details = (symbol: string) => screen.getByRole('region', { name: `Details for ${symbol}` });
const toFib = () => fireEvent.click(screen.getByRole('button', { name: 'Fib Pullback' }));
const lastChartProps = () => mockChart.mock.calls.at(-1)![0] as {
  data: unknown; height: number; showToggles: boolean; defaultIndicators: unknown; priceLines: unknown;
};

beforeEach(() => {
  __resetScanThresholdsForTests();
  for (const f of [api.prebreakoutScan, api.fibPullbackScan, api.postStockScan, api.getCandles]) m(f).mockReset();
  m(api.getCandles).mockResolvedValue(CANDLES_AMZN);
  mockChart.mockClear();
  useUniverseStore.setState({ pick: 'SP500' } as never);
  useScanStore.setState({
    preBreakoutResults: [], fibPullbackResults: [],
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
  } as never);
});

describe('Pre-Breakout row details', () => {
  it("Why it's a setup: the four exact lines at the default scanned params", async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    const d = within(details('AMZN'));
    expect(d.getByText("Why it's a setup")).toBeInTheDocument();
    expect(d.getByText('ATR ratio 0.62 · must be below 0.85')).toBeInTheDocument();
    expect(d.getByText('Range ratio 1.84 · 10-bar range must be below 3.0 × ATR')).toBeInTheDocument();
    expect(d.getByText('Volume ratio 0.71 · must be below 0.90')).toBeInTheDocument();
    expect(d.getByText('0.9% from swing high $201.40 · within 8.0%')).toBeInTheDocument();
    expect(d.getByText('Same facts as the hover tooltips.')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });

  it('confidence breakdown rows in the order proximity, atr, vol, with weights and rounded scores', async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    const d = within(details('AMZN'));
    expect(d.getByText('Confidence 53%')).toBeInTheDocument();
    const meters = d.getAllByRole('meter');
    expect(meters.map((el) => el.getAttribute('aria-label'))).toEqual([
      'Proximity score', 'ATR compression score', 'Volume quiet score',
    ]);
    const rowText = meters.map((el) => el.closest('[data-breakdown-row]')!.textContent);
    expect(rowText[0]).toBe('Proximity45% of confidence89');
    expect(rowText[1]).toBe('ATR compression30% of confidence27');
    expect(rowText[2]).toBe('Volume quiet25% of confidence21');
    expect(meters[0]).toHaveAttribute('aria-valuenow', '88.75');
    expect((meters[0].firstChild as HTMLElement).style.width).toBe('88.75%');
    expect(d.queryByText('Fib level')).toBeNull();
    await screen.findByTestId('mini-chart');
  });

  it('the mini chart is fetched on expand and gets one Swing high price line', async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN] } as never);
    render(<Step4PreBreakoutPage />);
    expect(api.getCandles).not.toHaveBeenCalled();
    expand('AMZN');
    expect(api.getCandles).toHaveBeenCalledWith('AMZN');
    expect(within(details('AMZN')).getByText('Loading chart…')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
    const p = lastChartProps();
    expect(p.data).toBe(CANDLES_AMZN);
    expect(p.height).toBe(180);
    expect(p.showToggles).toBe(false);
    expect(p.defaultIndicators).toEqual([]);
    expect(p.priceLines).toEqual([{ price: 201.4, title: 'Swing high' }]);
    expect(within(details('AMZN')).getByText('📈 Open in Chart and Set Alert stay on the row.')).toBeInTheDocument();
  });

  it('a failed candle fetch shows "Chart unavailable"', async () => {
    m(api.getCandles).mockRejectedValueOnce(new Error('boom'));
    useScanStore.setState({ preBreakoutResults: [AMZN] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    expect(await within(details('AMZN')).findByText('Chart unavailable')).toBeInTheDocument();
    expect(mockChart).not.toHaveBeenCalled();
  });

  it('a Bearish row says "swing low" and the price line is "Swing low"', async () => {
    useScanStore.setState({ preBreakoutResults: [{ ...AMZN, direction: 'Bearish' }] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    expect(within(details('AMZN')).getByText('0.9% from swing low $201.40 · within 8.0%')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
    expect(lastChartProps().priceLines).toEqual([{ price: 201.4, title: 'Swing low' }]);
  });

  it('thresholds come from the remembered scan (ATR 0.70, proximity 5 %)', async () => {
    rememberPreBreakoutScan({ ...PREBREAKOUT_DEFAULTS, atrCompressionRatio: 0.7, resistanceProximityPct: 0.05 });
    useScanStore.setState({ preBreakoutResults: [AMZN] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    const d = within(details('AMZN'));
    expect(d.getByText('ATR ratio 0.62 · must be below 0.70')).toBeInTheDocument();
    expect(d.getByText('0.9% from swing high $201.40 · within 5.0%')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });

  it('no confidence_breakdown → the re-run line; range_ratio absent → "Range ratio — · …"; no crash', async () => {
    const { confidence_breakdown: _omit, ...noBreakdown } = AMZN;
    const { range_ratio: _r, ...metrics } = AMZN.metrics;
    useScanStore.setState({ preBreakoutResults: [{ ...noBreakdown, metrics }] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    const d = within(details('AMZN'));
    expect(d.getByText('Confidence breakdown is not in this result — re-run the scan.')).toBeInTheDocument();
    expect(d.queryAllByRole('meter')).toHaveLength(0);
    expect(d.getByText('Range ratio — · 10-bar range must be below 3.0 × ATR')).toBeInTheDocument();
    expect(d.getByText('ATR ratio 0.62 · must be below 0.85')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });

  it('confidence_breakdown null → the re-run line', async () => {
    useScanStore.setState({ preBreakoutResults: [{ ...AMZN, confidence_breakdown: null }] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    expect(within(details('AMZN')).getByText('Confidence breakdown is not in this result — re-run the scan.')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });
});

describe('Fib row details', () => {
  function openFib(row: Record<string, unknown>) {
    useScanStore.setState({ fibPullbackResults: [row] } as never);
    render(<Step4PreBreakoutPage />);
    toFib();
    expand('PG');
    return within(details('PG'));
  }

  it('Bullish: swing low, swing high and the 61.8% level price high − r × (high − low)', async () => {
    const d = openFib(FIB);
    expect(d.getByText('Swing measured from')).toBeInTheDocument();
    // 171.8 − 0.618 × 19.7 = 159.6254
    expect(d.getByText('Swing low $152.10 · Swing high $171.80 · 61.8% level $159.63')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
    expect(lastChartProps().priceLines).toEqual([
      { price: 152.1, title: 'Swing low' },
      { price: 171.8, title: 'Swing high' },
      { price: 171.8 - 0.618 * (171.8 - 152.1), title: '61.8% level' },
    ]);
  });

  it('Bearish: the level price is low + r × (high − low)', async () => {
    const d = openFib({ ...FIB, direction: 'Bearish' });
    // 152.1 + 12.1746 = 164.2746
    expect(d.getByText('Swing low $152.10 · Swing high $171.80 · 61.8% level $164.27')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });

  it("an unknown level label → no level price, never guessed", async () => {
    const d = openFib({ ...FIB, fib_level_hit: '99' });
    expect(d.getByText('Swing low $152.10 · Swing high $171.80')).toBeInTheDocument();
    expect(d.queryByText(/level \$/)).toBeNull();
    await screen.findByTestId('mini-chart');
    expect(lastChartProps().priceLines).toEqual([
      { price: 152.1, title: 'Swing low' },
      { price: 171.8, title: 'Swing high' },
    ]);
  });

  it('fib_swing null → the re-run line; absent → the same', async () => {
    const d = openFib({ ...FIB, fib_swing: null });
    expect(d.getByText('Swing low/high is not in this result — re-run the scan.')).toBeInTheDocument();
    expect(d.queryByText(/Swing low \$/)).toBeNull();
    await screen.findByTestId('mini-chart');
    expect(lastChartProps().priceLines).toEqual([]);
  });

  it('fib_swing absent → the re-run line', async () => {
    const { fib_swing: _s, ...noSwing } = FIB;
    const d = openFib(noSwing);
    expect(d.getByText('Swing low/high is not in this result — re-run the scan.')).toBeInTheDocument();
    await screen.findByTestId('mini-chart');
  });
});

describe('Toggle semantics', () => {
  it('one open row; aria-expanded flips; opening another closes the first', async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN, CRM] } as never);
    render(<Step4PreBreakoutPage />);
    expect(toggle('AMZN')).toHaveAttribute('aria-expanded', 'false');
    expect(toggle('AMZN')).toHaveTextContent('▸');
    expand('AMZN');
    expect(toggle('AMZN')).toHaveAttribute('aria-expanded', 'true');
    expect(toggle('AMZN')).toHaveAccessibleName('Hide details for AMZN');
    expect(toggle('AMZN')).toHaveTextContent('▾');
    expect(screen.getAllByRole('region', { name: /^Details for / })).toHaveLength(1);
    expand('CRM');
    expect(toggle('AMZN')).toHaveAttribute('aria-expanded', 'false');
    expect(toggle('CRM')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('region', { name: 'Details for AMZN' })).toBeNull();
    expect(details('CRM')).toBeInTheDocument();
    fireEvent.click(toggle('CRM'));
    expect(toggle('CRM')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('region', { name: /^Details for / })).toBeNull();
    await act(async () => {});
  });

  it('changing mode or a new result set closes the open row', async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN, CRM] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    toFib();
    fireEvent.click(screen.getByRole('button', { name: 'Pre-Breakout' }));
    expect(toggle('AMZN')).toHaveAttribute('aria-expanded', 'false');
    expand('AMZN');
    act(() => useScanStore.getState().setPreBreakoutResults([AMZN, CRM] as never));
    expect(toggle('AMZN')).toHaveAttribute('aria-expanded', 'false');
    await act(async () => {});
  });

  it('Pullback rows have no details toggle (the Pre-Breakout and Fib rows do)', async () => {
    m(api.postStockScan).mockResolvedValueOnce({
      scan_id: 'S', timestamp: '2026-10-11T10:00:00+00:00', rejected: [],
      candidates: [{ symbol: 'MSFT', company: 'Microsoft', direction: 'Bullish', stock_score: 72, price: 410.5, confidence: 64 }],
    });
    useScanStore.setState({ preBreakoutResults: [AMZN], fibPullbackResults: [FIB] } as never);
    render(<Step4PreBreakoutPage />);
    expect(toggle('AMZN')).toBeInTheDocument(); // positive control
    toFib();
    expect(toggle('PG')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Pullback to EMA/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Run Scan' }));
    await screen.findByText('Microsoft');
    expect(screen.queryByRole('button', { name: /details for/ })).toBeNull();
  });
});

describe('Stale chart response', () => {
  it('expand AMZN (deferred), expand CRM, resolve AMZN → the chart never gets AMZN candles', async () => {
    const amzn = deferred<unknown>();
    const crm = deferred<unknown>();
    m(api.getCandles).mockImplementation((s: string) => (s === 'AMZN' ? amzn.promise : crm.promise));
    useScanStore.setState({ preBreakoutResults: [AMZN, CRM] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    expand('CRM');
    await act(async () => { amzn.resolve(CANDLES_AMZN); });
    expect(within(details('CRM')).getByText('Loading chart…')).toBeInTheDocument();
    expect(mockChart.mock.calls.some(([p]) => (p as { data: unknown }).data === CANDLES_AMZN)).toBe(false);
    await act(async () => { crm.resolve(CANDLES_CRM); });
    expect(lastChartProps().data).toBe(CANDLES_CRM);
    expect(mockChart.mock.calls.some(([p]) => (p as { data: unknown }).data === CANDLES_AMZN)).toBe(false);
  });
});

describe('No entry / stop / target / exit / position wording (D14)', () => {
  const FORBIDDEN = /\b(entry|stop|target|exit|position)\b/i;

  it('Pre-Breakout details (with and without breakdown, chart loaded and failed)', async () => {
    useScanStore.setState({ preBreakoutResults: [AMZN, { ...CRM, confidence_breakdown: undefined }] } as never);
    render(<Step4PreBreakoutPage />);
    expand('AMZN');
    await screen.findByTestId('mini-chart');
    expect(details('AMZN').textContent).not.toMatch(FORBIDDEN);
    m(api.getCandles).mockRejectedValueOnce(new Error('x'));
    expand('CRM');
    await within(details('CRM')).findByText('Chart unavailable');
    expect(details('CRM').textContent).not.toMatch(FORBIDDEN);
  });

  it('Fib details (with and without swing)', async () => {
    useScanStore.setState({ fibPullbackResults: [FIB, { ...FIB, symbol: 'KO', fib_swing: null }] } as never);
    render(<Step4PreBreakoutPage />);
    toFib();
    expand('PG');
    await screen.findByTestId('mini-chart');
    expect(details('PG').textContent).not.toMatch(FORBIDDEN);
    expand('KO');
    await act(async () => {});
    expect(details('KO').textContent).not.toMatch(FORBIDDEN);
  });
});
