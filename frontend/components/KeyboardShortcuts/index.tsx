'use client';

/*
 * Global keyboard shortcuts.
 *
 *   Inside /screener:
 *     1..7       → jump to step 1..7
 *     Left/Right → prev/next step (handled in StepNavBar already)
 *
 *   Anywhere:
 *     g then d   → /dashboard
 *     g then w   → /watchlist
 *     g then p   → /portfolio
 *     g then s   → /screener
 *     g then c   → /calendar
 *     ?          → open cheat sheet (Phase 7)
 *
 * All handlers ignore typing inside inputs / textareas / contenteditable.
 */

import { useEffect, useRef } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { SCREENER_STEPS } from '@/components/organisms/Stepper';

function isEditable(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable;
}

export function KeyboardShortcuts() {
  const router = useRouter();
  const pathname = usePathname();
  const gLeader = useRef<number>(0); // timestamp of last "g" press

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isEditable(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;

      // 1..7 inside screener
      if (pathname?.startsWith('/screener') && /^[1-7]$/.test(e.key)) {
        e.preventDefault();
        const idx = parseInt(e.key, 10) - 1;
        const step = SCREENER_STEPS[idx];
        if (step) router.push(`/screener/${step.slug}`);
        return;
      }

      // "g" leader
      if (e.key === 'g') {
        gLeader.current = Date.now();
        return;
      }

      const isLeaderActive = Date.now() - gLeader.current < 1200;
      if (isLeaderActive) {
        const jumps: Record<string, string> = {
          d: '/dashboard',
          w: '/watchlist',
          p: '/portfolio',
          s: '/screener',
          c: '/calendar',
          ',': '/settings',
        };
        const target = jumps[e.key];
        if (target) {
          e.preventDefault();
          gLeader.current = 0;
          router.push(target);
        }
      }
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [router, pathname]);

  return null;
}
