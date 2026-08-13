# Code Review Findings — Bamendjou

Audit date: 2026-08-13 (round 1), extended 2026-08-13 (round 2 — full-repo pass). Scope:
`frontend/`, `backend/`, root docs, and cross-checks against `CLAUDE.md`. Findings are grouped by
severity. File:line references are accurate as of this commit; re-verify before fixing if the
branch has moved on.

**Round 2 update:** Findings 1-3 below were independently re-verified by direct code inspection
(not just re-reported by an agent) — confirmed accurate as written. Round 2 extends coverage to
areas round 1 didn't touch: broker adapters, auto-trader, credential/websocket/migration/test
infra, the remaining app pages (dashboard/watchlist/calendar/alerts/analysis/chart/strategy-watch/
validation), e2e tests, `frontend/lib/api.ts`, and the rest of the docs tree (`llm-contexts/`,
`docs/mockup/`, `docs/superpowers/`, CI config, root `.md` files). New findings are numbered
continuing from round 1 and slotted into the same severity sections.

---

## Critical — financial correctness / risk control

### 1. "Max single position %" setting is never enforced
`backend/app/routers/risk_settings.py:118,142` persists the frontend's `maxSinglePositionPct`
into `risk_rules.yaml`'s `portfolio.max_single_position_pct` key. But the actual sizing gate used
by `auto_trader.py` — `check_position_risk()` in `backend/app/services/portfolio_risk.py:88` —
reads a **different** key, `max_single_trade_exposure_pct`, which has no settings-page UI at all
and is hardcoded at `0.05` in `risk_rules.yaml:4`. A user tightening or loosening the setting in
Settings has zero effect on real trade sizing/exposure enforcement. This is a silent risk-control
failure, not a display bug.

### 2. Closing a stock position shows realized P&L ~100x too large — FIXED
**Fix:** `ClosePositionDrawer` now branches on `positionMultiplier()` (exported from
`lib/risk.ts`, was previously module-private `_multiplier`) instead of hardcoding `* 100`. See
`SELL_CLOSE_SEMANTICS_PLAN.md` for the full fix (implemented together with findings #3 and #15,
which share a root cause). Covered by `ClosePositionDrawer/__tests__/ClosePositionDrawer.test.tsx`.

Original finding: `frontend/components/organisms/ClosePositionDrawer/index.tsx:34` computes
`realizedDollar = (exitPrice - entryPrice) * 100 * qty` unconditionally, assuming a 100-share
option contract. Every other P&L/exposure calculation in the app branches on
`position.contract.endsWith('|STOCK') ? 1 : 100` (`frontend/app/(frame)/portfolio/page.tsx:119,501`,
`frontend/app/(frame)/@contextRail/portfolio/page.tsx:15`, `frontend/lib/riskStore.ts:67`,
`frontend/lib/risk.ts:30-31`). Since `ClosePositionDrawer` is used for stock positions too
(`contract` = `"SYM|STOCK"`), the confirm dialog shows a wildly wrong number before the user
confirms the close.

### 3. Shorted stock positions are recorded as "Bullish" in the local portfolio — FIXED
**Fix:** `buildPaperStockPosition()` now takes a required `direction` parameter, threaded from
the real trade direction at all 4 call sites (3 pass through `c.direction`/`card.direction`; the
chart-click buy popover has no direction in scope by design and passes the literal `'Bullish'`,
since that entry point is always a long/buy). Covered by `lib/paperTrade.test.ts`.

Original finding: `frontend/lib/paperTrade.ts:29` — `buildPaperStockPosition()` hardcodes `direction: 'Bullish'`
regardless of the actual trade direction, even though the broker order sent from the same call
sites correctly does `action: c.direction === 'Bullish' ? 'BUY' : 'SELL'`
(`frontend/components/organisms/StockSendDialog/index.tsx:101`,
`frontend/components/organisms/StockPositionCard/index.tsx:189`). The mislabeled direction then
feeds `alertEngine.scanPortfolio()`'s direction-aware stop/target comparisons
(`frontend/lib/alertEngine.ts:49-90`) backwards for every short position.

### 15. Tradier and Tastytrade disagree on what `SELL` means — same request, opposite real-world trade — FIXED
**Fix:** every `BrokerOrder` now carries an explicit `effect: 'OPEN' | 'CLOSE'` field, decoupled
from `action`. Tradier and Tastytrade both now key their side/action mapping on
`(action, effect)` instead of guessing; Tradier's *stock* side also gained the same 4-way
treatment (`sell_short`/`buy_to_cover`), which turned out to need fixing too — its "no change,
auto-infers" assumption was verified false against Tradier's own API docs during planning. IBKR
and Alpaca are unchanged (they genuinely auto-infer open/close from account state). Full design,
3 rounds of adversarial review, and rationale in `SELL_CLOSE_SEMANTICS_PLAN.md`. Covered by new
tests in `test_tradier_paper.py` (7 new cases across stock + options), `test_tastytrade_paper.py`
(8-combination parametrized test + a live-bug regression test), and in `test_broker_router.py`:
missing-field schema validation, plus router-level `effect`-propagation tests through the real
HTTP route (added after a post-implementation adversarial audit proved via mutation testing that
the original schema-only tests would silently pass even if a route handler discarded the caller's
`effect` and hardcoded `"OPEN"` — the same class of bug as the original finding, one layer up).

Original finding: `backend/app/data/tradier_paper.py:19-23` maps `SELL` → `sell_to_open` ("the screener always
opens a new position"). `backend/app/data/tastytrade_paper.py:35-49` maps `SELL` →
`SELL_TO_CLOSE` (closes an existing long; fails if none exists). Both adapters are reachable with
an identical `{"action": "SELL", ...}` payload from `POST /broker/option-order`,
`POST /broker/stock-order` (`backend/app/routers/broker.py:16-34`), and `POST /auto-trade/arm`
(`backend/app/routers/auto_trade.py:15-25`) — broker selection is a plain string field with
nothing reconciling the two conventions. Routing a SELL to Tradier opens an unintended short
(real money exposure); routing the identical intent to Tastytrade throws instead of executing.
Confirmed by direct inspection of both files; `tests/test_broker_router.py` and
`tests/test_auto_trader.py` only exercise `SELL` against `ibkr_paper`, so this divergence has no
test coverage. This is the same class of bug as findings 1-3: a config/routing seam where one
side of an either/or path was never reconciled with the other.

---

## High

### 4. Blocking sync calls inside `async def` route handlers stall the event loop
- `backend/app/routers/contracts.py:80,83` — `get_contracts` (backs Step 6's contracts table)
  calls sync `fetch_option_chain(...)` / `fetch_price(...)` directly, even though the same file
  already imports and uses the async-safe `fetch_price_async`/`fetch_candles_async` elsewhere
  (lines 165, 295, 368). `fetch_option_chain` can invoke `fetch_iv_metrics_ibkr`
  (`backend/app/data/ibkr.py:262-303`), which does a hard blocking `time.sleep(1.5)` —
  explicitly documented at `ibkr.py:301-303` as needing a worker thread, not an async route.
- `backend/app/routers/watchlist.py:62-63` — `get_watchlist` calls sync `fetch_price`/
  `fetch_company_name` in a per-symbol loop.
- `backend/app/routers/regime.py:103,126` — same sync `fetch_price('VIX')` pattern.

Each of these stalls the single uvicorn event loop for the whole process — all concurrent scans,
websockets, and other requests — for up to several seconds per call. This is exactly the failure
mode `tastytrade_bridge.py` was built to avoid elsewhere; these three call sites just don't use
the async-safe path that already exists in `market.py`.

### 5. StepNavBar's REJECT gate reads a different field than CLAUDE.md documents
CLAUDE.md says: "`scanStore.regime` is set by Step 1 on mount and read by StepNavBar for the
REJECT gate." Actual code (`frontend/components/organisms/StepNavBar/index.tsx:25,43`) reads
`scanStore.combinedRegime`, a genuinely different value —  `regime` is the raw market-overall
status, `combinedRegime` is `alignmentVerdict(direction, descriptor)`
(`frontend/app/(frame)/screener/step-1-regime/page.tsx:85,89`). A developer trusting the doc
would edit the wrong field and silently break the REJECT confirmation overlay.

### 16. Calendar's "Today" can land on the wrong day for US-timezone users in the evening
`frontend/app/(frame)/calendar/page.tsx:20` — `const TODAY = new Date()` captures local
wall-clock time, but every comparison against it (`isoForUTC`, the month grid's `isToday` flag,
the "Today" nav button) treats it as UTC-anchored via `getUTCFullYear/Month/Date()`. For a US
Eastern-time user, once local time passes ~8pm ET the UTC calendar day has already rolled to
tomorrow, so the grid highlights tomorrow as "Today" and the "Today" button jumps a day ahead. A
second symptom: the selected-day header's `EventFlag` (line 185,
`Math.round((selectedDate.getTime() - TODAY.getTime()) / 86_400_000)`) can go negative for
genuinely-today events, silently hiding the flag (`EventFlag` returns `null` for `days < 0`,
`frontend/components/atoms/EventFlag/index.tsx:23`) while the event still shows in the list below.

### 17. Alerts page shows the wrong premium-stop percentage
`frontend/app/(frame)/alerts/page.tsx:43` — `ALERT_TYPE_LABELS.PREMIUM_STOP` is hardcoded to
`'Premium stop (–40%)'`, but the real default/configured threshold is 60%
(`frontend/lib/settingsStore.ts:379` → `premiumStopPct: 0.60`, mirrored in
`frontend/lib/alertEngine.ts:43`) and is user-adjustable in Settings. The label never reflects the
actual trigger threshold, misleading the user about when the alert fires — worse once a user
changes the setting away from the default, since the label doesn't update at all.

### 18. `/auto-trade/arm` has no quantity validation
`backend/app/routers/auto_trade.py:20` declares `quantity: int` with no `Field(ge=1)`, unlike the
equivalent fields in `broker.py:20,31` (`Field(..., ge=1)`). `AutoTradeService.arm()`
(`backend/app/services/auto_trader.py:139-148`) only validates `entry_premium > 0`, not quantity,
so an arm/fire cycle can submit a zero- or negative-quantity order straight to a broker adapter.

---

## Medium

### 6. Live strategy param falls outside its own WFO search grid
`backend/config/strategy_params.yaml:36` sets `pullback_ema.active.bearish.ema_period: 35`, but
line 42's `search.ema_period: [20, 50]` never includes 35. `walk_forward.py`'s
`_complexity_penalty` does `values.index(combo[key])` — so the walk-forward optimizer that's
supposed to keep this parameter honest can never reproduce or validate the value actually running
in production.

### 7. CLAUDE.md's Settings page section describes a UI that doesn't exist
CLAUDE.md (lines ~238-247) says the sub-nav is "Broker · Appearance · Score weights & parameters
· Alerts" with a 4-tab horizon strip storing `customW`/`customParams`. The actual sub-nav
(`frontend/app/(frame)/settings/page.tsx:28-37`) has nine sections (Appearance, Scan, Strategy
scan, Brokers, Risk, Regime, Notifications, Data, Strategy Tuning) — no "Score weights &
parameters" tab, no "Alerts" tab, and `customW`/`customParams` appear nowhere in `frontend/`.
Reads as a removed or never-shipped feature that was never pulled from the doc.

### 8. Strategy count undercounted in CLAUDE.md
CLAUDE.md says the Strategy picker offers 4 strategies and that `strategy_engine.py` has "Four
named signal functions." The actual picker
(`frontend/app/(frame)/screener/step-5-strategy/page.tsx:17-57`) lists six, and
`backend/app/services/strategy_engine.py` defines nine signal functions total, all wired into
`backend/app/routers/stock_scan.py:42-45,125-127`.

### 9. Zustand persisted storage key prefix is inconsistent
CLAUDE.md claims a single `'bamendjou:'` prefix. About half the stores use a colon
(`bamendjou:theme`, `bamendjou:alerts`, `bamendjou:scan-params`, …) and the other half use a
hyphen (`bamendjou-watchlist-v1`, `bamendjou-settings`, `bamendjou-portfolio-v1`,
`bamendjou-risk-v1`, `bamendjou-auto-trade`, `bamendjou-scan-store`, `bamendjou-alerts-v2`,
`bamendjou-audit-log`). No single convention actually holds today.

### 10. Primitive prop API in CLAUDE.md doesn't match the components
CLAUDE.md documents `Text size={11|12|13|14}`, `Data weight={400|500|600}`, and
`Title as="h1|h2|h3" size={18|20|24}`. Actual types
(`frontend/components/primitives/Text.tsx:13-14`, `Data.tsx:13-14`, `Title.tsx:10-11`) allow
`TextSize = 10|11|12|13|14|16`, `DataWeight = 400|500` only, and
`TitleSize = 20|24|32` with `as: 'h1'|'h2'|'span'|'div'`. `size={16}` is used extensively in real
code, so the doc's scale is stale.

### 19. Test suite defaults to the real local dev database — already causing confirmed pollution
`backend/tests/conftest.py:22` — `os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")`.
Any test that imports `app.main:app` without an explicit `get_db` override talks to the actual
local `dev.db` used by the running dev app, not an isolated test DB. This isn't hypothetical:
`backend/tests/test_portfolio_monitor.py:78-86` carries an `xfail` documenting that the assertion
"sees real leftover data" (a real position) because of exactly this gap. Any other test assuming
an empty/known DB state is at the same risk, and a buggy test could mutate real dev portfolio data.

### 20. Live-broker safety is an incomplete block-list, not a structural guarantee
`backend/app/services/broker_router.py:5` — `_LIVE_BROKERS = {"ibkr_live", "alpaca_live",
"tastytrade_live"}` omits `"tradier_live"`. Currently harmless only because
`build_router_from_credentials()` (lines 33-67) never registers a `tradier_live` adapter — but
the thing preventing live trading is "nobody wired it up yet," not a structural allow-list. If a
`TradierLiveAdapter` is added later without also updating this set in the same change, live
trading with real money silently activates. Should be inverted to an explicit allow-list of
paper-only broker keys instead of a block-list of live ones.

### 21. `ci.yml` never runs `npm run typecheck` — the documented pre-commit gate lives elsewhere
CLAUDE.md's dev workflow says `npm run typecheck` "must be clean before every commit."
`.github/workflows/ci.yml`'s frontend job runs only `npm run test -- --ci` and `npm run build`;
the actual `tsc --noEmit` step lives solely in the separate `playwright.yml` workflow, bundled in
with Playwright browser installs and `@smoke` e2e tests. `next build` does implicitly type-check
(no `ignoreBuildErrors` set), so type errors aren't entirely unguarded — but the documented gate
isn't literally present in `ci.yml`, and disabling/removing `playwright.yml` (which reads as "just
e2e tests") would silently drop the typecheck gate with nothing else calling it out.

### 22. Screener steps 4-7 e2e tests are permanently disabled with no explanation
`frontend/e2e/tests/screener-steps-4-7.spec.ts:5-31` — all 4 tests use `test.fixme()` with no
comment explaining why. Their locators (`frontend/e2e/pages/ScreenerPage.ts:103,113` —
`page.getByRole('table')` for both the ranking and contracts tables) look like they'd never match
the current div/grid-based table implementations, suggesting these are stale rather than
temporarily broken — but nothing documents that or tracks fixing/removing them.

### 23. Dashboard e2e test can never fail regardless of the actual regime banner
`frontend/e2e/pages/DashboardPage.ts:11` — `regimeBanner = page.getByRole('banner')` resolves to
the app's persistent `<header>` (`frontend/components/organisms/TopBar/index.tsx:89`, which
carries the implicit ARIA "banner" role), not the dashboard's own
`<section className={styles.regime}>` block (`frontend/app/(frame)/dashboard/page.tsx:162`).
Since TopBar renders on every page, `frontend/e2e/tests/dashboard.spec.ts:18-25`'s assertion can
never fail from a broken/missing regime section — it's effectively just checking page chrome
loaded.

---

## Low / cleanup

### 11. Stale `settingsStore.ts` header comment
`frontend/lib/settingsStore.ts:4` still says the store "Persists broker config,
alertDeduplicationHours, and IV thresholds," but IV thresholds were removed in the v18 migration
(`settingsStore.ts:336-339`) and now live in `ivThresholdsStore.ts`.

### 12. Hardcoded `#fff` bypasses the CSS-token-only rule
Five files hardcode `color: #fff` instead of a token: `NavItems.module.css:60`,
`StepNavBar.module.css:98`, `RunScanButton/index.module.css:128`,
`ConfirmDialog.module.css:56`, `AlertBadge.module.css:12`. Low functional impact but a direct,
repeated rule violation of the CLAUDE.md styling convention.

### 13. Redundant double-POST on options paper-order placement
`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:498,507` POSTs the new position via
`persistPosition(pos)`, then on success also calls `addPosition(pos)`, which independently POSTs
the same position again (`frontend/lib/portfolioStore.ts:311`). The second POST is swallowed as a
harmless 409 today, but it's a wasted request and a maintenance trap if duplicate-handling ever
changes.

### 14. Bare `except Exception: pass` worth a spot-check
Several sites (`backend/app/data/market.py:40-41,156-157,426-427,1054-1055,1113-1114`,
`backend/app/main.py:180-236`) swallow `Exception` broadly — mostly documented as deliberate
non-fatal fallbacks, but broad enough to also hide genuine programming errors (`AttributeError`,
`KeyError`) rather than just the intended I/O failures.

### 24. Auto-trade daily-loss blocks leave no audit trail
`backend/app/services/auto_trader.py:196-217` — a fire blocked by `_check_exposure` is recorded
to `AutoTradeState.history` with `status: "cap_blocked"` before re-raising. But
`_check_daily_loss(...)` (called unguarded at line 217, defined at 330-352) raises `RuntimeError`
directly with no surrounding try/except, so a fire blocked by the daily-loss circuit breaker
leaves zero trace in history even though the armed state was already cleared — an operator
checking `/auto-trade/status` after a blocked daily-loss fire sees nothing happened, not that a
trade was stopped.

### 25. `/ws/alerts` has no authentication
`backend/app/routers/ws_alerts.py:12-38` accepts any WebSocket connection and immediately
registers it for live portfolio-alert broadcast — no token/session check. Likely acceptable given
the single-user-local-machine assumption documented elsewhere (`credential_store.py:28-35`), but
there's no comment here acknowledging that same reasoning, so it reads as an oversight rather than
a deliberate call.

### 26. Credential file has no permission hardening
`backend/app/services/credential_store.py:71-79` writes `local_credentials.yaml` (plaintext
broker secrets, explicitly acknowledged at lines 28-35) via `os.replace` with no
`os.chmod(0o600)`, so the file inherits the process umask (often group/world-readable). Cheap
defense-in-depth that's currently missing.

### 27. `update_sp500_liquidity.py` overwrites production config with no backup or dry-run
`backend/scripts/update_sp500_liquidity.py:134-150` rewrites `backend/app/data/sp500.csv`
unconditionally. It warns on zero-liquidity symbols (line 142) but has no `--dry-run` or backup —
a bad yfinance batch (e.g. a transient outage returning mostly-empty `Close`/`Volume` series)
would still write a largely-zeroed `liquidity` column over the file that drives the sector heatmap
and universe filters.

### 28. Stale doc comment on `AlertConfig.keepAlertsDays`
`frontend/types/domain.ts:456` says "default 10" but the real default
(`frontend/lib/alertStore.ts:28` → `DEFAULT_CONFIG.keepAlertsDays: 30`) is 30.

### 29. Redundant duplicate PRD file at repo root
`temp_prd.md` is a byte-for-byte duplicate of
`PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md` (confirmed via
diff, zero differences, both 1050 lines) — dead weight that doubles the maintenance surface for
the same text.

---

## Documentation staleness (root-level docs, not CLAUDE.md)

- **`LLM_CONTEXT.md`** — presents itself as current ("read this file fully before touching any
  code") but claims "There is no backend yet. Everything runs on deterministic mocks" and "the
  project root only contains this file and CLAUDE.md," both long false. Also documents the
  opposite step order (`step-1-universe/step-2-direction/step-3-regime`) from CLAUDE.md's current
  `step-1-regime/step-2-universe/step-3-direction`, and references a `mocks/` folder and
  `frontend/styles/tokens.ts` that no longer exist. Unlike `PRODUCTION_READINESS_AUDIT.md`, which
  self-flags as historical, this one doesn't — an agent could read it instead of CLAUDE.md and be
  actively misled.
- **`docs/design/nextjs-implementation-plan.md`** and **`docs/design/bamendjou-design-spec.md`**
  — same stale step ordering and `/mocks` folder reference, no historical disclaimer.
- **`README.md`** — describes a root `config/` directory and a populated `tests/` scaffold that
  don't match the repo; calls the repo "the initial workspace."
- **`IMPLEMENTATION_PLAN.md`** — "Current state" table claims scoring/pricing/contract
  validation are "Not started," directly contradicted by CLAUDE.md's own pipeline description.
- **`PHASE_1_COMPLETION.md`** — "What remains" section claims `SendToBrokerDialog` "does not call
  any broker API," candle data is "currently seeded RNG," and the frontend still has `MOCK_*`
  imports to replace. All three are false today (live paper-broker adapters exist per CLAUDE.md's
  Integrations table; `frontend/lib/api.ts` has zero `MOCK_*` references). No superseded/archived
  marker, and its closing line ("Next: Backend integration / Phase 3 TBD") reads as current status.
- **`llm-contexts/01-backend-fastapi.md`** — presents itself as authoritative ("read every section
  before writing a single line of code") but describes a backend with no database, hardcoded
  fixture dicts, and fixtures sourced from `frontend/mocks/{watchlist,contracts,candles}.ts` —
  `frontend/mocks/` doesn't exist. Directly contradicts CLAUDE.md's SQLAlchemy v2 + Alembic +
  AsyncPG backend with real data adapters.
- **`llm-contexts/CONTEXT_FIX_STARTUP_AND_PERFORMANCE.md`** — describes a Windows dev setup
  (`F:\Git\GitHub\Trading assistant`, `start-backend.bat`/`start-frontend.bat`, entrypoint
  `backend\main.py`) that no longer exists; no `.bat` files or root `package.json` are in the
  repo, and the real entrypoint is `backend/app/main.py`.
- **`llm-contexts/04-execution-params.md`** still calls Direction+Horizon "Step 2," pre-dating the
  reorder documented in `llm-contexts/05-step-reorder.md` that moved it to Step 3 (matching
  CLAUDE.md's current `step-3-direction`) — the two files in the same directory contradict each
  other with no indication which is current.
- **`llm-contexts/`** (65 files) and **`docs/superpowers/`** (~90 files) are an undocumented,
  unindexed pile of point-in-time task/plan specs — CLAUDE.md never references either directory.
  Several present themselves as authoritative, dated-free "single source of truth" documents with
  no status header, so an agent landing on one at random has no signal it may be long superseded.
  Lower-confidence spot check: `docs/superpowers/plans/*` and `specs/*` reference component names
  that were never built (`BacktestReport/index.tsx`, `StrategyPicker/index.tsx`) and test files
  that don't exist (`test_edgar_mapping.py`, `test_fundamentals_gate.py`, others) — expected
  plan/implementation drift, not urgent, but adds to the same pile-of-stale-specs problem.
- **`docs/mockup/trading-workbench-mockup.html`** — a static HTML mockup predating the
  Options/Stocks/Pre-Breakout three-mode screener split; doesn't reference real file/component
  names so it isn't factually wrong, just a visually outdated design reference.
- Two files are non-authoritative content that happen to sit among project docs with nothing
  marking them as such: `llm-contexts/Bamendjou Stabilization Plan.md` (written as instructions
  for a different LLM, "DeepSeek") and
  `2026-06-02_How_To_Get_TradingView_Paid_Features_For_FREE_(Claude_Code_Is_Insane).md` (a YouTube
  transcript about Pine Script/TradingView — this repo doesn't use either).
- **`tests/` at repo root** is confirmed to be exactly a stub: one `tests/README.md` describing
  goals, zero actual test files. All real coverage lives in `backend/tests/` and
  `frontend/__tests__/`/`frontend/lib/__tests__/`, which is what CI actually runs.

---

## Verified as correct (no action needed)

- All ~20 Zustand stores listed in CLAUDE.md exist with matching fields (`screenerMode`,
  `confidenceGate`, `premiumStopPct`, etc.)
- All screener step folders `step-1-regime` through `step-7-trade-card`/`step-7-position-card`
  exist and match their described contents; `step-4-prebreakout` genuinely has no steps 5-7.
- `tastytrade_bridge.py`'s single-persistent-event-loop design is correct and consistent with
  `governor.py`'s process-wide lock.
- `scoring_rules.yaml` horizon weights all sum to 1.00; event-proximity windows match CLAUDE.md
  exactly (Swing reject <21d / caution <45d); `contract_rules.yaml` weights sum to 1.00;
  `fundamentals_gate` threshold directionality is correct for both bullish and bearish.
- All scheduled-job wiring in `main.py` matches the CLAUDE.md scheduler table.
- `reward_risk.py`, `entry_quality.py`, `walk_forward.py`, `signal_confidence.py`,
  `contract_validator.py` — no defects found.
- Alembic migration history (`backend/migrations/versions/`) has exactly one head, every migration
  has a real `downgrade()`, and the schema-drift fix migration matches current ORM models.
- Notification dispatch (`gmail.py`, `telegram.py`, `sent_log.py`, `alert_notifier.py`) — dedup
  logic and CRLF header-injection defenses are sound and tested; no plaintext-credential logging.
- `governor.py`'s token bucket / circuit breaker / symbol budget — no race found.
- All scheduled jobs match CLAUDE.md's descriptions and fail soft (logged warning, not a crashed
  startup) if registration fails.
- `frontend/lib/api.ts` — every endpoint call's URL/method matches its backend router; no
  mismatches found.
- `frontend/lib/alertEngine.ts`, `alertStore.ts`, `chartAlertStore.ts`, `strategyWatchStore.ts`,
  `performanceStore.ts`, `autoTradeStore.ts`, `universeStore.ts`, `structureStore.ts`,
  `eventThresholdsStore.ts`, `ivThresholdsStore.ts` — direction/sign comparisons, dedup, and
  Zustand immutability patterns all correct.
- Dependency/version claims in CLAUDE.md all confirmed accurate against `frontend/package.json`
  (Next 15.5.23, TypeScript 5.7, Zustand 5.0.2, lightweight-charts 5.0.0) and
  `backend/requirements.txt` (FastAPI, Pydantic v2, SQLAlchemy v2, AsyncPG, aiosqlite,
  pytest-asyncio) — no drift here.

---

## Suggested next step

Fix items 1-3 and 15 first (they affect real money/risk decisions — misapplied risk settings,
wrong P&L display, mislabeled short direction, and a broker-dependent SELL that either opens an
unintended short or throws). Then 4-5, 17-18, 20 (correctness/safety), then 21-23 (test/CI gaps),
then sweep the doc staleness (round 1 and round 2 sections) in one pass — the `llm-contexts/` and
`docs/superpowers/` piles in particular would benefit from either a top-level index noting which
files are current vs. historical, or archiving the superseded ones out of the main tree. Happy to
implement any subset on request.
