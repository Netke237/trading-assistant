# APP-AUDIT-B-REGIME-RACE — plan round 1

- Reviewer: fresh independent `gate-auditor` subagent (a27d688949ff06349), bmad-review-adversarial-general
- Reviewed: `docs/superpowers/plans/2026-10-20-app-audit-b-regime-race-plan.md` at `674ff931`, against the code it names
- Result: **GATE FINDINGS: 2**

## F1 — Steps 2/3 writing all three gate fields spreads the default-Markov reading
Steps 2 and 3 call `api.getRegime()` with backend defaults (20 / 0.02 / 0) while Step 1 sends the Settings Markov values; `omm.state`, `regime_direction` and the verdict depend on them. With a non-default preset, making Step 3 write `regimeDirection` and Step 2's Refresh write `combinedRegime` shows a new wrong reading (Step 3 "against the tide" banner; Step 2 Refresh flipping PASS→REJECT on Step 4 Stocks / Dashboard rail).
Suggested fix: parameter parity — Steps 2/3 send the Settings Markov values.

## F2 — "most recently started" discards a valid response
If the newer request is still pending or fails, the older valid response is thrown away: the gate stays PENDING (first load) or an older verdict, so Run Scan's REJECT confirmation and the Step 7 regime row are lost.
Suggested fix: "newest applied response wins" (`ticket > lastAppliedTicket`).

Below the gate (noted): planned test 2 (stale failure UI after unmount) would pass on the current code.

## Fixes (plan revision)
- F1: rule 1 — all three steps send `getRegime('intraday', Settings markov)` via one `fetchGateRegime()`; tests 3, 10, 12.
- F2: rule 2 — newest-applied ordering for the gate and for Step 1's own reading; test 7 inverted, A-then-B-fails case added.
- Test 2 replaced by an in-mount stale failure (test 6).
