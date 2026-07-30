# Execution Parameters rsi_floor/volume_multiplier Drift Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the hardcoded `rsi_floor` and `volume_multiplier` defaults in the Step 3 "Execution Parameters" panel so they match `backend/config/scoring_rules.yaml` (they drifted the same way `event_reject_days`/`event_caution_days` did, fixed in a prior commit), and add a regression test that pins the correct values against the YAML so this can't silently drift again.

**Architecture:** This is a pure data-correction fix, no new abstractions. `frontend/lib/executionParamDefaults.ts` is a plain hardcoded mirror of the backend YAML (by design — see the file's header comment); it is not fetched at runtime. The fix is: (1) a literal-value regression test following the existing `paramDefaults.eventDays.test.ts` pattern, (2) correcting the literal numbers in the defaults table, (3) fixing one now-stale e2e assertion that hardcodes the old wrong number.

**Tech Stack:** TypeScript, Jest, Playwright (e2e) — frontend only, no backend changes.

---

## Ground truth (confirmed by reading `backend/config/scoring_rules.yaml` directly)

| Horizon key (frontend) | YAML path | rsi_floor | volume_multiplier |
|---|---|---|---|
| Intraday | `horizons.intraday.trigger` | 40 | 1.20 |
| Swing | `horizons.swing.trigger` | 38 | 1.50 |
| Position | `horizons.position.trigger` | 37 | 1.50 |
| Custom | mirrors Swing (same weights/params as Swing elsewhere in the file) | 38 | 1.50 |

Current wrong values in `frontend/lib/executionParamDefaults.ts`:
- Intraday: `rsi_floor: 44` (wrong), `volume_multiplier: 1.2` (already correct, leave alone)
- Swing: `rsi_floor: 44` (wrong), `volume_multiplier: 1.2` (wrong, should be 1.50)
- Position (`PARAM_DEFAULTS_POSITION`): `rsi_floor: 48` (wrong), `volume_multiplier: 1.2` (wrong, should be 1.50)
- Custom: `rsi_floor: 44` (wrong), `volume_multiplier: 1.2` (wrong, should be 1.50)

`Quarterly`, `SemiAnnual`, `Annual` all spread `PARAM_DEFAULTS_POSITION` (`frontend/lib/executionParamDefaults.ts:90-92`), so fixing `PARAM_DEFAULTS_POSITION` fixes all three — no separate edit needed.

---

## Task 1: Add the failing regression test

**Files:**
- Create: `frontend/app/(frame)/screener/step-3-direction/__tests__/paramDefaults.rsiVolume.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// Regression guard for the rsi_floor/volume_multiplier drift fix (same class of bug
// as paramDefaults.eventDays.test.ts's event_reject_days/event_caution_days fix):
// PARAM_DEFAULTS_PER_HORIZON is a plain hardcoded copy of backend/config/scoring_rules.yaml's
// per-horizon trigger block. Nothing fetches this table from the backend, so it can
// silently drift — it already had, for all three horizons' rsi_floor and for
// Swing/Position's volume_multiplier.
//
// Expected values below are literal copies of scoring_rules.yaml's
// horizons.<horizon>.trigger.{rsi_floor,volume_multiplier} block, deliberately
// hand-copied rather than derived from any other frontend constant — comparing two
// frontend hardcoded copies against each other would pass even if both had drifted
// to the same wrong number together. Keep these three pairs in sync with the YAML
// by hand if it changes.
const EXPECTED_FROM_YAML: Record<'Intraday' | 'Swing' | 'Position', { rsi_floor: number; volume_multiplier: number }> = {
  Intraday: { rsi_floor: 40, volume_multiplier: 1.20 },
  Swing:    { rsi_floor: 38, volume_multiplier: 1.50 },
  Position: { rsi_floor: 37, volume_multiplier: 1.50 },
};

describe('Step 3 Execution Parameters defaults — rsi_floor/volume_multiplier match the backend', () => {
  it.each(['Intraday', 'Swing', 'Position'] as const)(
    '%s: rsi_floor/volume_multiplier match scoring_rules.yaml',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      const expected = EXPECTED_FROM_YAML[horizon];
      expect(defaults.rsi_floor).toBe(expected.rsi_floor);
      expect(defaults.volume_multiplier).toBe(expected.volume_multiplier);
    },
  );

  it('Custom mirrors the Swing trigger tuning (Custom defaults to a 5-15d hold, same as Swing)', () => {
    const custom = PARAM_DEFAULTS_PER_HORIZON.Custom;
    expect(custom.rsi_floor).toBe(EXPECTED_FROM_YAML.Swing.rsi_floor);
    expect(custom.volume_multiplier).toBe(EXPECTED_FROM_YAML.Swing.volume_multiplier);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="paramDefaults.rsiVolume"`
Expected: FAIL — 4 of 4 `it`/`it.each` cases fail. Note Jest aborts each test body at its first failing `expect`: for Intraday, `rsi_floor` (44 vs expected 40) fails first, so its `volume_multiplier` assertion on the next line never executes — it does not "pass," it simply isn't reached. All three `it.each` cases and the `Custom` case report as failing tests.

---

## Task 2: Fix the hardcoded defaults

**Files:**
- Modify: `frontend/lib/executionParamDefaults.ts`

- [ ] **Step 1: Fix `PARAM_DEFAULTS_POSITION` (Position horizon)**

In `frontend/lib/executionParamDefaults.ts`, line 23, change:
```ts
  macd_fast: 12, macd_slow: 26, macd_signal: 9, rsi_floor: 48,
  volume_lookback_bars: 20, volume_multiplier: 1.2,
```
to:
```ts
  macd_fast: 12, macd_slow: 26, macd_signal: 9, rsi_floor: 37,
  volume_lookback_bars: 20, volume_multiplier: 1.50,
```

- [ ] **Step 2: Fix the `Intraday` entry**

In `PARAM_DEFAULTS_PER_HORIZON.Intraday`, line 48, change:
```ts
    macd_fast: 5, macd_slow: 13, macd_signal: 3, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
```
to:
```ts
    macd_fast: 5, macd_slow: 13, macd_signal: 3, rsi_floor: 40,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
```
(`volume_multiplier` for Intraday was already correct — value unchanged, only `rsi_floor` moves.)

- [ ] **Step 3: Fix the `Swing` entry**

In `PARAM_DEFAULTS_PER_HORIZON.Swing`, line 71, change:
```ts
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
```
to:
```ts
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 38,
    volume_lookback_bars: 20, volume_multiplier: 1.50,
```

- [ ] **Step 4: Fix the `Custom` entry**

In `PARAM_DEFAULTS_PER_HORIZON.Custom`, line 98, change:
```ts
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
```
to:
```ts
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 38,
    volume_lookback_bars: 20, volume_multiplier: 1.50,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="paramDefaults.rsiVolume"`
Expected: PASS — 4/4 tests pass.

- [ ] **Step 6: Run typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, zero errors (no type shape changed, only literal numeric values).

---

## Task 3: Fix the stale e2e assertion

**Files:**
- Modify: `frontend/e2e/tests/ws-d-execution-params.spec.ts:29-36`

- [ ] **Step 1: Update the hardcoded Swing rsi_floor assertion, and add coverage for volume_multiplier's rendered value**

The test `'default values shown for Swing horizon'` asserts the panel renders the old wrong Swing `rsi_floor` value, and adds no coverage at all for `volume_multiplier`'s displayed value. That field is `type: 'display'`, rendered via `formatDefault()` in `page.tsx` as the plain string `String(val)` (no unit suffix), so the corrected value renders as literal text `"1.5"`.

**`"1.5"` is NOT unique on this panel** — `confidence_atr_mult` (subGroup "Confidence", `type: 'number'`) also defaults to `1.5` on every horizon (`frontend/lib/executionParamDefaults.ts` lines 19/44/67/94) and is rendered as its own `formatDefault(1.5)` → `"1.5"` text (`page.tsx`'s number-input row, lines 493-500) directly adjacent to its input. Both "STOCKS" (`stocksOpen` inits `true`) and the "Confidence" subgroup (`subGroupOpen[sg] ?? true` — "Confidence" isn't in the initial `subGroupOpen` state object at line 644-646, so it falls through to the `true` default) are expanded automatically, so both `"1.5"` texts are visible simultaneously after the test's one `Execution Parameters` click. A bare `page.getByText('1.5')` resolves to two elements and Playwright's strict mode throws rather than passing.

Both the `type: 'display'` row and the `type: 'number'` row carry `data-param-key={def.key}` on their wrapping `div` (`page.tsx` lines 371 and 494), so scope the locator to `[data-param-key="volume_multiplier"]` to disambiguate. Change:
```ts
  test('default values shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    await expect(page.getByText('34')).toBeVisible();
    await expect(page.getByText('44')).toBeVisible();
  });
```
to:
```ts
  test('default values shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    await expect(page.getByText('34')).toBeVisible();
    await expect(page.getByText('38')).toBeVisible();
    await expect(page.locator('[data-param-key="volume_multiplier"]').getByText('1.5')).toBeVisible();
  });
```
(`34` is `iv_rank_pass_max` for Swing — unrelated to this fix, unchanged. `44` was the stale `rsi_floor` display; `38` is the corrected value from Task 2 Step 3. The scoped `volume_multiplier` locator is new coverage, previously untested, and will fail against the pre-Task-2 code same as the `38` line — the corrected literal is `1.50` in TS source but renders as `"1.5"` via `String(1.5)`.)

- [ ] **Step 2: Confirm no other e2e test in this file hardcodes the old rsi_floor/volume_multiplier values**

Run: `grep -n "'44'\|'48'\|'1\.2'" "F:\Git\GitHub\Trading assistant\frontend\e2e\tests\ws-d-execution-params.spec.ts"`
Expected: no matches (the `rsi_floor` values `50`/`55` used elsewhere in the file are user-entered override values in different tests, not defaults — unaffected, don't search for those). Note: this grep deliberately excludes `1.5`/`1\.5` as a search term — Step 1 just added a literal `'1.5'` locator string to this same file, so a grep for `1.5` would trivially self-match and prove nothing.

This is a Playwright e2e spec; it is not run as part of `npm run test` (Jest). Do not attempt to execute it against a live server as part of this plan — visual/textual correctness is verified by inspection in Step 1-2 above, consistent with how the prior event-days fix updated this same file without an e2e run.

---

## Task 4: Verify full suite and commit

- [ ] **Step 1: Run the full frontend Jest suite for touched areas**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="paramDefaults|step-3-direction"`
Expected: all suites pass, including the pre-existing `paramDefaults.eventDays.test.ts` (untouched by this change) and the new `paramDefaults.rsiVolume.test.ts`.

- [ ] **Step 2: Run full typecheck one more time**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, zero errors.

- [ ] **Step 3: Commit**

```bash
git add "frontend/lib/executionParamDefaults.ts" \
  "frontend/app/(frame)/screener/step-3-direction/__tests__/paramDefaults.rsiVolume.test.ts" \
  "frontend/e2e/tests/ws-d-execution-params.spec.ts"
git commit -m "$(cat <<'EOF'
fix(screener): correct Execution Parameters rsi_floor/volume_multiplier defaults

Step 3's Execution Parameters panel carried its own hardcoded copy of
scoring_rules.yaml's per-horizon rsi_floor and volume_multiplier, and it had
drifted (same class of bug as the earlier event_reject_days/event_caution_days
fix): Intraday/Swing/Position rsi_floor were all wrong (44/44/48 instead of
40/38/37), and Swing/Position volume_multiplier was wrong (1.2 instead of
1.50). Corrected the literals and added a regression test that pins them
against the YAML by hand, plus fixed one now-stale e2e assertion.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes (spec coverage)

- Ground-truth values were confirmed by reading `backend/config/scoring_rules.yaml` directly (not by grep pattern-matching alone) for all three horizons.
- Checked for other frontend copies of these fields beyond `executionParamDefaults.ts` (the class of bug that caused the original event-days drift to have three copies): `page.tsx` only references the field *key* for form rendering, `stockScan.ts` only lists the key name for override-forwarding, and the e2e spec's `50`/`55` values are user-entered overrides in unrelated tests — the one real second copy found was the e2e spec's hardcoded `'44'` display assertion, now covered in Task 3.
- `Quarterly`/`SemiAnnual`/`Annual` need no separate task — confirmed they spread `PARAM_DEFAULTS_POSITION` rather than duplicating it.
- No backend changes needed — the backend already implements the correct values; only the frontend's hardcoded mirror was wrong.
- **Known adjacent gap, deliberately out of scope:** the immediately preceding commit (`e75ef76`) fixed the *same class* of drift for `event_reject_days`/`event_caution_days` on Step 5 by fetching live from a new `/api/config/event-thresholds` endpoint via `eventThresholdsStore` — but that architectural fix was only wired into Step 5's page, not Step 3's. Step 3's own `event_reject_days`/`event_caution_days` in `executionParamDefaults.ts` remain hardcoded literals, in the identical drift-prone state this plan's `rsi_floor`/`volume_multiplier` fields are in. This plan intentionally does not re-architect Step 3 to fetch live (that's a materially bigger change than a literal-value correction) — it only corrects the literals, same as the event-days fix's own literal-correction step for Step 3 did. Worth a separate follow-up plan if Kenneth wants Step 3 fully off hardcoded mirrors.
