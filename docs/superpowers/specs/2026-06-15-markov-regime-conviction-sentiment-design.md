# Markov Regime, Conviction & Sentiment — Design Spec

**Date:** 2026-06-15
**Status:** Draft for review
**Author:** Kenneth + Claude (brainstorming session)
*Horizon- and direction-aware · v2*

---

## 0. Decisions locked
- **Conviction** = direction-aware. Raw `s = P(Bull) − P(Bear)` from the symbol's **stride-true** transition-matrix current-state row. `conviction = s` if Bullish, `−s` if Bearish. Signed % (−100…+100). Positive = regime agrees with the trade.
- **Interpretation bands:** `≥+40` Strong tailwind · `+15…+40` Mild tailwind · `−15…+15` Neutral/chop · `−40…−15` Mild headwind · `≤−40` Strong headwind.
- **Everything is horizon-aware.** Regime runs at the timeframe of the chosen holding horizon: **Intraday → 15-min bars**, **Swing/Position → daily bars**. Per-symbol regime is **pullable at every horizon, including intraday**.
- **Alignment ships at every horizon** via a directional HMM that runs at the horizon's timeframe. The existing session HMM (Trending/Mean-reverting/Choppy) stays for Page-1 display only.
- **Regime is a demote-only gate + conviction value + optional sizing/filter — never a weighted scoring rule, never a strategy.** Lives in shared `score_stock`; both scans inherit it.
- **Stock scan is the reference implementation** (real sizing + data). Options scan + Page 1 inherit the engine.
- **Conviction sizing can only reduce risk below the configured %, never inflate it.** Default OFF.
- **Insufficient-data → degrade, never flatter:** if a horizon's `min_obs` isn't met, `sentiment = None` with a plain reason; no fabricated number.

---

## 1. Shared engine

### 1a. `backend/app/services/regime_omm.py`
- **Stride fix:** stride-sampled counting (non-overlapping windows, stride = horizon lookback). Compute both matrices (legacy overlapping + stride-true); stride-true drives `p_stay`, `stability`, `avg_regime_duration`, conviction.
- **Conviction:** `signal_from_row()`, `conviction(signal, direction)`, `conviction_interpretation(pct, stability)`.
- **Lower-value:** `n_step_forecast(P, n)`, `stationary_distribution(P)`; optional `enhanced_states` (20-day return + ATR + relative volume cluster), config-gated, default off.
- **Horizon-parameterised:** `compute_omm(bars, *, lookback, window, min_obs, threshold, ...)` — all timeframe/lookback/window/min_obs values come from per-horizon config.
- `OmmResult` carries both matrices, conviction_pct, conviction_label, interpretation, stationary, forecast.

### 1b. `backend/app/services/regime_hmm_daily.py` (NEW) — directional HMM, timeframe-agnostic
- `compute_directional_hmm(bars, ...) -> DirectionalHmmResult | None`: GaussianHMM on returns of whatever bars passed (daily or 15-min), 3 states labelled Bull/Bear/Sideways by mean-return order. Returns current label + p_stay + transition row. `None` if `hmmlearn` unavailable or `min_obs` unmet.
- `alignment(omm_state, hmm_state) -> 'Aligned' | 'Diverging' | 'Unavailable'` (Choppy ≡ Sideways).
- Existing `regime_hmm.py` (session HMM) untouched.

### 1c. `backend/app/scoring/stock_scorer.py`
- `score_stock(...)` gains `regime_signal: dict | None` + `regime_gate: dict | None`.
- Appends a demote-only `RuleResult(name="regime", ...)` (mirrors the `confidence` row): caps status on headwind, adds **zero** points. Weights untouched.

---

## 2. Config — `backend/config/scoring_rules.yaml`
```yaml
regime:
  intraday: { timeframe: 15min, lookback: 26, window: 1000, min_obs: 60 }
  swing:    { timeframe: daily, lookback: 20, window: 500,  min_obs: 100 }
  position: { timeframe: daily, lookback: 50, window: 750,  min_obs: 100 }
  enhanced_states: false

regime_gate:
  enabled: true
  headwind_caution_pct: -15
  headwind_reject_pct:  -40
  require_stable_for_reject: true

regime_sizing:
  enabled: false
  min_mult: 0.5
  full_conviction_pct: 40
```
Sizing multiplier: `mult = min_mult + (1−min_mult)·clamp(conviction_pct / full_conviction_pct, 0, 1)` — always ≤ 1.0.

---

## 3. Schemas — `backend/app/schemas/__init__.py`
```python
class SentimentData(BaseModel):
    horizon: str
    timeframe: str
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    conviction_pct: int
    conviction_label: str
    interpretation: str
    hmm_state: str | None = None
    alignment: Literal['Aligned','Diverging','Unavailable'] = 'Unavailable'
    insufficient_data: bool = False
```
- `ScoreBreakdown` → `sentiment: SentimentData | None`
- `TradeCardData` → `sentiment: SentimentData | None`
- `PositionCardOut` (stock_scan.py) → `sentiment: SentimentData | None`
- `OmmData` → `conviction_pct`, `conviction_label`; optional `stationary`, `forecast`
- `MarketRegime` → `conviction_pct`, `conviction_label`, `hmm_state`, `alignment`

---

## 4. Stock scan — `backend/app/routers/stock_scan.py` (reference impl)
- Horizon-aware fetch: Swing/Position use daily bars (pass ≥ window, not `bars[-120:]`); Intraday fetches `fetch_intraday_candles(symbol, '15min', days=55)`.
- Compute per-symbol OMM + conviction at the horizon timeframe → pass into `score_stock`.
- Sizing: in `_position_size`, when `regime_sizing.enabled`, multiply `dollar_risk` by conviction `mult` (reduce-only). Default off.
- Sentiment on `PositionCardOut`.
- Alignment: per-candidate directional HMM via `ProcessPoolExecutor` + 24h cache; cache key includes horizon + timeframe.
- Filter: `regime_filter: bool = False` on `StockScanRequest`; when true, drop headwind candidates; add `failed_regime` to `StockPipeline`.
- Regime NOT added to the strategy dropdown.

## 5. Options scan — `backend/app/routers/scan.py`
- Inherits the `score_stock` regime gate.
- Horizon-aware fetch; daily HMM only for shortlisted candidates (cache + pool).
- Populate `sentiment` on `TradeCardData`.

## 6. Page 1 market regime — `backend/app/routers/regime.py`
- Regime per selected horizon. Swing/Position: daily OMM + daily directional HMM. Intraday: session HMM (existing) + 15-min directional OMM conviction + alignment.
- Add `conviction_pct`, `conviction_label`, `hmm_state`, `alignment` to `MarketRegime`.

---

## 7. Frontend
- Shared `MarketSentiment` component (one build, reused): horizon + timeframe, state, conviction % styled by band, interpretation, stickiness line, Aligned/Diverging badge, "insufficient history" empty state.
- Options trade card, stock position card (step-4-stocks), ranking score-detail, Page-1 regime all render it.
- `frontend/types/domain.ts` → `SentimentData` + new fields.

## 8. Tests
- `test_regime_omm.py` — stride counting, conviction sign/magnitude, bands, horizon params.
- `test_regime_hmm_daily.py` — directional labelling daily + 15-min, alignment map, graceful degrade.
- `test_data_leakage.py` / `test_regime_no_lookahead.py` — causal at all timeframes.
- Scorer — `regime` gate demote-only (0 pts); sizing neutral when disabled.
- Stock scan — Intraday pulls 15-min bars; `regime_filter` drops headwind candidates; horizon-keyed cache.

## 9. Graceful degradation
- No `hmmlearn` → alignment "OMM only — HMM unavailable"; conviction + sentiment still work.
- Horizon `min_obs` unmet → `sentiment.insufficient_data = true`, no published number.
