# Wire Reward/Risk Execution Params Through to the Options Trade Plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the four Step 3 "Reward/Risk" fields (`rr_bullish_target_pct`, `rr_bearish_target_pct`, `rr_bullish_invalidation_pct`, `rr_bearish_invalidation_pct`) actually change the target price, invalidation price, and R/R ratio the options scan pipeline computes — today they are accepted by the API but silently dropped before `build_trade_plan()` runs.

**Architecture:** Introduce one small merge helper in `backend/app/services/config_loader.py` that takes the base `risk_rules.yaml` `reward_risk` block plus a per-request `overrides` dict and returns a resolved `rr_cfg` dict. Call that helper (instead of the raw cached loader) everywhere `build_trade_plan`/`estimate_rr` currently gets `rr_cfg` — the main scan candidate, its runner-up alternatives, and the `/api/contracts/recompute-plan` endpoint — so a trader's Step 3 edits (and Step 6 contract override recompute) are honored consistently everywhere a trade card's numbers get computed. Bring the frontend's own displayed defaults back in line with the real backend defaults at the same time, since they currently show different numbers (10%/5%) than what the backend actually uses (8%/3%).

**Tech Stack:** FastAPI + Pydantic (backend), Next.js/TypeScript + Zustand (frontend), pytest, Jest.

---

## Verified current behavior (read directly from the code, not assumed)

- `backend/app/routers/scan.py:677` computes `_rr = _rr_cfg()` where `_rr_cfg` is `config_loader.load_reward_risk_cfg`, a bare `lru_cache`-wrapped read of `risk_rules.yaml`'s `reward_risk` block. It takes no arguments.
- `backend/app/scoring/stock_scorer.py`'s `score_stock()` override allow-list (lines ~952-990) has no `rr_*` keys, so even though the frontend's `overrides` dict is passed to `score_stock(overrides=overrides)`, those four keys are silently ignored there too.
- `backend/app/scoring/trade_plan.py`'s `build_trade_plan()` takes `rr_cfg: dict` as a plain argument — it has no knowledge of per-request overrides; it just uses whatever dict the caller hands it.
- `backend/app/routers/contracts.py:219`'s `recompute_plan` endpoint (used by Step 6/7 contract override) calls `build_trade_plan(..., rr_cfg=_rr_cfg())` — same bare load, and its `RecomputePlanRequest` model has no `rr_*` fields to even carry an override.
- The frontend sends the four fields today: `frontend/components/organisms/RunScanButton/index.tsx:131-137` builds `effectiveOverrides` from `scanStore.scanOverrides` (only stripping the `confidence_*` keys) and `frontend/lib/api.ts:375` puts `overrides: overrides ?? {}` straight into the `POST /api/scan` body. So the values genuinely leave the browser — they just never get read on arrival.
- `frontend/lib/executionParamDefaults.ts` shows the trader `rr_bullish_target_pct: 0.10` / `rr_bearish_target_pct: 0.10` / `rr_bullish_invalidation_pct: 0.05` / `rr_bearish_invalidation_pct: 0.05` for every horizon, but `backend/config/risk_rules.yaml`'s real values are `bullish_target_pct: 0.08`, `bearish_target_pct: 0.08`, `bullish_invalidation_pct: 0.03`, `bearish_invalidation_pct: 0.03`. Two different numbers, and neither one is what a scan run without touching the panel actually uses to a trader's knowledge — the panel *claims* to be the live number.
- `backend/app/routers/scan.py:904-926` builds each `AlternativeContract`'s R/R via a second `estimate_rr(...)` call that reuses `_target_raw`/`_invalidation_raw` from the primary contract's plan and reads `premium_stop_pct=_rr["premium_stop_pct"]`. **This line needs no separate edit** — `_rr` is a single local variable reused by both the primary `build_trade_plan()` call and this alternatives loop within the same function scope, so once Task 2 reassigns `_rr` to the merged config, this line picks up the override automatically. It's called out here only because tracing every `_rr`/`premium_stop_pct` reader was necessary to confirm there's no *second*, independent read of the un-merged config hiding in the alternatives path — there isn't.

---

## File Structure

- Modify: `backend/app/services/config_loader.py` — add `merge_reward_risk_overrides(overrides: dict | None) -> dict`.
- Modify: `backend/app/routers/scan.py` — replace `_rr = _rr_cfg()` with the merged config (the alternatives loop's `premium_stop_pct` read needs no separate edit — see "Verified current behavior" above).
- Modify: `backend/app/routers/contracts.py` — add four optional `rr_*` fields to `RecomputePlanRequest`; merge them before calling `build_trade_plan`.
- Modify: `frontend/lib/api.ts` — add the four optional fields to `recomputePlan`'s request type.
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` — pass the current `rr_*` overrides into both `api.recomputePlan(...)` call sites.
- Modify: `frontend/lib/executionParamDefaults.ts` — correct the displayed `rr_*` defaults to match `risk_rules.yaml` (0.08 / 0.08 / 0.03 / 0.03) for every horizon row.
- Test: `backend/tests/test_config_loader.py` (new).
- Test: `backend/tests/test_scan_endpoint.py` (extend).
- Test: `backend/tests/test_contracts_scoring.py` (extend).
- Test: `frontend/lib/__tests__/executionParamDefaults.test.ts` (new — or extend if a file matching that name already exists after Task 1's Glob check below).

---

### Task 1: Merge helper for reward/risk overrides

**Files:**
- Modify: `backend/app/services/config_loader.py`
- Test: `backend/tests/test_config_loader.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config_loader.py`:

```python
"""Tests for app.services.config_loader's reward/risk override merging."""
from app.services.config_loader import load_reward_risk_cfg, merge_reward_risk_overrides


def test_merge_with_no_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides({})
    assert merged == base


def test_merge_with_none_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides(None)
    assert merged == base


def test_merge_overrides_bullish_target_pct():
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": 0.12})
    assert merged["bullish_target_pct"] == 0.12
    # Untouched keys keep the base config's values.
    base = load_reward_risk_cfg()
    assert merged["bearish_target_pct"] == base["bearish_target_pct"]
    assert merged["premium_stop_pct"] == base["premium_stop_pct"]


def test_merge_overrides_all_four_rr_keys():
    merged = merge_reward_risk_overrides({
        "rr_bullish_target_pct": 0.12,
        "rr_bearish_target_pct": 0.09,
        "rr_bullish_invalidation_pct": 0.04,
        "rr_bearish_invalidation_pct": 0.05,
    })
    assert merged["bullish_target_pct"] == 0.12
    assert merged["bearish_target_pct"] == 0.09
    assert merged["bullish_invalidation_pct"] == 0.04
    assert merged["bearish_invalidation_pct"] == 0.05


def test_merge_ignores_unrelated_override_keys():
    """Other scan overrides (e.g. rsi_floor) must not leak into rr_cfg or raise."""
    merged = merge_reward_risk_overrides({"rsi_floor": 40, "rr_bullish_target_pct": 0.11})
    assert merged["bullish_target_pct"] == 0.11
    assert "rsi_floor" not in merged


def test_merge_does_not_mutate_the_cached_base_config():
    base_before = dict(load_reward_risk_cfg())
    merge_reward_risk_overrides({"rr_bullish_target_pct": 0.99})
    assert load_reward_risk_cfg() == base_before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_config_loader.py -v`
Expected: `ImportError: cannot import name 'merge_reward_risk_overrides'`

- [ ] **Step 3: Write the implementation**

In `backend/app/services/config_loader.py`, add below `load_reward_risk_cfg`:

```python
# Maps the Step 3 "Reward/Risk" panel's override keys (frontend/lib/
# executionParamDefaults.ts) onto risk_rules.yaml's reward_risk block keys.
_RR_OVERRIDE_KEY_MAP = {
    "rr_bullish_target_pct":       "bullish_target_pct",
    "rr_bearish_target_pct":       "bearish_target_pct",
    "rr_bullish_invalidation_pct": "bullish_invalidation_pct",
    "rr_bearish_invalidation_pct": "bearish_invalidation_pct",
}


def merge_reward_risk_overrides(overrides: dict | None) -> dict:
    """Return risk_rules.yaml's reward_risk block with any per-request rr_*
    overrides applied on top.

    Returns a fresh dict every call — load_reward_risk_cfg()'s cached dict is
    never mutated, so a later call with different (or no) overrides isn't
    affected by an earlier one.
    """
    merged = dict(load_reward_risk_cfg())
    for override_key, cfg_key in _RR_OVERRIDE_KEY_MAP.items():
        if overrides and override_key in overrides:
            merged[cfg_key] = float(overrides[override_key])
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_config_loader.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/config_loader.py backend/tests/test_config_loader.py
git commit -m "feat(config): add reward/risk override merge helper"
```

---

### Task 2: Use the merged config in the scan pipeline

**Files:**
- Modify: `backend/app/routers/scan.py:677`, `:755-767`, `:916-926`
- Test: `backend/tests/test_scan_endpoint.py`

- [ ] **Step 1: Write the failing test**

**Do not reuse `_MOCK_CHAIN`/`_MOCK_CANDLES` with only `{"universe": [...], "overrides": {...}}` the way earlier drafts of this plan did — verified by actually running it that this produces an empty `candidates` list, for three independent reasons, and the assertions never even get to check a target price:**

1. `_MOCK_CHAIN`'s contract has no `open_interest` key at all — `contract.get("open_interest") or 0` defaults to `0`, which is below `contract_rules.yaml`'s `hard_reject.min_open_interest: 200`, so the contract is hard-rejected (`open_interest_too_low`) regardless of anything else.
2. `_MOCK_CHAIN`'s hardcoded `"expiry": "2026-06-20"` is a fixed calendar date that is **in the past** relative to whenever these tests actually run (dte would compute negative), which independently trips `dte_too_short`.
3. Even with both of those fixed, `_enter_mock_patches` does **not** fully isolate the scan from real backend state: `run_scan` pre-fetches a batch `price_map` via `fetch_quotes` (imported at `scan.py` module scope) and a batch `bars_map` via a *locally-imported* `app.services.historical_store.get_bars` (imported fresh inside the `run_scan` function body, not at module scope) — **neither is covered by `_enter_mock_patches`**, which only patches `fetch_price_async`/`fetch_candles_async`/`fetch_option_chain_async`/`fetch_company_name_async`/`fetch_fundamentals_calendar`. Confirmed by actually running this: if this repo's dev database already has real ingested OHLCV history for the test symbol (true in this repo's environment), `bars_map` comes back with *real* AAPL data instead of `_MOCK_CANDLES`, `_process_symbol` takes the `db_bars is not None` branch (`scan.py:459-467`) which never calls the mocked fetch functions at all, and the test silently runs against AAPL's real live price (observed: `333.07`, not `185.0`) instead of the fixture.
4. Separately, even a contract that survives all of the above still gets capped to REJECT by the default `confidence_gate` (`scoring_rules.yaml`'s `rejectBelow: 35`) once the real `score_stock()` runs against `_MOCK_CANDLES`'s synthetic flat-ish price series, since a synthetic series has no reliable backtested confidence. This is a pre-existing, already-documented problem in this exact test file — `test_scan_endpoint.py` already has a helper for it, `_force_passing_stock_score()` (defined a few hundred lines down, used by `test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends` and its sibling): it patches `app.routers.scan.score_stock` to a `MagicMock` returning a fixed `StockScoreCard(status="PASS", score=80)`, sidestepping the confidence/regime/fundamentals gates entirely so the test isolates the thing it's actually trying to prove.

Reuse that same, already-proven pattern, plus two extra patches to close the DB-leak in point 3. Append to `backend/tests/test_scan_endpoint.py`, **after** `_force_passing_stock_score()`'s own definition (so it's already in scope). **Check first whether the companion plan `2026-07-31-horizon-aware-contract-iv-gate.md`'s Task 2 has already been implemented and already added a `_no_db_leak()` helper to this file** (it has the identical DB-leak problem and defines the same fix) — if so, reuse that existing helper instead of adding a second, duplicate one:

```python
def _rr_test_chain(iv_rank: float = 55) -> list[dict]:
    """A single contract that clears every contract_rules.yaml hard-reject
    check (unlike _MOCK_CHAIN, which is missing open_interest and has a stale
    hardcoded expiry date) -- so it reliably becomes a candidate regardless of
    when this test runs."""
    return [{
        "strike": 190, "expiry": _dte_expiry(35), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": iv_rank, "dte": 35,
        "right": "C", "volume": 500, "open_interest": 2000,
    }]


def _no_db_leak():
    """Force the mocked candles/price fixtures to actually be used. Without
    this, run_scan's DB-backed bars_map/price_map pre-fetch (scan.py's
    fetch_quotes and a locally-imported historical_store.get_bars -- neither
    covered by _enter_mock_patches) can silently return real historical data
    for a symbol this repo's dev database already has ingested, bypassing
    _MOCK_CANDLES/price entirely."""
    return (
        patch("app.routers.scan.fetch_quotes", return_value={}),
        patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])),
    )


def test_scan_rr_bullish_target_pct_override_changes_target_price(client):
    """Without the override, target = price * 1.08 (risk_rules.yaml default).
    With rr_bullish_target_pct=0.20, target = price * 1.20 instead."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r_default = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
        r_override = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"rr_bullish_target_pct": 0.20},
        })
    default_candidates = r_default.json()["candidates"]
    override_candidates = r_override.json()["candidates"]
    assert default_candidates, "expected AAPL to score as a candidate for this fixture"
    assert override_candidates, "expected AAPL to score as a candidate for this fixture"
    default_target = default_candidates[0]["exit"]["target"]
    override_target = override_candidates[0]["exit"]["target"]
    assert override_target > default_target
    assert round(override_target, 2) == round(185.0 * 1.20, 2)


def test_scan_rr_override_leaves_default_scan_unchanged(client):
    """A scan with no rr_* overrides must still use the risk_rules.yaml default
    (8% bullish target) -- guards against the merge helper changing the
    no-override path's numbers."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    candidates = r.json()["candidates"]
    assert candidates
    assert round(candidates[0]["exit"]["target"], 2) == round(185.0 * 1.08, 2)
```

`_dte_expiry` (a small helper computing `(date.today() + timedelta(days=days_from_today)).isoformat()`) is already defined earlier in this same file, immediately before `_force_passing_stock_score()`. `AsyncMock` is already imported at the top of the file (`from unittest.mock import patch, AsyncMock, MagicMock`). No new imports needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_scan_endpoint.py -k rr_override -v`
Expected: `test_scan_rr_bullish_target_pct_override_changes_target_price` FAILS — `override_target == default_target` (both computed off the un-merged 8% default). `test_scan_rr_override_leaves_default_scan_unchanged` PASSES already (it's a regression guard for after the fix) — if either fails for a different reason (empty `candidates`, a `stock_price` that isn't `185.0`, an import error), the fixture/patching is still broken; fix that before continuing rather than assuming the failure proves the bug.

- [ ] **Step 3: Write the implementation**

In `backend/app/routers/scan.py`, change the import line (currently `from app.services.config_loader import load_reward_risk_cfg as _rr_cfg`) to also import the new helper:

```python
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
from app.services.config_loader import merge_reward_risk_overrides as _merge_rr_cfg
```

Replace line 677:

```python
    _rr = _rr_cfg()
```

with:

```python
    _rr = _merge_rr_cfg(overrides)
```

`overrides` is already the `_process_symbol` function's own parameter (the same dict passed to `score_stock(overrides=overrides)` a few lines above) — no new plumbing needed to get it into scope.

No further edit is needed for the alternatives loop (around line 925) — confirm this by inspection rather than skipping it:

```python
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
```

This line already reads `_rr["premium_stop_pct"]` — since `_rr` is now the merged config (not the base one), this line needs no further edit. Confirm by inspection that no other reference to the old `_rr_cfg()` call remains at module scope inside `_process_symbol`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_scan_endpoint.py -k rr_override -v`
Expected: 2 passed

Then run the full scan test file to check nothing else broke:

Run: `cd backend && pytest tests/test_scan_endpoint.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_scan_endpoint.py
git commit -m "fix(scan): honor rr_bullish/bearish_target_pct and invalidation_pct overrides"
```

---

### Task 3: Wire the same override into the Step 6/7 recompute-plan endpoint

**Files:**
- Modify: `backend/app/routers/contracts.py:165-220`
- Test: `backend/tests/test_contracts_scoring.py`

- [ ] **Step 1: Write the failing test**

`test_contracts_scoring.py` defines **no shared client fixture at all** — its own integration test builds an inline `FastAPI()` app, `include_router(contracts_router)`, and an `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`, and is itself an `async def` test (there is no synchronous `app_client`/`client` fixture anywhere in this file — `conftest.py`'s `client` fixture is a different, synchronous `TestClient` used by other test files, not this one). Match that exact pattern — do not invent a fixture name.

Append to `backend/tests/test_contracts_scoring.py`:

```python
@pytest.mark.asyncio
async def test_recompute_plan_rr_bullish_target_pct_override_changes_target():
    """Same override key set as the scan endpoint (rr_bullish_target_pct) must
    also move Step 6's recompute-plan target, or a user who overrides the
    contract after tuning R/R params would silently lose their tuning."""
    app = FastAPI()
    app.include_router(contracts_router)
    payload_base = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
        "strike": 190.0, "dte": 30, "premium": 2.50, "delta": 0.45, "spread": 0.10,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r_default = await ac.post("/api/contracts/recompute-plan", json=payload_base)
        r_override = await ac.post("/api/contracts/recompute-plan", json={
            **payload_base, "rr_bullish_target_pct": 0.20,
        })
    assert r_default.status_code == 200
    assert r_override.status_code == 200
    default_target = r_default.json()["exit"]["target"]
    override_target = r_override.json()["exit"]["target"]
    assert override_target > default_target
    assert round(override_target, 2) == round(185.0 * 1.20, 2)
```

`FastAPI`, `AsyncClient`, `ASGITransport`, and `contracts_router` are already imported at the top of `test_contracts_scoring.py` (confirmed: `from fastapi import FastAPI`, `from httpx import AsyncClient, ASGITransport`, `from app.routers.contracts import router as contracts_router`) — no new imports needed. If the project's pytest config doesn't already enable `pytest.mark.asyncio` implicitly (check `backend/pytest.ini` / `pyproject.toml` for `asyncio_mode = auto`), keep the explicit `@pytest.mark.asyncio` decorator shown above; if it's already `auto`, the decorator is harmless but redundant — either way, match whatever the file's existing `async def test_...` function does (with or without the decorator).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_contracts_scoring.py -k rr_bullish_target_pct -v`
Expected: FAIL — `422 Unprocessable Entity` (the field `rr_bullish_target_pct` doesn't exist on `RecomputePlanRequest` yet) or, if pydantic silently ignores unknown fields, FAIL on `override_target == default_target`.

- [ ] **Step 3: Write the implementation**

In `backend/app/routers/contracts.py`, add the import:

```python
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
from app.services.config_loader import merge_reward_risk_overrides as _merge_rr_cfg
```

Extend `RecomputePlanRequest`:

```python
class RecomputePlanRequest(BaseModel):
    symbol: str
    direction: Literal["Bullish", "Bearish"]
    stock_price: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    dte: int = Field(..., ge=0)
    premium: float = Field(..., gt=0)   # selected contract mid
    delta: float = 0.45
    spread: float = 0.0
    # Optional per-request reward/risk overrides — mirrors the same keys the
    # scan endpoint accepts in ScanRequest.overrides, so a contract override
    # recompute (Step 6/7) honors whatever R/R tuning the trader set on Step 3
    # instead of silently reverting to risk_rules.yaml's defaults.
    rr_bullish_target_pct: float | None = None
    rr_bearish_target_pct: float | None = None
    rr_bullish_invalidation_pct: float | None = None
    rr_bearish_invalidation_pct: float | None = None
```

Update `recompute_plan` to build the overrides dict and merge it:

```python
@router.post('/contracts/recompute-plan', response_model=RecomputePlanResponse)
async def recompute_plan(req: RecomputePlanRequest) -> RecomputePlanResponse:
    half = max(req.spread, 0.0) / 2
    entry_bid = max(0.01, req.premium - half)
    entry_ask = req.premium + half

    _rr_overrides = {
        k: v for k, v in {
            "rr_bullish_target_pct":       req.rr_bullish_target_pct,
            "rr_bearish_target_pct":       req.rr_bearish_target_pct,
            "rr_bullish_invalidation_pct": req.rr_bullish_invalidation_pct,
            "rr_bearish_invalidation_pct": req.rr_bearish_invalidation_pct,
        }.items() if v is not None
    }

    plan = build_trade_plan(
        direction=req.direction,
        stock_price=req.stock_price,
        strike=req.strike,
        dte=req.dte,
        premium=req.premium,
        delta=req.delta,
        entry_bid=entry_bid,
        entry_ask=entry_ask,
        entry_mid=req.premium,
        rr_cfg=_merge_rr_cfg(_rr_overrides),
    )
```

(Leave the rest of the function — the `TradePlan` → `RecomputePlanResponse` mapping — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_contracts_scoring.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/contracts.py backend/tests/test_contracts_scoring.py
git commit -m "fix(contracts): honor rr_* overrides in recompute-plan endpoint"
```

---

### Task 4: Thread the override through the frontend's Step 6/7 recompute calls

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:285-294`, `:355-364`

- [ ] **Step 1: Extend the `recomputePlan` request type**

In `frontend/lib/api.ts`, find the `recomputePlan` method (around line 325) and extend its request type:

```typescript
  recomputePlan: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    stock_price: number;
    strike: number;
    dte: number;
    premium: number;
    delta: number;
    spread: number;
    rr_bullish_target_pct?: number;
    rr_bearish_target_pct?: number;
    rr_bullish_invalidation_pct?: number;
    rr_bearish_invalidation_pct?: number;
  }, signal?: AbortSignal) =>
```

Leave the function body (the `post(...)` call) unchanged — it already forwards the whole `req` object as the JSON body, so any new keys pass through automatically. Confirm this by reading the existing body of `recomputePlan` before editing; only the type annotation changes.

- [ ] **Step 2: Build a small override-extraction helper**

In `frontend/lib/tradeCardOverride.ts`, add:

```typescript
const RR_OVERRIDE_KEYS = [
  'rr_bullish_target_pct', 'rr_bearish_target_pct',
  'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct',
] as const;

/** Pull just the four Reward/Risk override keys out of scanOverrides, dropping
 *  any that aren't set (so recomputePlan's optional fields stay optional). */
export function rrOverridesFrom(
  scanOverrides: Record<string, number | boolean | string>,
): Partial<Record<typeof RR_OVERRIDE_KEYS[number], number>> {
  const out: Partial<Record<typeof RR_OVERRIDE_KEYS[number], number>> = {};
  for (const key of RR_OVERRIDE_KEYS) {
    const v = scanOverrides[key];
    if (typeof v === 'number') out[key] = v;
  }
  return out;
}
```

- [ ] **Step 3: Write a unit test for the helper**

Create `frontend/lib/__tests__/tradeCardOverride.rrOverrides.test.ts`:

```typescript
import { rrOverridesFrom } from '@/lib/tradeCardOverride';

describe('rrOverridesFrom', () => {
  it('extracts only the four rr_* keys that are numbers', () => {
    const result = rrOverridesFrom({
      rr_bullish_target_pct: 0.12,
      rsi_floor: 40,
      trend_method: 'additive',
    });
    expect(result).toEqual({ rr_bullish_target_pct: 0.12 });
  });

  it('returns an empty object when no rr_* keys are set', () => {
    expect(rrOverridesFrom({ rsi_floor: 40 })).toEqual({});
  });

  it('extracts all four keys when all are present', () => {
    const result = rrOverridesFrom({
      rr_bullish_target_pct: 0.12,
      rr_bearish_target_pct: 0.09,
      rr_bullish_invalidation_pct: 0.04,
      rr_bearish_invalidation_pct: 0.05,
    });
    expect(result).toEqual({
      rr_bullish_target_pct: 0.12,
      rr_bearish_target_pct: 0.09,
      rr_bullish_invalidation_pct: 0.04,
      rr_bearish_invalidation_pct: 0.05,
    });
  });
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=tradeCardOverride.rrOverrides`
Expected: 3 passed

- [ ] **Step 5: Wire it into both `recomputePlan` call sites**

In `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, add the import:

```typescript
import { rrOverridesFrom } from '@/lib/tradeCardOverride';
```

At the first call site (around line 285, inside the active-card recompute effect):

```typescript
        api.recomputePlan({
          symbol,
          direction:   pickedCard.direction,
          stock_price: pickedCard.price,
          strike:      liveQcd.strike,
          dte:         liveQcd.dte,
          premium:     q?.price ?? liveQcd.mid,
          delta:       liveQcd.delta,
          spread:      q?.spread ?? 0,
          ...rrOverridesFrom(useScanStore.getState().scanOverrides),
        }, controller.signal)
```

At the second call site (around line 355, inside the basket recompute effect):

```typescript
      api.recomputePlan({
        symbol: sym,
        direction: resolved.direction,
        stock_price: resolved.price,
        strike: cd.strike,
        dte: cd.dte,
        premium: cd.mid,
        delta: cd.delta,
        spread: 0,
        ...rrOverridesFrom(useScanStore.getState().scanOverrides),
      }, controller.signal)
```

`useScanStore` is already imported in this file (it's used elsewhere on the page for `pickedCard`/basket state) — confirm the import exists before adding the calls; if the file imports individual selectors rather than the store object itself, use `useScanStore.getState().scanOverrides` exactly as shown, which works regardless of which selectors are already destructured via hooks elsewhere in the component.

- [ ] **Step 6: Manual verification (no existing test harness covers this integration path)**

Run: `cd frontend && npm run dev`, open the screener, run an options scan, change "Bullish target %" on Step 3, proceed to Step 6, override the auto-picked contract with a different strike, and confirm the recomputed Exit Plan's target price on Step 7 reflects the Step 3 override (compare against the formula `stock_price * (1 + rr_bullish_target_pct)`).

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/tradeCardOverride.ts frontend/lib/__tests__/tradeCardOverride.rrOverrides.test.ts "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(step7): forward rr_* overrides into recompute-plan calls"
```

---

### Task 5: Fix the frontend's displayed R/R defaults to match the real backend defaults

**Files:**
- Modify: `frontend/lib/executionParamDefaults.ts`
- Test: `frontend/app/(frame)/screener/step-3-direction/__tests__/paramDefaults.eventDays.test.ts` (reference — do not modify; model the new test on it)
- Test: `frontend/lib/__tests__/executionParamDefaults.rrDefaults.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/executionParamDefaults.rrDefaults.test.ts`:

```typescript
import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// backend/config/risk_rules.yaml's reward_risk block is the source of truth:
// bullish_target_pct: 0.08, bearish_target_pct: 0.08,
// bullish_invalidation_pct: 0.03, bearish_invalidation_pct: 0.03.
const EXPECTED_RR_DEFAULTS = {
  rr_bullish_target_pct: 0.08,
  rr_bearish_target_pct: 0.08,
  rr_bullish_invalidation_pct: 0.03,
  rr_bearish_invalidation_pct: 0.03,
};

describe('PARAM_DEFAULTS_PER_HORIZON reward/risk defaults match risk_rules.yaml', () => {
  for (const horizon of ['Intraday', 'Swing', 'Position', 'Custom'] as const) {
    it(`${horizon} row matches the backend default`, () => {
      const row = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(row.rr_bullish_target_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bullish_target_pct);
      expect(row.rr_bearish_target_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bearish_target_pct);
      expect(row.rr_bullish_invalidation_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bullish_invalidation_pct);
      expect(row.rr_bearish_invalidation_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bearish_invalidation_pct);
    });
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=executionParamDefaults.rrDefaults`
Expected: FAIL — every horizon row currently has `0.10`/`0.10`/`0.05`/`0.05`.

- [ ] **Step 3: Fix the four values in every horizon row**

In `frontend/lib/executionParamDefaults.ts`, in `PARAM_DEFAULTS_POSITION`, the `Intraday` entry, and the `Swing` entry, and the `Custom` entry (four separate object literals — `Position` is reused by `Quarterly`/`SemiAnnual`/`Annual` via spread, so fixing `PARAM_DEFAULTS_POSITION` covers those three automatically), change:

```typescript
  rr_bullish_target_pct: 0.10, rr_bearish_target_pct: 0.10,
  rr_bullish_invalidation_pct: 0.05, rr_bearish_invalidation_pct: 0.05,
```

to:

```typescript
  rr_bullish_target_pct: 0.08, rr_bearish_target_pct: 0.08,
  rr_bullish_invalidation_pct: 0.03, rr_bearish_invalidation_pct: 0.03,
```

in all four places (`PARAM_DEFAULTS_POSITION`, `Intraday`, `Swing`, `Custom`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=executionParamDefaults.rrDefaults`
Expected: 4 passed

- [ ] **Step 5: Run the full frontend test suite to check for incidental breakage**

Run: `cd frontend && npm run test`
Expected: all passed (no other test asserts the old 0.10/0.05 values — if one does, update it to 0.08/0.03 to match, since that test was pinning the wrong number).

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/executionParamDefaults.ts frontend/lib/__tests__/executionParamDefaults.rrDefaults.test.ts
git commit -m "fix(step3): correct displayed R/R defaults to match risk_rules.yaml"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 builds the merge primitive; Task 2 wires the main scan + alternatives path; Task 3 wires the Step 6/7 recompute path (the second consumer identified during investigation, not mentioned in the original finding but required for the fix to be complete — a scan honoring the override while a contract override silently reverts would be a new, subtler inconsistency); Task 4 makes the frontend actually send the override on recompute (previously it never did, even before this bug); Task 5 fixes the pre-existing display-only default mismatch. All four verified-broken behaviors are covered.
- **Placeholder scan:** No TBD/placeholder code; every step shows exact code and exact file locations.
- **Type consistency:** `merge_reward_risk_overrides` is defined once in `config_loader.py` and imported by name (`_merge_rr_cfg`) identically in both `scan.py` and `contracts.py`. `rrOverridesFrom`'s key list (`RR_OVERRIDE_KEYS`) matches the four keys used in `_RR_OVERRIDE_KEY_MAP` on the backend and the four new optional fields on `RecomputePlanRequest`.
- **Test-fixture correction (round 2, verified by actually executing the tests against the real repo):** Task 2's tests originally reused this file's existing `_MOCK_CHAIN`/no-gate-override scan payload. Run for real, both new tests returned an empty `candidates` list — `_MOCK_CHAIN` has no `open_interest` field (hard-rejected below the 200 minimum) and its hardcoded `"expiry": "2026-06-20"` is a stale date that's now in the past (negative DTE, also hard-rejected); separately, the default `confidence_gate` caps a real `score_stock()` run against synthetic candles to REJECT regardless of contract validity. The tests now use a locally-defined `_rr_test_chain()` fixture (valid rolling expiry via the file's existing `_dte_expiry()` helper, explicit `open_interest`) combined with this file's existing `_force_passing_stock_score()` helper (already used elsewhere in the same file for exactly this class of problem) to isolate the R/R feature under test from unrelated scoring-pipeline gates.
- **DB-leak correction (round 3, verified by actually executing the tests against the real repo a second time):** even after round 2's fixture fix, the tests still failed — this time because `_enter_mock_patches` doesn't patch `scan.py`'s batch `fetch_quotes` call or its locally-imported `historical_store.get_bars` call, so on a dev database with real ingested AAPL history, the scan silently used a real live price (observed: `333.07`) instead of the fixture's `185.0`, making every hardcoded `185.0 * 1.08`/`185.0 * 1.20` assertion meaningless. Added a `_no_db_leak()` helper patching both, used in both tests. This same fix is needed by the companion `horizon-aware-contract-iv-gate.md` plan's Task 2 tests — implement `_no_db_leak()` once and reuse it if both plans are implemented, rather than adding it twice.
- **Test-harness correction (post-audit):** Task 3's test originally called a nonexistent `app_client` fixture (`conftest.py` only defines a synchronous `client` fixture used by other test files; `test_contracts_scoring.py` itself defines no fixture at all and builds its client inline per async test). The test now matches that file's actual, existing async `FastAPI()` + `AsyncClient`/`ASGITransport` pattern.
- **Self-contradiction correction (post-audit):** the plan originally said the alternatives loop's `premium_stop_pct` read (scan.py ~line 925) "needs the same fix," then Task 2 correctly implemented no edit there. The "Verified current behavior" section and File Structure now state up front that no edit is needed there, so an implementer isn't tempted to make an unnecessary (and likely incorrect) change to a line the plan doesn't actually touch.
