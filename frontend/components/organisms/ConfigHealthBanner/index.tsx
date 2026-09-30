'use client';

// DOCC-5: the frame-wide config-health banner (plan
// docs/superpowers/plans/2026-09-30-docc-5-topbar-banner-plan.md §2.4).
// Mounted once, directly after <TopBar />, and it OWNS the poll: immediately on
// mount, every 30 s while the tab is not hidden, and at once when the tab
// becomes visible or the window regains focus. It renders nothing for
// `checking` and `clean` -- the TopBar chip covers those.

import { useEffect, useRef } from 'react';
import { Text } from '@/components/primitives';
import { useConfigHealthStore, useConfigHealthView } from '@/lib/configHealthStore';
import {
  CONFIG_HEALTH_BANNER_ID, POLL_INTERVAL_MS, hhmmss, type ConfigHealthReport, type HealthTier,
} from '@/lib/configHealth';
import styles from './ConfigHealthBanner.module.css';

/** Focus and visibilitychange fire together; one poll is enough. */
const REFOCUS_GUARD_MS = 2_000;
const TICK_MS = 5_000;

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function capitalise(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function headline(tier: HealthTier, r: ConfigHealthReport | null, reason: string | null): string {
  if (tier === 'unknown') return `Config health unknown: ${reason ?? 'no report'}. Retrying every 30 s.`;
  if (!r) return '';
  if (tier === 'error') {
    const files = [...new Set(r.errors.map((e) => e.file).filter(Boolean))];
    const where = files.length ? ` in ${files.join(', ')}` : '';
    const first = r.errors[0].blocks;
    const blocks = first ? ` ${capitalise(first)} are refused until it is fixed.` : '';
    return `Config error: ${plural(r.errors.length, 'problem')}${where}.${blocks}`;
  }
  if (tier === 'stale') return 'Config changed on disk: restart the backend to apply it.';
  if (tier === 'multiworker') {
    return 'The backend answers from several worker processes; each has its own config, and this check sees one of them.';
  }
  if (tier === 'warning') return `Config warning: ${plural(r.warnings.length, 'unknown key')}.`;
  return '';
}

function alsoCounts(tier: HealthTier, r: ConfigHealthReport | null): string {
  if (!r) return '';
  const parts: string[] = [];
  if (tier === 'error' && r.stale.length) parts.push(`${r.stale.length} stale`);
  if ((tier === 'error' || tier === 'stale' || tier === 'multiworker') && r.warnings.length) {
    parts.push(plural(r.warnings.length, 'warning'));
  }
  return parts.length ? ` · also ${parts.join(', ')}` : '';
}

export function ConfigHealthBanner() {
  const v = useConfigHealthView();
  const poll = useConfigHealthStore((s) => s.poll);
  const tick = useConfigHealthStore((s) => s.tick);
  const setCollapsed = useConfigHealthStore((s) => s.setCollapsed);
  const lastStart = useRef(0);

  useEffect(() => {
    const pollNow = () => { lastStart.current = Date.now(); void poll(); };
    const visible = () => document.visibilityState !== 'hidden';
    // tick() BEFORE poll(): a tab back from a throttled or frozen period is
    // re-judged at once, not at the next (throttled) tick (round-1 G2).
    const onReturn = () => {
      if (!visible()) return;
      tick();
      if (Date.now() - lastStart.current >= REFOCUS_GUARD_MS) pollNow();
    };
    pollNow();
    const pollId = setInterval(() => { if (visible()) pollNow(); }, POLL_INTERVAL_MS);
    const tickId = setInterval(tick, TICK_MS);
    document.addEventListener('visibilitychange', onReturn);
    window.addEventListener('focus', onReturn);
    return () => {
      clearInterval(pollId);
      clearInterval(tickId);
      document.removeEventListener('visibilitychange', onReturn);
      window.removeEventListener('focus', onReturn);
    };
  }, [poll, tick]);

  const { tier, report: r } = v;
  if (tier === 'checking' || tier === 'clean') return null;

  const quiet = tier === 'warning';
  const expanded = !v.collapsed;
  const toneClass = tier === 'error' ? styles.reject : styles.caution;
  const size = quiet ? 11 : 12;

  return (
    <section
      id={CONFIG_HEALTH_BANNER_ID}
      tabIndex={-1}
      className={[styles.banner, toneClass, quiet ? styles.quiet : ''].join(' ')}
      role={tier === 'error' ? 'alert' : undefined}
      aria-live="polite"
      aria-label="Config health"
      data-tier={tier}
    >
      <div className={styles.head}>
        <Text size={size} tone={tier === 'error' ? 'reject' : 'caution'} weight={500}>
          {headline(tier, r, v.unknownReason)}{alsoCounts(tier, r)}
        </Text>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={expanded}
          aria-controls={`${CONFIG_HEALTH_BANNER_ID}-detail`}
          onClick={() => setCollapsed(expanded, v.fingerprint)}
        >
          {expanded ? 'Collapse' : 'Show details'}
        </button>
      </div>

      {expanded && (
        <div id={`${CONFIG_HEALTH_BANNER_ID}-detail`} className={styles.detail}>
          {r && r.errors.length > 0 && (
            <ul className={styles.list} aria-label="Errors">
              {r.errors.map((e, i) => (
                <li key={`e${i}`}>
                  <Text size={11} tone="primary">
                    {[e.file, e.path].filter(Boolean).join(' · ')}{e.file || e.path ? ': ' : ''}{e.message}
                  </Text>
                  {e.blocks && <Text size={11} tone="secondary"> Blocks: {e.blocks}</Text>}
                </li>
              ))}
            </ul>
          )}
          {r && r.stale.length > 0 && (
            <ul className={styles.list} aria-label="Stale">
              {r.stale.map((e, i) => (
                <li key={`s${i}`}>
                  <Text size={11} tone="primary">
                    {[e.file, e.path].filter(Boolean).join(' · ')}{e.file || e.path ? ': ' : ''}{e.message}
                  </Text>
                </li>
              ))}
            </ul>
          )}
          {r && r.warnings.length > 0 && (
            <ul className={styles.list} aria-label="Warnings">
              {r.warnings.map((e, i) => (
                <li key={`w${i}`}>
                  <Text size={11} tone="primary">
                    {[e.file, e.path].filter(Boolean).join(' · ')}{e.file || e.path ? ': ' : ''}{e.message}
                  </Text>
                </li>
              ))}
            </ul>
          )}
          {v.multiWorker && (
            <Text size={11} tone="caution" as="p">
              Backend answers from several worker processes; health is per process.
            </Text>
          )}
          {v.restartedAt !== null && (
            <Text size={11} tone="secondary" as="p">
              Backend restarted at {hhmmss(v.restartedAt)}. Pages opened before then keep the IV and
              event thresholds they loaded until they are reopened.
            </Text>
          )}
          <div className={styles.scope}>
            {r ? (
              <>
                <Text size={11} tone="secondary" as="p">
                  Checked: {r.checked.length ? r.checked.join('; ') : 'nothing, the health check itself failed'}
                </Text>
                <Text size={11} tone="secondary" as="p">Not checked: {r.not_checked.join('; ')}</Text>
              </>
            ) : (
              <Text size={11} tone="secondary" as="p">Nothing could be checked.</Text>
            )}
          </div>
          {v.fetchedAt !== null && (
            <Text size={11} tone="dim" as="p">Last checked {hhmmss(v.fetchedAt)}</Text>
          )}
        </div>
      )}
    </section>
  );
}
