/**
 * P2 (premium stop & position editing) -- TradeCard items P2-19, P2-20,
 * P2-23, P2-24. Plan:
 * docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md
 */
import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { TradeCard, EditableKV } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import { useSettingsStore } from '@/lib/settingsStore';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
  },
}));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: () => <div /> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({ LabeledStatusBadge: () => <div /> }));

const card = (o: Partial<TradeCardData> = {}): TradeCardData => ({
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5.2, maxFill: 5.4, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 3.12, timeStopDays: 10, target: 200.02,
    targets: [{ id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 }],
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  ...o,
});
const premiumRow = () => screen.getByLabelText('Edit Premium stop');

beforeEach(() => {
  localStorage.clear();
  useSettingsStore.setState({ premiumStopPct: 0.6 });
  (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 185.2 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100 });
});

describe('P2-19 -- the untouched Premium stop follows the live mid, not the stale scan seed', () => {
  it('scan mid 5.20, live 1.00, global 0.60 -> shows $0.60 (global 60%)', () => {
    render(<TradeCard data={card()} liveMid={1.0} />);
    expect(premiumRow()).toHaveTextContent('$0.60');
    expect(screen.getByText('(global 60%)')).toBeInTheDocument();
  });

  it('no live mid -> the scan seed, with no global label', () => {
    render(<TradeCard data={card()} />);
    expect(premiumRow()).toHaveTextContent('$3.12');
    expect(screen.queryByText(/\(global \d+%\)/)).not.toBeInTheDocument();
  });

  it('a bare focus-and-blur writes nothing (premiumStop stays untouched)', () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={card()} liveMid={1.0} onEditsChange={onEditsChange} />);
    fireEvent.click(premiumRow());
    fireEvent.blur(screen.getByLabelText('Edit Premium stop'));
    const touchedPremium = onEditsChange.mock.calls.some(([, meta]) => meta?.touched?.premiumStop);
    expect(touchedPremium).toBe(false);
    expect(premiumRow()).toHaveTextContent('$0.60');
  });

  it('a typed value wins over the live-mid display', () => {
    render(<TradeCard data={card()} liveMid={1.0} />);
    fireEvent.click(premiumRow());
    const input = screen.getByLabelText('Edit Premium stop');
    fireEvent.change(input, { target: { value: '0.45' } });
    fireEvent.blur(input);
    expect(premiumRow()).toHaveTextContent('$0.45');
    expect(screen.queryByText('(global 60%)')).not.toBeInTheDocument();
  });
});

describe('P2-20 -- EditableKV rounds at its own decimals', () => {
  it('decimals={3} keeps three places', () => {
    const onChange = jest.fn();
    render(<dl><EditableKV label="X" value={1} onChange={onChange} decimals={3} /></dl>);
    fireEvent.click(screen.getByLabelText('Edit X'));
    const input = screen.getByLabelText('Edit X');
    fireEvent.change(input, { target: { value: '1.2346' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(1.235);
  });
});

describe('P2-23 -- with no live and no contract mid, the bounds anchor on the entry limit', () => {
  it('entry.limit 2.50 -> typing 25 into Limit is refused', () => {
    const noMid = card({
      contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 0, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      entry: { limit: 2.5, maxFill: 2.6, orderType: 'Limit' },
    });
    render(<TradeCard data={noMid} />);
    fireEvent.click(screen.getByLabelText('Edit Limit'));
    const input = screen.getByLabelText('Edit Limit');
    fireEvent.change(input, { target: { value: '25' } });
    fireEvent.blur(input);
    expect(screen.getByText(/Must be between \$0\.63 and \$7\.50/)).toBeInTheDocument();
  });
});

describe('P2-24 -- at a $0.01 mid the Premium stop row is read-only', () => {
  it('mid 0.01 untouched: no editor, says the global applies', () => {
    render(<TradeCard data={card()} liveMid={0.01} />);
    expect(screen.queryByLabelText('Edit Premium stop')).not.toBeInTheDocument();
    expect(screen.getByText('global (60%)')).toBeInTheDocument();
    expect(screen.getByText(/too small for a per-contract premium stop/)).toBeInTheDocument();
  });

  it('mid 0.02: editable', () => {
    render(<TradeCard data={card()} liveMid={0.02} />);
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
  });

  it('a restored cached dollar (initialPremiumStop) is kept and shown as pinned (decision Q-P2-2)', () => {
    // A cached value from the page IS a previous edit (touchedRef starts true).
    render(<TradeCard data={card()} liveMid={0.01} initialPremiumStop={2.0} />);
    expect(screen.queryByLabelText('Edit Premium stop')).not.toBeInTheDocument();
    expect(screen.getByText('$2.00 (pinned)')).toBeInTheDocument();
    expect(screen.queryByText('global (60%)')).not.toBeInTheDocument();
  });

  it('a stop typed at a normal mid is shown as pinned when the mid falls to $0.01', () => {
    const { rerender } = render(<TradeCard data={card()} liveMid={1.0} />);
    fireEvent.click(premiumRow());
    const input = screen.getByLabelText('Edit Premium stop');
    fireEvent.change(input, { target: { value: '0.45' } });
    fireEvent.blur(input);
    rerender(<TradeCard data={card()} liveMid={0.01} />);
    expect(screen.getByText('$0.45 (pinned)')).toBeInTheDocument();
    expect(screen.getByText(/Your pinned stop is kept and sent/)).toBeInTheDocument();
  });
});
