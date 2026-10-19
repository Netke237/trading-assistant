/*
 * Theme store — Zustand with localStorage persistence.
 *
 * The actual <html data-theme="..."> and <html data-density="..."> sync lives
 * in components/ThemeProvider/index.tsx (client component). This file only
 * owns the state.
 *
 * An inline no-flash script in app/layout.tsx reads the same localStorage key
 * before React hydrates, so users who saved "light" or "Compact" don't see a
 * flash. Keep THEME_STORAGE_KEY in sync with the inline script.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type Theme = 'dark' | 'light';
export type Density = 'Comfortable' | 'Compact';

export const THEME_STORAGE_KEY = 'bamendjou:theme';

export interface ThemeState {
  theme: Theme;
  density: Density;
  setTheme: (t: Theme) => void;
  setDensity: (d: Density) => void;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'dark',
      density: 'Comfortable',
      setTheme: (t) => set({ theme: t }),
      setDensity: (d) => set({ density: d }),
      toggle: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
    }),
    {
      name: THEME_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      version: 1,
      migrate: (persistedState: unknown, version: number) => {
        const state = (persistedState && typeof persistedState === 'object')
          ? (persistedState as Record<string, unknown>)
          : {};
        return {
          theme: state.theme === 'light' ? 'light' : 'dark',
          density: state.density === 'Compact' ? 'Compact' : 'Comfortable',
        };
      },
      skipHydration: true,
    }
  )
);
