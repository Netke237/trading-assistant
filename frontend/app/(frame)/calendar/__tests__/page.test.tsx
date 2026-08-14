import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';

// A fresh `require('@testing-library/react')` (see renderCalendarPageFresh below) re-runs that
// module's top-level side effect of registering an `afterEach(cleanup)` hook -- which Jest
// refuses mid-test ("Hooks cannot be defined inside tests"). Skip that auto-registration and
// clean the DOM up manually instead (see afterEach below).
process.env.RTL_SKIP_AUTO_CLEANUP = 'true';

jest.mock('@/lib/api', () => ({
  api: {
    getEvents: jest.fn().mockResolvedValue([]),
  },
}));

/**
 * Simulates a timezone whose *local* wall-clock calendar day is `offsetDays` away from the
 * instant's UTC calendar day, by mocking `Date.prototype`'s local getters to return the UTC
 * fields of `(this instant) + offsetDays`, while leaving the real UTC getters (and
 * `toISOString()`) untouched.
 *
 * This is used instead of mutating `process.env.TZ` because that mutation does not reliably
 * propagate to `Date`/`Intl`'s timezone resolution inside this Jest/Node sandbox once the
 * process has already resolved a default zone (verified empirically) -- mocking the getters
 * directly sidesteps that and deterministically reproduces the local-vs-UTC calendar-day
 * mismatch the bug fix is about, regardless of host environment quirks.
 */
function mockLocalDayOffsetFromUtc(offsetDays: number): void {
  const shift = (d: Date) => new Date(d.getTime() + offsetDays * 86_400_000);
  jest.spyOn(Date.prototype, 'getFullYear').mockImplementation(function (this: Date) {
    return shift(this).getUTCFullYear();
  });
  jest.spyOn(Date.prototype, 'getMonth').mockImplementation(function (this: Date) {
    return shift(this).getUTCMonth();
  });
  jest.spyOn(Date.prototype, 'getDate').mockImplementation(function (this: Date) {
    return shift(this).getUTCDate();
  });
}

/**
 * `TODAY` in `page.tsx` is a module-level `const` computed once at import time from `new Date()`
 * — so to test it under a mocked system time, the module must be freshly re-required *after*
 * `jest.setSystemTime()` runs, not just re-rendered.
 *
 * `jest.isolateModules` sandboxes the *entire* dependency graph resolved inside its callback,
 * including `react` itself — so both the page's `react` and the `render()` call used to mount it
 * must come from requires made inside the same isolated block, or React ends up with two
 * different module instances and hook calls fail with a null dispatcher. `screen` queries the
 * DOM directly (via `@testing-library/dom`) and doesn't depend on which React instance rendered
 * into it, so it's safe to keep using the statically-imported one for assertions.
 */
function renderCalendarPageFresh(): void {
  jest.isolateModules(() => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const freshReact = require('react');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { render: freshRender } = require('@testing-library/react');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const CalendarPage = require('../page').default;
    freshRender(freshReact.createElement(CalendarPage));
  });
}

/** ISO date of the grid cell that is initially selected (selected state seeds from TODAY). */
function todayCellIso(): string | null {
  const pressed = screen.getAllByRole('button', { pressed: true });
  const el = pressed[0];
  const label = el?.getAttribute('aria-label') ?? '';
  const match = label.match(/^\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : null;
}

describe('Calendar page — "Today" reflects the user\'s local calendar day, not UTC', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    jest.useRealTimers();
    jest.restoreAllMocks();
    jest.resetModules();
  });

  it('does not roll "Today" to tomorrow for a UTC-behind zone after evening local hours', () => {
    // e.g. 2026-03-15 21:00 EDT (US Eastern, UTC-4) == 2026-03-16 01:00 UTC: local calendar day
    // (March 15) is one day BEHIND the UTC calendar day (March 16). The old bug read UTC
    // calendar fields directly and would show "today" as March 16.
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-03-16T01:00:00Z'));
    mockLocalDayOffsetFromUtc(-1);

    renderCalendarPageFresh();

    expect(todayCellIso()).toBe('2026-03-15');
  });

  it('does not roll "Today" to yesterday for a UTC-ahead zone', () => {
    // e.g. 2026-03-16 09:00 AEDT (Sydney, UTC+11) == 2026-03-15 22:00 UTC: local calendar day
    // (March 16) is one day AHEAD of the UTC calendar day (March 15) -- the opposite failure
    // direction from the US-Eastern case above. A naive "just always use UTC" fix would get
    // this direction wrong.
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-03-15T22:00:00Z'));
    mockLocalDayOffsetFromUtc(1);

    renderCalendarPageFresh();

    expect(todayCellIso()).toBe('2026-03-16');
  });

  it('keeps a stable local "Today" for a UTC-behind zone shortly before local midnight', () => {
    // 2026-03-15 23:30 local == 2026-03-16 03:30 UTC -- deep into "tomorrow" by UTC, but still
    // "today" (March 15) locally.
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-03-16T03:30:00Z'));
    mockLocalDayOffsetFromUtc(-1);

    renderCalendarPageFresh();

    expect(todayCellIso()).toBe('2026-03-15');
  });

  it('matches UTC when local and UTC calendar days coincide (no offset)', () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-03-15T12:00:00Z'));
    mockLocalDayOffsetFromUtc(0);

    renderCalendarPageFresh();

    expect(todayCellIso()).toBe('2026-03-15');
  });
});
