# Alt-Contract Missing-Data Fabrication Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `_process_symbol()` in `backend/app/routers/scan.py` from fabricating plausible-looking `price`/`strike`/`dte` values for a runner-up (alternative) contract whose quote data is incomplete, and from running a fabricated premium through the real-IV reward/risk pipeline as if it were a genuine market quote.

**Architecture:** One added guard clause at the top of the existing alternative-contract-building loop in `_process_symbol()` (`backend/app/routers/scan.py`). When a runner-up's `alt_c` dict is missing `"price"`, `"strike"`, or `"dte"`, that runner-up is skipped entirely (not added to `alts`) instead of having any of those fields silently defaulted. No other files change; `alternativesCount` is already computed as `len(alts)` (line 1003), so skipping an entry automatically produces a correct, consistent count with zero additional bookkeeping. No backfill from further-down candidates is implemented — this matches the existing precedent that zero alternatives is already a valid, tested state (`test_scan_single_contract_produces_no_alternatives`).

**Tech Stack:** Python 3.14, FastAPI, pytest (`pytest-asyncio`). No new dependencies.

---

## Background (read before starting)

`_process_symbol()` in `backend/app/routers/scan.py` builds the primary trade card, then attaches up to 2 "runner-up" alternative contracts (`runner_ups = valid_scores[1:3]`, line 674) plus an optional alternative spread. For each runner-up, around line 904-919, it currently does:

```python
alts: list[AlternativeContract] = []
for alt_card, alt_c in runner_ups:
    alt_strike = float(alt_c.get("strike", price))
    alt_expiry_years = alt_c.get("dte", 30) / 365.0
    alt_premium = float(alt_c.get("price", 0.10))
    alt_rr = estimate_rr(
        stock_price=price,
        target_price=_target_raw,
        invalidation_price=_invalidation_raw,
        strike=alt_strike,
        expiry_years=alt_expiry_years,
        current_premium=alt_premium,
        is_call=(direction == "Bullish"),
        heston_params=heston_params,
        premium_stop_pct=_rr["premium_stop_pct"],
    )
    alts.append(AlternativeContract(
        symbol=symbol,
        strike=int(alt_strike),
        expiry=alt_c.get("expiry", "TBD"),
        right="C" if direction == "Bullish" else "P",
        dte=int(alt_c.get("dte", 30)),
        mid=round(float(alt_c.get("price", 0)), 2),
        delta=round(float(alt_c.get("delta", 0.45)), 3),
        theta=round(float(alt_c.get("theta", -0.05)), 3),
        ivRank=int(alt_c.get("ivRank", 50)),
        score=alt_card.score,
        contractConfidence=alt_card.status,
        contractBreakdown=ContractScoreBreakdown(...),
        rrRatio=alt_rr.rr_ratio,
        rrModel=alt_rr.model_used,
        reason=_alt_reason(alt_c, contract, is_call=(direction == "Bullish")),
    ))
```

`alt_c` dicts are the same augmented contract dicts as the primary contract (`augmented = [_augment(c, stock_price=price) for c in chain]`, line 640; `_augment` is `backend/app/data/augment.py`, which does `return {**c, "bid": ..., "ask": ..., "delta": ..., "iv_rank": ..., "iv_percentile": ...}` — it never strips or backfills `"price"`, `"strike"`, or `"dte"`; whatever the raw contract dict from `fetch_option_chain_async` had, or lacked, for those three keys passes straight through).

**Confirmed via direct reproduction (not just static reading)** — see verification notes at the end of this section — that when a runner-up's `alt_c` is missing `"price"` only (strike/dte present and valid), it currently:
1. Passes `validate_contract()`'s hard-reject checks (OI/volume/delta/dte/iv-rank are independent of the `"price"` key; the wide-spread hard-reject only fires if `"spread"` is *also* present alongside the missing price, since `_augment`'s `bid = mid - spread/2` / `ask = mid + spread/2` computation is what produces a spurious spread when `mid` collapses to 0 — a missing price with no spread data either does not trip that check).
2. Reaches the alt-contract loop, where `alt_premium = float(alt_c.get("price", 0.10))` substitutes a fabricated **$0.10**.
3. That $0.10 flows into `estimate_rr()` (`backend/app/scoring/reward_risk.py`) → `_derive_fallback_sigma()` → `bs_iv()`, which backs out a plausible-looking (but fabricated) implied volatility from it, producing a real-looking `rrRatio` and `estimatedOptionPrice` for that alternative. In the reproduction, this produced `rrRatio: 195.86` with `rrModel: "BS repriced (IV-derived)"` and `mid: 0.0` (the `mid` field uses a *different* default, `alt_c.get("price", 0)` at the `AlternativeContract(...)` call, so it silently shows `$0.00` while `rrRatio` looks like a real, large, attractive number) — a self-contradictory, misleading combination that would show a runner-up with a $0.00 premium and a 195.86 reward/risk ratio.

**Why `0.0` (an explicit real value, not a missing key) is already safe and stays out of scope:** if `alt_c["price"] == 0.0` (e.g. a genuinely illiquid contract with no quotes, which `_augment`'s own `mid = float(c.get("price", 0))` already treats as `0.0`), `.get("price", 0.10)` returns `0.0` (the default never applies), so `alt_premium = 0.0`. In `estimate_rr`, `risk = current_premium * premium_stop_pct` becomes `0.0`, and the function's existing guard (`if reward <= 0 or risk <= 0: return RrResult(rr_ratio=0.0, ...)`) already returns a harmless `rr_ratio=0.0` rather than fabricating a confident number. No change needed for that path.

**The `"strike"` and `"dte"` defaults have the identical fabrication shape and are fixed by the same guard.** `alt_strike = float(alt_c.get("strike", price))` (defaults to the *current stock price*, not a real strike) and `alt_expiry_years = alt_c.get("dte", 30) / 365.0` (defaults `dte` to 30 days) sit on the two lines immediately above the price fabrication. A runner-up missing either of these would otherwise be built into an `AlternativeContract` displaying a strike or DTE nobody observed, as if it were real — the same problem this plan fixes for price. This plan's guard covers all three fields together (see Task 2) rather than price alone, so the fix is internally consistent instead of leaving two adjacent, identically-shaped bugs unaddressed.

**Primary-contract equivalent, explicitly out of scope by user direction, not because the risk differs:** line 679, `premium = max(float(contract.get("price", 0.10)), 0.01)`, has the identical `.get(..., 0.10)` pattern for the *primary* contract (`contract = valid_scores[0]`, drawn from the exact same `validate_contract()`-screened list as the runner-ups — there is no separate, softer validation bar for either). It is arguably higher-impact than the runner-up case, since it drives `entry`, `target_price`, `invalidation_price`, `rrRatio`, and `contractDetails.mid` for the whole primary trade card, not one collapsible alternative row. It is **not touched by this plan** because the user scoped this task specifically to the alternatives path (`scan.py:908`); the primary-contract instance is a separate, real issue worth a follow-up task, not a scope-narrowing technicality.

**Verification method used while writing this plan (for the implementer's confidence, not a task to repeat):** rather than trust static reading alone, the bug and the fix were both reproduced directly by calling `_process_symbol()` in isolation (patching `score_stock`, `validate_contract`, `fetch_option_chain_async`, `build_trade_plan`, and `app.routers.scan._HESTON_PRICING_ENABLED = False` to isolate the BS-fallback path from Heston), confirming: (a) pre-fix, a runner-up with `"price"` missing produces `rrRatio: 195.86`, `rrModel: "BS repriced (IV-derived)"`, `mid: 0.0`; (b) post-fix (adding the guard from Task 2), that runner-up is excluded and `alternativesCount` drops to `0` with no other change in behavior. This is the same technique Task 1's test below uses.

**Note on testing via the full `/api/scan` HTTP endpoint (what `backend/tests/test_alternatives.py`'s existing 4 tests do):** during planning, this was tried first and found unreliable for this specific fix, for two independent reasons unrelated to this bug: (1) the shared `_MOCK_CANDLES` fixture in that file is flat/degenerate and its confidence sub-score is low enough that `_process_symbol` short-circuits at `card.status == "REJECT"` (line 635) *before* the option chain is ever scored — this affects the file's existing tests too, not just a new one, and is a separate, pre-existing test-coverage gap (see "Explicitly out of scope" below); (2) `_process_symbol`'s `db_bars` prefetch path (line 460-463) can bypass the `fetch_candles_async`/`fetch_price_async` mocks entirely for symbols that already have rows in the test DB (e.g. `AAPL`, which has seeded fixture data via `app/fixtures/candles.py`), making outcomes depend on unrelated DB/fixture state rather than the mocked chain. Both problems are sidestepped by calling `_process_symbol()` directly (as `backend/tests/test_scan_router_spreads.py` already does for its bearish-spread tests) with `score_stock`, `validate_contract`, and `build_trade_plan` patched to fixed, known-good results — this exercises the exact same alt-contract-building code this plan changes, deterministically, in under 3 seconds, with no dependency on scoring internals or DB state. Task 1 follows this established pattern.

---

## File Structure

- Modify: `backend/app/routers/scan.py` — extend the alternative-contract loop's field access in `_process_symbol()` (around line 905) with a skip guard.
- Test: `backend/tests/test_alternatives.py` — add one new test using the `_process_symbol()`-direct pattern already established in `backend/tests/test_scan_router_spreads.py`.

No new files.

---

### Task 1: Add a failing test that reproduces the fabrication bug

**Files:**
- Test: `backend/tests/test_alternatives.py`

- [ ] **Step 1: Write the failing test**

Add this test to the end of `backend/tests/test_alternatives.py` (after `test_scan_bearish_alternatives_have_right_P`, i.e. after line 127). It calls `_process_symbol()` directly rather than going through `client.post("/api/scan", ...)`, for the reasons explained in the Background section above:

```python
async def _run_alt_scan_with_runner_ups(runner_ups: list[dict]):
    """Like _run_alt_scan_with_runner_up, but takes the full list of
    runner-up dicts (chain[1:]) instead of exactly one, so a test can mix a
    valid runner-up with a broken one in the same chain."""
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.routers.scan import _process_symbol
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan

    pass_card = StockScoreCard(symbol="AAPL", direction="Bullish", horizon="Swing", score=75, status="PASS", rules=[])
    contract_score = ContractScoreCard(
        contract_id="AAPL|185|2026-09-13|C", symbol="AAPL", strike=185.0, expiry="2026-09-13",
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = EntryAssessment(limit_price=4.55, max_fill=4.65, order_type="Limit", quality_status="PASS")
    plan = TradePlan(
        entry=entry_result, invalidation_price=175.0, premium_stop=2.7, time_stop_days=12,
        target_price=200.0, targets=[], rr_ratio=2.0, rr_model="Heston repriced",
        target_price_raw=200.0, invalidation_price_raw=175.0,
    )

    chain = [
        {"strike": 185, "expiry": "2026-09-13", "price": 4.50, "spread": 0.15,
         "delta": 0.55, "theta": -0.06, "ivRank": 40, "dte": 45, "right": "C", "volume": 800},
        *runner_ups,
    ]

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple Inc.")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=plan),
        patch("app.routers.scan.log_event"),
        # Isolate the BS-fallback path (what this bug is about) from Heston,
        # which would otherwise calibrate off chain[0]'s real price and mask
        # the fallback-pricing fabrication these tests target.
        patch("app.routers.scan._HESTON_PRICING_ENABLED", False),
    ):
        return await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )


async def _run_alt_scan_with_runner_up(runner_up: dict):
    return await _run_alt_scan_with_runner_ups([runner_up])


def test_scan_alternative_with_missing_price_is_excluded():
    """A runner-up whose quote is missing 'price' must be excluded from
    alternatives, not fabricated into one with a fake $0.10 premium fed
    through the real-IV reward/risk pipeline. Regression test for the bug
    where alt_c.get("price", 0.10) silently substituted a fabricated
    premium that estimate_rr() then treated as a genuine market quote."""
    import asyncio
    runner_up = {
        # Missing "price" entirely -- simulates a runner-up quote with no
        # real market data. Must NOT be defaulted to a fabricated premium.
        "strike": 190, "expiry": "2026-09-13",
        "delta": 0.68, "theta": -0.05, "ivRank": 69, "dte": 45, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-price runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_with_missing_strike_is_excluded():
    """A runner-up whose quote is missing 'strike' must be excluded, not
    fabricated with the current stock price silently substituted as its
    strike (alt_c.get("strike", price))."""
    import asyncio
    runner_up = {
        # Missing "strike" entirely.
        "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 45, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-strike runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_with_missing_dte_is_excluded():
    """A runner-up whose quote is missing 'dte' must be excluded, not
    fabricated with a default 30-day expiry silently substituted
    (alt_c.get("dte", 30))."""
    import asyncio
    runner_up = {
        # Missing "dte" entirely.
        "strike": 190, "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-dte runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_skip_is_per_item_not_batch_wide():
    """When one runner-up has a complete quote and the other is missing
    'price', only the broken one is skipped -- the valid one still appears.
    Proves the guard is a per-item `continue`, not something that discards
    the whole runner-up batch or otherwise interacts across list entries."""
    import asyncio
    valid_runner_up = {
        "strike": 190, "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 45, "right": "C", "volume": 500,
    }
    broken_runner_up = {
        # Missing "price" entirely.
        "strike": 195, "expiry": "2026-09-13",
        "delta": 0.30, "theta": -0.03, "ivRank": 60, "dte": 45, "right": "C", "volume": 300,
    }
    result = asyncio.run(_run_alt_scan_with_runner_ups([valid_runner_up, broken_runner_up]))
    assert result.alternativesCount == 1, (
        f"Expected exactly the valid runner-up to survive, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives[0].strike == 190, (
        f"Expected the surviving alternative to be the valid strike=190 "
        f"runner-up, got strike={result.alternatives[0].strike}"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && "F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_alternatives.py -k missing_price_is_excluded -v`

Expected: **FAIL** — `result.alternativesCount == 1` (the strike=190 runner-up is currently fabricated into an alternative with `rrModel: "BS repriced (IV-derived)"`, `mid: 0.0`, and a large fabricated `rrRatio`), so `assert result.alternativesCount == 0` fails.

Then run the strike and dte variants too:

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && "F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_alternatives.py -k "missing_strike_is_excluded or missing_dte_is_excluded" -v`

Expected: **FAIL** for both — each runner-up is currently fabricated into an alternative (a fake strike equal to the stock price, or a fake 30-day DTE) instead of being excluded.

Then run the mixed-batch test:

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && "F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_alternatives.py::test_scan_alternative_skip_is_per_item_not_batch_wide -v`

Expected: **FAIL** — currently `alternativesCount == 2` (both runner-ups are fabricated into alternatives; the broken one isn't skipped at all yet), so `assert result.alternativesCount == 1` fails.

---

### Task 2: Fix the fabrication — skip runner-ups with incomplete quote data

**Files:**
- Modify: `backend/app/routers/scan.py:904-908`

- [ ] **Step 1: Add the skip guard**

In `_process_symbol()`, change:

```python
    alts: list[AlternativeContract] = []
    for alt_card, alt_c in runner_ups:
        alt_strike = float(alt_c.get("strike", price))
        alt_expiry_years = alt_c.get("dte", 30) / 365.0
        alt_premium = float(alt_c.get("price", 0.10))
```

to:

```python
    alts: list[AlternativeContract] = []
    for alt_card, alt_c in runner_ups:
        if alt_c.get("price") is None or alt_c.get("strike") is None or alt_c.get("dte") is None:
            # No real quote/strike/DTE for this runner-up -- do not fabricate
            # a value and run it through the real-IV reward/risk pipeline as
            # if it were observed data. Skip it; alternativesCount below is
            # len(alts), so this naturally yields a correct, consistent
            # count with no further bookkeeping.
            continue
        alt_strike = float(alt_c.get("strike", price))
        alt_expiry_years = alt_c.get("dte", 30) / 365.0
        alt_premium = float(alt_c.get("price", 0.10))
```

(The `.get(..., default)` fallbacks on the three lines below the guard are now dead for the missing-key/`None` case — guarded above — but are left as-is rather than rewritten, since touching them further is out of scope and risks an unrelated diff.)

- [ ] **Step 2: Run test to verify it passes**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && "F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_alternatives.py -v`

Expected: **PASS** — all tests in `test_alternatives.py`, including the four new ones, pass (8 passed). For the three missing-field tests, `result.alternativesCount == 0` and `result.alternatives == []`; for the mixed-batch test, `result.alternativesCount == 1` and the surviving alternative is the strike=190 one.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_alternatives.py
git commit -m "fix(scan): stop fabricating price/strike/dte for alt contracts with incomplete quote data"
```

---

### Task 3: Full regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && "F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest -q`

Expected: whatever the pre-change baseline count is on `main` at implementation time, plus exactly 4 new passing tests, 0 new failures. As of this plan being written, the baseline is **1182 passed, 9 skipped, 1 xpassed** — so the expected post-fix result is **1186 passed, 9 skipped, 1 xpassed, 0 failed**. If the baseline has drifted by the time this is implemented (e.g. from unrelated work landing on `main` first), compare against a fresh `main` run rather than treating this exact number as gospel — what matters is 0 failures and exactly 4 more passing tests than the fresh baseline. No regressions anywhere else, since the change is a single additive guard scoped to the alt-contract loop and touches no other code path.

---

## Explicitly out of scope

- `backend/app/routers/scan.py:679` (`premium = max(float(contract.get("price", 0.10)), 0.01)`, the primary contract's identical pattern) — not touched, per explicit user scoping to the alternatives path. See the Background section for why this is a real, separate, arguably higher-impact issue, not a technicality — worth flagging as a standalone follow-up.
- A present-but-non-numeric or present-but-negative `"price"`/`"strike"`/`"dte"` value (as opposed to a missing key or explicit `None`) — pre-existing behavior this plan does not change or worsen. `float(alt_c.get("price", 0.10))` would already raise on a non-numeric value regardless of this fix, and a negative value already flows through silently today; both are separate data-integrity concerns from the specific "key is missing so a plausible fake gets substituted" bug this plan addresses.
- Backfilling a 3rd/4th-ranked candidate to replace a skipped runner-up so `alternativesCount` stays at its previous maximum — not implemented; an empty or shorter alternatives list is already a valid, tested state in this codebase.
- Logging/telemetry when a runner-up is skipped — no existing precedent for this in the surrounding loop; not added.
- Fixing the pre-existing gap where `test_alternatives.py`'s 4 original tests never actually reach the alt-contract-building code (they short-circuit at the stock-score confidence gate before the option chain is ever scored, per the Background section) — a real, separate test-coverage bug, but out of scope for this plan; worth flagging as a standalone follow-up so those 4 tests get the same `_process_symbol()`-direct treatment as the new ones.
- `alt_c.get("delta", 0.45)`, `.get("theta", -0.05)`, and `.get("ivRank", 50)` in the same loop have a similar "silently substitute a plausible default" shape, but are deliberately NOT folded into the guard: none of them feed `estimate_rr()` (whose signature takes `stock_price`, `target_price`, `invalidation_price`, `strike`, `expiry_years`, `current_premium`, `is_call`, `heston_params`, `premium_stop_pct` — no delta/theta/iv-rank), so a missing one of these, unlike price/strike/dte, cannot compound into a fabricated R/R ratio. They still display a fabricated-looking cosmetic value on the alternative row, which is a real but lower-severity issue than this plan's target; left as a candidate for a future, separate pass.
