# Implementation Plan — Tier 2: Correctness Bugs (Frontend + Test/CI Infra)

Status: REVISED after adversarial review round 1. Two items had severity-5 findings requiring
substantial rewrites: item 5's proposed fix targeted a dead/empty `Base` class (there are 4
independent SQLAlchemy metadata registries in this codebase, not 1) and would have silently
created zero or partial tables while looking complete; item 7's proposed fix (add `role="table"`)
doesn't work because the pages being tested render an empty-state text message, not a table, when
no scan has run — the code path that would carry the new role never executes in these tests. Both
rewritten below. Item 2 and item 4 also had real scope gaps (a sibling timezone bug in
`riskStore.ts` affecting the daily-recommendation-limit reset; a third `direction: str` field in
the backend schema the original grep missed).

Scope: findings #5, #16, #17, #19, #21, #22, #23 from `CODE_REVIEW_FINDINGS.md`, plus one item
carried over from `SELL_CLOSE_SEMANTICS_PLAN.md`'s explicitly-deferred residual gaps (tightening
`PortfolioPosition.direction`'s backend type). Finding #9 (storage-key prefix inconsistency) is
**not** in this plan — see `PLAN_TIER4_DOCS.md` for why it's being treated as a doc fix rather
than a code change (renaming persisted keys risks silently wiping real users' local data).

---

## 1. `StepNavBar`'s REJECT gate field — CLAUDE.md doc bug, not a code bug (LOW effort, HIGH clarity)

**Re-verified:** `frontend/components/organisms/StepNavBar/index.tsx:25` reads
`useScanStore((s) => s.combinedRegime)`. CLAUDE.md claims it reads `scanStore.regime`. The code
is not wrong — `combinedRegime` (direction-aligned verdict) is almost certainly the *correct*
field for a REJECT gate that should consider the user's chosen direction, not just raw market
regime. This is purely a documentation error.

**Fix:** correct CLAUDE.md's line (in the "Zustand stores" section) to say `combinedRegime`
instead of `regime`, and briefly note what `regime` vs `combinedRegime` each represent (raw
market-overall status vs. `alignmentVerdict(direction, descriptor)`) so a future reader
understands why there are two similar fields. **No code change.** Bundled into
`PLAN_TIER4_DOCS.md`'s CLAUDE.md sweep — listed here only so it's not lost, not implemented twice.

---

## 2. Calendar "Today" timezone bug (MEDIUM — real, user-facing, evening-hours bug)

**Root cause (re-derived from current code):** `frontend/app/(frame)/calendar/page.tsx:20` —
`const TODAY = new Date();` captures the current instant. Every downstream comparison
(`isoForUTC(TODAY)` at lines 53/89, the "Today" button's anchor jump at line 149, the `EventFlag`
day-delta at line 185) extracts **UTC** calendar fields from that instant. For a US Eastern-time
user, UTC midnight falls at 8pm ET (or 7pm during EST) — after that time, `TODAY`'s UTC calendar
date is already tomorrow relative to the user's actual local calendar day.

The rest of the calendar (grid cell generation, `isoForUTC` on arbitrary dates) is internally
consistent UTC-based date arithmetic — that part isn't the bug. The bug is specifically that
`TODAY` is built from the live instant instead of from the user's *local* calendar day.

**Fix — minimal, targeted:**
```ts
// frontend/app/(frame)/calendar/page.tsx:20
const _now = new Date();
const TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()));
```
This makes `TODAY` a UTC-midnight-anchored `Date` whose UTC fields correctly reflect the user's
**local** calendar day. Every downstream consumer (`isoForUTC`, the grid's `isToday` comparison,
the "Today" button, the `EventFlag` delta) is unchanged — they all already treat `TODAY` as an
opaque UTC-denominated calendar-day value, which this fix makes actually true.

**Verification before committing:** timezone bugs are notoriously easy to get subtly wrong twice.
Before considering this fixed:
1. Confirm `selectedDate` (used in the `EventFlag` delta at line 185) is parsed the same
   UTC-midnight way — check how the `selected` ISO string state gets turned into a `Date` object
   for that comparison (grep for where `selectedDate` is derived from `selected`).
2. Write a test that mocks `Date` (via `jest.useFakeTimers().setSystemTime(...)`) to a known
   instant *after* 8pm ET / *before* UTC midnight (e.g. `2026-03-15T23:30:00-05:00`), renders the
   calendar, and asserts the "Today" cell's `iso` matches `2026-03-15`, not `2026-03-16`. This is
   the actual regression test that would have caught the original bug — add it even if no test
   file exists for this page yet.
3. Also test a timezone where the bug runs the *other* direction (UTC+ zones, where local
   midnight is ahead of UTC) to make sure the fix isn't accidentally ET-specific — it shouldn't
   be, since `Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate())` uses whatever the
   *local* getters return regardless of which side of UTC the timezone sits on, but verify this
   with an explicit test case (e.g. mock a UTC+9 environment or reason about it via `Intl`/
   `process.env.TZ` in the test setup) rather than assuming.

**Round 1 review found a sibling instance of this exact bug, in a higher-stakes location, that
this item did not originally cover — adding it here rather than letting it go undocumented:**
`frontend/lib/riskStore.ts:48,53` — `lastResetDate`/`today` are both derived via
`new Date().toISOString().split('T')[0]`, the same UTC-vs-local-midnight pattern, but this one
drives `incrementDaily()`'s **daily trade-recommendation counter reset** — an actual risk-limiting
mechanism, not a UI cosmetic. For an ET user active after 8pm, this resets the daily count hours
before their local midnight, silently granting extra daily recommendation slots early. Weaker
instances of the same pattern also appear in `frontend/lib/portfolioStore.ts:112` and
`frontend/lib/paperTrade.ts:26` (both used for `entryDate` defaults — lower stakes, a
cosmetic/record-keeping date being off by a few hours near midnight, not a limit-enforcement bug).

**Fix:** apply the same local-day-anchored pattern to `riskStore.ts`'s date derivation:
```ts
function localTodayIso(): string {
  const d = new Date();
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())).toISOString().split('T')[0];
}
```
(or equivalent — the point is deriving the ISO date string from local calendar fields, not from
`toISOString()`'s inherent UTC conversion of the live instant). Use this for both `lastResetDate`
and the `today` comparison in `incrementDaily()`. Leave `portfolioStore.ts`/`paperTrade.ts`'s
`entryDate` usages as a noted, explicitly out-of-scope lower-priority follow-up (same bug class,
much lower stakes — a trade's recorded entry date being off by a few hours near local midnight is
a record-keeping cosmetic, not a risk-limit bypass) rather than silently expanding this item's
scope further.

**Test plan:** a test that mocks the system time to just after 8pm ET, calls `incrementDaily()`
near the boundary, and confirms the daily count does NOT reset until actual local midnight.

---

## 3. Alerts page wrong premium-stop percentage label (LOW effort, real user-facing bug)

`frontend/app/(frame)/alerts/page.tsx:43` — `ALERT_TYPE_LABELS.PREMIUM_STOP` is a hardcoded string
`'Premium stop (–40%)'`. The real value is user-configurable
(`frontend/lib/settingsStore.ts` → `premiumStopPct`, default `0.60`).

**Fix:** make the label dynamic instead of a static map entry. `ALERT_TYPE_LABELS` is presumably
a `Record<AlertType, string>` used to render labels for several alert types, not just this one —
check its other entries before changing its type signature. Two viable approaches:
- **(A)** If `ALERT_TYPE_LABELS` is only consumed in places that have access to
  `useSettingsStore`, change the `PREMIUM_STOP` entry from a static string to a function
  `(pct: number) => string`, or special-case it at the render call site:
  `type === 'PREMIUM_STOP' ? \`Premium stop (–${(premiumStopPct * 100).toFixed(0)}%)\` : ALERT_TYPE_LABELS[type]`.
- **(B)** Simpler, if the label is rendered in only one or two places: read
  `useSettingsStore((s) => s.premiumStopPct)` at each render site and interpolate directly,
  leaving `ALERT_TYPE_LABELS.PREMIUM_STOP` as a fallback/generic `'Premium stop'` (no hardcoded
  percentage at all, since the percentage is genuinely dynamic per-user).

**Recommendation:** (B) — a label that can never go stale again beats one that's dynamically
computed from a value that could itself drift out of sync with a second source of truth. Grep all
usages of `ALERT_TYPE_LABELS.PREMIUM_STOP` (and `ALERT_TYPE_LABELS` generally) before deciding
final shape — there may be more than one render site.

**Test plan:** a test that sets a non-default `premiumStopPct` (e.g. `0.45`) in the settings
store, renders the alerts page, and asserts the displayed label reflects `45%`, not a hardcoded
`40%`.

---

## 4. Tighten `PortfolioPosition.direction` to `Literal["Bullish","Bearish"]` in backend schemas
   (LOW effort, closes a residual gap `SELL_CLOSE_SEMANTICS_PLAN.md` explicitly deferred)

**Round 1 review found a third plain-`str` field on the same underlying data that the original
grep missed — corrected below — and independently performed the frontend risk-check this item
asked for, finding it's low-risk (also noted below).**

`backend/app/schemas/__init__.py:592` (`PortfolioPositionCreate.direction: str`), `:627`
(`PortfolioPositionSchema.direction: str`), **and `:683` (`ClosedPositionSchema.direction: str`,
missed by the original grep)** are the three remaining plain-`str` typed direction fields. All
three are populated from the same underlying `PortfolioPositionModel.direction` column
(confirmed: `backend/app/services/portfolio_alert_monitor.py:104` reads that column for
`AlertItem.direction` too, though `AlertItem` itself is out of scope here — see note below). A
`Direction = Literal['Bullish', 'Bearish']` alias already exists (line 16) and is already used by
4 other fields in the same file (lines 157, 286, 448, 483).

**Fix — now three fields, not two:**
```python
# PortfolioPositionCreate, PortfolioPositionSchema, AND ClosedPositionSchema:
direction: Direction   # was: direction: str
```
Tightening only the open-position schemas while leaving `ClosedPositionSchema` permissive would
mean a legacy/bad-cased row 422s on `GET /api/portfolio` but reads back fine once closed — an
inconsistency the "consistency fix" would itself introduce if `ClosedPositionSchema` were missed.

**Scope note:** `AlertItem.direction` (line 320) and the continuous-scan-status `direction` field
(line 579) are also plain `str` and read from/relate to the same general concept, but are
populated from different contexts (alerts, scan status) with less certainty they're always exactly
`"Bullish"`/`"Bearish"` — leaving these two out of scope for this item rather than assuming they
behave identically to the portfolio-position trio; revisit separately if warranted.

**Risk check — round 1 review performed this independently, results below (the original plan only
asked for it, didn't do it):**
- **Frontend risk is low:** `PortfolioPosition.direction` is TS-typed as `Direction` end-to-end;
  the only loose spot is an `as Direction` cast in `portfolioStore.ts`'s `fromBackend()`, which is
  a read-side assertion (parsing what the backend already sent back), not something that
  constructs a bad value to send.
- **DB-backfill risk remains genuinely open** — neither this plan nor the review that checked it
  can inspect real production DB contents from the repo alone. If any already-persisted row has a
  different-cased or legacy `direction` value, tightening `PortfolioPositionSchema`/
  `ClosedPositionSchema` would make it fail to *read back*. Treat this as a real open question to
  resolve at implementation time (e.g. a one-off query against the actual dev/prod DB, if
  accessible, before shipping) — do not assume it's fine just because the frontend check came back
  clean.

**Test plan:** a test posting `direction: "bullish"` (wrong case) or `direction: "Long"` (wrong
value) to the portfolio-create endpoint now expects `422` instead of being silently accepted;
same for whatever endpoint returns `ClosedPositionSchema`.

---

## 5. Test suite defaults to the real local `dev.db` (HIGH effort, real isolation gap)

**Root cause (re-verified):** `backend/tests/conftest.py:22` —
`os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")`. The comment directly
above this line states the intent ("the suite can NEVER connect to or mutate the real Postgres dev
database") but the implementation only prevents connecting to *Postgres* — it still points at the
real local SQLite `dev.db` file used by the actually-running dev server. Any test that imports
`app.main:app` directly (not through this file's `client` fixture, which builds its own isolated
test app with `get_db` overridden) inherits this real, stateful database.

**Round 1 review found the original fix in this section was fundamentally broken and would have
silently created zero or partial tables. This section is rewritten from scratch with the
investigation actually performed, not just described as a TODO.**

**The codebase has FOUR independent SQLAlchemy declarative-base/metadata registries, not one:**
1. `app.models.base.Base` (`backend/app/models/base.py:7`) — **dead code.** Confirmed via
   whole-repo grep: nothing outside `migrations/env.py` imports it, and nothing registers a model
   against it. `Base.metadata.create_all()` against this class runs successfully and creates
   **zero tables** — a false-positive "it worked" signal. **Do not use this one; its name is a
   trap precisely because it's the most obvious thing to import.**
2. `app.database.Base` (`backend/app/database.py:22`, `declarative_base()`) — **this is the one
   actually used by every real model**: `PortfolioPositionModel`, `AlertRuleModel`,
   `AlertHistoryModel`, `ClosedPositionModel`, `EquitySnapshotModel`, `FundamentalsModel`,
   `DrawingModel`, `WatchedContractModel`, `WatchlistSymbolModel`,
   `PositionAlertHistoryModel` — confirmed via `grep -rn "from app.database import Base"`.
3. `ScanSessionBase` (`backend/app/models/scan_session.py:7`) — only `ScanSessionModel`; the only
   one the existing `client` fixture's `_create_tables()` currently covers.
4. `OhlcvBase` (`backend/app/models/ohlcv_daily.py:8`) — only `OhlcvDailyModel`.

Proof this isn't speculation: the repo's own `backend/migrations/env.py:30` already has to do
`target_metadata = [Base.metadata, DatabaseBase.metadata, ScanSessionBase.metadata,
OhlcvBase.metadata]` — Alembic itself had to name all four separately because they don't merge.
**Any fix must run `create_all()` against registries 2, 3, and 4 — three separate calls, not
one** — and must specifically avoid registry 1 despite it having the most obviously-correct name.

**Also corrected:** the original plan cited `test_broker_router.py`'s HTTP-level tests as an
example of a DB-touching test needing this fix — wrong; `backend/app/routers/broker.py` has no
`get_db`/`Session` usage at all, it isn't DB-backed. The actual `from app.main import app` test
files that ARE relevant (enumerated by round 1 review): `test_risk_limits_endpoint.py`,
`test_app.py`, `test_strategy_tuning_router.py`, `test_regime_direction.py`,
`test_symbol_info.py`, `test_schedule_endpoint.py`, `test_intraday_omm_fallback.py`,
`test_event_thresholds_endpoint.py`, `test_iv_thresholds_endpoint.py`.

**A correct reference pattern already exists in this codebase and should be generalized, not
reinvented:** `test_persistence.py`, `test_alert_notify_guard.py`, and `test_alerts.py` already
build their own in-memory engine, correctly import `Base` from `app.database` (registry 2, the
right one), and override `get_db` locally — entirely bypassing the module-level `DATABASE_URL`
and the shared `client` fixture. **Start from this pattern.** The fix here is less "invent a new
isolation mechanism" and more "make the already-correct pattern the default every test gets,
instead of something only 3 files opted into."

**Revised fix:**
1. Session-scoped autouse fixture in `conftest.py` that creates a fresh, isolated temp-file
   SQLite DB (a real file path, not `:memory:`, for safe behavior across pooled async
   connections) and runs `create_all()` against **registries 2, 3, and 4** (`app.database.Base`,
   `ScanSessionBase`, `OhlcvBase`) — three calls, explicitly skipping registry 1.
2. Swap `conftest.py:22`'s `DATABASE_URL` default to point at this new isolated file instead of
   `./dev.db`.
3. Confirm the existing `client` fixture's own `_create_tables()` (currently `ScanSessionBase`
   only) either gets folded into the same session-scoped setup, or is left alone if it already
   works correctly for what it covers — don't break what's already isolated correctly.
4. Run the **entire** backend suite after this change, not just the 9 files listed above — there
   may be others not yet identified that implicitly relied on `dev.db` having tables/data.

**Also revisit:** `backend/tests/test_portfolio_monitor.py`'s `xfail` (lines ~78-86) that
documents "sees real leftover data" — once the DB is genuinely isolated, this xfail should either
start passing (remove the marker, confirm clean) or, if it still fails for an unrelated reason,
needs its reason updated to reflect the real cause.

**Test plan:** run the full backend suite twice in a row, confirm identical results both times
(proving no cross-run state leakage via the temp file); add a test that writes a row in one test
function and asserts a different test function doesn't see it (proving per-test isolation, not
just proving tables exist); specifically re-run each of the 9 named `app.main:app` test files
individually and confirm each still passes with real tables now present instead of accidentally
inherited ones.

**Risk flag, still valid and now more specific:** this remains the highest-effort, highest-blast
-radius item in this plan. The original "just create_all on Base" framing would have looked like a
complete fix while silently doing nothing (registry 1) or doing a third of the job (forgetting
registries 3/4) — implement this one in isolation, run the *entire* backend suite immediately
after, and treat any new failure as a real signal, not noise. Given the severity of getting this
wrong undetected, consider having a second person (or a fresh review pass) specifically re-verify
the `create_all()` calls actually target the right 3 registries before merging, rather than
trusting a green test run alone — a `no such table` error would surface loudly, but a registry
that creates the WRONG empty set of tables in a way that happens not to be hit by any current test
would not.

---

## 6. `ci.yml` never runs `npm run typecheck` (LOW effort)

`.github/workflows/ci.yml`'s `frontend` job runs `npm run test -- --ci` and `npm run build` only.
The `tsc --noEmit` step lives solely in `.github/workflows/playwright.yml`.

**Fix:** add a typecheck step to `ci.yml`'s `frontend` job, matching that job's own existing
per-step style (each step does its own `cd frontend && ...`; round 1 review noted
`playwright.yml`'s equivalent step is bare `npm run typecheck` under a job-level
`working-directory: ./frontend` default, so "mirroring it exactly" isn't quite accurate — the
snippet below is correct for `ci.yml`'s actual established pattern, not a literal copy of
`playwright.yml`'s):
```yaml
      - name: Run typecheck
        run: |
          cd frontend
          npm run typecheck
```
Insert it before the `npm run test` step (fail fast on type errors before running the slower test
suite). This makes `ci.yml` — the workflow that actually gates every push/PR to `main` — self
-sufficient for the documented pre-commit bar, independent of whether `playwright.yml` stays
enabled.

**No test needed** — this is CI config, verified by the next real PR/push triggering it
successfully (and by deliberately introducing a type error locally and running `npm run typecheck`
to confirm it would be caught, which is just re-confirming the command works, not new coverage).

---

## 7. Screener steps 4-7 e2e tests permanently `test.fixme()`'d (MEDIUM effort)

**Round 1 review found the original fix for steps 4/6 does not work, and that steps 5/7 were
wrongly punted on when they're actually trivially fixable. This section is rewritten.**

**Steps 5 and 7 — round 1 review confirmed these ARE already correctly matchable, no punt
needed:**
- `step-5-vol-events/page.tsx:91-99` renders a table-header row containing the literal text
  "IV RANK" **unconditionally**, regardless of candidate count. `screener.ivSection`'s regex
  (`/iv rank|implied volatility/i`) matches this every time.
- `step-7-trade-card/page.tsx:636-638` renders `{cards.length === 0 && <Text>Run a scan to
  generate trade cards.</Text>}`, and `cards` defaults to `[]` on fresh mount — this matches
  `screener.tradeCardEmptyState`'s regex (`/no trade cards|empty|run a scan/i`) directly.
**Fix: simply remove `test.fixme` → `test` for these two, no application code changes needed.**
The original plan's "needs investigation" framing for these two was an unforced punt — the answer
was verifiable directly from the files already on disk.

**Steps 4 and 6 — the original fix (`role="table"`) does NOT work, for a reason the original plan
never traced:** both pages gate their table markup behind a candidates-empty check that returns
*before* the table renders at all:
- `step-4-ranking/page.tsx:176-189` — `if (!selected) { ... return <Text>Run a scan to see ranked
  candidates.</Text> }`, which fires before the `tableHeader`/`tableBody` divs (lines 231, 242)
  are ever reached.
- `step-6-contracts/page.tsx:175-179` — even more directly:
  `{candidates.length === 0 && <Text>Run a scan to see contracts.</Text>}` /
  `{candidates.length > 0 && (...the actual table markup...)}`.

`ScreenerPage.goto(step)` navigates straight to the URL with no scan run and no seeded state
(confirmed: no `page.addInitScript`/localStorage seeding, no mocked scan trigger) — so both tests
run in exactly the empty-candidates state, where **no table-shaped DOM renders at all**, just a
plain "Run a scan..." text message. Adding `role="table"` to markup inside a branch that never
executes in this test's actual state does nothing; the tests would still time out waiting for a
locator that never appears.

**Corrected fix — align the test's assertion with what the app actually, correctly does in this
state, rather than trying to force different application behavior:** the test names themselves
("loads without crash, empty table expected") show the original intent was to smoke-test that the
page loads without crashing in the no-data state — which the "Run a scan..." message proves just
as well as an empty table would, since there IS no concept of an "empty table" in this app; the
empty state is a text message, by design, on every step. Rewrite the two assertions to match:
```ts
// step 4
await expect(page).toHaveURL(/step-4-ranking/);
await expect(page.getByText(/run a scan to see ranked candidates/i)).toBeVisible();

// step 6
await expect(page).toHaveURL(/step-6-contracts/);
await expect(page.getByText(/run a scan to see contracts/i)).toBeVisible();
```
This directly replaces the now-provably-wrong `rankingTable`/`contractsTable`
`getByRole('table')` locators for these two specific tests. **Separately, and still worth doing
as a real accessibility improvement** (not because it fixes these tests, since the round 1 review
showed it doesn't): add `role="table"` to the header+body grid containers in both pages for when
they DO render with real candidate data — useful for screen readers and for any future e2e test
that actually seeds scan data before asserting on the table. Keep this as a separate, smaller
accessibility commit, not conflated with the test fix above.

**Test plan:** after rewriting the two assertions, remove `test.fixme` → `test` for all 4 tests
(steps 4, 5, 6, 7), run all 4 against a local dev server per CLAUDE.md's dev workflow, confirm
they actually pass — not just that they no longer time out for a different reason.

---

## 8. Dashboard e2e test can never fail (LOW-MEDIUM effort)

**Root cause, confirmed:** `frontend/e2e/pages/DashboardPage.ts:11` —
`regimeBanner = page.getByRole('banner')` resolves to the app's persistent `<header>`
(`TopBar/index.tsx`, which carries the implicit ARIA "banner" landmark role since it's a page-level
`<header>`), not the dashboard's own regime section
(`frontend/app/(frame)/dashboard/page.tsx:162` — `<section className={\`${styles.regime} ...\`}>`,
which currently has no ARIA role or accessible name at all).

**Fix, mirroring the same pattern used for `watchlistSection`/`portfolioSection`/`alertsSection`
in the same file (all use `getByRole('region', { name: /.../i })`):**
1. Add an accessible role + label to the dashboard's regime section:
   `<section role="region" aria-label="Market regime" className={...}>`.
2. Update `DashboardPage.ts`:
   `regimeBanner` → rename to `regimeSection` (the old name is misleading regardless of the bug —
   it was never actually a "banner"), locator becomes
   `page.getByRole('region', { name: /market regime/i })`.
3. Update the one call site in `dashboard.spec.ts` (`renders regime banner with status badge`)
   to use the renamed property.

**Test plan:** after the fix, verify the test can actually fail — temporarily rename the section's
`aria-label` in a scratch edit, confirm the test fails, then revert. This is the direct proof the
original bug (a test that structurally cannot fail) is gone; don't skip this verification step
just because the "happy path" passes, since a passing happy path is exactly what the original,
broken test also showed.

---

## Sequencing

1. #3 (alerts label) and #6 (CI typecheck) first — smallest, most self-contained, zero
   investigation needed beyond what's already done above.
2. #8 (dashboard e2e) and #7 (screener e2e, now all 4 steps since 5/7 need no investigation and
   4/6 have a corrected fix) — moderate, self-contained frontend/test changes.
3. #2 (calendar timezone, now including the `riskStore.ts` sibling fix) — moderate, needs the
   fake-timer tests to be trustworthy for both the calendar and the daily-counter-reset cases.
4. #5 (test DB isolation) — do this **before** #4, not after. Round 1 review found #4's own test
   plan (a 422 test against `/api/portfolio`) needs a real DB-backed test client with the actual
   portfolio router mounted — either `test_persistence.py`'s existing correct local pattern, or
   the isolated default this item establishes. Sequencing #5 before #4 means #4's test has a
   trustworthy home to land in rather than discovering the gap mid-implementation. This reorders
   #5 earlier than the original draft's "do last" — still treat it as the highest-risk item and
   run the full suite immediately after, but "last" was based on an "it's just risky, minimize
   blast radius by doing it in isolation at the end" framing that didn't account for #4 depending
   on it.
5. #4 (Direction Literal, now 3 fields) — after #5, using its isolated DB setup or
   `test_persistence.py`'s existing pattern for the new negative-case tests.
6. #1 — no code change, folded into `PLAN_TIER4_DOCS.md`.
