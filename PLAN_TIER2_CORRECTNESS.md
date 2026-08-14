# Implementation Plan — Tier 2: Correctness Bugs (Frontend + Test/CI Infra)

Status: DRAFT — pending adversarial review.

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

`backend/app/schemas/__init__.py:592` (`PortfolioPositionCreate.direction: str`) and `:627`
(`PortfolioPositionSchema.direction: str`) are the two remaining plain-`str` typed direction
fields; a `Direction = Literal['Bullish', 'Bearish']` alias already exists (line 16) and is
already used by 4 other fields in the same file (lines 157, 286, 448, 483) — this is a two-line
consistency fix, not new design work.

**Fix:**
```python
# both PortfolioPositionCreate and PortfolioPositionSchema:
direction: Direction   # was: direction: str
```

**Risk check before committing:** confirm no existing caller ever sends a `direction` value other
than exactly `"Bullish"`/`"Bearish"` (case-sensitive) through either of these two schemas — a
stricter type will reject anything else with a 422 where it previously silently accepted it.
Grep `frontend/lib/api.ts`, `frontend/lib/portfolioStore.ts`, and any script/fixture that posts to
`/api/portfolio` for the literal strings sent. Also check whether any already-persisted DB rows
could have a different-cased or legacy value that would now fail to *read back* via
`PortfolioPositionSchema` (if so, this becomes a migration/backfill question, not just a type
tightening — investigate before assuming this is purely additive).

**Test plan:** a test posting `direction: "bullish"` (wrong case) or `direction: "Long"` (wrong
value) to the portfolio-create endpoint now expects `422` instead of being silently accepted.

---

## 5. Test suite defaults to the real local `dev.db` (MEDIUM-HIGH effort, real isolation gap)

**Root cause (re-verified):** `backend/tests/conftest.py:22` —
`os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")`. The comment directly
above this line states the intent ("the suite can NEVER connect to or mutate the real Postgres dev
database") but the implementation only prevents connecting to *Postgres* — it still points at the
real local SQLite `dev.db` file used by the actually-running dev server. Any test that imports
`app.main:app` directly (not through this file's `client` fixture, which builds its own isolated
test app with `get_db` overridden) inherits this real, stateful database.

The `client` fixture's own isolated in-memory DB (`_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"`,
lines ~140-160) only creates tables for `ScanSessionBase.metadata` — not necessarily every model
reachable via `app.main`'s real `get_db` path (e.g. `PortfolioPositionModel`). This means a naive
swap of the module-level `DATABASE_URL` default to a fresh empty DB could break any test that
currently (accidentally) relies on tables/data already present in the real `dev.db`.

**This needs investigation before a fix is written, not just a one-line env var change:**
1. Enumerate every SQLAlchemy `Base`/metadata class in `backend/app/models/` and confirm which
   ones' tables are and aren't created by the existing `_create_tables()` fixture.
2. Enumerate every test file that does `from app.main import app` (not via the `client` fixture)
   and check whether any of them touch DB-backed endpoints (portfolio, risk settings, anything
   using `get_db`) — `test_broker_router.py`'s HTTP-level tests are one example; check for others.
3. Decide the isolation mechanism: a dedicated temp-file SQLite DB (safer for async connection
   pooling than `:memory:`, which doesn't share state across pooled connections by default) that
   gets its schema created via `Base.metadata.create_all` (covering *all* models, not just
   `ScanSessionBase`) in a session-scoped autouse fixture, deleted/recreated at the start of each
   test session.

**Fix (pending step 3's outcome, but the shape is clear):**
```python
import tempfile
_test_db_path = os.path.join(tempfile.gettempdir(), "bamendjou_backend_tests.db")
if os.path.exists(_test_db_path):
    os.remove(_test_db_path)  # fresh DB every test-session start
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_test_db_path}")
```
plus a session-scoped autouse fixture that runs `Base.metadata.create_all` (the *real* app's
`Base`, covering every model, not just `ScanSessionBase`) against this new default DB, so
`app.main:app`'s real `get_db` path has working tables for any test that hits it directly.

**Also revisit:** `backend/tests/test_portfolio_monitor.py`'s `xfail` (lines ~78-86) that
documents "sees real leftover data" — once the DB is genuinely isolated, this xfail should either
start passing (in which case remove the `xfail` marker and confirm it passes cleanly) or, if it
still fails for an unrelated reason, needs its xfail reason updated to reflect the real cause.

**Test plan:** after the fix, run the full backend suite twice in a row and confirm identical
results both times (proving no test leaks state into a shared file); also add an explicit test
that writes a row via one test function and asserts a *different* test function doesn't see it
(proving isolation, not just proving tables exist).

**Risk flag for the adversarial reviewer:** this is the highest-effort, highest-blast-radius item
in this plan — a wrong DB isolation change could turn currently-passing tests into failures for
reasons unrelated to this fix (missing tables, missing seed data some test implicitly relied on).
Recommend implementing this one in isolation, running the *entire* backend suite immediately
after, and treating any new failure as a signal to investigate before assuming it's unrelated
flakiness.

---

## 6. `ci.yml` never runs `npm run typecheck` (LOW effort)

`.github/workflows/ci.yml`'s `frontend` job runs `npm run test -- --ci` and `npm run build` only.
The `tsc --noEmit` step lives solely in `.github/workflows/playwright.yml`.

**Fix:** add a typecheck step to `ci.yml`'s `frontend` job, mirroring `playwright.yml`'s existing
step exactly:
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

## 7. Screener steps 4-7 e2e tests permanently `test.fixme()`'d (MEDIUM effort — partial fix,
   partial investigation)

**Root cause, confirmed for steps 4 and 6:** `frontend/e2e/pages/ScreenerPage.ts:103,113` —
`rankingTable`/`contractsTable` locators use `page.getByRole('table')`. Confirmed via direct
inspection: neither `step-4-ranking/page.tsx` nor `step-6-contracts/page.tsx` render an actual
`<table>` element or anything with `role="table"` — both use div/grid-based layouts
(`styles.tableHeader`, `styles.tableBody`). The locator can never match; that's why these were
presumably fixme'd rather than actually broken by application logic.

**Fix for steps 4 and 6 — add the ARIA role that's missing, don't weaken the test:**
Add `role="table"` to the outer container div wrapping the header+body grid in both
`step-4-ranking/page.tsx` and `step-6-contracts/page.tsx` (the element currently just has a plain
`className`). This is a real accessibility improvement (screen readers currently have no signal
these grids are tabular data) as well as the test fix — keeping `ScreenerPage.ts`'s
`getByRole('table')` locator unchanged and correct, rather than replacing it with a brittle
CSS-class-based query. Consider also adding `role="row"`/`role="columnheader"`/`role="cell"` to
the header/row-level elements for a more complete ARIA grid if the effort is small, but
`role="table"` on the container is the minimum needed to make the existing locator pass.

**Steps 5 and 7 — needs investigation before claiming a fix:** `screener.ivSection` and
`screener.tradeCardEmptyState` locators (`ScreenerPage.ts`, exact lines not yet checked in this
plan) haven't been verified against the current `step-5-vol-events` and `step-7-trade-card`
component trees. Before removing `test.fixme()` from those two tests specifically, check whether
their locators have the same "never matches" problem or a different one (e.g., the empty-state
text changed, the section needs a real scan to render). Do not blanket-remove all 4 `fixme()`
calls — only the 2 (steps 4, 6) confirmed fixable by this plan; leave 5 and 7 fixme'd with an
inline comment explaining what's still unverified, or investigate and fix those too if time
allows within the same implementation pass.

**Test plan:** after adding the ARIA roles, remove `test.fixme` → `test` for the steps-4 and
steps-6 cases specifically, run them against a local dev server (per CLAUDE.md's dev workflow) to
confirm they actually pass, not just that they no longer throw a "locator never resolves" timeout
for a different reason.

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
2. #4 (Direction Literal) — small, but do the risk-check grep first.
3. #2 (calendar timezone) — moderate, needs the fake-timer test to be trustworthy.
4. #8 (dashboard e2e) — moderate, needs the "can it actually fail" verification.
5. #7 (screener e2e, steps 4/6 only unless 5/7 get investigated too) — moderate.
6. #5 — no code change, folded into `PLAN_TIER4_DOCS.md`.
7. #19 (test DB isolation) — last, highest effort/risk, run full suite immediately after and
   treat any new failure as a real signal, not noise.
