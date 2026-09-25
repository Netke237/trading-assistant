# A5c — the Analysis page flags every filter on which the stock scan would drop the symbol

**Decisions:** `A5B-A5C-LOCKED-2026-09-24` (the four original filters, REJECT flag, card
unchanged, helpers shared with `_process_stock`) widened by `A5C-SCOPE-SIX-FILTERS-GO-2026-09-25`
(Kenneth, 2026-09-25: "Include both", "lets Go") to six filters. Phase
`A5C-ANALYSIS-SCAN-DROP-FLAGS`. Audit cap counts per stage (`AUDIT-CAP-PER-STAGE-2026-09-25`).

Layer: backend only, one router file plus one test file. No frontend change: the Analysis page
already renders every `gate_flags` entry as `StatusBadge(status) + "{gate}: {detail}"` under
"Advisory — would not pass scanner" (`frontend/app/(frame)/analysis/page.tsx:289-299`).

## 1. The defect (measured on main `489202d`)

`_analyze_core` (`backend/app/routers/stock_scan.py:369-555`) is meant to mirror the scan
(decision `A5-ANALYSIS-MIRRORS-SCAN`), but on six filters where `_process_stock` (:720-1083)
**drops** the symbol, Analysis either says nothing or says CAUTION:

| # | Filter | Scan (`_process_stock`) | Analysis today |
|---|---|---|---|
| 1 | Direction-conviction floor | :859-893 → `"direction_conviction: trend {t} < {m:g} for {dir} {hor}"` | not checked |
| 2 | Regime headwind with `req.regime_filter` | :895-897 → `"regime headwind"` | CAUTION flag (:450), same even when `regime_filter` is on |
| 3 | No setup (incl. `require_choppy_regime`, passed via `_SIGNAL_KWARGS`) | :946-947 → `"no {strategy} setup"` | CAUTION flag (:481-482) — **the defect marker** |
| 4 | `mean_reversion_multi` | :899-925 variant loop → `"no mean_reversion_multi: {n}/{m} signals fired"` or `"mean_reversion_multi: variants produced no valid combined levels"` | `_SIGNAL_FNS` has no multi entry → signal is always None → "no setup" CAUTION without evaluating anything; no backtest shown |
| 5 | Backtest gate | :965-966 → `"backtest gate: {summary_text}"` | CAUTION flag (:502-503) |
| 6 | Insufficient intraday history (`mean_reversion_vwap`) | :748-757 → `"insufficient intraday history"` when `< 30` 15m bars | not checked |

Consequence (the gate): the Analysis page shows a symbol as passable, or merely cautioned, that
the scan the user just ran threw away — a wrong verdict in front of the user. For multi it shows
"no setup" for a symbol the scan may have **kept**, and no backtest at all.

One further mirror gap found while reading, same mechanism, fixed here because a REJECT flag
built on it could be wrong:

- (Round 1 correction: an earlier draft listed a "G1 — intraday fetch window" gap, 80 vs 55 days.
  It does not exist: `fetch_intraday_candles` caps Tradier and yfinance at 55 days and calls IBKR
  only for 1h/4h/daily/weekly (`market.py:430-432`), so both fetches return the same 15m bars.
  H0 is withdrawn; the fetch arguments are left as they are.)
- **G2 — the 422 guard.** `run_stock_scan` (:1134-1139) refuses `mean_reversion_multi` with the
  intraday `mean_reversion_vwap` variant, because the variant loop runs every variant on DAILY
  bars. Once Analysis runs the loop for real (filter 4), it must refuse the same request, or it
  would compute that variant on daily bars mislabelled as 15m — the exact defect the guard exists
  to prevent.

## 2. Design: one "drop reason" per filter, shared, returning the scan's own string

Each filter becomes a module-level helper in `stock_scan.py` that returns **the exact reason
string `_process_stock` returns today** (or `None`). The scan returns
the helper's dict; Analysis appends
`{"gate": <gate>, "status": "REJECT", "detail": f"the scan would drop this: {r}"}`.
Reason strings must stay **byte-identical**: the funnel classifier buckets them
(`tests/test_stock_scan_funnel.py:_REAL_STOCK_REASONS`, `test_scan_direction_funnel.py:410`).

**Form of the return value (round 1).** `test_every_stock_reason_producer_is_classified`
(`test_stock_scan_funnel.py:~259-285`) finds every reason producer by regex over the module
source, `"reason":\s*\(?\s*f?"…`, with a floor of 10 distinct matches, and fails if any producer
has no funnel bucket. A helper that returned a bare string would hide its literal from that regex,
so a future reason added inside a helper could go unbucketed and miscount the funnel, and the
floor would break at build. So each helper returns the scan's rejection dict itself,
`{"symbol": symbol, "reason": f"…"}` (or `None`), keeping the `"reason": f"…"` literal in the
source. The scan does `if (d := helper(...)): return d`; Analysis reads `d["reason"]`. The test is
left unchanged and must still pass (same producers, same floor).

`card.status` is never changed by any of these flags (existing convention: the price, score and
confidence-REJECT flags leave the card alone). Flags are independent: Analysis evaluates and flags
every failing filter, whereas the scan stops at the first. Any one REJECT flag means "the scan
would drop this", which is what the page's heading says.

### H1 — `_intraday_history_drop(symbol, strategy, intraday_bars) -> dict | None`
`"insufficient intraday history"` iff `strategy in _INTRADAY_STRATEGIES and len(intraday_bars) <
_MIN_INTRADAY_BARS` (new constant `= 30`, replacing the literal at :756). Scan: replaces :756-757
(the fetch and its `except` stay where they are; a failed fetch leaves `[]` → drop, as today).
Analysis: after its intraday fetch; gate `"intraday_history"`. Signal/backtest evaluation in
Analysis is **not** skipped when this fires (the page still shows what it can); only the flag is
added.

### H2 — `_direction_conviction_drop(symbol, card, min_trend, direction, horizon) -> dict | None`
Body moved verbatim from :869-893 (the `, 50` fallback and its comment move with it). `None`
when `min_trend is None` (exempt, e.g. Intraday). Scan: `_min_trend` stays resolved at the top of
`_process_stock`, outside the `try` (:737 comment unchanged). Analysis: resolves
`load_direction_conviction_min_trend(req.direction, req.horizon)` as its **first statement,
before any fetch**, so a malformed YAML threshold raises (→ HTTP 500) instead of being reported as
a symbol verdict — same contract as the scan. Gate `"direction_conviction"`.

### H3 — `_regime_headwind(regime_signal, regime_gate) -> bool`
`bool(regime_signal) and regime_signal["conviction_pct"] <= regime_gate.get("headwind_caution_pct",
-15)` — the condition at :450 and :896, now one function. It returns a bool, not a dict, because Analysis also needs it when the
scan does NOT drop (the CAUTION case); the scan's `return {"symbol": symbol, "reason": "regime
headwind"}` stays literally at its call site:
`if req.regime_filter and _regime_headwind(...): return {"symbol": symbol, "reason": "regime headwind"}`.
Analysis's REJECT detail spells the same text, `"regime headwind"`; T2 asserts Analysis's detail starts with
`"the scan would drop this: " + <the scan's reason>`, so either side drifting turns T2 red.
Analysis: when it holds, gate `"regime_headwind"`: **REJECT** with detail `"the scan would drop
this: regime headwind (conviction {c}%)"` if `req.regime_filter`, else **CAUTION** with today's
detail `"conviction {c}%"` (advisory — the scan keeps it). One flag, never both.

### H4 — `_multi_signal(symbol, req, bars) -> tuple[signal | None, dict | None]`
The variant loop :899-921 moved verbatim (valid-variant filter, per-variant `vwap_daily` extra
kwargs, `_merge_strategy_params`, `fn(bars[-120:], direction=…, **kw)` with no `current_price`,
per-variant `except → None`, `min_confirmations`, `resolve_multi_signal`). Returns
`(signal, None)` or `(None, reason)` with the two existing reason strings. Plus
`_MULTI_BT_STRATEGY = "mean_reversion_rsi"` and `_multi_bt_params(req)` (the :922-925 RSI-proxy
params) so both callers backtest the same thing. Scan: the multi branch calls them; behaviour
identical. Analysis: when `req.strategy == "mean_reversion_multi"` it calls `_multi_signal(symbol, req,
bars)`; the reason becomes the `"signal"` REJECT flag; on a signal it backtests
`_MULTI_BT_STRATEGY` on **daily** `bars` with `_multi_bt_params(req)` through the same
`_backtest_key` → so the scan and the page share one cache entry and one verdict.

Analysis's backtest block is restructured to use `(_bt_strategy, _bt_bars, _bt_params)` like the
scan (today it reuses `req.strategy` / `signal_kwargs` directly); for non-multi strategies the
three values are exactly today's.

### H5 — no setup
`_no_setup_drop(symbol, strategy) -> dict` = `{"symbol": symbol, "reason": f"no {strategy} setup"}`, used by :947 and Analysis. The
Analysis `"signal"` flag becomes REJECT with `"the scan would drop this: no {strategy} setup"` —
this removes the defect marker `"gate": "signal", "status": "CAUTION"`. Known, accepted
asymmetry: a `signal_fn` that **raises** is caught in Analysis (→ None → this flag), while in the
scan it escapes to the outer `except` and the reason is `str(exc)`; both drop.

### H6 — `_backtest_drop(symbol, bt_result) -> dict | None`
`f"backtest gate: {bt_result.summary_text}"` iff `not bt_result.passes_gate`. Scan :965-966;
Analysis flag `"backtest"` goes CAUTION → REJECT, detail `"the scan would drop this: backtest
gate: …"`. Confidence is still computed and shown after a failed backtest (as today).

### H7 — `_reject_unsupported_multi_variants(req)` (fixes G2)
The :1134-1139 check moved into a function that raises the same `HTTPException(422, same
detail)`. Called first thing in `run_stock_scan` (unchanged position) and first thing in
`analyze_stock`. Not reachable from the shipped UI (MeanReversionConfirmPanel offers only
rsi/bb/vwap_daily); the Analysis request replays the scan's request, which already passed it.

### Not changed
- The scan's filter **order** and every reason string.
- Analysis's existing price / score / confidence flags and its CAUTION cap.
- Frontend (renders any `gate`/`status`/`detail`).
- `run_stock_scan`, auto-trader, options scan: untouched beyond H7's moved lines.

## 3. Tests — new `backend/tests/test_a5c_analysis_scan_drop_flags.py`

Reuses A5's offline harness (`_offline`, `_flags`, imported or copied into the new file).
Every "scan" leg calls `ss._process_stock` directly with the same monkeypatched data, so each
test asserts **both** sides of the mirror on one fixture.

- **T1 conviction.** A card with `rules=[trend 20]`, Bearish/Position (floor 40): `_process_stock`
  reason == `"direction_conviction: trend 20 < 40 for Bearish Position"`; Analysis has exactly one
  `direction_conviction` REJECT flag whose detail ends with that string; `card.status` unchanged
  (PASS). Trend 60 → no flag, scan passes that filter. Intraday (exempt) → no flag.
- **T2 regime headwind.** conviction -20 vs caution -15: `regime_filter=True` → scan reason
  `"regime headwind"`, Analysis one REJECT `regime_headwind` flag; `regime_filter=False` → one
  CAUTION flag, scan does not drop there. conviction -5 → no flag either way.
- **T3 no setup.** `_SIGNAL_FNS[strategy]` stubbed to return None: scan reason `"no pullback_ema
  setup"`, Analysis `signal` flag REJECT with that string; `require_choppy_regime=True` reaches the
  stubbed fn's kwargs for `mean_reversion_rsi` in both paths (spy).
- **T4 multi.** Variant fns stubbed (rsi fires, bb fires, vwap_daily not), min 2. **Each stub
  records the `bars` list it receives** and builds its signal's levels from that list
  (e.g. stop = min low of the bars, target = max high), so a different window changes the output.
  Assert (round 1): the Analysis and `_process_stock` legs pass each variant **the identical bars**
  — length 120, same first and last bar as `_BARS[-120:]` — and no `current_price` kwarg. Then →
  Analysis `core.signal.strategy == "mean_reversion_multi"`, a backtest was run with
  `strategy="mean_reversion_rsi"` on the daily bars, and its `_backtest_key` equals the scan's for
  the same fixture (spy on `run_strategy_backtest`/key). 1 of 3 fired, min 2 → both sides give
  `"no mean_reversion_multi: 1/3 signals fired"`. `resolve_multi_signal` → None → both give the
  "no valid combined levels" string. Levels identical between scan card and Analysis signal.
- **T5 backtest.** `passes_gate=False, summary_text="38% win over 12 trades"` → scan reason
  `"backtest gate: 38% win over 12 trades"`, Analysis REJECT `backtest` flag; `passes_gate=True`
  → no flag.
- **T6 intraday history.** `strategy="mean_reversion_vwap"`, 29 bars → scan reason
  `"insufficient intraday history"`, Analysis REJECT `intraday_history` flag; 30 bars → no flag;
  fetch raises → flag (both). Non-intraday strategy with 0 bars → no flag.
- **T7 funnel guard.** `test_every_stock_reason_producer_is_classified` passes unchanged, and
  the set of producers its regex finds is the same as on main (captured once at build and
  compared in the round record).
- **T8 422.** `POST /api/analyze-stock` with `strategy="mean_reversion_multi"` and
  `mean_reversion_vwap` in the variants → 422 with the scan's detail; the scan endpoint still 422s.
- **T9 card untouched.** For each of T1-T6's failing fixtures, `core.card.status` equals the
  status `score_stock` returned.
- **T10 malformed floor.** `load_direction_conviction_min_trend` raising → `_analyze_core` raises
  (not a flag, not None).
- **Existing tests.** The funnel reason tests (see T7) and `test_analyze_stock.py` must pass unchanged
  (the latter asserts no flag severities for signal/backtest; checked at build — any pin on the
  old CAUTION severity is updated, and named in the round record).

### Mutation checks (each must turn at least one test red, then be reverted)

| # | Mutation | Expected red |
|---|---|---|
| M1 | Analysis signal flag back to `"CAUTION"` | T3 |
| M2 | Analysis ignores `req.regime_filter` (always CAUTION) | T2 |
| M3 | `_regime_headwind` uses `<` instead of `<=` | T2 (boundary fixture at exactly the threshold) |
| M4 | Analysis skips `_direction_conviction_drop` | T1 |
| M5 | `_MIN_INTRADAY_BARS = 29` | T6 |
| M6 | Analysis backtests multi with `req.strategy` instead of `_MULTI_BT_STRATEGY` | T4 |
| M7 | Analysis calls `_multi_signal(symbol, req, bars[-60:])` (a copy that drifts) | T4 (the bars-identity assertion, and the bars-derived levels) |
| M8 | Analysis backtest flag back to CAUTION | T5 |
| M9 | drop the `analyze_stock` 422 call | T8 |
| M10 | one helper returns a bare reason string (scan wraps it) | T7 (regex floor / producer set) |
| M11 | Analysis sets `card.status = "REJECT"` on a drop flag | T9 |

## 4. Verification

`cd backend && .venv/bin/python -m pytest -q` (full suite), `python3 scripts/state.py`.
Frontend untouched (no typecheck/Jest run needed beyond confirming no file changed).

## 5. State

Phase `A5C-ANALYSIS-SCAN-DROP-FLAGS`: `audit_rounds` / `audit_clean` / note per round. Its
`defect_marker` (`"gate": "signal", "status": "CAUTION"`) disappears with H5, so at build the
verify entry switches to a presence probe on `def _direction_conviction_drop\(` in
`backend/app/routers/stock_scan.py`.

## 6. Residuals (logged, not built)

- The scan stops at its first drop reason; Analysis lists every one. Intended.
- Analysis still runs its signal on up to 300 intraday bars from the same fetch as the scan
  (both `[-300:]`), so no gap there; the two fetches happen at different times, so a bar that
  closes in between can differ. Inherent to two requests, not fixable by sharing code.
- The frontend heading "Advisory — would not pass scanner" also covers CAUTION flags that do not
  drop. Wording only; not gate-level.

## 7. What this changes for the user (for the handoff)

When the scan would throw a symbol away, the Analysis page now says so with a red REJECT flag
naming the scan's own reason — trend too weak for the direction, regime headwind (with the regime
filter on), no setup, the multi-strategy not confirming, the backtest gate, or too little intraday
history. The headline score and status do not change. For `mean_reversion_multi`, Analysis now
actually evaluates the variants and shows the setup and its backtest, instead of always "no setup".

## 8. Audit record

- **Plan round 1 (2026-09-25): ONE gate-level finding.** F1-1: mutation M7 could not fail — T4's
  variant stubs ignored their bars and the backtest key does not depend on the variant window, so a
  drifted bar slice in Analysis (different multi verdict/levels from the scan) would ship untested.
  Fixed: T4's stubs record their bars and derive levels from them; T4 asserts both legs pass
  identical bars. Two non-gate corrections noted by the reviewer, taken because each was a false
  statement about mechanism in this plan: G1/H0 withdrawn (IBKR is never used for 15m bars, so no
  window gap exists); helpers return the scan's rejection dict so the funnel producer-regex guard
  keeps seeing every reason literal (a bare-string helper would have broken its floor at build and
  hidden future reasons from it). Round 2 reviews only these amendments.
