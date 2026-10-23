# HESTON-RR-OVERPRICING — independent recompute (plan §3)

**What this is.** A fresh subagent recomputed the plan §3 items with its own code. It worked from the plan (`docs/superpowers/plans/2026-10-22-heston-rr-overpricing-plan.md`) and the raw inputs only. It did not author the probe or the evidence and has no stake in either. Branch `board/heston-rr-overpricing-fd5b379b` at `f9e405b5`, Python 3.11.17, `r = 0.05`, no network (sockets were patched to raise), no database. This is evidence for the acceptance criterion. It is **not** an audit round.

**Independence.** `backend/scripts/heston_rr_overpricing_probe.py` was neither imported nor called, and its source was not read. The recompute calls only the shipped functions being measured:
- `calibrate_heston`, `heston_price` and `heston_price_detail`;
- `heston_cache._run_calibration.cache_clear()`, called before **every** calibration;
- `build_trade_plan`, `estimate_rr` and `display_reprice_years`;
- `bs_iv` and `bs_price`, inside `estimate_rr` and for the raw-exit cross-check;
- `market.fetch_option_chain_async`, `hard_reject_delta_band()` and `scan._HESTON_DELTA_SAFETY_MARGIN`.

Everything else is the recompute's own code: the scan walking and counting, the synthetic chain builder (with its own Black–Scholes price and delta), the `heston_chain` rule, the httpx mock and replay, the parity spot, the proxy choice and the band grading. The scripts live outside the repo, in the session scratchpad's `recompute/` folder (`rc_common.py`, `rc_m1.py`, `rc_m2.py`, `rc_m3.py`, `rc_spots.py`, `rc_optB.py`, `rc_allfits.py`). They are not committed.

**Tolerances.** Counts must match exactly. Deterministic prices and ratios must agree to 1e-6 relative. In practice every compared value below agrees **bit for bit (difference 0)**, except where a row says otherwise.

## Summary

| # | Item | Verdict |
|---|---|---|
| 1 | M1 counts: cards and alternatives by label, per scan and per horizon/direction | **AGREE** (all exact) |
| 2 | Three M1 Heston cards: T1 Heston÷BS exit, both full-basis R/Rs, Step 7 bands | **AGREE** (difference 0) |
| 3 | Three M2 cells: proxy Heston÷mid; +10 % exit Heston÷BS-IV at the Position card horizon; R/R pair | **AGREE** (difference 0) |
| 4 | Three M3 fits, one per capture: same quantities | **AGREE** under m3.md's stated spot rule (difference 0). See note 4a on the plan's wording |
| 5 | Option B, L = 0.05: fits losing "Heston repriced" | **AGREE**: 39 (37 M2 + 2 M3), from options.json's D records, from 5 spot-check recalibrations, **and** from a full recalibration of all 326 fits |

There is no unresolved disagreement. One observation needs attention: the plan's wording of the parity-spot rule is ambiguous (4a). m3.md states the rule the probe used, and the recompute reproduces it on 35 of 35 capture × symbol spots.

## 1. M1 counts

**Method.** The recompute walked `docs/superpowers/measurements/scans/*/*.result.json` in sorted order. A result counts as an options result when it carries `schema_version == 2`. This was cross-checked against the filename (`stocks-*` / `*-stocks-*` mean stocks), and the two agree on every file. For each options result it counted:
- `candidates[].rrModel`;
- `candidates[].alternatives[].rrModel`.

Horizon and direction come from the sibling `.request.json`. No alternative row has a `spreadType`, so every row is a single-contract alternative.

| quantity | recompute | probe (`m1.json` / `m1.md`) | verdict |
|---|---|---|---|
| options result files | 22 | 22 | AGREE |
| headline cards | 94 | 94 | AGREE |
| … "Heston repriced" | 10 | 10 | AGREE |
| … other labels | `BS repriced (IV-derived)`: 84 | `BS repriced (IV-derived)`: 84 | AGREE |
| alternative rows | 114 | 114 | AGREE |
| … "Heston repriced" | 7 | 7 | AGREE |
| … other labels | `BS repriced (IV-derived)`: 107 | `BS repriced (IV-derived)`: 107 | AGREE |
| Position/Bearish: cards / Heston / alts / Heston alts | 32 / 4 / 31 / 3 | 32 / 4 / 31 / 3 | AGREE |
| Position/Bullish | 56 / 6 / 74 / 4 | 56 / 6 / 74 / 4 | AGREE |
| Swing/Bearish | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | AGREE |
| Swing/Bullish | 6 / 0 / 9 / 0 | 6 / 0 / 9 / 0 | AGREE |
| per-scan rows (22 scans × 4 counts) | 22 of 22 identical | — | AGREE |

## 2. Three M1 Heston cards

**Which cards.** The first three Heston headline cards in sorted file order:
- CVX, `2026-09-18/sp500-position-bullish`;
- CSCO, `2026-10-01/C5-options-position-bearish`;
- MSFT, `2026-10-01/C5b-options-position-bullish` (first in candidate order; XOM follows it).

**Method.** The shipped `build_trade_plan(heston_params=None)` was called with these inputs:
- from the card: `price`, `contractDetails` (strike, dte, mid as premium and entry mid), `exit.target` and `exit.invalidation`;
- `rr_cfg = {premium_stop_pct: 0.60}`;
- from the scan's request: `horizon_preset`, `hold_min_days` and `hold_max_days`;
- `stop_cost_fraction = stopCostPct / 100`.

A run with `stop_cost_fraction = None` gave identical exits and R/R on all three cards. The quantities are:
- Heston exit = the stored `exit.targets[0].estimatedOptionPrice`;
- BS exit = the shipped plan's T1 `estimatedOptionPrice`;
- Heston R/R = round((Heston exit − mid) / mid, 2);
- BS R/R = the shipped plan's `rr_ratio` (`rr_risk_basis = full_premium`);
- bands: ≥ 2.0 PASS, ≥ 1.5 CAUTION, else REJECT.

The stored pre-D5 `rrRatio` (2.19, 1.04, 1.64) was **not** compared with anything.

| card | quantity | recompute | probe (`m1.json` heston_cards) | diff | verdict |
|---|---|---|---|---|---|
| CVX\|220\|2026-11-20\|C (mid 6.08) | card reprice_years | 0.13424657534246576 | 0.13424657534246576 | 0 | AGREE |
| | T1 Heston exit (stored) | 14.06 | 14.06 | 0 | AGREE |
| | T1 BS exit (shipped) | 13.74 | 13.74 | 0 | AGREE |
| | Heston ÷ BS | 1.0232896652110626 | 1.0232896652110626 | 0 | AGREE |
| | Heston R/R / BS R/R | 1.31 / 1.26 | 1.31 / 1.26 | 0 / 0 | AGREE |
| | bands H → BS | REJECT → REJECT | REJECT → REJECT | — | AGREE |
| CSCO\|110\|2026-11-20\|P (mid 7.33) | card reprice_years | 0.09863013698630137 | 0.09863013698630137 | 0 | AGREE |
| | T1 Heston / BS exit | 11.90 / 11.88 | 11.90 / 11.88 | 0 / 0 | AGREE |
| | Heston ÷ BS | 1.0016835016835017 | 1.0016835016835017 | 0 | AGREE |
| | Heston R/R / BS R/R | 0.62 / 0.62 | 0.62 / 0.62 | 0 / 0 | AGREE |
| | bands H → BS | REJECT → REJECT | REJECT → REJECT | — | AGREE |
| MSFT\|520\|2026-11-20\|C (mid 23.70) | card reprice_years | 0.09863013698630137 | 0.09863013698630137 | 0 | AGREE |
| | T1 Heston / BS exit | 47.02 / 46.92 | 47.02 / 46.92 | 0 / 0 | AGREE |
| | Heston ÷ BS | 1.0021312872975277 | 1.0021312872975277 | 0 | AGREE |
| | Heston R/R / BS R/R | 0.98 / 0.98 | 0.98 / 0.98 | 0 / 0 | AGREE |
| | bands H → BS | REJECT → REJECT | REJECT → REJECT | — | AGREE |

T2 and T3 were compared as well, beyond what was asked. All six levels agree exactly with the probe on exits, ratio, both R/Rs and bands.

**Note 2a (within tolerance, not a disagreement).** On CSCO and MSFT, the shipped code rounds T1 to cents *before* it builds the ladder. So the recomputed T2/T3 stock targets are 1 cent below the stored ones:
- CSCO: 95.14 vs 95.15;
- MSFT: 578.29 vs 578.30, and 598.94 vs 598.95.

The cards were scanned before that rounding shipped. The difference is inside the plan's ±$0.01 input-recovery tolerance, which is why the probe marks `target_reproduced: true`. It does not touch T1, and the BS exits at T2/T3 still equal the probe's.

## 3. Three M2 cells

**Method.** The recompute built its own chain per plan §2 M2:
- S = 100; strikes K = 100·e^x for x evenly spaced over [−0.4, 0.4] (width points, unrounded);
- iv = atm + skew·ln(K/S) + 0.5·ln(K/S)²;
- mid = its own Black–Scholes price at r = 0.05, T = dte/365, rounded to $0.01. Its maximum difference from the app's `bs_price` was 1.4e-14;
- delta = N(d1), or N(d1) − 1 for puts, rounded to 4 dp.

It then applied its own re-implementation of `scan.py`'s `heston_chain` rule. The band is [max(0, round(min − margin, 6)), min(1, round(max + margin, 6))] = **[0.15, 0.90]**, with delta 0 kept and price > 0. The margin and the band are read from the app.

After `cache_clear()`, it ran `calibrate_heston(chain, 100, 0.05)`. The scored proxy is the row with price > 0 and |delta| in `hard_reject_delta_band()` = [0.20, 0.85] whose |delta| is closest to 0.50. The quantities are:
- Heston now = `heston_price(S, K, dte/365, r, params, is_call)`;
- exits from shipped `estimate_rr`, with `reprice_years = display_reprice_years("Position", 15, 45, dte)` and target = S × 1.10 (calls) or S × 0.90 (puts);
- Heston÷BS = the ratio of the two cents-rounded `estimated_exit_premium` values. That is what the probe reports and what a card displays. The unrounded ratio is given for reference.

| cell | quantity | recompute | probe (`m2.json`) | diff | verdict |
|---|---|---|---|---|---|
| 30 DTE / 15 / atm20_mild / C | chain rows → heston_chain rows | 15 → 3 | 15 → 3 | 0 | AGREE |
| | method, rel-RMSE | heston_grid, 0.011137 | heston_grid, 0.011137 | 0 | AGREE |
| | params (v0, κ, θ, σv, ρ) | 0.04024036, 0.5, 0.02, 0.2, −0.2 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 100.0, 0.54, 2.49; 1 | 100.0, 0.54, 2.49; 1 | 0 | AGREE |
| | Heston now ÷ mid | 0.9969646378179298 | 0.9969646378179298 | 0 | AGREE |
| | Position reprice_years | 0.043835616438356165 | 0.043835616438356165 | 0 | AGREE |
| | +10 % exit H / BS | 10.24 / 10.23 | 10.24 / 10.23 | 0 | AGREE |
| | Heston ÷ BS (rounded exits) | 1.0009775171065494 (unrounded 1.000389) | 1.0009775171065494 | 0 | AGREE |
| | R/R H / BS; bands | 3.11 / 3.11; PASS / PASS | 3.11 / 3.11; PASS / PASS | 0 | AGREE |
| 180 / 40 / atm35_steep / P | chain rows → heston_chain rows | 40 → 29 | 40 → 29 | 0 | AGREE |
| | method, rel-RMSE | heston_grid, 0.078714 | heston_grid, 0.078714 | 0 | AGREE |
| | params | 0.13811696530991735, 0.5, 0.08, 0.6, −0.8 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 105.26197441660045, −0.498, 10.93; 22 | same; 22 | 0 | AGREE |
| | Heston now ÷ mid | 0.9779308526534463 | 0.9779308526534463 | 0 | AGREE |
| | Position reprice_years | 0.4547945205479452 | 0.4547945205479452 | 0 | AGREE |
| | −10 % exit H / BS | 15.67 / 16.62 | 15.67 / 16.62 | 0 | AGREE |
| | Heston ÷ BS (rounded exits) | 0.9428399518652225 (unrounded 0.943122) | 0.9428399518652225 | 0 | AGREE |
| | R/R H / BS; bands | 0.43 / 0.52; REJECT / REJECT | 0.43 / 0.52; REJECT / REJECT | 0 | AGREE |
| 365 / 15 / atm20_steep / C | chain rows → heston_chain rows | 15 → 10 | 15 → 10 | 0 | AGREE |
| | method, rel-RMSE | heston_grid, 0.05367 | heston_grid, 0.05367 | 0 | AGREE |
| | params | 0.058990694399999995, 0.5, 0.08, 0.6, −0.8 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 105.88070577429671, 0.5213, 7.02; 7 | same; 7 | 0 | AGREE |
| | Heston now ÷ mid | 1.0960705576888412 | 1.0960705576888412 | 0 | AGREE |
| | Position reprice_years | 0.9616438356164384 | 0.9616438356164384 | 0 | AGREE |
| | +10 % exit H / BS | 15.00 / 12.99 | 15.00 / 12.99 | 0 | AGREE |
| | Heston ÷ BS (rounded exits) | 1.1547344110854503 (unrounded 1.155136) | 1.1547344110854503 | 0 | AGREE |
| | R/R H / BS; bands | 1.14 / 0.85; REJECT / REJECT | 1.14 / 0.85; REJECT / REJECT | 0 | AGREE |

## 4. Three M3 fits (one per capture)

**Which fits.** Three accepted `heston_grid` fits from `m3.json`, each from a different capture:
- MSFT 2026-10-30 C, `20261003T210145Z_weekend`;
- LYB 2026-11-20 P, `20261005T160001Z_in-session`;
- AAPL 2026-10-12 P, `20261005T204500Z_after-close`.

**Replay method.** The recompute used its own `httpx.MockTransport` handler. It answers `/v1/markets/options/expirations` with exactly `meta.expiries[symbol]` and `/v1/markets/options/chains` with the capture's own `raw` records for that symbol and expiry. It **raises** on any other symbol, expiry or path. Before each call it:
- patched `market.date` with a `date` subclass whose `today()` is the date of `meta.capture_et` (ET);
- cleared `market._expirations_cache`;
- patched IBKR, tastytrade and the yfinance IV backfill (`_yf_iv_for_chain`) to no-ops;
- left `socket.connect` / `create_connection` raising.

The shipped `fetch_option_chain_async` was then called for every expiry × right of the symbol.

**Replay checks.** On all 12 replayed chains (3 symbols × 2 expiries × C/P), the app's row count equals the capture's rows with ask > 0. Each row's `dte` equals the capture row's stored `dte`, and each mid equals round((bid + ask)/2, 2). No request raised.

**Spot.** S = C_mid − P_mid + K·e^(−rT), over every strike where both the call and the put are two-sided (raw bid > 0 and ask > 0), on every expiry of the symbol. Mids and dte come from the replayed app rows. After that come the heston_chain rule, the calibration, the proxy and the exits exactly as in §3. The puts' target is S × 0.90.

| fit | quantity | recompute | probe (`m3.json`) | diff | verdict |
|---|---|---|---|---|---|
| weekend MSFT 2026-10-30 C | parity spot (K, expiry) | 517.7748322846401 (517.5, 2026-10-09) | 517.7748322846401 (517.5, 2026-10-09) | 0 | AGREE |
| | app rows → heston_chain rows | 71 → 23 | 71 → 23 | 0 | AGREE |
| | method, rel-RMSE, params | heston_grid, 0.017028; v0 0.10348809262759925, 0.5, 0.02, 0.2, −0.2 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 520.0, 0.5103, 17.90; 18 | same; 18 | 0 | AGREE |
| | Heston now ÷ mid | 0.9920702599057717 | 0.9920702599057717 | 0 | AGREE |
| | Position reprice_years; +10 % target | 0.03561643835616438; 569.5523155131041 | same | 0 | AGREE |
| | exit H / BS; Heston ÷ BS | 51.41 / 51.38; 1.0005838847800699 | 51.41 / 51.38; 1.0005838847800699 | 0 | AGREE |
| | R/R H / BS; bands | 1.87 / 1.87; CAUTION / CAUTION | same | 0 | AGREE |
| in-session LYB 2026-11-20 P | parity spot (K, expiry) | 58.67310652791895 (60.0, 2026-11-20) † | 58.67310652791895 (60.0, 2026-11-20) | 0 | AGREE † |
| | app rows → heston_chain rows | 20 → 8 | 20 → 8 | 0 | AGREE |
| | method, rel-RMSE, params | heston_grid, 0.015244; v0 0.19063047515625, 0.5, 0.08, 0.2, −0.8 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 60.0, −0.5123, 4.05; 7 | same; 7 | 0 | AGREE |
| | Heston now ÷ mid | 1.0102046029643281 | 1.0102046029643281 | 0 | AGREE |
| | Position reprice_years; −10 % target | 0.08767123287671233; 52.80579587512705 | same | 0 | AGREE |
| | exit H / BS; Heston ÷ BS | 7.53 / 7.54; 0.9986737400530504 | 7.53 / 7.54; 0.9986737400530504 | 0 | AGREE |
| | R/R H / BS; bands | 0.86 / 0.86; REJECT / REJECT | same | 0 | AGREE |
| after-close AAPL 2026-10-12 P | parity spot (K, expiry) | 332.9513172011034 (332.5, 2026-10-12) | 332.9513172011034 (332.5, 2026-10-12) | 0 | AGREE |
| | app rows → heston_chain rows | 50 → 10 | 50 → 10 | 0 | AGREE |
| | method, rel-RMSE, params | heston_grid, 0.032134; v0 0.0445125604, 3.0, 0.02, 0.6, −0.8 | same | 0 | AGREE |
| | proxy (K, Δ, mid), in-band count | 332.5, −0.4734, 3.45; 8 | same; 8 | 0 | AGREE |
| | Heston now ÷ mid | 1.0064787335327112 | 1.0064787335327112 | 0 | AGREE |
| | Position reprice_years; −10 % target | 0.004794520547945206; 299.6561854809931 | same | 0 | AGREE |
| | exit H / BS; Heston ÷ BS | 32.76 / 32.76; 1.0 | 32.76 / 32.76; 1.0 | 0 | AGREE |
| | R/R H / BS; bands | 8.50 / 8.50; PASS / PASS | same | 0 | AGREE |

**† Note 4a: the parity-spot pair rule.** The plan says "the strike nearest the money" without naming a reference price or an expiry. The recompute first tried the literal reading: the pair whose strike is nearest its own parity spot (|K − S_K| smallest).

That reading reproduces only **18 of 35** capture × symbol spots in `m3.json`. For the LYB fit above it picks K = 57.5, which gives S = 58.63881042258899 instead of 58.67310652791895 (−0.058 %). That changes the fit:

| quantity | probe's pair (K 60) | literal pair (K 57.5) |
|---|---|---|
| rel-RMSE | 0.015244 | 0.017333 |
| Heston ÷ mid | 1.0102 | 1.0087 |
| −10 % exits H / BS | 7.53 / 7.54 | 7.54 / 7.56 |
| R/R H / BS | 0.86 / 0.86 | 0.86 / 0.87 |
| band | REJECT | REJECT (unchanged) |

m3.md (line 7) states the rule the probe actually used: the pair with the **smallest |C_mid − P_mid|**, which is the strike nearest the *forward*. Taken over all of the symbol's listed expiries, that rule reproduces **35 of 35** spots exactly. The MSFT and AAPL fits are identical under both rules.

**Diagnosis:** this is not a probe error. It is a definitional gap in the plan text, and the probe resolves it in m3.md. The report should keep that sentence. It may also say "across all listed expiries of the symbol", since the chosen pair is sometimes on the other expiry (e.g. MSFT weekend uses 2026-10-09 for a 2026-10-30 fit).

## 5. Option B at L = 0.05: fits losing "Heston repriced"

**Method.** The recompute took (a) a count straight from `options.json`, (b) a 5-fit spot check, and (c) a full recalibration of all fits.

**(a) Count from options.json.** It counted the fits whose `calibrations.D.method == "heston_grid"` and `calibrations.D.rel_rmse > 0.05`, without reading `options.md`'s tables. It also checked those D records against `m2.json` and `m3.json` (192 + 134 fits): **0 mismatches** on method or rel-RMSE.

**(b) Spot check.** It recalibrated 5 fits drawn at random from that set (`random.seed(20261022)`). M2 fits used its own synthetic chain; M3 fits used its own replay and parity spot (m3.md rule). A fresh `cache_clear()` came before each.

**(c) Full recalibration.** It recalibrated **all 326 fits** (192 M2 + 134 M3) under the default grid, with its own chains and spots. That gives a count that does not depend on the probe's outputs at all. No M3 chain had fewer than 3 rows after filtering.

| quantity | recompute | probe | diff | verdict |
|---|---|---|---|---|
| fits with D = heston_grid and rel-RMSE > 0.05, from options.json D records | 39 (M2 37, M3 2) | 39 (37 synthetic, 2 real): `options.md` lines 22/115/208, `report.md` line 102 and `summary.all.B_0.05.label_lost_vs_D` | 0 | AGREE |
| per-fit `options.B_0.05.heston` flag flipped vs D | 39, same set as above | — | 0 | AGREE |
| share of D's Heston fits / of all fits | 39/201 = 19.4 %; 39/326 = 12.0 % | 19.4 %; 12.0 % | 0 | AGREE |
| M2 / M3 shares | 37/170 = 21.8 %, 37/192 = 19.3 %; 2/31 = 6.5 %, 2/134 = 1.5 % | same | 0 | AGREE |
| spot check: m2/365/15/atm20_steep/P | heston_grid, 0.053479 | heston_grid, 0.053479 | 0 | AGREE |
| spot check: m3/…weekend/TSCO/2026-10-30/C | heston_grid, 0.099492 | heston_grid, 0.099492 | 0 | AGREE |
| spot check: m2/180/60/atm20_steep/P | heston_grid, 0.065029 | heston_grid, 0.065029 | 0 | AGREE |
| spot check: m2/180/25/atm35_steep/C | heston_grid, 0.060762 | heston_grid, 0.060762 | 0 | AGREE |
| spot check: m2/90/40/atm35_steep/C | heston_grid, 0.052958 | heston_grid, 0.052958 | 0 | AGREE |
| full recalibration: methods | heston_grid 201, bs_flat 124, bs_fallback 1 | heston_grid 201, bs_flat 124, bs_fallback 1 | 0 | AGREE |
| full recalibration: method and rel-RMSE equal to options.json D, per fit | 326 of 326 ‡ | — | 0 | AGREE |
| full recalibration: count at L = 0.05 / 0.10 / 0.20 / 0.30 | 39 / 4 / 0 / 0 | 39 / 4 / 0 / 0 (label_lost_vs_D) | 0 | AGREE |

‡ The one `bs_fallback` fit (m2/30/15/atm20_mild/P) has rel-RMSE `inf` in shipped code. The probe's JSON stores it as `null`, a serialisation of `inf`, not a disagreement. It is not `heston_grid`, so it cannot enter the count.

## What was not recomputed

- The rest of M1: the 84-card input-recovery sweep, the 7 Heston alternatives and the grep of `rrRatio` consumers. These were outside §3's list.
- Options A and C, and B's per-level exit and R/R deltas and band changes.
- Calibration timings. They are not deterministic and are relative to D only.
- The Swing and half-expiry horizons for the M2/M3 items. §3 here asked for the Position card horizon only, although the same code path was exercised.
