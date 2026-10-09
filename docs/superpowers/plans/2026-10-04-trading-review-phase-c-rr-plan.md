# Trading Review Phase C, R/R basis — Implementation Plan (`TRADING-REVIEW-PHASE-C-RR`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket, one fresh implementer, test-first.
> The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never edit audit fields
> and never put `round N` in a commit subject.

**Origin.** This was task T9 of `docs/superpowers/plans/2026-10-04-trading-review-phase-c-plan.md`. The Phase C plan
audit reached its three-round cap with one finding on T9 still open (R3-F1: the fix below under "Backend scan-result
schema version" was written at the cap and never audited). On 2026-10-04 Kenneth decided (decision
`PHASE-C-CAP-SPLIT-T9-2026-10-04`) to build the rest of Phase C and to move T9 into this separate target. **This
target's plan audit starts at round 1 of 3 and reviews this whole file against the code.** Every plan-stage finding
on T9 so far (R1 F2, R2-F1, R3-F1) is folded into the text below; the round record is in the
`TRADING-REVIEW-PHASE-C` phase note in `PROJECT_STATE.json`.

**Decision it implements:** D5 (Kenneth, 2026-10-04): the options R/R loss basis is 100% of premium unless a
protective stop order is placed. Proposal: `docs/superpowers/plans/2026-10-04-trading-review-phase-c-proposal.md`.

**Independence.** Disjoint from every Phase C task's files. It can be built on its own branch from `main` before or
after Phase C merges.

## Global constraints

- **Runtime.** Backend Python **3.11** (`cd backend && .venv/bin/python -m pytest`; Windows
  `.\.venv\Scripts\python.exe -m pytest`). Frontend `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **No threshold changes.** The Step-7 R/R row thresholds (`≥2.0 PASS / ≥1.5 CAUTION`) stay as they are (C4).
- **Numeric golden pins.** A pin that moves because of this task's own mechanism may be re-pinned in the same commit
  with `# Re-pinned by TRADING-REVIEW-PHASE-C-RR: <one-line mechanism>` and listed under DEVIATIONS. Any other moved
  pin is a defect: stop and report it.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## The task — Options R/R at the full-premium loss basis (fixes M7, D5)

**Mechanism today.**

- `estimate_rr` and `estimate_targets` (`reward_risk.py:112-168, 171-370`) divide reward by `resolved_risk_dollars` = `premium × premium_stop_pct` (0.60), or the smaller captured stock-stop loss (`:379-387`).
- No protective option order is ever placed. The premium stop is an alert level (`services/premium_stop.py`), and sizing assumes the whole premium can be lost (Phase A D5).
- The card's R/R therefore overstates reward per unit of real risk by ≥ 1/0.6.

**Semantics.**

- `estimate_rr(..., protective_stop_order: bool = False)` and `estimate_targets(..., protective_stop_order: bool = False)`.
- When False, which is every caller today:
  - `risk = current_premium` (rounded as today when a captured stock risk exists).
  - `RrResult.risk_basis = "full_premium"`.
- When True, today's `resolved_risk_dollars` and `premium_stop` / `stock_stop` basis apply unchanged.
- `TradePlan.premium_stop`, the dollar alert level, is **unchanged**.
- `resolved_risk_dollars` itself is unchanged; it is still used when True.

**Test first.**

1. `backend/tests/test_rr_full_premium_basis.py`:
   - For a fixed Heston-free input with a premium of 2.00, `estimate_rr(...)` returns `rr_ratio == round((exit − 2.00) / 2.00, 2)` and `risk_basis == "full_premium"`.
   - With `protective_stop_order=True`, the result equals today's value: compute the expected value in the test from `resolved_risk_dollars`.
2. The same pair for `estimate_targets(...)[i].rrContribution`.
3. `build_trade_plan` (`trade_plan.py`) passes no flag, so its `rr_ratio` uses the full premium and `premium_stop` is still `premium × 0.60`.
4. Frontend, `TradeCard` tests (find the existing test files for `TradeCard`). Plan round 1, F2: `index.tsx:3351` serves **every** row without an `authoritativeRr`, not only edited ones. `authoritativeRr` is passed only when `hasCapturedStockRisk && !rrStale` and the entry limit and premium stop are unedited (`:3221`). Otherwise the row divides by `ladderRisk` (`:1853`), which is `overlay.premiumStop` or `min(premiumStop, capturedStockRisk)`. Tests, all on the full-premium basis (risk leg = `overlay.entryLimit`):
   - (i) an **un-edited** row on a card with **no** `stockStopLoss`: premium 2.00, estimate 3.50 → 0.8 (today 1.3);
   - (ii) an edited target row;
   - (iii) a card with a captured stock risk after the entry limit is edited;
   - (iv) `rrStale` true.
   - (v) Plan round 2, R2-F1: a **saved pre-T9 candidate** (`exit.rrRiskBasis: 'premium_stop'`, `rrContribution` 1.25, premium 2.00, estimate 3.50) renders **0.8**, not 1.3, and its caption does not say "full premium" for a value computed on another basis.
6. Frontend, `frontend/lib/__tests__/` scanStore migration test (extend the existing v13-v17 migration tests):
   - A v17 persisted state whose `scanResult` (options) holds any candidate with `exit.rrRiskBasis` absent or ≠ `'full_premium'` migrates to `scanResult: null`. The same rule applies to `previousRun`.
   - A state whose candidates are all `'full_premium'` is kept unchanged.
   - `stockScanResult` and every other field are untouched.
7. Frontend, the step-7 rail: a candidate whose `exit.rrRiskBasis !== 'full_premium'` grades the R/R row **CAUTION** with the detail "R/R computed on an older basis: re-run the scan". This is defence in depth for any live card that bypasses the migration.
5. Frontend, the step-7 context-rail checklist row: with `rrRiskBasis: 'full_premium'`, the detail text says "risking the full premium (no protective stop order)".

**Code.**

- Backend:
  - Add the flag.
  - `RrResult.risk_basis` Literal gains `"full_premium"`.
  - `trade_plan.rr_risk_basis` carries it.
  - The `scan.py:1371` alternative-contract call needs no change, because the default applies.
  - `routers/contracts.py:1128,1172` use `estimate_rr` only for `estimated_exit_premium`. Confirm that by reading the code, and leave them unchanged. If either reads `rr_ratio`, stop and report a plan defect.
- Frontend:
  - `types/domain.ts:666` union gains `'full_premium'`.
  - `TradeCard`: `ladderRisk` becomes `overlay.entryLimit` (the full premium at the overlay's own entry). It no longer reads `premiumStop` or `capturedStockRisk` for R/R. `authoritativeRr` passes the backend's `rrContribution` only while the entry limit is unedited. The stock-stop conditions are no longer relevant because the backend no longer uses that basis.
  - **`authoritativeRr` guard (R2-F1).** Pass the backend's `t.rrContribution` only when `data.exit.rrRiskBasis === 'full_premium'` **and** `overlay.entryLimit === data.entry.limit`. Otherwise the row recomputes `rrContribution(estOptionPrice, overlay.entryLimit, overlay.entryLimit)`. That recomputation is exact, because `estimatedOptionPrice` does not depend on the risk basis.
  - **scanStore v18 (R2-F1).** Bump `version` 17 → 18 and add an accumulating `if (version < 18)` branch, in the same shape as the v13-v15 branches that delete a saved field that became a wrong number under a new reading. It discards a persisted options `scanResult` and `previousRun` when any candidate's `exit.rrRiskBasis !== 'full_premium'`, so persisted `rrRatio` values from before T9 (header, rail, `AlternativeContractRow`) are never shown under the new basis. The user re-runs the scan. The one-time loss of Δrank against the discarded `previousRun` is accepted. Comment the branch with this reason.
  - **Backend scan-result schema version (plan round 3, R3-F1).**
    - **Status:** this fix was written AT THE PLAN-STAGE CAP and has **not** been audited.
    - **Why:** the v18 branch alone is undone by `StoreHydration` (`components/StoreHydration/index.tsx:47-98`). It refills a null `scanResult` from `/scan/last`, and `restore_from_db` (`routers/scan.py:1508-1586`) serves the pre-T9 blob, because its `schema_version` 2 is still current.
    - **Change:** bump `SCAN_RESULT_SCHEMA_VERSION` 2 → 3 (`backend/app/schemas/__init__.py:1030`), with a comment line "3 — options R/R on the full-premium basis (Phase C T9)". Every reader compares rather than testing for None, so `restore_from_db`, `/api/tradecards` and the watchlist router refuse v2 automatically.
    - **Test:** a stored `ScanSession` blob at schema 2 is refused by `restore_from_db`, and `/scan/last` returns null.
    - Keep the v18 branch.
  - The `premiumStop` **field** itself (the editable alert level) is unchanged.
  - Update the comment at `index.tsx:129-131`, the comment at `:3214-3218`, and the caption at `:3202-3204`, which becomes: "R/R risk: full premium (no protective stop order)." Keep the `rrStale` caption only if `rrStale` still changes anything; it does not for R/R, so remove that branch from the caption only.
  - The step-7 rail text gains the third branch.
- The schema for `rrRiskBasis` in `backend/app/schemas` (find it with `grep -n rrRiskBasis backend/app/schemas`) gains the literal.

**Consequence, recorded for Kenneth and not a defect.** Every options R/R drops by a factor of about 0.6 or more, so the Step-7 checklist row (`≥2.0 PASS / ≥1.5 CAUTION`) will show more CAUTION and REJECT. Its thresholds are **not** changed in this phase. That is a C4 decision.

**Commit:** `fix(rr): options R/R risks the full premium unless a protective stop order exists (Phase C RR, review M7)`
