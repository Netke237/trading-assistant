/**
 * PORTFOLIO-ALERT-ACTION T5 — in-app toasts follow the episode logic.
 * Plan: docs/superpowers/plans/2026-11-27-portfolio-alert-action-plan.md §5.
 */
import { useAlertStore, DEFAULT_CONFIG, migrateAlerts } from '@/lib/alertStore';
import { EPISODE_GAP_HOURS, REMINDER_PERIOD_HOURS } from '@/lib/alertEpisodes';
import type { ToastItem } from '@/types/domain';

const H = 3_600_000;
const T0 = Date.UTC(2026, 10, 2, 14, 0, 0); // 2026-11-02T14:00:00Z
const KEY = 'REC-1-STOP_REACHED';

const stop = {
  kind: 'Critical' as const, symbol: 'AAPL', reason: 'Stop breached',
  recId: 'REC-1', alertType: 'STOP_REACHED' as const,
};

// Count chimes: playBeep() creates one oscillator per beep. The module caches
// its AudioContext, so the fake is installed once for the whole file.
let beeps = 0;
class FakeAudioContext {
  state = 'running';
  currentTime = 0;
  destination = {};
  createOscillator() {
    beeps += 1;
    return { connect: () => {}, frequency: { value: 0 }, start: () => {}, stop: () => {} };
  }
  resume() { return Promise.resolve(); }
}

let nowMs = T0;
let fetchMock: jest.Mock;

function at(ms: number) { nowMs = ms; }
function add(item: Parameters<ReturnType<typeof useAlertStore.getState>['addToast']>[0] = stop) {
  useAlertStore.getState().addToast(item);
}
function rows(): ToastItem[] { return useAlertStore.getState().toasts; }

beforeAll(() => {
  (window as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
});

beforeEach(() => {
  beeps = 0;
  nowMs = T0;
  jest.spyOn(Date, 'now').mockImplementation(() => nowMs);
  fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) });
  (global as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  localStorage.clear();
  useAlertStore.setState({
    toasts: [], config: { ...DEFAULT_CONFIG, soundEnabled: true },
    firedAlerts: {}, suppressedAlerts: {}, episodes: {},
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('alertStore episodes — constants come from alertEpisodes.ts', () => {
  it('uses the shared 72 h gap and 24 h reminder period', () => {
    expect(EPISODE_GAP_HOURS).toBe(72);
    expect(REMINDER_PERIOD_HOURS).toBe(24);
  });
});

describe('alertStore episodes — first fire', () => {
  it('records an episode, adds a row and chimes', () => {
    add();
    expect(rows()).toHaveLength(1);
    expect(rows()[0]!.firedAt).toBe(new Date(T0).toISOString());
    expect(useAlertStore.getState().episodes[KEY]).toEqual({
      startedAt: new Date(T0).toISOString(), lastSeenAt: T0, lastSurfacedAt: T0,
    });
    expect(beeps).toBe(1);
  });
});

describe('alertStore episodes — new episode after the gap', () => {
  it('re-toasts an acknowledged condition when it returns after > 72 h', () => {
    add();
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    beeps = 0;
    at(T0 + (EPISODE_GAP_HOURS + 1) * H);
    add();
    const active = rows().filter((t) => !t.acknowledged);
    expect(active).toHaveLength(1);
    expect(active[0]!.firedAt).toBe(new Date(nowMs).toISOString());
    expect(active[0]!.dismissed).toBe(false);
    expect(useAlertStore.getState().suppressedAlerts[KEY]).toBeUndefined();
    expect(useAlertStore.getState().episodes[KEY]!.startedAt).toBe(new Date(nowMs).toISOString());
    expect(beeps).toBe(1);
  });

  it('refreshes an un-acknowledged row in place with firedAt = now and un-dismisses it', () => {
    add();
    useAlertStore.getState().dismissToast(rows()[0]!.id);
    beeps = 0;
    at(T0 + (EPISODE_GAP_HOURS + 1) * H);
    add({ ...stop, reason: 'Stop breached again' });
    expect(rows()).toHaveLength(1);
    expect(rows()[0]!.firedAt).toBe(new Date(nowMs).toISOString());
    expect(rows()[0]!.dismissed).toBe(false);
    expect(rows()[0]!.reason).toBe('Stop breached again');
    expect(beeps).toBe(1);
  });

  it('a gap of exactly 72 h is still the same episode', () => {
    add();
    at(T0 + EPISODE_GAP_HOURS * H);
    add();
    expect(useAlertStore.getState().episodes[KEY]!.startedAt).toBe(new Date(T0).toISOString());
  });
});

describe('alertStore episodes — daily reminder', () => {
  it('an acknowledged condition re-surfaces once after 24 h and not before', () => {
    add();
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    beeps = 0;
    // Still true every hour: suppressed until the 24 h mark.
    for (let h = 1; h < REMINDER_PERIOD_HOURS; h += 1) {
      at(T0 + h * H);
      add();
    }
    expect(rows().filter((t) => !t.acknowledged)).toHaveLength(0);
    expect(beeps).toBe(0);
    // lastSeenAt kept moving while suppressed.
    expect(useAlertStore.getState().episodes[KEY]!.lastSeenAt).toBe(T0 + 23 * H);

    at(T0 + REMINDER_PERIOD_HOURS * H);
    add();
    const active = rows().filter((t) => !t.acknowledged);
    expect(active).toHaveLength(1);
    // A new row carries the ORIGINAL trigger time.
    expect(active[0]!.firedAt).toBe(new Date(T0).toISOString());
    expect(useAlertStore.getState().suppressedAlerts[KEY]).toBeUndefined();
    expect(useAlertStore.getState().episodes[KEY]!.lastSurfacedAt).toBe(nowMs);
    expect(beeps).toBe(1);

    // Further ticks the same day refresh in place: no second reminder.
    at(T0 + (REMINDER_PERIOD_HOURS + 1) * H);
    add();
    expect(rows().filter((t) => !t.acknowledged)).toHaveLength(1);
    expect(beeps).toBe(1);
  });

  it('un-dismisses an un-acknowledged row on the reminder, keeping its firedAt', () => {
    add();
    useAlertStore.getState().dismissToast(rows()[0]!.id);
    beeps = 0;
    at(T0 + 12 * H);
    add();
    expect(rows()[0]!.dismissed).toBe(true);           // not due yet
    expect(beeps).toBe(0);
    at(T0 + REMINDER_PERIOD_HOURS * H);
    add();
    expect(rows()).toHaveLength(1);
    expect(rows()[0]!.dismissed).toBe(false);
    expect(rows()[0]!.firedAt).toBe(new Date(T0).toISOString());
    expect(beeps).toBe(1);
  });

  it('no chime when sound is off', () => {
    useAlertStore.setState({ config: { ...DEFAULT_CONFIG, soundEnabled: false } });
    add();
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    at(T0 + REMINDER_PERIOD_HOURS * H);
    add();
    expect(rows().filter((t) => !t.acknowledged)).toHaveLength(1);
    expect(beeps).toBe(0);
  });
});

describe('alertStore episodes — notify POST cadence unchanged', () => {
  it('POSTs follow the dedupWindowMinutes throttle only, reminder or not', () => {
    // Un-acknowledged condition re-checked every 5 min for 25 h.
    const step = 5 * 60_000;
    let expected = 0;
    let lastSent: number | null = null;
    const throttle = DEFAULT_CONFIG.dedupWindowMinutes * 60_000;
    for (let t = T0; t <= T0 + 25 * H; t += step) {
      at(t);
      add();
      if (lastSent == null || t - lastSent >= throttle) { expected += 1; lastSent = t; }
    }
    expect(fetchMock).toHaveBeenCalledTimes(expected);
  });

  it('an acknowledged (suppressed) condition does not POST before its reminder', () => {
    add();
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    fetchMock.mockClear();
    for (let h = 1; h < REMINDER_PERIOD_HOURS; h += 1) {
      at(T0 + h * H);
      add();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('alertStore episodes — scan lifecycle types unaffected', () => {
  it('SCAN_COMPLETE gets no episode and an acknowledged one stays suppressed', () => {
    const scan = { kind: 'Info' as const, symbol: '—', reason: 'Scan done', recId: 'SCAN', alertType: 'SCAN_COMPLETE' as const };
    add(scan);
    expect(useAlertStore.getState().episodes).toEqual({});
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    at(T0 + (EPISODE_GAP_HOURS + 1) * H);
    add(scan);
    expect(rows().filter((t) => !t.acknowledged)).toHaveLength(0);
    expect(useAlertStore.getState().episodes).toEqual({});
  });
});

describe('alertStore episodes — clearAll / deleteAlert', () => {
  it('clearAll clears episodes; deleteAlert leaves them', () => {
    add();
    useAlertStore.getState().deleteAlert(rows()[0]!.id);
    expect(useAlertStore.getState().episodes[KEY]).toBeDefined();
    useAlertStore.getState().clearAll();
    expect(useAlertStore.getState().episodes).toEqual({});
  });
});

describe('alertStore episodes — persistence (v4)', () => {
  it('v3 → v4 migration keeps toasts and suppressions and does not re-add an unchecked STRUCTURAL_STOP_BREACHED', () => {
    const enabledTypes = DEFAULT_CONFIG.enabledTypes.filter((t) => t !== 'STRUCTURAL_STOP_BREACHED');
    const toast: ToastItem = {
      id: 'a', kind: 'Critical', symbol: 'AAPL', reason: 'x', recId: 'REC-1', alertType: 'STOP_REACHED',
      dismissed: false, acknowledged: true, firedAt: new Date(T0).toISOString(),
    };
    const migrated = migrateAlerts({
      toasts: [toast], config: { ...DEFAULT_CONFIG, enabledTypes },
      suppressedAlerts: { [KEY]: true }, firedAlerts: { [KEY]: T0 },
    }, 3);
    expect(migrated.toasts).toEqual([toast]);
    expect(migrated.suppressedAlerts).toEqual({ [KEY]: true });
    expect(migrated.firedAlerts).toEqual({ [KEY]: T0 });
    expect(migrated.config!.enabledTypes).not.toContain('STRUCTURAL_STOP_BREACHED');
    expect(migrated.episodes).toEqual({});
  });

  it('v3 → v4 through the real persist path keeps the unchecked type off', async () => {
    const enabledTypes = DEFAULT_CONFIG.enabledTypes.filter((t) => t !== 'STRUCTURAL_STOP_BREACHED');
    localStorage.setItem('bamendjou-alerts-v2', JSON.stringify({
      version: 3,
      state: {
        toasts: [{
          id: 'a', kind: 'Critical', symbol: 'AAPL', reason: 'x', recId: 'REC-1', alertType: 'STOP_REACHED',
          dismissed: false, acknowledged: true, firedAt: new Date(Date.now()).toISOString(),
        }],
        config: { ...DEFAULT_CONFIG, enabledTypes }, suppressedAlerts: { [KEY]: true }, firedAlerts: {},
      },
    }));
    await useAlertStore.persist.rehydrate();
    const s = useAlertStore.getState();
    expect(s.toasts.map((t) => t.id)).toEqual(['a']);
    expect(s.suppressedAlerts).toEqual({ [KEY]: true });
    expect(s.config.enabledTypes).not.toContain('STRUCTURAL_STOP_BREACHED');
    expect(s.episodes).toEqual({});
  });

  it('pre-v3 blobs still get the one-time STRUCTURAL_STOP_BREACHED backfill', () => {
    const migrated = migrateAlerts({ config: { ...DEFAULT_CONFIG, enabledTypes: ['TP_HIT'] } }, 2);
    expect(migrated.config!.enabledTypes).toEqual(['TP_HIT', 'STRUCTURAL_STOP_BREACHED']);
  });

  it('drops malformed episode entries and keeps valid ones', () => {
    const good = { startedAt: new Date(T0).toISOString(), lastSeenAt: T0, lastSurfacedAt: T0 };
    const migrated = migrateAlerts({
      episodes: {
        good,
        badStart: { startedAt: 5, lastSeenAt: T0, lastSurfacedAt: T0 },
        badDate: { startedAt: 'not a date', lastSeenAt: T0, lastSurfacedAt: T0 },
        badSeen: { startedAt: good.startedAt, lastSeenAt: 'x', lastSurfacedAt: T0 },
        nanSurfaced: { startedAt: good.startedAt, lastSeenAt: T0, lastSurfacedAt: null },
        notObj: 7,
      },
    }, 4);
    expect(migrated.episodes).toEqual({ good });
    expect(migrateAlerts({ episodes: [1, 2] }, 4).episodes).toEqual({});
  });

  it('persist → rehydrate keeps episodes and an acknowledged condition stays suppressed (no re-toast, no chime)', async () => {
    add();
    useAlertStore.getState().acknowledgeAlert(rows()[0]!.id);
    const saved = localStorage.getItem('bamendjou-alerts-v2');
    expect(saved).not.toBeNull();
    expect(JSON.parse(saved!).version).toBe(4);
    expect(JSON.parse(saved!).state.episodes[KEY]).toBeDefined();

    // Simulate a reload: wipe memory (persist writes that wipe too, so put the
    // saved blob back), then hydrate from storage.
    useAlertStore.setState({ toasts: [], firedAlerts: {}, suppressedAlerts: {}, episodes: {} });
    localStorage.setItem('bamendjou-alerts-v2', saved!);
    await useAlertStore.persist.rehydrate();
    expect(useAlertStore.getState().episodes[KEY]).toEqual({
      startedAt: new Date(T0).toISOString(), lastSeenAt: T0, lastSurfacedAt: T0,
    });
    expect(useAlertStore.getState().suppressedAlerts[KEY]).toBe(true);

    beeps = 0;
    at(T0 + 2 * H);
    add();
    expect(rows().filter((t) => !t.acknowledged)).toHaveLength(0);
    expect(beeps).toBe(0);
  });
});
