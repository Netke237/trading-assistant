import { create } from 'zustand';
import { api } from '@/lib/api';

export type ContractRulesStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface ContractRulesState {
  minStockScore: number | null;
  status: ContractRulesStatus;
  error: string | null;
  fetch: () => Promise<void>;
  reset: () => void;
}

export const useContractRulesStore = create<ContractRulesState>((set, get) => ({
  minStockScore: null,
  status: 'idle',
  error: null,
  fetch: async () => {
    if (get().status === 'loading') return;
    set({ status: 'loading', error: null });
    try {
      const res = await api.getContractRules();
      if (res && typeof res.min_stock_score === 'number' && Number.isFinite(res.min_stock_score)) {
        set({ minStockScore: res.min_stock_score, status: 'ready', error: null });
      } else {
        set({ minStockScore: null, status: 'failed', error: 'Malformed contract rules payload' });
      }
    } catch (err) {
      set({ minStockScore: null, status: 'failed', error: err instanceof Error ? err.message : String(err) });
    }
  },
  reset: () => {
    set({ minStockScore: null, status: 'idle', error: null });
  },
}));
