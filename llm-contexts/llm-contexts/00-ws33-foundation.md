# WS-33 — Foundation Fixes
## LLM Handover Context Document

> **Before writing any code:** Read this file fully. It is your single source of truth.
> Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement.

---

## Mission

Fix five small but critical issues that block all other workstreams:
1. Backend rejects `"Intraday"` horizon with a 422 error
2. Three magic numbers in `entry_quality.py` violate the config-discipline rule (FR-45)
3. Three magic numbers in `scan.py` violate the same rule
4. `test_portfolio_rules.py` tests its own helper functions instead of the real `check_position_risk()` — providing false test coverage for FR-42
5. `audit.ts` localStorage log has no size cap and will silently fail at ~5–10 MB

**Conflict class: Medium.** You touch `backend/app/schemas/__init__.py`, two backend source files, two YAML config files, one backend test file, and one frontend utility. You do not touch any Zustand store interfaces, any API endpoint responses, or any frontend pages.

**Do not touch any file not in the Owned Files table below.**

---

## Owned Files

| File path | Status | Purpose |
|---|---|---|
| `backend/app/schemas/__init__.py` | Modify | Add `'Intraday'` to `Horizon` literal (line 16) |
| `backend/config/scoring_rules.yaml` | Modify | Add entry-quality threshold section |
| `backend/config/risk_rules.yaml` | Modify | Add reward-risk and premium-stop defaults section |
| `backend/app/scoring/entry_quality.py` | Modify | Read thresholds from YAML instead of hardcoding |
| `backend/app/routers/scan.py` | Modify | Read 3 magic-number percentages from `risk_rules.yaml` |
| `backend/tests/test_portfolio_rules.py` | Modify | Replace helper-only tests with tests of real `check_position_risk()` |
| `frontend/lib/audit.ts` | Modify | Add 500-entry FIFO cap + `QuotaExceededError` recovery |

---

## Read-Only References

| File | Why you need it |
|---|---|
| `backend/app/scoring/stock_scorer.py` lines 39–54 | Exact `_load_config()` pattern to replicate in `entry_quality.py` |
| `backend/app/services/portfolio_risk.py` | Full `check_position_risk()` signature and `PortfolioPosition` dataclass your tests must import |
| `backend/config/contract_rules.yaml` | YAML structure pattern to follow |

---

## Task 1 — Fix `Horizon` literal (5 min)

**File:** `backend/app/schemas/__init__.py` line 16

**Current code:**
```python
Horizon = Literal['Swing', 'Position']
```

**Change to:**
```python
Horizon = Literal['Intraday', 'Swing', 'Position']
```

No other changes in this file.

**Verify:**
```bash
cd backend
python -c "from app.schemas import Horizon; print('ok')"
```
Expected: `ok` (no import error)

**Commit:**
```bash
git add backend/app/schemas/__init__.py
git commit -m "fix(schema): add Intraday to Horizon literal (R6)"
```

---

## Task 2 — Add entry-quality thresholds to `scoring_rules.yaml` (5 min)

**File:** `backend/config/scoring_rules.yaml`

Add this block at the **end of the file** (after all existing content):

```yaml
# Entry quality thresholds (FR-45 — no magic numbers in code)
entry_quality:
  spread_tolerance_pct: 0.10
  max_slippage_pct: 0.03
  min_premium: 0.10
```

**Verify** — the file must still parse:
```bash
cd backend
python -c "import yaml; yaml.safe_load(open('config/scoring_rules.yaml'))); print('ok')"
```
Expected: `ok`

**Commit:**
```bash
git add backend/config/scoring_rules.yaml
git commit -m "config: externalise entry_quality thresholds to scoring_rules.yaml (R2)"
```

---

## Task 3 — Add reward-risk defaults to `risk_rules.yaml` (5 min)

**File:** `backend/config/risk_rules.yaml`

Add this block at the **end of the file**:

```yaml
# Reward-risk calculation defaults (FR-45)
reward_risk:
  bullish_target_pct: 0.08      # +8% stock move for T1 target
  bearish_target_pct: 0.08      # 8% move down for bearish T1
  bullish_invalidation_pct: 0.03   # -3% stock = invalidation
  bearish_invalidation_pct: 0.03   # +3% stock = bearish invalidation
  premium_stop_pct: 0.60        # stop out if option loses 60% of premium
```

**Verify:**
```bash
cd backend
python -c "import yaml; yaml.safe_load(open('config/risk_rules.yaml')); print('ok')"
```
Expected: `ok`

**Commit:**
```bash
git add backend/config/risk_rules.yaml
git commit -m "config: externalise reward_risk defaults to risk_rules.yaml (R3)"
```

---

## Task 4 — Refactor `entry_quality.py` to read from YAML (15 min)

**File:** `backend/app/scoring/entry_quality.py`

**Full replacement of the file** (keep `EntryAssessment` and `assess_entry` unchanged except the config loading):

```python
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

OrderType = Literal["Limit", "Market"]
Status = Literal["PASS", "CAUTION", "REJECT"]

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _entry_cfg() -> dict:
    return _load_config()["entry_quality"]


@dataclass
class EntryConfig:
    spread_tolerance_pct: float | None = None
    max_slippage_pct: float | None = None
    min_premium: float | None = None

    def __post_init__(self) -> None:
        cfg = _entry_cfg()
        if self.spread_tolerance_pct is None:
            self.spread_tolerance_pct = cfg["spread_tolerance_pct"]
        if self.max_slippage_pct is None:
            self.max_slippage_pct = cfg["max_slippage_pct"]
        if self.min_premium is None:
            self.min_premium = cfg["min_premium"]


@dataclass
class EntryAssessment:
    limit_price: float
    max_fill: float
    order_type: OrderType
    quality_status: Status
    quality_reasons: list[str] = field(default_factory=list)


def assess_entry(
    bid: float,
    ask: float,
    mid: float,
    config: EntryConfig | None = None,
) -> EntryAssessment:
    if config is None:
        config = EntryConfig()

    spread_pct = round((ask - bid) / mid, 10) if mid > 0 else 1.0

    limit_price = round(mid, 2)
    max_fill = round(mid * (1 + config.max_slippage_pct), 2)
    order_type: OrderType = "Limit"

    quality_reasons: list[str] = []
    worst_status: Status = "PASS"

    if mid < config.min_premium:
        quality_reasons.append("premium too low")
        worst_status = "REJECT"

    if spread_pct > config.spread_tolerance_pct * 3:
        quality_reasons.append("wide spread")
        worst_status = "REJECT"

    if spread_pct > config.spread_tolerance_pct:
        if worst_status == "PASS":
            worst_status = "CAUTION"
        quality_reasons.append("elevated spread")

    return EntryAssessment(
        limit_price=limit_price,
        max_fill=max_fill,
        order_type=order_type,
        quality_status=worst_status,
        quality_reasons=quality_reasons,
    )
```

**Important:** Check the rest of `entry_quality.py` beyond line 50 before writing. Paste the full file — do not truncate `assess_entry` if it continues past what is shown here.

**Verify no numeric literals remain:**
```bash
grep -n "0\.10\|0\.03\|0\.10" backend/app/scoring/entry_quality.py
```
Expected: no output (no hardcoded threshold values in source)

**Run existing entry quality tests:**
```bash
cd backend && python -m pytest tests/test_entry_quality.py -v
```
Expected: all pass

**Commit:**
```bash
git add backend/app/scoring/entry_quality.py
git commit -m "refactor(entry_quality): load thresholds from scoring_rules.yaml (R2)"
```

---

## Task 5 — Refactor magic numbers in `scan.py` (15 min)

**File:** `backend/app/routers/scan.py`

Three magic numbers to replace at lines 185–186 and 257. They currently read:
```python
# line 185
target_price = price * (1.08 if req.direction == "Bullish" else 0.92)
# line 186
invalidation_price = price * (0.97 if req.direction == "Bullish" else 1.03)
# line 257
premiumStop=round(premium * 0.6, 2),
```

**Step 1:** At the top of the file (after the existing `import yaml` line, before the router definition), add a config loader. Check whether `_rr_cfg` or similar already exists in the file — if it does, adapt accordingly:

```python
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path

_RR_CONFIG_PATH = _Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

@_lru_cache(maxsize=1)
def _rr_cfg() -> dict:
    import yaml as _yaml
    with open(_RR_CONFIG_PATH) as f:
        return _yaml.safe_load(f)["reward_risk"]
```

**Step 2:** Replace the three magic-number lines:
```python
# Replace lines 185–186:
_rr = _rr_cfg()
_bull = req.direction == "Bullish"
target_price = price * (1 + _rr["bullish_target_pct"]) if _bull else price * (1 - _rr["bearish_target_pct"])
invalidation_price = price * (1 - _rr["bullish_invalidation_pct"]) if _bull else price * (1 + _rr["bearish_invalidation_pct"])

# Replace line 257:
premiumStop=round(premium * _rr["premium_stop_pct"], 2),
```

**Verify:**
```bash
cd backend
python -c "from app.routers.scan import router; print('ok')"
```
Expected: `ok`

**Run scan tests:**
```bash
cd backend && python -m pytest tests/test_scan_endpoint.py tests/test_integration.py -v --tb=short
```
Expected: same pass/fail ratio as before this change (no new failures)

**Commit:**
```bash
git add backend/app/routers/scan.py
git commit -m "refactor(scan): load target/invalidation/premium_stop from risk_rules.yaml (R3)"
```

---

## Task 6 — Rewrite `test_portfolio_rules.py` (30 min)

**File:** `backend/tests/test_portfolio_rules.py`

**Replace the entire file** with tests that call the real `check_position_risk()` function. The function lives in `backend/app/services/portfolio_risk.py`.

**Critical:** `portfolio_risk.py` defines its **own** `PortfolioPosition` dataclass — it is NOT the same as `app.schemas.PortfolioPosition`. Import from `app.services.portfolio_risk`.

```python
"""
Portfolio risk rule tests — FR-42.
Tests the actual check_position_risk() function from portfolio_risk.py.
"""
import pytest
from app.services.portfolio_risk import (
    check_position_risk,
    PortfolioPosition,
    RiskCheckResult,
)


def _make_portfolio_position(
    symbol: str = "AAPL",
    contract_id: str = "AAPL|190|2026-05-16|C",
    contracts: int = 1,
    entry_premium: float = 4.15,
    current_price: float = 5.02,
    capital_at_risk: float = 415.0,
) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol,
        contract_id=contract_id,
        contracts=contracts,
        entry_premium=entry_premium,
        current_price=current_price,
        capital_at_risk=capital_at_risk,
    )


def _make_request(
    symbol: str = "TSLA",
    contract_id: str = "TSLA|250|2026-05-16|C",
    proposed_contracts: int = 1,
    entry_premium: float = 3.50,
    current_price: float = 4.20,
    portfolio: list[PortfolioPosition] | None = None,
    portfolio_value: float = 50_000.0,
    daily_recommendation_count: int = 0,
) -> dict:
    return dict(
        symbol=symbol,
        contract_id=contract_id,
        proposed_contracts=proposed_contracts,
        entry_premium=entry_premium,
        current_price=current_price,
        portfolio=portfolio or [],
        portfolio_value=portfolio_value,
        daily_recommendation_count=daily_recommendation_count,
    )


class TestCheckPositionRisk:

    def test_clean_position_is_approved(self):
        """A position well within all limits should be approved."""
        result = check_position_risk(**_make_request())
        assert isinstance(result, RiskCheckResult)
        assert result.approved is True
        assert result.reasons == []

    def test_rejected_by_single_trade_exposure(self):
        """Entry premium × contracts > max_single_trade_exposure_pct × portfolio_value → rejected or size-adjusted."""
        # max_single_trade_exposure_pct = 0.05 (from risk_rules.yaml)
        # 50_000 * 0.05 = 2_500 max capital at risk
        # entry_premium=30, contracts=2 → capital_at_risk = 30*2*100 = 6_000 > 2_500
        result = check_position_risk(**_make_request(
            entry_premium=30.0,
            proposed_contracts=2,
            portfolio_value=50_000.0,
        ))
        # Either rejected outright or adjusted to a smaller size
        if result.approved:
            assert result.adjusted_size is not None
            assert result.adjusted_size < 2
        else:
            assert "single_trade_exposure_too_high" in result.reasons

    def test_rejected_by_max_concurrent_positions(self):
        """Portfolio already at max_concurrent_positions (10) → rejected."""
        full_portfolio = [
            _make_portfolio_position(symbol=f"SYM{i}", capital_at_risk=200.0)
            for i in range(10)  # max_concurrent_positions = 10
        ]
        result = check_position_risk(**_make_request(portfolio=full_portfolio))
        assert result.approved is False
        assert "max_concurrent_positions_reached" in result.reasons

    def test_rejected_by_daily_recommendation_limit(self):
        """daily_recommendation_count >= max_daily_recommendations (5) → rejected."""
        result = check_position_risk(**_make_request(daily_recommendation_count=5))
        assert result.approved is False
        assert "daily_recommendation_limit_reached" in result.reasons

    def test_rejected_by_duplicate_symbol(self):
        """Same symbol already open → rejected when max_same_symbol_positions=1."""
        existing = [_make_portfolio_position(symbol="TSLA")]
        result = check_position_risk(**_make_request(
            symbol="TSLA",
            portfolio=existing,
        ))
        assert result.approved is False
        assert "duplicate_symbol_already_open" in result.reasons
```

**Run the new tests:**
```bash
cd backend && python -m pytest tests/test_portfolio_rules.py -v
```
Expected: 5 tests, all PASS.

**Commit:**
```bash
git add backend/tests/test_portfolio_rules.py
git commit -m "test(portfolio): test actual check_position_risk() for FR-42 (R7)"
```

---

## Task 7 — Add size cap to `audit.ts` (15 min)

**File:** `frontend/lib/audit.ts`

**Full replacement of the file:**

```typescript
/**
 * Minimal audit logger — console + localStorage.
 * Capped at MAX_ENTRIES to prevent QuotaExceededError.
 */

export type AuditEvent = 'APPROVE' | 'REJECT' | 'SUBMIT' | 'CLOSE';

interface AuditEntry {
  timestamp: string;
  event: AuditEvent;
  recId: string;
  details?: Record<string, unknown>;
}

const AUDIT_STORAGE_KEY = 'bamendjou-audit-log';
const MAX_ENTRIES = 500;
const EVICT_COUNT = 100; // how many to drop when over limit

export function logAudit(
  event: AuditEvent,
  recId: string,
  details?: Record<string, unknown>
): void {
  const entry: AuditEntry = {
    timestamp: new Date().toISOString(),
    event,
    recId,
    details,
  };
  // eslint-disable-next-line no-console
  console.log('[AUDIT]', entry);
  try {
    const raw = localStorage.getItem(AUDIT_STORAGE_KEY);
    const log: AuditEntry[] = raw ? (JSON.parse(raw) as AuditEntry[]) : [];
    log.push(entry);

    // FIFO eviction: keep newest MAX_ENTRIES
    if (log.length > MAX_ENTRIES) {
      log.splice(0, log.length - MAX_ENTRIES);
    }

    _setWithFallback(log);
  } catch {
    // ignore storage read errors
  }
}

function _setWithFallback(log: AuditEntry[]): void {
  try {
    localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(log));
  } catch {
    // QuotaExceededError: evict oldest EVICT_COUNT entries and retry once
    try {
      log.splice(0, EVICT_COUNT);
      localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(log));
    } catch {
      // If it still fails (e.g. single entry too large), silently drop
    }
  }
}
```

**Verify typecheck:**
```bash
cd frontend && npm run typecheck
```
Expected: no errors.

**Commit:**
```bash
git add frontend/lib/audit.ts
git commit -m "fix(audit): add 500-entry FIFO cap and QuotaExceededError recovery (R8)"
```

---

## Final verification

Run all these and confirm they pass:

```bash
# Backend — full suite (11 pre-existing route failures are expected and unchanged)
cd backend && python -m pytest --tb=short -q
# Expected: same 90 pass, 11 fail as baseline. Zero new failures.

# Specific tests added/modified in this workstream:
cd backend && python -m pytest tests/test_portfolio_rules.py tests/test_entry_quality.py -v
# Expected: all pass

# Frontend typecheck
cd frontend && npm run typecheck
# Expected: no errors

# Schema sanity check
cd backend && python -c "
from app.schemas import ScanRequest, Horizon
r = ScanRequest(universe=['AAPL'], direction='Bullish', horizon='Intraday')
print('Intraday accepted:', r.horizon)
"
# Expected: Intraday accepted: Intraday
```

---

## Hard Rules

1. No Tailwind, styled-components, or CSS-in-JS in frontend files.
2. No hardcoded hex colors — always use CSS custom properties.
3. `npm run typecheck` must be clean after every frontend file edit.
4. No numeric threshold literals in Python source files — all thresholds live in YAML.
5. Do not modify any file outside the Owned Files table above.
6. Do not change any Pydantic schema field names — other workstreams depend on them.

---

## Copy-Paste Handover Prompt

```
Read `llm-contexts/00-ws33-foundation.md` fully before writing any code.
It is your single source of truth.

You are implementing WS-33 (Foundation Fixes) for the Bamendjou options screener
(FastAPI backend + Next.js 15 frontend, TypeScript strict).

Your owned files (do not touch anything else):
- backend/app/schemas/__init__.py         (add 'Intraday' to Horizon literal)
- backend/config/scoring_rules.yaml       (add entry_quality section)
- backend/config/risk_rules.yaml          (add reward_risk section)
- backend/app/scoring/entry_quality.py    (read thresholds from YAML)
- backend/app/routers/scan.py             (read magic-number pcts from YAML)
- backend/tests/test_portfolio_rules.py   (test actual check_position_risk())
- frontend/lib/audit.ts                   (add FIFO cap + QuotaExceededError recovery)

Work in the worktree at: .worktrees/fix/ws-33-foundation
Branch: fix/ws-33-foundation

After every backend change run: cd backend && python -m pytest tests/test_entry_quality.py tests/test_portfolio_rules.py -v
After every frontend change run: cd frontend && npm run typecheck

Commit after each file is complete. Do not bundle all changes into one commit.
```
