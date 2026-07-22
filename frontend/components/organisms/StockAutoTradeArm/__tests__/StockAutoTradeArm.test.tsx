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

  it('arms a watch with the given direction', async () => {
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
      expect(mockAdd).toHaveBeenCalledWith('TSLA', 'pullback_ema', 'Bearish');
    });
  });
});
