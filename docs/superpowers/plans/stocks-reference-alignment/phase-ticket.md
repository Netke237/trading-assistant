[codex · coordinator]

**Phase id:** `STOCKS-REFERENCE-ALIGNMENT` · **Design / spec:** [approved Stocks preview](https://github.com/Netke237/trading-assistant/blob/docs/stocks-prebreakout-information-flow-34181032/docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/stocks-preview.html) · **Decision:** user instruction in this chat, 11 November 2026: "convert to ticket and start implementing"
**Branch:** `board/stocks-reference-alignment-63771a99`
**Blocked by:** none · **Touches:** StockPositionCard, PositionEvidence, InitialStrategyTargets, their CSS/tests; terminal Stocks presentation only.

## Goal
Implement the recovered Stocks preview's information flow using existing application data and behavior.

## Scope
Sentiment then fundamentals then identity; collapsed Stock Qualification and Backtest Evidence; compact execution stop/risk; independent method viewing and two/three-method comparison with preserved detailed evidence; entry/shares and existing decision/action controls. Preserve embedded Backtest card behavior, every unique explanation, calculation semantics, provenance, edit invalidation, research-only execution block and basket/save/send payloads. Arithmetic owns its race; Ladder uses edited targets, separate from original scanned strategy. No model, API, backend, persistence schema or execution authority changes.

## Acceptance
- [ ] Source-to-destination preservation inventory and payload ownership trace completed.
- [ ] Exact implementation plan independently reviewed clean before child build tickets.
- [ ] Actual rendered position card matches approved flow in both themes at supported widths; details retain all source information.
- [ ] Viewing/comparing does not calculate or pick; calculation/selection do not apply stops; Apply suggested shares changes shares only.
- [ ] Existing numeric, ownership, stale response, submission and embedded-card regressions pass.
- [ ] Typecheck, required tests and independent phase-wide code audit clean under audit_rule.

## Ratings and progress
0% — queued; concrete plan being drafted. Size L, complexity 3: several presentation components and method states must be coordinated while preserving financial and execution boundaries.
Next unmet milestone: concrete source-checked implementation plan (10%).
