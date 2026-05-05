import { renderHook, act } from '@testing-library/react';
import { useWatchlistStore, WATCHLIST_STORAGE_KEY } from '@/lib/watchlistStore';

describe('watchlistStore', () => {
  let store: Storage;

  beforeEach(() => {
    store = {} as Storage;
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: jest.fn((key: string) => store[key] ?? null),
        setItem: jest.fn((key: string, value: string) => {
          store[key] = value;
        }),
        removeItem: jest.fn((key: string) => {
          delete store[key];
        }),
      },
      writable: true,
    });

    // Re-hydrate from empty localStorage for each test
    useWatchlistStore.persist.clearStorage();
    useWatchlistStore.setState({ added: [] });
  });

  it('starts with empty watchlist', () => {
    const { result } = renderHook(() => useWatchlistStore());
    expect(result.current.added).toEqual([]);
  });

  it('adds a symbol in uppercase', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('aapl');
    });
    expect(result.current.added).toContain('AAPL');
  });

  it('ignores duplicate adds', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('AAPL');
      result.current.addSymbol('AAPL');
    });
    expect(result.current.added).toEqual(['AAPL']);
  });

  it('removes a symbol', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('AAPL');
      result.current.addSymbol('MSFT');
    });
    expect(result.current.added).toHaveLength(2);

    act(() => {
      result.current.removeSymbol('AAPL');
    });
    expect(result.current.added).toEqual(['MSFT']);
  });

  it('isWatched returns true for watched symbols', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('AAPL');
    });

    expect(result.current.isWatched('AAPL')).toBe(true);
    expect(result.current.isWatched('MSFT')).toBe(false);
  });

  it('isWatched is case-insensitive', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('aapl');
    });

    expect(result.current.isWatched('AAPL')).toBe(true);
    expect(result.current.isWatched('aapl')).toBe(true);
  });

  it('ignores empty strings', () => {
    const { result } = renderHook(() => useWatchlistStore());

    act(() => {
      result.current.addSymbol('');
      result.current.addSymbol('  ');
    });
    expect(result.current.added).toEqual([]);
  });
});
