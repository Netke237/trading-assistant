import '@testing-library/jest-dom';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: ({ open }: { open: boolean }) => (
    <div data-testid="inline-chart" data-open={String(open)}>Chart</div>
  ),
}));

jest.mock('@/components/molecules/SymbolHeader', () => ({
  SymbolHeader: ({ ticker, company }: { ticker: string; company: string }) => (
    <div data-testid="symbol-header">{ticker} — {company}</div>
  ),
}))

jest.mock('@/components/molecules/ScoreCardPanel', () => ({
  ScoreCardPanel: ({ title }: { title: string }) => (
    <div data-testid="score-panel">{title}</div>
  ),
}));

jest.mock('@/components/molecules/LabeledStatusBadge', () => ({
  LabeledStatusBadge: ({ label, status }: { label: string; status: string }) => (
    <div data-testid="labeled-badge">{label}: {status}</div>
  ),
}));

const mockTradeCard: TradeCardData = {
  symbol: 'AAPL',
  company: 'Apple Inc.',
  price: 185.2,
  direction: 'Bullish',
  status: 'PASS',
  stockScore: 82,
  stockConfidence: 'PASS',
  stockBreakdown: {
    trend: 85,
    pullback: 78,
    trigger: 72,
    event: 90,
    volatility: 65,
  },
  contract: 'AAPL 190C 05/15',
  contractScore: 70,
  contractConfidence: 'PASS',
  contractBreakdown: {
    dteFit: 80,
    delta: 65,
    ivAttractiveness: 55,
    liquidity: 75,
    spread: 60,
  },
  contractDetails: {
    strike: 190,
    expiry: '2026-05-15',
    right: 'C',
    mid: 2.5,
    delta: 0.45,
    theta: -0.09,
    ivRank: 45,
    dte: 24,
  },
  entry: {
    limit: 2.5,
    maxFill: 2.63,
    orderType: 'Limit',
  },
  exit: {
    invalidation: 179.64,
    premiumStop: 1.5,
    timeStopDays: 10,
    target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 5.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
    ],
  },
  rrRatio: 2.5,
  rrModel: 'Heston repriced',
  finalStatus: 'PASS',
};

describe('TradeCard', () => {
  it('renders symbol and company in header', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByTestId('symbol-header')).toHaveTextContent('AAPL — Apple Inc.');
  });

  it('renders stock and contract score panels', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Stock Scorecard')).toBeInTheDocument();
    expect(screen.getByText('Contract — AAPL 190C 05/15')).toBeInTheDocument();
  });

  it('renders contract details when provided', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Contract Details')).toBeInTheDocument();
    expect(screen.getByText('$190')).toBeInTheDocument();
    expect(screen.getByText('2026-05-15')).toBeInTheDocument();
    expect(screen.getByText('Call')).toBeInTheDocument();
    expect(screen.getByText('0.45')).toBeInTheDocument();
    expect(screen.getByText('$-0.09')).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('24d')).toBeInTheDocument();
    const mids = screen.getAllByText('$2.50');
    expect(mids.length).toBeGreaterThanOrEqual(1);
  });

  it('renders entry plan section', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Entry Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Max fill')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
  });

  it('renders exit plan section', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Exit Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Time stop')).toBeInTheDocument();
  });

  it('renders sell-to-close plan with editable target', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Sell-to-Close Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit target stock price for TP1')).toBeInTheDocument();
  });

  it('renders risk/reward ratio', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Risk / Reward')).toBeInTheDocument();
    expect(screen.getByText('2.5×')).toBeInTheDocument();
  });

  it('renders final status', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByTestId('labeled-badge')).toHaveTextContent('Final Status: PASS');
  });

  it('shows send-to-broker button disabled when no handler provided', () => {
    render(<TradeCard data={mockTradeCard} />);
    const btn = screen.getByRole('button', { name: /send to broker/i });
    expect(btn).toBeDisabled();
  });

  it('shows send-to-broker button enabled when handler provided', () => {
    const onSend = jest.fn();
    render(<TradeCard data={mockTradeCard} onSendToBroker={onSend} />);
    const btn = screen.getByRole('button', { name: /send to broker/i });
    expect(btn).toBeEnabled();
  });

  it('uses custom send label when provided', () => {
    render(<TradeCard data={mockTradeCard} onSendToBroker={() => {}} sendLabel="Send (3)" />);
    expect(screen.getByRole('button', { name: /send \(3\)/i })).toBeInTheDocument();
  });

  it('toggles chart visibility on button click', async () => {
    render(<TradeCard data={mockTradeCard} />);
    const chart = screen.getByTestId('inline-chart');
    expect(chart).toHaveAttribute('data-open', 'false');

    const btn = screen.getByRole('button', { name: /view chart/i });
    await act(async () => {
      btn.click();
    });

    expect(screen.getByTestId('inline-chart')).toHaveAttribute('data-open', 'true');
    expect(screen.getByRole('button', { name: /hide chart/i })).toBeInTheDocument();
  });

  it('shows historical accuracy label for confidence row', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Historical accuracy (3×ATR exit)')).toBeInTheDocument();
    expect(screen.queryByText('Stock confidence')).not.toBeInTheDocument();
  });

  it('shows projected RR label with method note', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Projected R/R (+8% stock move)')).toBeInTheDocument();
    expect(screen.queryByText('R:R ratio')).not.toBeInTheDocument();
  });

  describe('editable fields', () => {
    it('renders editable fields with aria-label affordance', () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Max fill')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Time stop')).toBeInTheDocument();
    });

    it('opens inline input when clicking editable limit field', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      expect(screen.getByDisplayValue('2.5')).toBeInTheDocument();
      expect(screen.getByDisplayValue('2.5')).toHaveAttribute('type', 'number');
    });

    it('saves edited value on blur', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.50' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$3.50');
    });

    it('saves edited value on Enter key', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '4.00' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$4.00');
    });

    it('cancels edit on Escape key', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '99.99' } });
        fireEvent.keyDown(input, { key: 'Escape' });
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$2.50');
    });

    it('updates R:R section to show edited model when entry limit changes', async () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getAllByText('Heston repriced').length).toBeGreaterThanOrEqual(1);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '5.0' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getAllByText(/Edit \(delta approx\)/).length).toBeGreaterThanOrEqual(1);
    });

    it('shows edited badge in target row when stock price is changed', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const targetTrigger = screen.getByLabelText('Edit target stock price for TP1');
      await act(async () => {
        fireEvent.click(targetTrigger);
      });
      const input = screen.getByDisplayValue('200.02');
      await act(async () => {
        fireEvent.change(input, { target: { value: '210.00' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByText('edited')).toBeInTheDocument();
    });

    it('updates contracts display', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const contractsTrigger = screen.getByLabelText('Edit Contracts');
      await act(async () => {
        fireEvent.click(contractsTrigger);
      });
      const input = screen.getByDisplayValue('1');
      await act(async () => {
        fireEvent.change(input, { target: { value: '5' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('5');
    });

    it('clamps entry limit to minimum 0.01 on save', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '0.001' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$0.01');
    });

    it('clamps contracts to minimum 1 on save', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const contractsTrigger = screen.getByLabelText('Edit Contracts');
      await act(async () => {
        fireEvent.click(contractsTrigger);
      });
      const input = screen.getByDisplayValue('1');
      await act(async () => {
        fireEvent.change(input, { target: { value: '0' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('1');
    });

    it('fires onEditsChange callback when overlay changes', async () => {
      const onEditsChange = jest.fn();
      render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.0' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(onEditsChange).toHaveBeenCalledWith(
        expect.objectContaining({ entryLimit: 3.0 }),
      );
    });

    it('shows edited indicator in R:R sections when values differ from original', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.50' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      const editedLabels = screen.getAllByText(/edited/);
      expect(editedLabels.length).toBeGreaterThanOrEqual(1);
    });
  });
});