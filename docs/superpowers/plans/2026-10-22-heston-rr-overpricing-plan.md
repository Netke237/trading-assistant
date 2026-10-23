# HESTON-RR-OVERPRICING — measurement plan (r1, 2026-10-22)

**Board item:** #335 (is the tracking issue) · **Phase id:** `HESTON-RR-OVERPRICING`
**Branch:** `board/heston-rr-overpricing-fd5b379b` (from `origin/main` `9e2641ac`, which includes #174 / PR #521)
**Decision so far:** Kenneth on #174, Q3 → A: measure in a separate item and decide. **This phase changes no pricing, R/R, grid or label.** It ends with evidence, options with their measured effect on fits and the exit gap on real cards, and numbered questions for Kenneth (`needs-kenneth`). The chosen change, if any, is built afterwards under its own plan and audits.

## 1. The question

A calibrated Heston fit can price the scored contract above its own chain mid. Measured in 2026-09 over 96 synthetic cells: up to 1.36× at long DTE, with wings down to 0.48×. Every winner sat on 4 of 4 grid boundaries and broke the Feller condition by 4.5×. On a "Heston repriced" card, the Heston fit prices the option at each target (the **exit premium**). R/R on the current basis (decision D5, 2026-10-05) is `(exit − premium) / premium`, with the full premium as the risk leg. A fit biased high therefore inflates R/R.

Where the Heston exit premium reaches the user (verified at `9e2641ac`):
- the card's headline `rrRatio` (T1);
- the card's target ladder: each level's "Est. option" (`estimatedOptionPrice`) and `rrContribution` for T1–T3 (`TradeCard`);
- each **alternative contract's** `rrRatio` (`AlternativeContractRow`). `scan.py`'s alternatives loop calls `estimate_rr(..., heston_params=heston_params)` **without** `reprice_years`, so alternatives use the half-expiry default horizon, not the card's;
- the Step 7 context rail grade, `rrRatio >= 2.0` → PASS, `>= 1.5` → CAUTION, else REJECT (`frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx:219`).

`services/picked_method.py` reads the exit-plan R-multiple, not the option R/R, so it is not a consumer. No ranking, contract-score, sizing or auto-trader gate reads the card's `rrRatio`; T1 re-verifies this by grep and records the result. **"Effect" below means: the change in each displayed value above (headline R/R, ladder T1–T3 est. option and R/R contribution, alternatives' R/R), and whether the Step 7 grade band changes.**

## 2. Measurements

All read-only, no network, no database, Python 3.11, rate `r = 0.05` (what `scan.py` passes to `calibrate_heston`). Scripts live under `backend/scripts/`; outputs (JSON + Markdown) under `docs/superpowers/measurements/2026-10-22-heston-rr-overpricing/`. Every number in the report is printed by a script, never typed. Before **every** calibration the probe calls `heston_cache._run_calibration.cache_clear()`. Its `lru_cache` is keyed on the chain, not the grid, so a repeated or grid-switched chain would otherwise return a stale result and a timing of about 0 s.

**M1 — Reach and exit gap on the committed real scans.** Committed results live under `docs/superpowers/measurements/scans/` (2026-09-18, 2026-10-01, 2026-10-09).
- They are **old-schema blobs** (`schema_version: 2`, no `exit.rrRiskBasis`). Their stored `rrRatio` uses the pre-D5 premium-stop basis `(exit − premium)/(0.60 × premium)`. Neither today's frontend nor the backend loads them. The report says this, and **no stored `rrRatio` is compared with a shipped-code R/R**.
- **Counts.** "Heston repriced" against other labels, separately for headline cards and alternative rows, per scan, horizon and direction. A first count: 10 of 94 option cards and 7 of 114 alternative rows.
- **Input-recovery check.** For every **non-Heston** card, re-run the shipped `build_trade_plan` (with `heston_params=None`) from the card's stored inputs:
  - `price`, `contractDetails` (strike, expiry, right, mid, dte);
  - the stored entry quote fields;
  - the stored target and stop;
  - the scan's `.request.json` (direction, horizon preset, hold window, overrides).

  It must reproduce the card's stored ladder `estimatedOptionPrice` values to ±$0.01. A card that fails is listed `not-reproducible` with the differing field. If more than 10 % fail, M1's counterfactuals are reported as unreliable.
- **Counterfactual for Heston cards.** For each Heston card and Heston alternative, using the same recovered inputs, compute the shipped non-Heston exit premiums:
  - the ladder through `build_trade_plan` with `heston_params=None`;
  - alternatives through `estimate_rr` at their own half-expiry default, as `scan.py` calls it.

  Report the stored Heston exit premium ÷ that BS exit premium per level. Report both R/Rs **on the current full-premium basis**: Heston R/R = (stored Heston exit − premium) / premium, and BS R/R from shipped code. Report the Step 7 band each R/R falls in.
- The stored cards carry **no Heston parameters, fit error or calibration chain**. So M1 cannot reproduce a Heston number, and cannot evaluate any option. It reports reach and the exit gap only.

**M2 — Synthetic sweep, 96 cells, on current `main`.**
- Cells: 6 expiries (30, 45, 60, 90, 180, 365 DTE) × 4 chain widths (15, 25, 40, 60 strikes) × 4 smile regimes. The regimes are ATM vol 0.20 or 0.35, each with a mild or steep skew: `iv(k) = atm + skew·ln(K/S) + 0.5·ln(K/S)²`, skew −0.10 (mild) or −0.30 (steep). Spot is 100.
- Mids are Black-Scholes at `iv(k)` (one right per chain, calls and puts as separate chains), rounded to $0.01, with delta rounded to 4 dp as `market.py` does. Strikes are spaced evenly over ±40 % log-moneyness.
- The chain is filtered with `scan.py`'s `heston_chain` rule. `_heston_delta_ok` is nested inside `_process_symbol` and cannot be imported, so the probe re-implements it:
  - `|delta|` within `[hard_reject_delta_band()` min − `_HESTON_DELTA_SAFETY_MARGIN`, max + margin], rounded to 6 dp and clamped to [0, 1];
  - delta 0 kept (fail open);
  - `price > 0`.

  It reads `hard_reject_delta_band` and `_HESTON_DELTA_SAFETY_MARGIN` from the app, not copied constants. T1's test pins this re-implementation against `scan.py`'s source block, so a change there fails the test.
- Each cell calibrates with the shipped `calibrate_heston` and records: method, rel-RMSE, boundary hits, Feller ratio, and single-thread calibration seconds.
- **Exit gaps** for accepted fits: Heston ÷ mid now, for the scored proxy (the in-band contract with |delta| closest to 0.50) and for every in-band strike.
  - The scored proxy's exit premium Heston ÷ BS-IV at stock moves of +5 %, +10 % and +15 % (puts: −5/−10/−15 %), with R/Rs on the full-premium basis (premium = mid).
  - Each is computed at the **card horizon**, `reprice_years = display_reprice_years(preset, hold_min, hold_max, dte)`, for the two committed options protocol requests: Swing and Position, with the `hold_min`/`hold_max` in `docs/superpowers/measurements/protocol-requests/options-*.request.json`.
  - It is also computed at the **alternatives horizon** (the half-expiry default).

**M3 — Real chains.** Use the five committed Tradier captures, `backend/scripts/out/tradier_chain_raw/*/rows.json` (2026-10-03 to 05; near-dated expiries only, which the report states).
- Chain rows come from the **shipped** `market.fetch_option_chain_async`, called with an httpx mock transport that returns the capture's own `raw` Tradier records for that symbol, expiry and right. IBKR/tastytrade/yfinance enrichment is patched to no-ops; they only add IV-rank fields, which calibration does not read. The rows are therefore exactly what the app builds (one-sided `bid = 0` rows included, `ask <= 0` dropped, mid and delta rounded as shipped).
- **Replay date and caches.** The shipped function computes `dte` from `date.today()` and caches expiry lists per symbol in the module-level `market._expirations_cache`. So for each capture × symbol replay the probe:
  - patches `market.date` with a `date` subclass whose `today()` returns the capture's ET date, from `meta.capture_et`;
  - clears `market._expirations_cache` (and any other per-symbol cache the function reads) before the call;
  - has the mock answer the expirations endpoint with exactly that capture's expiry list for the symbol, and fail loudly (raise, not 404) on any request for an expiry or symbol the capture does not hold.

  Every symbol × expiry × right that comes back with 0 rows, or with fewer than 3 rows after filtering, is **counted and listed** in the output, with the reason. None is silently dropped. The report states per capture how many chains were calibrated.
- They are then filtered with the same `heston_chain` rule as M2. No "two-sided only" filter is applied; a two-sided-only run, if added, is a separately labelled variant.
- **Spot** is not in the captures. Per capture × symbol it is taken from put–call parity at the strike nearest the money that has both a two-sided call and a two-sided put on the same expiry: `S = C_mid − P_mid + K·e^{−rT}`. The value and the strike used are recorded. Where no such pair exists, the symbol is skipped and counted. Parity spot has no dividend term, and the report says so.
- Each symbol × expiry × right with at least 3 rows after filtering is calibrated with shipped code. The same quantities as M2 are recorded (both horizons).

**M4 — Options and their effect, on fits.** Each option is evaluated on M2's cells and M3's real fits only. Results are reported as **fits, never as cards**, because no stored card carries what an option needs. For each option and each fit, the probe reports:
- the remaining Heston ÷ mid;
- the change in the scored proxy's exit premium and R/R at T1–T3 (both horizons);
- whether the Step 7 band changes;
- whether the fit would still label its card "Heston repriced";
- single-thread calibration seconds, **relative to the default grid only**. Scan abandonment at the 2.0 s guard is driven by GIL queueing under concurrency (`heston_latency_probe.py`), so isolated timings are not abandonment rates and are not reported as such.

The options:
- **A. Widen the grid.** First the shipped 3-rung `HESTON_FULL_CALIBRATION` grid, run through the shipped code with `_USE_FULL_GRID` patched and the cache cleared. Then a wider box: kappa {0.5, 1.5, 3, 6}, theta {0.02, 0.04, 0.08, 0.16, 0.25}, sigma_v {0.2, 0.4, 0.6, 0.9, 1.2}, rho {−0.95, −0.8, −0.5, −0.2}. The shipped grids are local variables in `_run_calibration`, so this runs through a **script-local copy** of `_run_calibration` that takes the grids as arguments. A test pins that copy against the shipped function: same method, rmse and params on the default grid for fixture chains.
- **B. Absolute fit-error limit.** A fit with rel-RMSE above L would fall back to BS (IV-derived). L is swept over {0.05, 0.10, 0.20, 0.30}, and the share of **fits** losing "Heston repriced" is reported for each value.
- **C. Anchor Heston to the market.** Exit premium = `heston(target) × mid / heston(now)` for the scored proxy. This keeps Heston's shape and removes the level bias.
- **D. Leave as is.**

The prototypes for A–C exist only inside the measurement scripts; nothing under `backend/app` changes.

## 3. Independent recompute

After T2, a fresh independent subagent recomputes, from this plan and the raw inputs only, with its own code:
- the M1 counts;
- three M1 Heston cards' exit gaps and full-basis R/R pairs;
- three M2 cells and three M3 fits (ratio and R/R pair);
- one option's effect count.

It records agreement or the exact differences in `recompute.md`. Disagreements are resolved before the report is final. This recompute is evidence for the acceptance criterion; it is not an audit round.

## 4. Tickets

- **T1** — `backend/scripts/heston_rr_overpricing_probe.py` (M1–M3) and its outputs, with tests in `backend/tests/test_heston_rr_overpricing_probe.py`:
  - the `heston_chain` re-implementation matches `scan.py`'s source block and reads the app's constants;
  - the M3 replay, run for **two captures in one process** (one of them dated 2026-10-03, one 2026-10-05), makes the shipped `fetch_option_chain_async` return exactly each capture's rows: row count, ids, expiry, mids, and **`dte` equal to each capture row's stored `dte`**;
  - put–call-parity spot on a fixture;
  - M1 input recovery reproduces a fixture non-Heston card's ladder to ±$0.01;
  - `cache_clear` is called before each calibration (a spy).
- **T2** — M4 option evaluation (an `--options` mode of the same script, including the script-local `_run_calibration` copy and its pin test) and `report.md`: tables, effect counts on fits, a one-paragraph summary per option, and the stated limits. Then the independent recompute (§3).
- Afterwards: the code audit on `origin/main..branch` (cap 3), then a PR that **refers to #335 without closing it**. Self-merge only under `board.md` step 7. Then numbered questions on #335, `needs-kenneth`, and the claim is released.

## 5. Gate briefing

For this evidence phase the gate is: a finding blocks only if the evidence or report would put a **wrong number or wrong verdict in front of Kenneth**, or if the diff changes application code, pricing, persisted data, or fixtures shared with other lanes. Examples: a ratio computed against the wrong mid, a chain built differently from `scan.py`, an option effect count that miscounts, or a check claimed as run that did not run. Wording and style are not reported.

## 6. Limits stated up front

- M1 uses three days of real scans and M3 uses five captures from 3–5 October. That is real, but it is not a long history, and the report says so.
- #174's per-scan summary line only appears on live scans after deployment. That evidence needs the mini PC and is listed as pending, not as measured.
- Calibration latency is measured on this cloud box. Per the earlier GIL measurements, the mini PC's absolute numbers differ, so the report compares options relative to each other.

## 7. Ratings and milestones

Size **L**; complexity **4** (numerical, multi-source evidence; prototypes must not leak into the app). For this evidence phase:
- 10 % plan drafted · 20 % plan audit clean · 50 % T1 evidence exists · 70 % T2 and the independent recompute agree · 85 % code audit clean · 95 % PR exact-head CI green · then `needs-kenneth` with the questions.
- The build of the chosen option is a later milestone set, after Kenneth's answer.
