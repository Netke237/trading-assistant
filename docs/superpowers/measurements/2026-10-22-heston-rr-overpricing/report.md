# HESTON-RR-OVERPRICING — evidence report

Phase `HESTON-RR-OVERPRICING`, board item #335. Plan: `docs/superpowers/plans/2026-10-22-heston-rr-overpricing-plan.md`.
This phase changes no pricing, R/R, grid or label. It reports evidence and the measured effect of four options **on fits**; the choice is Kenneth's.

Every number below is printed by `backend/scripts/heston_rr_overpricing_probe.py` into one of the files in this directory, cited in brackets: [m1] = `m1.md`/`m1.json`, [m2] = `m2.md`/`m2.json`, [m3] = `m3.md`/`m3.json`, [opt] = `options.md`/`options.json`. Numbers quoted from the 2026-09 record are cited to `docs/superpowers/PROJECT_STATE.json` `open_questions[13]` [state].

**Status of this report:** T2 output. The independent recompute (plan §3) and the code audit have not run yet. Nothing here is audit-clean.

## 1. What was measured, on what

- **M1**: the committed real option scans (`docs/superpowers/measurements/scans/`, 2026-09-18, 2026-10-01, 2026-10-09). These are old-schema results (schema_version 2): their stored `rrRatio` uses the pre-D5 premium-stop basis. No stored `rrRatio` is compared with a shipped-code R/R. Every R/R in this report is on today's full-premium basis, `(exit − premium) / premium` [m1].
- **M2**: 96 synthetic cells (6 DTE × 4 widths × 4 smile regimes), each a call chain and a put chain: 192 fits on current code [m2].
- **M3**: the five committed Tradier captures (3–5 October 2026, seven symbols, near-dated expiries, dte 6–46), replayed through the shipped `market.fetch_option_chain_async`: 134 calibrated chains [m3].
- **M4**: options A(i), A(ii), B (four limits), C and D evaluated on M2's 192 and M3's 134 fits [opt]. Option D re-calibrates every chain in the same run. It reproduces T1's stored method, rel-RMSE, params, scored proxy, Heston÷mid and exits on 326 of 326 fits [opt, "Consistency with T1"].
- **Scored proxy**: the in-band contract (|delta| inside the hard-reject band) with |delta| closest to 0.50. In M4, T1–T3 use the shipped ladder spacing (T2 = 1.5×, T3 = 2.0× the T1 move) on a fixed 10 % T1 stock move. They are priced at the Swing and Position card horizons and at the alternatives' half-expiry horizon [opt].

**Limits, stated up front (plan §6).**
- M1 covers three days of real scans and M3 five captures from 3–5 October. The data is real, but it is not a long history.
- #174's per-scan summary line only appears on live scans after deployment. That evidence needs the mini PC. It is **pending, not measured**.
- Calibration latency is measured single-thread on this cloud box, with the cache cleared before every calibration. The mini PC's absolute numbers differ, so options are compared relative to D only. These timings are **not** scan abandonment rates: abandonment at the 2.0 s guard is driven by GIL queueing under concurrency.
- M4 results are about **fits**, never cards: no stored card carries the chain, fit or parameters an option needs.
- M3 spot comes from put–call parity with no dividend term: the two-sided call/put pair with the smallest |C_mid − P_mid| (the strike nearest the forward), searched **across all of the symbol's listed expiries in that capture**, so the pair can sit on a different expiry from the fit (`m3.md`; reproduced 35 of 35 by the independent recompute, `recompute.md`). M3 expiries are near-dated only.

## 2. Reach and exit gap on real cards (M1)

- **Reach.** 10 of 94 option cards and 7 of 114 alternative rows were labelled "Heston repriced". Every other card and row was "BS repriced (IV-derived)". All Heston cards and rows come from Position scans; the 6 Swing cards carry none [m1].
- **Input recovery.** The shipped `build_trade_plan(heston_params=None)` reproduces the stored ladder to ±$0.01 on 84 of 84 non-Heston cards, so the counterfactuals are reliable [m1].
- **Cards (card horizon).** Over all 30 Heston-card ladder levels, the stored Heston exit ÷ shipped BS exit is 0.991 / 1.002 / 1.036 (min / median / max). The headline Step 7 band is the same under Heston and BS on all 10 Heston cards (0 of 10 change) [m1].
- **Alternatives (half-expiry horizon).** Heston ÷ BS exit is 0.995 / 1.003 / 1.058 over the 7 rows, with 0 of 7 band changes. Alternatives carry no Step 7 grade of their own [m1].
- **Old-basis caveat.** The comparison uses stored exit premiums, never stored R/Rs. The Heston R/Rs in [m1] are recomputed on the full-premium basis from the stored exit premium.
- No ranking, contract-score, sizing or auto-trader gate reads the card's `rrRatio`: 0 hits in the gate files and 0 sort/rank expressions [m1].

## 3. The bias today (M2, M3)

- **M2 synthetic: 170 of 192 fits accepted.** Scored proxy Heston÷mid is 0.926 / 0.996 / 1.096 (calls 0.926 / 0.996 / 1.096, puts 0.940 / 0.996 / 1.070). The extremes are at long DTE: 0.926 / 0.978 / 1.096 at 365 DTE. In-band strikes run from 0.789 to 1.131 [m2].
- **M2 exit gap.** At the card horizons, the scored proxy's Heston ÷ BS-IV exit runs from 0.915 to 1.155 over all moves. Against BS, at most 5 of 170 fits change band (Position, ±15 %) [m2].
- **M3 real chains: 31 of 134 accepted.** The flat-BS gate rejects most real near-dated chains (103 `bs_flat`). Scored proxy Heston÷mid is 0.938 / 0.992 / 1.099 (calls 0.965 / 0.992 / 1.099, puts 0.938 / 1.004 / 1.027). In-band strikes run from 0.791 to 1.176. Heston ÷ BS exit at the card horizons runs from 0.968 to 1.061. At most 1 of 31 fits changes band [m3].
- **Fit quality.** Every accepted fit sits on the grid's edge in all four searched parameters. On two rungs this is arithmetic, not a finding. The side varies; for example, M2 kappa sits at its minimum in 138 of 170 fits [m2]. The Feller ratio of accepted fits is 0.08 / 2.00 / 18.00 in both M2 and M3 [m2, m3].

On current code and these chains, the scored proxy sits within about ±10 % of its own mid. The exit gap moves the Step 7 band on very few fits.

## 4. Reconciling today's numbers with the 2026-09 figure

The plan quotes the 2026-09 record: up to 1.36× on the scored contract at long DTE, wings down to 0.48×, every winning fit at kappa = 0.5, theta = 0.08, sigma_v = 0.6, rho = −0.8 and violating Feller by 4.5×, worst cell 365 DTE / 15 strikes [state]. Today's maximum is 1.096 in M2 and 1.099 in M3 [m2, m3]. This section sets out what differs.

**Established.**
1. **It is not a code change.** The record was logged by round 2 of TIMEOUT-DELETE-INNER, an F2 follow-up (2026-09-13). It was therefore measured after F1's pricer fix and after F2's relative objective, solved v0 seed and flat-BS gate [state]. `git diff da42ea92 HEAD -- backend/app/models/heston.py backend/app/models/heston_cache.py` shows that the grids, seed, objective, gate and search loop of `_run_calibration` are unchanged since then (da42ea92 is that change's round-2 fix commit). The only change to `heston.py` is DECISION-23 H-1: a no-arbitrage floor at forward intrinsic, which can only raise a deep in-the-money price, and an honest `fell_back` label.
2. **The figure reproduces today on the chain committed with that change.** `backend/scripts/heston_latency_probe.py` was committed with TIMEOUT-DELETE-INNER. It builds its synthetic chain from the spec's reference smile:
   - spot 201.86 and iv = 0.345 + 0.45·(−m) + 1.6·m²;
   - OTM calls above spot and OTM puts below, **in one chain**;
   - strikes on a $2.50 ladder over spot·(1 ± 0.45·√T).

   Today's shipped calibration was run on that chain over the same 6 DTE × 4 widths, calibrating the whole chain as that probe does. Results [opt, "2026-09 reconciliation run"; per-cell values in `options.json` `recon_2026_09.cells`]:
   - all 24 winners sit at kappa = 0.5, theta = 0.08, sigma_v = 0.6, rho = −0.8;
   - the Feller ratio is 4.50 on every cell;
   - scored proxy Heston÷mid is 1.018 / 1.061 / 1.365, rising with DTE to 1.289 / 1.312 / 1.365 at 365 DTE;
   - the worst cell is 365 DTE / 15 strikes, at 1.365.

   The parameter corner, the Feller multiple, the long-DTE maximum and the worst cell all match the record.
3. **scan.py's delta filter removes part of the bias.** Run through scan.py's `heston_chain` rule, the same chain puts 22 of 24 winners at the same corner, with a scored proxy of 1.001 / 1.022 / 1.215 [opt]. A scan never calibrates the whole chain, so 1.365 is not what a scan would produce, even on that smile.
4. **The remaining gap comes from the chain.** M2's chains have one right per chain, skew −0.10 or −0.30, curvature 0.5, spot 100 and ±40 % log-moneyness. On them and on the real M3 chains, winners fall on both sides of every parameter and the maximum is near 1.10 [m2, m3]. In M2 the low-vol, steep-skew regime has the largest proxy maximum (atm20_steep, 1.096) [m2]. That is the direction one would expect if smile steepness drives the bias.

**Hypothesis, not established.**
- **Same chain?** It is not established that the 2026-09 sweep used exactly `heston_latency_probe.chain()`. The sweep's own script and outputs were never committed: no file in the repo holds that sweep. Two details do not fit:
  - the record cites a "180/25 242.5C" contract, and 242.5 is not among the strikes of the 180-DTE / 25-strike chain [`options.json` `recon_2026_09.cells`];
  - the record's "96 cells" is four times the 24 shapes this chain has.
- **The wings.** The "wings down to 0.48×" is not reproduced. On the whole reference chain, out-of-band strikes go down to 0.142 and in-band strikes to 0.563 [opt]. The record's definition of "wings" is unknown.
- **Size of each cause.** The step from 1.215 to about 1.10 is not split between the smile, the mixed-right chain, the spot and ladder, and the strike span. The reconciliation run varies only the filter.

**In plain terms:** the 2026-09 number was real. Today's code still produces it on that very steep, mixed-right synthetic chain when the whole chain is calibrated. On scan-filtered chains with milder smiles, and on the real near-dated chains captured in October, the bias is about a tenth, not a third.

## 5. Options A–D, measured on fits

The table covers M2's 192 fits plus M3's 134, 326 in all. Column meanings:
- **Lost / gained:** fits whose scored proxy would stop or start being labelled "Heston repriced", compared with D.
- **Band changes:** fits whose headline (T1) Step 7 band differs from D's at the Swing or Position card horizon.
- **Calibration time:** single-thread time relative to D on the same chain (median per fit; total = sum over fits). It is **not** an abandonment rate.

All values are from [opt] ("Summary — M2 + M3", and the M2 and M3 sections).

| option | labelled Heston (of 326) | lost vs D | gained vs D | scored proxy Heston÷mid, M2 (min / median / max) | scored proxy Heston÷mid, M3 | headline band changes vs D (share of fits) | calibration time vs D |
|---|---|---|---|---|---|---|---|
| D. Leave as is | 201 | 0 | 0 | 0.926 / 0.996 / 1.096 | 0.938 / 0.992 / 1.099 | 0 (0.0 %) | 1× |
| A(i). 3-rung full grid | 210 | 0 | 9 | 0.928 / 0.996 / 1.050 | 0.943 / 0.998 / 1.098 | 3 (0.9 %) | 4.13× median; total 4.15× |
| A(ii). Wider box | 228 | 0 | 27 | 0.961 / 1.000 / 1.052 | 0.938 / 0.998 / 1.129 | 3 (0.9 %) | 21.50× median; total 21.33× |
| B, L = 0.05 | 162 | 39 (19.4 % of D's 201; 12.0 % of all) | 0 | 0.955 / 0.996 / 1.057 | 0.965 / 0.992 / 1.032 | 1 (0.3 %) | 1× (no recalibration) |
| B, L = 0.10 | 197 | 4 (2.0 % of D's 201; 1.2 % of all) | 0 | 0.926 / 0.996 / 1.096 | 0.938 / 0.992 / 1.099 | 0 (0.0 %) | 1× |
| B, L = 0.20 | 201 | 0 | 0 | as D | as D | 0 (0.0 %) | 1× |
| B, L = 0.30 | 201 | 0 | 0 | as D | as D | 0 (0.0 %) | 1× |
| C. Anchor to mid | 201 | 0 | 0 | 1.000 (by construction) | 1.000 (by construction) | 7 (2.1 %) | 1× (no recalibration) |

In-band Heston÷mid over all fits (min / max) is D 0.789 / 1.176, A(i) 0.788 / 1.145, A(ii) 0.802 / 1.129 and B at L = 0.05 0.926 / 1.057. C anchors the scored proxy only [opt]. Under every option, 0 Heston levels on labelled fits fell back to BS, and 0 T1–T3 Heston ladders were non-increasing [opt].

**A(i): the shipped 3-rung `HESTON_FULL_CALIBRATION` grid.** It accepts 9 more chains than D (7 synthetic, 2 real) and loses none. The median rel-RMSE of accepted fits falls from 0.0230 to 0.0131, yet no winner has all four parameters interior (0 of 210) [opt]. The M2 scored-proxy maximum falls from 1.096 to 1.050; the M3 maximum barely moves (1.099 → 1.098). Against D, the Swing T1 exit premium changes by −$1.80 to +$1.12 (median $0.00), and its R/R by −0.17 to +0.17. 3 of 326 fits change headline band. **Cost:** about 4× D's single-thread calibration time [opt].

**A(ii): the wider box.** It accepts 27 more chains than D (21 synthetic, 6 real) and loses none. It is the only option where some winners have every parameter interior (14 of 228). The median rel-RMSE falls to 0.0096 and the median Feller ratio to 1.59 [opt]. The M2 scored-proxy range narrows to 0.961–1.052. The M3 maximum **rises** to 1.129: on the TSCO 2026-10-30 call chain from the 2026-10-03 capture, D's fit gives 1.099 and A(ii)'s gives 1.129 [`options.json` fit `m3/20261003T210145Z_weekend/TSCO/2026-10-30/C`]. Against D, the Swing T1 exit premium changes by −$1.14 to +$0.97 (median +$0.04, R/R median +0.01). 3 of 326 fits change headline band. **Cost:** about 21× D's single-thread calibration time, by far the largest [opt].

**B: an absolute fit-error limit.**
- L = 0.20 and L = 0.30 change nothing: no accepted fit has a rel-RMSE above 0.1488 [opt].
- L = 0.10 removes the label from 4 fits, all synthetic.
- L = 0.05 removes it from 39 fits (37 synthetic, 2 real), 19.4 % of D's Heston-labelled fits. It narrows the scored-proxy range to 0.955–1.057. The fits it drops fall back to BS-IV exits. Against D, the Swing T1 exit premium moves by −$2.02 to +$1.89, and 1 of 326 fits changes headline band.
- **Cost:** no calibration time; B only discards fits [opt].

**C: anchor Heston to the market.** The scored proxy's "now" price equals its mid by construction, and the label is unchanged (201 of 326). Under D the median proxy Heston÷mid is slightly below 1 (0.996), so anchoring lifts the median exit. Against D, the Swing T1 exit premium changes by −$1.32 to +$1.32 (median +$0.05), and its R/R by −0.25 to +0.16 [opt]. C changes the headline band on 7 of 326 fits, the most of any option, because it moves every labelled fit a little rather than a few fits a lot. It removes the level bias of the scored contract only; the other in-band strikes and the shape of the fit stay as they are. **Cost:** no recalibration and one extra Heston price per contract [opt].

**D: leave as is.** The scored proxy sits at 0.926–1.099 of its own mid. Against BS, the exit gap moves the Step 7 band on at most 5 of 170 synthetic fits and 1 of 31 real fits for any one horizon and move [m2, m3]. **Cost:** none.

## 6. What this means for cards today

Only M1 speaks about cards. Over the three committed days of real scans:
- 10 of 94 option cards and 7 of 114 alternative rows were "Heston repriced" [m1].
- On those cards, the stored Heston exit premium was 0.991 to 1.036 of the shipped BS exit; on the alternatives it was 0.995 to 1.058 [m1].
- The headline Step 7 band was the same under Heston and BS on all 10 cards and all 7 alternatives [m1].
- No gate, ranking or sizing reads the card's R/R [m1].

These are old-schema results. The comparison uses exit premiums, and both R/Rs are recomputed on today's full-premium basis. Live evidence from #174's per-scan line on the mini PC is still pending.

## Independent recompute (plan §3)

A fresh independent subagent recomputed, with its own code calling only the shipped functions being measured (never the probe), the M1 counts, three M1 Heston cards, three M2 cells, three M3 fits (one per capture, through the shipped chain builder with its own mock) and option B's effect count; it also recalibrated all 326 fits. Every compared value agrees with this evidence with zero difference. Details, tables and the two clarifying notes (parity-spot search scope; one-cent T2/T3 stock-target rounding with no exit-premium effect) are in [`recompute.md`](recompute.md). This recompute is evidence for the acceptance criterion; it is not an audit round.
