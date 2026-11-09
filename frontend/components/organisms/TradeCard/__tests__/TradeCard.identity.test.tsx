import '@testing-library/jest-dom';
import * as React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { TradeCard } from '..';
import { fundamentalScoreTooltip, safetyFlagTooltip } from '@/lib/statusTooltips';
import type { TradeCardData, SentimentData } from '@/types/domain';

// TC-REVIEW-02 (#577) — identity and market context. Presentation only: the
// contract the trader is looking at must be readable at a glance (strike,
// call/put, expiry WITH its year), Fundamental Health sits directly beneath
// Market Sentiment, and nothing already on the card is lost on the way.

jest.mock('@/lib/api', () => ({ api: {
  getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
  getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
} }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: ({ open }: { open: boolean }) => (
    <div data-testid="inline-chart" data-open={String(open)}>Chart</div>
  ),
}));

const sentiment: SentimentData = {
  horizon: 'Swing', timeframe: 'daily', state: 'Bull', p_stay: 0.876,
  stability: 'Stable', regime_age_days: 12, avg_regime_duration: 31.5,
  conviction_pct: 27.4, conviction_label: 'Strong conviction',
  interpretation: 'The regime favours this trade.', alignment: 'Aligned',
};

const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 2.5,
    delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: { invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02, targets: [] },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  sentiment,
  fundamentals: { score: 64, growth_score: 65, quality_score: 40, risk_score: 39,
    quality_label: 'Strong', risk_label: 'High', safety_flags: ['negative_equity'], detail: {} },
};

const spread: TradeCardData = {
  ...card, direction: 'Bearish', contract: 'AAPL 190P 05/15',
  contractDetails: { ...card.contractDetails!, right: 'P' },
  spreadType: 'bear_put',
  legs: [
    { action: 'BUY', qty: 1, strike: 190, right: 'P', expiry: '2026-05-15', bid: 5, ask: 5.2 },
    { action: 'SELL', qty: 1, strike: 180.5, right: 'P', expiry: '2026-05-15', bid: 2.2, ask: 2.4 },
  ],
  netDebitCredit: -2.75, maxProfit: 725, maxLoss: 275, breakeven: 187.25,
};

const follows = (a: Element, b: Element) =>
  (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

beforeEach(() => localStorage.clear());

describe('TradeCard identity and market context (#577)', () => {
  it('orders Market Sentiment, then Fundamental Health, then the identity, then the folded scores', () => {
    render(<TradeCard data={card} />);
    const sentimentNode = screen.getByText('Market Sentiment');
    const health = screen.getByText('Fundamental Health');
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const scores = screen.getByRole('button', { name: /Stock Qualification/ });
    expect(follows(sentimentNode, health)).toBe(true);
    expect(follows(health, identity)).toBe(true);
    expect(identity).toContainElement(scores);
    expect(follows(within(identity).getByText('Contract Details'), scores)).toBe(true);
    expect(screen.getAllByText('Fundamental Health')).toHaveLength(1);
  });

  it('promotes strike, call/put and an expiry that carries its year beside the symbol', () => {
    render(<TradeCard data={card} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const headline = within(identity).getByRole('group', { name: 'Contract identity' });
    expect(within(headline).getByText('Selected contract')).toBeInTheDocument();
    expect(within(headline).getByText('$190 Call')).toBeInTheDocument();
    expect(within(headline).getByText('Expires 15 May 2026')).toBeInTheDocument();
    // Beside the symbol: the headline sits in the identity header, ahead of
    // the snapshot note and the score/contract facts.
    expect(follows(within(identity).getByText('AAPL'), headline)).toBe(true);
    expect(follows(headline, within(identity).getByText(/Stock and contract snapshots/))).toBe(true);
    // The older ambiguous label (no year) is still shown as the contract id.
    expect(within(identity).getAllByText('AAPL 190C 05/15').length).toBeGreaterThan(0);
  });

  it('keeps a put readable and never fabricates a year for a non-ISO expiry', () => {
    const { rerender } = render(<TradeCard data={{ ...card, contractDetails: { ...card.contractDetails!, right: 'P', strike: 182.5 } }} />);
    let headline = screen.getByRole('group', { name: 'Contract identity' });
    expect(within(headline).getByText('$182.5 Put')).toBeInTheDocument();
    rerender(<TradeCard data={{ ...card, contractDetails: { ...card.contractDetails!, expiry: '05/15' } }} />);
    headline = screen.getByRole('group', { name: 'Contract identity' });
    expect(within(headline).getByText('Expires 05/15')).toBeInTheDocument();
    rerender(<TradeCard data={{ ...card, contractDetails: undefined }} />);
    headline = screen.getByRole('group', { name: 'Contract identity' });
    expect(within(headline).getByText('AAPL 190C 05/15')).toBeInTheDocument();
    expect(within(headline).queryByText(/Expires/)).not.toBeInTheDocument();
  });

  it('identifies every leg of a multi-leg spread prominently and keeps the spread panel and results', () => {
    render(<TradeCard data={spread} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const headline = within(identity).getByRole('group', { name: 'Contract identity' });
    expect(within(headline).getByText('$190 Put')).toBeInTheDocument();
    expect(within(headline).getByText('Bear Put Spread')).toBeInTheDocument();
    expect(within(headline).getByText('Buy 1 × $190 Put · Expires 15 May 2026')).toBeInTheDocument();
    expect(within(headline).getByText('Sell 1 × $180.5 Put · Expires 15 May 2026')).toBeInTheDocument();
    // The full spread panel and its spread-specific results are unchanged.
    expect(within(identity).getByText(/Spread Legs/)).toHaveTextContent('Bear Put Spread');
    for (const value of ['−$2.75', '$725.00', '$275.00', '$187.25', 'BUY', 'SELL', '$180.5']) {
      expect(within(identity).getByText(value)).toBeInTheDocument();
    }
  });

  it('keeps the chart jump beside the symbol opening a separate tab, and the inline chart toggle', () => {
    const open = jest.spyOn(window, 'open').mockImplementation(() => null);
    render(<TradeCard data={card} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const jump = within(identity).getByTitle('Open in Chart');
    expect(jump.parentElement).toContainElement(within(identity).getByText('AAPL'));
    fireEvent.click(jump);
    expect(open).toHaveBeenCalledWith('/chart?symbol=AAPL', '_blank');
    expect(screen.getByTestId('inline-chart')).toHaveAttribute('data-open', 'false');
    open.mockRestore();
  });

  it('keeps the complete selected Contract Details below the identity', () => {
    render(<TradeCard data={card} contracts={2} />);
    const identity = screen.getByRole('region', { name: 'Selected stock and contract' });
    const headline = within(identity).getByRole('group', { name: 'Contract identity' });
    const details = within(identity).getByText('Contract Details');
    expect(follows(headline, details)).toBe(true);
    const cell = (label: string) => within(identity).getByText(label).parentElement!;
    expect(cell('STRIKE')).toHaveTextContent('$190');
    expect(cell('EXPIRY')).toHaveTextContent('2026-05-15');
    expect(cell('RIGHT')).toHaveTextContent('Call');
    expect(cell('MID')).toHaveTextContent('$2.50');
    expect(cell('Δ')).toHaveTextContent('0.45');
    expect(cell('Θ / DAY')).toHaveTextContent('$-0.09');
    expect(cell('IV RANK')).toHaveTextContent('45');
    expect(cell('DTE')).toHaveTextContent('24d');
    expect(cell('CAR')).toHaveTextContent('$500');
  });

  it('keeps every Fundamental Health score, badge, colour and definition, and its missing-data state', () => {
    const { rerender } = render(<TradeCard data={card} />);
    const health = screen.getByText('Fundamental Health').closest('div')!.parentElement!;
    expect(within(health).getByText('64')).toBeInTheDocument();
    expect(within(health).getByText('Strong quality · High risk')).toBeInTheDocument();
    expect(within(health).getByText('negative equity')).toBeInTheDocument();
    expect(within(health).getByText('Score definitions & safety flags')).toBeInTheDocument();
    for (const text of [fundamentalScoreTooltip('overall', 64), fundamentalScoreTooltip('growth', 65),
      fundamentalScoreTooltip('quality', 40), fundamentalScoreTooltip('risk', 39),
      safetyFlagTooltip('negative_equity')]) {
      expect(within(health).getAllByText(text).length).toBeGreaterThan(0);
    }
    rerender(<TradeCard data={{ ...card, fundamentals: null }} />);
    expect(screen.getByText('Fundamental Health — no data')).toBeInTheDocument();
    expect(follows(screen.getByText('Market Sentiment'), screen.getByText('Fundamental Health — no data'))).toBe(true);
  });

  it('lets the page own both market-context blocks without mounting a second copy', () => {
    render(<TradeCard data={card} showMarketSentiment={false} showFundamentalHealth={false} />);
    expect(screen.queryByText('Market Sentiment')).not.toBeInTheDocument();
    expect(screen.queryByText('Fundamental Health')).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Contract identity' })).toBeInTheDocument();
  });
});
