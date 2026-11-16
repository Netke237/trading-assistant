/**
 * P2 (premium stop & position editing) -- TradeCard items P2-19, P2-20,
 * P2-23, P2-24. Plan:
 * docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md
 */
import '@testing-library/jest-dom';
import { render as renderCard, screen, fireEvent, within } from '@testing-library/react';
import { TradeCard, EditableKV } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import type { TradeCardData } from '@/types/domain';

// These existing calculation/flow tests exercise all methods explicitly.
const render = (...args: Parameters<typeof renderCard>) => {
  const view = renderCard(...args);
  for (const name of ['Arithmetic', 'Ladder']) {
    const toggle = screen.queryByRole('checkbox', { name });
    if (toggle && toggle.getAttribute('aria-checked') !== 'true') fireEvent.click(toggle);
  }
  const summary = screen.getByText('Risk-derived size & budget override');
  fireEvent.click(summary);
  return view;
};

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
const plan = {
  stop: { price: 180, source: 'structural' as const, contractPrice: 2.2,
    rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const,
    structuralConfidence: 80, structuralPrice: 180, atrFloorPrice: 175, distanceDollar: 5 },
  targets: [], atr: 3.5, computedAt: '2026-10-13T12:00:00Z',
};
const planned = () => card({ exit: { ...card().exit, exitPlan: plan } });
const group = () => within(screen.getByRole('region', { name: 'Entry & position size' }));
const exit = () => within(screen.getByRole('region', { name: 'Exit Plan' }));
const fields = (label: string) => ['Invalidation', 'Premium stop'].includes(label) ? exit() : group();
const budget = () => within(group().getByRole('region', { name: 'Max loss budget' }));
const edit = (label: string, value: string) => {
  fireEvent.click(fields(label).getByLabelText(`Edit ${label}`));
  const input = fields(label).getByLabelText(`Edit ${label}`);
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
};
beforeEach(() => {
  localStorage.clear(); jest.clearAllMocks();
  useSettingsStore.setState({ premiumStopPct: 0.6 });
  useRiskStore.setState({ limits: { ...useRiskStore.getState().limits, portfolioValue: 100000, maxLossPerTradePct: 0.0375 } });
});
it('keeps one live set of exit controls before methods and entry, budget and sizing after methods', () => {
  render(<TradeCard data={planned()} contracts={2} />);
  for (const label of ['Limit', 'Contracts', 'Invalidation', 'Premium stop'])
    expect(fields(label).getByLabelText(`Edit ${label}`)).toBeVisible();
  expect(group().getByText(/Order type Limit · Max fill \$5\.40/)).toBeVisible();
  expect(exit().getByText('Time exit')).toBeVisible();
  expect(budget().getByText('$3,750 (account default)')).toBeVisible();
  expect(group().getByText(/Risk-derived size: 12 contracts \(12.50 exact\)/)).toBeVisible();
  expect(screen.getAllByRole('button', { name: 'Apply recommended contract size' })).toHaveLength(1);
  expect(screen.getByText('Arithmetic Profit Target').compareDocumentPosition(screen.getByRole('region', { name: 'Entry & position size' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
it('distinguishes entered quantity, recommendation, snapshot exposure and arithmetic loss and retains explicit Apply', () => {
  const change = jest.fn();
  render(<TradeCard data={planned()} contracts={2} onEditsChange={change} liveMid={9} />);
  expect(group().getByText('Entered quantity')).toBeVisible();
  expect(group().getByText('$1040')).toBeVisible();
  expect(group().getByText('$600.00')).toBeVisible();
  edit('Contracts', '3');
  expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ contracts: 3 }), expect.anything());
  expect(group().getByText('$1560')).toBeVisible();
  expect(group().getByText('$900.00')).toBeVisible();
  expect(group().getByText(/Risk-derived size: 12 contracts/)).toBeVisible();
  fireEvent.click(group().getByRole('button', { name: 'Apply recommended contract size' }));
  expect(group().getByLabelText('Edit Contracts')).toHaveTextContent('12');
});
it('keeps percent/dollar override, zero-fit refusal and Use default without applying size implicitly', () => {
  const change = jest.fn();
  render(<TradeCard data={planned()} contracts={2} onMaxLossOverrideChange={change} />);
  fireEvent.click(budget().getByRole('button', { name: 'Set trade loss budget' }));
  fireEvent.change(budget().getByLabelText('Max loss override value'), { target: { value: '0.5' } });
  fireEvent.click(budget().getByRole('button', { name: 'Apply max loss override' }));
  expect(change).toHaveBeenLastCalledWith({ mode: 'percent', value: 0.005 });
  expect(budget().getByText('$500 (override: 0.50%)')).toBeVisible();
  expect(group().getByText(/Risk-derived size: 1 contract \(1.66 exact\)/)).toBeVisible();
  fireEvent.click(budget().getByRole('button', { name: 'Edit trade loss budget' }));
  fireEvent.click(budget().getByRole('button', { name: '$' }));
  fireEvent.change(budget().getByLabelText('Max loss override value'), { target: { value: '10' } });
  fireEvent.click(budget().getByRole('button', { name: 'Apply max loss override' }));
  expect(change).toHaveBeenLastCalledWith({ mode: 'dollar', value: 10 });
  expect(group().getByRole('button', { name: 'Apply recommended contract size' })).toBeDisabled();
  expect(group().getByLabelText('Edit Contracts')).toHaveTextContent('2');
  fireEvent.click(budget().getByRole('button', { name: 'Edit trade loss budget' }));
  fireEvent.click(budget().getByRole('button', { name: 'Use default' }));
  expect(change).toHaveBeenLastCalledWith(null);
  expect(budget().getByText('$3,750 (account default)')).toBeVisible();
});
it('retains clear-to-inherit entry and execution stops', () => {
  render(<TradeCard data={planned()} liveMid={5.2} />);
  for (const [label, changed, original] of [['Limit', '6', '$5.20'], ['Invalidation', '180', '$179.64'], ['Premium stop', '2', '$3.12']]) {
    edit(label, changed); edit(label, '');
    expect(fields(label).getByLabelText(`Edit ${label}`)).toHaveTextContent(original);
  }
});
it('clears prior candidate budget draft and restores supplied quantity/override', () => {
  const { rerender } = render(<TradeCard data={planned()} contracts={4} initialMaxLossOverride={{ mode: 'dollar', value: 600 }} />);
  expect(budget().getByText('$600 (override: $600)')).toBeVisible();
  fireEvent.click(budget().getByRole('button', { name: 'Edit trade loss budget' }));
  fireEvent.change(budget().getByLabelText('Max loss override value'), { target: { value: '9999' } });
  rerender(<TradeCard data={card({ symbol: 'MSFT', contract: 'MSFT 200C' })} contracts={3} />);
  expect(budget().queryByLabelText('Max loss override value')).not.toBeInTheDocument();
  expect(budget().getByText('$3,750 (account default)')).toBeVisible();
  expect(group().getByLabelText('Edit Contracts')).toHaveTextContent('3');
  expect(group().queryByRole('button', { name: 'Apply recommended contract size' })).not.toBeInTheDocument();
});
it('keeps low-premium execution stop read-only and missing arithmetic loss unavailable', () => {
  render(<TradeCard data={card()} liveMid={0.01} />);
  expect(exit().queryByLabelText('Edit Premium stop')).not.toBeInTheDocument();
  expect(exit().getByText('global (60%)')).toBeVisible();
  expect(group().getByText(/Arithmetic stop-loss estimate unavailable/)).toBeVisible();
});
it('distinguishes selected-contract exposure from whole-spread debit and max loss', () => {
  render(<TradeCard data={card({ spreadType: 'bear_put', netDebitCredit: 1.2, maxLoss: 120,
    legs: [{ action: 'BUY', qty: 1, strike: 190, right: 'P', expiry: '2026-05-15', bid: 1, ask: 1.2 },
      { action: 'SELL', qty: 1, strike: 185, right: 'P', expiry: '2026-05-15', bid: 1, ask: 1.2 }] })} />);
  expect(group().getByText('Selected-contract premium exposure')).toBeVisible();
  expect(group().getByText(/Whole-spread debit\/credit and max loss/)).toBeVisible();
  expect(group().getByText(/Arithmetic stop-loss estimate unavailable for spreads/)).toBeVisible();
  expect(screen.getByText('$120.00')).toBeVisible();
});


it('keeps missing contract/basis unavailable and a genuine returned zero loss visible', () => {
  const { rerender } = render(<TradeCard data={card({ contractDetails: undefined })} />);
  expect(group().getByText('Full-premium exposure').parentElement).toHaveTextContent('—');
  expect(group().getByText(/Arithmetic stop-loss estimate unavailable/)).toBeVisible();
  rerender(<TradeCard key="zero" data={card({ exit: { ...card().exit, exitPlan: { ...plan, stop: { ...plan.stop, contractPrice: 5.2 } } } })} />);
  fireEvent.click(screen.getByText('Risk-derived size & budget override'));
  expect(group().getByText('$0.00')).toBeVisible();
  rerender(<TradeCard key="missing" data={card({ exit: { ...card().exit, exitPlan: { ...plan, stop: { ...plan.stop, contractPrice: Number.NaN } } } })} />);
  fireEvent.click(screen.getByText('Risk-derived size & budget override'));
  expect(group().getByText(/Arithmetic stop-loss estimate unavailable/)).toBeVisible();
});

it('starts with one compact Entry & position size panel and a closed sizing explanation', () => {
  renderCard(<TradeCard data={planned()} contracts={2} />);
  const panel = screen.getByRole('region', { name: 'Entry & position size' });
  expect(within(panel).getByLabelText('Edit Limit')).toBeVisible();
  expect(within(panel).getByLabelText('Edit Contracts')).toBeVisible();
  expect(within(panel).getByText('$1040')).toBeVisible();
  const details = within(panel).getByText('Risk-derived size & budget override').closest('details')!;
  expect(details).not.toHaveAttribute('open');
  expect(within(panel).getByRole('button', { name: 'Apply recommended contract size', hidden: true })).not.toBeVisible();
  fireEvent.click(within(panel).getByText('Risk-derived size & budget override'));
  expect(within(panel).getByRole('button', { name: 'Apply recommended contract size' })).toBeEnabled();
});
