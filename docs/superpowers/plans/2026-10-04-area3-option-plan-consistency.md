# AREA3-OPTION-PLAN-CONSISTENCY — implementation plan

Status: PLAN, unaudited. Branch `claude/cool-babbage-6i83la`. Claim `AREA3-OPTION-PLAN-CONSISTENCY`.

Origin: the area-3 (options contract selection) review rated CAUTION with four Medium
findings. This target closes findings 1, 2 and 3. Finding 4 (spreads) is
`AREA3-SPREAD-HONESTY`; the missing options evidence is `AREA3-OPTIONS-MEASUREMENT`.
Both are separate targets and out of scope here.

## Decisions this plan implements (Kenneth, 2026-10-03/04 grilling session)

| Id | Decision |
|---|---|
| D1 | Every preset including Custom: an option must still have **≥ 21 days of life left when sold at `hold_max`**. The window's upper bound is at least lower bound + 35 days, so a monthly expiry always fits. |
| D2 | The option R/R **target** is the exit plan's T1 (R-multiple × stop distance, snapped to structure), not a flat +8%. |
| D3 | The option R/R **risk** is the loss at whichever stop fires first: `premium × min(premium_stop_pct, stop_cost.fraction)`. `stop_cost.fraction` is the existing Black-Scholes-at-today loss at the resolved stock stop (`scoring/stop_cost.py`). When it is not computed, risk = `premium × premium_stop_pct` (today's behaviour). |
| D4 | The Step 3 `Bullish/Bearish target %` overrides become one **R-multiple** override. The same multiple drives the option R/R target **and** the exit-plan card's target rows. Saved values of the old keys are dropped on load and a one-time notice is shown. |
| D5 | The Step 7 checklist's R/R row reads the new number. Its 2.0 / 1.5 thresholds are unchanged and recorded as UNMEASURED (checked by `AREA3-OPTIONS-MEASUREMENT`). |

Amendment to Kenneth's approved fallback (D2), stated so the plan audit can check it: the
approved fallback for "the price data can't form a target" was an ATR move. In code, that
fallback path is reached only when `_atr(candles, 14) <= 0` (`resolve_stock_stop`'s
`flat_fallback`), so there is no ATR to scale by. This plan uses the arithmetic
`entry ± multiple × |entry − flat_stop|` instead. This is the same R-multiple rule with no
structural snap. **Flag to Kenneth in the round report.**

## Split (audit_rule: one layer per change, about 500 lines)

* **Slice A: backend** (`backend/app/**`, `backend/config/**`, `backend/tests/**`). Gets its own code-audit stage.
* **Slice B: frontend** (`frontend/**`). Gets its own code-audit stage and starts only after slice A's code audit is clean. Slice B depends on slice A's API shape, which is fixed by this plan.

---

## Slice A: backend

### A1. DTE window (D1): `backend/app/scoring/dte_window.py`

New module constants, next to `DTE_WINDOW_TOLERANCE_DAYS`:

```python
DTE_EXIT_BUFFER_DAYS = 21      # life left at exit when held to hold_max (D1)
DTE_MIN_WINDOW_SPAN_DAYS = 35  # one monthly cycle, so a monthly always fits (D1)
```

`dte_window(hold_min, hold_max, multiplier)` becomes:

```
min_dte = max(1, round(hold_min * multiplier), hold_max + DTE_EXIT_BUFFER_DAYS)
max_dte = max(round(hold_max * multiplier), min_dte + DTE_MIN_WINDOW_SPAN_DAYS)
```

`widened_min_dte(lo, hold_max_days)`: the clamp `hold_max_days + 1` becomes
`hold_max_days + DTE_EXIT_BUFFER_DAYS`. Without this, the tolerance subtraction would put
the hard-reject floor back under the buffer: Swing `36 − 10 = 26`, and 26 − 15 = 11 days
left at exit. `hold_max_days=None` still skips the clamp.

`widen_contract_overrides_for_dte` is unchanged. It already derives from
`widened_min_dte` and `hi + tolerance`.

Resulting windows (multiplier 2.0). These are pinned in tests:

| Preset (hold) | old window → old effective floor | new `dte_window` | new hard-reject `[min, max]` |
|---|---|---|---|
| Intraday (0–2) | 1–4 → 3 | 23–58 | 23–68 |
| Swing (5–15) | 10–30 → 16 | 36–71 | 36–81 |
| Position (15–45) | 30–90 → 46 | 66–101 | 66–111 |
| Quarterly (45–60) | 90–120 → 80 | 90–125 | 81–135 |
| SemiAnnual (90–105) | 180–210 → 170 | 180–215 | 170–225 |
| Annual (165–200) | 330–400 → 320 | 330–400 | 320–410 |
| Custom 15–200 | 30–400 → 201 | 221–400 | 221–410 |

Propagation, verified by reading the callers. Every consumer goes through `dte_window` /
`widened_min_dte`, so no caller changes are needed:
* `routers/scan.py`: `resolve_dte_bounds` → `_dte_bounds`/`DteWindow` echoed on `ScanResult.dte_window`; `_dte_floor = widened_min_dte(...)` into the chain fetch; `widen_contract_overrides_for_dte` into `validate_contract`.
* `routers/contracts.py` `GET /api/contracts`: the same three uses.
* `data/market.py` `_nearest_expiration_in_window`: receives `bounds` + `min_dte_floor`. Its docstring example ("floor 3", "floor 201") is updated to the new numbers.
* The no-hold path (`effective_dte_limits`, `contract_rules.yaml` min 21 / max 90) is **unchanged**.

Docstrings to rewrite in `dte_window.py`: the module docstring ("One rule … bottom clamp only engages for Intraday" is no longer true) and `widened_min_dte`'s. Both must state the D1 rule and point to this plan.

Tests (`tests/test_dte_window.py`, `tests/test_horizon_dte.py`, `tests/test_option_chain_expiry_selection.py`, `tests/test_contract_validator.py`):
* Table test over all seven rows above: `dte_window`, `widened_min_dte`, `widen_contract_overrides_for_dte`.
* Invariant (property-style loop over hold_min ≤ hold_max in 0..250): `widened_min_dte(lo, hold_max) − hold_max ≥ 21` and `max_dte − min_dte ≥ 35`.
* Existing assertions pinning the old windows are updated, each with the derivation in a comment. **Never regenerate a pin without the derivation.**

### A2. Target (D2, D4): one stock target per symbol, resolved where the candles are

New helper in `backend/app/scoring/exit_plan.py`:

```python
def resolve_t1_target(
    candles, direction, entry_price, stock_stop: StockStopResult | None,
    stop_price: float, r_multiple: float, snap_atr_multiplier: float,
) -> tuple[float, Literal["structural_snap", "arithmetic", "flat_fallback"]]:
```

* If `stock_stop is not None and stock_stop.source == "final_stop"`, it returns `compute_target_row(candles, direction, entry_price, stock_stop.final_stop, stock_stop.atr, r_multiple, snap_atr_multiplier)`, giving `(row.price, row.tp_source)`.
* Otherwise it returns `entry ± r_multiple × |entry − stop_price|`, giving `(price, "flat_fallback")` (amendment above).
* **Bearish floor on every branch (R1-F4).** A stock target at or below $0 is never a real level. A 10% stop × a 5R multiple would otherwise put T1 at −50%, and `bs_price(S≤0)` then drops to the flat-delta guess and inflates the R/R.
  * `compute_target_row` floors its bearish `arithmetic_price` at $0.01 before the snap test. This is one place, and it also covers `/contracts/exit-plan` rows and `/api/stocks/exit-plan` (stock mode gains the same floor; a negative stock target is wrong there too).
  * The flat-fallback branch floors identically.
  * `estimate_targets` floors its bearish T2/T3 extensions (`stock_price − 1.5·move`, `− 2·move`) at $0.01.
  * Test: final-stop branch, bearish, 10% stop distance, m=10 gives T1 = 0.01. The ladder T2/T3 are 0.01, never ≤ 0.

`r_multiple` resolution, in a new function `config_loader.resolve_target_r_multiple(overrides) -> float`:
* The per-request override `rr_target_r_multiple` if present. It must be finite and in (0, 10]; otherwise it raises ValueError and the endpoint returns 422, as the existing `rr_*` overrides do.
* Else `load_exit_plan_cfg()["target"]["rr_ratios"][0]` (2.0). **This is the one default for both the option R/R and the exit-plan card.**

Override-key changes in `services/config_loader.py`:
* Remove `rr_bullish_target_pct` / `rr_bearish_target_pct` from `_RR_OVERRIDE_KEY_MAP` and `_RR_OVERRIDE_CAPS`.
* Add `rr_target_r_multiple` to `effective_rr_overrides`' output, so `ScanResult.rr_overrides` records it and Step 7's recompute sends back the scan's value (STEP3-PARAM-REACH contract preserved). It does not map to a `reward_risk` key; `effective_rr_overrides` gets an explicit branch for it.
* An old request carrying `rr_*_target_pct` keys in `overrides`: the keys are **ignored**, because `merge_reward_risk_overrides` only applies mapped keys. A persisted pre-change scan result whose `rr_overrides` holds them therefore recomputes at the default 2R. No 422 for a stale client.

`backend/config/risk_rules.yaml`: delete `bullish_target_pct` / `bearish_target_pct`. Remove them from `config_health.py`'s `RISK_KEYS` known-key schema (line 164). The Settings › Risk save path (`routers/risk_settings.py`) only rewrites keys it owns. Verify by test that a save on a file without the two keys round-trips.

### A3. Risk (D3): `scoring/reward_risk.py` and `scoring/trade_plan.py`

`estimate_rr(...)` and `estimate_targets(...)` gain `risk_fraction: float | None = None`. The risk leg becomes:

```python
frac = premium_stop_pct
if risk_fraction is not None and math.isfinite(risk_fraction) and risk_fraction > 0:
    frac = min(premium_stop_pct, risk_fraction)
risk = current_premium * frac
```

`risk_fraction <= 0` is treated as "not computed". A stop that costs nothing would make the R/R infinite, which is not a measurement. The `invalidation_price` "reserved" comment on `estimate_rr` is rewritten to say risk is now `min(premium stop, stop-cost fraction)`.

`RrResult` gains `risk_basis: Literal["premium_stop", "stock_stop"]` (`stock_stop` when the min picked `risk_fraction`; a tie goes to `premium_stop`).

`build_trade_plan(...)`:
* **Removes** the `target_price = stock_price × (1 ± target_pct)` computation. It takes a new required keyword `target_price: float` (resolved by the caller, A2). Like `final_stop_price`, it has no default, so no caller can silently fall back to a target nobody chose.
* Takes `stop_cost_fraction: float | None` (required keyword, may be None) and passes it as `risk_fraction` to both `estimate_rr` and `estimate_targets`.
* `TradePlan` gains `rr_risk_basis`, `target_source` and `stock_stop_loss` (`round(premium × stop_cost_fraction, 2)`, or None when not computed).
* `premium_stop` (the dollar field) is unchanged. It is still `premium × premium_stop_pct`, the premium-stop alert level, which is a separate concept.

**Where the new fields live (R1-F1, R1-F2): on `TradeExit`, not on `TradeCardData`.**
`TradeExit` (`schemas/__init__.py:605`, `frontend/types/domain.ts`) gains three optional fields:
* `stockStopLoss: float | None`, in dollars per share of premium;
* `rrRiskBasis: Literal["premium_stop","stock_stop"] | None`;
* `targetSource: Literal["structural_snap","arithmetic","flat_fallback"] | None`.

All three default to None, so persisted pre-change cards still validate. Putting them on `exit` matters: Step 7's `mergePlan` (`tradeCardOverride.ts:91-97`) replaces `exit` wholesale, so a Step 6 recompute carries all three with it and they can never describe a different contract from `rrRatio`.

**The ladder's client-side R:R must use the same risk (R1-F1).** `EditableTargetRow` computes `rrContribution(estOptionPrice, entryLimit, premiumStop)` in the browser (`TradeCard/index.tsx:121-130, 3257`), dividing by `overlay.premiumStop`. Left alone, ladder T1 would show 1.0× beside a checklist 1.5× on the same contract. Slice B changes its risk leg to `min(overlay.premiumStop, data.exit.stockStopLoss ?? Infinity)`. That is the same "whichever stop fires first" rule as D3, and a trader-edited premium stop still participates. `premiumStop` itself stays the alert level. The backend `TargetLevel.rrContribution` (A3) uses the same min, so the two agree when nothing is edited.

### A4. Scan pipeline: `routers/scan.py` `_process_symbol`, around lines 1040–1180

Reorder so the plan is built after the stop cost:
1. `_stock_stop` is resolved (unchanged).
2. **Move** the stop-cost block (currently after the plan, lines about 1111–1160) before `build_trade_plan`. Its inputs (`_stock_stop`, `price`, `strike`, `contract["dte"]`, `premium`, `horizon_preset`) are all available there. Its outputs `stop_cost_pct` / `stop_cost_status` are unchanged. The raw `_scan_cost.fraction` is kept as `_stop_cost_fraction` (None when not computed).
3. `_t1_price, _t1_source = await asyncio.to_thread(resolve_t1_target, candles, direction, price, _stock_stop, _stock_stop_price, _r_multiple, snap)`, inside try/except. On exception it falls back to the arithmetic flat-fallback formula, the same "must not take the candidate down" pattern as the stop.
4. `build_trade_plan(..., target_price=_t1_price, stop_cost_fraction=_stop_cost_fraction)`.

Validation: `resolve_target_r_multiple(req.overrides)` is called beside the existing `_merge_rr_cfg(req.overrides)` fail-fast check in `_execute_scan_core` (`scan.py:1623-1626`). A bad value gives a 422 before any symbol runs. Inside `_process_symbol`, `_r_multiple` is resolved next to `_rr` (`scan.py:~935`) from the same `overrides`; it is already validated, so it cannot raise there.

Runner-up alternatives (line ~1335): `alt_rr = estimate_rr(..., target_price=_target_raw, ..., risk_fraction=<the alt's own stop cost>)`. The alternative's stop cost is computed with the same `compute_stop_cost` call (same stop, the alt's strike/dte/premium) when `_stock_stop.source == "final_stop"`, else None. **Out of scope, logged, not fixed:** alternatives still omit `reprice_years` (pre-existing; a different repricing horizon from the main plan).

The card's `exit` is built with `stockStopLoss`, `rrRiskBasis` and `targetSource` from the plan (see A3, "Where the new fields live").

### A5. Recompute endpoint: `routers/contracts.py` `POST /contracts/recompute-plan`

`RecomputePlanRequest`:
* Remove `rr_bullish_target_pct` / `rr_bearish_target_pct`. Pydantic's default `extra="ignore"` means a stale client still sending them gets a 200 at the default. Confirm the model has no `extra="forbid"`.
* Add `rr_target_r_multiple: float | None = Field(None, gt=0, le=10)`.
* Add `target_stock_price: float | None = Field(None, gt=0)` and `target_source: Literal[...] | None = None`. This is the card's `exit.target` (and `exit.targetSource`), round-tripped like `final_stop` and for the same reason: the target is a stock level, so a contract override must not move it.
* Absent means the arithmetic formula from `req.final_stop.price` (or the flat stop) at the resolved multiple, bearish-floored (A2).
* **The client sends `target_stock_price` ONLY when `card.exit.targetSource` is present (R1-F2).** A pre-change card's `exit.target` is the old `stock × (1 ± target_pct)` (a required field, so it is always populated). Sending it would price a hybrid: the old % target with the new min() risk. Omitting it makes this endpoint build the D2 target. The backend does not need to tell the two apart, because the client contract is the guard. A test pins it on the client side (B5).

The body computes `stop_cost_fraction` with `compute_stop_cost(stop_price=round(req.final_stop.price, 2), ...)`, **only when `req.final_stop is not None`**. That mirrors the scan's `source == "final_stop"` guard: `FinalStopOut` is only sent for a final stop. Otherwise it is None.

`RecomputePlanResponse.exit` carries `target = plan.target_price` plus the three new `TradeExit` fields.

`targetSource` on a recompute is the request's own `target_source` echoed when `target_stock_price` was sent. It is `"arithmetic"`/`"flat_fallback"` when the endpoint built the target itself: `"arithmetic"` with `final_stop`, `"flat_fallback"` without. So a pre-change card, once recomputed, is visibly a new-basis card.

### A6. Exit-plan endpoint (D4): `POST /contracts/exit-plan`

`ExitPlanRequest` gains `target_r_multiple: float | None = Field(None, gt=0, le=10)`. The target rows become:

```python
ratios = ep_cfg["target"]["rr_ratios"]
if req.target_r_multiple is not None:
    step = (ratios[1] - ratios[0]) if len(ratios) > 1 else 1.0
    ratios = [req.target_r_multiple] + [req.target_r_multiple + step * i for i in range(1, len(ratios))]
```

So with 2.0 / 3.0 configured and an override of 2.5, the rows are 2.5R and 3.5R. Absent means unchanged behaviour. `/api/stocks/exit-plan` (stock mode) is **not touched**, except for the A2 bearish floor that lives in `compute_target_row`.

**Position writer: the TP seed must follow the rows that were actually shown (R1-F3).** `services/position_writer.py:661-678` passes the *configured* `exit_plan.target.rr_ratios` to `seed_tp_from_pick`. `picked_method._seed_for_rr` matches the picked row's `rrRatio` against that list positionally. Under an override the shown rows are 2.5R/3.5R, nothing matches, and every Arithmetic pick would persist as `active_tp_method='ladder', resolved_tp_price=NULL`. That fires TP_HIT on the ladder T1 instead of the price the trader picked, which corrupts persisted position data.

The fix: `create_position` derives `_rr_ratios` from `body.exitPlan["targets"][i]["rrRatio"]` when `body.exitPlan` is a dict whose `targets` is a non-empty list of rows with numeric (non-bool) `rrRatio`. This is the same positional rule `EditDrawer.tsx:1427-1467` uses to label the rows. It falls back to the configured list otherwise (pre-change bodies, no exit plan). It stays inside the existing try/except, because the write happens after the broker order and must never 500.

Tests:
* override 2.5 plus an Arithmetic pick of row 0 seeds `exit_plan_2r` at that row's price, and row 1 seeds `exit_plan_3r`;
* no `exitPlan` falls back to config;
* malformed `targets` (scalar, rows without rrRatio, bool rrRatio) falls back to config and never raises.

### A7. Tests (backend)

* `test_reward_risk.py` / `test_multi_target.py`: `risk_fraction` None gives a byte-identical result to today (regression pin). With `risk_fraction` 0.40 and premium_stop 0.60, risk = 0.40 × premium and `risk_basis == "stock_stop"`. With 0.77, risk = 0.60 × premium and `risk_basis == "premium_stop"`. 0 / NaN / negative behave like None.
* `test_trade_plan.py`: `target_price` is required (TypeError without it); `stop_cost_fraction` flows to both rr and targets.
* `test_exit_plan.py`: `resolve_t1_target` final-stop path equals `compute_target_row(...).price`. Flat-fallback path arithmetic: bullish and bearish, bearish floored at 0.01.
* Scan integration (an existing scan fixture test): the card's `exit.target` equals `resolve_t1_target`'s price for the fixture's candles. `rrRatio` equals `estimate_rr` recomputed by hand from the fixture's stop-cost fraction. The stop cost is computed exactly once per symbol (assert by patch count).
* Recompute: round-tripping `target_stock_price` and `final_stop` reproduces the scan card's `rrRatio` exactly for the same contract. This is the drift test that matters.
* Exit-plan: override 2.5 gives rows [2.5, 3.5]; absent gives [2.0, 3.0].
* Config: an `rr_target_r_multiple` of 0, −1, NaN or 10.01 gives 422 on scan and on recompute. Old `rr_bullish_target_pct` in overrides is ignored (200, default 2R).
* Full backend suite on **Python 3.11** (verify `python --version` first, per CLAUDE.md).

---

## Slice B: frontend

### B1. DTE preview: `frontend/lib/horizonPresets.ts`

`previewDteWindow` mirrors A1 exactly, with constants `DTE_EXIT_BUFFER_DAYS = 21` and `DTE_MIN_WINDOW_SPAN_DAYS = 35`. `horizonPresets.test.ts` pins the same seven-row table as the backend test. A comment cross-references both files.

### B2. R-multiple parameter (D4)

* `step-3-direction/page.tsx` param defs: replace the two `rr_*_target_pct` rows with one row: `{ key: 'rr_target_r_multiple', label: 'Target (R-multiple)', min: 0.5, max: 10, step: 0.25, unit: 'R', section: 'all', subGroup: 'Reward/Risk' }`. The hint explains "target = multiple × distance to the stop, snapped to a nearby structural level". Update any param-count test.
* `executionParamDefaults.ts`: replace the two keys with `rr_target_r_multiple: 2.0` in every preset.
* `tradeCardOverride.ts` `RR_OVERRIDE_KEYS`, `lib/api.ts` recompute request type and `resolveStockScanRequest.ts`' key set: replace the two keys with `rr_target_r_multiple`.
* **Persisted state.** `scanStore` does **not** persist `scanOverrides` (`partialize`, `scanStore.ts:745-786`), so it needs no migration. The live overrides reset each session. Old keys reach the app through only two paths:
  * `searchProfilesStore` (`bamendjou:search-profiles`): v3 → v4. Its migrate branch deletes `rr_bullish_target_pct` / `rr_bearish_target_pct` from every profile's `scanOverrides`. The branches accumulate, with no early return (the pattern the file documents). If any deleted value was non-default (≠ 0.08), it sets `legacyTargetPctDropped: true`, a new top-level field added to that store's `partialize` (`searchProfilesStore.ts:163`) so it survives a reload until dismissed. Step 3's Reward/Risk group shows one line: "A saved profile's target % was replaced by a 2R target (targets are now multiples of the stop distance)." The line has a dismiss control that clears the flag.
  * Server-side scan schedules persist a `resolved_request` with the old keys (`searchProfilesStore.ts:219-243`). The backend ignores them (A2), so a schedule runs at the default 2R. That is consistent with D4's "dropped", and the same notice copy covers it. No server-side migration.

### B3. Round-trips (A5, A6)

* `step-7-trade-card/page.tsx`: the two `recomputePlan` effects (`:896-910`, `:972-983`) add `rr_target_r_multiple` via `rrOverridesForPlan`. They add `target_stock_price: card.exit.target` and `target_source: card.exit.targetSource` **only when `card.exit.targetSource != null`** (R1-F2).
* `TradeCard` has two edits, the only two in this target:
  1. The `getExitPlan` call adds `target_r_multiple` from the scan's recorded `rr_overrides` (via `rrOverridesForPlan`, the same rule as recompute), absent when not overridden.
  2. `EditableTargetRow`'s risk leg becomes `min(premiumStop, data.exit.stockStopLoss ?? Infinity)` (R1-F1). `rrContribution`'s doc comment is updated to state the min.
  Coordinate with the active `TRADE-CARD-SCORE-EVIDENCE` claim: merge `origin/main` right before slice B.

### B4. Checklist row (D5): `@contextRail/screener/step-7-trade-card/page.tsx`

The thresholds are unchanged. The detail text adds the risk basis when `candidate.exit.rrRiskBasis` is present (it lives on `exit`, so it follows a Step 6 recompute):
`Projected reward:risk is X.X× to the target, risking the <stock stop | premium stop> (whichever is hit first) — pass ≥2.0×, caution 1.5–2.0×.`
A code comment records the thresholds as UNMEASURED, pending `AREA3-OPTIONS-MEASUREMENT`. Types: `stockStopLoss?`, `rrRiskBasis?`, `targetSource?` on `TradeExit` in `types/domain.ts` (and any mirrored type in `lib/api.ts`).

### B5. Tests (frontend)

The `previewDteWindow` table; the searchProfiles v4 migration (non-default value sets the flag, default 0.08 doesn't, other overrides untouched, a store frozen at v1/v2 still lands on v4, the flag survives `partialize`); the recompute payload carries `rr_target_r_multiple` and carries `target_stock_price`/`target_source` **only** for a card with `exit.targetSource` (a pre-change card omits both); the `EditableTargetRow` R:R uses `min(premiumStop, stockStopLoss)` and equals the backend `rrContribution` for an unedited row; `getExitPlan` payload; checklist text for both bases and the absent case. `npm run typecheck` and `npm run test` must be clean.

---

## Gate-relevant risks for the auditors to probe

1. **Risk-basis asymmetry (accepted, recorded):** the risk leg uses Black-Scholes at **today's** DTE (stop_cost basis, no theta), while the reward leg is repriced at the hold horizon (`reprice_years`). This was Kenneth's explicit choice (D3: "the stop_cost.py basis"). The auditor should not report it as a defect, but should report any place where the **same card** shows two different R/R numbers for the same contract.
2. **Small stop-cost fractions inflate R/R.** A deep-ITM or long-dated contract can lose about 10% at a 2×ATR stop, so the R/R reads 5×. This is arithmetically what D3 asked for, and there is no floor (none approved). Logged for `AREA3-OPTIONS-MEASUREMENT`.
3. **Persisted pre-change scan results** (`scan_sessions` via `/api/scan/last`, browser-persisted results) carry an old-basis `rrRatio` (8% target, 60% risk) on the auto-pick card until the next scan, which is internally consistent with the old basis. Any card recomputed in Step 7 is fully new-basis, because the client omits the old `exit.target` (A5, R1-F2) and the endpoint builds the D2 target. The old number is never mixed with the new risk. This is documented in the round report.
4. **The 2 call sites of `estimate_rr` in `contracts.py` exit-plan** (stop row, target rows) keep the 60% basis for their own `contractPrice` repricing. They use only `estimated_exit_premium`, never `rr_ratio`. The auditor should verify that no `rr_ratio` from those calls reaches a user.

## Out of scope (logged against main, not fixed here)

* Alternatives omit `reprice_years` (pre-existing).
* `/contracts/exit-plan` resolves its own final stop from fresh candles at the live price, so it can differ from the scan's stop (pre-existing).
* Spreads (`AREA3-SPREAD-HONESTY`), measurement (`AREA3-OPTIONS-MEASUREMENT`).

## Done means

The plan audit is clean, then slice A's code audit is clean, then slice B's code audit is clean (each stage capped at 3 rounds), with backend (3.11) and frontend suites and typecheck green. PROJECT_STATE is updated with the rounds, reviewers, diffs and findings. Merge only on Kenneth's say-so.

---

## Audit record

### Plan round 1 (plan stage 1 of 3): fresh independent subagent running `bmad-review-adversarial-general`; reviewed commit 144b68d
4 gate-level findings, all accepted and fixed in the plan revision that follows 144b68d:
* **R1-F1 (high).** The ladder's client-side R:R divides by `overlay.premiumStop` and would disagree with the checklist `rrRatio` on the same card. Fix: `TradeExit.stockStopLoss`; `EditableTargetRow` risk = `min(premiumStop, stockStopLoss)` (A3, B3).
* **R1-F2 (medium).** Pre-change cards always send their old `exit.target`, which would price a hybrid old-target/new-risk R:R. Fix: the client sends `target_stock_price` only when `exit.targetSource` is present (A5, B3). Risk item 3 was corrected.
* **R1-F3 (medium-high).** `position_writer` seeds the TP method against the configured `rr_ratios`, so an override mis-seeds every Arithmetic pick to the ladder (persisted). Fix: derive the ratios from `body.exitPlan.targets[].rrRatio` (A6).
* **R1-F4 (medium).** Bearish targets can go ≤ $0 on the final-stop branch and in the T2/T3 extensions. Fix: a $0.01 floor in `compute_target_row`, the flat fallback and `estimate_targets` (A2).

Non-gate corrections also applied (factual): `scanStore` does not persist `scanOverrides` (the migration was moved to `searchProfilesStore` only); the 422 point is `scan.py:1623`; `_rr` lives in `_process_symbol`; the exit-plan `estimate_rr` sites are 2, not 3. The new fields were moved onto `TradeExit` so `mergePlan` carries them.
