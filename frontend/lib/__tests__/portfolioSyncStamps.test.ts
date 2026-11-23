import { usePortfolioStore } from '../portfolioStore';

const jsonRes = (body: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => body }) as unknown as Response;

const RESET: Partial<ReturnType<typeof usePortfolioStore.getState>> = { positions: [], lastSyncAt: null, lastSyncFailedAt: null, firstSyncAt: null };

describe('portfolio sync stamps', () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    localStorage.clear();
    usePortfolioStore.setState({ ...RESET });
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('starts with all three stamps null', () => {
    const s = usePortfolioStore.getState();
    expect(s.lastSyncAt).toBeNull();
    expect(s.lastSyncFailedAt).toBeNull();
    expect(s.firstSyncAt).toBeNull();
  });

  it('a successful sync stamps lastSyncAt and firstSyncAt once', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes([])) as unknown as typeof fetch;
    const now = jest.spyOn(Date, 'now');
    now.mockReturnValue(1_000);
    expect(await usePortfolioStore.getState().syncFromBackend(true)).toBe(true);
    let s = usePortfolioStore.getState();
    expect(s.lastSyncAt).toBe(1_000);
    expect(s.firstSyncAt).toBe(1_000);
    expect(s.lastSyncFailedAt).toBeNull();
    now.mockReturnValue(5_000);
    await usePortfolioStore.getState().syncFromBackend(true);
    s = usePortfolioStore.getState();
    expect(s.lastSyncAt).toBe(5_000);
    expect(s.firstSyncAt).toBe(1_000);
  });

  it('!res.ok stamps lastSyncFailedAt and leaves lastSyncAt', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(jsonRes([]))
      .mockResolvedValueOnce(jsonRes({}, false, 500)) as unknown as typeof fetch;
    const now = jest.spyOn(Date, 'now');
    now.mockReturnValue(1_000);
    await usePortfolioStore.getState().syncFromBackend(true);
    now.mockReturnValue(2_000);
    expect(await usePortfolioStore.getState().syncFromBackend(true)).toBe(false);
    const s = usePortfolioStore.getState();
    expect(s.lastSyncAt).toBe(1_000);
    expect(s.lastSyncFailedAt).toBe(2_000);
    expect(s.firstSyncAt).toBe(1_000);
  });

  it('a thrown fetch stamps lastSyncFailedAt and never firstSyncAt', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    jest.spyOn(Date, 'now').mockReturnValue(3_000);
    expect(await usePortfolioStore.getState().syncFromBackend(true)).toBe(false);
    const s = usePortfolioStore.getState();
    expect(s.lastSyncAt).toBeNull();
    expect(s.firstSyncAt).toBeNull();
    expect(s.lastSyncFailedAt).toBe(3_000);
  });

  it('bad JSON counts as a failure', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => { throw new Error('bad json'); },
    }) as unknown as typeof fetch;
    expect(await usePortfolioStore.getState().syncFromBackend(true)).toBe(false);
    expect(usePortfolioStore.getState().lastSyncAt).toBeNull();
    expect(usePortfolioStore.getState().lastSyncFailedAt).not.toBeNull();
  });

  it('the persisted blob holds exactly the positions key and no version bump', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes([])) as unknown as typeof fetch;
    await usePortfolioStore.getState().syncFromBackend(true);
    const raw = JSON.parse(localStorage.getItem('bamendjou-portfolio-v1') ?? '{}');
    expect(Object.keys(raw.state)).toEqual(['positions']);
    expect(raw.version).toBe(8);
  });
});
