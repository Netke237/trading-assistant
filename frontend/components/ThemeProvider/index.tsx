'use client';

/*
 * ThemeProvider — syncs the Zustand theme store to <html data-theme>.
 *
 * Server-rendered HTML starts with data-theme="dark" (set in app/layout.tsx).
 * An inline no-flash script in the same file may overwrite it to "light"
 * before hydration, based on localStorage. Once React hydrates, this effect
 * keeps the DOM attribute in lockstep with the store.
 */

import { useEffect } from 'react';
import { useThemeStore, THEME_STORAGE_KEY, syncThemeFromStorage } from '@/lib/theme';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY || event.key === null) {
        syncThemeFromStorage(event.newValue);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  return <>{children}</>;
}
