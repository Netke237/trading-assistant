# Heston Delta-Band Filter + Honest Pricing-Method Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Options A and G from `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md` — (A) filter `heston_chain` to a delta band derived from this request's own contract-selection settings before calibration, so far-from-the-money strikes (which are never selectable as the scored contract anyway) stop dominating the grid-search cost, and (G) stop mislabeling a crude IV-seed fallback calibration as `"Heston repriced"` downstream. Also record, in the investigation doc, that Option B (the "Little Heston Trap" characteristic-function reformulation) was empirically tested during this plan's own preparation and found to be a **no-op** for this codebase's actual (reduced-grid) parameter ranges — so it is not implemented — and commit a permanent regression test that will catch it if that ever stops being true.

**Architecture:** A and G are localized changes inside `_process_symbol`'s Heston calibration block in `backend/app/routers/scan.py` (lines ~659-699) — no changes to `heston_cache.py`, `reward_risk.py`, or any schema. G changes what value scan.py *keeps* after calibration finishes (only genuine `heston_grid` results are kept; `bs_fallback` results are treated exactly like "calibration failed," i.e. `heston_params` stays `None`, which the rest of the pipeline already handles correctly via the existing delta-approximation fallback). A changes what scan.py feeds *into* calibration.

**Revision history (two rounds of adversarial audit, both addressed below):**

- **Round 1** caught that filtering by a fixed strike/price *moneyness ratio* (0.7x-1.3x, the investigation doc's own suggested proxy) is unsafe: the real delta-selectable moneyness range shifts substantially with volatility and time-to-expiry — e.g. at 45% implied vol and 325 DTE (this investigation's own AMD scenario), the true 0.20-0.85 delta band already spans roughly **0.74x-1.64x** moneyness, well past a 0.7x-1.3x cutoff; at 60-80% vol it extends past 2x-3x. **Fix:** filter using each contract's own broker-reported `delta` field instead of a moneyness proxy — it is already present on every chain entry returned by `fetch_option_chain_async` (`backend/app/data/market.py:1210,1222` — sourced from the broker's own greeks, not estimated), so this requires no new computation, and it is the actual selection criterion, not an approximation of it.
- **Round 2** caught that a *fixed* delta band (the round-1 fix used a hardcoded `(0.05, 0.95)` constant) reproduces the exact same class of bug one layer down: `contract_rules.yaml`'s `min_delta`/`max_delta` are not fixed — they are live, per-request overrides a user can set anywhere in `[0, 1]` via the Execution Parameters panel (`frontend/app/(frame)/screener/step-3-direction/page.tsx:259,267`, "Max delta" / "Min delta (far OTM)", both `min: 0, max: 1`). A user who sets `max_delta` to, say, `0.97` could have a genuinely selectable contract whose delta falls outside a hardcoded `(0.05, 0.95)` calibration band, silently starving that contract's own Heston fit of its own strike's market data. **Fix:** derive the calibration band from *this request's own* `contract_overrides["min_delta"]`/`["max_delta"]` (the exact same dict `validate_contract` uses for real contract selection, confirmed via `backend/app/scoring/contract_validator.py:83,85,231,232`) plus a small numerical safety margin, instead of a fixed constant — so the calibration input band always tracks whatever selection band is actually in effect for this request, by construction, regardless of what the user configures.
- **Round 3** caught that round 2's *fallback* defaults (used only when a request has no explicit `min_delta`/`max_delta` override, e.g. `contract_overrides.get("min_delta", 0.20)`) hardcoded today's `contract_rules.yaml` values (`0.20`/`0.85`) as literals in `scan.py` — reintroducing the same "value can silently drift from the live config" problem one layer further down. If `contract_rules.yaml`'s `hard_reject.min_delta`/`max_delta` is ever retuned without a matching hand-edit to this literal, an un-overridden scan's calibration band would silently keep using the stale default while real contract selection already enforces the new one — and this fallback path is common, not a rare corner case (the scheduled-scan path replays the most recent manual request's overrides, and the frontend's override dict starts empty and only gains `min_delta`/`max_delta` keys if a user explicitly edits those specific sliders). **Fix:** read the fallback defaults from `contract_rules.yaml` at the source, instead of hardcoding literals.
- **Round 4** caught that round 3's fix, while functionally correct, reached past this codebase's own established pattern for "expose one `contract_rules.yaml` value to other modules": `contract_validator.py` already has `dte_holding_multiplier()`, a small public accessor built for exactly this purpose, but round 3's fix instead imported `contract_validator`'s private (leading-underscore) `_load_config()` directly into `scan.py` and indexed into its raw dict shape. That works, but it couples `scan.py` to `contract_validator.py`'s internal dict structure instead of a narrow, purpose-built contract, and it's inconsistent with the very accessor pattern sitting one line above the new import. Round 4 also caught two inaccurate justification claims (not code bugs, but incorrect supporting text): the "every scheduled scan" claim overstated what was actually verified about `scan_scheduler.py`, and a citation to `market.py:1319` as evidence of an "opposite convention" function was factually wrong (that line's `None` sentinel is specific to a stock-position branch, not option greeks, and the function's actual option-quote path shares the same `0.0` convention already cited elsewhere). **Fix:** add a new public `hard_reject_delta_band()` accessor to `contract_validator.py`, mirroring `dte_holding_multiplier()` exactly, and have `scan.py` import that instead of the private loader; soften the scheduled-scan claim to what was actually confirmed; remove the incorrect `:1319` citation entirely (the core claim — `fetch_option_chain_async` defaults delta to `0.0` — stands on its own without it).

**Why Option B is not part of this plan:** See the addendum appended to the investigation doc in Task 4 below, backed by a permanent regression test added in Task 3. Summary: the Little Heston Trap only causes a problem when a specific term (`|g|`) in the pricer's characteristic function exceeds 1, which flips the numerically fragile branch of a complex logarithm. `|g|` depends only on `kappa`, `sigma_v`, `rho`, and the integration variable `phi` — **not** on `theta` or time-to-expiry `T` (confirmed directly from `_heston_char_fn`'s structure: `theta` and `T` first enter via the `a`/`exp_dT`/`C`/`D` terms, all computed *after* `d` and `g`). A scan across every `(kappa, sigma_v, rho)` combination this codebase's reduced calibration grid actually uses found `|g|` peaks at ~0.996 — close to, but never crossing, the trap threshold of 1.0. Directly reimplementing the literature's branch-selection fix and running it against the investigation's own pathological AMD fixture (deep-ITM K=25, worst grid combo, T=325 days) produced bit-identical prices and the identical 2 integration warnings, before and after. The fix would change nothing for this codebase today — but because the margin is only ~0.4%, Task 3 commits a permanent test that fails loudly if a future change to the calibration grid ever pushes `|g|` past 1, rather than leaving this as a one-off, unreproducible claim.

**Tech Stack:** Python 3, pytest, unittest.mock. No new dependencies. Touches `backend/app/routers/scan.py`, `backend/tests/test_scan_endpoint.py`, a new `backend/tests/test_heston_char_fn.py`, and `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md`.

**Context:** Third implementation round on the Heston pricing feature (`docs/superpowers/plans/2026-07-25-heston-pricing-in-trade-plan.md`, `docs/superpowers/plans/2026-07-26-heston-ladder-floor-fix.md`, commit `4f3e835`'s concurrency fix). This plan implements exactly the two items from `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md`'s remediation-options list that the user selected (A and G), and closes out the third (B) with a documented, evidence-based, test-backed "ruled out."

---

### Task 1: Stop mislabeling a crude fallback calibration as "Heston repriced" (Option G)

**Files:**
- Modify: `backend/app/routers/scan.py:691-696`
- Test: `backend/tests/test_scan_endpoint.py` (add a new test near the existing Heston wiring tests, after `test_process_symbol_falls_back_when_calibrate_heston_raises` at line ~445)

Per the investigation doc's finding #5: `calibrate_cached()` (`backend/app/models/heston_cache.py`) can return a `CalibrationResult` with `method="bs_fallback"` — a crude, single-point IV-seed guess used when its own inner 1.0s timeout fires — instead of `method="heston_grid"`, a genuine 16-combo grid fit. `scan.py:694` currently discards `.method` and keeps only `.params`, so both cases produce a non-`None` `HestonParams` that `reward_risk.py` labels `"Heston repriced"` with no way to tell them apart. The fix: only keep `.params` when `.method == "heston_grid"`; otherwise treat it exactly like a calibration failure (`heston_params` stays `None`), which already correctly falls through to the delta-approximation labeling everywhere downstream — no changes needed outside `scan.py`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_scan_endpoint.py`, add this test directly after `test_process_symbol_falls_back_when_calibrate_heston_raises` (which ends at line 445). Note the test name deliberately contains "heston" (unlike a plain description) so it is picked up by later `-k heston` regression sweeps in this plan:

```python
@pytest.mark.asyncio
async def test_process_symbol_discards_bs_fallback_heston_calibration():
    """Option G (docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md,
    finding #5): a CalibrationResult with method='bs_fallback' is a crude
    single-point IV-seed guess, not a genuine grid fit -- scan.py must NOT
    pass its .params through to build_trade_plan, since reward_risk.py has no
    way to tell a crude guess apart from a real fit once it receives non-None
    HestonParams (both get labelled 'Heston repriced'). heston_params must
    stay None, exactly as if calibration had failed outright, so the existing
    delta-approximation fallback path is used and labelled honestly."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=float("inf"), method="bs_fallback")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    assert mock_build_plan.call_args.kwargs["heston_params"] is None, (
        "a bs_fallback CalibrationResult must not reach build_trade_plan as "
        "heston_params -- it would be indistinguishable from a genuine grid "
        "fit and mislabelled 'Heston repriced' downstream"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py::test_process_symbol_discards_bs_fallback_heston_calibration -v` (from `backend/`)

Expected: FAIL — `mock_build_plan.call_args.kwargs["heston_params"]` is currently `fake_params` (not `None`), because current code at line 694 extracts `.params` unconditionally.

- [ ] **Step 3: Implement the fix**

In `backend/app/routers/scan.py`, replace lines 691-696:

```python
            if calibration_task in _done:
                # .result() re-raises if the (in-time) calibration failed —
                # caught below, falling back to delta approximation.
                heston_params = calibration_task.result().params
            # else: still running past the ceiling — move on with
            # heston_params=None; the task finishes in the background.
```

with:

```python
            if calibration_task in _done:
                # .result() re-raises if the (in-time) calibration failed —
                # caught below, falling back to delta approximation. Only a
                # genuine grid-search fit ("heston_grid") is honest to label
                # "Heston repriced" downstream. A crude single-point IV-seed
                # guess ("bs_fallback" — calibrate_cached's own inner 1.0s
                # timeout fired before the grid search finished, see
                # docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md
                # finding #5) is discarded here so this symbol falls back to
                # the same delta-approximation path as a genuine calibration
                # failure, instead of silently displaying the crude guess
                # mislabelled as a real Heston fit.
                _calibration_result = calibration_task.result()
                if _calibration_result.method == "heston_grid":
                    heston_params = _calibration_result.params
            # else: still running past the ceiling — move on with
            # heston_params=None; the task finishes in the background.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py::test_process_symbol_discards_bs_fallback_heston_calibration -v` (from `backend/`)

Expected: PASS

- [ ] **Step 5: Run the full Heston test block to confirm no regression**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py -v -k heston` (from `backend/`)

Expected: all PASS, including every pre-existing test that uses `method="heston_grid"` (unaffected by this change, since the new `if` branch is a no-op for that case).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_scan_endpoint.py
git commit -m "fix(scan): stop labeling crude Heston fallback calibration as a real fit"
```

---

### Task 2: Filter `heston_chain` to a request-derived delta band before calibration (Option A)

**Files:**
- Modify: `backend/app/scoring/contract_validator.py` (add a new public `hard_reject_delta_band()` accessor)
- Modify: `backend/app/routers/scan.py:276` (add a new safety-margin constant near the other `_HESTON_*` constants) and `backend/app/routers/scan.py:663-672` (the `heston_chain` list comprehension)
- Test: `backend/tests/test_contract_validator.py` (one small direct test for the new accessor) and `backend/tests/test_scan_endpoint.py` (add a new mock chain fixture and two new tests near the existing Heston wiring tests)

Per the investigation doc's findings #4 and #5: calibration cost rises sharply for strikes far from at-the-money (a $25 strike against a $521.95 underlying cost 18x the ATM baseline, and was one of the two strikes that produced explicit non-convergence warnings), and those strikes are never selectable as the actual scored contract anyway (`contract_rules.yaml`'s *default* hard-reject delta band is 0.20-0.85). As explained in the revision history above, neither a fixed moneyness ratio nor a fixed delta band is safe: `min_delta`/`max_delta` are live, per-request overrides. So this plan derives the calibration band directly from **this request's own** `contract_overrides["min_delta"]`/`["max_delta"]` — the exact dict `validate_contract` uses for real contract selection, already in scope at this point in `_process_symbol` (built at line 623, well before the calibration block) — widened by a small, fixed numerical safety margin.

`market.py` (`backend/app/data/market.py:1210,1222`, the function `fetch_option_chain_async` actually calls) defaults `delta` to `0.0` (not `None`) whenever the broker doesn't return greeks for a quote — this is indistinguishable from a genuinely near-zero-delta strike using the field alone. The filter therefore fails **open** on `delta == 0`: such a strike is kept in, since wrongly excluding a live, valid contract because its greeks happened to be temporarily unavailable is worse than losing this filter's speed benefit for that one strike.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_scan_endpoint.py`, add this new mock-chain fixture near `_MOCK_CHAIN` (after its definition, around line 111). With the default `contract_overrides` (no explicit override passed by these tests — `min_delta=0.20`, `max_delta=0.85`, per `contract_rules.yaml`) and a `0.05` safety margin, the effective calibration band is `(0.15, 0.90)`:

```python
_WIDE_MOCK_CHAIN = [
    {"strike": 25,  "expiry": "2026-06-20", "price": 460.0, "spread": 0.20,
     "delta": 0.99, "theta": -0.01, "ivRank": 40, "dte": 30, "right": "C", "volume": 500},
    {"strike": 100, "expiry": "2026-06-20", "price": 86.0,  "spread": 0.20,
     "delta": 0.90, "theta": -0.02, "ivRank": 45, "dte": 30, "right": "C", "volume": 450},
    {"strike": 130, "expiry": "2026-06-20", "price": 12.0,  "spread": 0.20,
     "delta": 0.80, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
    {"strike": 190, "expiry": "2026-06-20", "price": 2.50,  "spread": 0.20,
     "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
    {"strike": 280, "expiry": "2026-06-20", "price": 0.55,  "spread": 0.20,
     "delta": 0.15, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 350},
    {"strike": 300, "expiry": "2026-06-20", "price": 0.30,  "spread": 0.20,
     "delta": 0.02, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
    {"strike": 340, "expiry": "2026-06-20", "price": 0.10,  "spread": 0.10,
     "delta": 0,    "theta": 0.0,   "ivRank": 0,  "dte": 30, "right": "C", "volume": 10},
]
```

Deltas: 0.99 (above the 0.90 ceiling, excluded), 0.90 (exactly the ceiling, inside), 0.80 and 0.45 (comfortably inside), 0.15 (exactly the floor, inside), 0.02 (below the floor, excluded), and `0` (missing/unavailable greeks — fails open, kept in regardless of band).

Add these two tests directly after `test_process_symbol_discards_bs_fallback_heston_calibration` (added in Task 1). Note the second test's name also contains "heston" for the same `-k heston` sweep reason as Task 1:

```python
@pytest.mark.asyncio
async def test_process_symbol_filters_heston_chain_to_delta_band():
    """Option A (docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md,
    findings #4/#5): strikes far from at-the-money dominate calibration cost.
    Filter heston_chain using each contract's own broker-reported delta
    (already present on every chain entry from fetch_option_chain_async,
    app/data/market.py:1210,1222) rather than a raw strike/price moneyness
    ratio -- a fixed moneyness band was found, during this plan's own
    preparation, to badly mismatch the REAL delta-selectable strike range at
    long DTE with realistic volatility. Using the real delta avoids that
    failure mode entirely. The band itself is DERIVED from this request's own
    contract_overrides (min_delta=0.20, max_delta=0.85 defaults here, +/-0.05
    safety margin -> effective band 0.15-0.90) rather than a hardcoded
    constant -- a hardcoded delta band was ALSO found, in a second audit
    round, to reproduce the same fixed-vs-configurable mismatch one layer
    down, since contract_rules.yaml's min_delta/max_delta are live per-request
    overrides a user can set anywhere in [0,1] via the Execution Parameters
    panel. A strike with delta==0 (greeks missing/unavailable -- market.py
    defaults to 0.0 rather than None) fails OPEN -- kept in, since a missing
    greek can't be used to judge selectability."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_WIDE_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_strikes = sorted(c["strike"] for c in called_chain)
    assert called_strikes == [100.0, 130.0, 190.0, 280.0, 340.0], (
        f"expected the five in-band-or-unknown-delta strikes, got {called_strikes}"
    )


@pytest.mark.asyncio
async def test_process_symbol_filtered_thin_heston_chain_falls_back_honestly():
    """Regression guard for the Task 1 + Task 2 interaction: if the delta-band
    filter (Task 2) narrows a real chain down to fewer than 3 strikes,
    calibrate_cached's own existing len(chain)<3 path
    (app/models/heston_cache.py:86-92) returns method='bs_fallback' before
    ever running the grid search. Combined with Task 1's fix, that fallback
    must be discarded (heston_params stays None), not silently displayed as
    'Heston repriced'. Uses the REAL (unmocked) calibrate_heston ->
    calibrate_cached path end-to-end, overriding the autouse
    _default_fast_heston_calibration fixture (conftest.py) for this one test
    only, so this interaction is actually exercised rather than assumed. The
    len(chain)<3 path returns before any scipy quad() call runs, so this test
    stays fast despite using the real calibration function."""
    from app.routers.scan import _process_symbol
    from app.models.heston import calibrate_heston as _real_calibrate_heston

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    # With the default (0.15, 0.90) effective band, only 2 of these 4 strikes
    # clear it (0.80, 0.45); the filtered heston_chain therefore has length
    # 2, below calibrate_cached's len(chain)<3 floor.
    thin_after_filter_chain = [
        {"strike": 25,  "expiry": "2026-06-20", "price": 460.0, "spread": 0.20,
         "delta": 0.99, "theta": -0.01, "ivRank": 40, "dte": 30, "right": "C", "volume": 500},
        {"strike": 130, "expiry": "2026-06-20", "price": 12.0, "spread": 0.20,
         "delta": 0.80, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
        {"strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
         "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
        {"strike": 300, "expiry": "2026-06-20", "price": 0.30, "spread": 0.20,
         "delta": 0.02, "theta": -0.01, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
    ]

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=thin_after_filter_chain)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        # Override the autouse default mock with the REAL function for this
        # one test, so calibrate_cached's real len(chain)<3 path actually runs.
        patch("app.routers.scan.calibrate_heston", side_effect=_real_calibrate_heston),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert mock_build_plan.call_args.kwargs["heston_params"] is None, (
        "a filtered chain of only 2 strikes should hit calibrate_cached's "
        "real len(chain)<3 bs_fallback path, which Task 1's fix must then "
        "discard rather than pass through as heston_params"
    )
```

- [ ] **Step 2: Run both tests to verify they fail**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py::test_process_symbol_filters_heston_chain_to_delta_band tests/test_scan_endpoint.py::test_process_symbol_filtered_thin_heston_chain_falls_back_honestly -v` (from `backend/`)

Expected: BOTH FAIL. The first fails because `called_strikes` is currently `[25.0, 100.0, 130.0, 190.0, 280.0, 300.0, 340.0]` (all seven — no delta filter yet). The second fails because, without Task 2's filter, all 4 strikes reach `calibrate_cached` (length 4, not below the `<3` floor), so the real grid search runs and (given well-behaved default-ish params on a small clean chain) returns a genuine `heston_grid` fit — `heston_params` comes back non-`None`, not `None` as asserted. (If it happens to also return `None` for a different reason on your machine, note that discrepancy before proceeding — the important confirmation is that Step 5 below passes for the *intended* reason.)

- [ ] **Step 3: Add a public `hard_reject_delta_band()` accessor to `contract_validator.py`**

`contract_validator.py` already has a small, purpose-built public accessor for exposing one `contract_rules.yaml` value to other modules: `dte_holding_multiplier()` (lines 49-51). An earlier draft of this plan hardcoded `0.20`/`0.85` literals as fallback defaults directly in `scan.py` (a third adversarial audit round caught that this would silently drift from `contract_rules.yaml` if its `hard_reject.min_delta`/`max_delta` were ever retuned without a matching hand-edit); a later draft fixed the drift risk by importing `contract_validator.py`'s *private* `_load_config()` directly, but a fourth audit round caught that this reaches past the codebase's own established pattern (sitting one line away) and couples `scan.py` to `contract_validator.py`'s internal dict shape. This step instead adds a proper public accessor, matching `dte_holding_multiplier()`'s style exactly.

In `backend/app/scoring/contract_validator.py`, directly after `dte_holding_multiplier()` (lines 49-51):

```python
def dte_holding_multiplier() -> float:
    """DTE-to-holding-period ratio from contract_rules.yaml."""
    return float(_load_config().get("dte_holding_multiplier", 2.0))
```

add:

```python


def hard_reject_delta_band() -> tuple[float, float]:
    """(min_delta, max_delta) from contract_rules.yaml's hard_reject block --
    the same values _hard_reject_reasons() uses for real contract selection."""
    hr = _load_config()["hard_reject"]
    return float(hr["min_delta"]), float(hr["max_delta"])
```

Add a small direct test in `backend/tests/test_contract_validator.py` (matching the existing convention for `dte_holding_multiplier()` in `backend/tests/test_horizon_dte.py:5`):

```python
def test_hard_reject_delta_band_reads_from_config():
    from app.scoring.contract_validator import hard_reject_delta_band
    assert hard_reject_delta_band() == (0.20, 0.85)
```

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_contract_validator.py::test_hard_reject_delta_band_reads_from_config -v` (from `backend/`) — expected PASS immediately (this is a new, additive function; nothing to fail against first).

- [ ] **Step 4: Import the new accessor in `scan.py` and add the `_HESTON_DELTA_SAFETY_MARGIN` constant**

In `backend/app/routers/scan.py`, directly after the existing line 59:

```python
from app.scoring.contract_validator import dte_holding_multiplier
```

add:

```python
from app.scoring.contract_validator import hard_reject_delta_band
```

Then, directly after the `_HESTON_CALIBRATION_TIMEOUT_S = 2.0` line (line 276), add:

```python

# Investigation findings #4/#5 (docs/superpowers/plans/
# 2026-07-27-heston-long-dte-slowness-investigation.md): calibration cost
# rises sharply for strikes far from at-the-money, and those strikes are
# never selectable as the scored contract anyway. Two earlier approaches were
# tried and rejected during this plan's own adversarial audit: (1) a FIXED
# MONEYNESS RATIO -- the real delta-selectable moneyness range shifts
# substantially with volatility/time-to-expiry, so a static ratio either
# wrongly excludes real candidates at long DTE or is too wide to filter
# anything useful; (2) a FIXED DELTA BAND -- contract_rules.yaml's
# min_delta/max_delta are live, per-request overrides a user can set
# anywhere in [0,1] via the Execution Parameters panel, so a hardcoded delta
# band reproduces the same fixed-vs-configurable mismatch one layer down.
# This margin is instead added on both sides of THIS REQUEST's actual
# min_delta/max_delta (contract_overrides, the same dict validate_contract
# uses for real contract selection -- and, when no override is present,
# whatever contract_rules.yaml's hard_reject band currently is, read live via
# hard_reject_delta_band() rather than a hardcoded fallback) at the call
# site below, so the calibration band always tracks whatever selection band
# is actually in effect, by construction.
_HESTON_DELTA_SAFETY_MARGIN = 0.05
```

- [ ] **Step 5: Apply the filter to `heston_chain`**

In `backend/app/routers/scan.py`, replace the `heston_chain` list comprehension (lines 663-672):

```python
            heston_chain = [
                {
                    "strike": float(c.get("strike", 0)),
                    "expiry_years": c.get("dte", 30) / 365.0,
                    "mid_price": float(c.get("price", 0)),
                    "is_call": c.get("right", "C") == "C",
                }
                for c in chain
                if float(c.get("price", 0)) > 0
            ]
```

with:

```python
            _default_min_delta, _default_max_delta = hard_reject_delta_band()
            _cfg_min_delta = float(contract_overrides.get("min_delta", _default_min_delta))
            _cfg_max_delta = float(contract_overrides.get("max_delta", _default_max_delta))
            _calib_delta_lo = max(0.0, _cfg_min_delta - _HESTON_DELTA_SAFETY_MARGIN)
            _calib_delta_hi = min(1.0, _cfg_max_delta + _HESTON_DELTA_SAFETY_MARGIN)

            def _heston_delta_ok(entry: dict) -> bool:
                d = abs(float(entry.get("delta") or 0))
                if d == 0.0:
                    # Greeks missing/unavailable for this quote (market.py
                    # defaults to 0.0, not None) -- indistinguishable from a
                    # genuinely near-zero-delta strike using this field
                    # alone. Fail OPEN: keep it in rather than risk wrongly
                    # excluding a live, valid contract.
                    return True
                return _calib_delta_lo <= d <= _calib_delta_hi

            heston_chain = [
                {
                    "strike": float(c.get("strike", 0)),
                    "expiry_years": c.get("dte", 30) / 365.0,
                    "mid_price": float(c.get("price", 0)),
                    "is_call": c.get("right", "C") == "C",
                }
                for c in chain
                if float(c.get("price", 0)) > 0 and _heston_delta_ok(c)
            ]
```

`contract_overrides` is already defined and in scope at this point in `_process_symbol` (built at line 623, before this block). `hard_reject_delta_band()` currently returns `(0.20, 0.85)` (verified against `backend/config/contract_rules.yaml`), matching the values used throughout this task's tests below — but as a live config read, not a hardcoded literal, so it tracks the YAML if it ever changes.

- [ ] **Step 6: Run both tests to verify they pass**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py::test_process_symbol_filters_heston_chain_to_delta_band tests/test_scan_endpoint.py::test_process_symbol_filtered_thin_heston_chain_falls_back_honestly -v` (from `backend/`)

Expected: both PASS.

- [ ] **Step 7: Run the full Heston test block to confirm no regression**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_scan_endpoint.py -v -k heston` (from `backend/`)

Expected: all PASS. In particular, `test_process_symbol_calls_calibrate_heston_with_the_chain` (single strike 190, delta 0.45) and `test_process_symbol_reuses_heston_params_for_alt_contracts` (strikes 190/195/200, deltas 0.45/0.35/0.28) are all comfortably inside the default (0.15, 0.90) band and must be unaffected.

- [ ] **Step 8: Commit**

```bash
git add backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py backend/app/routers/scan.py backend/tests/test_scan_endpoint.py
git commit -m "perf(scan): filter Heston calibration input to a request-derived delta band"
```

---

### Task 3: Commit a permanent regression test for the Option B "no-op" finding

**Files:**
- Create: `backend/tests/test_heston_char_fn.py`

Per the round-1 adversarial audit finding: the empirical "|g| never exceeds 1" claim behind ruling out Option B was based on a standalone script that was never committed, making it unreproducible and unverifiable by a future session. This task converts that verification into a real, committed pytest test. Per the round-2 adversarial audit finding: `|g|` is mathematically independent of `theta` and `T` (time-to-expiry) — confirmed directly from `_heston_char_fn`'s structure, where `theta` only enters via `a = kappa * theta` (used in the `C` term) and `T` only enters via `exp_dT = exp(-d*T)` (used in `C` and `D`), both computed *after* `d` and `g`. The test below therefore intentionally does not loop over `theta` or `T` — an earlier draft did, and that looping was a no-op that gave a false impression of broader coverage than the test actually had.

- [ ] **Step 1: Write the test**

Create `backend/tests/test_heston_char_fn.py`:

```python
"""Regression guard for the 'Little Heston Trap' branch-cut condition
(Albrecher, Mayer, Schoutens & Tistaert, 2007) -- see the addendum in
docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md
for the full writeup and the decision this test backs (Option B was found to
be a no-op for this codebase and was not implemented)."""
import cmath


def _max_abs_g(kappa, sigma_v, rho, j, n=400, phi_max=500):
    """Mirrors backend/app/models/heston.py's _heston_char_fn d/g formula
    (lines 45-47) for the SAME (phi - 1j*j) argument heston_price's own P1
    (j=1) and P2 (j=0) integrands evaluate it at (see heston.py's
    _integrand, lines 87-96). Deliberately duplicated rather than imported,
    since _heston_char_fn is a private module internal that returns the full
    characteristic function value, not d/g individually -- if that formula's
    d/g computation ever changes, this test's own copy must be updated to
    match, or it silently stops verifying the real code.

    Deliberately takes NO theta or T (time-to-expiry) parameter: |g| depends
    only on kappa, sigma_v, rho, and phi. theta only enters _heston_char_fn's
    full formula via `a = kappa*theta` (used in the C term); T only enters
    via `exp_dT = exp(-d*T)` (used in C and D) -- both computed AFTER d and g.
    Looping over theta/T here would be redundant, not more thorough (an
    earlier draft did loop over them and it never changed the result)."""
    worst = 0.0
    for k in range(1, n):
        phi_real = phi_max * k / n
        phi = complex(phi_real, 0) - complex(0, j)
        i = complex(0, 1)
        d = cmath.sqrt((rho * sigma_v * phi * i - kappa) ** 2
                       + sigma_v ** 2 * (phi * i + phi ** 2))
        g = (kappa - rho * sigma_v * phi * i - d) / (kappa - rho * sigma_v * phi * i + d)
        worst = max(worst, abs(g))
    return worst


def test_little_heston_trap_branch_never_triggers_for_reduced_grid():
    """docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md's
    Addendum (2026-07-28): the Little Heston Trap only causes a numerical
    problem when |g| exceeds 1, which flips cmath.log's branch continuity in
    _heston_char_fn. Option B (a conditional branch-selection fix) was found
    to be a no-op because |g| never exceeds 1 anywhere in heston_cache.py's
    REDUCED grid (HESTON_FULL_CALIBRATION unset -- the grid this app runs by
    default): kappa in {0.5, 3.0}, sigma_v in {0.2, 0.6}, rho in
    {-0.8, -0.2} (theta is excluded from this grid -- see _max_abs_g's
    docstring for why it's irrelevant to |g|). The observed peak is
    ~0.996 -- close to, but never crossing, the 1.0 trap threshold.

    This test locks that finding in as a regression guard, NOT a proof for
    all possible parameters: if this ever fails, |g| has started exceeding 1
    for a real combination this app calibrates with, meaning Option B may
    actually be needed now -- revisit the investigation doc.

    NOTE: HESTON_FULL_CALIBRATION's full grid (kappa/sigma_v/rho each with a
    third, interior value) was NOT verified by this test or the addendum it
    backs -- that flag is off by default in this codebase, and this test
    intentionally only covers the grid actually used without it."""
    grid_kappa = [0.5, 3.0]
    grid_sigma_v = [0.2, 0.6]
    grid_rho = [-0.8, -0.2]

    worst_overall = 0.0
    for kappa in grid_kappa:
        for sigma_v in grid_sigma_v:
            for rho in grid_rho:
                for j in (0, 1):
                    worst_overall = max(worst_overall, _max_abs_g(kappa, sigma_v, rho, j))

    assert worst_overall < 1.0, (
        f"|g| reached {worst_overall} >= 1 for a combination in this app's "
        "reduced calibration grid -- the Little Heston Trap branch-cut "
        "condition may now be occurring; Option B "
        "(docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md) "
        "should be revisited"
    )
```

- [ ] **Step 2: Run it and confirm the observed peak**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_heston_char_fn.py -v` (from `backend/`)

Expected: PASS (verified while writing this plan: `worst_overall` computes to `0.9961874296821448` with this exact grid/resolution — comfortably under 1.0, but only by about 0.4%, which is why this is a permanent regression test rather than a one-off comment). Confirm the test completes in well under a second (verified while writing this plan: ~0.01s) — it is pure Python complex arithmetic, no scipy calls.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_heston_char_fn.py
git commit -m "test(heston): add permanent regression guard for the Little Heston Trap no-op finding"
```

---

### Task 4: Record Option B as empirically ruled out

**Files:**
- Modify: `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md` (two small inline edits, plus a new section appended at the end)

The investigation doc lists Option B ("Reformulate `_heston_char_fn` using the Little Trap-safe branch") as unverified in two places — the "Root cause" section and the "What this investigation did not do" list. This plan's preparation empirically tested it and found it to be a no-op for this codebase's reduced calibration grid, now backed by Task 3's permanent test. Both existing "unverified" mentions must get a short forward-pointer to the addendum (otherwise a reader hits a flat contradiction: the same document says "not confirmed" in one place and "confirmed and ruled out" in another, with no link between them), and the addendum itself must be appended.

- [ ] **Step 1: Add a forward-pointer to the "Root cause" section**

In `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md`, find this exact text in the "Root cause" section (note the line break falls right after "This" — copy the block below exactly, including that line break, since an exact-match edit will fail otherwise; a fifth adversarial audit round on this plan caught an earlier draft of this exact step quoting the sentence with different line-wrapping than the real file, which would have caused the edit to fail):

```
This
investigation did not implement or numerically verify the trap
reformulation against reference prices — it is cited as the standard,
literature-documented explanation consistent with every symptom observed
(slow convergence, occasional explicit non-convergence warnings, worse at
long T and extreme moneyness, absent at short T and near-ATM), not confirmed
by directly patching and re-testing.
```

Replace it with:

```
This
investigation did not implement or numerically verify the trap
reformulation against reference prices — it is cited as the standard,
literature-documented explanation consistent with every symptom observed
(slow convergence, occasional explicit non-convergence warnings, worse at
long T and extreme moneyness, absent at short T and near-ATM), not confirmed
by directly patching and re-testing. (Update 2026-07-28: this WAS
subsequently implemented and tested — see the Addendum at the end of this
document. Result: it is a no-op for this codebase's actual calibration
grid.)
```

- [ ] **Step 2: Add a forward-pointer to the "What this investigation did not do" list**

In the same document, find this bullet in "What this investigation did not do":

```
- Did not implement or test the "Little Trap" reformulation (Option B) — its
  applicability is asserted from the literature and consistency with observed
  symptoms, not confirmed by direct experiment.
```

Replace it with:

```
- Did not implement or test the "Little Trap" reformulation (Option B) — its
  applicability is asserted from the literature and consistency with observed
  symptoms, not confirmed by direct experiment. (Update 2026-07-28: this WAS
  subsequently tested — see the Addendum at the end of this document.)
```

- [ ] **Step 3: Append the addendum**

Append to the end of `docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md`:

```markdown

## Addendum (2026-07-28): Option B tested and ruled out as a no-op (reduced grid only)

During preparation of `docs/superpowers/plans/2026-07-28-heston-moneyness-filter-and-honest-labeling.md`
(which implements Options A and G above), Option B was directly tested
before being scoped into that plan — and found to change nothing for this
codebase's default (reduced) calibration grid. This finding is now backed by
a permanent, committed regression test: `backend/tests/test_heston_char_fn.py`.

**What was tested:** the Little Heston Trap (Albrecher, Mayer, Schoutens &
Tistaert, 2007) causes a problem specifically when `|g|` — a term inside
`_heston_char_fn` (`backend/app/models/heston.py:47`) — exceeds 1, which
flips `cmath.log`'s principal-branch continuity as the integration variable
sweeps through. The literature's fix is to conditionally pick whichever root
of the pricer's `d` term (a `cmath.sqrt(...)` result, which always has two
valid roots) keeps `|g| <= 1`.

`|g|` depends only on `kappa`, `sigma_v`, `rho`, and the integration variable
`phi` — **not** on `theta` or time-to-expiry `T` (confirmed directly from
`_heston_char_fn`'s structure: `theta` enters only via `a = kappa*theta`,
used in the `C` term; `T` enters only via `exp_dT = exp(-d*T)`, used in `C`
and `D` — both computed strictly after `d` and `g`). So the parameter space
actually relevant to this trap condition is just `(kappa, sigma_v, rho)` ×
`phi`, not the full 16-combo `(kappa, theta, sigma_v, rho)` grid.

That conditional branch-selection fix was implemented in a standalone script
(the exploratory version; the verification itself is now reproducible via
`backend/tests/test_heston_char_fn.py`) and run against every
`(kappa, sigma_v, rho)` combination this codebase's **reduced** calibration
grid actually uses (the default when `HESTON_FULL_CALIBRATION` is unset) —
`kappa` ∈ {0.5, 3.0}, `sigma_v` ∈ {0.2, 0.6}, `rho` ∈ {-0.8, -0.2}
(`backend/app/models/heston_cache.py`) — scanning `|g|` across the full
integration domain (`phi` ∈ [0, 500], both the real-`phi` and `phi - 1j`
argument forms `heston_price` actually evaluates). **`HESTON_FULL_CALIBRATION=1`'s
full 3×3×3×3×3 grid (interior values like `kappa=1.5`, `sigma_v=0.4`) was NOT
tested** — that flag is off by default in this codebase.

**Result:** `|g|` peaked at ~0.996 — close to, but never crossing, 1 — so the
branch-selection condition never fires for the reduced grid. Directly
confirmed against the investigation's own pathological fixture (AMD,
deep-ITM K=25, the worst grid combo from finding #3, T=325 days): the
reformulated pricer produced a bit-identical price and the identical 2
integration warnings as the current code, both before and after. The same
held for the DTE=185 ladder-artifact fixture from
`docs/superpowers/plans/2026-07-26-heston-ladder-floor-fix.md` (T1/T2/T3
identical to the last digit).

**Conclusion:** the branch-cut discontinuity this reformulation fixes does
not occur anywhere in this codebase's default parameter space, so
implementing it would not change the slowness, the integration warnings, or
the non-monotonic ladder artifact today. The residual slow-convergence
symptom (finding #4: cost rising sharply for strikes far from at-the-money)
is more consistent with a genuinely oscillatory integrand for those inputs —
closer to Option C's territory (a different integration scheme) than Option
B's. Because the observed `|g|` margin below the trap threshold is only
~0.4%, `backend/tests/test_heston_char_fn.py` is a permanent regression
guard, not a one-off check — if a future change widens the calibration grid
(e.g. adding a third `sigma_v` or `rho` value, or turning on
`HESTON_FULL_CALIBRATION` by default) pushes `|g|` past 1, that test fails
and Option B should be revisited then, with the full grid in scope.

Per the user's decision (2026-07-28), Option B is not implemented; the
residual slowness for symptoms not resolved by Options A/G is left as a
documented, known limitation (Option E) for this round. Options C, D, and F
remain unevaluated.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md
git commit -m "docs(heston): record Option B as empirically ruled out for the reduced grid"
```

---

### Task 5: Full backend suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest -q` (from `backend/`)

Expected: baseline before this plan was `1174 passed, 9 skipped, 1 xpassed, 0 failed` (confirmed by running it directly while writing this plan). This plan adds exactly 5 net-new tests: Task 1 (1), Task 2 (3 — the accessor unit test plus the two scan-level tests), Task 3 (1) — and modifies no other test's expected behavior. Expected result: **1179 passed, 9 skipped, 1 xpassed, 0 failed**. If the count differs, investigate before proceeding — do not adjust the expected count to match an unexplained result.

- [ ] **Step 2: No commit** (verification-only task — nothing to stage)

---

## Self-review notes (for the plan author, not the implementer)

- **Spec coverage:** Option G (honest labeling) — Task 1 ✓. Option A (request-derived delta-band filter) — Task 2 ✓. Option B (real fix) — empirically tested during plan preparation, confirmed to be a no-op for the reduced grid, not implemented per the user's explicit decision, backed by a permanent test (Task 3) and recorded in the investigation doc (Task 4) ✓. Full-suite green — Task 5 ✓.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or an exact command.
- **Type/naming consistency:** `_HESTON_DELTA_SAFETY_MARGIN`, `_cfg_min_delta`/`_cfg_max_delta`, `_calib_delta_lo`/`_calib_delta_hi`, and `_heston_delta_ok` are each defined once (Task 2 Step 3/4) and referenced identically at their one call site. `_calibration_result` is scoped to its immediate block, matching the surrounding code's leading-underscore convention.
- **Round-1 adversarial audit (2026-07-28):** an independent subagent found: (1) the original 0.7x-1.3x moneyness-ratio filter would wrongly exclude real, delta-selectable contracts at long DTE with realistic volatility — fixed by switching to a delta-based filter; (2) the Task 1 + Task 2 interaction (a filtered chain dropping below `calibrate_cached`'s 3-strike floor) was unanalyzed and untested — fixed by adding an interaction test; (3) the Option B addendum's conclusion overclaimed beyond the reduced grid actually tested — fixed by scoping every claim and explicitly flagging `HESTON_FULL_CALIBRATION` as untested; (4) the Option B verification was an uncommitted, unreproducible script — fixed by committing it as a permanent test; (5) a test fixture's boundary comment was numerically imprecise — moot after switching to delta-based filtering with exact boundary values; (6) a regression-sweep command wouldn't match a new test's name — fixed by renaming it. All six fixed, none deferred.
- **Round-2 adversarial audit (2026-07-28):** a second, independent subagent found: (1) the interaction test added in round 1 (`test_process_symbol_filtered_thin_heston_chain_falls_back_honestly`, the one test exercising the REAL calibration path) still didn't have "heston" in its name and would be silently skipped by the plan's own `-k heston` sweep — fixed by renaming it; (2) the round-1 fix's hardcoded `(0.05, 0.95)` delta band reproduces the exact fixed-vs-configurable bug round 1 caught for moneyness, one layer down: `contract_rules.yaml`'s `min_delta`/`max_delta` are live, user-configurable overrides (verified directly against `frontend/app/(frame)/screener/step-3-direction/page.tsx:259,267`, both sliders span `[0,1]`) — fixed by deriving the calibration band from this request's own `contract_overrides` instead of a fixed constant (Task 2, this revision), and updating the affected test's fixture values and expected band edges accordingly (0.90/0.15 instead of 0.95/0.05, matching the new default-derived band); (3) the addendum text contradicted the investigation doc's pre-existing "not confirmed by direct experiment" language elsewhere in the same document — fixed by adding two short forward-pointers (Task 4, Steps 1-2, new in this revision); (4) a self-review citation (`market.py:1319`) pointed to an unrelated function (`fetch_contract_quote_async`) with the opposite `None`-not-`0.0` default — fixed by correcting every citation to the actually-invoked function's real lines (`1210,1222`) and explicitly noting why `:1319` doesn't apply; (5) `test_heston_char_fn.py`'s `T`/`theta` loops were mathematically no-ops (`|g|` doesn't depend on either — confirmed by inspecting `_heston_char_fn`'s structure directly) despite the test's docstring implying they were meaningfully exercised — fixed by removing both loops from the test and its supporting `_max_abs_g` helper, and by removing the same false T-dependence framing from the addendum text (Task 3/4, this revision); re-verified the simplified 8-combo scan (down from the original 16, since `theta` no longer varies) still produces the identical `worst_overall = 0.9961874296821448`, confirming the removed loops never affected the result. (6) A minor, non-blocking suggestion (reuse `_augment()`'s BS-estimated delta instead of the raw broker delta for the zero-delta fallback case) was explicitly flagged by the auditor as "not a bug" — deliberately NOT implemented, to avoid reordering `heston_chain`'s construction relative to `_augment()` and adding coupling for a case (missing broker greeks) that Task 2's fail-open rule already handles safely. Five of six findings fixed; one explicitly deferred with reason given.
- **Round-3 adversarial audit (2026-07-28):** a third, independent subagent, reviewing the fully-merged round-1+round-2 revisions, found: (1) Task 4 Step 2's quoted "old" text for the investigation doc's "did not do" bullet did not byte-for-byte match the real file (it ended "...not confirmed by directly patching and re-testing" — actually the Root Cause section's wording — when the real bullet ends "...not confirmed by direct experiment") — fixed by re-quoting the actual current text, verified directly against the file; (2) round 2's own fix introduced a new instance of the same class of problem it was created to solve: `contract_overrides.get("min_delta", 0.20)` hardcoded today's `contract_rules.yaml` defaults as literals in `scan.py`, which would silently drift from the YAML if it's ever retuned — and this fallback is a live production path, not a rare corner case (`scan_scheduler.py`'s scheduled scans pass no overrides at all, so every scheduled scan hits it) — fixed by reading the fallback from `contract_validator._load_config()["hard_reject"]`, the same cached loader real contract selection already uses, instead of duplicating the literals (Task 2 Step 3/4, this revision). Both fixed, none deferred. The reviewer independently re-verified every other line-number citation, the delta-band arithmetic, the `len(chain)<3` short-circuit ordering, the `_max_abs_g` formula transcription, `widen_contract_overrides_for_dte`'s non-interference with delta keys, and `_augment()`'s non-mutating behavior, and found all of it accurate against the current repo state.
- **Round-4 adversarial audit (2026-07-28):** a fourth, independent subagent, reviewing the fully-merged round-1/2/3 revisions, confirmed every line-number citation, the delta-band arithmetic, both Task 4 doc-edit quote blocks, the `_max_abs_g` transcription, the mutation-safety of reading a cached config dict, and the test baseline (`1174 passed`) were all accurate — but found three problems in the justification/reasoning layer rather than the code changes: (1) round 3's fix imported `contract_validator.py`'s *private* `_load_config()` directly into `scan.py` rather than using this codebase's own established pattern for exposing one config value across modules (`dte_holding_multiplier()`, sitting one line above the new import) — fixed by adding a proper public `hard_reject_delta_band()` accessor instead (Task 2 Step 3, new in this revision), which also added one more test (the accessor's own direct unit test), bringing the total net-new test count from 4 to 5; (2) the claim "every scheduled scan hits this exact fallback" overstated what was actually verified about `scan_scheduler.py` — fixed by softening it to what was actually confirmed (the scheduled path replays the most recent request's overrides, which are empty unless a user explicitly touches those sliders); (3) a citation to `market.py:1319` as an "opposite convention" function was factually wrong (that `None` sentinel is specific to a stock-position branch, not option greeks) — fixed by removing the citation entirely, since the core claim about `fetch_option_chain_async`'s own `0.0` default stands without it. All three fixed, none deferred.
- **Round-5 adversarial audit (2026-07-28):** a fifth, independent subagent, using a byte-level substring check (extracting each Task 4 quote block from the plan and testing it against the real investigation doc programmatically, not by eye), found Task 4 Step 1's quoted "old" text did not actually match the real file: the real document wraps the line as "...struggles to resolve by subdivision). This\ninvestigation did not implement..." (the line break falls right after "This"), while the plan's quote started a fresh line at "This investigation did not implement..." with no embedded break there — an exact-match edit would have failed. This directly contradicted the Round-4 self-review's own claim that "both Task 4 doc-edit quote blocks... were accurate." Fixed by re-quoting the exact real text, byte-for-byte, with an explicit callout in the step's instructions about the line-break position so a future editor doesn't reflow it back to prose and reintroduce the same mismatch. Also found Task 1's "Files:" header cited `scan.py:691-694`, one line short of the `691-696` range Step 3 actually replaces (the trailing `# else:` comment) — fixed by correcting the header. Both fixed, none deferred. Confirms the value of re-verifying byte-level claims each round rather than trusting a prior round's "confirmed accurate" note — Task 4 Step 2's quote block, by contrast, was independently re-confirmed correct at the same byte level.
- **Round-6 adversarial audit (2026-07-28): CLEAN.** A sixth, independent subagent re-derived every check from rounds 1-5 from scratch (byte-level substring checks on both Task 4 quote blocks, direct reads of every cited line across `scan.py`/`contract_validator.py`/`heston.py`/`heston_cache.py`/`market.py`/the frontend, from-scratch delta-band arithmetic, an actual `pytest -q` run confirming the `1174` baseline still holds, and an actual execution of `_max_abs_g`'s grid scan reproducing `0.9961874296821448` bit-for-bit) and found no defect. It also specifically checked for regressions from earlier rounds' fixes (no leftover moneyness-ratio logic, no reintroduced hardcoded `0.20`/`0.85` literals) and found none. The plan is implementation-ready.
- **Verified against the repo's real pricer/data model while writing this plan:** the delta-selectable moneyness range at various vol/DTE combinations (used to justify rejecting the moneyness-ratio approach) was computed via the standard Black-Scholes `N^-1(delta)` inversion, not estimated. `test_heston_char_fn.py`'s exact `worst_overall` value (`0.9961874296821448`, both before and after removing the T/theta loops) and runtime (~0.01s) were measured directly, not guessed. `market.py`'s delta-defaulting behavior for the actually-invoked `fetch_option_chain_async` function was confirmed by reading `backend/app/data/market.py:1210,1222` directly (and the unrelated `:1319` function was read and confirmed to use the opposite convention, hence excluded from the filter's justification). `contract_rules.yaml`'s `min_delta`/`max_delta` defaults (0.20/0.85) and the frontend's unclamped `[0,1]` override range were both read directly, not assumed.
