import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SignalKind, StructureSignal } from '@/types/structure';

interface StructureState {
  signals: Record<string, StructureSignal[]>;
  visibility: Record<SignalKind, boolean>;
  structureVisible: boolean;

  setSignals: (key: string, signals: StructureSignal[]) => void;
  toggleKind: (kind: SignalKind) => void;
  toggleStructure: () => void;
  clearSignals: (key: string) => void;
}

const DEFAULT_VISIBILITY: Record<SignalKind, boolean> = {
  FVG:        false,   // all OFF by default (user turns on what they want)
  BOS:        false,
  CHoCH:      false,
  OrderBlock: false,
  Divergence: false,
  Fibonacci:  false,
  Confluence: false,
};

export const useStructureStore = create<StructureState>()(
  persist(
    (set) => ({
      signals: {},
      visibility: { ...DEFAULT_VISIBILITY },
      structureVisible: false,

      setSignals: (key, signals) =>
        set((state) => ({ signals: { ...state.signals, [key]: signals } })),

      toggleKind: (kind) =>
        set((state) => ({
          visibility: { ...state.visibility, [kind]: !state.visibility[kind] },
        })),

      toggleStructure: () =>
        set((state) => ({ structureVisible: !state.structureVisible })),

      clearSignals: (key) =>
        set((state) => {
          const next = { ...state.signals };
          delete next[key];
          return { signals: next };
        }),
    }),
    {
      name: 'bamendjou:structure',
      storage: createJSONStorage(() =>
        typeof window === 'undefined'
          ? { getItem: () => null, setItem: () => {}, removeItem: () => {} }
          : localStorage
      ),
      skipHydration: true,
      // Don't persist `signals` — they're populated from WS on mount
      partialize: (state) => ({
        visibility: state.visibility,
        structureVisible: state.structureVisible,
      }),
    }
  )
);
