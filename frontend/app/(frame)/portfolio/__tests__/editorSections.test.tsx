import { fireEvent, render, screen, within } from '@testing-library/react';
import { EditDrawer } from '../EditDrawer';
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

function makeStockPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
    stop: 182, targets: [
      { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
      { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
    ],
    status: 'PASS', contracts: 10, recId: 'REC-1',
    tradeCardSnapshot: { stock_score: 78, horizon: 'Swing (5–15d)', strategy: { strategy: 'pullback_ema' } },
    ...overrides,
  };
}

function makeOptionPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL 220C 05/16', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
    entryPrice: 4.2, currentPrice: 4.5, currentStockPrice: 195,
    pnlDollar: 30, pnlPct: 7.1, stop: 185,
    targets: [{ id: 'T1', stockPrice: 205, targetPrice: 6, status: 'PENDING' }],
    status: 'PASS', delta: 0.5, contracts: 2, recId: 'REC-2',
    tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
    // MaxLossBanner renders only when an exit plan has been computed.
    exitPlan: {
      computedAt: '2026-08-27T00:00:00.000Z',
      stop: {
        price: 180, source: 'structural' as const, contractPrice: 2.0,
        rrModel: 'BS repriced (IV-derived)' as const, structuralSource: 'swing_low' as const, structuralConfidence: 0.8,
        structuralPrice: 180, atrFloorPrice: 175, distanceDollar: 5,
      },
      targets: [],
      atr: 3.1,
    },
    ...overrides,
  };
}

const noop = () => {};
const mount = (p: PortfolioPosition) =>
  render(<EditDrawer position={p} onClose={noop} onChange={noop} onRemove={noop} />);

const SECTIONS = [
  'Risk & stops',
  'Targets & take-profit',
  'Exit plan & odds',
  'Alerts for this position',
  'Position',
];
const region = (name: string) => screen.getByRole('region', { name });
const contains = (outer: HTMLElement, inner: HTMLElement) => outer.contains(inner);
const before = (a: HTMLElement, b: HTMLElement) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('Position editor sections (#662 T1)', () => {
  it('renders the five sections in order S1..S5 for an option position', () => {
    mount(makeOptionPosition());
    const regions = SECTIONS.map((n) => region(n));
    for (let i = 0; i < regions.length - 1; i++) expect(before(regions[i], regions[i + 1])).toBe(true);
  });

  it('option: S1 holds Stop, Structural level, Premium stop and Max loss', () => {
    mount(makeOptionPosition());
    const s1 = within(region('Risk & stops'));
    expect(s1.getByText('Stop')).toBeInTheDocument();
    expect(s1.getByText('Structural level')).toBeInTheDocument();
    expect(s1.getByLabelText('Premium stop percent')).toBeInTheDocument();
    expect(s1.getByText('Max loss at stop')).toBeInTheDocument();
  });

  it('option: S2 holds Targets, then Active TP method, then Picked at trade', () => {
    mount(makeOptionPosition());
    const s2 = region('Targets & take-profit');
    const targets = within(s2).getByText('Targets');
    const selector = within(s2).getByRole('radiogroup', { name: 'Active TP method' });
    const picked = within(s2).getByText('Picked at trade');
    expect(before(targets, selector)).toBe(true);
    expect(before(selector, picked)).toBe(true);
  });

  it('option: S3 holds Compute Exit Plan and the Monte Carlo Estimate', () => {
    mount(makeOptionPosition());
    const s3 = within(region('Exit plan & odds'));
    expect(s3.getByRole('button', { name: 'Compute Exit Plan' })).toBeInTheDocument();
    expect(s3.getByRole('button', { name: 'Estimate' })).toBeInTheDocument();
    expect(s3.getByText('Monte Carlo estimate')).toBeInTheDocument();
  });

  it('S4 holds the six alert type radiogroups', () => {
    mount(makeOptionPosition());
    const groups = within(region('Alerts for this position')).getAllByRole('radiogroup');
    expect(groups).toHaveLength(6);
  });

  it('S5 holds Contracts and Notes', () => {
    mount(makeOptionPosition());
    const s5 = region('Position');
    expect(within(s5).getByText('Contracts')).toBeInTheDocument();
    expect(within(s5).getByText('Notes')).toBeInTheDocument();
  });

  it('stock: no Exit Plan and no Max loss; S3 holds only the Monte Carlo block', () => {
    mount(makeStockPosition());
    expect(screen.queryByRole('button', { name: 'Compute Exit Plan' })).toBeNull();
    expect(screen.queryByText('Max loss at stop')).toBeNull();
    const s3 = within(region('Exit plan & odds'));
    expect(s3.getByText('Monte Carlo estimate')).toBeInTheDocument();
    expect(s3.getByRole('button', { name: 'Estimate' })).toBeInTheDocument();
    expect(s3.queryByRole('button', { name: 'Compute Exit Plan' })).toBeNull();
  });

  it.each([['option', makeOptionPosition], ['stock', makeStockPosition]] as const)(
    '%s: each inventory control renders exactly once',
    (_k, make) => {
      mount(make());
      // Editable fields: count <label> wrappers whose first text span is the field label.
      for (const label of ['Stop', 'Structural level', 'Contracts', 'Current price']) {
        const fields = Array.from(document.querySelectorAll('label'))
          .filter((l) => l.querySelector('span')?.textContent === label);
        expect(fields).toHaveLength(1);
      }
      for (const label of ['Notes', 'Targets', 'Picked at trade']) {
        expect(screen.getAllByText(label, { exact: true })).toHaveLength(1);
      }
      expect(screen.getAllByRole('button', { name: 'Estimate' })).toHaveLength(1);
      expect(screen.getAllByRole('button', { name: 'Close position' })).toHaveLength(1);
      expect(screen.getAllByRole('radiogroup', { name: 'Active TP method' })).toHaveLength(1);
      expect(screen.getAllByLabelText('Premium stop percent').length).toBe(1);
    },
  );

  it('tab order: interactive elements follow section order S1..S5', () => {
    const { container } = mount(makeOptionPosition());
    const sels = 'input, button, textarea, select, [tabindex]:not([tabindex="-1"])';
    const regions = SECTIONS.map((n) => region(n));
    const tabbables = Array.from(container.querySelectorAll<HTMLElement>(sels))
      .filter((el) => regions.some((r) => contains(r, el)));
    expect(tabbables.length).toBeGreaterThan(10);
    const idx = tabbables.map((el) => regions.findIndex((r) => contains(r, el)));
    expect(idx).toEqual([...idx].sort((a, b) => a - b));
    // every section contributes at least one tab stop
    expect(new Set(idx).size).toBe(5);
  });
});

describe('Manual overrides fold (#662 T2)', () => {
  const summaryOf = () => screen.getByText('Manual overrides', { selector: 'summary' });

  it.each([['option', makeOptionPosition], ['stock', makeStockPosition]] as const)(
    '%s: Current price sits inside a closed "Manual overrides" details in the Position section',
    (_k, make) => {
      mount(make());
      const details = summaryOf().closest('details') as HTMLDetailsElement;
      expect(details).not.toBeNull();
      expect(details.open).toBe(false);
      expect(details.contains(screen.getByLabelText(/Current price/))).toBe(true);
      expect(region('Position').contains(details)).toBe(true);
      expect(details.contains(screen.getByLabelText(/Contracts/))).toBe(false);
      expect(details.contains(screen.getByText('Notes'))).toBe(false);
    },
  );

  it('order inside Position is Contracts, Manual overrides, Notes', () => {
    mount(makeOptionPosition());
    const details = summaryOf().closest('details') as HTMLElement;
    expect(before(screen.getByLabelText(/Contracts/), details)).toBe(true);
    expect(before(details, screen.getByText('Notes'))).toBe(true);
  });

  it('editing the price from the opened details still flags a stale estimate', async () => {
    const { api } = jest.requireMock('@/lib/api');
    api.getStockFirstPassage.mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    mount(makeStockPosition());
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    (summaryOf().closest('details') as HTMLDetailsElement).open = true;
    fireEvent.change(screen.getByLabelText(/Current price/), { target: { value: '210' } });
    fireEvent.blur(screen.getByLabelText(/Current price/));
    expect(await screen.findByText('Price has changed since this estimate was computed.')).toBeInTheDocument();
  });
});
