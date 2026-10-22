import { renderHook, act } from '@testing-library/react';
import { useStrategyWatchStore } from '@/lib/strategyWatchStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getStrategyWatches: jest.fn().mockResolvedValue([]),
    getStrategyWatchSchedule: jest.fn().mockResolvedValue({
      enabled: false, mode: 'eod', eod_time: '16:15', poll_hours: 4, sustain_minutes: 0,
    }),
    addStrategyWatch: jest.fn().mockResolvedValue({}),
    addStrategyWatchesBulk: jest.fn().mockResolvedValue({ added: 0, watches: [] }),
  },
}));

const mockAdd = api.addStrategyWatch as jest.MockedFunction<typeof api.addStrategyWatch>;
const mockAddBulk = api.addStrategyWatchesBulk as jest.MockedFunction<typeof api.addStrategyWatchesBulk>;

describe('strategyWatchStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      useStrategyWatchStore.setState({ watches: [], schedule: null, loading: false, error: null });
    });
  });

  it('add() defaults direction to Bullish when none is given', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.add('AAPL', 'pullback_ema');
    });
    expect(mockAdd).toHaveBeenCalledWith('AAPL', 'pullback_ema', 'Bullish', null);
  });

  it('add() passes through an explicit Bearish direction', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.add('AAPL', 'pullback_ema', 'Bearish');
    });
    expect(mockAdd).toHaveBeenCalledWith('AAPL', 'pullback_ema', 'Bearish', null);
  });

  it('addBulk() passes through direction', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.addBulk(['AAPL', 'MSFT'], 'breakout_base', 'Bearish');
    });
    expect(mockAddBulk).toHaveBeenCalledWith(['AAPL', 'MSFT'], 'breakout_base', 'Bearish', null);
  });
});
