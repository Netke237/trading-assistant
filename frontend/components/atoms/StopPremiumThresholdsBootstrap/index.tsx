'use client';
import { useEffect } from 'react';
import { useStopPremiumThresholdsStore } from '@/lib/stopPremiumThresholdsStore';

export function StopPremiumThresholdsBootstrap() {
  const fetch = useStopPremiumThresholdsStore((s) => s.fetch);
  useEffect(() => { fetch(); }, [fetch]);
  return null;
}
