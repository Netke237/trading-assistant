# LLM Context — Backend Tests for WS-24 & WS-25 (Workstream 30)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates three new test files. It does not modify any existing file.

**Goal:**
Add unit tests for `assess_entry()` and `estimate_rr()` (WS-24), and integration tests for `POST /api/scan` (WS-25). The scan endpoint uses `yfinance` for real market data — tests must mock those calls to stay network-independent.

**What NOT to touch:**
- Any file under `frontend/`
- Any existing backend file — including existing tests
- `backend/app/scoring/entry_quality.py` — read-only
- `backend/app/scoring/reward_risk.py` — read-only
- `backend/app/routers/scan.py` — read-only
- `backend/tests/conftest.py` — read-only (reuse its `client` fixture as-is)

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/tests/test_entry_quality.py` | **Create** | Unit tests for `assess_entry()` |
| `backend/tests/test_reward_risk.py` | **Create** | Unit tests for `estimate_rr()` |
| `backend/tests/test_scan_endpoint.py` | **Create** | Route tests for `POST /api/scan` |

---

## Section 3 — Read-only references

### `backend/tests/conftest.py` — do not modify, just use its fixture

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)
```

Use `client` as a parameter in any test that calls HTTP endpoints.

### Test style (match existing files exactly)

- Plain functions, no classes.
- One assertion concept per test function.
- Use the `client` fixture only in HTTP tests — pure unit tests import and call functions directly.
- No `pytest.mark` decorators needed.

### Module signatures (verified from source — do not re-read the files)

```python
# entry_quality.py
class EntryConfig:
    spread_tolerance_pct: float = 0.10   # CAUTION if spread > 1×, REJECT if > 3×
    max_slippage_pct:     float = 0.03   # max_fill = mid * (1 + 0.03)
    min_premium:          float = 0.10   # REJECT if mid < this

class EntryAssessment:
    limit_price:    float
    max_fill:       float
    order_type:     Literal["Limit", "Market"]   # always "Limit" in MVP
    quality_status: Literal["PASS", "CAUTION", "REJECT"]
    quality_reasons: list[str]

def assess_entry(bid, ask, mid, config=None) -> EntryAssessment: ...

# reward_risk.py
class RrResult:
    rr_ratio:               float
    model_used:             Literal["Heston repriced", "Delta approximation"]
    estimated_exit_premium: float

def estimate_rr(stock_price, target_price, invalidation_price, strike,
                expiry_years, current_premium, is_call,
                r=0.05, heston_params=None, sigma_fallback=0.25) -> RrResult: ...

# heston.py — needed for the Heston path test
class HestonParams:
    v0: float; kappa: float; theta: float; sigma_v: float; rho: float
```

### `assess_entry` logic summary (for deriving expected values)

1. `spread_pct = (ask - bid) / mid` if `mid > 0`, else `1.0`
2. REJECT `"premium too low"` if `mid < config.min_premium`
3. REJECT `"wide spread"` if `spread_pct > config.spread_tolerance_pct * 3`  (i.e. > 0.30)
4. CAUTION `"elevated spread"` elif `spread_pct > config.spread_tolerance_pct`  (i.e. > 0.10)
5. Worst status wins: REJECT > CAUTION > PASS

### `estimate_rr` logic summary

**Delta approximation** (when `heston_params is None`):
- Call: `delta = 0.5` if `target_price > strike`, else `0.3`
- Put:  `delta = 0.5` if `target_price < strike`, else `0.3`
- `exit_premium = current_premium + delta * abs(target_price - stock_price)`
- `exit_premium = max(exit_premium, 0.01)` — floor
- `reward = exit_premium - current_premium`
- If `reward <= 0` or `risk (= current_premium) <= 0`: return `rr_ratio=0.0`
- `rr_ratio = round(reward / risk, 2)`

**Heston path** (when `heston_params is not None`):
- `dte_at_target = max(expiry_years * 0.5, 7/365)`
- `exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)`
- Same floor and ratio logic as above

### Scan endpoint — why mocking is required

`backend/app/data/market.py` uses `yfinance` for live data.
In CI / offline environments `fetch_price` returns `None` and `fetch_candles` returns `[]`,
causing every symbol to land in `rejected`. Tests that mock those functions get
deterministic, network-free results.

Mock patch targets (these are the names as imported inside `scan.py`):
```python
"app.routers.scan.fetch_price"
"app.routers.scan.fetch_candles"
"app.routers.scan.fetch_option_chain"
```

---

## Section 4 — Complete file implementations

### 4.1 `backend/tests/test_entry_quality.py`

```python
"""Unit tests for app.scoring.entry_quality.assess_entry()."""

from app.scoring.entry_quality import assess_entry, EntryConfig


# ── PASS ─────────────────────────────────────────────────────────────────────

def test_pass_normal_spread():
    """spread_pct == tolerance boundary (0.10) is not > 0.10 → PASS."""
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.quality_status == "PASS"
    assert ea.quality_reasons == []


def test_pass_limit_price():
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.limit_price == 2.00


def test_pass_max_fill():
    """max_fill = round(mid * 1.03, 2)."""
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.max_fill == 2.06


def test_pass_order_type_always_limit():
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.order_type == "Limit"


# ── CAUTION ──────────────────────────────────────────────────────────────────

def test_caution_elevated_spread():
    """spread_pct = 0.25 — above 1× tolerance (0.10), below 3× (0.30) → CAUTION."""
    ea = assess_entry(bid=1.75, ask=2.25, mid=2.00)
    assert ea.quality_status == "CAUTION"
    assert "elevated spread" in ea.quality_reasons


def test_caution_does_not_set_wide_spread():
    ea = assess_entry(bid=1.75, ask=2.25, mid=2.00)
    assert "wide spread" not in ea.quality_reasons


# ── REJECT ───────────────────────────────────────────────────────────────────

def test_reject_wide_spread():
    """spread_pct = 1.50 — above 3× tolerance → REJECT."""
    ea = assess_entry(bid=0.50, ask=3.50, mid=2.00)
    assert ea.quality_status == "REJECT"
    assert "wide spread" in ea.quality_reasons


def test_reject_premium_too_low():
    """mid = 0.05 < min_premium 0.10 → REJECT."""
    ea = assess_entry(bid=0.04, ask=0.06, mid=0.05)
    assert ea.quality_status == "REJECT"
    assert "premium too low" in ea.quality_reasons


def test_reject_both_reasons_present():
    """mid too low AND wide spread → both reasons in list."""
    ea = assess_entry(bid=0.04, ask=0.06, mid=0.05)
    assert "premium too low" in ea.quality_reasons
    assert "wide spread" in ea.quality_reasons


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_zero_mid_falls_back_to_reject():
    """mid = 0 → spread_pct fallback = 1.0 → wide spread + premium too low."""
    ea = assess_entry(bid=0.00, ask=0.00, mid=0.00)
    assert ea.quality_status == "REJECT"


def test_custom_config_tighter_tolerance():
    """With spread_tolerance_pct=0.05, a 10% spread (previously PASS) becomes CAUTION."""
    cfg = EntryConfig(spread_tolerance_pct=0.05)
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, config=cfg)
    assert ea.quality_status == "CAUTION"
    assert "elevated spread" in ea.quality_reasons


def test_custom_config_max_fill_uses_slippage():
    """max_fill uses config.max_slippage_pct, not the default."""
    cfg = EntryConfig(max_slippage_pct=0.10)
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, config=cfg)
    assert ea.max_fill == round(2.00 * 1.10, 2)


def test_large_premium_clears_all_checks():
    ea = assess_entry(bid=9.80, ask=10.20, mid=10.00)
    assert ea.quality_status == "PASS"
    assert ea.limit_price == 10.00
```

---

### 4.2 `backend/tests/test_reward_risk.py`

```python
"""Unit tests for app.scoring.reward_risk.estimate_rr()."""

from app.scoring.reward_risk import estimate_rr
from app.models.heston import HestonParams


# ── Delta approximation — call ────────────────────────────────────────────────

def test_delta_approx_call_above_strike():
    """Call, target(200) > strike(190) → delta=0.5, rr=3.0."""
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 3.0
    assert rr.estimated_exit_premium == 10.0


def test_delta_approx_call_below_strike():
    """Call, target(188) < strike(190) → delta=0.3."""
    rr = estimate_rr(
        stock_price=185, target_price=188, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=1.00, is_call=True,
    )
    assert rr.model_used == "Delta approximation"
    # exit = 1.00 + 0.3 * 3 = 1.90 → reward = 0.90 → rr = 0.90
    assert rr.rr_ratio == 0.90


# ── Delta approximation — put ─────────────────────────────────────────────────

def test_delta_approx_put_below_strike():
    """Put, target(170) < strike(180) → delta=0.5, rr=3.75."""
    rr = estimate_rr(
        stock_price=185, target_price=170, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=2.00, is_call=False,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 3.75
    assert rr.estimated_exit_premium == 9.50


def test_delta_approx_put_above_strike():
    """Put, target(185) > strike(180) → delta=0.3."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=1.00, is_call=False,
    )
    # price_move = 0 → exit = 1.00 → reward = 0 → rr_ratio = 0.0
    assert rr.rr_ratio == 0.0


# ── Zero / degenerate cases ───────────────────────────────────────────────────

def test_zero_price_movement_returns_zero_ratio():
    """target == stock_price → price_move=0 → reward=0 → rr_ratio=0.0."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.rr_ratio == 0.0


def test_zero_premium_returns_zero_ratio():
    """current_premium=0 → risk=0 → rr_ratio=0.0."""
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=0.0, is_call=True,
    )
    assert rr.rr_ratio == 0.0


def test_exit_premium_floored_at_0_01():
    """When computed exit_premium would be <= 0, floor kicks in."""
    # Very short expiry, deep OTM Heston → may return near-zero
    # Use delta path with negative movement to force floor
    rr = estimate_rr(
        stock_price=185, target_price=100, invalidation_price=175,
        strike=300, expiry_years=1/365, current_premium=0.01, is_call=True,
    )
    assert rr.estimated_exit_premium >= 0.01


# ── Heston path ───────────────────────────────────────────────────────────────

def test_heston_path_uses_correct_model_label():
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "Heston repriced"


def test_heston_path_returns_valid_ratio():
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert isinstance(rr.rr_ratio, float)
    assert rr.estimated_exit_premium > 0


def test_heston_path_not_used_when_params_none():
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=None,
    )
    assert rr.model_used == "Delta approximation"
```

---

### 4.3 `backend/tests/test_scan_endpoint.py`

```python
"""Route tests for POST /api/scan.

market.py uses yfinance for live data. All tests that exercise the pipeline
mock fetch_price, fetch_candles, and fetch_option_chain so they run
network-free and deterministically.
"""

import re
from unittest.mock import patch

# ── Shape & contract ──────────────────────────────────────────────────────────

def test_scan_returns_200(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200


def test_scan_response_has_required_fields(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert "scan_id"    in data
    assert "timestamp"  in data
    assert "candidates" in data
    assert "rejected"   in data


def test_scan_id_format(client):
    """scan_id must match REC-YYYYMMDD-XXXXXXXX."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    scan_id = r.json()["scan_id"]
    assert re.match(r"REC-\d{8}-[A-F0-9]{8}", scan_id), f"Unexpected scan_id: {scan_id}"


def test_scan_empty_universe_returns_empty_lists(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert data["candidates"] == []
    assert data["rejected"]   == []


def test_scan_invalid_direction_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Sideways", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_invalid_horizon_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Daily", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_missing_body_returns_422(client):
    r = client.post("/api/scan")
    assert r.status_code == 422


# ── No market data → symbol rejected ─────────────────────────────────────────

def test_scan_no_market_data_rejects_symbol(client):
    """When fetch_price returns None the symbol must appear in rejected, not candidates."""
    with patch("app.routers.scan.fetch_price",        return_value=None), \
         patch("app.routers.scan.fetch_candles",       return_value=[]), \
         patch("app.routers.scan.fetch_option_chain",  return_value=[]):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    rejected_symbols = [item["symbol"] for item in data["rejected"]]
    assert "AAPL" in rejected_symbols
    assert all(c["symbol"] != "AAPL" for c in data["candidates"])


# ── With mocked market data — pipeline runs end-to-end ───────────────────────

_MOCK_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]

_MOCK_CHAIN = [
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
        "right": "C", "volume": 500,
    }
]


def test_scan_with_mock_data_processes_symbol(client):
    """With valid mock data the symbol appears in candidates or rejected — never missing."""
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_CHAIN):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    all_symbols = (
        [c["symbol"] for c in data["candidates"]] +
        [rej["symbol"] for rej in data["rejected"]]
    )
    assert "AAPL" in all_symbols


def test_scan_with_mock_data_candidate_shape(client):
    """If AAPL is scored as a candidate its TradeCardData shape must be valid."""
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_CHAIN):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    for c in data["candidates"]:
        assert "symbol"       in c
        assert "stockScore"   in c
        assert "rrRatio"      in c
        assert "finalStatus"  in c
        assert c["direction"] == "Bullish"


def test_scan_multiple_symbols_all_accounted_for(client):
    """Every symbol in universe must appear in candidates OR rejected — none silently dropped."""
    universe = ["AAPL", "MSFT", "NVDA"]
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_CHAIN):
        r = client.post("/api/scan", json={
            "universe": universe, "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    processed = (
        {c["symbol"] for c in data["candidates"]} |
        {rej["symbol"] for rej in data["rejected"]}
    )
    assert processed == set(universe)
```

---

## Section 5 — Task spec

### Acceptance criteria

1. `pytest backend/tests/test_entry_quality.py -v` — all tests pass.
2. `pytest backend/tests/test_reward_risk.py -v` — all tests pass.
3. `pytest backend/tests/test_scan_endpoint.py -v` — all tests pass.
4. `pytest backend/tests/ -v` — full suite passes (no regressions in existing tests).

### Verify

```bash
cd backend
pytest tests/test_entry_quality.py tests/test_reward_risk.py tests/test_scan_endpoint.py -v
# Then run full suite:
pytest tests/ -v
```

---

## Section 6 — Hard rules

1. Do NOT modify any existing file — only create the three new test files.
2. Do NOT touch any frontend file.
3. Copy the implementations from Section 4 exactly — do not paraphrase or restructure.
4. Mock targets are `"app.routers.scan.fetch_price"`, `"app.routers.scan.fetch_candles"`, `"app.routers.scan.fetch_option_chain"` — these are the names as imported inside `scan.py`. Using the wrong module path will silently fail to mock.
5. Do not assert specific `rr_ratio` or `estimated_exit_premium` values in the Heston path tests — Heston output depends on numerical integration and may shift. Only assert type and sign.
6. All tests must pass without a live network connection.

---

## Section 7 — Dev workflow

```bash
cd backend
pytest tests/test_entry_quality.py tests/test_reward_risk.py tests/test_scan_endpoint.py -v
```

---

## Section 8 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-30-backend-tests.

Read `llm-contexts/30-backend-tests-ws24-25.md` fully before writing any code.
It is your single source of truth.

You are adding backend tests for the entry quality, reward-risk, and scan
pipeline modules of the Bamendjou options screener (FastAPI / Python 3.11 / pytest).

Your owned files:
  - backend/tests/test_entry_quality.py   (CREATE)
  - backend/tests/test_reward_risk.py     (CREATE)
  - backend/tests/test_scan_endpoint.py   (CREATE)

Do not modify any existing file.
Copy the complete implementations from Section 4 exactly.
Run the verification in Section 5 after creating all three files.
Commit after all tests pass.
```
