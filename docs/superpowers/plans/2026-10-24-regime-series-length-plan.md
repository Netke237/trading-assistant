# REGIME-SERIES-LENGTH — Measurement & Options Plan (r1, 2026-10-24)

**Board item:** #534 (tracking issue) · **Phase id:** `REGIME-SERIES-LENGTH`
**Branch:** `board/regime-series-length-1df66ee6` (from `origin/main` at `4a74d186`)
**Decision so far:** Issue #534 — measure across universe first, then numbered options for Kenneth. **Nothing changes on a card or gate before Kenneth's yes.** This phase changes no scoring logic, trade cards, or gate thresholds; it produces read-only measurement data, option evaluations, independent recomputations, and numbered questions for Kenneth (`needs-kenneth`). The chosen architectural remediation is built afterwards under its own implementation tickets.

---

## 1. Problem & Root Mechanism

### The Discrepancy Across Readers
When measuring daily regime using Rolling Optimal Markov Model (`compute_omm`), three daily readers in the codebase provide different bar-series lengths for the exact same symbol on the exact same date:
1. **Options Scan** (`backend/app/routers/scan.py:1858`):
   Pre-fetches OHLCV bars using:
   `_bar_start = _bar_end - timedelta(days=int(1.75 * 252))` (441 calendar days ≈ 304 trading bars).
   When falling back to Tradier (`backend/app/data/market.py:1696`), `fetch_candles_async` requests 252 bars.
2. **Auto-Trade Fire Path** (`backend/app/services/auto_trader.py:903`):
   Mirrors the options scan: `_SCAN_BAR_WINDOW_DAYS = int(1.75 * 252)` (441 calendar days ≈ 304 trading bars).
3. **Stock Scan** (`backend/app/routers/stock_scan.py:602`):
   Uses `_HISTORY_YEARS = 5`, pre-fetching 5 years of daily bars (≈ 1,260 trading bars).

### The Mathematical Bottleneck in `compute_omm`
In `backend/config/scoring_rules.yaml`, the daily regime configurations are:
- `swing`: `lookback: 20`, `window: 500`, `min_obs: 100`
- `position`: `lookback: 50`, `window: 750`, `min_obs: 100`

In `backend/app/services/regime_omm.py:193-195`:
```python
window_labels = labels[-window:] if len(labels) > window else labels
if window_labels.count(current) < min_obs:
    return None
```
When only 304 bars are provided:
- `len(labels) <= 304`.
- The entire series becomes the window (`labels[-window:]` is just `labels`).
- If the current regime state has occurred fewer than 100 times within those 304 bars, `compute_omm` returns `None`.

### The Silent Gate Bypass
When `compute_omm` returns `None`:
1. In `backend/app/routers/scan.py:743-757`, `_regime_signal` remains `None`.
2. In `backend/app/routers/scan.py:813` (pre-screen) and `921` (final score):
   `regime_gate=_regime_gate if _regime_signal else None`
   Because `_regime_signal` is `None`, `regime_gate` is passed to `score_stock` as `None`.
3. In `backend/app/scoring/stock_scorer.py:1270-1282`:
   When `regime_gate` is `None`, no regime cap or penalty is applied. The symbol passes through as if `regime_gate.enabled: false`, with no warning or indicator that the gate was bypassed.
4. On the auto-trade fire path (`backend/app/services/auto_trader.py:1645-1657`), an unmeasured regime abstains / fails open.
5. In contrast, the Stock Scan hands `compute_omm` ~1,260 bars. For the same symbol, the Stock Scan successfully measures the regime, potentially applying a `CAUTION` or `REJECT` cap, while the Options Scan and Auto-Trade fire treat the symbol as ungated.

---

## 2. Measurements to Take

All measurements are read-only, non-destructive, executed using Python 3.11 against the local database (Postgres, 540 distinct universe symbols).
Outputs will be stored under `docs/superpowers/measurements/2026-10-24-regime-series-length/`:
- `m1_coverage.json`
- `m2_gate_flips.json`
- `examples.json`
- `report.md`
- `recompute.md`

### M1: Universe Coverage & Unmeasured Rate Sweep
For all symbols in the universe (540 symbols in `ohlcv_daily`), across both horizons (`swing`, `position`) and both directions (`Bullish`, `Bearish`), test three bar window lengths:
1. **Window A (Short / 304 bars):** 441 calendar days (`int(1.75 * 252)`), matching current Options Scan and Fire path.
2. **Window B (Window + Lookback):**
   - Swing: `500 + 20 = 520` bars.
   - Position: `750 + 50 = 800` bars.
3. **Window C (Full History / 5-year / ~1,260 bars):** 5 years of daily bars, matching current Stock Scan.

For each window configuration, record:
- Total valid cells (`symbol × horizon × direction`).
- Unmeasured count (`compute_omm is None`).
- Measured count.
- Unmeasured rate (`unmeasured / total %`).
- Breakdown by horizon (`swing` vs `position`) and reason (`insufficient observations < min_obs`).

### M2: Gate Threshold Impacts & Status Flips
Compare the regime verdict and gate outcome between Window A (304 bars) vs Window B (Window + Lookback) vs Window C (Full History):
1. **Gate Thresholds** (`scoring_rules.yaml`):
   - `caution`: `headwind_caution_pct: -15`
   - `reject`: `headwind_reject_pct: -40` (with `require_stable_for_reject: true`)
2. **Flip Metrics:**
   - **Silent Bypass (False Passes):** How many cells are unmeasured at 304 bars, but when measured with Window B or C have `conviction <= -15%` (Caution) or `conviction <= -40%` (Reject)?
   - **Gate Flip Summary:** Count of cells changing status:
     - `Unmeasured (Ungated) → PASS`
     - `Unmeasured (Ungated) → CAUTION`
     - `Unmeasured (Ungated) → REJECT`
     - `PASS → CAUTION / REJECT`
     - `CAUTION → REJECT` or vice-versa
   - **Conviction Delta Distribution:** For cells measured under both windows, calculate `conviction(Window C) - conviction(Window A)`: mean, median, min, max, std dev.

### M3: Concrete In-Depth Symbol Cases
Examine and document the exact metrics for key representative symbols (including WMT, CPRT, TSCO, SRE, LYB, SPY):
- Bar count in each window.
- State sequence and observation count of the current state.
- Resulting `conviction_pct`, `stability`, `state`.
- Exact score card impact on pre-screen and final grade.

### M4: Options Evaluation & Trade-off Analysis
Evaluate four remediation options based on empirical data:
- **Option 1: Uniform Window + Lookback Bars** (Swing: 520 bars, Position: 800 bars; or uniform 800 bars from DB across all daily readers).
- **Option 2: 5-Year History Across All Daily Readers** (~1,260 bars, aligning Options Scan and Fire with Stock Scan).
- **Option 3: Adjust Configuration Parameters in `scoring_rules.yaml`** (e.g. lowering `window` or `min_obs` to fit within 304 bars).
- **Option 4: Explicit Unmeasured Regime Disclosure and Gating Policy** (card badge, log message, and configurable fail-closed vs fail-open behavior).

For each option, report:
- Implementation complexity.
- DB query overhead / memory footprint.
- Impact on scan latency (against the scan timeout guard).
- Numerical consistency achieved across Options, Stocks, and Auto-Trader.

---

## 3. Independent Recompute

Following the board audit protocol (`docs/agents/board.md` / `ticket-orchestration.md`):
After T1 and T2 run, a fresh independent subagent with its own clean script will independently recompute:
1. Universe symbol count and cell counts.
2. Unmeasured rates for Window A vs Window B vs Window C on both horizons.
3. Silent bypass counts (cells unmeasured in A that cross -15% or -40% in C).
4. Exact numerical values for 5 sample symbols.

Agreement or discrepancies will be recorded in `docs/superpowers/measurements/2026-10-24-regime-series-length/recompute.md`.

---

## 4. Implementation Tickets

### Ticket 1 (T1): Measurement Probe & Test Suite
- Script: `backend/scripts/regime_series_length_probe.py`
  - Loads DB daily bars for the 540 universe symbols.
  - Implements the exact Window A (304 bars), Window B (520/800 bars), and Window C (5-year) slices.
  - Evaluates `compute_omm` using shipped `app.services.regime_omm.compute_omm` and `scoring_rules.yaml` config.
  - Emits `m1_coverage.json`, `m2_gate_flips.json`, and `examples.json`.
- Test: `backend/tests/test_regime_series_length_probe.py`
  - Verifies that the probe uses the shipped `compute_omm` and reads official scoring rules.
  - Tests window slicing logic against fixture data.
  - Verifies gate classification matches `scoring_rules.yaml`.
  - Asserts that outputs conform to schema and contain no null/NaN fields.

### Ticket 2 (T2): Report, Options Evaluation, and Kenneth Questions
- Report: `docs/superpowers/measurements/2026-10-24-regime-series-length/report.md`
  - Executive summary and root-cause mechanism diagram.
  - Full measurement tables from M1 and M2.
  - Detailed case studies from M3.
  - Deep-dive into Options 1–4 from M4.
  - Numbered decision questions with concrete recommendations for Kenneth.
- Independent Recompute: `recompute.md` verified by independent subagent.

---

## 5. Acceptance Criteria

- [ ] Probe script `backend/scripts/regime_series_length_probe.py` and unit test `backend/tests/test_regime_series_length_probe.py` pass cleanly.
- [ ] M1, M2, and M3 measurement data generated and saved to `docs/superpowers/measurements/2026-10-24-regime-series-length/`.
- [ ] Comprehensive `report.md` published detailing coverage, gate flips, option evaluations, and numbered questions for Kenneth.
- [ ] Independent recompute verifies numbers with zero discrepancy in `recompute.md`.
- [ ] `PROJECT_STATE.json` updated with phase progress, audit records, and `python scripts/state.py` passes with zero drift.
- [ ] Full test suite and typechecks pass (`cd frontend && npm run typecheck && npm run test`, `cd backend && pytest`).
- [ ] Plan audit and code audit clean under `audit_rule`.
