import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockAutoTradeArm } from '@/components/organisms/StockAutoTradeArm';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    addStrategyWatch: jest.fn().mockResolvedValue({ id: 'wch_test001' }),
  },
}));

const mockAdd = api.addStrategyWatch as jest.MockedFunction<typeof api.addStrategyWatch>;

describe('StockAutoTradeArm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('blocks a new watch arm while strategy validation is unavailable', async () => {
    render(
      <StockAutoTradeArm
        symbol="TSLA"
        strategyKey="pullback_ema"
        direction="Bearish"
        afterScanArmed={false}
        onAfterScanToggle={() => {}}
      />
    );

    fireEvent.click(screen.getByText('Armed — add to Strategy Watches now'));
    fireEvent.click(screen.getByText(/Watch TSLA — pullback_ema/));

    await waitFor(() => {
      expect(mockAdd).not.toHaveBeenCalled();
      expect(screen.getByText(/Unvalidated — research only/)).toBeInTheDocument();
    });
  });
});

it('shows retained after-scan intent on remount without granting execution', () => {
  render(<StockAutoTradeArm symbol="AAPL" strategyKey="pullback_ema" direction="Bullish" afterScanArmed onAfterScanToggle={() => {}} />);
  expect(screen.getByText(/After-scan intent saved for AAPL/)).toBeInTheDocument();
  expect(api.addStrategyWatch).not.toHaveBeenCalled();
});
