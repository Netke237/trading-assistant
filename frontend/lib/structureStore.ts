import { create } from 'zustand';
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
  FVG: true,
  BOS: true,
  CHoCH: true,
  OrderBlock: true,
  Divergence: true,
  Fibonacci: true,
  Confluence: true,
};

export const useStructureStore = create<StructureState>((set) => ({
  signals: {},
  visibility: { ...DEFAULT_VISIBILITY },
  structureVisible: true,

  setSignals: (key, signals) =>
    set((state) => ({
      signals: { ...state.signals, [key]: signals },
    })),

  toggleKind: (kind) =>
    set((state) => ({
      visibility: { ...state.visibility, [kind]: !state.visibility[kind] },
    })),

  toggleStructure: () =>
    set((state) => ({
      structureVisible: !state.structureVisible,
    })),

  clearSignals: (key) =>
    set((state) => {
      const next = { ...state.signals };
      delete next[key];
      return { signals: next };
    }),
}));
