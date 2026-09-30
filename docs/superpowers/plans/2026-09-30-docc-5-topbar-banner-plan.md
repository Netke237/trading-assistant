# DOCC-5: a frame-wide config-health banner and a scoped TopBar chip

Document C, plan 5, the last slice of YAML-CONFIG-INTEGRITY. Frontend only. It
consumes DOCC-4's `GET /api/config/health` (plan
`2026-09-30-docc-4-config-health-plan.md` §2.3) and changes nothing in the
backend.

**Implements:** decision `DOCC-4-5-SLICING-2026-09-30` (a frame-wide banner on
every page whenever the config is not clean; it names which checks ran; stale
config has its own "restart" state) and decision
`DOCC-5-BANNER-DESIGN-2026-09-30`, Kenneth's six answers of 2026-09-30, all the
recommended options:

- (1) **Poll every 30 s while the tab is visible, plus an immediate poll when
  the tab becomes visible or the window regains focus.**
- (2) **Three tiers.** Errors give a reject-tinted banner. Stale gives its own
  caution "restart needed" banner. Warnings alone give a quieter caution strip.
  When several apply, the worst tier sets the colour and the headline.
- (3) **Collapse, never hide.** The user can collapse the detail to a one-line
  strip. The strip stays until the config is clean. Any change in the findings
  re-expands it. Not persisted.
- (4) **A failed health fetch shows "Config health unknown"**, a caution strip
  that names the failure. Never green, never silent. It clears on the next
  good poll (DOCC-3's refuse-to-fall-back precedent).
- (5) **When clean, no banner, but a small TopBar chip** "Config OK · N
  checks". Its popover lists `checked` and `not_checked`. The expanded banner
  lists both as well.
- (6) **Flag multi-worker.** If the polls of one tab see a pid come back after
  a different pid, show a caution line "backend answers from several worker
  processes; health is per process". A single pid change that then holds is a
  restart: an info line in the detail only.

**Closes:** YAML-CONFIG-INTEGRITY's remaining work. Its probe (absent on
`/api/config/health` in `frontend/lib/api.ts`) flips to present with the
build.

---

## 1. What the backend gives, on main `4c52000`

`backend/app/services/config_health.py` `report()` (`:249-335`), served by
`routers/config.py:73-81`. It **always returns 200**; a crash inside the report
becomes one `errors` entry (`:250-260`).

```
{ ok: bool,                       # true only when errors, warnings, stale are all empty
  checked: string[],              # subset of CHECK_ORDER, in that order (:66-70)
  not_checked: string[],          # the NOT_CHECKED literal (:78-84), 5 entries today
  pid: int,                       # os.getpid() of the answering worker
  errors:   [{file, path, message, blocks}],   # blocks may be "" (crash lines)
  warnings: [{file, path, message}],
  stale:    [{file, path, message}] }          # file/path "" for worker/registry lines
```

Things the frontend must not assume:

- `stale` is non-empty **forever** when `WEB_CONCURRENCY > 1` (`:303-309`). That
  is correct: the banner says restart with `--workers 1`, which is the message.
- A crashed report has `checked: []` and one error. It must render as the
  error tier, and the scope line must say nothing was checked.
- `uvicorn --workers N` without `WEB_CONCURRENCY` is invisible to the backend.
  The pid rule in §2.2 is this slice's only handle on it.

## 2. What changes

### 2.1 `lib/configHealth.ts` (new, pure)

```ts
export interface ConfigHealthError   { file: string; path: string; message: string; blocks: string }
export interface ConfigHealthLine    { file: string; path: string; message: string }
export interface ConfigHealthReport {
  ok: boolean; checked: string[]; not_checked: string[]; pid: number;
  errors: ConfigHealthError[]; warnings: ConfigHealthLine[]; stale: ConfigHealthLine[];
}

/** Throws an Error naming the path, e.g. "errors[1].blocks: expected a string". */
export function parseConfigHealth(raw: unknown): ConfigHealthReport;

export type HealthTier = 'checking' | 'clean' | 'warning' | 'multiworker' | 'unknown' | 'stale' | 'error';
```

**Parser rules (refuse, never repair):**

- `raw` must be a plain object. Every key above is required. Extra keys are
  ignored.
- `ok` is a boolean. `checked` and `not_checked` are arrays of strings (either
  may be empty). `pid` is a positive safe integer.
- Every entry of `errors` has the four string fields; every entry of
  `warnings` and `stale` has the three. `""` is allowed in every field.
- **Consistency:** `ok` must equal `errors.length === 0 && warnings.length ===
  0 && stale.length === 0`. A contradiction is refused as
  `"ok: contradicts errors/warnings/stale"`. This is the one place a buggy or
  foreign payload could otherwise produce a green with findings in hand, or a
  red with nothing to show.

**`tierOf(view)`**, the only function that decides the tier. Input:

```ts
interface HealthView {
  status: 'idle' | 'loading' | 'ready' | 'failed';
  report: ConfigHealthReport | null;
  error: string | null;
  fetchedAt: number | null;   // ms, of the report in hand
  multiWorker: boolean;
  now: number;               // the store's clock (§2.2), never Date.now() at render
}
```

Order, first match wins:

1. `report === null` and `error === null` and `status` is `idle` or
   `loading` → `checking`. That is only true before any fetch has finished:
   a failure sets `error`, and a poll that starts does **not** clear it
   (§2.2), so a retry after a failure stays `unknown` while it is in flight
   (round-1 G1).
2. `report === null` → `unknown` (the last fetch failed; §2.2 clears the report
   on failure).
3. `now - fetchedAt > MAX_REPORT_AGE_MS` (70 000: two intervals plus the 10 s
   timeout) → `unknown`, reason "last check is older than 70 s". This closes a
   frozen green in a tab whose timers the browser throttled.
4. `report.errors.length` → `error`.
5. `report.stale.length` → `stale`.
6. `multiWorker` → `multiworker`.
7. `report.warnings.length` → `warning`.
8. otherwise → `clean`.

`clean` is therefore reachable **only** with a parsed report whose `ok` is
true, fetched in the last 70 s, from a tab that has not seen a second worker.

Severity for colour: `error` → reject; `stale`, `unknown`, `multiworker`,
`warning` → caution (`warning` uses the quieter strip style, §2.4);
`checking` → neutral; `clean` → pass (chip only).

**`fingerprintOf(view)`**: a string built from the tier plus the sorted
`kind|file|path|message` of every finding plus `multiWorker`. For `unknown`
it is the constant `'unknown'`, so a changing network message does not keep
re-expanding the strip. `checking` and `clean` return `''`.

### 2.2 `lib/configHealthStore.ts` (new, Zustand, **no `persist()`**)

```ts
interface ConfigHealthState {
  status: 'idle' | 'loading' | 'ready' | 'failed';
  report: ConfigHealthReport | null;
  error: string | null;
  fetchedAt: number | null;
  pids: number[];            // pid of each successful poll, newest last, at most PID_WINDOW (10)
  multiWorker: boolean;
  restartedAt: number | null;  // the last time the pid changed and did not come back
  collapsed: boolean;
  collapsedFingerprint: string | null;
  now: number;               // Date.now() at creation; advanced only by tick() and a successful poll
  tick: () => void;          // set({ now: Date.now() })
  poll: () => Promise<void>;
  setCollapsed: (collapsed: boolean, fingerprint: string) => void;
}
```

**`poll()`**, same race guard as DOCC-3's stores:

- Module-level `let seq = 0`, `const my = ++seq`, `status: 'loading'`. The
  report in hand is **kept** while loading, and so is `error` (round-1 G1:
  clearing it would turn a retry after a failure into `checking`, and the
  banner renders nothing for `checking`).
- `api.getConfigHealth(signal)` with an `AbortController` aborted after
  `FETCH_TIMEOUT_MS` (10 000).
- After the `await`, `if (my !== seq) return`.
- Success: `parseConfigHealth` → `report`, `status: 'ready'`, `error: null`,
  `fetchedAt: Date.now()`, `now: Date.now()`, append the pid to `pids` (trim to 10).
- Any throw (network, `apiError`, abort, parse): `report: null`,
  `status: 'failed'`, `error: message`, `fetchedAt: null`. `pids` is kept.

**The pid rule (decision 6):**

- `multiWorker` is true when some pid in `pids` appears again after a
  different pid (A, B, A). A process that restarts gets a new pid and the old
  one does not come back, so a restart gives A, A, B, B and no flag. The flag
  falls away once the window of 10 polls (5 minutes) holds no such return.
- `restartedAt` is set when the newest pid differs from the previous one and
  `multiWorker` is false. It drives an info line only (§2.4). It is not a
  tier.

**Collapse (decision 3):** `setCollapsed(true, fp)` stores the fingerprint the
user collapsed. The banner is shown collapsed only while
`collapsed && collapsedFingerprint === fingerprintOf(currentView)`. A new
fingerprint therefore shows the banner expanded without any effect having to
reset state. Nothing is written to storage, so a reload expands it too.

### 2.3 `lib/api.ts`

```ts
// DOCC-5: GET /api/config/health (DOCC-4). Always 200; parsed by lib/configHealth.ts.
getConfigHealth: (signal?: AbortSignal) => get<unknown>('/api/config/health', signal),
```

This line flips the YAML-CONFIG-INTEGRITY probe to present.

### 2.4 `components/organisms/ConfigHealthBanner/` (new)

Mounted once in `app/(frame)/layout.tsx`, directly after `<TopBar />`. It owns
the poll:

- On mount: `poll()` immediately.
- `setInterval(30 000)`; each tick polls unless
  `document.visibilityState === 'hidden'` (anything else, `undefined`
  included, counts as visible).
- `visibilitychange` to visible, and window `focus`: poll now, unless a poll
  started less than 2 s ago (focus and visibility fire together).
- A 5 s `setInterval` calling `tick()`, so rule 3 of `tierOf` can turn an old
  green into `unknown` without waiting for a poll. The `visibilitychange` and
  `focus` handlers call `tick()` **before** `poll()`, so a tab coming back
  from a throttled or frozen period is re-judged at once, not at the next
  throttled tick (round-1 G2).
- All listeners and timers removed on unmount.

It renders **nothing** for `checking` and `clean` (the chip covers those).
Otherwise one `<section>` with `aria-live="polite"` (`role="alert"` for the
`error` tier), tinted per §2.1, holding:

- **Headline** (always shown, also when collapsed), by tier:
  - `error`: "Config error: N problem(s) in <files>. <blocks of the first
    error> are refused until it is fixed." The second sentence is left out
    when that `blocks` is `""` (the crash shape).
  - `stale`: "Config changed on disk: restart the backend to apply it."
  - `unknown`: "Config health unknown: <error or age reason>. Retrying every
    30 s."
  - `multiworker`: "The backend answers from several worker processes; each
    has its own config, and this check sees one of them."
  - `warning`: "Config warning: N unknown key(s)."
  - Followed by the other tiers' counts when present, e.g. "· also 2 stale,
    1 warning".
- A **Collapse / Show details** button (`aria-expanded`).
- **Detail** (expanded only): one list per non-empty kind, in the order
  errors, stale, warnings. Each line is `file · path: message`, and error lines
  add "Blocks: <blocks>" when `blocks` is not empty. Then the multi-worker line
  if set, then the restart info line if `restartedAt` is set ("Backend
  restarted at HH:MM:SS. Pages opened before then keep the IV and event
  thresholds they loaded until they are reopened."). Then **scope**:
  "Checked: …" (or "Checked: nothing, the health check itself failed" when
  `checked` is empty) and "Not checked: …", from the report. The `unknown` tier
  has no report, so its scope line reads "Nothing could be checked."
- "Last checked HH:MM:SS" from `fetchedAt` when there is one.

`warning` alone uses a thinner strip (smaller padding, `Text size={11}`), the
"quieter" style of decision 2. Colours use `color-mix` with
`--reject`/`--caution` over `--bg-surface`, and a 1 px border; no shadow.

**Frame grid** (`components/organisms/Frame.module.css`): a `banner` row is
added between `topbar` and the rest:

```
"topbar  topbar    topbar"
"banner  banner    banner"
"navrail workspace contextrail"
grid-template-rows: var(--frame-topbar-h) auto 1fr;
```

The banner element gets `grid-area: banner`. When it renders nothing, the
`auto` row is 0 px high and the layout is what it is today.

### 2.5 `components/molecules/ConfigHealthChip/` (new) in the TopBar

Rendered in `TopBar/index.tsx` between `<MarketClock />` and
`<TopBarActions />`; `.bar`'s `grid-template-columns` gains one `auto`. It
always renders one element, so the TopBar columns do not shift:

- `checking`: "Config: checking…", dim, not clickable.
- `clean`: "Config OK · N checks", pass tone. A click opens a popover with
  "Checked" (every `checked` entry), "Not checked" (every `not_checked` entry)
  and "Last checked HH:MM:SS". Escape and an outside click close it.
- Any other tier: the tier's short label ("Config error", "Restart needed",
  "Config unknown", "Several workers", "Config warning") in its tone. A click
  expands the banner (`setCollapsed(false, …)`) and moves focus to it.

It reads the same store and the same `tierOf`, through one shared hook
`useConfigHealthView()` (in `lib/configHealthStore.ts`), so the chip and the
banner can never disagree about the tier. The hook reads the 5 s `now` from
the store (the banner's tick writes `now` into the store) rather than keeping
its own clock. `useConfigHealthView()` passes the store's `now` to `tierOf`;
nothing in the view path calls `Date.now()`.

### 2.6 E2E fixtures

- `e2e/fixtures/api-mocks.ts` gains a `**/api/config/health` route answering a
  clean report (`ok: true`, the ten shipped `checked` names, the five
  `not_checked` lines, `pid: 4242`, empty lists). Specs that do not use the
  mocks and run without a backend will show the `unknown` strip; §3.4 runs the
  whole Playwright suite to find any spec that depended on the old grid.
- `e2e/fixtures/api-mocks-reject.ts` needs nothing: `setupRejectMocks`
  already calls `setupApiMocks`, so it inherits the clean route.

### 2.7 Records

- `CLAUDE.md` store table: a `configHealthStore.ts` row (poll state for the
  banner and chip, not persisted).
- `PROJECT_STATE.json`: phase `DOCC-5-TOPBAR-BANNER` with its probe flipped to
  present on `export function parseConfigHealth` in `frontend/lib/configHealth.ts`;
  YAML-CONFIG-INTEGRITY's probe flipped to present.

## 3. Tests

Fixture file `lib/testFixtures/configHealth.ts` (outside `__tests__`, as
DOCC-3 did): `CLEAN_REPORT` (the shipped check names, verbatim from
`config_health.py:59-70`, and the five `NOT_CHECKED` lines, verbatim from
`:78-84`), `ERROR_REPORT`, `STALE_REPORT`, `WARNING_REPORT`,
`CRASH_REPORT` (the `:253-260` shape). No production module may import it.

### 3.1 `lib/__tests__/configHealth.test.ts`

- P1: every fixture parses to itself.
- P2: refused, each with the path in the message: non-object; each required
  key missing in turn; `pid: 0`, `pid: 1.5`, `pid: "1"`; `checked: "x"`;
  `errors[0].blocks` missing; `stale[0].message: 3`.
- P3: `ok: true` with one error, and `ok: false` with three empty lists, are
  both refused ("contradicts").
- T1: `tierOf` walks rules 1-8, one case each, including rule 3 at
  `fetchedAt = now - 70 001` over a clean report (→ `unknown`) and
  `now - 70 000` (→ `clean`).
- T2: worst tier wins: errors + stale + warnings → `error`; stale + warnings
  + multiWorker → `stale`; warnings + multiWorker → `multiworker`.
- T3: `CRASH_REPORT` → `error`.
- T5 (round-1 G1): `status: 'loading'`, `report: null`, `error: 'x'` →
  `unknown`, not `checking`.
- T4: **no green without a report:** for every `status` with `report: null`,
  `tierOf` is never `clean`.
- F1: `fingerprintOf` is stable under reordering of findings, changes when a
  message changes, and is `'unknown'` for two different failure messages.

### 3.2 `lib/__tests__/configHealthStore.test.ts`

- S1: a good poll → `ready`, parsed report, pid recorded.
- S2: a rejection, and separately a malformed payload, → `failed`, `report:
  null`, the error text kept; a ready report before it is **cleared**.
- S3: race: A and B in flight, B resolves then A; B stands, success or failure
  of A.
- S4: the abort after 10 s (fake timers) → `failed` with the abort message.
- S5: pids A,A,B,B → `multiWorker` false, `restartedAt` set. A,B,A →
  `multiWorker` true. After ten more polls of B only → false again.
- S6: while loading after `ready`, the old report is still in hand.
- S8 (round-1 G2): a clean report with `fetchedAt` 70 001 ms before a
  `tick()` → the view's tier is `unknown`; before the `tick()` it was
  `clean`. A poll that starts after a failure leaves `error` set.
- S7: collapse: `setCollapsed(true, fp)`; the view is collapsed for `fp`, and
  expanded for any other fingerprint.

### 3.3 Components

`components/organisms/ConfigHealthBanner/__tests__/ConfigHealthBanner.test.tsx`
(api mocked, fake timers):

- B1: first render polls once; nothing is shown until it answers; a clean
  answer shows nothing.
- B2: each fixture tier shows its headline, the detail lists, "Blocks:" on
  error lines, and both scope lists; the error tier has `role="alert"`.
- B3: a 500 shows "Config health unknown" and the status in the text; the next
  good poll clears it.
- B3b (round-1 G1): after a 500, the next poll is left pending; the strip is
  still shown, and the chip does not read "checking".
- B4: 30 s ticks do not poll while `visibilityState` is `'hidden'`; a
  `visibilitychange` to visible polls at once; `focus` right after it does not
  poll again within 2 s.
- B5: collapse hides the detail and keeps the headline; a poll with a changed
  finding shows the detail again; the same finding keeps it collapsed.
- B6 (reworked, round-1 G2): one clean poll, then `visibilityState` mocked
  to `'hidden'` so no tick polls; the clock is advanced 75 s and then
  `visibilitychange` fires with the state back at `'visible'` and the poll
  mocked to hang. Before the abort fires, the `unknown` strip is shown with
  the age reason. This reaches `unknown` through rule 3, not rule 2.
- B7: unmount clears every interval and listener (no poll after unmount).

`components/molecules/ConfigHealthChip/__tests__/ConfigHealthChip.test.tsx`:

- C1: `checking` label before the first answer; never "OK".
- C2: clean → "Config OK · 10 checks"; the popover lists all ten checked and
  all five not-checked lines.
- C3: an error tier shows "Config error"; a click un-collapses the banner.
- C4: chip and banner agree on the tier for every fixture (one render of both).

Existing tests: `TopBar` and frame layout tests that snapshot or count TopBar
children are updated for the one new child, and nothing else.

### 3.4 E2E

`e2e/tests/docc5-config-health.spec.ts`:

- clean mock → chip reads "Config OK", no banner, on `/dashboard` and on
  `/screener/step-1-regime`;
- an error payload → the banner shows on both pages with the error text;
- a 500 → "Config health unknown".

Then the **whole** Playwright suite, and `npm run typecheck`, `npm run test`.

### 3.5 Mutations to run at code review

m1 drop the `ok` consistency check; m2 make rule 2 return `clean`; m3 drop
rule 3; m4 swap rules 4 and 5; m5 keep the old report on failure; m6 remove
the `my !== seq` guard; m7 compare pids with "any two distinct" instead of
"a return"; m8 poll while hidden; m9 fingerprint without messages; m10 chip
computing its own tier; m11 clear `error` when a poll starts; m12 call
`tick()` after `poll()` instead of before, or not at all, in the
visibility handler. Each must fail a test.

## 4. Out of scope

- Any backend change. Messages, the `not_checked` list and the staleness rules
  are DOCC-4's.
- Refreshing `eventThresholdsStore` and `ivThresholdsStore` on a backend
  restart. The restart line tells the user; the stores keep DOCC-3's
  fetch-on-mount behaviour.
- A reload or restart button (§9.2 of the old plan: no reload endpoint).
- Notifications (Gmail/Telegram) for config errors.
- DOCC-4's below-gate items: a save plus hand revert inside one poll can show
  green for that poll; `full_conviction_pct: 0` reads green.

## 5. Behaviour changes Kenneth should know about

1. Every page shows a banner under the TopBar whenever the config is not
   clean, including when the backend cannot be reached ("Config health
   unknown"). That includes local dev with the backend stopped.
2. The TopBar gains a chip. Green only after a validated clean report less than
   70 s old.
3. With `WEB_CONCURRENCY` above 1 the "restart" banner never clears. That is
   DOCC-4's rule, surfaced.
4. The app sends `GET /api/config/health` every 30 s from each visible tab.

## 6. Audit notes

**The gate for this slice.** The audit rule's gate is a wrong number in front
of a user or on a broker order, or corrupt persisted data. For a health banner
the equivalent is **a false green**: any path where the chip reads "Config OK",
or no banner is shown, while the last validated report had findings, was
older than 70 s, or there is no validated report at all. Also gate-level: a
lower tier hiding a higher one (stale shown while errors are present), and any
existing page broken by the grid change. Wording, style and test hygiene are
not findings.

Check in particular:

- that `tierOf` is the only tier decision, and the chip and banner both go
  through `useConfigHealthView`;
- the parser against `config_health.py:249-335`, field by field, including the
  crash shape;
- the race guard and the clear-on-failure;
- that the visibility gate cannot stop the poll in a visible tab (only
  `'hidden'` skips a tick);
- that the `auto` grid row really is 0 px when the banner renders nothing, and
  that no page relied on `grid-template-rows` having two rows.

## 7. Audit record

**Plan round 1 (2026-09-30): NOT CLEAN, 2 gate-level findings, both fixed
above.**
- G1: after a failure, the retry's `loading` state matched rule 1
  (`checking`), so the "unknown" strip vanished during every retry: up to
  10 s of every 30 s with a hung backend. Fixed: rule 1 also needs
  `error === null`, and a poll no longer clears `error` on start (T5, S8,
  B3b, m11).
- G2: §2.5 read `now` from the store, but §2.2's contract had no `now`, so
  rule 3 had no clock and a frozen green could stay. B6 reached `unknown`
  through rule 2 instead. Fixed: `now` + `tick()` in the store, the
  visibility and focus handlers tick before polling, and B6 now goes through
  rule 3 (S8, m12).

Round-1 items logged below the gate: the crash headline's empty subject
(fixed in passing, §2.4); the reject mocks already inherit the health route
(fixed in passing, §2.6); keep-alive can keep a multi-worker backend on one
pid for a tab (already in `NOT_CHECKED`); `ws-a`..`ws-e` specs will show the
unknown strip without a backend (the §3.4 full run covers them); after a
failed fetch a known error report shows as the caution `unknown` (decision 4).
