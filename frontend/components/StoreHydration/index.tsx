'use client';

import { useEffect } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { useThemeStore } from '@/lib/theme';

export function StoreHydration() {
  useEffect(() => {
    useChartStore.persist.rehydrate();
    useChartAlertStore.persist.rehydrate();
    useScanStore.persist.rehydrate();
    useSettingsStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    useWatchedContractsStore.persist.rehydrate();
    useThemeStore.persist.rehydrate();
  }, []);

  return null;
}
