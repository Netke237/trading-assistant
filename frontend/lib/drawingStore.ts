import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Drawing } from '@/types/overlays';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function pushDrawingToAPI(drawing: Drawing): Promise<void> {
  try {
    await fetch(`${BASE_URL}/chart/drawings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(drawing),
    });
  } catch { /* fire-and-forget */ }
}

async function deleteDrawingFromAPI(id: string): Promise<void> {
  try {
    await fetch(`${BASE_URL}/chart/drawings/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } catch { /* fire-and-forget */ }
}

interface DrawingStoreState {
  drawings: Drawing[];
  addDrawing: (d: Drawing) => void;
  removeDrawing: (id: string) => void;
  clearForSymbol: (symbol: string, interval: string) => void;
  updateDrawing: (id: string, patch: Partial<Drawing>) => void;
  syncFromBackend: (symbol: string, interval: string) => Promise<void>;
}

export const useDrawingStore = create<DrawingStoreState>()(
  persist(
    (set, get) => ({
      drawings: [],

      addDrawing: (d) => {
        set((s) => ({ drawings: [...s.drawings, d] }));
        pushDrawingToAPI(d);
      },

      removeDrawing: (id) => {
        set((s) => ({ drawings: s.drawings.filter((d) => d.id !== id) }));
        deleteDrawingFromAPI(id);
      },

      clearForSymbol: (symbol, interval) => {
        const toDelete = get().drawings.filter(
          (d) => d.symbol === symbol && d.interval === interval,
        );
        set((s) => ({
          drawings: s.drawings.filter(
            (d) => !(d.symbol === symbol && d.interval === interval),
          ),
        }));
        toDelete.forEach((d) => deleteDrawingFromAPI(d.id));
      },

      updateDrawing: (id, patch) => {
        set((s) => ({
          drawings: s.drawings.map((d) => (d.id === id ? { ...d, ...patch } : d)),
        }));
        const d = get().drawings.find((x) => x.id === id);
        if (d) pushDrawingToAPI(d);
      },

      syncFromBackend: async (symbol, interval) => {
        try {
          const res = await fetch(
            `${BASE_URL}/chart/drawings?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`,
          );
          if (!res.ok) return;
          const serverDrawings: Drawing[] = await res.json();
          const localDrawings = get().drawings;

          // Replace all drawings for this symbol+interval with the server set,
          // preserving drawings for other symbols/intervals.
          const otherDrawings = localDrawings.filter(
            (d) => !(d.symbol === symbol && d.interval === interval),
          );
          const serverIds = new Set(serverDrawings.map((d) => d.id));
          const localOnly = localDrawings.filter(
            (d) => d.symbol === symbol && d.interval === interval && !serverIds.has(d.id),
          );

          set({ drawings: [...otherDrawings, ...serverDrawings, ...localOnly] });
        } catch { /* fire-and-forget */ }
      },
    }),
    {
      name: 'bamendjou:drawings',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (state) => ({ drawings: state.drawings }),
      version: 1,
      migrate: (persistedState: unknown, _version: number) => {
        const prev = (persistedState as Partial<DrawingStoreState> | null) ?? {};
        return prev as DrawingStoreState;
      },
    },
  ),
);
