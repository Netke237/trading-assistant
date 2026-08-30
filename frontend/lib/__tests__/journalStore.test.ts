import { useJournalStore } from '@/lib/journalStore';
import { api } from '@/lib/api';
import type { JournalEntry, JournalEntryInput } from '@/types/journal';

jest.mock('@/lib/api', () => ({
  api: {
    getJournalEntries: jest.fn(),
    createJournalEntry: jest.fn(),
    updateJournalEntry: jest.fn(),
    deleteJournalEntry: jest.fn(),
  },
}));

function makeEntry(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 'e1',
    user_id: 'default',
    entry_type: 'trade',
    entry_date: '2026-08-01T00:00:00.000Z',
    symbol: 'AAPL',
    instrument_type: 'stock',
    direction: 'long',
    entry_price: 100,
    exit_price: null,
    position_size: 10,
    stop_loss: 95,
    risk_dollars: 50,
    net_pnl: null,
    thesis: 'Pullback to 20-EMA',
    strategy_tag: 'pullback_ema',
    mistake_tags: null,
    execution_grade: null,
    status: 'open',
    lessons_learned: null,
    notes: null,
    position_id: null,
    r_multiple: null,
    created_at: '2026-08-01T00:00:00.000Z',
    updated_at: '2026-08-01T00:00:00.000Z',
    ...overrides,
  };
}

function makeInput(overrides: Partial<JournalEntryInput> = {}): JournalEntryInput {
  const { id: _id, user_id: _u, r_multiple: _r, created_at: _c, updated_at: _up, ...rest } = makeEntry();
  return { ...rest, ...overrides };
}

describe('journalStore', () => {
  beforeEach(() => {
    useJournalStore.setState({ entries: [], loading: false, error: null });
    jest.clearAllMocks();
  });

  it('syncEntries loads entries and clears error on success', async () => {
    useJournalStore.setState({ error: 'stale error from before' });
    (api.getJournalEntries as jest.Mock).mockResolvedValue([makeEntry()]);

    await useJournalStore.getState().syncEntries();

    const s = useJournalStore.getState();
    expect(s.entries).toHaveLength(1);
    expect(s.loading).toBe(false);
    // (b) a successful syncEntries() call clears a pre-existing error — mount,
    // filter-change, and mutation-recovery paths all go through this same
    // success handler.
    expect(s.error).toBeNull();
  });

  it('syncEntries sets error when the fetch itself fails, independent of any mutation', async () => {
    // (c)
    (api.getJournalEntries as jest.Mock).mockRejectedValue(new Error('network down'));

    await useJournalStore.getState().syncEntries();

    const s = useJournalStore.getState();
    expect(s.entries).toEqual([]);
    expect(s.error).toBe('network down');
    expect(s.loading).toBe(false);
  });

  it('syncEntries forwards the filters object to api.getJournalEntries', async () => {
    (api.getJournalEntries as jest.Mock).mockResolvedValue([]);
    const filters = { symbol: 'AAPL', status: 'open' as const };
    await useJournalStore.getState().syncEntries(filters);
    expect(api.getJournalEntries).toHaveBeenCalledWith(filters);
  });

  it('createEntry adds the server-returned entry on success', async () => {
    const created = makeEntry({ id: 'server-1' });
    (api.createJournalEntry as jest.Mock).mockResolvedValue(created);

    await useJournalStore.getState().createEntry(makeInput());

    const s = useJournalStore.getState();
    expect(s.entries).toHaveLength(1);
    expect(s.entries[0].id).toBe('server-1');
  });

  it('(a) a failed createEntry rolls back, awaits syncEntries, and sets error only after it resolves', async () => {
    (api.createJournalEntry as jest.Mock).mockRejectedValue(new Error('create failed: 422'));
    // The reconcile GET succeeds (and would otherwise clear `error` right back
    // to null) — this is the case the ordering rule exists for.
    (api.getJournalEntries as jest.Mock).mockResolvedValue([makeEntry({ id: 'real-1' })]);

    await useJournalStore.getState().createEntry(makeInput());

    const s = useJournalStore.getState();
    // The optimistic temp row is gone, replaced by whatever syncEntries()
    // reconciled from the backend.
    expect(s.entries.map((e) => e.id)).toEqual(['real-1']);
    // syncEntries()'s own success cleared `error` to null first — the
    // mutation's own catch block must still land its message AFTER that,
    // or this would be null instead.
    expect(s.error).toBe('create failed: 422');
  });

  it('(a) a failed updateEntry rolls back to the prior entry, then sets error after syncEntries resolves', async () => {
    const original = makeEntry({ id: 'e1', symbol: 'AAPL' });
    useJournalStore.setState({ entries: [original] });
    (api.updateJournalEntry as jest.Mock).mockRejectedValue(new Error('update failed: 422'));
    (api.getJournalEntries as jest.Mock).mockResolvedValue([original]);

    await useJournalStore.getState().updateEntry('e1', makeInput({ symbol: 'MSFT' }));

    const s = useJournalStore.getState();
    expect(s.entries[0].symbol).toBe('AAPL'); // rolled back / reconciled to the original
    expect(s.error).toBe('update failed: 422');
  });

  it('(a) a failed deleteEntry restores the entry, then sets error after syncEntries resolves', async () => {
    const original = makeEntry({ id: 'e1' });
    useJournalStore.setState({ entries: [original] });
    (api.deleteJournalEntry as jest.Mock).mockRejectedValue(new Error('delete failed: 500'));
    (api.getJournalEntries as jest.Mock).mockResolvedValue([original]);

    await useJournalStore.getState().deleteEntry('e1');

    const s = useJournalStore.getState();
    expect(s.entries.map((e) => e.id)).toEqual(['e1']);
    expect(s.error).toBe('delete failed: 500');
  });

  it('clearError resets the error field', () => {
    useJournalStore.setState({ error: 'boom' });
    useJournalStore.getState().clearError();
    expect(useJournalStore.getState().error).toBeNull();
  });

  it('a slower, earlier syncEntries() call does not clobber a faster, later one when it resolves last', async () => {
    // Simulates a mutation-recovery resync (call #1, slow) racing a
    // filter-bar change (call #2, fast) that fires and resolves before it.
    let resolveFirst!: (v: JournalEntry[]) => void;
    const firstCallPromise = new Promise<JournalEntry[]>((resolve) => { resolveFirst = resolve; });
    (api.getJournalEntries as jest.Mock)
      .mockImplementationOnce(() => firstCallPromise)
      .mockImplementationOnce(() => Promise.resolve([makeEntry({ id: 'fresh', symbol: 'MSFT' })]));

    const first = useJournalStore.getState().syncEntries({ status: 'open' });
    const second = useJournalStore.getState().syncEntries({ symbol: 'MSFT' });
    await second; // the newer, faster call resolves first
    expect(useJournalStore.getState().entries.map((e) => e.id)).toEqual(['fresh']);

    resolveFirst([makeEntry({ id: 'stale', symbol: 'AAPL' })]);
    await first; // the older, slower call resolves last — must NOT overwrite

    const s = useJournalStore.getState();
    expect(s.entries.map((e) => e.id)).toEqual(['fresh']);
    expect(s.lastFilters).toEqual({ symbol: 'MSFT' });
  });
});

describe('api.getJournalEntries — query string omission (d)', () => {
  const realFetch = global.fetch;

  afterEach(() => {
    global.fetch = realFetch;
  });

  it('omits empty/undefined filter values entirely, never as empty query params', async () => {
    jest.resetModules();
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    // Re-require the real (unmocked) api module for this describe block.
    const { api: realApi } = jest.requireActual('@/lib/api') as typeof import('@/lib/api');
    await realApi.getJournalEntries({ symbol: '', date_from: undefined, status: 'open' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain('status=open');
    expect(calledUrl).not.toContain('symbol=');
    expect(calledUrl).not.toContain('date_from=');
    expect(calledUrl).not.toContain('date_from');
  });

  it('produces no query string at all when every filter is absent', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => [] });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { api: realApi } = jest.requireActual('@/lib/api') as typeof import('@/lib/api');
    await realApi.getJournalEntries();

    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).not.toContain('?');
  });
});
