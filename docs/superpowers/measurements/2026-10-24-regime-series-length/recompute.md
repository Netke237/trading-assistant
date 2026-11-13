# REGIME-SERIES-LENGTH — Independent Numerical Recompute (Plan §3)

**What this is.** A fresh, independent recompute subagent independently verified and recomputed all numerical claims in the REGIME-SERIES-LENGTH plan (`docs/superpowers/plans/2026-10-24-regime-series-length-plan.md` §3) and report (`docs/superpowers/measurements/2026-10-24-regime-series-length/report.md`).
The recompute agent did not author the measurement probe or the report, had no prior stake in the findings, and executed completely independent verification code.

**Environment & Runtime:**
- OS: Windows
- Python runtime: 3.11.9 (verified Python 3.11 pinned runtime)
- Database: Local PostgreSQL `ohlcv_daily` (540 universe symbols)
- Reference date (`as_of`): `2026-10-24`

**Independence Protocol:**
- `backend/scripts/regime_series_length_probe.py` was **neither imported nor called**.
- The recomputation script called only the official shipped application services and configuration:
  - `app.services.regime_omm.compute_omm` and `app.services.regime_omm.label_daily_states`
  - `app.services.historical_store.get_bars`
  - `backend/config/scoring_rules.yaml` (`regime` lookback/window/min_obs and `regime_gate` thresholds)
  - `app.database.AsyncSessionLocal` and `app.models.ohlcv_daily.OhlcvDailyModel` (for universe discovery)

---

## 1. Executive Summary & Verification Matrix

Every single metric, count, percentage, gate flip, conviction delta, and representative sample symbol was reproduced with **100% exact numerical agreement (zero discrepancy, difference 0)**.

| # | Recompute Target | Recompute Result | Report Value | Difference | Verdict |
|---|---|---|---|---|---|
| **1** | Universe Symbol Count | 540 symbols | 540 symbols | 0 | **AGREE** (Exact) |
| | Total Universe Cells ($540 \times 2 \times 2$) | 2,160 cells | 2,160 cells | 0 | **AGREE** (Exact) |
| **2** | Window A (Calendar 441d) Unmeasured | 944 / 2,160 (43.70%) | 944 / 2,160 (43.70%) | 0 (0.00%) | **AGREE** (Exact) |
| | Window A_304 (Exact 304 bars) Unmeasured | 894 / 2,160 (41.39%) | 894 / 2,160 (41.39%) | 0 (0.00%) | **AGREE** (Exact) |
| | Window B (520 / 800 bars) Unmeasured | 148 / 2,160 (6.85%) | 148 / 2,160 (6.85%) | 0 (0.00%) | **AGREE** (Exact) |
| | Window C (5-Year / ~1,260 bars) Unmeasured | 148 / 2,160 (6.85%) | 148 / 2,160 (6.85%) | 0 (0.00%) | **AGREE** (Exact) |
| **3** | Silent Bypasses: Window A $\rightarrow$ Window C | 288 (287 Caution, 1 Reject) | 288 (287 Caution, 1 Reject) | 0 | **AGREE** (Exact) |
| | Silent Bypasses: Window A $\rightarrow$ Window B | 288 (287 Caution, 1 Reject) | 288 (287 Caution, 1 Reject) | 0 | **AGREE** (Exact) |
| | Extreme Headwinds ($\le -40\%$) in Window A Unmeasured | 177 cells | 177 cells | 0 | **AGREE** (Exact) |
| **4** | Mathematical Identity Window B $\equiv$ Window C: Conviction Deltas | min=0, max=0, mean=0.0, $\sigma=0.0$ | min=0, max=0, mean=0.0, $\sigma=0.0$ | 0.0 | **AGREE** (Bit-for-bit) |
| | Window B $\rightarrow$ Window C Status Flips | 0 flips across 2,160 cells | 0 flips across 2,160 cells | 0 | **AGREE** (Zero Flips) |
| **5** | Concrete Sample Symbols (WMT, CPRT, TSCO, SRE, LYB, SPY) | All metrics, states, conv, gates match | All metrics, states, conv, gates match | 0 | **AGREE** (Exact) |
| | Single Hard REJECT Silent Bypass (FBHS) | Unmeasured $\rightarrow$ Reject (-67%, Stable) | Unmeasured $\rightarrow$ Reject (-67%, Stable) | 0 | **AGREE** (Exact) |

---

## 2. Universe Coverage & Unmeasured Rate Sweep (M1)

### Recomputation Method:
Using `app.services.historical_store.get_bars`, daily adjusted bars were loaded from the database for each of the 540 distinct universe symbols across the 5-year period ending on `2026-10-24`.
Four window configurations were independently sliced:
1. **Window A (Calendar 441d):** Bars where `date >= 2026-10-24 - timedelta(days=int(1.75 * 252))`, matching `backend/app/routers/scan.py:1858` and `backend/app/services/auto_trader.py:903`.
2. **Window A_304 (Exact 304 bars):** Slicing exactly `closes[-304:]`.
3. **Window B (Window + Lookback):** `closes[-520:]` for swing, `closes[-800:]` for position.
4. **Window C (Full History / 5-Year):** Full 5-year closes (~1,260 bars), matching `backend/app/routers/stock_scan.py:602`.

For each cell (`symbol × horizon × direction`), `app.services.regime_omm.compute_omm` was evaluated using the configured parameters in `scoring_rules.yaml` (`swing`: lookback=20, window=500, min_obs=100; `position`: lookback=50, window=750, min_obs=100). When `compute_omm` returned `None`, the causal reason was extracted by counting the current state occurrences in `label_daily_states`.

### Recomputed Coverage Results:

| Window | Metric | Swing ($N=1,080$) | Position ($N=1,080$) | Universe Total ($N=2,160$) | Report Value | Discrepancy |
|---|---|---|---|---|---|---|
| **Window A** | **Measured** | 602 (55.74%) | 614 (56.85%) | **1,216 (56.30%)** | 1,216 (56.30%) | 0 |
| *(441 cal days)* | **Unmeasured** | 478 (44.26%) | 466 (43.15%) | **944 (43.70%)** | 944 (43.70%) | 0 |
| | — *obs < 100* | 454 | 442 | 896 | 896 | 0 |
| | — *series < lookback+2* | 24 | 24 | 48 | 48 | 0 |
| **Window A_304** | **Measured** | 628 (58.15%) | 638 (59.07%) | **1,266 (58.61%)** | 1,266 (58.61%) | 0 |
| *(304 bars)* | **Unmeasured** | 452 (41.85%) | 442 (40.93%) | **894 (41.39%)** | 894 (41.39%) | 0 |
| | — *obs < 100* | 450 | 440 | 890 | 890 | 0 |
| | — *series < lookback+2* | 2 | 2 | 4 | 4 | 0 |
| **Window B** | **Measured** | 990 (91.67%) | 1,022 (94.63%) | **2,012 (93.15%)** | 2,012 (93.15%) | 0 |
| *(520 / 800 bars)*| **Unmeasured** | 90 (8.33%) | 58 (5.37%) | **148 (6.85%)** | 148 (6.85%) | 0 |
| | — *obs < 100* | 88 | 56 | 144 | 144 | 0 |
| | — *series < lookback+2* | 2 | 2 | 4 | 4 | 0 |
| **Window C** | **Measured** | 990 (91.67%) | 1,022 (94.63%) | **2,012 (93.15%)** | 2,012 (93.15%) | 0 |
| *(5-Year)* | **Unmeasured** | 90 (8.33%) | 58 (5.37%) | **148 (6.85%)** | 148 (6.85%) | 0 |
| | — *obs < 100* | 88 | 56 | 144 | 144 | 0 |
| | — *series < lookback+2* | 2 | 2 | 4 | 4 | 0 |

**Finding:** All coverage counts, percentage rates, and failure reason breakdowns match `report.md` and `m1_coverage.json` exactly.

---

## 3. Silent Gate Bypasses & Gate Transition Matrix (M2)

### Recomputation Method:
Gate status was evaluated according to `scoring_rules.yaml`:
- `headwind_caution_pct: -15`
- `headwind_reject_pct: -40`
- `require_stable_for_reject: true`
- If `omm_res is None` $\rightarrow$ `UNMEASURED`
- If `conviction_pct <= -40` and `stability == "Stable"` $\rightarrow$ `REJECT`
- Elif `conviction_pct <= -15` $\rightarrow$ `CAUTION`
- Else $\rightarrow$ `PASS`

A **silent bypass** is defined as any cell that evaluated to `UNMEASURED` in Window A (which causes `score_stock` to bypass the regime cap) but evaluates to `CAUTION` or `REJECT` under full history.

### Recomputed Silent Bypass Metrics:

| Comparison | Total Silent Bypasses | Bypassed to CAUTION | Bypassed to REJECT | Raw Conviction $\le -15\%$ | Raw Conviction $\le -40\%$ | Report Agreement |
|---|---|---|---|---|---|---|
| **Window A $\rightarrow$ Window C** | **288** | 287 | 1 | 288 | 177 | **EXACT (Diff 0)** |
| **Window A $\rightarrow$ Window B** | **288** | 287 | 1 | 288 | 177 | **EXACT (Diff 0)** |
| **Window A_304 $\rightarrow$ Window C** | **272** | 272 | 0 | 272 | 170 | **EXACT (Diff 0)** |
| **Window A_304 $\rightarrow$ Window B** | **272** | 272 | 0 | 272 | 170 | **EXACT (Diff 0)** |
| **Window B $\rightarrow$ Window C** | **0** | **0** | **0** | **0** | **0** | **EXACT (Diff 0)** |

### Recomputed Full Gate Transition Matrix: Window A $\rightarrow$ Window C (and Window B)

$$\begin{array}{l|rrrr|r}
\text{From Window A } \backslash \text{ To Window C} & \text{UNMEASURED} & \text{PASS} & \text{CAUTION} & \text{REJECT} & \text{Total} \\
\hline
\text{UNMEASURED} & 148 & 508 & 287 & 1 & 944 \\
\text{PASS} & 0 & 599 & 170 & 2 & 771 \\
\text{CAUTION} & 0 & 207 & 147 & 4 & 358 \\
\text{REJECT} & 0 & 37 & 43 & 7 & 87 \\
\hline
\text{Total} & 148 & 1,351 & 647 & 14 & 2,160
\end{array}$$

- **Cells with unchanged status:** $148 + 599 + 147 + 7 = 901$ (41.71%)
- **Cells with flipped status:** $1,259$ (58.29%)
- **Discrepancy against Report:** Exactly 0 cells.

---

## 4. Verification of Window B $\equiv$ Window C Mathematical Identity

The report claims that Window B (`window + lookback` closes = 520 bars for swing, 800 bars for position) is bit-for-bit mathematically identical to Window C (5-year full history, ~1,260 closes) for every measured cell.

### Recomputation Verification:
1. **Measured Cell Overlap:**
   - Both Window B and Window C measured exactly **2,012 cells**.
   - Exactly **148 cells** were unmeasured in both Window B and Window C.
   - Cells measured in B but not in C: **0**.
   - Cells measured in C but not in B: **0**.
2. **Conviction Delta Statistics:**
   For all 2,012 co-measured cells, calculating $\Delta = \text{conviction}(C) - \text{conviction}(B)$:
   - Minimum delta: **0**
   - Maximum delta: **0**
   - Mean delta: **0.0000**
   - Median delta: **0.0000**
   - Standard deviation ($\sigma$): **0.0000**
3. **Gate Status Transitions (Window B $\rightarrow$ Window C):**
   - `UNMEASURED -> UNMEASURED`: 148 (6.85%)
   - `PASS -> PASS`: 1,351 (62.55%)
   - `CAUTION -> CAUTION`: 647 (29.95%)
   - `REJECT -> REJECT`: 14 (0.65%)
   - Any flip (`PASS <-> CAUTION <-> REJECT`): **0 (0.000%)**

**Conclusion:** Window B produces 100% bit-for-bit numerical identity with Window C across all 2,160 cells.

---

## 5. Sample Symbol Detailed Verification

The 6 representative symbols requested in plan §3 and evaluated in report §4 were recomputed independently:

### 5.1 WMT (Walmart Inc.)
- **Swing Bullish:**
  - Window A (304 bars): State `Bull`, Obs=131, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window B (520 bars): State `Bull`, Obs=229, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bull`, Obs=229, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Swing Bearish:**
  - Window A (304 bars): State `Bull`, Obs=131, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window B (520 bars): State `Bull`, Obs=229, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bull`, Obs=229, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Position Bullish:**
  - Window A (304 bars): State `Bull`, Obs=134, Conviction=+33%, Stability=`Fragile`, Gate=`PASS`
  - Window B (800 bars): State `Bull`, Obs=498, Conviction=+40%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bull`, Obs=498, Conviction=+40%, Stability=`Fragile`, Gate=`PASS`
- **Position Bearish:**
  - Window A (304 bars): State `Bull`, Obs=134, Conviction=-33%, Stability=`Fragile`, Gate=`CAUTION`
  - Window B (800 bars): State `Bull`, Obs=498, Conviction=-40%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,255 bars): State `Bull`, Obs=498, Conviction=-40%, Stability=`Fragile`, Gate=`CAUTION`
- **Verdict:** **AGREE** (Exact match on all values).

### 5.2 CPRT (Copart Inc.) — Classic Silent Bypass
- **Swing Bullish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=61 < 100) $\rightarrow$ Ungated PASS in Options Scan
  - Window B (520 bars): State `Bull`, Obs=154, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,255 bars): State `Bull`, Obs=154, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
- **Swing Bearish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=61 < 100)
  - Window B (520 bars): State `Bull`, Obs=154, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bull`, Obs=154, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
- **Position Bullish:**
  - Window A (304 bars): `UNMEASURED` (Choppy obs=70 < 100)
  - Window B (800 bars): State `Choppy`, Obs=108, Conviction=+100%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Choppy`, Obs=108, Conviction=+100%, Stability=`Fragile`, Gate=`PASS`
- **Position Bearish:**
  - Window A (304 bars): `UNMEASURED` (Choppy obs=70 < 100) $\rightarrow$ Ungated PASS in Options Scan
  - Window B (800 bars): State `Choppy`, Obs=108, Conviction=-100%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,255 bars): State `Choppy`, Obs=108, Conviction=-100%, Stability=`Fragile`, Gate=`CAUTION`
- **Verdict:** **AGREE** (Exact match on all values).

### 5.3 TSCO (Tractor Supply Co.) — False Rejection & Silent Bypass
- **Swing Bullish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=60 < 100) $\rightarrow$ Silent Bypass
  - Window B (520 bars): State `Bull`, Obs=151, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,255 bars): State `Bull`, Obs=151, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
- **Swing Bearish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=60 < 100)
  - Window B (520 bars): State `Bull`, Obs=151, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bull`, Obs=151, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
- **Position Bullish:**
  - Window A (304 bars): State `Bear`, Obs=169, Conviction=-50%, Stability=`Stable`, Gate=`REJECT` (False Reject)
  - Window B (800 bars): State `Bear`, Obs=318, Conviction=+14%, Stability=`Fragile`, Gate=`PASS` (Recovered)
  - Window C (1,255 bars): State `Bear`, Obs=318, Conviction=+14%, Stability=`Fragile`, Gate=`PASS` (Recovered)
- **Position Bearish:**
  - Window A (304 bars): State `Bear`, Obs=169, Conviction=+50%, Stability=`Stable`, Gate=`PASS`
  - Window B (800 bars): State `Bear`, Obs=318, Conviction=-14%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,255 bars): State `Bear`, Obs=318, Conviction=-14%, Stability=`Fragile`, Gate=`PASS`
- **Verdict:** **AGREE** (Exact match on all values).

### 5.4 SRE (Sempra) — Boundary Sensitivity
- **Swing Bullish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=89 < 100)
  - Window B (520 bars): State `Bull`, Obs=176, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,253 bars): State `Bull`, Obs=176, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Swing Bearish:**
  - Window A (304 bars): `UNMEASURED` (Bull obs=89 < 100)
  - Window B (520 bars): State `Bull`, Obs=176, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,253 bars): State `Bull`, Obs=176, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Position Bullish:**
  - Window A (304 bars): State `Choppy`, Obs=100, Conviction=+100%, Stability=`Fragile`, Gate=`PASS`
  - Window B (800 bars): State `Choppy`, Obs=107, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,253 bars): State `Choppy`, Obs=107, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Position Bearish:**
  - Window A (304 bars): State `Choppy`, Obs=100, Conviction=-100%, Stability=`Fragile`, Gate=`CAUTION` (False Caution)
  - Window B (800 bars): State `Choppy`, Obs=107, Conviction=0%, Stability=`Fragile`, Gate=`PASS` (True Neutral)
  - Window C (1,253 bars): State `Choppy`, Obs=107, Conviction=0%, Stability=`Fragile`, Gate=`PASS` (True Neutral)
- **Verdict:** **AGREE** (Exact match on all values).

### 5.5 LYB (LyondellBasell) — Directional Inversion
- **Swing Bullish:**
  - Window A (304 bars): State `Bull`, Obs=133, Conviction=-14%, Stability=`Fragile`, Gate=`PASS`
  - Window B (520 bars): State `Bull`, Obs=199, Conviction=+30%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,253 bars): State `Bull`, Obs=199, Conviction=+30%, Stability=`Fragile`, Gate=`PASS`
- **Swing Bearish:**
  - Window A (304 bars): State `Bull`, Obs=133, Conviction=+14%, Stability=`Fragile`, Gate=`PASS`
  - Window B (520 bars): State `Bull`, Obs=199, Conviction=-30%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,253 bars): State `Bull`, Obs=199, Conviction=-30%, Stability=`Fragile`, Gate=`CAUTION`
- **Position Bullish:**
  - Window A (304 bars): State `Bull`, Obs=122, Conviction=-100%, Stability=`Fragile`, Gate=`CAUTION`
  - Window B (800 bars): State `Bull`, Obs=257, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
  - Window C (1,253 bars): State `Bull`, Obs=257, Conviction=-50%, Stability=`Fragile`, Gate=`CAUTION`
- **Position Bearish:**
  - Window A (304 bars): State `Bull`, Obs=122, Conviction=+100%, Stability=`Fragile`, Gate=`PASS`
  - Window B (800 bars): State `Bull`, Obs=257, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,253 bars): State `Bull`, Obs=257, Conviction=+50%, Stability=`Fragile`, Gate=`PASS`
- **Verdict:** **AGREE** (Exact match on all values).

### 5.6 SPY (S&P 500 ETF) — Index Threshold Cross
- **Swing Bullish:**
  - Window A (301 bars): State `Choppy`, Obs=172, Conviction=+14%, Stability=`Fragile`, Gate=`PASS`
  - Window B (520 bars): State `Choppy`, Obs=218, Conviction=+17%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,252 bars): State `Choppy`, Obs=218, Conviction=+17%, Stability=`Fragile`, Gate=`PASS`
- **Swing Bearish:**
  - Window A (301 bars): State `Choppy`, Obs=172, Conviction=-14%, Stability=`Fragile`, Gate=`PASS` (Escaped by 1%)
  - Window B (520 bars): State `Choppy`, Obs=218, Conviction=-17%, Stability=`Fragile`, Gate=`CAUTION` (Demoted)
  - Window C (1,252 bars): State `Choppy`, Obs=218, Conviction=-17%, Stability=`Fragile`, Gate=`CAUTION` (Demoted)
- **Position Bullish:**
  - Window A (301 bars): State `Choppy`, Obs=114, Conviction=+100%, Stability=`Fragile`, Gate=`PASS`
  - Window B (800 bars): State `Choppy`, Obs=147, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,252 bars): State `Choppy`, Obs=147, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Position Bearish:**
  - Window A (301 bars): State `Choppy`, Obs=114, Conviction=-100%, Stability=`Fragile`, Gate=`CAUTION`
  - Window B (800 bars): State `Choppy`, Obs=147, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
  - Window C (1,252 bars): State `Choppy`, Obs=147, Conviction=0%, Stability=`Fragile`, Gate=`PASS`
- **Verdict:** **AGREE** (Exact match on all values).

### 5.7 FBHS (Fortune Brands) — The Single Hard REJECT Silent Bypass
- **Swing Bullish:**
  - Window A (0 bars due to spin-off date cutoff): `UNMEASURED` $\rightarrow$ Passed ungated in Options Scan
  - Window B (286 bars from DB): State `Bull`, Obs=124, Conviction=-67%, Stability=`Stable`, Gate=`REJECT`
  - Window C (286 bars from DB): State `Bull`, Obs=124, Conviction=-67%, Stability=`Stable`, Gate=`REJECT`
- **Verdict:** **AGREE** (Confirmed that FBHS is the sole cell in the universe where Window A permitted an unmeasured trade setup that is hard-rejected with $-67\%$ conviction and `Stable` classification under Window B/C).

---

## 6. Final Recompute Certification

The independent recomputation executed with clean code calling only the shipped application services against the database has verified every table, statistic, transition count, and sample symbol in `report.md`.

- Universe size: **540 symbols, 2,160 cells** (Exact)
- Window A unmeasured rate: **43.70%** (Exact)
- Window B / C unmeasured rate: **6.85%** (Exact)
- Window A $\rightarrow$ Window B/C silent gate bypasses: **288 cells** (Exact)
- Extreme headwind ($\le -40\%$) unmeasured in Window A: **177 cells** (Exact)
- Window B $\equiv$ Window C mathematical parity: **0 deltas, 0 flips across all 2,012 measured cells** (Exact)

**Independent Recompute Verdict: COMPLETE & 100% IN AGREEMENT.**
