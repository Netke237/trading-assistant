import { renderHook, act } from '@testing-library/react';
import { useStructureStore } from '@/lib/structureStore';
import type { StructureSignal } from '@/types/structure';

const SAMPLE_SIGNALS: StructureSignal[] = [
  {
    kind: 'FVG',
    direction: 'bullish',
    time_start: '2024-01-03',
    time_end: null,
    price_high: 106,
    price_low: 103,
    mitigated: false,
    confidence: 72,
    mtf_aligned: false,
  },
];

describe('structureStore', () => {
  beforeEach(() => {
    useStructureStore.setState({
      signals: {},
      visibility: {
        FVG: true, BOS: true, CHoCH: true, OrderBlock: true,
        Divergence: true, Fibonacci: true, Confluence: true,
      },
      structureVisible: true,
    });
  });

  it('stores signals keyed by symbol:interval', () => {
    const { result } = renderHook(() => useStructureStore());
    act(() => result.current.setSignals('AAPL:15min', SAMPLE_SIGNALS));
    expect(result.current.signals['AAPL:15min']).toEqual(SAMPLE_SIGNALS);
  });

  it('toggles individual signal kind visibility', () => {
    const { result } = renderHook(() => useStructureStore());
    expect(result.current.visibility.FVG).toBe(true);
    act(() => result.current.toggleKind('FVG'));
    expect(result.current.visibility.FVG).toBe(false);
    act(() => result.current.toggleKind('FVG'));
    expect(result.current.visibility.FVG).toBe(true);
  });

  it('toggles overall structure visibility', () => {
    const { result } = renderHook(() => useStructureStore());
    expect(result.current.structureVisible).toBe(true);
    act(() => result.current.toggleStructure());
    expect(result.current.structureVisible).toBe(false);
  });

  it('clears signals for a key', () => {
    const { result } = renderHook(() => useStructureStore());
    act(() => result.current.setSignals('AAPL:15min', SAMPLE_SIGNALS));
    expect(result.current.signals['AAPL:15min']).toBeDefined();
    act(() => result.current.clearSignals('AAPL:15min'));
    expect(result.current.signals['AAPL:15min']).toBeUndefined();
  });
});
