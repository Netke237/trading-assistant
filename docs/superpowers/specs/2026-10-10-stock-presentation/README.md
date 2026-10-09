# Stocks + Pre-Breakout presentation — design proposal (STOCK-DESIGN-GRILLING)

Status: **proposal, awaiting Kenneth's approval of the mockup.** No application code changed. No plan, audit or tickets yet.

## Why this exists

The Options pages got an approved Options-style presentation (`../2026-10-03-trade-card-presentation/preview.html`; Steps 5, 6, 7 shipped). The Stocks work that shipped afterwards (STOCKS-STEP-MERGE-S1/S2, STOCKS-HORIZON-P0A/P0B/T1) changed workflow and logic only — S2's spec explicitly listed "Visual redesign" and "Pre-Breakout handoff" as out of scope. The design step for Stocks/Pre-Breakout (STOCK-DESIGN-GRILLING, claimed 2026-10-04) never produced anything. This folder is that missing step.

## Files

- [preview.html](preview.html) — interactive offline mockup; toolbar switches Strategy / Backtest / Position / Pre-Breakout; "Information mapping" lists every current item and where it goes. Values are illustrative.
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
2. Backtest table: grouping win % / trades / return / DD into one "Backtest" column — acceptable, or keep separate columns?
3. Mini chart in Pre-Breakout: reuse the existing lightweight-charts candlestick component at small size — acceptable cost?

## Next steps after approval

1. Reconcile with `codex/trade-card-qualification-presentation` (possible overlap on score components).
2. Write the implementation plan → independent plan audit (repo `audit_rule`, 3-round cap) → tracking issue + tickets via k-ticket-coordinator.
3. Build, integrated code audit, PR. No merge without Kenneth.
