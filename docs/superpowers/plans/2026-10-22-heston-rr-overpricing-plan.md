# HESTON-RR-OVERPRICING — measurement plan (r1, 2026-10-22)

**Board item:** #335 (is the tracking issue) · **Phase id:** `HESTON-RR-OVERPRICING`
**Branch:** `board/heston-rr-overpricing-fd5b379b` (from `origin/main` `9e2641ac`, which includes #174 / PR #521)
**Decision so far:** Kenneth on #174, Q3 → A: measure in a separate item and decide. **This phase changes no pricing, R/R, grid or label.** It ends with evidence, options with their measured card-level effect, and numbered questions for Kenneth (`needs-kenneth`). The chosen change, if any, is built afterwards under its own plan and audits.

## 1. The question

A calibrated Heston fit can price the scored contract above its own chain mid. Measured in 2026-09 over 96 synthetic cells: up to 1.36× at long DTE, with wings down to 0.48×. Every winner sat on 4 of 4 grid boundaries and broke the Feller condition by 4.5×. On a "Heston repriced" card, R/R uses a Heston exit premium at the target (`reward_risk.estimate_rr` / `estimate_targets`, called by `trade_plan`). R/R is `(exit − premium) / premium`, with the full premium as the risk leg. A fit biased high therefore inflates R/R.

Where R/R reaches the user (verified at `9e2641ac`):
- the card's R/R and its target ladder;
- the Step 7 context rail grade, `rrRatio >= 2.0` → PASS, `>= 1.5` → CAUTION, else REJECT (`frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx:219`);
- the picked-target mapping in `services/picked_method.py`, which reads the stored `rrRatio` rows.

No ranking, contract-score or auto-trader gate reads `rrRatio`; T1 re-verifies this by grep and records the result. **"Card-level effect" below therefore means: the change in displayed R/R, and whether the Step 7 grade band changes.**

## 2. Measurements

All read-only, no network, no database, Python 3.11. Scripts live under `backend/scripts/`; outputs (JSON + Markdown) under `docs/superpowers/measurements/2026-10-22-heston-rr-overpricing/`. Every number in the report is printed by a script, never typed.

**M1 — Reach on real scans.** The committed scan results under `docs/superpowers/measurements/scans/` (2026-09-18, 2026-10-01, 2026-10-09) hold every card's `rrModel`.
- Count "Heston repriced" against the other labels, per scan, horizon and direction. A first grep gives 18 of 248 option cards; T1 produces the exact table.
- For each Heston card, recompute its R/R with `heston_params=None` through the shipped `trade_plan` / `reward_risk` code, using that card's stored inputs (spot, strike, expiry, premium, target ladder, direction, horizon). That gives the "BS repriced (IV-derived)" R/R the card would have shown.
- Report the per-card difference and any Step 7 grade-band change.
- A card whose stored fields cannot reproduce its own displayed R/R at its recorded label (a sanity check, run first) is listed as `not-reproducible` with the reason and excluded from the effect counts. It is never silently fixed.

**M2 — Synthetic sweep, 96 cells, on current `main`.**
- Cells: 6 expiries (30, 45, 60, 90, 180, 365 DTE) × 4 chain widths (15, 25, 40, 60 strikes) × 4 smile regimes. The regimes are ATM vol 0.20 or 0.35, each with a mild or steep skew: `iv(k) = atm + skew·ln(K/S) + 0.5·ln(K/S)²`, skew −0.10 (mild) or −0.30 (steep), with spot 100 and r 0.05.
- Mids are Black-Scholes at `iv(k)`. Strikes are spaced evenly over ±40 % log-moneyness. The chain is filtered with the same rule as `scan.py`'s `heston_chain`. `_heston_delta_ok` is nested inside `_process_symbol` and cannot be imported, so the probe re-implements it: `|delta|` within `[hard_reject_delta_band() min − _HESTON_DELTA_SAFETY_MARGIN, max + margin]`, rounded to 6 dp and clamped to [0, 1], with delta 0 kept (fail open), and `price > 0`. It reads `hard_reject_delta_band` and `_HESTON_DELTA_SAFETY_MARGIN` from the app, not copied constants. T1's test pins this re-implementation against `scan.py`'s source block, so a change there fails the test.
- Each cell calibrates with the shipped `calibrate_heston` and records: method (`heston_grid` / `bs_flat` / `bs_fallback`), rel-RMSE, boundary hits, Feller ratio, and calibration seconds.
- For accepted fits: Heston ÷ mid for the scored proxy (the in-band call with |delta| closest to 0.50) and for every in-band strike. Also the R/R pair (Heston vs `heston_params=None`) for a +5 % and a +10 % target at the default repricing horizon.

**M3 — Real chains.** Use the five committed Tradier captures, `backend/scripts/out/tradier_chain_raw/*/rows.json` (2026-10-03 to 05).
- For every symbol × expiry × right with at least 3 two-sided, in-band contracts, build `heston_chain` exactly as `scan.py` does (price = mid, delta band) and calibrate with shipped code.
- Record the same per-fit quantities as M2, plus Heston ÷ mid per in-band contract and the R/R pair for the scored proxy.
- Captures whose quotes are not two-sided are skipped and counted.

**M4 — Options and their effect.** Each option is evaluated on M1's Heston cards (where reproducible), on M3's real fits, and on M2's cells. For each it reports: how many cards' R/R change by more than 0.05; how many change Step 7 grade band; calibration-time change against the 2.0 s scan guard (more time means more symbols abandoned and so fewer Heston cards); and the remaining Heston ÷ mid distribution.
- **A. Widen the grid.** First the shipped 3-rung `HESTON_FULL_CALIBRATION` grid. Then a prototype wider box: kappa {0.5, 1.5, 3, 6}, theta {0.02, 0.04, 0.08, 0.16, 0.25}, sigma_v {0.2, 0.4, 0.6, 0.9, 1.2}, rho {−0.95, −0.8, −0.5, −0.2}. The prototype is passed to the shipped search code by monkeypatch inside the script only.
- **B. Absolute fit-error limit.** A fit with rel-RMSE above L falls back to BS (IV-derived). L is swept over {0.05, 0.10, 0.20, 0.30}, and the share of cards losing "Heston repriced" is reported for each value.
- **C. Anchor Heston to the market.** Exit premium = `heston(target) × mid / heston(now)` for the scored contract. This keeps Heston's shape but removes the level bias.
- **D. Leave as is.**

The prototypes for A–C exist only inside the measurement scripts; nothing under `backend/app` changes.

## 3. Independent recompute

After T2, a fresh independent subagent recomputes, from this plan and the raw inputs only, with its own code:
- the M1 counts;
- three M1 cards' R/R pairs;
- three M2 cells and three M3 fits (ratio and R/R pair);
- one option's effect count.

It records agreement or the exact differences in `recompute.md`. Disagreements are resolved before the report is final. This recompute is evidence for the acceptance criterion; it is not an audit round.

## 4. Tickets

- **T1** — `backend/scripts/heston_rr_overpricing_probe.py` (M1–M3) and its outputs, with a small test (`backend/tests/test_heston_rr_overpricing_probe.py`). The test covers chain-building parity with `scan.py`: the same input rows give the same `heston_chain` as a `_process_symbol` run with calibration captured, and the delta-band constants are read from the app. It also covers the `not-reproducible` sanity check, on a fixture card. M1's card inputs come from each card's `price`, `contract`, `contractDetails` (strike, expiry, right, mid, dte, iv), `exit` (target ladder) and the scan's `.request.json` (direction, horizon, overrides).
- **T2** — M4 option evaluation (same script, an `--options` mode) and `report.md`: tables, the effect counts, and a one-paragraph summary per option. Then the independent recompute (§3).
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
