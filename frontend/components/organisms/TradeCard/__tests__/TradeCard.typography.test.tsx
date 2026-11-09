import '@testing-library/jest-dom';
import * as React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { TradeCard } from '..';
import BarrierRaceCard from '@/components/organisms/BarrierRaceCard';
import type { BarrierRace, TradeCardData } from '@/types/domain';

// #610 acceptance fixes G1/G3/G13/G14/G15 — the readable-type and consistent
// disclosure pass. Presentation only: these pin which classes carry the text
// (size, tone, shared disclosure row, panel header), never a figure.
//
// The shared CSS-module mock is `{}`, so every class renders as `undefined`.
// Echo the key instead so the primitive size/tone classes and the card's own
// classes are observable (`__esModule` stays falsy for default-import interop).
jest.mock('@/components/primitives/Text.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));

jest.mock('@/lib/api', () => ({ api: {
  getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
  getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
} }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: () => null,
}));

const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 2.5,
    delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: { invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 192, estimatedOptionPrice: 3.4, contractsToSell: 1 },
      { id: 'tp2', stockPrice: 198, estimatedOptionPrice: 5.1, contractsToSell: 1 },
    ] },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
};

const words = (el: Element) => (el.textContent ?? '').trim().split(/\s+/).filter(Boolean).length;

beforeEach(() => localStorage.clear());

describe('G1 — explanatory text is readable sentence-case, not uppercase microtext', () => {
  it('keeps the uppercase size-10 style for short eyebrows only, and no prose in the dim tone', () => {
    const { container } = render(<TradeCard data={card} contracts={2} />);
    // Expand the Ladder too, so its notes are in the document.
    fireEvent.click(screen.getByRole('button', { name: /Fixed % Ladder Plan/, hidden: true }));
    // Eyebrows are labels ("ACTION", "MAX LOSS IF THE STOP IS HIT"), never a
    // sentence: no sentence punctuation and a heading's length at most.
    const microtext = Array.from(container.querySelectorAll('.s10'));
    for (const el of microtext) {
      expect([el.textContent, words(el) <= 7 && !/[.;:]/.test(el.textContent ?? '')]).toEqual([el.textContent, true]);
    }
    // The card's own sections (the shared score and fundamentals molecules
    // keep their own missing-data styling).
    const own = [container.querySelector('.grid'), screen.getByRole('region', { name: 'Contract Details' })];
    const dimProse = own.flatMap((root) => Array.from(root!.querySelectorAll('.toneDim')))
      .filter((el) => words(el) > 3);
    expect(dimProse.map((el) => el.textContent)).toEqual([]);
  });

  it('renders the Exit Plan explanations at 12px in the secondary tone', () => {
    render(<TradeCard data={card} />);
    const note = screen.getByText(/Invalidation is the editable execution stock stop/);
    expect(note).toHaveClass('s12', 'toneSecondary');
    expect(note).not.toHaveClass('s10');
  });

  it('keeps an actionable caution visible at its caution tone, at 12px', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, invalidation: null } }} />);
    const caution = within(screen.getByRole('region', { name: 'Exit Plan' }))
      .getByText(/Invalidation stop required — Send to broker stays disabled/);
    expect(caution).toHaveClass('s12', 'toneCaution');
    expect(caution.closest('details')).toBeNull();
  });

  it('moves the Monte Carlo independence note into its closed model disclosure', () => {
    render(<TradeCard data={card} />);
    const note = screen.getByText(/Monte Carlo estimate — independent of the other profit-target methods/);
    const details = note.closest('details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');
    expect(within(details as HTMLElement).getByText('Monte Carlo model, inputs & provenance')).toBeInTheDocument();
  });
});

describe('G3 — Contract Details is its own readable panel', () => {
  it('has its own heading region inside the identity, with 12px labels and bold 14px values', () => {
    render(<TradeCard data={card} contracts={2} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const panel = within(identity).getByRole('region', { name: 'Contract Details' });
    expect(within(panel).getByRole('heading', { name: 'Contract Details' })).toBeInTheDocument();
    expect(within(panel).getByText('Contract snapshot')).toBeInTheDocument();
    const cell = (label: string) => within(panel).getByText(label).parentElement!;
    const label = within(panel).getByText('Strike');
    expect(label).toHaveClass('s12', 'toneSecondary');
    expect(within(cell('Strike')).getByText('$190')).toHaveClass('s14', 'w600');
    expect(cell('Delta')).toHaveTextContent('0.45');
    expect(cell('Theta / day')).toHaveTextContent('−$0.09');
    expect(cell('Capital at risk')).toHaveTextContent('$500');
  });
});

describe('G13 — one disclosure row style', () => {
  it('gives every native disclosure on the card the shared disclosure row', () => {
    const { container } = render(<TradeCard data={card} />);
    const all = Array.from(container.querySelectorAll('details'));
    expect(all.length).toBeGreaterThan(3);
    for (const d of all) {
      expect([d.querySelector('summary')?.textContent, d.className]).toEqual([
        d.querySelector('summary')?.textContent, expect.stringContaining('disclosureRow'),
      ]);
      expect(d).not.toHaveAttribute('open');
    }
  });

  it('gives the Barrier Race explanation disclosure the same row', () => {
    const race: BarrierRace = {
      outcomes: [{
        targetPct: 0.2, targetOptionPrice: 6.24, pTargetFirst: 0.27, pStockStopFirst: 0,
        pPremiumStopFirst: 0.69, pNeither: 0.04, daysTarget: 7, daysStockStop: null,
        daysPremiumStop: 20, daysAnyPathReachedStop: 26, weightTargetFirst: 0.27,
        weightStockStopFirst: 0, weightPremiumStopFirst: 0.69, weightNeither: 0.04,
        terminalMean: 3.64, rewardDollar: 1.04, repriceDaysStockStop: 26, stopRepricedValue: 0.03,
        riskStockStop: 5.17, riskPremiumStop: 3.12, rrStockStop: 0.2, rrPremiumStop: 0.33,
        edgePerContract: -193,
      }],
      premiumStopPrice: 2.08, premiumStopPct: 0.6, stockStopPrice: 176, premiumUsed: 5.2,
      ivSolved: true, nPaths: 2000,
    };
    const { container } = render(<BarrierRaceCard race={race} premiumStopFromField premiumStopField={3.12} isFresh />);
    expect(container.querySelector('details')).toHaveClass('disclosureRow');
    expect(container.querySelectorAll('.s10')).toHaveLength(0);
  });
});

describe('G14 — consistent panel headers', () => {
  it('gives each top-level section the same header row with an h2 title', () => {
    render(<TradeCard data={card} />);
    for (const name of ['Contract Details', 'Exit Plan', 'Profit-target methods', 'Decision and execution']) {
      const region = screen.getByRole('region', { name });
      const head = region.querySelector('.panelHead');
      expect([name, head]).toEqual([name, expect.anything()]);
      const title = (head as HTMLElement).querySelector('h2');
      expect([name, title?.className]).toEqual([name, expect.stringContaining('s20')]);
    }
  });
});

describe('G15 — editable fields carry an Editable tag', () => {
  it('tags the Exit Plan and Order Entry editables, and not the read-only rows', () => {
    render(<TradeCard data={card} />);
    const exit = screen.getByRole('region', { name: 'Exit Plan' });
    const row = (root: HTMLElement, label: string) => within(root).getAllByText(label)
      .find((el) => el.classList.contains('toneSecondary'))!.closest('[class*="kvRow"]') as HTMLElement;
    expect(within(row(exit, 'Invalidation')).getByText('Editable')).toHaveClass('toneAccent');
    expect(within(row(exit, 'Premium stop')).getByText('Editable')).toBeInTheDocument();
    const order = screen.getByRole('region', { name: 'Order Entry' });
    expect(within(row(order, 'Limit')).getByText('Editable')).toBeInTheDocument();
    expect(within(row(order, 'Contracts')).getByText('Editable')).toBeInTheDocument();
    expect(within(row(order, 'Max fill')).queryByText('Editable')).not.toBeInTheDocument();
    expect(within(row(order, 'Order type')).queryByText('Editable')).not.toBeInTheDocument();
  });
});
