# Stocks + Pre-Breakout presentation — design proposal (STOCK-DESIGN-GRILLING)

Status: **proposal 02, awaiting Kenneth's approval.** No application code changed. No plan, audit or tickets yet.

## Why this exists

The Options pages got an approved Options-style presentation (`../2026-10-03-trade-card-presentation/preview.html`; Steps 5, 6, 7 shipped). The Stocks work that shipped afterwards (STOCKS-STEP-MERGE-S1/S2, STOCKS-HORIZON-P0A/P0B/T1) changed workflow and logic only — S2's spec explicitly listed "Visual redesign" and "Pre-Breakout handoff" as out of scope. The design step for Stocks/Pre-Breakout (STOCK-DESIGN-GRILLING, claimed 2026-10-04) never produced anything. This folder is that missing step.

## Files

- [preview.html](preview.html) — **proposal 02**, interactive offline mockup. Toolbar switches Strategy / Backtest / Position / Pre-Breakout; every element is tagged EXISTING / MOVED / NEW / BACKEND FIELD ("Tags on/off" hides them); "Information mapping" is a 66-row item-by-item table built from the current source. Values are illustrative.
- [strategy.png](strategy.png), [backtest.png](backtest.png), [position.png](position.png), [prebreakout.png](prebreakout.png) — 1440px captures.

## Decisions (Kenneth, 2026-10-10)

| # | Question | Decision |
|---|---|---|
| D1 | Which pages | All four: Strategy (step 4), Backtest (step 5), Position (step 6), Pre-Breakout |
| D2 | Fidelity to Options trade card | Same layout and parts: reuse shipped MarketSentiment / FundamentalHealthCard compact variants, method cards, qualification section, right rail |
| D3 | Pre-Breakout → Position handoff | No. Redesign in place; it stays a scanner + watch/alert tool (exits not designed until STOCKS-HORIZON-T4) |
| D4 | New calculations (stock Barrier Race etc.) | No. Show only what exists: Arithmetic, Monte Carlo, Fixed ladder, structural stop |
| D5 | Replacement for "Contract Scorecard" | Backtest evidence card (win %, trades, return, max DD, expectancy, Sharpe, confidence, gate with this scan's thresholds) beside the Stock Scorecard |
| D6 | Pre-trade checklist on Position | Yes, built only from gates the stock path already enforces (gate_flags, score threshold, backtest gate, earnings veto, fundamentals, Unvalidated block, exposure/daily risk) |
| D7 | Backtest row detail | Inline details like Options Step 6: score factors, backtest stats vs thresholds, gates, actions (Open Position, Pin, Arm after-scan); no horizontal scroll |
| D8 | Pre-Breakout row detail | All four: why it's a setup (each ratio vs threshold, trend filter), confidence breakdown, Fibonacci/pullback detail, mini chart |

## Proposal 01 errors, corrected in 02 (Kenneth's review, 2026-10-10)

Proposal 01 was not checked line by line against the code. It dropped existing items (R:R at T1, per-leg R:R and return %, most Arithmetic-plan lines, structural-stop details, two broker modes, status messages, the Backtest full-card Expand, the Pullback and Fib tables) and showed things that do not exist (per-leg win %, "Gain $", made-up labels and parameter names, "no Barrier Race for stocks" — the two-barrier race exists inside the Arithmetic plan, a per-row direction-floor check, a pre-checked exposure line, an "Above 20-EMA" column). 02 rebuilds every page from the source; nothing is removed.

Monte Carlo already exists for stocks: the Estimate button (`/api/stocks/first-passage`) and the Arithmetic plan (`/api/stocks/exit-plan`, which also returns the race). The redesign calculates nothing new.

## New items, each approved by Kenneth (2026-10-10, round 3)

| Page | New item |
|---|---|
| Position | Stock Scorecard factor rows (backend field) · Pre-trade checklist from existing gates only · "Latest calculation" strip · Sharpe |
| Backtest | Quick summary above the full card (full card kept) · Score and Confidence sort · summary strip of existing numbers |
| Strategy | Market Sentiment strip · "Looks for" line per strategy (overlaps the Entry line — wording to confirm) · after-scan armed count |
| Pre-Breakout | Confidence breakdown (backend field) · "Why it's a setup" inline (tooltips stay) · mini chart · Fib swing low/high (backend field) |
| All | "How this page works" disclosures and section links (part of the Options layout, D2) |

## Constraints carried into the plan

- Presentation only: every current information item and control is preserved (see the mapping drawer); no trading logic, sizing, gate or persistence change.
- Existing colour tokens/status semantics only (PASS green, CAUTION amber, REJECT red).
- **Additive backend fields needed (no calculation change)** — marked with purple dashed tags in the mockup:
  1. Stock score components (trend / pullback / trigger / event / volatility + observation text). `stock_scorer` already computes a `StockScoreCard`; `routers/stock_scan.py` only emits `score`/`status`. Note: unmerged branch `codex/trade-card-qualification-presentation` ("capture additive stock scoring evidence") may already contain this — reconcile before planning.
  2. Pre-Breakout confidence sub-scores (proximity / ATR / volume, + fib when enabled). Computed in `strategy_engine.py` ~L1554-1593, not returned.
  3. Fib swing high/low used for the retracement (for the fib detail and mini-chart lines).
- The pre-trade checklist must not invent a rule: each line maps to an existing field or gate.

## Approval and build decisions (Kenneth, 2026-10-10)

| # | Decision |
|---|---|
| D9 | Proposal 02 approved as is (incl. "Looks for"); real pages follow the app theme tokens |
| D10 | Five phases, in order: P1 backend fields → P2 Position → P3 Backtest → P4 Strategy → P5 Pre-Breakout |
| D11 | ~~P1 reuses commit `08ce063c`~~ **Corrected 2026-10-10:** that evidence (`StockScoreCard.explanation`: weights, factor components, caps) is already on main via the trade-card integration. P1 only sends it on stock-scan candidates — one source of score factors, nothing imported |
| D12 | Planning documents live on `main`; code on one feature branch per phase; merge only on Kenneth's go. Work continues from a cloud container |
| D13 | Tracking stays on **GitHub issues** (umbrella #144): issue updates cost no Actions minutes, while Markdown status commits to `main` each triggered CI (~20 min). CI now skips docs-only changes (PR #145, pending Kenneth's merge). Every agent-written issue/comment/PR starts with `[claude]` or `[codex]` |
| D14 | **P3** must also keep the Backtest time-exit display added by `STOCKS-T1-FOLLOWUPS` (merged `ea9c67ce`, after the 66-row mapping was drawn): its plan adds that item to the mapping slice. **P5** is presentation only and must not pre-empt reconciliation ticket 10 “Pre-Breakout exit semantics” (`.scratch/project-ticket-reconciliation-20261009/issues/10-t4-exits.md`) |

Recorded (with the D11/D13/D14 corrections) as decision `STOCK-PRESENTATION-2026-10-10` and backlog items `STOCK-PRES-P1…P5` in `PROJECT_STATE.json`. Umbrella tracking issue: **#144**.

## The path (per phase)

1. Claim the phase id, cut branch `claude/stock-pres-pN-…` from `main`.
2. Write the plan `docs/superpowers/plans/<date>-stock-pres-pN-plan.md`: tasks test-first, exact files, and **this phase's slice of the 66-row mapping as an acceptance checklist** (nothing removed, only approved NEW items).
3. Plan audit: fresh gate auditor per round, cap 3 (`audit_rule`). Push the plan + audit record to `main`.
4. Cut tickets under a new phase tracking issue (k-ticket-coordinator Start mode); link it from #144.
5. Build loop, one fresh implementer per ticket, coordinator verifies.
6. Coordinator checks the mapping slice item by item, then the code audit on `origin/main..branch` (cap 3), then a PR. Merge on Kenneth's go; tick the phase in #144.

## Container notes

- Needs `GH_TOKEN` (repo Issues + PRs read/write) — the coordinator stops without it.
- Python 3.11 venv for backend tests (P1); frontend `npm ci` for typecheck/Jest.
- `ticket-implementer` / `gate-auditor` agent types are absent in containers → the skill uses `general-purpose` with its briefs.
- No browser in most containers → the visual check against `preview.html` is listed under "Needs Kenneth" in the phase issue.
