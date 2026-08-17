import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SignalKind, StructureSignal } from '@/types/structure';

export interface StructureState {
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function migrateStructure(
  persistedState: unknown,
  _version: number,
): Partial<StructureState> {
  const prev = (persistedState as Partial<StructureState> | null) ?? {};
  const rawVisibility: Record<string, unknown> = isRecord(prev.visibility)
    ? prev.visibility
    : {};
  const { signals: _signals, ...withoutSignals } = prev;
  const visibility = { ...DEFAULT_VISIBILITY };
  for (const kind of Object.keys(DEFAULT_VISIBILITY) as SignalKind[]) {
    if (typeof rawVisibility[kind] === 'boolean') {
      visibility[kind] = rawVisibility[kind] as boolean;
    }
  }
  return {
    ...withoutSignals,
    visibility,
    structureVisible: typeof prev.structureVisible === 'boolean'
      ? prev.structureVisible
      : false,
  };
}

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
      version: 2,
      migrate: migrateStructure,
      // Don't persist `signals` — they're populated from WS on mount
      partialize: (state) => ({
        visibility: state.visibility,
        structureVisible: state.structureVisible,
      }),
    }
  )
);
