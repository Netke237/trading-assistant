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

## Open questions for the approval pass

1. Mockup is light, like the Options proposal; production follows the app theme tokens (dark default). OK?
2. "Looks for" wording per strategy (it repeats the Entry line).
3. Approval of proposal 02 as the design to plan against.

## Next steps after approval

1. Reconcile with `codex/trade-card-qualification-presentation` (possible overlap on score components).
2. Write the implementation plan → independent plan audit (repo `audit_rule`, 3-round cap) → tracking issue + tickets via k-ticket-coordinator.
3. Build, integrated code audit, PR. No merge without Kenneth.
