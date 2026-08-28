import { act } from '@testing-library/react';
import { useNotesStore, flushPendingNoteSave } from '@/lib/notesStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getSymbolNote: jest.fn(),
    putSymbolNote: jest.fn(),
  },
}));

const mockGet = api.getSymbolNote as jest.Mock;
const mockPut = api.putSymbolNote as jest.Mock;

describe('notesStore', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    useNotesStore.setState({ notes: {} });
    mockGet.mockReset();
    mockPut.mockReset();
    mockPut.mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: '2026-08-28T00:00:00Z' });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('fetchNote loads a note and uppercases the symbol key', async () => {
    mockGet.mockResolvedValueOnce({ symbol: 'AAPL', body: 'watching for breakout', updatedAt: '2026-08-01T00:00:00Z' });

    await act(async () => {
      await useNotesStore.getState().fetchNote('aapl');
    });

    expect(mockGet).toHaveBeenCalledWith('AAPL');
    expect(useNotesStore.getState().notes['AAPL']).toMatchObject({
      body: 'watching for breakout',
      loaded: true,
      error: false,
    });
  });

  it('fetchNote does not overwrite a note the user already started editing', async () => {
    let resolveGet: (v: unknown) => void = () => {};
    mockGet.mockReturnValueOnce(new Promise((resolve) => { resolveGet = resolve; }));

    const fetchPromise = useNotesStore.getState().fetchNote('AAPL');
    // User types before the GET resolves.
    act(() => { useNotesStore.getState().setNoteBody('AAPL', 'my own note'); });

    await act(async () => {
      resolveGet({ symbol: 'AAPL', body: 'stale server value', updatedAt: null });
      await fetchPromise;
    });

    expect(useNotesStore.getState().notes['AAPL'].body).toBe('my own note');
  });

  it('setNoteBody applies the edit locally right away, before the debounce fires', () => {
    act(() => { useNotesStore.getState().setNoteBody('tsla', 'buy the dip'); });

    expect(useNotesStore.getState().notes['TSLA']).toMatchObject({ body: 'buy the dip', saving: true });
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('debounces rapid edits into a single PUT', async () => {
    act(() => { useNotesStore.getState().setNoteBody('MSFT', 'a'); });
    act(() => { jest.advanceTimersByTime(300); });
    act(() => { useNotesStore.getState().setNoteBody('MSFT', 'ab'); });
    act(() => { jest.advanceTimersByTime(300); });
    act(() => { useNotesStore.getState().setNoteBody('MSFT', 'abc'); });

    await act(async () => { jest.advanceTimersByTime(600); });

    expect(mockPut).toHaveBeenCalledTimes(1);
    expect(mockPut).toHaveBeenCalledWith('MSFT', 'abc');
  });

  it('clears the saving flag once the debounced PUT resolves', async () => {
    act(() => { useNotesStore.getState().setNoteBody('NVDA', 'note body'); });
    expect(useNotesStore.getState().notes['NVDA'].saving).toBe(true);

    await act(async () => { jest.advanceTimersByTime(600); });

    expect(useNotesStore.getState().notes['NVDA'].saving).toBe(false);
    expect(useNotesStore.getState().notes['NVDA'].error).toBe(false);
  });

  it('marks the note errored when the PUT fails', async () => {
    mockPut.mockRejectedValueOnce(new Error('network down'));
    act(() => { useNotesStore.getState().setNoteBody('AMD', 'note body'); });

    await act(async () => { jest.advanceTimersByTime(600); });

    expect(useNotesStore.getState().notes['AMD'].saving).toBe(false);
    expect(useNotesStore.getState().notes['AMD'].error).toBe(true);
  });

  it('flushPendingNoteSave sends an in-flight debounced edit immediately', async () => {
    act(() => { useNotesStore.getState().setNoteBody('GOOG', 'final note') });

    await act(async () => { flushPendingNoteSave('goog'); });

    expect(mockPut).toHaveBeenCalledWith('GOOG', 'final note');
    // The debounce timer must not fire a second, duplicate PUT later.
    await act(async () => { jest.advanceTimersByTime(600); });
    expect(mockPut).toHaveBeenCalledTimes(1);
  });

  it('flushPendingNoteSave is a no-op when nothing is pending', () => {
    flushPendingNoteSave('IBM');
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('a failed GET marks loadError without pretending the note is loaded/empty', async () => {
    mockGet.mockRejectedValueOnce(new Error('network down'));

    await act(async () => { await useNotesStore.getState().fetchNote('SPY'); });

    expect(useNotesStore.getState().notes['SPY']).toMatchObject({
      loaded: false,
      loadError: true,
    });
  });

  it('a failed GET can be retried and does not permanently block re-fetching', async () => {
    mockGet.mockRejectedValueOnce(new Error('network down'));
    await act(async () => { await useNotesStore.getState().fetchNote('QQQ'); });
    expect(useNotesStore.getState().notes['QQQ'].loadError).toBe(true);

    mockGet.mockResolvedValueOnce({ symbol: 'QQQ', body: 'real note', updatedAt: '2026-08-01T00:00:00Z' });
    await act(async () => { await useNotesStore.getState().fetchNote('QQQ'); });

    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(useNotesStore.getState().notes['QQQ']).toMatchObject({
      body: 'real note',
      loaded: true,
      loadError: false,
    });
  });

  it('does not double-fetch when two callers request the same symbol concurrently', async () => {
    let resolveGet: (v: unknown) => void = () => {};
    mockGet.mockReturnValueOnce(new Promise((resolve) => { resolveGet = resolve; }));

    const p1 = useNotesStore.getState().fetchNote('AMZN');
    const p2 = useNotesStore.getState().fetchNote('AMZN');

    await act(async () => {
      resolveGet({ symbol: 'AMZN', body: 'note', updatedAt: null });
      await Promise.all([p1, p2]);
    });

    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('does not stamp a stale save-error onto a note a newer edit has already saved', async () => {
    // First edit's PUT will be slow and eventually fail.
    let rejectFirst: (e: unknown) => void = () => {};
    mockPut.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }));

    act(() => { useNotesStore.getState().setNoteBody('COIN', 'first draft'); });
    await act(async () => { jest.advanceTimersByTime(600); }); // fires the first (slow) PUT

    // A newer edit supersedes it and its PUT resolves successfully first.
    mockPut.mockResolvedValueOnce({ symbol: 'COIN', body: 'final version', updatedAt: '2026-08-28T00:00:00Z' });
    act(() => { useNotesStore.getState().setNoteBody('COIN', 'final version'); });
    await act(async () => { jest.advanceTimersByTime(600); }); // fires + resolves the second PUT

    expect(useNotesStore.getState().notes['COIN']).toMatchObject({ body: 'final version', saving: false, error: false });

    // The first (stale) PUT now rejects — it must not retroactively mark
    // today's already-saved content as errored.
    await act(async () => { rejectFirst(new Error('stale request finally failed')); });

    expect(useNotesStore.getState().notes['COIN']).toMatchObject({ body: 'final version', saving: false, error: false });
  });

  it('does not stamp a stale save-error onto a newer edit that happens to have identical text', async () => {
    // A body-text-equality staleness check (rather than a generation id)
    // would miss this: the user types "note", clears it, then types "note"
    // again — two DIFFERENT edits with the same text. If the first one's
    // now-stale PUT rejects after the second one's PUT already succeeded, a
    // text-equality guard sees the same string and wrongly concludes it's
    // still "the current edit," stamping an error onto content that is, in
    // fact, already safely saved.
    let rejectFirst: (e: unknown) => void = () => {};
    mockPut.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }));

    act(() => { useNotesStore.getState().setNoteBody('PLTR', 'note'); });
    await act(async () => { jest.advanceTimersByTime(600); }); // fires the first (slow) PUT

    mockPut.mockResolvedValueOnce({ symbol: 'PLTR', body: 'note', updatedAt: '2026-08-28T00:00:00Z' });
    act(() => { useNotesStore.getState().setNoteBody('PLTR', 'note'); }); // same text, a distinct later edit
    await act(async () => { jest.advanceTimersByTime(600); });

    expect(useNotesStore.getState().notes['PLTR']).toMatchObject({ body: 'note', saving: false, error: false });

    await act(async () => { rejectFirst(new Error('stale request finally failed')); });

    expect(useNotesStore.getState().notes['PLTR']).toMatchObject({ body: 'note', saving: false, error: false });
  });
});
