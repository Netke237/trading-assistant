import { renderHook, act } from '@testing-library/react';
import { useScanStore } from '@/lib/scanStore';

describe('scanStore', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        scanState: 'IDLE',
        scanAt: null,
        context: null,
        regime: 'PENDING',
        scanResult: null,
        selectedSymbol: null,
      });
    });
  });

  it('starts in IDLE state', () => {
    const { result } = renderHook(() => useScanStore());
    expect(result.current.scanState).toBe('IDLE');
    expect(result.current.scanAt).toBeNull();
    expect(result.current.context).toBeNull();
    expect(result.current.regime).toBe('PENDING');
  });

  it('transitions IDLE -> SCANNING -> COMPLETED', () => {
    const { result } = renderHook(() => useScanStore());

    act(() => {
      result.current.setScanState('SCANNING', '2026-05-05T10:00:00');
    });
    expect(result.current.scanState).toBe('SCANNING');
    expect(result.current.scanAt).toBe('2026-05-05T10:00:00');

    act(() => {
      result.current.setScanState('COMPLETED', '2026-05-05T10:00:05');
    });
    expect(result.current.scanState).toBe('COMPLETED');
    expect(result.current.scanAt).toBe('2026-05-05T10:00:05');
  });

  it('sets and updates scan context', () => {
    const { result } = renderHook(() => useScanStore());

    act(() => {
      result.current.setContext({ universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' });
    });
    expect(result.current.context).toEqual({
      universe: 'SP500',
      direction: 'Bullish',
      horizon: 'Swing (5–15d)',
    });

    act(() => {
      result.current.setContext({ universe: 'NAS100', direction: 'Bearish', horizon: 'Position (30–90d)' });
    });
    expect(result.current.context).toEqual({
      universe: 'NAS100',
      direction: 'Bearish',
      horizon: 'Position (30–90d)',
    });
  });

  it('sets regime status', () => {
    const { result } = renderHook(() => useScanStore());

    act(() => {
      result.current.setRegime('PASS');
    });
    expect(result.current.regime).toBe('PASS');

    act(() => {
      result.current.setRegime('REJECT');
    });
    expect(result.current.regime).toBe('REJECT');
  });

  it('sets scan result with candidates', () => {
    const { result } = renderHook(() => useScanStore());
    const mockResult = {
      scan_id: 'REC-20260505-A1B2C3D4',
      timestamp: '2026-05-05T10:00:00Z',
      rejected: [],
      candidates: [],
    };

    act(() => {
      result.current.setScanResult(mockResult);
    });
    expect(result.current.scanResult).toEqual(mockResult);
  });

  it('shifts old scan result into previousRun when setting new result', () => {
    const { result } = renderHook(() => useScanStore());
    const firstResult = {
      scan_id: 'REC-20260504-A1B2C3D4',
      timestamp: '2026-05-04T09:30:00',
      rejected: [],
      candidates: [{ symbol: 'AAPL', stockScore: 80 } as any],
    };
    const secondResult = {
      scan_id: 'REC-20260505-E5F6G7H8',
      timestamp: '2026-05-05T10:00:00',
      rejected: [],
      candidates: [{ symbol: 'AAPL', stockScore: 85 } as any],
    };

    act(() => {
      result.current.setScanResult(firstResult);
    });
    expect(result.current.scanResult).toEqual(firstResult);
    expect(result.current.previousRun).toBeNull();

    act(() => {
      result.current.setScanResult(secondResult);
    });
    expect(result.current.scanResult).toEqual(secondResult);
    expect(result.current.previousRun).toEqual(firstResult);
  });

  it('preserves previousRun when clearing scan result', () => {
    const { result } = renderHook(() => useScanStore());
    const firstResult = {
      scan_id: 'REC-1',
      timestamp: '2026-05-04T09:30:00',
      rejected: [],
      candidates: [],
    };
    const secondResult = {
      scan_id: 'REC-2',
      timestamp: '2026-05-05T10:00:00',
      rejected: [],
      candidates: [],
    };

    act(() => {
      result.current.setScanResult(firstResult);
    });
    act(() => {
      result.current.setScanResult(secondResult);
    });
    expect(result.current.previousRun).toEqual(firstResult);

    act(() => {
      result.current.setScanResult(null);
    });
    expect(result.current.scanResult).toBeNull();
    expect(result.current.previousRun).toEqual(firstResult);
  });

  it('sets selected symbol', () => {
    const { result } = renderHook(() => useScanStore());

    act(() => {
      result.current.setSelectedSymbol('AAPL');
    });
    expect(result.current.selectedSymbol).toBe('AAPL');
  });

  it('clears scan result', () => {
    const { result } = renderHook(() => useScanStore());

    act(() => {
      result.current.setScanResult({ scan_id: '1', timestamp: 't', rejected: [], candidates: [] });
    });
    expect(result.current.scanResult).not.toBeNull();

    act(() => {
      result.current.setScanResult(null);
    });
    expect(result.current.scanResult).toBeNull();
  });
});
