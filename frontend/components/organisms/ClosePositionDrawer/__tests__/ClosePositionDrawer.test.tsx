import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { ClosePositionDrawer } from '@/components/organisms/ClosePositionDrawer';
import type { PortfolioPosition } from '@/types/domain';

function makePosition(overrides: Partial<PortfolioPosition>): PortfolioPosition {
  return {
    symbol: 'AAPL',
    contract: 'AAPL|STOCK',
    direction: 'Bullish',
    entryDate: '2026-01-01',
    expiry: '',
    dteRemaining: 0,
    dteTotal: 0,
    entryPrice: 100,
    currentPrice: 100,
    pnlDollar: 0,
    pnlPct: 0,
    stop: null,
    targets: [],
    status: 'PENDING',
    contracts: 1,
    recId: 'PAPER-test',
    ...overrides,
  } as PortfolioPosition;
}

const noop = () => {};

describe('ClosePositionDrawer realized P&L', () => {
  it('long stock: profit when exit price is above entry', () => {
    const position = makePosition({
      contract: 'AAPL|STOCK', direction: 'Bullish', entryPrice: 100, currentPrice: 110, contracts: 10,
    });
    render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    // (110 - 100) * 1 (stock multiplier) * 10 shares = +$100, +10%
    expect(screen.getByText(/\+\$100\b/)).toBeInTheDocument();
    expect(screen.getByText(/\+10\.0%/)).toBeInTheDocument();
  });

  it('short stock: profit when exit price is below entry (not a loss)', () => {
    const position = makePosition({
      contract: 'TSLA|STOCK', direction: 'Bearish', entryPrice: 100, currentPrice: 90, contracts: 5,
    });
    render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    // Covering a short at a lower price is a profit: (100 - 90) * 1 * 5 = +$50, +10%
    expect(screen.getByText(/\+\$50\b/)).toBeInTheDocument();
    expect(screen.getByText(/\+10\.0%/)).toBeInTheDocument();
  });

  it('short stock: loss when exit price is above entry', () => {
    const position = makePosition({
      contract: 'TSLA|STOCK', direction: 'Bearish', entryPrice: 100, currentPrice: 110, contracts: 5,
    });
    render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    // (100 - 110) * 1 * 5 = -$50, -10%. Rendered with a Unicode minus before
    // the "$" (PORTFOLIO-NUMBERS T3): "−$50", "−10.0%".
    expect(screen.getByText(/−\$50\b/)).toBeInTheDocument();
    expect(screen.getByText(/−10\.0%/)).toBeInTheDocument();
  });

  it('long option: uses the 100x contract multiplier, not the stock 1x multiplier', () => {
    const position = makePosition({
      contract: 'AAPL 185C 05/16', direction: 'Bullish', entryPrice: 2, currentPrice: 3, contracts: 2,
    });
    render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    // (3 - 2) * 100 * 2 contracts = +$200, +50%
    expect(screen.getByText(/\+\$200\b/)).toBeInTheDocument();
    expect(screen.getByText(/\+50\.0%/)).toBeInTheDocument();
  });

  it('short option (long put entered on a bearish view): still priced with the 100x multiplier', () => {
    const position = makePosition({
      contract: 'AAPL 185P 05/16', direction: 'Bearish', entryPrice: 2, currentPrice: 1, contracts: 2,
    });
    render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    // A long put is still a BUY-to-open position, not a short — closing it is a plain
    // sell-to-close, so P&L follows the long formula regardless of the Bearish direction
    // tag: (1 - 2) * 100 * 2 = -$200, -50%. Rendered as "−$200" (Unicode minus).
    expect(screen.getByText(/−\$200\b/)).toBeInTheDocument();
    expect(screen.getByText(/−50\.0%/)).toBeInTheDocument();
  });
});

describe('ClosePositionDrawer title (PORTFOLIO-NUMBERS T3)', () => {
  it('shows a readable option contract and keeps the raw key as the title', () => {
    const position = makePosition({ contract: 'AAPL|185|2027-01-15|C', entryPrice: 2, currentPrice: 3 });
    const { container } = render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    const titled = container.querySelector('[title="AAPL|185|2027-01-15|C"]') as HTMLElement;
    expect(titled).not.toBeNull();
    expect(titled).toHaveTextContent('Close AAPL 185C · 15 Jan 27');
    expect(screen.queryByText(/AAPL\|185\|2027-01-15\|C/)).not.toBeInTheDocument();
  });

  it('shows "Stock" for a stock row, the raw key as the title', () => {
    const position = makePosition({ contract: 'AAPL|STOCK' });
    const { container } = render(<ClosePositionDrawer position={position} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    expect(screen.getByText('Close AAPL Stock')).toBeInTheDocument();
    expect(container.querySelector('[title="AAPL|STOCK"]')).not.toBeNull();
  });
});

/* Open question 54 (C1): the row can shrink under an open dialog (a close-404
 * re-save or a qty edit booked smaller). The drawer must follow it, so the
 * preview and the next confirm describe the size actually held. */
describe('ClosePositionDrawer — the row changes size under an open dialog', () => {
  const big = makePosition({ contract: 'AAA|STOCK', entryPrice: 100, currentPrice: 110, contracts: 100 });

  it('clamps the quantity to the new size and sends it on the next confirm', () => {
    const onConfirm = jest.fn();
    const { rerender } = render(<ClosePositionDrawer position={big} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect(screen.getByText(/\+\$1,000\b/)).toBeInTheDocument();

    rerender(<ClosePositionDrawer position={{ ...big, contracts: 33 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect(screen.getByText(/of 33/)).toBeInTheDocument();
    expect(screen.getByText(/\+\$330\b/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /close position/i }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ qtyToClose: 33 }));
  });

  it('caps a typed partial size at the new, smaller held size', () => {
    const onConfirm = jest.fn();
    const { rerender } = render(<ClosePositionDrawer position={big} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    fireEvent.change(screen.getByLabelText(/contracts to sell/i), { target: { value: '50' } });
    rerender(<ClosePositionDrawer position={{ ...big, contracts: 33 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect(screen.getByLabelText(/contracts to sell/i)).toHaveValue(33);
    fireEvent.click(screen.getByRole('button', { name: /close position/i }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ qtyToClose: 33 }));
  });

  it('keeps a full close full when the row grows', () => {
    const onConfirm = jest.fn();
    const { rerender } = render(<ClosePositionDrawer position={big} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    rerender(<ClosePositionDrawer position={{ ...big, contracts: 150 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect(screen.getByText(/of 150/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /close position/i }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ qtyToClose: 150 }));
  });

  it('keeps a smaller partial size, and never raises it when the row grows', () => {
    const onConfirm = jest.fn();
    const { rerender } = render(<ClosePositionDrawer position={big} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    fireEvent.change(screen.getByLabelText(/contracts to sell/i), { target: { value: '20' } });

    rerender(<ClosePositionDrawer position={{ ...big, contracts: 33 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    rerender(<ClosePositionDrawer position={{ ...big, contracts: 150 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole('button', { name: /sell 20 of 150/i }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ qtyToClose: 20 }));
  });
});

describe('ClosePositionDrawer exit reason (PORTFOLIO-EXIT-RECORD)', () => {
  const optionPos = (over: Partial<PortfolioPosition> = {}) => makePosition({
    contract: 'AAA|100|2099-01-15|C', direction: 'Bullish', entryPrice: 5, currentPrice: 5,
    currentStockPrice: 100, dteRemaining: 40, stop: 90, targets: [{ stockPrice: 120 } as never],
    ...over,
  });

  it('renders a required Reason select with all 8 labels, pre-selected from the default', () => {
    render(<ClosePositionDrawer position={optionPos({ currentStockPrice: 89 })} premiumStopPct={0.6} onCancel={noop} onConfirm={noop} />);
    const select = screen.getByLabelText('Exit reason') as HTMLSelectElement;
    expect(select).toBeRequired();
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      'Stop', 'Structural stop', 'Premium stop', 'Target', 'Time stop', 'Expiry', 'Manual', 'Unknown',
    ]);
    expect(select.value).toBe('stop');
  });

  it('defaults to manual when nothing triggered and sends it in onConfirm', () => {
    const onConfirm = jest.fn();
    render(<ClosePositionDrawer position={optionPos()} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect((screen.getByLabelText('Exit reason') as HTMLSelectElement).value).toBe('manual');
    fireEvent.click(screen.getByRole('button', { name: /Close position/ }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ exitReason: 'manual' }));
  });

  it('sends the edited value in onConfirm', () => {
    const onConfirm = jest.fn();
    render(<ClosePositionDrawer position={optionPos({ currentStockPrice: 89 })} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    fireEvent.change(screen.getByLabelText('Exit reason'), { target: { value: 'target' } });
    fireEvent.click(screen.getByRole('button', { name: /Close position/ }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ exitReason: 'target' }));
  });

  it('computes the default once on open: a later row change does not overwrite it', () => {
    const onConfirm = jest.fn();
    const p = optionPos();
    const { rerender } = render(<ClosePositionDrawer position={p} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    rerender(<ClosePositionDrawer position={{ ...p, currentStockPrice: 89 }} premiumStopPct={0.6} onCancel={noop} onConfirm={onConfirm} />);
    expect((screen.getByLabelText('Exit reason') as HTMLSelectElement).value).toBe('manual');
  });
});
