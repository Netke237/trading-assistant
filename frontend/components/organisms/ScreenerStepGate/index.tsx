'use client';

/*
 * ScreenerStepGate — mode-gates the screener step pages.
 *
 * Every step page slug belongs to at least one mode's step list; a URL that
 * doesn't match the active mode (e.g. /screener/step-5-strategy while
 * Pre-Breakout is selected) is bounced to that mode's step 4, the canonical
 * landing page. Without this, StepNavBar renders a nonsensical "STEP 5 OF 4"
 * counter and the wrong page content under the wrong mode's navigation.
 *
 * Hydration: scanStore uses skipHydration, so screenerMode reads its default
 * until StoreHydration rehydrates — redirecting before then would bounce a
 * persisted-mode user to the wrong step 4. zustand 5's persist API has no
 * `subscribe`, so hydration is mirrored reactively into a module-scope vanilla
 * store via onHydrate/onFinishHydration listeners, registered once on the
 * client (typeof window guard). The optional chaining on useScanStore.persist
 * is belt-and-suspenders: the persist api object is attached in every
 * environment (createJSONStorage builds its wrapper even when the inner
 * storage getter yields undefined), but rehydrate/setItem would fail
 * server-side — only the client-side rehydrate path may ever touch them.
 *
 * Corrupt-storage / write-failure fallback: if persisted JSON is unparseable
 * OR a post-hydration localStorage write throws (e.g. QuotaExceededError),
 * zustand never fires onFinishHydration, so a grace timer sends an invalid
 * deep URL to the shared Step 1 route rather than rendering it under a
 * possibly wrong default mode. Step 1 is shared by all modes and is safe to
 * render with defaults.
 *
 * Known limitations (accepted):
 * - The mode toggle and StepNavBar live outside this gate (layout siblings),
 *   so they can briefly show the default mode before hydration. If hydration
 *   exceeds the grace timer, children render under the default mode for a
 *   moment before the post-hydration redirect.
 * - Server prerender of every step page is an empty shell (mode is
 *   client-only state); content appears after hydration. Fine for this
 *   single-user local tool.
 * - In dev, Fast Refresh re-runs this module, appending another idempotent
 *   listener pair per edit (cleared on reload). Harmless.
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { createStore } from 'zustand';
import type { StoreApi } from 'zustand';
import { useScanStore } from '@/lib/scanStore';
import { getSteps } from '@/components/organisms/Stepper';

const HYDRATION_GRACE_MS = 1500;
const SAFE_FALLBACK_STEP = 'step-1-regime';

let hydStore: StoreApi<boolean> | null = null;
let listenersRegistered = false;

function getHydStore() {
  if (!hydStore) {
    hydStore = createStore<boolean>(() => useScanStore.persist?.hasHydrated() ?? false);
  }
  return hydStore;
}

if (typeof window !== 'undefined') {
  const persist = useScanStore.persist;
  if (persist && !listenersRegistered) {
    listenersRegistered = true;
    // onHydrate fires at the START of every rehydrate (including failed ones,
    // which never reach onFinishHydration — see the corrupt-storage note above).
    persist.onHydrate(() => getHydStore().setState(persist.hasHydrated()));
    persist.onFinishHydration(() => getHydStore().setState(true));
  }
}

export function ScreenerStepGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const mode = useScanStore((s) => s.screenerMode);

  const hydrated = useSyncExternalStore(
    (onStoreChange) => getHydStore().subscribe(onStoreChange),
    () => getHydStore().getState(),
    () => false,
  );

  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    // Once hydrated, no grace timer is needed (and re-hydration re-arms it,
    // since onHydrate flips the hydStore back to false).
    if (hydrated) {
      setTimedOut(false);
      return;
    }
    setTimedOut(false);
    const t = setTimeout(() => setTimedOut(true), HYDRATION_GRACE_MS);
    return () => clearTimeout(t);
  }, [hydrated]);

  const segs = (pathname ?? '').split('/').filter(Boolean);
  const slug = segs[segs.length - 1] ?? '';
  const isStepRoute = /^step-\d+/.test(slug);
  const steps = getSteps(mode);
  const allowed = !isStepRoute || steps.some((s) => s.slug === slug);
  const hydrationFallback = timedOut && !hydrated;
  // Step 4 by index, not position — robust if the step arrays ever reorder.
  const landing = steps.find((s) => s.index === 4) ?? steps[steps.length - 1];

  useEffect(() => {
    if (hydrationFallback && isStepRoute && slug !== SAFE_FALLBACK_STEP) {
      router.replace(`/screener/${SAFE_FALLBACK_STEP}`);
      return;
    }
    if (hydrated && isStepRoute && !allowed) {
      router.replace(`/screener/${landing.slug}`);
    }
  }, [hydrated, hydrationFallback, isStepRoute, slug, allowed, landing, router]);

  const ready = hydrated || timedOut;
  if (!ready) return null;
  if (hydrationFallback && isStepRoute && slug !== SAFE_FALLBACK_STEP) return null;
  if (isStepRoute && !allowed) return null;
  return <>{children}</>;
}
