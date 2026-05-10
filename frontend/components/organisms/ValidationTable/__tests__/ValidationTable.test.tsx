import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import type { TradeCardData } from '@/types/domain';

function makeCandidate(i: number): TradeCardData {
  return {
    symbol: `SYM${i}`,
    company: `Company ${i}`,
    price: 100 + i,
    direction: i % 2 === 0 ? 'Bullish' : 'Bearish',
    status: 'PASS',
    stockScore: 77 + (i % 23),
    stockConfidence: 'PASS',
    stockBreakdown: {
      trend: 80 + (i % 20),
      pullback: 70 + (i % 30),
      trigger: 75 + (i % 25),
      event: 65 + (i % 35),
      volatility: 60 + (i % 40),
    },
    contract: '',
    contractScore: 0,
    contractConfidence: 'PENDING',
    contractBreakdown: { dteFit: 0, delta: 0, ivAttractiveness: 0, liquidity: 0, spread: 0 },
    entry: { limit: 0, maxFill: 0, orderType: 'Limit' },
    exit: { invalidation: 0, premiumStop: 0, timeStopDays: 0, target: 0, targets: [] },
    rrRatio: 0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
  };
}

describe('ValidationTable', () => {
  let ValidationTable: React.ComponentType<{ candidates: TradeCardData[] }>;

  beforeAll(async () => {
    const mod = await import('@/components/organisms/ValidationTable');
    ValidationTable = mod.ValidationTable;
  });

  it('shows empty state when no candidates', () => {
    render(<ValidationTable candidates={[]} />);
    expect(screen.getByText(/no scan data/i)).toBeInTheDocument();
  });

  it('renders header row with column labels', () => {
    render(<ValidationTable candidates={[makeCandidate(0)]} />);
    expect(screen.getByText('SYMBOL')).toBeInTheDocument();
    expect(screen.getByText('TREND')).toBeInTheDocument();
    expect(screen.getByText('PULLBACK')).toBeInTheDocument();
    expect(screen.getByText('TRIGGER')).toBeInTheDocument();
    expect(screen.getByText('EVENT')).toBeInTheDocument();
    expect(screen.getByText('VOL')).toBeInTheDocument();
    expect(screen.getByText('SCORE')).toBeInTheDocument();
    expect(screen.getByText('STATUS')).toBeInTheDocument();
  });

  it('renders candidate symbols in data rows', () => {
    const candidates = Array.from({ length: 3 }, (_, i) => makeCandidate(i));
    render(<ValidationTable candidates={candidates} />);
    expect(screen.getByText('SYM0')).toBeInTheDocument();
    expect(screen.getByText('SYM1')).toBeInTheDocument();
    expect(screen.getByText('SYM2')).toBeInTheDocument();
  });

  it('renders rule scores for each candidate', () => {
    render(<ValidationTable candidates={[makeCandidate(0)]} />);
    expect(screen.getByText('80')).toBeInTheDocument(); // trend
    expect(screen.getByText('70')).toBeInTheDocument(); // pullback
    expect(screen.getByText('75')).toBeInTheDocument(); // trigger
    expect(screen.getByText('65')).toBeInTheDocument(); // event
    expect(screen.getByText('60')).toBeInTheDocument(); // volatility
    expect(screen.getByText('77')).toBeInTheDocument(); // stockScore
  });

  it('paginates with 10 items per page', () => {
    const candidates = Array.from({ length: 25 }, (_, i) => makeCandidate(i));
    render(<ValidationTable candidates={candidates} />);

    expect(screen.getByText('SYM0')).toBeInTheDocument();
    expect(screen.getByText('SYM9')).toBeInTheDocument();
    expect(screen.queryByText('SYM10')).not.toBeInTheDocument();
  });

  it('shows candidate count in header', () => {
    const candidates = Array.from({ length: 5 }, (_, i) => makeCandidate(i));
    render(<ValidationTable candidates={candidates} />);
    expect(screen.getByText(/5 candidates/i)).toBeInTheDocument();
  });

  it('shows direction arrows for each candidate', () => {
    render(<ValidationTable candidates={[makeCandidate(0), makeCandidate(1)]} />);
    expect(screen.getByText('↑')).toBeInTheDocument();
    expect(screen.getByText('↓')).toBeInTheDocument();
  });
});
