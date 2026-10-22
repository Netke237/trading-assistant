import { useContractRulesStore } from '@/lib/contractRulesStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getContractRules: jest.fn(),
  },
}));

const getMock = api.getContractRules as jest.Mock;

describe('contractRulesStore', () => {
  beforeEach(() => {
    getMock.mockReset();
    useContractRulesStore.getState().reset();
  });

  it('sets ready and minStockScore on successful fetch', async () => {
    getMock.mockResolvedValue({ min_stock_score: 45 });
    await useContractRulesStore.getState().fetch();

    const state = useContractRulesStore.getState();
    expect(state.status).toBe('ready');
    expect(state.minStockScore).toBe(45);
    expect(state.error).toBeNull();
  });

  it('sets failed and null minStockScore on network error', async () => {
    getMock.mockRejectedValue(new Error('Network error'));
    await useContractRulesStore.getState().fetch();

    const state = useContractRulesStore.getState();
    expect(state.status).toBe('failed');
    expect(state.minStockScore).toBeNull();
    expect(state.error).toContain('Network error');
  });

  it('sets failed on malformed payload', async () => {
    getMock.mockResolvedValue({ min_stock_score: 'not-a-number' });
    await useContractRulesStore.getState().fetch();

    const state = useContractRulesStore.getState();
    expect(state.status).toBe('failed');
    expect(state.minStockScore).toBeNull();
    expect(state.error).toBe('Malformed contract rules payload');
  });

  it('resets state cleanly', async () => {
    getMock.mockResolvedValue({ min_stock_score: 45 });
    await useContractRulesStore.getState().fetch();
    expect(useContractRulesStore.getState().status).toBe('ready');

    useContractRulesStore.getState().reset();
    const state = useContractRulesStore.getState();
    expect(state.status).toBe('idle');
    expect(state.minStockScore).toBeNull();
    expect(state.error).toBeNull();
  });

  it('does not re-enter if status is loading', async () => {
    let resolvePromise!: (v: unknown) => void;
    getMock.mockReturnValue(new Promise((res) => { resolvePromise = res; }));

    const p1 = useContractRulesStore.getState().fetch();
    expect(useContractRulesStore.getState().status).toBe('loading');

    // Second fetch call while loading
    const p2 = useContractRulesStore.getState().fetch();
    expect(getMock).toHaveBeenCalledTimes(1);

    resolvePromise({ min_stock_score: 45 });
    await Promise.all([p1, p2]);
    expect(useContractRulesStore.getState().status).toBe('ready');
  });
});
