'use client';
import { useEffect } from 'react';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';

export function IvThresholdsBootstrap() {
  const fetch = useIvThresholdsStore((s) => s.fetch);
  useEffect(() => { fetch(); }, [fetch]);
  return null;
}
