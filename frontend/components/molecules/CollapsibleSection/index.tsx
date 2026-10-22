'use client';

/*
 * CollapsibleSection — generic collapse/expand wrapper for a group of cards.
 * Collapsed state persists per browser under a caller-supplied colon-form
 * localStorage key (see frontend/CLAUDE.md's Zustand-persistence section for
 * the colon-vs-hyphen key convention this repo uses going forward).
 *
 * SSR-safe: the FIRST render (server and client, pre-hydration) always uses
 * `defaultCollapsed` — reading localStorage happens in an effect, after
 * mount, so there is no server/client markup mismatch. This means a returning
 * visitor whose stored state differs from the default sees one brief
 * collapsed/expanded flash on load, which is an acceptable trade for
 * hydration safety.
 */

import { useEffect, useState } from 'react';
import { Text } from '@/components/primitives';
import styles from './CollapsibleSection.module.css';

interface CollapsibleSectionProps {
  title: string;
  /** Colon-form localStorage key, e.g. 'bamendjou:tradecard-ladder-collapsed'. */
  storageKey: string;
  defaultCollapsed?: boolean;
  /** Keep child state alive in hidden DOM while collapsed; legacy callers unmount. */
  keepMounted?: boolean;
  className?: string;
  children: React.ReactNode;
}

export function CollapsibleSection({
  title,
  storageKey,
  defaultCollapsed = false,
  keepMounted = false,
  className,
  children,
}: CollapsibleSectionProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  // Guards the persistence effect below from firing on the very first render
  // (before the restore effect has had a chance to read localStorage) — without
  // it, mounting with defaultCollapsed would immediately re-write that default
  // over whatever was actually stored, on every mount, defeating persistence.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored != null) setCollapsed(stored === '1');
    } catch {
      // localStorage unavailable (private mode, disabled) — fall back to
      // defaultCollapsed for this session, same as a first-ever visit.
    }
    setHydrated(true);
    // Only re-run if the caller swaps to a genuinely different storage key —
    // not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      window.localStorage.setItem(storageKey, collapsed ? '1' : '0');
    } catch {
      // localStorage unavailable — collapsed state just won't persist this session.
    }
  }, [collapsed, hydrated, storageKey]);

  return (
    <section className={`${styles.wrap} ${className ?? ''}`}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
      >
        <Text size={14} weight={600}>{title}</Text>
        <Text size={12} tone="dim">{collapsed ? '▸' : '▾'}</Text>
      </button>
      {keepMounted
        ? <div hidden={collapsed}><div className={styles.body}>{children}</div></div>
        : !collapsed && <div className={styles.body}>{children}</div>}
    </section>
  );
}
