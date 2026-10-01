'use client';

// DOCC-5: the TopBar config-health chip (plan §2.5). It always renders one
// element so the TopBar columns do not shift. It never decides a tier itself:
// it reads useConfigHealthView(), the same path the banner reads.

import { useEffect, useRef, useState } from 'react';
import { useConfigHealthStore, useConfigHealthView } from '@/lib/configHealthStore';
import { CONFIG_HEALTH_BANNER_ID, TIER_SHORT_LABEL, TIER_TONE, hhmmss } from '@/lib/configHealth';
import styles from './ConfigHealthChip.module.css';

const TONE_CLASS = {
  reject: styles.reject, caution: styles.caution, pass: styles.pass, dim: styles.dim,
} as const;

export function ConfigHealthChip() {
  const v = useConfigHealthView();
  const setCollapsed = useConfigHealthStore((s) => s.setCollapsed);
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  const clean = v.tier === 'clean';
  useEffect(() => { if (!clean) setOpen(false); }, [clean]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);

  const tone = TONE_CLASS[TIER_TONE[v.tier]];

  if (v.tier === 'checking') {
    return (
      <div className={styles.wrap}>
        <span className={[styles.chip, tone].join(' ')} data-tier="checking">{TIER_SHORT_LABEL.checking}</span>
      </div>
    );
  }

  if (clean && v.report) {
    const r = v.report;
    return (
      <div className={styles.wrap} ref={wrap}>
        <button
          type="button"
          className={[styles.chip, styles.button, tone].join(' ')}
          data-tier="clean"
          aria-expanded={open}
          aria-controls="config-health-scope"
          onClick={() => setOpen((o) => !o)}
        >
          {TIER_SHORT_LABEL.clean} · {r.checked.length} {r.checked.length === 1 ? 'check' : 'checks'}
        </button>
        {open && (
          <div id="config-health-scope" className={styles.popover} role="region" aria-label="Config health scope">
            <p className={styles.heading}>Checked</p>
            <ul className={styles.list}>{r.checked.map((c) => <li key={c}>{c}</li>)}</ul>
            <p className={styles.heading}>Not checked</p>
            <ul className={styles.list}>{r.not_checked.map((c) => <li key={c}>{c}</li>)}</ul>
            {v.fetchedAt !== null && <p className={styles.foot}>Last checked {hhmmss(v.fetchedAt)}</p>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={[styles.chip, styles.button, tone].join(' ')}
        data-tier={v.tier}
        aria-controls={CONFIG_HEALTH_BANNER_ID}
        onClick={() => {
          setCollapsed(false, v.fingerprint);
          document.getElementById(CONFIG_HEALTH_BANNER_ID)?.focus();
        }}
      >
        {TIER_SHORT_LABEL[v.tier]}
      </button>
    </div>
  );
}
