import '@testing-library/jest-dom';
import * as React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { TradeCard } from '..';
import { useSettingsStore } from '@/lib/settingsStore';
import type { TradeCardData } from '@/types/domain';

// #610 acceptance fixes G2/G4/G5 — the identity, qualification placement and
// Exit Plan arrangement of the frozen trade-card reference. Presentation
// only: these pin WHERE existing facts and controls sit, never a figure.
//
// Echo CSS-module keys so the primitive family (Text vs Data) is observable.
jest.mock('@/components/primitives/Text.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));
jest.mock('@/components/primitives/Data.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));

jest.mock('@/lib/api', () => ({ api: {
  getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
  getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
} }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => null }));

const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS', confidence: 72,
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL|185|2026-12-18|C', contractScore: 78, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 185, expiry: '2026-12-18', right: 'C', mid: 2.15,
    delta: 0.52, theta: -0.05, ivRank: 45, dte: 75 },
  entry: { limit: 2.15, maxFill: 2.2, orderType: 'Limit' },
  exit: {
    invalidation: 180, premiumStop: 1.29, timeStopDays: 10, target: 200.02,
    targets: [{ id: 'tp1', stockPrice: 200.02, estimatedOptionPrice: 8, contractsToSell: 1 }],
    finalStop: {
      price: 169.0, source: 'final_stop', stopSource: 'atr_widened', structuralSource: 'swing_low',
      structuralPrice: 182.0, atrFloorPrice: 169.0, distanceDollar: 13.0, atr: 8.0,
      computedAt: '2026-09-09T12:00:00+00:00',
    },
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  alternatives: [{
    symbol: 'AAPL', strike: 190, expiry: '2026-12-18', right: 'C', dte: 75, mid: 1.4, delta: 0.4,
    theta: -0.04, ivRank: 40, score: 66, contractConfidence: 'CAUTION',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    rrRatio: 2, rrModel: 'Delta approximation', reason: 'Cheaper premium, lower delta.',
  }],
};

const follows = (a: Element, b: Element) =>
  (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

beforeEach(() => {
  localStorage.clear();
  useSettingsStore.setState({ premiumStopPct: 0.6 });
});

describe('G2 — two-column identity', () => {
  it('puts the underlying and the selected contract side by side, the contract in sans with expiry on its own line', () => {
    render(<TradeCard data={card} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const underlying = within(identity).getByRole('group', { name: 'Underlying' });
    const contract = within(identity).getByRole('group', { name: 'Contract identity' });
    // Two columns of one grid.
    expect(underlying.parentElement).toBe(contract.parentElement);
    expect(follows(underlying, contract)).toBe(true);
    // Final status stays in the identity, with the underlying.
    expect(underlying).toContainElement(identity.querySelector('[data-identity="final-status"]') as HTMLElement);
    // Strike/right in the sans primitive, expiry on its own line in full.
    const strike = within(contract).getByText('$185 Call');
    expect(strike).toHaveClass('text');
    expect(strike).not.toHaveClass('data');
    const expiry = within(contract).getByText('Expires 18 December 2026');
    // Each on its own (block) line, never inline beside the strike.
    expect(strike.tagName).toBe('DIV');
    expect(expiry.tagName).toBe('DIV');
    expect(strike).not.toContainElement(expiry);
    // One metadata line: DTE and option mid, the existing values.
    expect(within(contract).getByText('75 days to expiry · Option mid $2.15 / share')).toBeInTheDocument();
  });

  it('moves the extra identity lines to the qualification titles and the Contract Details header, losing none', () => {
    render(<TradeCard data={card} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    // No longer stacked under the identity.
    expect(screen.queryByText('Stock score 82/100 · PASS')).not.toBeInTheDocument();
    expect(screen.queryByText(/^Contract score 78\/100/)).not.toBeInTheDocument();
    // Stock score and backtested confidence in the Stock Qualification title.
    const stockQ = screen.getByRole('button', { name: /Stock Qualification/ });
    expect(stockQ).toHaveTextContent('82/100 · PASS');
    expect(stockQ).toHaveTextContent('backtested confidence 72%');
    // Contract score in the Contract Qualification title.
    expect(screen.getByRole('button', { name: /Contract Qualification/ })).toHaveTextContent('78/100 · PASS');
    // Raw contract id and the snapshot note are the Contract Details header meta.
    const details = within(identity).getByRole('region', { name: 'Contract Details' });
    expect(within(details).getByText('AAPL|185|2026-12-18|C')).toBeInTheDocument();
    expect(within(details).getByText(/Stock and contract snapshots/)).toBeInTheDocument();
    expect(within(details).getByText('Capital at risk')).toBeInTheDocument();
  });

  it('says "not supplied" for a missing backtested confidence, and keeps the raw id without contract details', () => {
    render(<TradeCard data={{ ...card, confidence: null, contractDetails: undefined }} />);
    expect(screen.getByRole('button', { name: /Stock Qualification/ })).toHaveTextContent('backtested confidence not supplied');
    expect(screen.getAllByText('AAPL|185|2026-12-18|C').length).toBeGreaterThan(0);
    expect(screen.getByText(/Stock and contract snapshots/)).toBeInTheDocument();
  });
});

describe('G4 — qualification and alternatives placement', () => {
  it('groups closed qualifications below Contract Details and keeps Alternatives after Decision & execution', () => {
    render(<TradeCard data={card} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const decision = screen.getByRole('region', { name: 'Decision and execution' });
    expect(screen.getAllByRole('button', { name: /Stock Qualification/ })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: /Contract Qualification/ })).toHaveLength(1);
    const stockQ = screen.getByRole('button', { name: /Stock Qualification/ });
    const contractQ = screen.getByRole('button', { name: /Contract Qualification/ });
    const alternatives = screen.getByRole('button', { name: /Alternative contracts \(1\)/ });
    const details = within(identity).getByRole('region', { name: 'Contract Details' });
    expect(identity).toContainElement(stockQ);
    expect(identity).toContainElement(contractQ);
    expect(details.nextElementSibling).toBe(stockQ.closest('section'));
    expect(stockQ.closest('section')!.nextElementSibling).toBe(contractQ.closest('section'));
    expect(decision).not.toContainElement(stockQ);
    expect(decision).not.toContainElement(contractQ);
    expect(identity).not.toContainElement(alternatives);
    expect(decision).not.toContainElement(alternatives);
    expect(follows(decision, alternatives)).toBe(true);
    expect(stockQ).toHaveAttribute('aria-expanded', 'false');
    expect(contractQ).toHaveAttribute('aria-expanded', 'false');
    expect(alternatives).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens the alternatives in the shared disclosure without persisting anything', () => {
    render(<TradeCard data={card} />);
    const keysBefore = Object.keys(localStorage);
    const alternatives = screen.getByRole('button', { name: /Alternative contracts \(1\)/ });
    expect(screen.queryByText('Cheaper premium, lower delta.')).not.toBeInTheDocument();
    fireEvent.click(alternatives);
    expect(alternatives).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Cheaper premium, lower delta.')).toBeInTheDocument();
    // Same as before: a local, unpersisted open state — no new storage key.
    expect(Object.keys(localStorage).filter((k) => !keysBefore.includes(k))).toEqual([]);
    expect(screen.queryByText(/^ALTERNATIVES/)).not.toBeInTheDocument();
  });
});

describe('G5 — compact Exit Plan', () => {
  const exitPlan = () => screen.getByRole('region', { name: 'Exit Plan' });

  it('has exactly one top-level, default-closed explanation holding the structure evidence and Check structure', () => {
    render(<TradeCard data={card} contracts={2} />);
    const plan = exitPlan();
    const topLevel = Array.from(plan.querySelectorAll('details')).filter((d) => d.parentElement?.closest('details') == null);
    expect(topLevel).toHaveLength(1);
    const explanation = topLevel[0];
    expect(explanation).not.toHaveAttribute('open');
    expect(explanation.querySelector('summary')).toHaveTextContent('Exit Plan explanation · stop basis, premium & time exit');
    const inside = within(explanation);
    expect(inside.getByRole('region', { name: 'Structure & Stops' })).toBeInTheDocument();
    expect(inside.getByRole('button', { name: 'Check structure' })).not.toBeVisible();
    expect(inside.getByText('Bottom (final stop)')).not.toBeVisible();
    expect(inside.getByText(/Invalidation is the editable execution stock stop/)).not.toBeVisible();
    expect(inside.getByText('Loss for 2 entered contracts')).not.toBeVisible();
    fireEvent.click(explanation.querySelector('summary')!);
    expect(inside.getByRole('button', { name: 'Check structure' })).toBeVisible();
  });

  it('shows the loss % as a chip beside the premium stop and two concise remaining/loss lines instead of a 2x2 grid', () => {
    render(<TradeCard data={card} liveMid={1.0} contracts={2} />);
    const plan = within(exitPlan());
    const premiumRow = plan.getByRole('button', { name: 'Edit Premium stop' }).parentElement!;
    expect(within(premiumRow).getByText('60% loss · global')).toBeVisible();
    const summary = plan.getByRole('group', { name: 'Premium-loss summary' });
    expect(within(summary).getByText('Remaining: $0.40/share · $40.00 / contract')).toBeVisible();
    expect(within(summary).getByText('Loss: $60.00 / contract')).toBeVisible();
    // The full readout is kept, closed, in the explanation.
    for (const label of ['Premium-loss %', 'Remaining option value per share', 'Loss per contract (×100 shares)']) {
      expect(plan.getByText(label)).not.toBeVisible();
    }
  });

  it('keeps the time exit on one element and the warnings visible outside the explanation', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, invalidation: null } }} liveMid={0.01} />);
    const plan = within(exitPlan());
    expect(plan.getByText('3 days to expiry')).toBeVisible();
    const warning = plan.getByText(/Invalidation stop required — Send to broker stays disabled/);
    expect(warning).toBeVisible();
    expect(warning.closest('details')).toBeNull();
    const small = plan.getByText(/too small for a per-contract premium stop/);
    expect(small.closest('details')).toBeNull();
  });
});
