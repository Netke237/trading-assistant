# DOCC-3: Step 5's threshold stores refuse on a failed fetch and re-fetch on mount

Document C, plan 3 of the YAML-CONFIG-INTEGRITY split. Frontend only, one layer.
It follows the DOCC-2 plan (`2026-09-28-docc-2-options-regime-plan.md`), and
DOCC-1's and DOCC-2's backend checks stay as they are.

**Implements:** decision `DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29`, from Kenneth
on 2026-09-29 (all four recommended or chosen options):
- (1) **Refuse.** A failed or malformed threshold fetch shows no thresholds and no
  IV/event verdicts. It never shows the hardcoded `FALLBACK`.
- (2) **Re-fetch on mount, plus Retry.** Step 5, the Step 7 rail and Settings each
  fetch when they mount. A failed fetch offers a Retry button.
- (3) **Settings' IV edit is kept, as an override layer.** It survives a re-fetch
  and is labelled wherever it changes a verdict.
- (4) **Step 3's per-scan overrides are out of scope.** That mismatch is logged as
  a separate target, DOCC-3b (§5).

**Closes:** round-5 finding G3 (§13.1 of `2026-09-16-yaml-config-integrity-plan.md`),
and §11.1 item 3 for the two stores that still exist. The third store §11.1
names, `stopPremiumThresholdsStore.ts`, is no longer in the tree.

---

## 1. The defect, on main `94ee443`

| Site | Today | Consequence |
|---|---|---|
| `lib/eventThresholdsStore.ts:31-43` | Starts at `thresholds: FALLBACK`. On a failed fetch, `catch { set({ loaded: true }) }` keeps it. | Step 5 grades event proximity against 1/3, 21/45 and 30/60 whatever the YAML says, and shows no sign of it. |
| `lib/eventThresholdsStore.ts:45-50` `getEventWindow` | `thresholds[h] ?? FALLBACK[h] ?? FALLBACK.Swing` | A good payload that lacks a horizon is graded silently on the hardcoded or Swing window. |
| `lib/ivThresholdsStore.ts:87-99` | Same as the event store, with FALLBACK 34/55 and 44/65. | Step 5 IV verdicts and the Step 7 "IV acceptable" item are graded against numbers the YAML may no longer hold. |
| `lib/ivThresholdsStore.ts:106-124` `getIvPassMax` / `getIvCautionMax` | `thresholds[h]?.[k] ?? FALLBACK[h]?.[k] ?? null`, where **`null` means "no IV gate"**. | Worse than a fallback. A payload whose `Swing` entry is missing or carries `null` reads as "IV gate disabled", and every Swing row with a reading passes the IV side. |
| `components/atoms/{Event,Iv}ThresholdsBootstrap` | Fetch once, in `(frame)/layout.tsx`. | An edit to `scoring_rules.yaml` never reaches an open tab. A single failed fetch at app load means FALLBACK for the whole session. |
| `app/(frame)/settings/page.tsx:1135-1210` `IvThresholdsSection` | `setThresholds({...thresholds, Swing: {...abs_pass_max}})` writes into the fetched record. Input seeds and parse failures fall back to the literals `34` / `44`. | Once re-fetching lands, a re-fetch would silently wipe the user's session edit. While nothing is loaded, the inputs show 34/44, numbers that did not come from the backend. |

These are the only readers (grep on `main`):
- Step 5 `page.tsx:262-400`
- the Step 7 rail `@contextRail/screener/step-7-trade-card/page.tsx:62-99,142`
- Settings `:1136`
- the two bootstraps
- `lib/ivThresholds.ts`, a re-export shim with **no importers**

`statusTooltips.ts:303` mentions `FALLBACK` only in a comment.

**What the backend returns.** `GET /api/config/{iv,event}-thresholds`
(`backend/app/routers/config.py`) bare-indexes `horizons[key]`. A broken
`scoring_rules.yaml` gives a 500, which `api.ts:apiError` turns into a thrown
`Error` whose message carries the path and status. The IV endpoint uses `.get`
for the four keys, so a missing key is served as `null` (see §5, logged).

## 2. What changes

### 2.1 `lib/eventThresholdsStore.ts`

```ts
export type ThresholdHorizon = 'Intraday' | 'Swing' | 'Position';
export const THRESHOLD_HORIZONS: readonly ThresholdHorizon[] = ['Intraday', 'Swing', 'Position'];
export type ThresholdsStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface EventThresholdsState {
  /** ONLY ever a validated backend payload. null = none in hand. */
  thresholds: Record<ThresholdHorizon, HorizonEventThresholds> | null;
  status:     ThresholdsStatus;
  error:      string | null;
  fetch:      () => Promise<void>;
}

/** Throws Error naming the path, e.g. "Swing.caution_days: expected a number". */
export function parseEventThresholds(raw: unknown): Record<ThresholdHorizon, HorizonEventThresholds>;
```

**Fetch semantics:**

- Module-level `let seq = 0`. `fetch()` takes `const my = ++seq` and sets
  `status: 'loading'`. `thresholds` is NOT cleared here: a record that was
  valid stays on screen until the answer arrives.
- After the `await`, `if (my !== seq) return`. Only the latest request writes,
  so a slow first response cannot overwrite a newer one. Step 5 and the rail
  mounting in the same tick is the common case.
- Success: `set({ thresholds: parseEventThresholds(data), status: 'ready', error: null })`.
- Any throw, from the network, from `apiError` or from `parse`:
  `set({ thresholds: null, status: 'failed', error: messageOf(e) })`.
  **Clearing on failure is the refusal.** A backend that now says the config is
  broken outranks the record fetched a minute ago.

**`parseEventThresholds` rules:**

- The payload is a plain object.
- All three horizons are present.
- `reject_days` and `caution_days` are finite numbers, each `>= 0`.
- `reject_days <= caution_days`.

Extra keys are ignored. The shipped YAML (1/3, 21/45, 30/60) passes.

**Deleted:**

- `FALLBACK`, `loaded`, and the unused `setThresholds`.
- The `?? FALLBACK…` chain in `getEventWindow`. It becomes
  `getEventWindow(h: ThresholdHorizon, t: Record<ThresholdHorizon, …>) => t[h]`.

The header comment is rewritten to say that the store holds only backend values,
and to name decision `DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29`.

### 2.2 `lib/ivThresholdsStore.ts`

The status, `seq` and failure semantics are the same as in §2.1. It imports
`ThresholdHorizon`, `THRESHOLD_HORIZONS` and `ThresholdsStatus` from the event
store; nothing new is shared beyond those.

**`parseIvThresholds` rules:**

- All three horizons are present.
- All four keys are present on each horizon, as a finite number in `[0, 100]`
  or `null`. A key that is **absent** is refused, not treated as `null`.
- **Per basis** (`abs_*` and `rank_*`, each separately):
  - `pass_max === null` requires `caution_max === null`;
  - `pass_max <= caution_max` when both are numbers.

Shipped values pass: Intraday is all null; Swing and Position are 34/55 and
44/65 on both bases.

**The Settings override layer:**

```ts
export type IvOverrideHorizon = 'Swing' | 'Position';
overrides: Partial<Record<IvOverrideHorizon, { abs_pass_max: number }>>;
setAbsPassOverride: (h: IvOverrideHorizon, v: number) => void;
clearOverrides:     () => void;

/** Pure. null when `thresholds` is null. The override is NOT applied to a
 *  horizon whose fetched abs_pass_max is null (no gate there: an override must
 *  not invent one). An override above abs_caution_max raises the pass ceiling
 *  only; the caution ceiling is unchanged, so that band is empty. That is
 *  today's behaviour, kept. */
export function effectiveIvThresholds(t, overrides): Record<ThresholdHorizon, HorizonIvThresholds> | null;
export function ivOverrideFor(h: ThresholdHorizon, t, overrides): { value: number; yaml: number } | null;
```

- `fetch()` never touches `overrides`. That is what lets an edit survive a
  re-fetch.
- `overrides` is not persisted, the same as today ("session only").

**Deleted:**

- `FALLBACK`, `loaded`, `setThresholds`.
- The `?? FALLBACK…` fallthrough in `getIvPassMax` / `getIvCautionMax`. Both now
  take `(h: ThresholdHorizon, t: Record<ThresholdHorizon, HorizonIvThresholds>, basis)`
  and read `t[h][k]`. `parse` guarantees `t[h]` exists, and `null` keeps its one
  meaning: no gate on this basis.

**Zustand v5 trap.** Consumers must select `thresholds` and `overrides` as two
separate selectors and call `effectiveIvThresholds` inside `useMemo`. A selector
that returns a fresh object re-renders forever in v5.

Also delete `lib/ivThresholds.ts`, the shim with no importers. It re-exports
`FALLBACK`, so leaving it would stop the build.

### 2.3 Fetch on mount

- **Step 5** (`page.tsx`), the **Step 7 rail** (`page.tsx`) and **Settings**
  `IvThresholdsSection` each add
  `useEffect(() => { void useXStore.getState().fetch(); }, [])`.
  Step 5 fetches both stores; the rail and Settings fetch only the IV store.
- The two Bootstrap atoms and their mounts in `(frame)/layout.tsx` are
  **deleted**. The pages now fetch for themselves, and a fetch at app load
  whose result nobody reads only adds a second request that can race.
- **Staleness boundary, stated so nobody over-reads the fix:** a YAML edit
  reaches the page on the next mount, **subject to the backend's `lru_cache`**
  on `load_scoring_cfg` (§9.2, pre-existing, not changed here).

### 2.4 Step 5 (`app/(frame)/screener/step-5-vol-events/page.tsx`)

**The page's state:**

- `const iv = effective` (from §2.2) and `const ev = useEventThresholdsStore(s => s.thresholds)`.
- `avail: 'ready' | 'loading' | 'failed'`:
  - `failed` if either store's status is `failed`;
  - otherwise `ready` if both records are non-null;
  - otherwise `loading`.

  `ready` does not require `status === 'ready'`, because a re-fetch in flight
  keeps the last good record on screen.
- `horizonKey` is typed `ThresholdHorizon`. The existing ternary already yields
  exactly those three values.

**When `avail !== 'ready'`, the page computes no verdict:**

- In every `gatedRows` entry, `ivSt`, `proxStatus` and `gate` are all `'PENDING'`
  while loading and all `'NO_DATA'` when failed.
- `drivers` is a constant with every flag false. `gateDrivers` is not called.
- `gateSummary` is `null`, so there is no counts line.
- `gateDisabled` is `false`. It is only computed when `ready`, so "IV gate
  disabled for this horizon." can never be said about an unknown config.
- `ivBands` is `[]`.
- The IV mini-bar fill is not rendered.
- The GATE badge's tooltip is the unavailable sentence below, instead of
  `eventVolGateTooltip(…)`, which quotes `evReject` and `evCaution`.
- The root's `data-ev-reject` and `data-ev-caution` render as `""`, and
  `data-iv-gated` as `"unknown"`.

**The header's thresholds line.** When `avail !== 'ready'`, the `iv-thresholds`,
`event-window` and `gate-rule` parts are **replaced** by:

```tsx
<span data-part="thresholds-unavailable" data-avail={avail} data-error={error ?? ''}>
  {avail === 'loading'
    ? 'Loading the volatility and event thresholds from scoring_rules.yaml…'
    : `The volatility and event thresholds could not be loaded from scoring_rules.yaml (${error}). No IV or event verdict is shown.`}
</span>
{avail === 'failed' && <button data-part="thresholds-retry" …>Retry</button>}
```

Retry calls both stores' `fetch()`.

**The override label.** When `avail === 'ready'` and
`ivOverrideFor(horizonKey, …)` is non-null, one more part is appended to the
thresholds line after `iv-thresholds`:

```tsx
<span data-part="iv-override" data-override={value} data-yaml={yaml}>
  IV pass ceiling is a session override from Settings ({value}), not scoring_rules.yaml's ({yaml}).
</span>
```

**The test contract.** The Step 5 tests enforce that nothing undeclared may
speak (`gateSummary.test.tsx` `PART_PINS` and the owner walk at `:388-440` and
`:793-840`). The three new parts get **pins** that check each part's words
against its own published `data-*`, in the declared order. They are not added
to a whitelist.

### 2.5 Step 7 rail (`@contextRail/screener/step-7-trade-card/page.tsx`)

- `buildChecklist` takes `ivThresholds: Record<ThresholdHorizon, HorizonIvThresholds> | null`,
  the effective record from §2.2.
- When it is `null`, the "IV acceptable" item is
  `{ status: 'CAUTION', detail: 'IV thresholds could not be loaded from scoring_rules.yaml — the IV gate was not applied.' }`,
  checked **before** the `gateDisabled` branch. It is never PASS and never
  "No IV gate for Intraday": an unknown config is not a disabled gate. CAUTION
  is the rail's existing word for "could not be checked" (`rrPending`, no IV
  data).
- When `ivOverrideFor` is non-null for the horizon, the detail ends with
  ` (session override from Settings; scoring_rules.yaml: ${yaml})`.
- It fetches on mount, per §2.3.

### 2.6 Settings `IvThresholdsSection`

- It reads the fetched `thresholds`, `overrides` and `status`, and fetches on
  mount.
- **Input seeds**:
  - the override if one is set;
  - otherwise the fetched `abs_pass_max`;
  - otherwise `''`.

  The literals `?? 34` and `?? 44` are deleted, and so are the `isNaN → 34/44`
  defaults.
- **Apply:**
  - A field whose parsed value is not a number in `[1, 100]` is not applied, and
    the section says so inline.
  - Otherwise it calls `setAbsPassOverride(h, v)`.
  - Apply is disabled unless the store's thresholds are non-null (`ready`, or
    `loading` with the last good record). With no fetched record it shows the
    error text instead.
- A new **"Reset to scoring_rules.yaml"** button calls `clearOverrides()`.
- The blurb is reworded to say that the edit is a session override on top of
  the fetched values, and that it changes Step 5 and the Step 7 checklist only,
  never the scan.

## 3. Tests

**New fixture file `lib/testFixtures/thresholds.ts`.** The shipped values, as
typed records: `EVENT_SHIPPED` and `IV_SHIPPED`. Every test that imported
`FALLBACK` now imports these. They are fixtures, not a fallback. The file sits
outside `__tests__` because jest would collect it there and fail it as "Your
test suite must contain at least one test". No production module may import it.

**`lib/__tests__/eventThresholdsStore.test.ts`** (rewritten):

- E1: a good payload gives `ready`, the parsed record and `error: null`.
- E2: a rejection (`new Error('GET /api/config/event-thresholds → 500 …')`) gives
  `thresholds: null`, `failed`, and an `error` that contains the message. A
  record that was ready before is **cleared**.
- E3: malformed payloads each give `failed`, with an error naming the path:
  - `Swing` missing;
  - `caution_days: "45"`;
  - `reject_days: 50, caution_days: 45`;
  - `NaN`;
  - a non-object.
- E4: a failure followed by a success recovers to `ready`.
- E5: race. Fetch A and fetch B are both in flight; B resolves, then A resolves.
  B's record stands, and A is ignored, whether A succeeded or failed.
- E6: while a re-fetch is in flight after `ready`, `status` is `'loading'` and
  `thresholds` is still the old record.
- E7: `getEventWindow` returns exactly `t[h]`.

**`lib/__tests__/ivThresholdsStore.test.ts`** (new):

- I1–I6: the same cases as E1–E6. I3 also covers:
  - an absent key (refused, not read as `null`);
  - `pass: null, caution: 40` on one basis;
  - `pass: 60, caution: 55`;
  - `101`.
- I7: `setAbsPassOverride('Swing', 50)` followed by a successful re-fetch keeps
  the override, and `effectiveIvThresholds(...).Swing.abs_pass_max === 50`.
- I8: a failed re-fetch keeps `overrides`, but `effectiveIvThresholds` is `null`.
- I9: an override on a horizon whose fetched `abs_pass_max` is `null` is not
  applied, and `ivOverrideFor` returns `null` for it.
- I10: `clearOverrides` restores the fetched value.
- I11: `getIvPassMax` / `getIvCautionMax` read only the record; `null` still
  means no gate.

**`lib/__tests__/ivBasis.test.ts`:** the `FALLBACK` cases move to `IV_SHIPPED`.
The `'Nonsense'` horizon case is deleted, because the type now forbids it.

**Step 5, new `__tests__/thresholdsUnavailable.test.tsx`.** `jest.mock('@/lib/api')`:

- S1: both fetches reject, with a mixed scan (rows that would be PASS, CAUTION
  and REJECT on shipped values).
  - Every `[data-cell="gate"]` has `data-gate="NO_DATA"`, and both side
    attributes are `NO_DATA`.
  - No badge renders PASS, CAUTION or REJECT.
  - There is no `[data-line="summary"]`.
  - The header shows `thresholds-unavailable` with the error text.
  - `data-ev-reject` is `""` and `data-iv-gated` is `"unknown"`.
- S2: only the IV fetch rejects. The page is still wholly `failed`, with no
  event verdicts either. The gate is "worst of" both sides, so half a gate is
  not a gate.
- S3: Retry after a failure, with the api now resolving, shows verdicts equal
  to the ready-path verdicts for the same scan.
- S4: while the fetch is pending, every gate is `PENDING` and the loading
  sentence is shown.
- S5: mount calls each `api.get*Thresholds` once; unmount and remount calls
  each again.
- S6: an Intraday scan that fails to load never shows "IV gate disabled for
  this horizon."
- S7: an override is active for Swing.
  - The `iv-override` part shows, with `data-override` and `data-yaml`.
  - A row whose IV lies between the YAML ceiling and the override is graded by
    the override (the badge agrees with the label).
- S8: the owner walk from `gateSummary.test.tsx` passes. It is moved into a
  shared test helper that both files import, not copied. It must pass
  in the failed, loading and override states, so every new part is declared
  and pinned.

**Existing Step 5 tests** (`gateSummary`, `literalPins`, `eventGate`,
`ivPercentileZero`):

- `thresholds: {}` and `loaded: …` become `thresholds: IV_SHIPPED` (or the
  test's explicit record) and `status: 'ready'`.
- `jest.mock('@/lib/api', …)` resolves the same records, so the mount fetch
  re-sets the values the test set rather than clearing them.
- **No assertion changes.** Any assertion that changes is a finding against the
  build.

**Step 7 rail (`rail.test.tsx`):**

- R1: with `thresholds: null`, the IV item is CAUTION with the named detail, on
  Swing and on Intraday. It is never PASS.
- R2: an active override adds the suffix to the detail, and the verdict uses the
  override.
- R3: mount calls `api.getIvThresholds`.
- The existing cases migrate the same way as Step 5's.

**Settings, new `app/(frame)/settings/__tests__/IvThresholdsSection.test.tsx`.**
It renders the section on its own; export it, or export it through a named test
export if the file's convention forbids that.

- G1: with no record, neither input shows 34 or 44, Apply is disabled, and the
  error text is shown when the store has `failed`.
- G2: Apply writes `overrides` and leaves `thresholds` untouched.
- G3: a re-fetch after Apply keeps the input value and the override.
- G4: Reset clears it.
- G5: Apply with a value outside `[1, 100]` sets nothing and says so.

**Gates:** `npm run typecheck`, `npm run lint` if the repo runs it, and
`npm run test` all clean. The backend is untouched.

## 4. Out of scope

- The `config_health` endpoint and banner, and §9.5's per-poll re-stat. That is
  a later DOCC plan.
- The backend endpoints' bare `KeyError` 500 (§13.2 C2). The frontend shows
  whatever message arrives. A named backend message is the `config_health`
  plan's work.
- The Step 7 rail's "Earnings > 7d away" item uses fixed 7/3 thresholds, not
  the event store. It is not a threshold store, and it is logged below the gate.
- Other hardcoded YAML mirrors, which are not stores and are not G3:
  - `executionParamDefaults.ts`;
  - `statusTooltips.ts` `CONTRACT_PREFERRED`.

## 5. Logged, not fixed here

- **DOCC-3b: Step 3 overrides versus Step 5.** Step 3's Execution Parameters
  send `event_reject_days`, `event_caution_days` and `iv_abs_pass_max` as
  per-scan overrides, and the backend scores with them. Step 5 shows the YAML
  values, so it can disagree with the score even on a good fetch. The likely fix
  is for the scan response to carry the thresholds it applied, which is backend
  plus frontend. Kenneth chose to make it a separate target (2026-09-29).
- **IV endpoint `.get` fail-open.** A missing `iv_abs_pass_max` in the YAML is
  served as `null`, which means no gate. After this plan the frontend still
  reads a served `null` as "no gate". Only an absent KEY is refused. That fix
  belongs on the backend: the same C1 class as G1.

## 6. Behaviour changes Kenneth should know about

1. A failed or malformed threshold fetch now shows **no verdicts** on Step 5
   (every gate is NO_DATA), with the error and a Retry button. It used to show
   verdicts against built-in numbers. The Step 7 "IV acceptable" item reads
   CAUTION with the reason.
2. Step 5, the rail and Settings fetch each time they open, so a YAML edit shows
   up on the next visit, once the backend's cache has dropped the old file.
3. A Settings IV edit now survives those re-fetches, is labelled on Step 5 and
   in the rail, and can be reset. When nothing has loaded, the Settings inputs
   are blank instead of 34/44.
4. The app no longer fetches thresholds at start-up. It fetches when a page that
   uses them opens.

## 7. Audit notes

- Confirm that no reader can still reach a hardcoded threshold:
  - grep for `FALLBACK`, `?? 34`, `?? 44` and `loaded` across `app/`, `lib/` and
    `components/`;
  - check that the deleted shim `lib/ivThresholds.ts` has no importer.
- Confirm that every `null` returned by `getIvPassMax` or `getIvCautionMax` now
  comes only from a validated payload's explicit `null`. None may come from a
  missing horizon or key.
- Confirm the race guard. A stale response, success or failure, must never
  overwrite a newer one (E5, I5).
- Confirm that Step 5 cannot reach `gateDisabled === true` or "IV gate disabled"
  unless `avail === 'ready'`, and that no badge, tooltip or `data-*` quotes a
  number while `avail !== 'ready'`.
- Confirm that the override is applied identically on Step 5 and in the rail
  (the same `effectiveIvThresholds`), and never where the YAML has no gate.
- Confirm that the Zustand selectors do not return fresh objects.

Gate: a finding blocks only if it can put a wrong number in front of a user or
on a broker order, or corrupt persisted data.
