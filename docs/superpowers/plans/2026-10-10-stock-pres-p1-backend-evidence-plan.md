# STOCK-PRES-P1-BACKEND-EVIDENCE — plan

Board item / tracking issue: **#146** · Branch: `board/stock-pres-p1-backend-evidence-f4e4b87f` · Decision: `STOCK-PRESENTATION-2026-10-10` (D11 as corrected 2026-10-10) · Spec: `docs/superpowers/specs/2026-10-10-stock-presentation/README.md` ("Additive backend fields needed").

## Goal (Kenneth's words, from #146)

Send the numbers the redesigned Stocks and Pre-Breakout pages need. They are already calculated by the backend but not sent today.

## Scope

In — **send already-computed values only; no calculation change**:

1. **Stock score factors.** `StockScoreCard.explanation` (weights, per-factor components, caps, thresholds) is already built by `score_stock` (`backend/app/scoring/stock_scorer.py` ~L1336-1357) and already sent on Options trade cards as `stockExplanation` (`backend/app/routers/scan.py:1241`, schema `StockExplanation` in `backend/app/schemas/__init__.py:297`). The stock scan (`backend/app/routers/stock_scan.py` `_process_stock`, `PositionCardOut(...)` ~L1632) drops it. Send it as `stock_explanation` on every stock-scan candidate. Nothing is imported from `codex/trade-card-qualification-presentation`.
2. **Pre-Breakout confidence sub-scores.** `breakout_setup_signal` (`backend/app/services/strategy_engine.py` ~L1554-1593) computes `atr_score`, `vol_score`, `prox_score` (+ `fib_score` when Fib is used), weights them and truncates to `confidence`; only `confidence` leaves the function. Send the sub-scores, weights, contributions and the unrounded sum.
3. **Fib swing low / high.** `_fibonacci_pullback_signal` (`strategy_engine.py` L118-210) computes `swing_low` / `swing_high` of its window and measures the retracement levels from them; it returns only `(at_level, dist_pct, label)`. Send the two swing values on Pre-Breakout rows (when Fib was used) and on Fib-pullback rows.
4. Matching **optional** frontend types. Results persisted before this change (backend `scan_sessions` / `scheduled_scan_runs` JSON, browser `scanStore` localStorage) must still load.

Out: any UI change (P2–P5); any scoring / confidence / gate / sizing formula change; any change to an existing field's name, value or meaning; the `/analyze-stock` response (not a stock-scan candidate; P2 decides if it needs it); the Fib-pullback scan's own `confidence` formula (router-local, not a sub-score breakdown).

## Facts checked against the code (main `8d1e32e`)

- `score_stock(...)` returns `StockScoreCard(..., explanation=explanation)`; `explanation` is a plain dict whose shape is exactly what `StockExplanation` validates on the Options path (`scan.py` passes `card.explanation` into `TradeCardData.stockExplanation: Optional[StockExplanation]`).
- In `_process_stock`, after `score_stock`, later scan gates replace the card's **status** only, never its explanation: missing confidence → CAUTION (~L1546), `confidence_caution_below` → CAUTION (~L1560), Bearish → CAUTION (~L1565), earnings veto (~L1626-1628). So `explanation.status` / `explanation.score` are the **scorer's** verdict at scoring time; `stock_status` stays the final verdict. This is the same relation the Options card has (`stockConfidence` vs `status`). P1 only sends; P2 must label the explanation as score evidence and keep `stock_status` as the verdict (recorded in the type comments below, so a P2 implementer cannot misread it).
- `PositionCardOut` is constructed only at `stock_scan.py` ~L1632. `StockScanResult` is persisted and re-read with `model_validate_json` at `stock_scan.py:719` (`restore_stock_from_db`) and `scan_schedule_scheduler.py:160`; a new `Optional[...] = None` field validates old rows as `None`. No schema-version bump: an absent field means "not captured", the meaning of no existing field changes (contrast `SCAN_RESULT_SCHEMA_VERSION`, which guards a changed meaning).
- pydantic serialises NaN/inf in dict values as `null` both in `model_dump_json` and in FastAPI responses (checked on this repo's FastAPI/pydantic), so evidence `detail` dicts cannot break the JSON.
- `breakout_setup_signal` has one caller (`stock_scan.py` `/scan/prebreakout`, ~L2202); `SetupSignal` is not persisted server-side and is "not watchable" (`strategy_watch_store.py:24`). `_fibonacci_pullback_signal` has two callers: `breakout_setup_signal` (~L1574) and `/scan/fib-pullback` (via the public alias `fibonacci_pullback_signal`, `stock_scan.py:2085`), plus tests.
- Frontend: `scanStore` (store `version: 18`) persists `stockScanResult` and `previousStockScanResult`; `preBreakoutResults` and `fibPullbackResults` are **not** in `partialize` (session-only today; corrected after plan round 1). Their element types are inline in `frontend/lib/scanStore.ts` (~L454-470) and `frontend/lib/api.ts` (~L888-916). The Pre-Breakout "pullback" sub-mode calls `api.postStockScan`, so it receives `stock_explanation` through item 1.
- Size: one stock-mode explanation is ~3.6 KB of JSON (AAPL fixture). With the default `shortlist_max_candidates = 10`, the persisted `stockScanResult` + `previousStockScanResult` grow by ~70 KB. `scanStore`'s storage adapter already survives a quota error (`scanStoreQuotaStorage.test.ts`).

## Pinned current numbers (must not move)

From `backend/tests/test_prebreakout_params.py::_make_bars(60, 100.0, 0.5)` with `atr_compression_ratio=0.85, atr_avg_lookback=20, range_atr_mult=3.0, range_lookback_bars=10, vol_compression_ratio=0.9, resistance_proximity_pct=0.08, swing_lookback=50, direction="Bullish", require_trend=True`, on main `8d1e32e`, Python 3.11:

| Case | `confidence` | `metrics` |
|---|---|---|
| Fib off | 59 | `{'atr_ratio': 0.535, 'range_ratio': 0.878, 'vol_ratio': 0.732, 'proximity_pct': 0.31, 'swing_level': 104.42, 'current_atr': 0.4557}` |
| `fib_enabled=True, fib_swing_lookback=50, fib_levels=[23.6, 38.2, 50.0, 61.8]` | 67 | the six above + `'fib_at_level': True, 'fib_level_hit': '23.6', 'fib_dist_pct': 0.63` |
| `fib_enabled=True, fib_levels=[]` (falls back) | 59 | the six above, no fib keys |

`fibonacci_pullback_signal(tests/test_strategy_engine_fib.py::_impulse_then_retrace(), "Bullish")` → `(True, 0.07, '61.8')`.

## Tasks

Run backend tests with the Python **3.11** interpreter (repo pin). Frontend: `cd frontend && npm run typecheck && npm run test`.

### Task 1 — stock-scan candidates carry the scorer's evidence (`stock_explanation`)

Files: `backend/app/schemas/stock_scan.py`, `backend/app/routers/stock_scan.py`, new `backend/tests/test_stock_pres_p1_stock_explanation.py`.

Tests first (new file):

1. **Equal to the scorer's dict.** Reuse the `stock_client` setup pattern of `tests/test_scan_bearish_unvalidated.py` (offline fakes, `_pass_bt`, fake `pullback_ema` signal), but wrap the **real** `score_stock` so it records the card it returned (`monkeypatch.setattr(ss, "score_stock", recorder)` where `recorder` calls the original with the router's kwargs and appends the card). Post one `/api/stock-scan` (Bullish, Swing, `pullback_ema`, one symbol; bars from `tests/fixtures/AAPL_candles.json` via the fakes the harness already uses, or the harness's own bars). Assert `candidate["stock_explanation"] == json.loads(StockExplanation.model_validate(recorded.explanation).model_dump_json())` and `candidate["stock_score"] == recorded.score`. Red today: the key is absent (`KeyError`).
2. **Verdict stays separate.** Same harness, Bearish: `candidate["stock_status"] == "CAUTION"` (Bearish cap) while `candidate["stock_explanation"]["status"] == recorded.status` (the scorer's own status, here not CAUTION-capped by the scan). Pins that the scan never rewrites the evidence and never takes the verdict from it.
3. **Real scorer output always validates.** For each of `AAPL`, `MSFT`, `NVDA` fixtures × `Bullish`/`Bearish` × `Intraday`/`Swing`/`Position`: `score_stock(symbol=…, direction=…, horizon=…, bars=bars[-120:], scoring_mode="stock")` → `StockExplanation.model_validate(card.explanation)` does not raise. (Guards item 4 below: a validation error must never be the normal path.)
4. **A bad explanation never drops a candidate.** Monkeypatch `score_stock` to return a `StockScoreCard` with a valid score/status/rules and `explanation={"version": 1}` (invalid). The candidate is still returned, with `stock_explanation is None`, and the same `stock_score`/`stock_status` as with `explanation=None`. Red today: the key is absent.
5. **Old persisted results load.** `StockScanResult.model_validate_json(<a stored-shape JSON with one candidate and no stock_explanation key>)` → `candidates[0].stock_explanation is None`; and `PositionCardOut` round-trips a present explanation through `model_dump_json` / `model_validate_json` unchanged.

Implementation:

- `schemas/stock_scan.py`: `from app.schemas import SentimentData, FundamentalsOut, StockExplanation`; add to `PositionCardOut`, after `params_source`:
  ```python
  # STOCK-PRES-P1: the scorer's own evidence for stock_score (weights, factor
  # components, scorer caps), exactly StockScoreCard.explanation. Scorer-time:
  # its `status` is the SCORER's verdict, before the scan's later caps
  # (missing/low confidence, Bearish, earnings veto). The verdict is
  # stock_status. None on results persisted before P1, or if the evidence
  # failed validation (logged; the candidate is kept).
  stock_explanation: Optional[StockExplanation] = None
  ```
- `routers/stock_scan.py`: a small helper next to `_scan_drop_flag`:
  ```python
  def _stock_explanation_out(symbol: str, card) -> StockExplanation | None:
      if card.explanation is None:
          return None
      try:
          return StockExplanation.model_validate(card.explanation)
      except ValidationError:
          logger.warning("stock scan: %s score evidence failed validation; sent without it", symbol)
          return None
  ```
  (`ValidationError` is already imported at L22; import `StockExplanation` from `app.schemas`.) In `PositionCardOut(...)` add `stock_explanation=_stock_explanation_out(symbol, card),`. `card` at that point is the post-cap card; `dataclasses.replace` keeps `explanation` untouched, so it is the scorer's dict.
- No other change: no field renamed, no status/score/gate logic touched.

Commit: `feat(stock-scan): send the scorer's score evidence on stock-scan candidates (STOCK-PRES-P1 T1)`

### Task 2 — Pre-Breakout confidence breakdown and Fib swing low/high

Files: `backend/app/services/strategy_engine.py`, `backend/app/routers/stock_scan.py`, new `backend/tests/test_stock_pres_p1_prebreakout_evidence.py`, `backend/tests/test_fib_pullback_endpoint.py` (only its two patches of `app.services.strategy_engine.fibonacci_pullback_signal`, L96 and L177: once the route calls `fibonacci_pullback_detail` they would no longer take effect — repoint them at `app.services.strategy_engine.fibonacci_pullback_detail` returning the equivalent dict, same assertions).

Tests first (new file):

1. **Numbers unchanged.** The three pinned `breakout_setup_signal` cases above: `confidence` and `metrics` equal the pinned literals exactly; `fibonacci_pullback_signal(_impulse_then_retrace(), "Bullish") == (True, 0.07, '61.8')`.
2. **Breakdown reproduces the confidence.** For each pinned case, `signal.confidence_breakdown`:
   - `fib_used` is `False`, `True`, `False` respectively;
   - `weights == {"atr": 0.30, "vol": 0.25, "proximity": 0.45}` when Fib not used, `{"atr": 0.24, "vol": 0.20, "proximity": 0.36, "fib": 0.20}` when used;
   - each component's `score` equals an independent recomputation in the test from the inputs (`atr_score = max(0, 100*(1 - atr_ratio_unrounded/0.85))`, etc., with the unrounded ratios recomputed in the test from the bars exactly as the engine does — or, simpler and equally binding, asserted via `contribution == score * weight` and `min(100, max(0, int(unrounded))) == signal.confidence` where `unrounded == sum of contributions in the engine's order`);
   - `confidence == signal.confidence`.
   Red today: `AttributeError` (no `confidence_breakdown`).
3. **Fib swing equals the window the levels were measured from.** Fib-on case: `signal.fib_swing == {"low": min(b["low"] for b in window), "high": max(b["high"] for b in window)}` with `window = bars[-50:]`; Fib-off and Fib-fallback cases: `signal.fib_swing is None`.
4. **Detail helper.** `fibonacci_pullback_detail(_impulse_then_retrace(), "Bullish")` returns `{"at_level": True, "dist_pct": 0.07, "label": "61.8", "swing_low": <min low of bars[-100:]>, "swing_high": <max high of bars[-100:]>}`; for `_flat_bars(5)` (fewer than 10 bars) it returns all-`None`/`False` exactly as the tuple function's `(False, None, None)` plus `swing_low = swing_high = None`.
5. **Endpoints.** `/api/scan/prebreakout` (patch `app.routers.stock_scan.get_historical_bars` to return the pinned bars, `get_active` / `params_override` set to the pinned Fib-on parameters): the row has the unchanged `symbol/confidence/direction/metrics` plus `confidence_breakdown` (same dict as the engine's) and `fib_swing`. `/api/scan/fib-pullback` with `_impulse_then_retrace()` bars: existing keys and values unchanged, plus `fib_swing == {"low": …, "high": …}` equal to item 4's swing values (the endpoint's default `fib_swing_lookback` is from `_FIB_DEFAULTS`; compute the expected window from that value in the test).

Implementation:

- `strategy_engine.py`:
  - Rename the body of `_fibonacci_pullback_signal` into `_fibonacci_pullback_detail(...) -> dict` with the **same parameters**, returning `{"at_level": bool, "dist_pct": float | None, "label": str | None, "swing_low": float | None, "swing_high": float | None}`. `swing_low`/`swing_high` are the very variables the levels are built from (`max(b["high"] ...)` / `min(b["low"] ...)` of `window`); they are `None` on the `len(window) < 10` early return, and set (not `None`) on every later return, including the `move <= 0`, impulse, recency and no-level returns. No arithmetic changes.
  - `_fibonacci_pullback_signal(...)` keeps its signature and returns `(d["at_level"], d["dist_pct"], d["label"])` from the detail call. Public alias `fibonacci_pullback_detail = _fibonacci_pullback_detail` next to the existing alias.
  - `SetupSignal`: add `confidence_breakdown: dict | None = None` and `fib_swing: dict | None = None` (defaulted, after `metrics`).
  - `breakout_setup_signal`: call `_fibonacci_pullback_detail` instead of the tuple function (unpack the same three values; keep the swing pair). Compute the weighted sum **once** into `unrounded` using the existing expression, operand order unchanged (`atr_score * 0.24 + vol_score * 0.20 + prox_score * 0.36 + fib_score * 0.20` / `atr_score * 0.30 + vol_score * 0.25 + prox_score * 0.45`), then `confidence = int(unrounded)` — bit-identical to today's `int(<same expression>)`. Build:
    ```python
    {"fib_used": fib_enabled,            # after the two fallbacks
     "weights": {...},                   # the literals used in the sum
     "components": {name: {"score": s, "weight": w, "contribution": s * w}},
     "unrounded": unrounded,
     "confidence": min(100, max(0, confidence))}
    ```
    with components `atr`, `vol`, `proximity` (+ `fib` when used); `fib_swing = {"low": swing_low, "high": swing_high}` only when `fib_used`, else `None`. Return them on the `SetupSignal`. `metrics` and `confidence` untouched.
- `routers/stock_scan.py`:
  - `/scan/prebreakout`: add `"confidence_breakdown": signal.confidence_breakdown, "fib_swing": signal.fib_swing` to the result dict. Sorting unchanged.
  - `/scan/fib-pullback`: import and call `fibonacci_pullback_detail` with the same arguments; derive `at_level, dist_pct, level_hit` from it (same values); add `"fib_swing": {"low": d["swing_low"], "high": d["swing_high"]}` to the result dict. The existing `level_hit is None` skip, EMA filter, confidence formula and sort are unchanged.
  - `PreBreakoutResult` model (L122, currently unused by the route): add `confidence_breakdown: dict | None = None` and `fib_swing: dict | None = None` so the model matches what the route sends.

**Amendment after plan round 1 (plan round 2 scope).** `backend/tests/test_horizon_tuning_core.py::test_signal_cache_version_tracks_strategy_engine_source` pins the sha256 of `strategy_engine.py` (LF line endings) per `SIGNAL_CACHE_VERSION` (`backend/app/services/horizon_tuning/cache.py:35`, currently `1` → `a43b311f…aa2519`, the main/dcc015a5 bytes). Any edit to `strategy_engine.py` fails it until the version is bumped and the new hash pinned. The STOCKS-HORIZON-T1 tuning disk cache (`backend/data/tuning_cache/signals/`, gitignored, local) keys every cached signal series on `SIGNAL_CACHE_VERSION` (`signal_key`). No tuned signal function's output changes in this task (`breakout_setup_signal` and the Fib helper are not used by `horizon_tuning`; `confidence` / `metrics` / the Fib tuple are pinned unchanged), but the conservative step is the guard's documented convention — bump, so no cached series computed under the old source can be reused:
- Task 2's file list adds `backend/app/services/horizon_tuning/cache.py` (`SIGNAL_CACHE_VERSION = 1` → `2`, comment unchanged) and `backend/tests/test_horizon_tuning_core.py` (add `2: "<sha256 of the final strategy_engine.py, LF>"` to `_ENGINE_SOURCE_PINS`, keeping the `1:` pin).
- Effect: every signal key changes, so the next tuning run recomputes signal series once (cost only; old files are orphaned and never read). Gate-mask keys do not include `SIGNAL_CACHE_VERSION` and are unaffected. No live-scan, backtest-cache, confidence-cache or persisted scan-result behaviour changes.
- The pin must be the hash of the bytes actually committed; if `strategy_engine.py` changes again (e.g. a code-audit fix), re-pin `2` before any audit round closes (the version stays `2` while the branch is unmerged — nothing outside this branch ever wrote a version-2 key).

Commit: `feat(prebreakout): send the confidence sub-scores and Fib swing low/high (STOCK-PRES-P1 T2)`

### Task 3 — optional frontend types; old persisted results still load

Files: `frontend/types/stockDomain.ts`, `frontend/lib/api.ts`, `frontend/lib/scanStore.ts`, new `frontend/lib/__tests__/stockPresP1Types.test.ts`.

Tests first (new file):

1. **Old persisted state hydrates.** (`preBreakoutResults` / `fibPullbackResults` are session-only, so for them this only pins that `merge` passes old-shape rows through unchanged.) Using the real persist `merge` (as `scanStoreMergeHydration.test.ts` reaches it) and `migrate` at version 18 (as `scanStoreHorizonMigration.test.ts` reaches it): a blob with a `stockScanResult` whose candidate has no `stock_explanation`, `preBreakoutResults` rows with only `symbol/confidence/direction/metrics`, and `fibPullbackResults` rows with only the six current keys → hydrated values are deep-equal to the input (nothing dropped, nothing added).
2. **New fields survive the store.** `setPreBreakoutResults([...row with confidence_breakdown and fib_swing])` and `setFibPullbackResults([...row with fib_swing])` keep the fields; `setStockScanResult` with a candidate carrying `stock_explanation` keeps it (reference-equal).
   These tests are type-level red today (the new keys are not in the store's element types → `tsc` error in the test file); run `npm run typecheck` to see the red.

Implementation (types only, no runtime change, **no store version bump** — the persisted shape gains optional keys only):

- `types/stockDomain.ts`:
  - `import type { StockExplanation } from './domain';` add to `PositionCardData`:
    ```ts
    /** STOCK-PRES-P1: the scorer's evidence for stock_score — exactly the
     *  backend StockScoreCard.explanation. Its `status` is the SCORER's verdict
     *  before the scan's later caps; the verdict to show is `stock_status`.
     *  Absent on results persisted before P1; null if the backend could not
     *  validate it. */
    stock_explanation?: StockExplanation | null;
    ```
  - New exported types:
    ```ts
    export interface PreBreakoutConfidenceComponent { score: number; weight: number; contribution: number; }
    export interface PreBreakoutConfidenceBreakdown {
      fib_used: boolean;
      weights: Record<string, number>;
      components: Record<string, PreBreakoutConfidenceComponent>; // atr, vol, proximity (+ fib)
      unrounded: number;
      confidence: number;
    }
    export interface FibSwing { low: number | null; high: number | null; }
    export interface PreBreakoutResultRow {
      symbol: string; confidence: number; direction: string; metrics: Record<string, number>;
      /** STOCK-PRES-P1. Absent on rows persisted before P1. */
      confidence_breakdown?: PreBreakoutConfidenceBreakdown | null;
      /** Swing low/high the Fib levels were measured from; null when Fib was not used. */
      fib_swing?: FibSwing | null;
    }
    export interface FibPullbackResultRow {
      symbol: string; direction: string; fib_level_hit: string; fib_dist_pct: number | null;
      at_level: boolean; confidence: number;
      /** STOCK-PRES-P1. Absent on rows persisted before P1. */
      fib_swing?: FibSwing | null;
    }
    ```
- `lib/api.ts`: `prebreakoutScan` → `post<PreBreakoutResultRow[]>`, `fibPullbackScan` → `post<FibPullbackResultRow[]>` (same URLs, bodies, params).
- `lib/scanStore.ts`: `preBreakoutResults` / `setPreBreakoutResults` use `PreBreakoutResultRow[]`; `fibPullbackResults` / `setFibPullbackResults` use `FibPullbackResultRow[]`. Nothing else in the store changes (`version` stays 18; `migrate`, `merge`, `partialize` untouched).
- `app/(frame)/screener/step-4-prebreakout/page.tsx` is not edited (P5). Its local row types are structural subsets of the new ones, so it type-checks unchanged; if `tsc` disagrees, stop and report (plan defect) rather than edit the page.

Commit: `feat(types): optional stock evidence, Pre-Breakout breakdown and Fib swing types (STOCK-PRES-P1 T3)`

## Ticket graph

T1 and T2 both edit `backend/app/routers/stock_scan.py` → serialized: **T1 → T2 → T3** (T3 types mirror T1/T2's wire shape). Coordinator ticket (acceptance check, `git merge origin/main`, code audit, PR) blocked by all three.

## Acceptance checklist (#146) — checked by the coordinator before the code audit

- [ ] `stock_explanation` on every new stock-scan candidate equals the scorer's `StockScoreCard.explanation` (T1 test 1); `stock_score`, `stock_status`, `gate_flags`, sizing and every other existing field unchanged (T1 tests 1-2 + existing suites).
- [ ] Pre-Breakout `confidence_breakdown` reproduces `confidence`; `fib_swing` equals the swing the levels were measured from; pinned `confidence` / `metrics` / Fib tuple unchanged (T2 tests 1-5).
- [ ] An old persisted stock scan result (backend JSON and browser store) and old Pre-Breakout / Fib rows still load (T1 test 5, T3 test 1).
- [ ] No UI file changed; no formula, gate, sort or persistence-version change (diff review).
- [ ] Python 3.11 backend suite + frontend typecheck/Jest green (failures only where identical on `origin/main`); plan audit and code audit clean (`audit_rule`).

## Audit record

- Plan round 1 (2026-10-10): fresh independent gate auditor, plan at c9335d89 vs main 8d1e32e — **0 gate findings, clean**. Two below-gate notes applied as clarifications without behaviour change: the session-only Pre-Breakout/Fib store fields (Facts), and the two `test_fib_pullback_endpoint.py` patches T2 must repoint.
- Plan amendment (2026-10-10, after the T2 implementer reported a plan defect): Task 2 also bumps `SIGNAL_CACHE_VERSION` 1→2 and pins the new `strategy_engine.py` hash. Plan round 2 audits only this amendment and its interactions.
- Plan round 2 (2026-10-10): fresh independent gate auditor, scope = the amendment only (`git diff 18b3fbb0..a27bf075` on this plan) and its interactions — **0 gate findings, clean**. Below-gate note: the bump also changes each cell's `run_key` in `backend/scripts/tune_horizons.py` (~L330), so `--resume` recomputes already-finished tuning cells once; time cost only, never a stale number.
- Code round 1 (overall round 3, 2026-10-10): fresh independent gate auditor on `git diff 13c8b52c..fd8cdb0b -- backend frontend` (main merged) — **0 gate findings, clean**. Differential run of the old vs new engine over 20,000 random bar series: identical numbers.
