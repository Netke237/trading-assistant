# NUMERIC-API-INPUTS — reject NaN/Infinity at the API boundary (board #164)

**Phase id:** `NUMERIC-API-INPUTS` · **Board item / tracking issue:** #164 · **Source:** `.scratch/project-ticket-reconciliation-20261009/issues/33-numeric-api-residuals.md`
**Branch:** `board/numeric-api-inputs-54c0ddc4` (from origin/main 13c8b52c)
**Goal (item):** no NaN/Infinity reaches calculations or storage.

## 1. Inventory (done before this plan; evidence)

Method: a script (`scratchpad inventory.py`, reproduced as the T3 test) builds the real app with `create_app()` under Python 3.11.17 with the pinned `requirements.txt` (FastAPI 0.141.1, pydantic 2.13.4). It walks every `APIRoute` (FastAPI 0.141 nests included routers as `_IncludedRouter`, so it recurses through `original_router.routes`) — 143 routes. For every query/path/header/cookie/body parameter it walks the parameter's pydantic-core schema. Each `float` leaf is validated directly with its own constraints and the effective `allow_inf_nan` (field value, else the nearest model `config`), against `nan`, `inf`, `-inf`, the string `"NaN"` and the string `"1e999"`. Untyped leaves (`Any`, `dict` with `Any` values) are listed separately.

How each value arrives:

- **JSON literals.** FastAPI parses bodies with `json.loads`, which accepts the literals `NaN`, `Infinity` and `-Infinity`. It turns an overflowing number such as `1e999` into `inf`.
- **Strings.** Pydantic's lax mode turns the string `"NaN"`, `"inf"` or `"1e999"` into a non-finite float.
- **Fields without an upper bound.** `gt=`/`ge=` alone rejects NaN (every comparison with NaN is false) but accepts `+inf`.

Results:

- **Query parameters: 3 float query params exist** (`/api/contracts` `max_price`, `/api/regime` `threshold`, `smoothing`). All are bounded on both sides, so all already reject. Path, header and cookie params have no float leaves. No route takes a raw `Request` and parses the JSON itself.
- **Body float leaves that accept a non-finite value: 123, in these request models:**

| Model | File | Fields accepting non-finite (A = NaN, ±inf, "NaN", "1e999"; B = +inf, "1e999" only) |
|---|---|---|
| `AlertNotifyRequest` | `app/routers/alerts.py:62` | price, referenceValue (A) |
| `ArmRequest` | `app/routers/auto_trade.py:69` | portfolio_value, regime_headwind_caution_pct, regime_headwind_reject_pct (A); stop, scan_stock_price, structural_stop, premium_stop_dollar (B) |
| `StockOrderRequest`, `OptionOrderRequest` | `app/routers/broker.py:227/247` | limit_price (B) |
| `DrawingPoint` | `app/routers/chart_drawings.py:23` | price (A) — **shared with `DrawingOut` (response built from stored rows)** |
| `RecomputePlanRequest` | `app/routers/contracts.py:404` | delta, spread (A); stock_price, strike, premium, hold_min, hold_max (B); `final_stop: FinalStopOut` price/structuralPrice/atrFloorPrice/distanceDollar/atr (A) — **`FinalStopOut` is built internally by `app/scoring/exit_plan.py:161` and returned in responses** |
| `StructuralStopRequest` | `app/routers/contracts.py:623` | stock_price, strike, premium (B) |
| `FirstPassageRequest` | `app/routers/contracts.py:738` | delta (A); stock_price, strike, premium, invalidation_price, t1_pct, t2_pct, t3_pct, hold_min, hold_max (B) |
| `ExitPlanRequest` | `app/routers/contracts.py:1008` | entry_price, strike, premium (B) |
| `JournalEntryCreate` | `app/routers/journal.py:38` | entry_price, exit_price, position_size, stop_loss, risk_dollars, net_pnl (A) — persisted |
| `PortfolioPositionCreate` | `app/schemas/__init__.py:1143` | stop, structuralStop, portfolioValue, scanStockPrice (A); premiumStopDollar (B) — persisted; **also built internally by `app/services/auto_trade_booking.py:197`** |
| `PortfolioPositionUpdate` | `app/schemas/__init__.py:1293` | stop, structuralStop, portfolioValue (A) — persisted |
| `ClosePositionRequest` | `app/schemas/__init__.py:1437` | exitPrice (A) — persisted |
| `ScanRequest` | `app/schemas/__init__.py:808` | 19 floats (A): min/max_price, min/max_cap_usd, confidence_atr_mult_target/stop, fundamentals_* (5), regime_headwind_caution/reject_pct, spread_width, short_leg_delta, iv_rank_threshold, iv_abs_threshold, min_credit, max_debit_pct — **re-validated from stored schedules** |
| `StockScanRequest` (+ subclass `StockAnalysisRequest`) | `app/schemas/stock_scan.py:11/246` | 17 floats (A) + breakout_volume_mult, account_size, vwap_deviation_pct (B) — **re-validated from stored schedules and the saved last request** |
| `StockFirstPassageRequest` | `app/routers/stock_scan.py:2221` | targets items (A); stock_price, stop_price (B) |
| `StockExitPlanRequest` | `app/routers/stock_scan.py:2404` | entry_price (B). Its `rr_ratios` list shows as (A) in the schema walk, but its `_positive_finite_ratios` field validator already rejects non-finite values: **already guarded, no change.** |

- **Untyped leaves: 34** (`dict`/`dict[str, Any]`/`Any`). The values are not validated, so only a JSON-level guard can reach them:
  - ArmRequest: exit_plan, targets, max_loss_override, trade_card_snapshot;
  - AlertHistoryCreate: candle, trigger_values;
  - AlertRuleCreate: composite_def, conditions;
  - AlertTestRequest: candles, indicators, signals;
  - CompositeWatchCreate: trigger_def;
  - CredentialUpdate: values;
  - PortfolioPositionCreate/Update: exitPlan, targets, tradeCardSnapshot, maxLossOverride, alertOverrides;
  - ScanRequest/StockScanRequest: overrides;
  - ScanScheduleEntryCreate: resolved_request;
  - Fib/PreBreakout scan: params_override;
  - AddWatch: params_override;
  - AdoptRequest: params;
  - strategy-tuning run: its whole body;
  - WatchedContractAddRequest: grading.contract_rules.

  Several of these are persisted (portfolio JSON columns, alert history, schedules).
- **Already in place:** 21 `allow_inf_nan=False` sites (e.g. `PortfolioPositionCreate.entryPrice`, `ArmRequest.limit_price/entry_premium`). Also `main.py:353` `request_validation_handler` (decision `P6-SCOPE-2026-09-30`), which makes a 422 that echoes a non-finite input serialisable instead of a 500. This phase builds on that handler.

### Deliberate inventory extension — CANDIDATE-BACKTEST-CHART (2026-10-15)

The original 34-leaf inventory above is retained as historical evidence. The current route-wide ratchet pins **35 untyped leaves**, adding exactly:

| Route | Parameter kind | Leaf kind | Schema path |
|---|---|---|---|
| `POST /api/backtest-artifacts/fresh` | body | any-dict | `request.<FreshBacktestRequest>.params` |

`FreshBacktestRequest.params` deliberately carries a strategy-dependent object. Its dict value schema is untyped, but its whole-model validator calls `validate_parameters` before the endpoint runs. For each supported daily strategy it requires the complete signature-derived key set, rejects unknown keys, checks strict scalar types (including rejecting numeric strings and booleans as numbers), bounds integer/float parameters and signal-window requirements, requires finite floats, and requires an explicit null historical `current_price`. Multi-strategy configuration requires unique supported daily variants, an integer confirmation count within the selected count, and an exact matching `variant_params` key set; the same validator recursively checks every selected variant's complete parameters. It does not accept ambient parameter defaults.

The application-wide `NonFiniteJsonGuard` additionally rejects NaN/Infinity/overflowing numeric literals at any depth before request validation. `test_fresh_backtest.py::test_nonfinite_params_rejected_before_history_or_engine` uses the real `create_app()` stack to pin HTTP 422 for direct and multi-nested literals and nonfinite strings, asserts neither historical data nor the backtest engine runs, and confirms the same finite configuration reaches history. The inventory walker still requires exact set/count equality, probes every typed float leaf, and has no float allowlist. Future untyped additions still fail until deliberately documented and covered.

## 2. Validation outcome (one rule, everywhere)

Any non-finite number in a request input gets **HTTP 422** with FastAPI's standard shape: `{"detail": [{"type", "loc", "msg", "input"}]}`. That shape is what `frontend/lib/api.ts` `apiError` reads. "Non-finite number" covers:
- a NaN or ±Infinity literal;
- a JSON number that overflows to ±inf;
- a string coerced into a float field ("NaN", "inf", "1e999").

Finite input behaves exactly as today. No new bounds and no other validation changes. The browser can never send a NaN literal (`JSON.stringify(NaN)` is `null`), so no current frontend request changes behaviour.

## 3. Tickets

### T1 — JSON boundary guard (blocks T3)
**Files:** new `backend/app/request_guards.py`; `backend/app/main.py` (registration only); new `backend/tests/test_request_json_finite_guard.py`.
- A **pure ASGI middleware** `NonFiniteJsonGuard`. Not `BaseHTTPMiddleware`, which mishandles body replay and background tasks.
  - **Scope.** Only `scope["type"] == "http"` and methods POST/PUT/PATCH/DELETE. Everything else passes through untouched, websockets included.
  - **When it parses.** Exactly when FastAPI would parse JSON: a `content-type` header whose subtype is `json` or ends with `+json` (FastAPI 0.141 `routing.py:436-446`, `strict_content_type` default True, so a missing content-type is not parsed as JSON there and is not inspected here).
  - **How it parses.** It buffers the full body (all `http.request` messages until `more_body` is false), then parses with `json.loads(body, parse_constant=..., parse_float=...)`. `parse_constant` raises on `NaN`/`Infinity`/`-Infinity`. `parse_float` raises when `float(s)` is not finite.
  - **On a non-finite value:** it sends a 422 `JSONResponse` and does not call the app. The body is `{"detail": [{"type": "finite_number", "loc": ["body"], "msg": "Input should be a finite number", "input": "<the literal text, e.g. 'NaN' or '1e999'>"}]}`, the same type and message pydantic uses.
  - **On any other decode error** (invalid JSON, bad UTF-8): it passes the original bytes through unchanged so FastAPI keeps its current error. The guard never changes what valid finite JSON means.
  - **Replay.** A `receive` wrapper returns the buffered body once as a single `http.request` (`more_body: False`), then delegates to the original `receive` (so `http.disconnect` still works).
- **Registration:** `app.add_middleware(NonFiniteJsonGuard)` placed **before** the existing `CORSMiddleware` call in `create_app()`. Starlette makes the last-added middleware outermost, so CORS wraps the guard and the 422 carries CORS headers.
- **Tests** (TestClient on `create_app()`; no provider calls, since each request is refused before the endpoint runs or hits a trivial endpoint):
  1. NaN, Infinity, -Infinity and `1e999` inside an untyped dict, e.g. `POST /api/portfolio` with `targets: {"t1": NaN}` → 422 with type `finite_number`; the endpoint is not called (patch it to fail if called).
  2. The same literal in a nested list inside an untyped dict → 422.
  3. A `+json` content type → guarded; `text/plain` → not inspected (current behaviour kept).
  4. A string `"NaN"` inside an untyped dict passes the guard (documented residual, §5).
  5. A finite JSON body reaches the endpoint byte-identical (assert on a tiny echo route mounted in the test app) and chunked bodies (`more_body`) are reassembled.
  6. The 422 carries `access-control-allow-origin` for an allowed origin.

### T2 — Schema guard on the request models (blocks T3)
**Files:** the model files in §1 (`app/routers/alerts.py`, `auto_trade.py`, `broker.py`, `chart_drawings.py`, `contracts.py`, `journal.py`, `stock_scan.py`, `app/schemas/__init__.py`, `app/schemas/stock_scan.py`), `app/routers/scan_schedule.py` (list endpoint), new `backend/tests/test_request_finite_models.py`.
- Add `allow_inf_nan=False` to the **model config** of each request model in the §1 table. Where a model already has a `model_config`, add the key there (`ArmRequest` keeps `extra='forbid'`; the portfolio, close and analysis models keep `populate_by_name=True`). `StockAnalysisRequest` inherits it from `StockScanRequest`. Pydantic v2 merges a parent's config into a subclass.
- **Shared models are not changed.** A request-only subclass carries the guard instead:
  - `FinalStopIn(FinalStopOut)` with `model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)`, in `app/schemas/__init__.py` next to `FinalStopOut`. Only `RecomputePlanRequest.final_stop` changes type, to `FinalStopIn | None`. `exit_plan.py:161` and every response keep `FinalStopOut`. `contracts.py:568` passes `req.final_stop` into a `FinalStopOut`-typed response field; a subclass instance is valid there and serialises with the parent's fields. Assert this in a test: the recompute-plan response JSON for a finite `final_stop` is unchanged.
  - `DrawingPointIn(DrawingPoint)` with `allow_inf_nan=False`; `DrawingIn.points: list[DrawingPointIn]`. `DrawingOut` keeps `DrawingPoint`, so a drawing already stored with a non-finite price still lists. Persisted rows are not rewritten (§5).
- **Internal construction paths (behaviour stated, then tested):**
  - `auto_trade_booking._build_body` builds `PortfolioPositionCreate`. With the guard, a strategy carrying a non-finite stop, portfolio value, scan price or structural stop now fails to build. The existing `except Exception` at `auto_trade_booking.py:391-393` then routes it to `_refuse(fired, "the position did not build: …", True)`: the not-booked alert and page, broker order live. Before this change the non-finite value was written to the portfolio row. Test: a `FiredOrder` with `structural_stop=float("nan")` → `book_fired_order` returns the refused outcome, writes no row, and `_alert_not_booked` is called with `broker_live=True`.
  - `ScanRequest`/`StockScanRequest` re-validation from stored data:
    - (a) The scheduler (`scan_schedule_scheduler.py:139/158`) already catches, logs and records a failed run. With the guard, an entry whose stored `resolved_request` holds a non-finite value records a failed run instead of scanning with it. No code change; a test pins it.
    - (b) `GET /api/scan-schedule` (`routers/scan_schedule.py:48`) validates every stored entry; one legacy non-finite entry would turn the whole list into a 500. Change: validate each entry inside `try/except ValidationError`, **skip** the failing entry and `logger.warning` its id. This is the same drop-with-warning rule `restore_stock_from_db` already applies (`stock_scan.py:725-742`). The entry stays in the store, `DELETE /api/scan-schedule/{id}` still removes it, and the scheduler records its failed runs. Test: a store with one valid entry and one entry with `min_price: nan` → 200 listing only the valid one.
    - (c) `scan.py:1595` restores `ScanRequest.model_validate_json(row.last_request_json)`. That JSON is written by `model_dump_json()` (`scan.py:1525`), which serialises NaN/inf as `null` (pydantic default `ser_json_inf_nan='null'`), so it can never contain a non-finite literal. No change; the test asserts `ScanRequest(...).model_dump_json()` of a finite request round-trips.
    - (d) `stock_scan.py:734` already catches `ValidationError`/`ValueError` and drops the replay. No change.
- **Tests**, parametrised over every (model, field) in the §1 table:
  - `model_validate` with a minimal valid payload plus that field set to `float('nan')`, `float('inf')`, `float('-inf')`, `"NaN"` and `"1e999"` → `ValidationError` of type `finite_number`.
  - The same payload with a finite value → validates.
  - Minimal valid payloads live in the test module as a dict per model, built from each model's required fields.
  - Plus one HTTP check per router (e.g. `POST /journal/entries` with `entry_price: "NaN"` → 422 through the main.py handler, not 500).

### T3 — Route-wide ratchet test (blocked by T1, T2)
**Files:** new `backend/tests/test_request_finite_inventory.py` only.
- Build `create_app()`, walk every `APIRoute` the way §1 does (recursing `_IncludedRouter.original_router.routes` and nested `Dependant.dependencies`), and walk each parameter's core schema.
- **Assert zero float leaves** accept any of nan, inf, -inf, "NaN", "1e999". There is no allowlist. A leaf inside a `function-*` validator is probed against its float schema only, so `StockExitPlanRequest.rr_ratios` would still show; it gets an explicit allowlist entry with the reason (already guarded by `_positive_finite_ratios`) and a sub-test that sends `rr_ratios: [NaN]` through the HTTP route → 422.
- Assert the route count is > 100, so a FastAPI change that hides routes from the walk fails loudly instead of passing vacuously.
- Assert every untyped leaf is reached by the T1 guard: list them and assert that the count equals the §1 inventory (34). A new untyped leaf fails the test with a message pointing at this plan, so it gets a conscious decision.

## 4. Order and size
T1 → T2 → T3, sequential (T3 needs both). T1 and T2 touch disjoint files. Expected size is about 120 lines of code plus about 400 lines of tests, within `audit_rule`'s batch guidance.

## 5. Out of scope / residuals (logged, not built)
- **Strings inside untyped dicts.** A string such as `"NaN"` inside an untyped dict is not rejected by the guard, because the guard cannot know a string is meant as a number, and rejecting the text "NaN"/"inf" anywhere would break free text and tickers. The consumers that coerce such values to float are not all inventoried. Those seen already check finiteness: `services/config_loader.py:402/492/509` (`math.isfinite` after `float()`) and `auto_trade_booking.py:162`. A follow-up item can type these dicts.
- **Rows already persisted with a non-finite value** (portfolio, journal, drawings, schedules) are not migrated. The reads stay as today, except the schedule list skip in T2(b).
- **Response serialisation** of non-finite internal values is unchanged (pydantic writes `null`).
- **Bounds** (e.g. negative prices) are not part of this phase: finite-only.

## 6. Acceptance (item #164)
- The §1 inventory and these outcomes are recorded on #164.
- T1–T3 green; backend full `pytest` on Python 3.11 green, apart from failures that pre-exist on main (#129-class commission fixture, provider-reaching `test_shortlist.py` tests in a sandbox), compared against a main run in the same container.
- Plan audit clean, then code audit clean on `origin/main..board/numeric-api-inputs-54c0ddc4` (`audit_rule`, cap 3 per stage).
