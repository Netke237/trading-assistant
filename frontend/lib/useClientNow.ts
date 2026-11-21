// frontend/lib/useClientNow.ts
// A clock that is `null` on the server pass and on the first client render, so
// nothing clock- or locale-derived is rendered into server HTML (hydration).
import { useCallback, useEffect, useState } from 'react';

export function useClientClock(): { now: Date | null; refreshNow: () => void } {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => { setNow(new Date()); }, []);
  const refreshNow = useCallback(() => setNow(new Date()), []);
  return { now, refreshNow };
}

export function useClientNow(): Date | null {
  return useClientClock().now;
}
