import { useScanStore } from '../scanStore';

// Reach into the store's persist config for the real merge() callback, the same
// way scanStoreHorizonMigration.test.ts reaches migrate().
const merge = (useScanStore as unknown as {
  persist: { getOptions: () => { merge: (persisted: unknown, current: unknown) => Record<string, unknown> } };
}).persist.getOptions().merge;

const current = { scanState: 'IDLE', screenerMode: 'options', someAction: () => {} };

describe('scanStore persisted merge(): hydration with no stored state', () => {
  // Regression: merge() dereferenced `persisted` directly, so a first visit —
  // empty localStorage, persisted === undefined — threw a TypeError. zustand
  // swallows that in its internal catch, so onFinishHydration never fired and
  // persist.hasHydrated() stayed false forever. ScreenerStepGate's 1500ms grace
  // timer then bounced every deep step URL to step-1-regime, which is why a
  // fresh browser could not open Steps 2-7 at all.
  it('does not throw when nothing has been persisted yet (first visit)', () => {
    expect(() => merge(undefined, current)).not.toThrow();
  });

  it('does not throw on a null persisted blob', () => {
    expect(() => merge(null, current)).not.toThrow();
  });

  it('falls back to IDLE and preserves current state when persisted is undefined', () => {
    const out = merge(undefined, current);
    expect(out.scanState).toBe('IDLE');
    expect(out.screenerMode).toBe('options');
    // Actions on the current state must survive the merge — a replace-style
    // hydration that dropped them would leave the store without its methods.
    expect(typeof out.someAction).toBe('function');
  });

  it('still restores a terminal persisted scanState', () => {
    for (const terminal of ['COMPLETED', 'PARTIAL', 'FAILED']) {
      expect(merge({ scanState: terminal }, current).scanState).toBe(terminal);
    }
  });

  it('still resets a non-terminal persisted scanState to IDLE', () => {
    // An in-progress state from before a crash or server restart is meaningless.
    expect(merge({ scanState: 'RUNNING' }, current).scanState).toBe('IDLE');
  });
});
