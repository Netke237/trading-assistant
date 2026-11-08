/**
 * TC-REVIEW-03 (#578) — one actual Exit Plan with explicit premium-loss units,
 * consistent editable styling, collapsed explanations, and no setting change
 * from calculation or method selection.
 */
import '@testing-library/jest-dom';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { premiumStopDollarToSend } from '@/lib/premiumStop';
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
const FINAL_STOP = {
  price: 169.0, source: 'final_stop' as const, stopSource: 'atr_widened' as const,
  structuralSource: 'swing_low' as const, structuralPrice: 182.0, atrFloorPrice: 169.0,
  distanceDollar: 13.0, atr: 8.0, computedAt: '2026-09-09T12:00:00+00:00',
};
const PLAN_RESPONSE = {
  stop: { price: 178, source: 'atr_widened' as const, contractPrice: 1.2, rrModel: 'Heston repriced' as const,
    structuralSource: null, structuralConfidence: null, structuralPrice: null, atrFloorPrice: 178, distanceDollar: null },
  targets: [{ rrRatio: 2, arithmeticPrice: 210.5, price: 210.5, tpSource: 'arithmetic' as const, structuralPrice: null, contractPrice: 9, rrModel: 'Heston repriced' as const, probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
  atr: 4,
};

const exitPlan = () => within(screen.getByRole('region', { name: 'Exit Plan' }));
const values = () => within(exitPlan().getByRole('group', { name: 'Premium-loss values' }));
const value = (label: string) => values().getByText(label).parentElement;
const edit = (label: string, v: string) => {
  fireEvent.click(screen.getByLabelText(`Edit ${label}`));
  const input = screen.getByLabelText(`Edit ${label}`);
  fireEvent.change(input, { target: { value: v } });
  fireEvent.blur(input);
};

beforeEach(() => {
  localStorage.clear(); jest.clearAllMocks();
  useSettingsStore.setState({ premiumStopPct: 0.6 });
  useRiskStore.setState({ limits: { ...useRiskStore.getState().limits, portfolioValue: 100000, maxLossPerTradePct: 0.0375 } });
  (api.getStructuralStop as jest.Mock).mockResolvedValue({ available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 });
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 185.2 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 5.2 });
});

describe('premium-loss values use the execution field basis', () => {
  it('live mid + untouched: global % on the live mid, per share / per contract / entered quantity', () => {
    render(<TradeCard data={card()} liveMid={1.0} contracts={2} />);
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent('$0.60');
    expect(screen.getByText('(global 60%)')).toBeInTheDocument();
    expect(value('Premium basis')).toHaveTextContent('$1.00/share · live mid');
    expect(value('Premium-loss %')).toHaveTextContent('60%');
    expect(value('Loss per share')).toHaveTextContent('$0.60/share');
    expect(value('Loss per contract (×100 shares)')).toHaveTextContent('$60.00');
    expect(value('Loss for 2 entered contracts')).toHaveTextContent('$120.00');
    expect(value('Remaining option value per share')).toHaveTextContent('$0.40/share');
    expect(value('Remaining option value per contract (×100 shares)')).toHaveTextContent('$40.00');
    expect(value('Remaining option value for 2 entered contracts')).toHaveTextContent('$80.00');
  });

  it('no live mid + untouched: the scan seed against the scan mid', () => {
    render(<TradeCard data={card()} />);
    expect(value('Premium basis')).toHaveTextContent('$5.20/share · scan mid');
    expect(value('Premium-loss %')).toHaveTextContent('60%');
    expect(value('Loss per share')).toHaveTextContent('$3.12/share');
    expect(value('Loss per contract (×100 shares)')).toHaveTextContent('$312.00');
    expect(value('Loss for 1 entered contract')).toHaveTextContent('$312.00');
    expect(value('Remaining option value per share')).toHaveTextContent('$2.08/share');
    expect(value('Remaining option value per contract (×100 shares)')).toHaveTextContent('$208.00');
  });

  it('no mid at all: the plan entry limit is the basis, as for the field bounds', () => {
    render(<TradeCard data={card({
      contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 0, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      entry: { limit: 2.5, maxFill: 2.6, orderType: 'Limit' },
      exit: { ...card().exit, premiumStop: 1.5 },
    })} />);
    expect(value('Premium basis')).toHaveTextContent('$2.50/share · plan entry limit (no mid)');
    expect(value('Premium-loss %')).toHaveTextContent('60%');
    expect(value('Remaining option value per share')).toHaveTextContent('$1.00/share');
  });

  it('a typed amount wins, follows quantity, and clearing reverts to the inherited value', () => {
    render(<TradeCard data={card()} />);
    edit('Premium stop', '2.6');
    expect(value('Premium-loss %')).toHaveTextContent('50%');
    expect(value('Loss per share')).toHaveTextContent('$2.60/share');
    expect(value('Remaining option value per share')).toHaveTextContent('$2.60/share');
    edit('Contracts', '3');
    expect(value('Loss for 3 entered contracts')).toHaveTextContent('$780.00');
    expect(value('Remaining option value for 3 entered contracts')).toHaveTextContent('$780.00');
    edit('Premium stop', '');
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent('$3.12');
    expect(value('Premium-loss %')).toHaveTextContent('60%');
    expect(value('Loss for 3 entered contracts')).toHaveTextContent('$936.00');
  });

  it('a saved (restored) edit keeps precedence over the live-mid global', () => {
    render(<TradeCard data={card()} liveMid={1.0} initialPremiumStop={0.5} initialInvalidation={175} />);
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent('$0.50');
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$175.00');
    expect(screen.queryByText('(global 60%)')).not.toBeInTheDocument();
    expect(value('Premium basis')).toHaveTextContent('$1.00/share · live mid');
    expect(value('Premium-loss %')).toHaveTextContent('50%');
    expect(value('Remaining option value per share')).toHaveTextContent('$0.50/share');
  });

  it('tiny premium, untouched: read-only global, dollar figures unavailable (never $0.00)', () => {
    render(<TradeCard data={card()} liveMid={0.01} />);
    expect(screen.queryByLabelText('Edit Premium stop')).not.toBeInTheDocument();
    expect(screen.getByText('global (60%)')).toBeInTheDocument();
    expect(screen.getByText(/too small for a per-contract premium stop/)).toBeVisible();
    expect(value('Premium basis')).toHaveTextContent(/^Premium basisUnavailable — resolved against the fill$/);
    expect(value('Premium-loss %')).toHaveTextContent('60% global — resolved against the fill');
    expect(value('Loss per share')).toHaveTextContent(/Unavailable/);
    expect(value('Remaining option value per share')).toHaveTextContent(/Unavailable/);
    expect(values().queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it('tiny premium, pinned: the kept dollar amount, basis-derived values unavailable', () => {
    render(<TradeCard data={card()} liveMid={0.01} initialPremiumStop={2.0} contracts={2} />);
    expect(screen.getByText('$2.00 (pinned)')).toBeInTheDocument();
    expect(screen.getByText(/Your pinned stop is kept and sent/)).toBeVisible();
    expect(value('Loss per share')).toHaveTextContent('$2.00/share (pinned)');
    expect(value('Loss per contract (×100 shares)')).toHaveTextContent('$200.00');
    expect(value('Loss for 2 entered contracts')).toHaveTextContent('$400.00');
    expect(value('Premium-loss %')).toHaveTextContent(/Unavailable — resolved against the fill/);
    expect(value('Remaining option value per share')).toHaveTextContent(/Unavailable — resolved against the fill/);
  });

  it('missing basis: unavailable, never zero and never a borrowed calculation premium', () => {
    render(<TradeCard data={card({
      contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 0, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      entry: { limit: 0, maxFill: 0, orderType: 'Limit' },
      exit: { ...card().exit, premiumStop: 1.5, exitPlan: { ...PLAN_RESPONSE, computedAt: '2026-10-13T12:00:00Z' } },
    })} />);
    expect(value('Premium basis')).toHaveTextContent('Unavailable — no positive premium basis');
    expect(value('Premium-loss %')).toHaveTextContent(/Unavailable/);
    expect(value('Remaining option value per share')).toHaveTextContent(/Unavailable/);
    expect(value('Loss per share')).toHaveTextContent('$1.50/share');
    expect(values().queryByText(/\$1\.20|\$9\.00|\$0\.00/)).not.toBeInTheDocument();
  });

  it('missing loss amount: unavailable rather than $0.00', () => {
    render(<TradeCard data={card({ exit: { ...card().exit, premiumStop: 0 } })} />);
    expect(value('Loss per share')).toHaveTextContent(/Unavailable/);
    expect(value('Premium-loss %')).toHaveTextContent(/Unavailable/);
    expect(values().queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });
});

describe('time exit, warnings and disclosures', () => {
  it('explains 3 DTE as an alert at three or fewer days until expiry, read-only', () => {
    render(<TradeCard data={card()} />);
    expect(exitPlan().getByText('3 DTE')).toBeVisible();
    expect(exitPlan().getByText(/alert when 3 or fewer calendar days remain until expiry/i)).toBeVisible();
    expect(exitPlan().getByText(/not 3 days after entry/i)).toBeVisible();
    expect(exitPlan().getByText(/not an automatic close/i)).toBeVisible();
    expect(screen.queryByLabelText('Edit Time exit')).not.toBeInTheDocument();
  });

  it('collapses the source explanation by default and keeps the missing-stop warning visible', () => {
    render(<TradeCard data={card({ exit: { ...card().exit, invalidation: null } })} />);
    const explanation = exitPlan().getByText(/Invalidation is the editable execution stock stop/);
    expect(explanation).not.toBeVisible();
    expect(exitPlan().getByText(/Invalidation stop required — Send to broker stays disabled/)).toBeVisible();
    fireEvent.click(exitPlan().getByText('How these exit settings are resolved'));
    expect(explanation).toBeVisible();
    expect(exitPlan().getByText(/Monte Carlo and Arithmetic premiums are separate calculation inputs/)).toBeVisible();
  });

  it('no missing-stop warning when invalidation is present', () => {
    render(<TradeCard data={card()} />);
    expect(exitPlan().queryByText(/Invalidation stop required — Send to broker stays disabled/)).not.toBeInTheDocument();
  });

  it('collapses stop source / ATR / structure detail but keeps the final stop price visible', () => {
    render(<TradeCard data={card({ exit: { ...card().exit, invalidation: 169, finalStop: FINAL_STOP } })} />);
    const stops = within(screen.getByRole('region', { name: 'Structure & Stops' }));
    expect(stops.getByText('Bottom (final stop)')).toBeVisible();
    expect(stops.getByText('Price')).toBeVisible();
    expect(stops.getByText('ATR(14)')).not.toBeVisible();
    expect(stops.getByText('Structural stop — Swing Low')).not.toBeVisible();
    expect(stops.getByText(/ATR floor is backend-configured/)).not.toBeVisible();
    fireEvent.click(stops.getByText('Stop source, ATR and structure detail'));
    expect(stops.getByText('ATR(14)')).toBeVisible();
    expect(stops.getByText(/widened to \$169\.00/)).toBeVisible();
  });
});

describe('editable versus read-only styling', () => {
  it('marks every existing editable field with the editable affordance and nothing read-only', async () => {
    render(<TradeCard data={card()} />);
    for (const label of ['Edit Limit', 'Edit Contracts', 'Edit Invalidation', 'Edit Premium stop']) {
      expect(screen.getByLabelText(label)).toHaveAttribute('data-editable', 'true');
    }
    expect(screen.getByLabelText('Edit target stock price for TP1')).toHaveAttribute('data-editable', 'true');
    for (const key of ['T1', 'T2', 'T3']) {
      expect(screen.getByLabelText(`${key} profit target %`)).toHaveAttribute('data-editable', 'true');
    }
    const budget = within(screen.getByRole('region', { name: 'Max loss budget' }));
    fireEvent.click(budget.getByRole('button', { name: 'Set trade loss budget' }));
    expect(budget.getByLabelText('Max loss override value')).toHaveAttribute('data-editable', 'true');
    expect(budget.getByRole('button', { name: '%' })).toHaveAttribute('data-editable', 'true');
    expect(budget.getByRole('button', { name: '$' })).toHaveAttribute('data-editable', 'true');
    // An opened editor keeps the same affordance.
    fireEvent.click(screen.getByLabelText('Edit Limit'));
    expect(screen.getByLabelText('Edit Limit')).toHaveAttribute('data-editable', 'true');
    fireEvent.blur(screen.getByLabelText('Edit Limit'));
    fireEvent.click(screen.getByLabelText('Edit target stock price for TP1'));
    expect(screen.getByLabelText('Edit target stock price for TP1')).toHaveAttribute('data-editable', 'true');
  });

  it('read-only max fill, order type, time exit and computed values do not look editable', () => {
    render(<TradeCard data={card()} />);
    for (const label of ['Max fill', 'Order type', 'Time exit']) {
      const row = screen.getByText(label).parentElement as HTMLElement;
      expect(row.querySelector('[data-editable]')).toBeNull();
      expect(within(row).queryByRole('button')).not.toBeInTheDocument();
    }
    const list = exitPlan().getByRole('group', { name: 'Premium-loss values' });
    expect(list.querySelector('[data-editable]')).toBeNull();
    expect(within(list).queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('settings are not mutated by focus, calculation or selection', () => {
  it('focus and blur without typing does not mark either execution stop touched', () => {
    const change = jest.fn();
    render(<TradeCard data={card()} liveMid={1.0} onEditsChange={change} />);
    for (const label of ['Invalidation', 'Premium stop', 'Limit']) {
      fireEvent.click(screen.getByLabelText(`Edit ${label}`));
      fireEvent.blur(screen.getByLabelText(`Edit ${label}`));
    }
    expect(change).not.toHaveBeenCalled();
    expect(value('Loss per share')).toHaveTextContent('$0.60/share');
  });

  it('computing a plan and choosing a method leave the exit settings and outbound edits untouched', async () => {
    (api.getExitPlan as jest.Mock).mockResolvedValue(PLAN_RESPONSE);
    const change = jest.fn();
    const pickChange = jest.fn();
    render(<TradeCard data={card()} contracts={2} onEditsChange={change} onMethodPickChange={pickChange} />);
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Arithmetic' })).toBeEnabled());
    fireEvent.click(screen.getByRole('radio', { name: 'Arithmetic' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
    fireEvent.click(screen.getByRole('radio', { name: 'TP1' }));
    expect(pickChange).toHaveBeenCalled();
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent('$3.12');
    expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('2');
    expect(value('Premium basis')).toHaveTextContent('$5.20/share · scan mid');
    expect(value('Loss for 2 entered contracts')).toHaveTextContent('$624.00');
  });
});

describe('outbound parity (preservation guard)', () => {
  it('reports exactly the same overlay and touched flags for edit, quantity and revert', () => {
    const change = jest.fn();
    render(<TradeCard data={card()} liveMid={1.0} onEditsChange={change} />);
    edit('Premium stop', '0.45');
    edit('Contracts', '3');
    edit('Invalidation', '176');
    edit('Premium stop', '');
    const base = { entryLimit: 5.2, maxFill: 5.4, timeStopDays: 10, targets: [200.02] };
    expect(change.mock.calls).toEqual([
      [{ ...base, invalidation: 179.64, premiumStop: 0.45, contracts: 1 }, { touched: { entryLimit: false, invalidation: false, premiumStop: true } }],
      [{ ...base, invalidation: 179.64, premiumStop: 0.45, contracts: 3 }, { touched: { entryLimit: false, invalidation: false, premiumStop: true } }],
      [{ ...base, invalidation: 176, premiumStop: 0.45, contracts: 3 }, { touched: { entryLimit: false, invalidation: true, premiumStop: true } }],
      [{ ...base, invalidation: 176, premiumStop: 3.12, contracts: 3 }, { touched: { entryLimit: false, invalidation: true, premiumStop: false } }],
    ]);
    // The live-mid display value ($0.60) never enters a payload, and the send
    // helper still maps the cached touched amount unchanged.
    expect(change.mock.calls.some(([o]) => o.premiumStop === 0.6)).toBe(false);
    expect(premiumStopDollarToSend(0.45)).toBe(0.45);
    expect(premiumStopDollarToSend(null)).toBeNull();
  });
});
