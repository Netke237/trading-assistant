'use client';

import { useEffect } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useStructureStore } from '@/lib/structureStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { useThemeStore } from '@/lib/theme';
import { useAutoTradeStore } from '@/lib/autoTradeStore';

export function StoreHydration() {
  useEffect(() => {
    useChartStore.persist.rehydrate();
    useChartAlertStore.persist.rehydrate();
    useScanStore.persist.rehydrate();
    useSettingsStore.persist.rehydrate();
    useStructureStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    useWatchedContractsStore.persist.rehydrate();
    useThemeStore.persist.rehydrate();
    useAutoTradeStore.persist.rehydrate();
  }, []);

  return null;
}
