/*
 * Theme store — Zustand with localStorage persistence.
 *
 * The actual <html data-theme="..."> sync lives in components/ThemeProvider/index.tsx
 * (client component). This file only owns the state.
 *
 * An inline no-flash script in app/layout.tsx reads the same localStorage key
 * before React hydrates, so users who saved "light" don't see a dark flash.
 * Keep THEME_STORAGE_KEY in sync with the inline script.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'bamendjou:theme';

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'dark',
      setTheme: (t) => set({ theme: t }),
      toggle: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
    }),
    {
      name: THEME_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
    }
  )
);
