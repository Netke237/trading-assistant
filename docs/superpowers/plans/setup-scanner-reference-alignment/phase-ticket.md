[codex · coordinator]

**Phase id:** `SETUP-SCANNER-REFERENCE-ALIGNMENT` · **Design / spec:** [approved scanner preview](https://github.com/Netke237/trading-assistant/blob/docs/stocks-prebreakout-information-flow-34181032/docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/prebreakout-preview.html) · **Decision:** user instruction in this chat, 11 November 2026: "convert to ticket and start implementing"
**Branch:** _(set by the agent holding the claim)_
**Blocked by:** none · **Touches:** step-4-prebreakout page, selected context/evidence/news components, CSS/tests.

## Goal
Implement the recovered Setup Scanner preview across Pre-Breakout, EMA Pullback and Fib Pullback.

## Scope
Keep scan controls, shared mode toggle and Run Scan; selected sentiment then fundamentals; candidates beside selected chart; setup/stock qualification, parameters, news and saved diagnostics accessible in default-closed disclosures. Preserve every field, explanation, action, status color, response state, run ownership, separate original/supplementary context and existing request triggers. Do not invent prices, probabilities, trading levels, orders or new fetches.

## Acceptance
- [ ] Complete current-source preservation inventory and independent clean implementation plan.
- [ ] All three modes match the reference hierarchy with keyboard/mouse candidate selection and existing Watch/chart/Alert actions.
- [ ] Complete parameters/reset/help, evidence, context/source warnings, news and per-mode reports remain reachable.
- [ ] Expanding/viewing never reruns scans; stale responses cannot cross selected symbols/runs; absent data remains absent.
- [ ] Light/dark and supported-width browser checks, typecheck, required regressions and independent code audit clean.

## Ratings and progress
0% — queued for implementation after Stocks begins. Size L, complexity 3: three mode-specific tables and selected research panels need presentation coordination while preserving existing async ownership.
Next unmet milestone: concrete source-checked implementation plan (10%).
