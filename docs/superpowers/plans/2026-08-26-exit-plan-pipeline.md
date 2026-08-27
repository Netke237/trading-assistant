# Exit-Plan Pipeline & Risk Enhancements Implementation Plan

> **Status:** Accepted 2026-08-26. Nothing implemented yet — this session was planning-only (extensive back-and-forth with the user, including a `/grill-me` pass, to converge the design before any code was touched). Whoever picks this up should implement task-by-task using the checkboxes below, running `K-adversarial-audit-loop` (audit-only mode) at each ✅ checkpoint, not just at the end — per explicit user instruction.

**Goal:** Replace the TradeCard/Portfolio "Set the profit/target" mechanism's ad-hoc pieces (fixed-% invalidation, one arithmetic TP ladder, no dollar-loss awareness, no per-position alert control) with one coherent, structurally-grounded exit-plan pipeline, plus the risk-sizing and alerting features that depend on it.

**Architecture:** One new backend orchestration module (`backend/app/scoring/exit_plan.py`) composing existing, already-verified building blocks — `structural_stop.py`'s order-block/swing detection, `first_passage.py`'s Monte Carlo engine, `reward_risk.py`'s option repricing chain — rather than duplicating any of them. Everything new is **additive**: today's Sell-to-Close ladder and today's Monte Carlo %-based "Estimate" flow are untouched; the new pipeline's outputs are new entries alongside them in a per-position "active TP method" selector, surfaced on both the pre-trade TradeCard and the post-trade Portfolio editor.

**Tech Stack:** Next.js 15/TypeScript (strict) frontend, FastAPI/Pydantic v2/SQLAlchemy v2+Alembic backend, per repo `CLAUDE.md`.

---

## Context

The user's original "profit target pipeline" idea (structural invalidation → ATR floor → RR-derived target → probability/timing → alerting → display) was refined over several rounds of Q&A into a fully-specified algorithm — see "The exit-plan algorithm" below. Two rounds of codebase research (this session) established what already exists (`find_structural_stop`, the Monte Carlo `first_passage` engine, the option repricing chain, the alert-type enum) versus what's genuinely new (ATR-floor stop widening, structural target snapping, the composite quality flag, dollar-loss sizing, per-position alert overrides). Reuse existing patterns everywhere one exists; only the pipeline orchestration itself is new logic.

The user runs a ~4000 EUR account (displayed as USD `$` in this app — no currency change in scope) and wants to risk 100–200 EUR (~2.5–5%) per trade, against structurally-justified stops and targets rather than arbitrary percentages.

## The exit-plan algorithm (Feature B, the centerpiece)

1. **Final stop** = the wider of (a) the existing structural stop (`find_structural_stop`) and (b) an ATR floor (`atr_stop_multiplier × ATR(14)`, default multiplier **2.0**, YAML-editable). If structural already clears the floor unassisted, tag `stop_source: structural` (the "best case" — a real technical level that also happens to have enough breathing room). If it's tighter than the floor, widen it out and tag `stop_source: atr_widened`.
2. **Target rows**, one per configured R:R ratio (default **both 2.0 and 3.0**, shown as two independent rows, not a single pick): `arithmetic_tp = entry ± rr_ratio × final_stop_distance`. Search for a real structural level ahead of entry in the trade direction (`find_structural_target` — new, a direction-flipped mirror of `find_structural_stop`, reusing the same `detect_order_blocks`/`find_swings` calls); if it falls within an ATR-relative snap distance (`snap_atr_multiplier × ATR`, default **0.3**, YAML-editable — deliberately ATR-relative, not a flat dollar figure, since a flat number is wrong at both ends of a universe spanning $25 to $600+ stocks) of the arithmetic TP, snap to it (`tp_source: structural_snap`) and report both numbers; otherwise the arithmetic price stands (`tp_source: arithmetic`).
3. Reprice the final TP (and final stop) to an approximate contract price via the existing repricing chain (Heston → BS-with-derived-IV → delta-approx fallback), and run the final TP through the existing Monte Carlo `first_passage` engine for probability + expected days.
4. **Composite quality flag**, per row: ✅ good setup when `stop_source == structural` (no ATR-widening needed) **and** the TP sits at-or-before the next real structural level in the trade's direction (trivially true when `tp_source == structural_snap`). Otherwise flag which condition failed.

## Decisions locked in (do not re-litigate during implementation)

- Max-loss-per-trade is **warning-only**, never auto-clamps contract count.
- Loss/max-loss basis uses whatever the exit-plan pipeline resolves as the **final stop** — no separate "structural vs manual" ambiguity.
- Per-trade override accepts **either a fixed € amount or a percent** (one field, `{mode, value}`), toggle in the UI; global YAML default is a percent of `portfolioValue` (**3.75%**, editable).
- `portfolioValue` stays a **static, manually-edited** number (no auto-tracking from realized/open P&L) — add a "last updated" staleness nudge near the Settings field.
- Currency stays **USD `$`** display — no EUR support added in this pass.
- Max-loss warning surfaces at **both** TradeCard (pre-trade) and Portfolio (open position) — inline badge only at Portfolio time (nothing is being submitted there, so no confirmation gate needed), two-click override at TradeCard time (reuses `SendToBrokerDialog`'s existing soft-reason pattern).
- **One active TP method per position** drives that position's `TP_HIT` alert — methods: `ladder | monte_carlo | exit_plan_2r | exit_plan_3r`. Not independent alerts per method.
- Per-position alert-type overrides: `absent key = inherit global`, explicit `true`/`false` wins when present. Implementing this correctly also fixes a real pre-existing bug — global `enabledTypes` today only gates outbound email/Telegram, never in-app toasts — **bundle that fix in**, a deliberate, locked-in behavior change.
- `PricingMethod.DELTA_APPROX`'s display string is a confirmed bug (`backend/app/schemas/__init__.py:350` literally equals `"BS repriced (IV-derived)"`) — split into three honest labels: Heston repriced / BS repriced (IV-derived) / Delta approximation. `_bs_reprice_or_delta_approx` (`reward_risk.py:37-59`) already knows internally which path it took; surface that instead of discarding it.
- The approx contract price shown for stop/target levels is **persisted** (not recomputed on every render), shown on **both** TradeCard and Portfolio editor, for **both** the stop and target sides — never wired into alert-trigger logic (alerts stay keyed on stock price).
- Monte Carlo wiring into the Portfolio editor (was scoped "options-only v1") covers **both options and stock positions** — includes building the missing buy-time snapshot capture for the stock buy flow (mirrors `tradeCardSnapshotOf` in `step-7-trade-card/page.tsx:60-71`, currently absent from the stock position flow).
- Adversarial audit (`K-adversarial-audit-loop`, audit-only mode) runs at **every** checkpoint below, not just at the end.

---

## Feature B — Exit-plan pipeline

- [x] `backend/app/scoring/exit_plan.py`: `compute_final_stop(candles, direction, entry_price, atr, atr_multiplier)` — implements algorithm step 1 above, calling existing `find_structural_stop` (`structural_stop.py`).
- [x] New YAML: `exit_plan.stop.atr_multiplier: 2.0` (`backend/config/risk_rules.yaml`).
- [x] New function `find_structural_target(candles, direction, entry_price)` in `structural_stop.py` — direction-flipped mirror of `find_structural_stop`, reusing `detect_order_blocks`/`find_swings` from `market_structure.py`. Reuses the `StructuralStop` dataclass unchanged. (Implemented as a one-line delegation to `find_structural_stop` with direction flipped — a bearish-trade stop search IS a bullish-trade target search, and vice versa; see the function's docstring.)
- [x] `exit_plan.py`: `compute_target_row(candles, direction, entry_price, final_stop, atr, rr_ratio, snap_atr_multiplier)` — implements algorithm step 2, one call per ratio in new YAML `exit_plan.target.rr_ratios: [2.0, 3.0]` and `exit_plan.target.structural_snap.atr_multiplier: 0.3`.
- [x] Wire in existing repricing chain + `first_passage`'s `estimate_first_passage` for algorithm step 3 (contract price + probability/expected days on the final TP).
- [x] Composite quality flag per row (algorithm step 4).
- [x] New endpoint `POST /api/contracts/exit-plan` (`contracts.py`) + new Pydantic schemas (`ExitPlanResponse`, `ExitPlanTargetRowOut`, `ExitPlanStopOut`) returning stop + both target rows + ATR(14) at the top level.
- [x] Frontend: one new "Compute Exit Plan" button (manual, deliberate-click — same propose-then-confirm pattern as today's "Check structure") in `TradeCard/index.tsx`'s Exit Plan section **and** the Portfolio `EditDrawer`, rendering both RR rows with stock price, contract price, source tags, probability, expected days, and the quality badge. (Portfolio editor: options-only, gated on `!contract.endsWith('|STOCK')` — the repricing chain needs strike/dte/premium a stock position doesn't carry; `trend_score` defaults to a neutral 50 there since a post-trade position doesn't retain its scan-time score.)
- [x] Persist result as one JSON blob `exitPlan` (typed `ExitPlan | null` on the frontend, `dict | null` on the backend) on `PortfolioPosition`/`PortfolioPositionModel` (mirrors the existing `tradeCardSnapshot` pattern), timestamped (`computedAt`, stamped client-side on receipt — the endpoint itself is stateless), refreshed only on manual re-click.
- [x] Pricing-method 3-way split: `PricingMethod` gains a third value (`BS_REPRICED = "BS repriced (IV-derived)"`; `DELTA_APPROX` now correctly means `"Delta approximation"`); `_bs_reprice_or_delta_approx` returns `(price, used_bs_reprice)` and both call sites (`estimate_rr`, `estimate_targets`) label from that instead of hardcoding. `RrModel` (both copies — `reward_risk.py` and `schemas/__init__.py`) widened to 3 values. Legacy `'delta-approx'` code now maps to `BS_REPRICED` (preserves old sessions' historical display, since old data never distinguished the two). Applies everywhere `pricingMethod`/`model_used`/`rrModel` is shown (backend + frontend types widened).

## Feature C — Max-loss-per-trade (built on Feature B's final stop)

- [x] `backend/config/risk_rules.yaml`: `portfolio.max_loss_per_trade_pct: 0.0375`.
- [x] `risk_settings.py`: add `maxLossPerTradePct`, mirrors existing `maxSinglePositionPct`.
- [x] `RiskLimits`/`RiskSettings` (domain.ts/api.ts) + `riskStore.ts` (`DEFAULT_LIMITS`, persisted store version bump 2→3, migration branch) + new Settings `RiskForm()` row.
- [x] Per-trade override field `maxLossOverride: { mode: 'dollar' | 'percent'; value: number } | null` on `PortfolioPosition`/`PortfolioPositionModel`. (Backend ORM/schema/PATCH plumbing already existed from Phase 0 scaffolding; this phase wired the frontend type + `portfolioStore.ts` PATCH payload + the Portfolio-editor UI that sets it.)
- [x] Loss basis = reprice the option at Feature B's `final_stop` price (reuse the same repricing call, no duplicate logic) × contracts; debounce ~400ms on stop/contracts change. (`exitPlan.stop.contractPrice` is already the repriced value from Feature B's "Compute Exit Plan" — no *additional* backend round trip needed; the ~400ms debounce is a client-side render-smoothing measure on the derived $ figure, distinct from `portfolioStore`'s existing 600ms network-patch debounce.)
- [x] Trade-card-time: new soft reason `max_loss_per_trade_exceeded` in `checkTradeRisk()`, reuses `SendToBrokerDialog`'s two-click override UX.
- [x] Portfolio-time: inline badge/banner, recomputed on stop/contracts/override change.
- [x] `portfolioValue` "last updated" staleness nudge in Settings (no auto-tracking).

## Feature D — Active TP method + per-position alert controls

- [ ] `TpMethod = 'ladder' | 'monte_carlo' | 'exit_plan_2r' | 'exit_plan_3r'` field on `PortfolioPosition`/ORM + selector UI (radio/segmented control) in the Portfolio editor across all TP-producing sections.
- [ ] Headless alerting: `resolved_tp_price` / `resolved_tp_updated_at` snapshot columns, refreshed only on manual re-estimate/re-compute; `portfolio_alert_monitor.py` compares live price against this snapshot exactly as it already does for `structuralStop`.
- [ ] `AlertOverrides = Partial<Record<AlertType, boolean>>` field on `PortfolioPosition`/ORM. `effectiveEnabled(type) = overrides[type] ?? globalEnabledTypes.includes(type)`, implemented in both `frontend/lib/alertEngine.ts::scanPortfolio` and `backend/app/services/alert_generator.py::generate_alerts` (documented mirrors of each other per `CLAUDE.md`).
- [ ] Toast-gating bugfix bundled in: thread `enabledTypes` into `scanPortfolio`/`addToast` for the first time.
- [ ] UI: toggle switches per `AlertType` in the Portfolio `EditDrawer`, defaulting to "inherit" (visually distinct from explicit on/off), plus a line showing which price each active alert currently fires against.

## Feature E — Monte Carlo + buy-time snapshot for stock positions

> **Status: DONE — shipped to `main` ahead of this plan, via a separate branch (`feat/stock-monte-carlo-buy-snapshot`, merge commit `41e40480`) and its own plan docs (`2026-08-26-monte-carlo-portfolio-drawer-and-snapshot-gaps.md`, implemented; `2026-08-26-stock-monte-carlo-buy-snapshot.md`, superseded once the backend estimator was found to already exist).** This section's checkboxes are retro-marked. Adversarial-audit evidence is self-reported in commit messages only (2 documented `K-adversarial-audit-loop` rounds — `79f2480e`, `423f2d5b` — plus a clean 3rd per `41e40480`); no standalone audit report was produced.

- [x] Build the missing snapshot-capture step in the stock buy flow (mirror `tradeCardSnapshotOf()` from `step-7-trade-card/page.tsx:60-71` into the equivalent stock buy flow, `step-7-position-card`/`StockPositionCard`), capturing whatever `getStockFirstPassage` needs (`horizon`, `strategy`, `trend_score`-equivalent) that isn't already captured. — `stockCardSnapshotOf(card, horizon)` in `frontend/lib/paperTrade.ts`, wired into all three broker-order stock paths (`StockSendDialog` auto-send, `StockPositionCard.submit`, `step-7-position-card` submit). Two create paths remain snapshotless by design — the after-scan auto-execute loop (`step-4-stocks/page.tsx`) and the `ChartWorkspace` chart-click buy — and their estimate degrades gracefully to `strategy: ''`, `horizon: 'Swing'`, `trend_score: 50`.
- [x] Wire the existing Monte Carlo estimate-button + result-row pattern into the Portfolio `EditDrawer` for both options (`getFirstPassageEstimate`) and stock (`getStockFirstPassage`) positions, branching on contract shape. — `EditDrawer` in `frontend/app/(frame)/portfolio/page.tsx`, branches on `position.contract.endsWith('|STOCK')`. Option-side estimate is disabled when `currentStockPrice`/strike can't be resolved.

## Migration

- [ ] One combined Alembic migration for all new `portfolio_positions` columns: `exit_plan` (JSON), `max_loss_override` (JSON), `active_tp_method` (string), `resolved_tp_price` / `resolved_tp_updated_at`, `alert_overrides` (JSON). All additive `ADD COLUMN`s, no ordering dependency between them.

## Build sequence with checkpoints

Each ✅ checkpoint = typecheck/pytest green **and** a `K-adversarial-audit-loop` (audit-only mode) pass against the work done so far, findings fixed before moving on.

1. **Phase 0** — combined migration + ORM/schema/router scaffolding for every new column. ✅ checkpoint + audit.
2. **Phase 1** — Feature B in full (largest, most novel phase; verify in isolation before anything depends on it). ✅ checkpoint + audit.
3. **Phase 2** — Feature C (built on Feature B's final stop). ✅ checkpoint + audit. [done]
4. **Phase 3** — Feature E (stock snapshot capture + Monte Carlo in Portfolio editor, both asset types). [done — shipped separately, see the Feature E section]
5. **Phase 4** — Feature D (active TP method selector + per-position alert overrides + toast-gating fix — most cross-cutting alert code, done last).
6. **Final** — full-diff `K-adversarial-audit-loop` pass end-to-end.

> **Phase 0 / Feature D scaffolding note:** Phase 0's `bbb04a057515` migration already added *all* the columns, Feature D's included (`active_tp_method`, `resolved_tp_price`, `resolved_tp_updated_at`, `alert_overrides`), and the ORM fields (`models/portfolio.py`), the `TpMethod` literal, the read/update Pydantic schemas, and the CREATE/PATCH router plumbing (`routers/portfolio.py`) are all in place. Phase 4 therefore needs **no new migration** — only the business logic that populates and consumes those columns (`alert_generator.py`/`portfolio_alert_monitor.py`/`alertEngine.ts` override + toast-gating, `resolved_tp` snapshot refresh) plus the frontend type/store/UI.

Extend existing test files rather than adding new ones at the end: `test_first_passage.py`, `test_structural_stop.py` (+ new `test_exit_plan.py`), `test_risk_settings.py`, `test_portfolio_update.py`, `test_portfolio_alert_monitor.py`, `riskStore.test.ts`, `risk.test.ts`, `alertEngine.test.ts`, `portfolioStore.test.ts`.

## Verification

- Backend: `cd backend && pytest tests/test_exit_plan.py tests/test_structural_stop.py tests/test_first_passage.py tests/test_risk_settings.py tests/test_portfolio_update.py tests/test_portfolio_alert_monitor.py`.
- Frontend: `cd frontend && npm run typecheck && npm run test`.
- Manual: open an options TradeCard, press "Compute Exit Plan," confirm both RR rows show stock+contract price, source tags, probability/days, and the quality badge; confirm the delta-approximation label is distinct from BS-repriced when it actually fires; confirm the max-loss warning appears pre-trade and again in the Portfolio editor; confirm a stock position now captures a buy-time snapshot and can run the Monte Carlo estimate in the Portfolio editor; switch a position's active TP method and confirm the alert-driving price updates; toggle one alert type off for a single position and confirm others are unaffected globally.
