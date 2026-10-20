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

/**
 * Safely parse a raw JSON string from storage into a validated Theme.
 * Returns null if the string is empty, invalid JSON, or contains an unsupported theme value.
 */
export function parseTheme(raw: string | null | undefined): Theme | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    const t = parsed?.state?.theme;
    if (t === 'light' || t === 'dark') return t;
  } catch {
    // Malformed JSON or unreadable format
  }
  return null;
}

/**
 * Synchronize the in-memory theme store from localStorage or an incoming cross-tab storage payload.
 * If raw is null (storage cleared or key deleted), resets to default 'dark'.
 * If raw is corrupted JSON, leaves current state untouched.
 * If parsed theme differs from current state, updates useThemeStore.
 */
export function syncThemeFromStorage(raw?: string | null): void {
  if (typeof window === 'undefined') return;
  const value = raw !== undefined ? raw : localStorage.getItem(THEME_STORAGE_KEY);
  if (value === null) {
    if (useThemeStore.getState().theme !== 'dark') {
      useThemeStore.setState({ theme: 'dark' });
    }
    return;
  }
  const parsed = parseTheme(value);
  if (parsed && useThemeStore.getState().theme !== parsed) {
    useThemeStore.setState({ theme: parsed });
  }
}

