// DOCC-5: poll state for the config-health banner and the TopBar chip.
//
// NO persist(): a health verdict from an earlier page load is exactly the stale
// green this slice exists to prevent, and collapse must not survive a reload
// (decision DOCC-5-BANNER-DESIGN-2026-09-30, answer 3).
//
// `poll()` is driven by ConfigHealthBanner (mounted once in the frame layout);
// the chip only reads. Both go through `useConfigHealthView()`, so they cannot
// disagree about the tier. `seq` makes only the latest poll write, as in
// DOCC-3's threshold stores.
import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { api } from '@/lib/api';
import { messageOf } from '@/lib/eventThresholdsStore';
import {
  parseConfigHealth, tierOf, fingerprintOf, unknownReason, FETCH_TIMEOUT_MS,
  type ConfigHealthReport, type HealthStatus, type HealthTier, type HealthView,
} from '@/lib/configHealth';

/** Successful polls remembered for the multi-worker rule (5 minutes at 30 s). */
export const PID_WINDOW = 10;

export interface ConfigHealthState {
  status: HealthStatus;
  report: ConfigHealthReport | null;
  error: string | null;
  fetchedAt: number | null;
  /** pid of each successful poll, newest last, at most PID_WINDOW. */
  pids: number[];
  multiWorker: boolean;
  /** The last time the pid changed and did not come back. */
  restartedAt: number | null;
  collapsed: boolean;
  collapsedFingerprint: string | null;
  /** Date.now() at creation; advanced only by tick() and a successful poll. */
  now: number;
  tick: () => void;
  poll: () => Promise<void>;
  setCollapsed: (collapsed: boolean, fingerprint: string) => void;
}

/** True when some pid comes back after a different one (A, B, A). A restart
 *  gives A, A, B, B: the old pid never returns. */
export function sawPidReturn(pids: readonly number[]): boolean {
  const seen = new Set<number>();
  for (let i = 0; i < pids.length; i++) {
    if (i > 0 && pids[i] !== pids[i - 1] && seen.has(pids[i])) return true;
    seen.add(pids[i]);
  }
  return false;
}

let seq = 0;

export const useConfigHealthStore = create<ConfigHealthState>((set, get) => ({
  status: 'idle',
  report: null,
  error: null,
  fetchedAt: null,
  pids: [],
  multiWorker: false,
  restartedAt: null,
  collapsed: false,
  collapsedFingerprint: null,
  now: Date.now(),
  tick: () => set({ now: Date.now() }),
  poll: async () => {
    const my = ++seq;
    // The report in hand is kept while loading, and so is `error`: clearing it
    // would turn a retry after a failure into `checking` (round-1 G1).
    set({ status: 'loading' });
    const ctrl = new AbortController();
    const timer = setTimeout(
      () => ctrl.abort(new Error(`no answer within ${FETCH_TIMEOUT_MS / 1000} s`)),
      FETCH_TIMEOUT_MS,
    );
    try {
      const raw = await api.getConfigHealth(ctrl.signal);
      if (my !== seq) return;
      const report = parseConfigHealth(raw);
      const at = Date.now();
      const prev = get().pids;
      const pids = [...prev, report.pid].slice(-PID_WINDOW);
      const multiWorker = sawPidReturn(pids);
      const changed = prev.length > 0 && prev[prev.length - 1] !== report.pid;
      // Collapse lasts "until the config is clean" (decision 3): a clean
      // landing resets it, so the same finding coming back shows expanded.
      const reset = report.ok && !multiWorker ? { collapsed: false, collapsedFingerprint: null } : {};
      set({
        ...reset,
        report, status: 'ready', error: null, fetchedAt: at, now: at, pids, multiWorker,
        restartedAt: changed && !multiWorker ? at : multiWorker ? null : get().restartedAt,
      });
    } catch (e) {
      if (my !== seq) return;
      const reason = ctrl.signal.aborted && ctrl.signal.reason instanceof Error
        ? ctrl.signal.reason.message : messageOf(e);
      set({ report: null, status: 'failed', error: reason, fetchedAt: null });
    } finally {
      clearTimeout(timer);
    }
  },
  setCollapsed: (collapsed, fingerprint) =>
    set({ collapsed, collapsedFingerprint: collapsed ? fingerprint : null }),
}));

export interface ConfigHealthViewModel extends HealthView {
  tier: HealthTier;
  fingerprint: string;
  /** Collapsed only while the findings are the ones the user collapsed. */
  collapsed: boolean;
  unknownReason: string | null;
  restartedAt: number | null;
}

/** The one read path for the banner and the chip. It passes the store's `now`
 *  to tierOf; nothing here calls Date.now(). */
export function useConfigHealthView(): ConfigHealthViewModel {
  const s = useConfigHealthStore(useShallow((st) => ({
    status: st.status, report: st.report, error: st.error, fetchedAt: st.fetchedAt,
    multiWorker: st.multiWorker, now: st.now, restartedAt: st.restartedAt,
    collapsedFlag: st.collapsed, collapsedFingerprint: st.collapsedFingerprint,
  })));
  const view: HealthView = {
    status: s.status, report: s.report, error: s.error, fetchedAt: s.fetchedAt,
    multiWorker: s.multiWorker, now: s.now,
  };
  const fingerprint = fingerprintOf(view);
  return {
    ...view,
    tier: tierOf(view),
    fingerprint,
    collapsed: s.collapsedFlag && s.collapsedFingerprint === fingerprint,
    unknownReason: unknownReason(view),
    restartedAt: s.restartedAt,
  };
}
