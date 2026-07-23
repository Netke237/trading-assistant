'use client';
import { useEffect } from 'react';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';

export function EventThresholdsBootstrap() {
  const fetch = useEventThresholdsStore((s) => s.fetch);
  useEffect(() => { fetch(); }, [fetch]);
  return null;
}
