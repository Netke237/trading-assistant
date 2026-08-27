# Horizon-Aware Contract IV-Rank Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the contract-scoring "IV rank too rich" soft penalty (`contract_rules.yaml`'s `soft_rank.preferred_iv_rank_max`) horizon-aware, so a Position-horizon scan (which the stock-scorer's own `vol` rule already treats as tolerant of IV rank up to 65) doesn't dock a contract's score using the stricter Swing-level ceiling of 55 that's currently applied to every horizon uniformly.

**Architecture:** `contract_validator.py`'s `validate_contract()` already accepts a per-call `overrides` dict — the exact same mechanism `scan.py` already uses to widen DTE bounds per horizon (`widen_contract_overrides_for_dte`). This plan adds one new recognized override key, `preferred_iv_rank_max`, to `validate_contract`'s allow-list, then has both callers that build contract-scoring overrides (`scan.py`'s main pipeline and `contracts.py`'s `GET /api/contracts` endpoint) inject the horizon's own `iv_rank_caution_max` from `scoring_rules.yaml` into that key — reusing the exact ceiling the stock-score's own `vol` rule already treats as "acceptable, not yet rich" for that horizon, instead of leaving the two systems to disagree.

**Tech Stack:** FastAPI + Pydantic (backend), pytest.

---

## Verified current behavior (read directly from the code, not assumed)

- `backend/config/contract_rules.yaml`'s `soft_rank.preferred_iv_rank_max: 55` and `hard_reject.max_iv_rank: 70` are single global numbers with no per-horizon variant.
- `backend/config/scoring_rules.yaml`'s `horizons.<horizon>.vol` block IS per-horizon: `swing.vol.iv_rank_caution_max: 55`, `position.vol.iv_rank_caution_max: 65`, `intraday.vol.iv_rank_caution_max: null` (the stock-score `vol` rule is skipped entirely for Intraday — confirmed in `backend/app/scoring/stock_scorer.py`'s `_rule_vol()`: `if vc["iv_rank_pass_max"] is None: return RuleResult("vol", "PASS", 90, {"iv_rank": iv_rank, "scored": False})`).
- `backend/app/scoring/contract_validator.py`'s `_score_iv_rank()` reads `cfg["soft_rank"]["preferred_iv_rank_max"]` with no horizon input at all — `validate_contract()`'s signature is `(contract: dict, stock_score: int, overrides: dict | None = None)`, no `horizon` parameter.
- `validate_contract()`'s override-merge loop (lines ~236-246) already recognizes `max_iv_rank` (hard-reject threshold) as an override key — confirmed by the existing test `test_override_raises_max_iv_rank` in `backend/tests/test_contract_validator.py`. It does **not** recognize `preferred_iv_rank_max` (soft-rank threshold) — there is no `elif key == "preferred_iv_rank_max"` branch.
- `backend/app/routers/scan.py:645-653` already builds a per-call `contract_overrides` dict and widens DTE bounds into it via `widen_contract_overrides_for_dte` before calling `validate_contract(c, card.score, overrides=contract_overrides)` — this is the exact, already-proven mechanism for injecting horizon-derived values into contract scoring. The `horizon` variable is in scope at this point (it's `_process_symbol`'s own parameter, used earlier in the same function for the regime signal at line 522).
- `backend/app/routers/contracts.py`'s `GET /api/contracts` endpoint declares `horizon: str = Query(default='swing')` in its signature (line 43) but **never references it anywhere in the function body** — confirmed by grep; it's a dead parameter today.
- `IvRankDetail.preferred_max` (in `backend/app/schemas/__init__.py`) is the exact field that will change value once this is wired for the **scan** endpoint — it's already serialized into every `TradeCardData.contractBreakdown.ivDetail.preferred_max` in the `POST /api/scan` response, so Task 2's fix is directly observable via an integration test without adding any new response field. **`GET /api/contracts`' response model, `OptionContract`, does not have this luxury** — it only serializes a bare `score: int`, with no breakdown/detail object at all. Task 3's test therefore cannot assert on a response field the way Task 2's does; see Task 3's test design below.

## Design decision, stated explicitly (not left implicit)

Only the **soft** ceiling (`preferred_iv_rank_max`) becomes horizon-aware. The **hard** reject ceiling (`hard_reject.max_iv_rank: 70`) stays a single global safety net across all horizons — 70 sits above every horizon's own `iv_rank_caution_max` (55 for Swing, 65 for Position), so it was never in conflict with the horizon-tuned values; it's a blunt "never buy this rich" backstop, and there's no evidence in the code that it was meant to vary. If this decision turns out to be wrong, it's a one-line change to also inject `max_iv_rank` the same way — Task 2 below leaves a clear extension point.

For Intraday, `iv_rank_caution_max` is `null` in `scoring_rules.yaml` (the horizon has no stock-score-level opinion on IV rank at all). This plan leaves the contract-level `preferred_iv_rank_max` at its global default (55) for Intraday rather than inventing a number — injecting only happens when the horizon config has a real value to offer.

**Cross-reference — read before implementing the companion Intraday-disclosure plan:** The sibling plan `2026-07-31-intraday-options-risk-disclosure.md` has an *optional* Task 2 that would replace `scoring_rules.yaml`'s `horizons.intraday.vol.iv_rank_caution_max: null` with a real number (proposed: `45`). Both plans read/write that exact same config key. If this plan ships first (Intraday stays at the global 55 ceiling, per the design decision above) and the sibling plan's optional Task 2 ships later, Intraday's contract-level `preferred_iv_rank_max` will silently change from the global 55 to 45 the moment that config edit lands — this plan's injection code (`if _iv_ceiling is not None`) has no Intraday-specific carve-out, so it will pick up whatever value that key holds automatically. That's very likely the *right* outcome (a tighter Intraday ceiling), but it's a behavior change that will show up with no code diff in this plan's own files — if you implement both plans, re-verify Intraday's contract scoring after the second one lands rather than assuming this plan's tests still describe Intraday's behavior.

---

## File Structure

- Modify: `backend/app/scoring/contract_validator.py` — add `preferred_iv_rank_max` to the override allow-list.
- Modify: `backend/app/routers/scan.py` — inject the horizon's `iv_rank_caution_max` into `contract_overrides`.
- Modify: `backend/app/routers/contracts.py` — same injection, using the previously-unused `horizon` query parameter.
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx` — send a clean scoring-horizon keyword instead of the display string `context.horizon` currently sends (Task 3, Step 0 — without this the backend fix in Task 3 is a no-op for the real caller).
- Test: `backend/tests/test_contract_validator.py` (extend).
- Test: `backend/tests/test_scan_endpoint.py` (extend).
- Test: `backend/tests/test_contracts_scoring.py` (extend).

---

### Task 1: Recognize `preferred_iv_rank_max` as an override key

**Files:**
- Modify: `backend/app/scoring/contract_validator.py:233-246`
- Test: `backend/tests/test_contract_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_contract_validator.py`:

```python
def test_override_lowers_preferred_iv_rank_max():
    """Caller can override the SOFT preferred ceiling (not just the hard
    max_iv_rank) via the overrides dict -- this is what lets a horizon-aware
    caller tighten or loosen the soft penalty independently of the hard reject.

    Deliberately asserts on soft_flags membership, NOT on breakdown.iv_rank_score
    ordering -- _score_iv_rank()'s in-range/out-of-range branches are
    discontinuous at the ceiling (verified: at iv_rank=60, ceiling=55 scores 17
    via the out-of-range branch, but ceiling=65 scores only 7 via the in-range
    branch -- the *more permissive* ceiling scores *lower*). soft_flags
    membership doesn't have this problem: iv_rank > ceiling always sets the
    flag, iv_rank <= ceiling never does, regardless of which branch's formula
    produced the score."""
    card_default = validate_contract(_base_contract(iv_rank=60), stock_score=70)
    card_overridden = validate_contract(
        _base_contract(iv_rank=60),
        stock_score=70,
        overrides={"preferred_iv_rank_max": 65},
    )
    assert "iv_rank_elevated" in card_default.soft_flags
    assert "iv_rank_elevated" not in card_overridden.soft_flags


def test_override_raises_preferred_iv_rank_max_reflected_in_detail():
    """detail['iv_rank']['preferred_max'] must reflect the override, since the
    API response's contractBreakdown.ivDetail.preferred_max is read straight
    from this field."""
    card = validate_contract(
        _base_contract(iv_rank=60), stock_score=70,
        overrides={"preferred_iv_rank_max": 65},
    )
    assert card.detail["iv_rank"]["preferred_max"] == 65
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_contract_validator.py -k preferred_iv_rank_max -v`
Expected: FAIL — `card_overridden` scores identically to `card_default` (override silently ignored).

- [ ] **Step 3: Write the implementation**

In `backend/app/scoring/contract_validator.py`, inside `validate_contract()`'s override loop (the `if ov:` block, ~lines 233-246), add one branch:

```python
    ov = overrides or {}
    if ov:
        hr = cfg["hard_reject"]
        sr = cfg["soft_rank"]
        for key, val in ov.items():
            if key == "max_bid_ask_spread_pct": hr["max_bid_ask_spread_pct"] = float(val)
            elif key == "max_delta":            hr["max_delta"]              = float(val)
            elif key == "min_delta":            hr["min_delta"]              = float(val)
            elif key == "min_volume":           hr["min_volume"]             = int(val)
            elif key == "min_open_interest":    hr["min_open_interest"]      = int(val)
            elif key == "min_dte":              hr["min_dte"]                = int(val)
            elif key == "max_dte":              hr["max_dte"]                = int(val)
            elif key == "max_iv_rank":          hr["max_iv_rank"]            = float(val)
            elif key == "preferred_dte_min":    sr["preferred_dte_min"]      = int(val)
            elif key == "preferred_dte_max":    sr["preferred_dte_max"]      = int(val)
            elif key == "preferred_iv_rank_max": sr["preferred_iv_rank_max"] = float(val)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_contract_validator.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py
git commit -m "feat(contracts): allow overriding the soft IV-rank ceiling"
```

---

### Task 2: Inject the horizon's IV ceiling in the scan pipeline

**Files:**
- Modify: `backend/app/routers/scan.py:645-653`
- Test: `backend/tests/test_scan_endpoint.py`

- [ ] **Step 1: Write the failing test**

**Do not build the test chain the way an earlier draft of this plan did.** Verified by actually running it: a chain copy-pasted from this file's existing `_MOCK_CHAIN` (missing `open_interest`, hardcoded `"expiry": "2026-06-20"` which is now a past date) gets hard-rejected before its IV rank is ever evaluated (`open_interest_too_low`, `dte_too_short`) — and separately, a scan with no confidence-gate override caps a real `score_stock()` run against synthetic candles to REJECT regardless of the contract.

**Two further landmines, also confirmed by actually running the tests, that a naive `_dte_expiry()`/`_force_passing_stock_score()` fix is not enough to clear on its own:**

1. **A single shared DTE value does not survive both horizons' widened DTE windows.** The Position test passes `hold_min_days=15, hold_max_days=45`, which `resolve_dte_bounds`/`widen_contract_overrides_for_dte` turns into a *widened* hard-reject window of `[46, 100]` (not the raw `dte_window(15,45,2.0)=(30,90)` — `widened_min_dte(30, hold_max_days=45)` clamps up to `45+1=46`). A contract at `dte=35` (which comfortably survives the Swing test's widened `[16, 40]` window) is hard-rejected as `dte_too_short` under the Position window. The two tests need different DTE values, not one shared fixture value.
2. **`_enter_mock_patches` does not fully isolate the scan from real backend state.** `run_scan` pre-fetches `bars_map` via a *locally-imported* `app.services.historical_store.get_bars` (imported fresh inside the endpoint function, not at `scan.py` module scope) and pre-fetches `price_map` via `fetch_quotes` (imported at `scan.py` module scope) — **neither is patched by `_enter_mock_patches`**, which only covers `fetch_price_async`/`fetch_candles_async`/`fetch_option_chain_async`/`fetch_company_name_async`/`fetch_fundamentals_calendar`. If this repo's dev database has real ingested OHLCV history for the test symbol (confirmed true in this repo's environment), `bars_map` silently comes back with *real* data instead of `_MOCK_CANDLES`, and `_process_symbol` takes the `db_bars is not None` branch (`scan.py:459-467`), which never calls the mocked `fetch_candles_async`/`fetch_price_async` at all — the test then runs against whatever AAPL's real price/candles happen to be, not the fixture. Both pre-fetches must be explicitly patched to force the empty/mocked path.

Use `test_scan_endpoint.py`'s existing `_dte_expiry()` and `_force_passing_stock_score()` helpers (already defined in this file, already used by other tests for exactly this class of problem), a per-call `dte` parameter on the new chain fixture, and two additional patches to close the DB-leak:

```python
def _iv_ceiling_test_chain(iv_rank: float = 60, dte: int = 35) -> list[dict]:
    """A single contract that clears every contract_rules.yaml hard-reject
    check regardless of when this test runs -- iv_rank=60 sits strictly
    between Swing's ceiling (55) and Position's ceiling (65), so the two
    horizons disagree on whether it's 'elevated.' `dte` is a parameter, not a
    constant, because Swing's and Position's widened DTE hard-reject windows
    don't overlap at the same value (see Step 1's landmine #1 above)."""
    return [{
        "strike": 190, "expiry": _dte_expiry(dte), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": iv_rank, "dte": dte,
        "right": "C", "volume": 500, "open_interest": 2000,
    }]


def _no_db_leak():
    """Force the mocked candles/price fixtures to actually be used. Without
    this, run_scan's DB-backed bars_map/price_map pre-fetch (scan.py:1089,
    1095 -- neither covered by _enter_mock_patches) can silently return real
    historical data for a symbol this repo's dev database already has
    ingested, bypassing _MOCK_CANDLES/price entirely."""
    return (
        patch("app.routers.scan.fetch_quotes", return_value={}),
        patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])),
    )


def test_scan_position_horizon_uses_position_iv_ceiling(client):
    """A Position scan's contract-level preferred IV ceiling must be 65 (its own
    horizon's iv_rank_caution_max), not the Swing-level 55 applied everywhere
    today."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES,
                             chain=_iv_ceiling_test_chain(dte=60),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": 15, "hold_max_days": 45, "overrides": {},
        })
    candidates = r.json()["candidates"]
    assert candidates, "expected AAPL to score as a candidate for this fixture"
    iv_detail = candidates[0]["contractBreakdown"]["ivDetail"]
    assert iv_detail["preferred_max"] == 65


def test_scan_swing_horizon_keeps_swing_iv_ceiling(client):
    """Regression guard: Swing must still use 55, unaffected by the Position fix."""
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES,
                             chain=_iv_ceiling_test_chain(dte=35),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "hold_min_days": 5, "hold_max_days": 15, "overrides": {},
        })
    candidates = r.json()["candidates"]
    assert candidates, "expected AAPL to score as a candidate for this fixture"
    iv_detail = candidates[0]["contractBreakdown"]["ivDetail"]
    assert iv_detail["preferred_max"] == 55
```

`_dte_expiry` and `_force_passing_stock_score` are both already defined in `test_scan_endpoint.py` (see the companion plan `2026-07-31-wire-reward-risk-overrides.md`'s Task 2, which relies on the same two helpers) — no new imports needed beyond `AsyncMock`, which the file already imports at its top (`from unittest.mock import patch, AsyncMock, MagicMock`). If that companion plan's Task 2 hasn't been implemented yet, `_force_passing_stock_score` still already exists in the file independent of that plan (it backs `test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends`), so this test doesn't actually depend on the companion plan landing first. **The companion plan's Task 2 tests have this exact same DB-leak problem and need the identical `_no_db_leak()` fix — apply both plans' Task 2 fixes together, or add `_no_db_leak()` once and have both plans' tests use it, rather than fixing it twice independently.**

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_scan_endpoint.py -k iv_ceiling -v`
Expected: `test_scan_position_horizon_uses_position_iv_ceiling` FAILS — `preferred_max` is `55` (the untouched global default) instead of `65`. `test_scan_swing_horizon_keeps_swing_iv_ceiling` PASSES already (it's the pre-existing behavior, kept as a regression guard) — if either fails for a different reason (empty `candidates`, wrong `stock_price`, an import error), the fixture/patching is still broken; fix that before continuing rather than assuming the failure proves the bug.

- [ ] **Step 3: Write the implementation**

In `backend/app/routers/scan.py`, find the block (around line 641-653 — quoted here in full, including the existing comments, so a literal string match succeeds):

```python
    # DTE bounds are derived from the holding horizon and apply to contracts only,
    # via a separate dict — kept apart from `overrides` for clarity, not because
    # score_stock() would misinterpret these keys (its override handling is an
    # allow-list that already ignores unrecognised keys).
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        # Hard-reject AND soft-score preferred-band bounds are both widened by
        # the same DTE_WINDOW_TOLERANCE_DAYS -- see widen_contract_overrides_for_dte's
        # docstring for why the two must move together, not just the hard bound.
        contract_overrides = widen_contract_overrides_for_dte(contract_overrides, lo, hi, hold_max_days)
    scored = [(validate_contract(c, card.score, overrides=contract_overrides or None), c)
              for c in augmented]
```

and change it to (only the two new lines before `scored = [...]` are additions — everything above them, including the comments, stays exactly as-is):

```python
    # DTE bounds are derived from the holding horizon and apply to contracts only,
    # via a separate dict — kept apart from `overrides` for clarity, not because
    # score_stock() would misinterpret these keys (its override handling is an
    # allow-list that already ignores unrecognised keys).
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        # Hard-reject AND soft-score preferred-band bounds are both widened by
        # the same DTE_WINDOW_TOLERANCE_DAYS -- see widen_contract_overrides_for_dte's
        # docstring for why the two must move together, not just the hard bound.
        contract_overrides = widen_contract_overrides_for_dte(contract_overrides, lo, hi, hold_max_days)
    # Horizon-aware soft IV-rank ceiling: contract_rules.yaml's
    # preferred_iv_rank_max is a single global number, but scoring_rules.yaml's
    # own vol rule treats a materially higher IV rank as acceptable for
    # Position than for Swing (65 vs 55; null for Intraday, which has no
    # stock-score-level opinion on IV rank at all). Reuse that same
    # horizon-tuned ceiling for the contract-level soft penalty instead of
    # letting the two disagree.
    _vol_cfg = _load_scoring_cfg().get("horizons", {}).get(horizon.lower(), {}).get("vol", {})
    _iv_ceiling = _vol_cfg.get("iv_rank_caution_max")
    if _iv_ceiling is not None:
        contract_overrides["preferred_iv_rank_max"] = float(_iv_ceiling)
    scored = [(validate_contract(c, card.score, overrides=contract_overrides or None), c)
              for c in augmented]
```

`_load_scoring_cfg` is already imported at module scope (`from app.services.config_loader import load_scoring_cfg as _load_scoring_cfg`, used for `regime_gate`/`regime` above) — no new import needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_scan_endpoint.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_scan_endpoint.py
git commit -m "fix(scan): use the horizon's own IV-rank ceiling for contract scoring"
```

---

### Task 3: Wire the same fix into `GET /api/contracts` (Step 6's contract browser)

**Important — the endpoint's response never exposes what we need to assert on directly.** `GET /api/contracts` returns `OptionContract` (`backend/app/schemas/__init__.py`), which only carries a bare `score: int` — it does **not** serialize `ContractScoreBreakdown`/`IvRankDetail` the way the scan endpoint's `TradeCardData.contractBreakdown.ivDetail.preferred_max` does. Comparing raw `score` between two horizons is also unreliable on its own: `_score_iv_rank()`'s two branches (`backend/app/scoring/contract_validator.py:191-205`) are discontinuous at the ceiling — an in-range value close to a *wide* ceiling can score *lower* than an out-of-range value just past a *narrow* one (verified directly: at `iv_rank=60`, Swing's ceiling of 55 puts it in the "just past the ceiling" branch scoring `17`, while Position's ceiling of 65 puts it in the "close to the ceiling" in-range branch scoring `7` — the *opposite* of what "Position is more tolerant" would suggest). So this task's test asserts on what `validate_contract` was actually **called with**, not on the derived score, which is the only way to verify the injected ceiling directly and robustly regardless of the scoring formula's shape.

**Files:**
- Modify: `backend/app/routers/contracts.py`
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx:94` — the endpoint fix alone is not enough; see Step 0 below.
- Test: `backend/tests/test_contracts_scoring.py`

- [ ] **Step 0: Fix the real caller first — it doesn't send a bare horizon keyword today**

Verified: `frontend/app/(frame)/screener/step-6-contracts/page.tsx:94` calls `api.getContracts(..., { ..., horizon: context?.horizon ?? 'swing', ... })`. `context.horizon` is populated by `horizonDisplayString()` (`frontend/lib/horizonPresets.ts:83-85`) as a string like `"Swing (5–15d)"`, not a bare `"swing"`/`"position"`/`"intraday"` keyword. `"swing (5–15d)".lower()` will never match any key in `scoring_rules.yaml`'s `horizons` dict, so without this step, the backend fix below is a silent no-op for the one caller that actually matters — Step 6's contract browser would keep using the untouched global 55 ceiling forever, regardless of the backend changes in this task.

`ScanContext` already carries the clean `horizonPreset: HorizonKey` field (`frontend/lib/scanStore.ts:41`), and `RunScanButton` (`frontend/components/organisms/RunScanButton/index.tsx:103-111`) already derives a clean scoring horizon from it the same way this page needs to:

```typescript
const horizon: string = presetByKey(resolveParamsHorizon(presetKey, holdMax)).scoringHorizon;
```

In `frontend/app/(frame)/screener/step-6-contracts/page.tsx`, add `presetByKey` and `resolveParamsHorizon` to the existing import (currently `import { sanitizeHoldDays } from '@/lib/horizonPresets';`):

```typescript
import { sanitizeHoldDays, presetByKey, resolveParamsHorizon } from '@/lib/horizonPresets';
```

Then, inside `loadContracts` (around line 85, before the `Promise.all(...)` call), derive the clean horizon and use it instead of the raw display string:

```typescript
    const right = (context?.direction ?? 'Bullish') === 'Bullish' ? 'C' : 'P';
    const presetKey = context?.horizonPreset ?? 'Swing';
    const holdMaxForScoring = context?.holdMax ?? presetByKey('Swing').holdMax;
    const scoringHorizon = presetByKey(resolveParamsHorizon(presetKey, holdMaxForScoring)).scoringHorizon;
    const hold = context?.holdMin != null && context?.holdMax != null
      ? sanitizeHoldDays(context.holdMin, context.holdMax)
      : undefined;
    try {
      const results = await Promise.all(
        candidates.map((c) => api.getContracts(c.symbol, right, {
          stock_score:   stockScoreBySymbol[c.symbol] ?? 70,
          direction:     context?.direction ?? 'Bullish',
          horizon:       scoringHorizon,
          limit:         maxContractsPerChain,
          max_price:     maxContractPrice,
          hold_min_days: hold?.hold_min_days,
          hold_max_days: hold?.hold_max_days,
        }, signal))
      );
```

(Only the `horizon:` line's value changes — from `context?.horizon ?? 'swing'` to `scoringHorizon` — everything else in this block is unchanged; the new `presetKey`/`holdMaxForScoring`/`scoringHorizon` consts are inserted before the existing `hold` const.)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_contracts_scoring.py`. Reuse the file's existing `_make_raw_contract` helper. This test patches `validate_contract` itself (imported into `app.routers.contracts`'s namespace) to capture the `overrides` dict each call receives, then delegates to the real function so scoring still happens normally — this is what makes the assertion robust against `_score_iv_rank`'s branch discontinuity:

```python
def test_contracts_endpoint_position_horizon_widens_iv_ceiling():
    """GET /api/contracts declares a `horizon` query param that's currently
    unused -- this pins that it now injects the horizon-aware IV ceiling into
    the overrides dict validate_contract() is called with. Asserting on the
    overrides passed in (rather than the resulting score) sidesteps
    _score_iv_rank's in-range/out-of-range branch discontinuity, which makes
    raw score comparisons between two different ceilings unreliable."""
    from app.scoring.contract_validator import validate_contract as _real_validate_contract

    raw = [_make_raw_contract(iv=0.60)]
    captured: list[dict | None] = []

    def _capture(contract, stock_score, overrides=None):
        captured.append(overrides)
        return _real_validate_contract(contract, stock_score, overrides=overrides)

    app = FastAPI()
    app.include_router(contracts_router)

    async def _get(horizon: str):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.get("/api/contracts", params={
                "symbol": "TSLA", "right": "C", "stock_score": 70, "horizon": horizon,
            })

    with patch("app.routers.contracts.fetch_option_chain", return_value=raw), \
         patch("app.routers.contracts.fetch_price", return_value=185.0), \
         patch("app.routers.contracts.validate_contract", side_effect=_capture):
        import asyncio
        r_position = asyncio.run(_get("position"))
        captured_position = list(captured)
        captured.clear()
        r_swing = asyncio.run(_get("swing"))
        captured_swing = list(captured)

    assert r_position.status_code == 200
    assert r_swing.status_code == 200
    assert captured_position and captured_position[0] is not None
    assert captured_position[0]["preferred_iv_rank_max"] == 65
    assert captured_swing and captured_swing[0] is not None
    assert captured_swing[0]["preferred_iv_rank_max"] == 55
```

If the file's existing integration tests build the client/app differently (e.g. via a shared fixture rather than inline `FastAPI()`/`ASGITransport`), match that existing pattern exactly instead of the inline version shown here — read the file's current top-of-file integration test before finalizing this step.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_contracts_scoring.py -k position_horizon_widens -v`
Expected: FAIL — `captured_position[0]` is either `None` or a dict without a `preferred_iv_rank_max` key (the horizon param is currently ignored entirely).

- [ ] **Step 3: Write the implementation**

In `backend/app/routers/contracts.py`, add the import:

```python
from app.services.config_loader import load_scoring_cfg as _load_scoring_cfg
```

Change the `get_contracts` body (currently lines 51-72) from:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None:
        if hold_max_days < hold_min_days:
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["query", "hold_max_days"],
                    "msg": "Value error, hold_max_days must be >= hold_min_days",
                    "type": "value_error",
                }],
            )
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            contract_overrides = widen_contract_overrides_for_dte({}, dte_bounds[0], dte_bounds[1], hold_max_days)
```

to:

```python
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict = {}
    if hold_min_days is not None and hold_max_days is not None:
        if hold_max_days < hold_min_days:
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["query", "hold_max_days"],
                    "msg": "Value error, hold_max_days must be >= hold_min_days",
                    "type": "value_error",
                }],
            )
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            contract_overrides = widen_contract_overrides_for_dte({}, dte_bounds[0], dte_bounds[1], hold_max_days)

    # Horizon-aware soft IV-rank ceiling -- same mechanism and same source
    # (scoring_rules.yaml horizons.<horizon>.vol.iv_rank_caution_max) as
    # app.routers.scan's contract scoring, so Step 6's contract browser agrees
    # with the scan that populated it instead of using a single global ceiling
    # regardless of which horizon the scan was run under.
    _vol_cfg = _load_scoring_cfg().get("horizons", {}).get(horizon.lower(), {}).get("vol", {})
    _iv_ceiling = _vol_cfg.get("iv_rank_caution_max")
    if _iv_ceiling is not None:
        contract_overrides["preferred_iv_rank_max"] = float(_iv_ceiling)
```

Then update the call site (currently `score_card = validate_contract(augmented, stock_score, overrides=contract_overrides)`) to match the new "always a dict, possibly empty" shape used by `scan.py`:

```python
        score_card = validate_contract(augmented, stock_score, overrides=contract_overrides or None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_contracts_scoring.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/contracts.py backend/tests/test_contracts_scoring.py "frontend/app/(frame)/screener/step-6-contracts/page.tsx"
git commit -m "fix(contracts): wire the previously-unused horizon param to the IV ceiling"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 makes the primitive overridable; Task 2 fixes the main scan path (the one the original finding was about); Task 3 fixes the second, previously-unnoticed instance of the exact same gap (`GET /api/contracts`' dead `horizon` parameter) discovered while tracing callers — leaving it unfixed would mean Step 6's contract browser and the scan that fed it disagree on IV scoring for the same symbol/horizon. Task 3 also fixes a *third*, deeper instance of the same class of bug found during an adversarial pass: the endpoint's one real caller (`step-6-contracts/page.tsx`) sends a human-readable display string (`"Swing (5–15d)"`), not a bare horizon keyword, so the router-level fix alone would have been a silent no-op — Task 3 Step 0 fixes the caller first.
- **Placeholder scan:** No TBD/placeholder code.
- **Type consistency:** `preferred_iv_rank_max` is the override key name used identically in `contract_validator.py`, `scan.py`, and `contracts.py`. `_vol_cfg`/`_iv_ceiling` extraction logic is identical in both router files, deliberately duplicated rather than factored into a shared helper (each file already has its own inline pattern for `contract_overrides` construction — see `dte_window.py`'s `widen_contract_overrides_for_dte` docstring for why the DTE version was pulled into a shared function while this two-line IV lookup is small enough not to need the same treatment).
- **Explicit non-goal:** `hard_reject.max_iv_rank` (currently 70, global) is deliberately left untouched — see "Design decision" above.
- **Test-design correction (post-audit):** Task 3's test originally compared raw `score` values between two horizons. `_score_iv_rank()`'s in-range/out-of-range branches are discontinuous at the ceiling, which made that comparison direction-dependent on the specific IV rank chosen rather than a reliable signal of "which ceiling is more permissive." The test now asserts on the `overrides` dict `validate_contract` was actually called with (via a `side_effect` capture), which is exact and formula-independent.
- **Cross-plan dependency (post-audit):** see "Cross-reference" note under "Design decision" above — this plan's Intraday behavior is not fully independent of the sibling `intraday-options-risk-disclosure.md` plan's optional Task 2.
- **Test-fixture correction (round 2, verified by actually executing the tests against the real repo):** Task 2's tests originally used a chain copy-pasted from `test_scan_endpoint.py`'s existing `_MOCK_CHAIN` with no confidence-gate override. Run for real, both failed before ever reaching the IV-ceiling logic under test — one from the missing `open_interest` field plus a now-past hardcoded expiry date (both trip unrelated hard-reject rules), the other from the default confidence gate capping a real `score_stock()` run to REJECT regardless of contract validity. The tests now build a self-contained, always-valid chain via the file's existing `_dte_expiry()` helper and isolate the scoring pipeline via its existing `_force_passing_stock_score()` helper — the same fix applied to the companion R/R-overrides plan's Task 2, for the identical underlying reason.
- **Further corrections (round 3, verified by actually executing the tests a second time):** (1) the Position test's `dte=35` fails under the Position hold's *widened* DTE hard-reject window (`[46, 100]` once `hold_min_days=15/hold_max_days=45` widen it — not the raw `dte_window(15,45,2.0)=(30,90)`), even though the identical `dte=35` survives the Swing hold's widened window (`[16, 40]`). The chain fixture now takes `dte` as a parameter, and the Position test passes `dte=60`. (2) the same DB-leak found in the companion R/R-overrides plan applies here too — `_enter_mock_patches` doesn't cover `scan.py`'s batch `fetch_quotes`/`historical_store.get_bars` pre-fetch, so a dev database with real ingested history silently overrides the fixture. Added the same `_no_db_leak()` helper. (3) Task 1's own test (`test_override_lowers_preferred_iv_rank_max`) had the identical `_score_iv_rank` discontinuity bug that Task 3 was already designed around — `iv_rank=60` scores *lower* (7) under the more permissive ceiling (65) than under the stricter one (17 under 55), so the score-comparison assertion was backwards. Removed it; the two `soft_flags` membership assertions (which are monotonic and unaffected by the discontinuity) already fully prove the override works.
