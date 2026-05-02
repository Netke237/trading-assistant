# LLM Context — Portfolio Risk Controls (Workstream 23)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates `backend/app/services/portfolio_risk.py` and `backend/config/risk_rules.yaml`. It does not touch `frontend/`, any router, any fixture, or any existing model or schema file.

**Goal:**
Implement portfolio risk controls. Given a proposed new trade and the current portfolio, check whether adding the trade would breach position-sizing, exposure, or correlation limits. Returns an approved/rejected decision with reasons. All limits are loaded from `backend/config/risk_rules.yaml` — no magic numbers in Python.

**What NOT to touch:**
- Any file under `frontend/`
- Any router, fixture, or existing model file
- `backend/app/main.py`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/services/portfolio_risk.py` | **Create** | Risk check entry point and rule functions |
| `backend/config/risk_rules.yaml` | **Create** | All limit values |

---

## Section 3 — Type contracts

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PortfolioPosition:
    symbol: str
    contract_id: str        # SYMBOL|STRIKE|EXPIRY|C/P
    contracts: int          # number of contracts held
    entry_premium: float    # premium paid per contract
    current_price: float    # current underlying price
    capital_at_risk: float  # max loss (entry_premium * contracts * 100)


@dataclass
class RiskCheckResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    adjusted_size: Optional[int] = None  # suggested contract count if size was reduced
    portfolio_exposure_pct: float = 0.0  # total portfolio exposure after adding trade
```

---

## Section 4 — `risk_rules.yaml`

Create `backend/config/risk_rules.yaml` with these values:

```yaml
# backend/config/risk_rules.yaml

portfolio:
  # All percentages expressed as decimals (0.05 = 5%)
  max_single_trade_exposure_pct: 0.05     # single trade capital at risk / total portfolio value
  max_total_exposure_pct: 0.25            # sum of all open positions capital at risk / total portfolio value
  max_concurrent_positions: 10            # hard cap on number of open positions
  max_daily_recommendations: 5           # max new trades recommended per calendar day
  max_same_symbol_positions: 1           # reject if symbol already has an open position
  min_portfolio_value: 5000.0            # below this, all trades rejected (account too small)

sizing:
  default_contracts: 1                   # default contract count when not specified
  max_contracts_per_trade: 5             # hard cap per single trade
```

---

## Section 5 — Implementation

### Config loading

```python
from __future__ import annotations

import yaml
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)
```

### Risk check entry point

```python
def check_position_risk(
    symbol: str,
    contract_id: str,
    proposed_contracts: int,
    entry_premium: float,
    current_price: float,
    portfolio: list[PortfolioPosition],
    portfolio_value: float,
    daily_recommendation_count: int = 0,
) -> RiskCheckResult:
    """
    Check whether adding a new position is within risk limits.

    Args:
        symbol:                     Underlying ticker (e.g. "AAPL")
        contract_id:                Canonical contract ID (SYMBOL|STRIKE|EXPIRY|C/P)
        proposed_contracts:         Number of contracts to buy
        entry_premium:              Premium per contract in dollars
        current_price:              Current underlying price
        portfolio:                  List of currently open PortfolioPosition objects
        portfolio_value:            Total portfolio value in dollars (cash + positions)
        daily_recommendation_count: Number of recommendations already made today

    Returns:
        RiskCheckResult with approved flag, list of rejection reasons,
        optionally adjusted_size if size reduction could make trade fit,
        and resulting portfolio_exposure_pct.
    """
    cfg = _load_config()
    rules = cfg["portfolio"]
    sizing = cfg["sizing"]
    reasons = []
    adjusted_size: Optional[int] = None

    # Guard: minimum portfolio size
    if portfolio_value < rules["min_portfolio_value"]:
        return RiskCheckResult(
            approved=False,
            reasons=["portfolio_too_small"],
            portfolio_exposure_pct=0.0,
        )

    # Guard: max contracts per trade
    proposed_contracts = min(proposed_contracts, sizing["max_contracts_per_trade"])

    # Guard: daily recommendation cap
    if daily_recommendation_count >= rules["max_daily_recommendations"]:
        return RiskCheckResult(
            approved=False,
            reasons=["daily_recommendation_limit_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    # Rule: max concurrent positions
    if len(portfolio) >= rules["max_concurrent_positions"]:
        return RiskCheckResult(
            approved=False,
            reasons=["max_concurrent_positions_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    # Rule: correlation — no duplicate symbol
    existing_symbols = [p.symbol for p in portfolio]
    if symbol in existing_symbols and rules["max_same_symbol_positions"] <= 1:
        return RiskCheckResult(
            approved=False,
            reasons=["duplicate_symbol_already_open"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    # Rule: single-trade exposure
    capital_at_risk = entry_premium * proposed_contracts * 100
    single_exposure_pct = capital_at_risk / portfolio_value
    max_single = rules["max_single_trade_exposure_pct"]

    if single_exposure_pct > max_single:
        # Can we reduce contracts to fit?
        max_allowed_premium = portfolio_value * max_single
        adjusted = int(max_allowed_premium / (entry_premium * 100))
        if adjusted >= 1:
            adjusted_size = adjusted
            capital_at_risk = entry_premium * adjusted_size * 100
            single_exposure_pct = capital_at_risk / portfolio_value
        else:
            reasons.append("single_trade_exposure_too_high")

    # Rule: total portfolio exposure
    current_exposure = _current_exposure_abs(portfolio)
    total_exposure_pct = (current_exposure + capital_at_risk) / portfolio_value
    max_total = rules["max_total_exposure_pct"]

    if total_exposure_pct > max_total:
        reasons.append("total_exposure_limit_reached")

    if reasons:
        return RiskCheckResult(
            approved=False,
            reasons=reasons,
            adjusted_size=adjusted_size,
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    return RiskCheckResult(
        approved=True,
        reasons=[],
        adjusted_size=adjusted_size,  # set if size was reduced but still fits
        portfolio_exposure_pct=round(total_exposure_pct * 100, 2),
    )


def _current_exposure_abs(portfolio: list[PortfolioPosition]) -> float:
    """Total capital at risk across all open positions in dollars."""
    return sum(p.capital_at_risk for p in portfolio)


def _current_exposure(portfolio: list[PortfolioPosition], portfolio_value: float) -> float:
    """Total exposure as a percentage of portfolio value (0–100)."""
    if portfolio_value <= 0:
        return 0.0
    return round(_current_exposure_abs(portfolio) / portfolio_value * 100, 2)
```

---

## Section 6 — Task spec

### Acceptance criteria

1. A trade that would put 6% of portfolio into one position (above 5% limit) returns `approved=False` with `"single_trade_exposure_too_high"` in reasons — unless reducing to 1 contract would fit, in which case `adjusted_size=1` and `approved=True`.
2. A portfolio already at 25% total exposure returns `approved=False` with `"total_exposure_limit_reached"`.
3. A portfolio with 10 open positions returns `approved=False` with `"max_concurrent_positions_reached"`.
4. A trade for a symbol already in the portfolio returns `approved=False` with `"duplicate_symbol_already_open"`.
5. `check_position_risk("AAPL", "AAPL|190|2025-08-15|C", 1, 3.0, 185.0, [], 10000.0)` returns `approved=True` (1 contract at $300 capital risk = 3% of $10k portfolio, within limits).
6. `python -c "from app.services.portfolio_risk import check_position_risk; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
python -c "
from app.services.portfolio_risk import check_position_risk, PortfolioPosition

# Clean trade — should approve
r1 = check_position_risk('AAPL', 'AAPL|190|2025-08-15|C', 1, 3.0, 185.0, [], 10000.0)
print('Clean trade:', r1.approved, r1.reasons)
assert r1.approved, f'Expected approved, got {r1.reasons}'

# Exposure too high — single trade
r2 = check_position_risk('AAPL', 'AAPL|190|2025-08-15|C', 5, 12.0, 185.0, [], 10000.0)
print('High exposure:', r2.approved, r2.reasons, 'adjusted:', r2.adjusted_size)

# Duplicate symbol
pos = PortfolioPosition('AAPL', 'AAPL|185|2025-07-18|C', 1, 3.5, 185.0, 350.0)
r3 = check_position_risk('AAPL', 'AAPL|190|2025-08-15|C', 1, 3.0, 185.0, [pos], 10000.0)
print('Duplicate symbol:', r3.approved, r3.reasons)
assert not r3.approved
assert 'duplicate_symbol_already_open' in r3.reasons

# Portfolio too small
r4 = check_position_risk('AAPL', 'AAPL|190|2025-08-15|C', 1, 3.0, 185.0, [], 1000.0)
print('Too small:', r4.approved, r4.reasons)
assert not r4.approved
assert 'portfolio_too_small' in r4.reasons

# Max concurrent positions
positions = [PortfolioPosition(f'SYM{i}', f'SYM{i}|100|2025-08-15|C', 1, 2.0, 100.0, 200.0)
             for i in range(10)]
r5 = check_position_risk('NEW', 'NEW|50|2025-08-15|C', 1, 2.0, 50.0, positions, 50000.0)
print('Max positions:', r5.approved, r5.reasons)
assert not r5.approved
assert 'max_concurrent_positions_reached' in r5.reasons

print('All checks passed')
"
```

---

## Section 7 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. No magic numbers in `portfolio_risk.py` — every limit from YAML.
3. All functions must be safe on empty portfolio list.
4. Do NOT use pandas or numpy.
5. `pyyaml` is already available.
6. `portfolio_exposure_pct` in `RiskCheckResult` is expressed as a percentage (0–100), not a decimal.

---

## Section 8 — Dev workflow

```bash
cd backend
python -c "from app.services.portfolio_risk import check_position_risk; print('OK')"
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-23-portfolio-risk.

Read `llm-contexts/23-portfolio-risk.md` fully before writing any code.
It is your single source of truth.

You are implementing the portfolio risk controls for the Bamendjou options screener
(FastAPI / Python 3.11 / pure Python).

Your owned files:
  - backend/app/services/portfolio_risk.py   (CREATE)
  - backend/config/risk_rules.yaml           (CREATE — use YAML from Section 4)

Do not modify any file outside this list.

Task: Implement check_position_risk() and all helper functions exactly as specified
in Section 5. All limits must come from YAML. Safe on empty portfolio.
Run the verification block in Section 6 after implementation.
Commit after all checks pass.
```
