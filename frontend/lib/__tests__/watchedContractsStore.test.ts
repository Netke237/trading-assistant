jest.mock('@/lib/api', () => ({
  api: {
    getWatchedContractsDetail: jest.fn(),
    getWatchedContracts:       jest.fn(),
  },
}));

import { api } from '@/lib/api';
import {
  migrateWatchedContracts, useWatchedContractsStore, WATCHED_CONTRACTS_STORAGE_KEY,
} from '@/lib/watchedContractsStore';
import type { ContractGrading } from '@/types/domain';

const mockApi = api as jest.Mocked<typeof api>;

const A = 'AAPL|190|2026-05-15|C';
const B = 'MSFT|400|2026-06-19|P';
const G: ContractGrading = { contract_rules: { min_volume: 20 }, hold_min_days: 20, hold_max_days: 25, stock_score: 72 };
const G2: ContractGrading = { ...G, stock_score: 55 };

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  useWatchedContractsStore.setState({ ids: [], grading: {} });
});

describe('watchedContractsStore — migrate', () => {
  it('v1 -> v3 keeps the ids and adds an empty grading map', () => {
    expect(migrateWatchedContracts({ ids: [A] }, 1)).toEqual({ ids: [A], grading: {} });
  });

  it('v2 -> v3 keeps the ids and adds an empty grading map', () => {
    expect(migrateWatchedContracts({ ids: [A, B] }, 2)).toEqual({ ids: [A, B], grading: {} });
  });

  it('v3 is kept as is', () => {
    expect(migrateWatchedContracts({ ids: [A], grading: { [A]: G } }, 3)).toEqual({ ids: [A], grading: { [A]: G } });
  });
});

describe('watchedContractsStore — add / remove / clearGrading', () => {
  it('add(id, g) stores g; remove drops it', () => {
    useWatchedContractsStore.getState().add(A, G);
    expect(useWatchedContractsStore.getState().ids).toEqual([A]);
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
    useWatchedContractsStore.getState().remove(A);
    expect(useWatchedContractsStore.getState().ids).toEqual([]);
    expect(useWatchedContractsStore.getState().grading).toEqual({});
  });

  it('add on an existing id updates its grading (a rollback restoring it)', () => {
    useWatchedContractsStore.getState().add(A, G);
    useWatchedContractsStore.getState().add(A, G2);
    expect(useWatchedContractsStore.getState().ids).toEqual([A]);
    expect(useWatchedContractsStore.getState().grading[A]).toEqual(G2);
  });

  it('add without grading keeps an existing grading', () => {
    useWatchedContractsStore.getState().add(A, G);
    useWatchedContractsStore.getState().add(A);
    expect(useWatchedContractsStore.getState().grading[A]).toEqual(G);
  });

  it('clearGrading drops only the grading', () => {
    useWatchedContractsStore.getState().add(A, G);
    useWatchedContractsStore.getState().clearGrading(A);
    expect(useWatchedContractsStore.getState().ids).toEqual([A]);
    expect(useWatchedContractsStore.getState().grading).toEqual({});
  });

  it('toggle no longer exists (it would be a grading-less star path)', () => {
    expect((useWatchedContractsStore.getState() as unknown as Record<string, unknown>).toggle).toBeUndefined();
  });
});

describe('watchedContractsStore — syncFromBackend', () => {
  it('replaces ids and grading from /detail (null grading -> no key)', async () => {
    useWatchedContractsStore.setState({ ids: ['OLD|1|2026-01-01|C'], grading: {} });
    mockApi.getWatchedContractsDetail.mockResolvedValue([
      { contract_id: A, grading: G },
      { contract_id: B, grading: null },
    ]);
    await useWatchedContractsStore.getState().syncFromBackend();
    expect(useWatchedContractsStore.getState().ids).toEqual([A, B]);
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
    expect(mockApi.getWatchedContracts).not.toHaveBeenCalled();
  });

  it('on a /detail failure, falls back to the ids and keeps the surviving local grading', async () => {
    useWatchedContractsStore.setState({ ids: [A, B], grading: { [A]: G, [B]: G2 } });
    mockApi.getWatchedContractsDetail.mockRejectedValue(new Error('API /api/watched-contracts/detail → 404: Not Found'));
    mockApi.getWatchedContracts.mockResolvedValue([A]);
    await useWatchedContractsStore.getState().syncFromBackend();
    expect(useWatchedContractsStore.getState().ids).toEqual([A]);
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
  });

  it('the fallback keeps grading rehydrated from v3 storage', async () => {
    localStorage.setItem(WATCHED_CONTRACTS_STORAGE_KEY, JSON.stringify({
      state: { ids: [A, B], grading: { [A]: G } }, version: 3,
    }));
    await useWatchedContractsStore.persist.rehydrate();
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
    mockApi.getWatchedContractsDetail.mockRejectedValue(new Error('down'));
    mockApi.getWatchedContracts.mockResolvedValue([A, B]);
    await useWatchedContractsStore.getState().syncFromBackend();
    expect(useWatchedContractsStore.getState().ids).toEqual([A, B]);
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
  });

  it('both endpoints failing keeps state', async () => {
    useWatchedContractsStore.setState({ ids: [A], grading: { [A]: G } });
    mockApi.getWatchedContractsDetail.mockRejectedValue(new Error('down'));
    mockApi.getWatchedContracts.mockRejectedValue(new Error('down'));
    await useWatchedContractsStore.getState().syncFromBackend();
    expect(useWatchedContractsStore.getState().ids).toEqual([A]);
    expect(useWatchedContractsStore.getState().grading).toEqual({ [A]: G });
  });

  it('a structurally identical sync does not set (no new references)', async () => {
    useWatchedContractsStore.setState({ ids: [A], grading: { [A]: G } });
    const before = useWatchedContractsStore.getState();
    const listener = jest.fn();
    const unsub = useWatchedContractsStore.subscribe(listener);
    mockApi.getWatchedContractsDetail.mockResolvedValue([{ contract_id: A, grading: { ...G } }]);
    await useWatchedContractsStore.getState().syncFromBackend();
    unsub();
    expect(listener).not.toHaveBeenCalled();
    expect(useWatchedContractsStore.getState().ids).toBe(before.ids);
    expect(useWatchedContractsStore.getState().grading).toBe(before.grading);
  });

  it('a changed grading alone does set', async () => {
    useWatchedContractsStore.setState({ ids: [A], grading: { [A]: G } });
    mockApi.getWatchedContractsDetail.mockResolvedValue([{ contract_id: A, grading: G2 }]);
    await useWatchedContractsStore.getState().syncFromBackend();
    expect(useWatchedContractsStore.getState().grading[A]).toEqual(G2);
  });
});
