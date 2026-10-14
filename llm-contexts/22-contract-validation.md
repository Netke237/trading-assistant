# LLM Context — Contract Validation Engine (Workstream 22)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates `backend/app/scoring/contract_validator.py` and `backend/config/contract_rules.yaml`. It reads `backend/app/data/market.py` (WS-13, read-only). It does not touch `frontend/`, any router, any fixture, or any existing model or schema file.

**Goal:**
Implement the contract validation engine. Given an option contract and a stock score, it applies hard-reject rules (FR-24) and soft-rank rules (FR-25) from the PRD and returns a `ContractScoreCard`. All thresholds are loaded from `backend/config/contract_rules.yaml` — no magic numbers in Python.

**What NOT to touch:**
- Any file under `frontend/`
- `backend/app/data/market.py` — read-only dependency
- `backend/app/scoring/stock_scorer.py` — read-only reference for `StockScoreCard`
- Any router, fixture, or existing schema file
- `backend/app/main.py`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/scoring/contract_validator.py` | **Create** | Hard-reject + soft-rank rules + aggregator |
| `backend/config/contract_rules.yaml` | **Create** | All numeric thresholds |

`backend/app/scoring/__init__.py` was created by WS-20. If it does not exist, create it as empty.

---

## Section 3 — Read-only references

**Option contract dict shape** (from `fetch_option_chain()` in WS-13):
```python
{
    "symbol": "AAPL",
    "strike": 190.0,
    "expiry": "2025-06-20",       # ISO date string
    "is_call": True,
    "bid": 2.80,
    "ask": 3.20,
    "last": 3.00,
    "volume": 1500,
    "open_interest": 8200,
    "implied_vol": 0.28,          # annualised IV (may be None)
    "delta": 0.42,                # BS delta (may be None)
    "theta": -0.08,               # BS theta per day (may be None)
}
```

**Contract canonical ID format:** `SYMBOL|STRIKE|EXPIRY|C/P`
Example: `AAPL|190|2025-06-20|C`

---

## Section 4 — Type contracts

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional

Status = Literal["PASS", "CAUTION", "REJECT"]


@dataclass
class ContractScoreBreakdown:
    liquidity_score: int        # 0–100
    spread_score: int           # 0–100
    delta_score: int            # 0–100
    dte_score: int              # 0–100
    iv_rank_score: int          # 0–100
    oi_score: int               # 0–100


@dataclass
class ContractScoreCard:
    contract_id: str            # canonical ID: SYMBOL|STRIKE|EXPIRY|C/P
    symbol: str
    strike: float
    expiry: str
    is_call: bool
    score: int                  # 0–100 aggregate
    status: Status
    reject_reasons: list[str] = field(default_factory=list)  # hard-reject labels
    soft_flags: list[str] = field(default_factory=list)       # soft-rank labels
    breakdown: ContractScoreBreakdown = field(
        default_factory=lambda: ContractScoreBreakdown(0, 0, 0, 0, 0, 0)
    )
```

---

## Section 5 — `contract_rules.yaml`

Create `backend/config/contract_rules.yaml` with these values:

```yaml
# backend/config/contract_rules.yaml

score_thresholds:
  pass: 65
  caution: 45

# Hard-reject rules (FR-24) — any one triggers REJECT, score = 0
hard_reject:
  min_volume: 0                 # optional hard floor; 0 = off (FR-25 treats volume as soft)
  min_open_interest: 200        # open interest — below this = illiquid
  max_bid_ask_spread_pct: 0.20  # spread / mid-price — above this = too wide
  min_delta: 0.20               # absolute delta — below this = too far OTM
  max_delta: 0.85               # absolute delta — above this = too deep ITM
  min_dte: 14                   # calendar days to expiry — below this = too short
  max_dte: 90                   # calendar days to expiry — above this = too long
  max_soft_fail_count: 3        # reject if this many soft rules fail

# Soft-rank rules (FR-25) — penalise score but do not block
soft_rank:
  preferred_volume_min: 200          # below this = soft penalty
  preferred_oi_min: 1000             # below this = soft penalty
  preferred_spread_pct_max: 0.08     # above this = soft penalty
  preferred_delta_min: 0.30          # below this = soft penalty (edge of golden zone)
  preferred_delta_max: 0.70          # above this = soft penalty
  preferred_dte_min: 21              # below this = soft penalty
  preferred_dte_max: 60              # above this = soft penalty
  preferred_iv_rank_max: 55          # above this = soft penalty (expensive premium)

# Weights for scoring (must sum to 1.0)
weights:
  liquidity: 0.25    # volume + OI combined
  spread: 0.25       # bid-ask spread tightness
  delta: 0.20        # delta in preferred zone
  dte: 0.15          # DTE in preferred band
  iv_rank: 0.15      # IV rank acceptability
```

---

## Section 6 — Implementation

### Config loading

```python
import yaml
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "contract_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)
```

### Hard-reject checks (FR-24)

```python
from datetime import date

def _hard_reject_reasons(contract: dict, cfg: dict) -> list[str]:
    """Return list of hard-reject reason strings. Empty = no hard reject."""
    hr = cfg["hard_reject"]
    reasons = []

    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    delta = abs(contract.get("delta") or 0)

    expiry_str = contract.get("expiry", "")
    try:
        expiry_date = date.fromisoformat(expiry_str)
        dte = (expiry_date - date.today()).days
    except (ValueError, TypeError):
        dte = 0

    # min_volume is an optional hard floor, 0 = off (the default). For an
    # explicit floor above 0, volume == 0 is exempt when OI is adequate: a 0
    # (session-to-date count) cannot be told apart from "no trades yet this
    # session". Off-hours rows are handled by the quote-liveness rule.
    if (
        hr["min_volume"] > 0
        and volume < hr["min_volume"]
        and not (volume == 0 and oi >= hr["min_open_interest"])
    ):
        reasons.append("volume_too_low")
    if oi < hr["min_open_interest"]:
        reasons.append("open_interest_too_low")
    if spread_pct > hr["max_bid_ask_spread_pct"]:
        reasons.append("spread_too_wide")
    if delta < hr["min_delta"]:
        reasons.append("delta_too_low_far_otm")
    if delta > hr["max_delta"]:
        reasons.append("delta_too_high_deep_itm")
    if dte < hr["min_dte"]:
        reasons.append("dte_too_short")
    if dte > hr["max_dte"]:
        reasons.append("dte_too_long")

    return reasons
```

### Soft-rank scoring (FR-25)

Each soft component scores 0–100. Soft failures append a flag string.

```python
def _score_liquidity(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    flags = []
    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0

    vol_score = min(100, int(volume / sr["preferred_volume_min"] * 60))
    oi_score = min(100, int(oi / sr["preferred_oi_min"] * 60))
    score = (vol_score + oi_score) // 2

    # One soft flag for the liquidity axis: volume and open interest together
    # count as at most one soft miss toward max_soft_fail_count.
    if volume < sr["preferred_volume_min"] or oi < sr["preferred_oi_min"]:
        flags.append("thin_liquidity")
    return score, flags


def _score_spread(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    flags = []

    max_pct = sr["preferred_spread_pct_max"]
    score = max(0, int((1 - spread_pct / max_pct) * 100)) if spread_pct < max_pct else 0
    score = min(score, 100)

    if spread_pct > max_pct:
        flags.append("spread_elevated")
    return score, flags


def _score_delta(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    delta = abs(contract.get("delta") or 0)
    flags = []
    d_min = sr["preferred_delta_min"]
    d_max = sr["preferred_delta_max"]

    if d_min <= delta <= d_max:
        # Linear score peaking at 0.50
        centre = (d_min + d_max) / 2
        half_range = (d_max - d_min) / 2
        score = int(100 * (1 - abs(delta - centre) / half_range))
    else:
        score = 20
        flags.append("delta_outside_preferred")
    return score, flags


def _score_dte(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    expiry_str = contract.get("expiry", "")
    flags = []
    try:
        dte = (date.fromisoformat(expiry_str) - date.today()).days
    except (ValueError, TypeError):
        return 0, ["dte_parse_error"]

    d_min = sr["preferred_dte_min"]
    d_max = sr["preferred_dte_max"]

    if d_min <= dte <= d_max:
        centre = (d_min + d_max) / 2
        half_range = (d_max - d_min) / 2
        score = int(100 * (1 - abs(dte - centre) / half_range))
    else:
        score = 25
        flags.append("dte_outside_preferred")
    return score, flags


def _score_iv_rank(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    iv_rank = contract.get("iv_rank")
    flags = []

    if iv_rank is None:
        return 50, ["no_iv_rank_data"]  # neutral

    max_pref = sr["preferred_iv_rank_max"]
    if iv_rank <= max_pref:
        score = int(100 * (1 - iv_rank / max_pref))
    else:
        score = max(0, int(20 * (1 - (iv_rank - max_pref) / (100 - max_pref))))
        flags.append("iv_rank_elevated")
    return score, flags
```

### Main entry point

```python
def _contract_id(contract: dict) -> str:
    side = "C" if contract.get("is_call", True) else "P"
    return f"{contract.get('symbol', '')}|{contract.get('strike', '')}|{contract.get('expiry', '')}|{side}"


def validate_contract(
    contract: dict,
    stock_score: int,
) -> ContractScoreCard:
    """
    Validate and score an option contract.

    Args:
        contract:    Option contract dict (see Section 3 for shape)
        stock_score: Aggregate stock score from StockScoreCard (0–100).
                     Contracts are only recommended when stock_score >= 50.

    Returns:
        ContractScoreCard with score, status, hard-reject reasons, soft flags,
        and score breakdown.
    """
    cfg = _load_config()
    contract_id = _contract_id(contract)

    reject_reasons = _hard_reject_reasons(contract, cfg)

    liq_score, liq_flags = _score_liquidity(contract, cfg)
    spread_score, spread_flags = _score_spread(contract, cfg)
    delta_score, delta_flags = _score_delta(contract, cfg)
    dte_score, dte_flags = _score_dte(contract, cfg)
    iv_score, iv_flags = _score_iv_rank(contract, cfg)

    soft_flags = liq_flags + spread_flags + delta_flags + dte_flags + iv_flags
    soft_fail_count = len(soft_flags)

    if soft_fail_count >= cfg["hard_reject"]["max_soft_fail_count"]:
        reject_reasons.append("too_many_soft_failures")

    if reject_reasons:
        return ContractScoreCard(
            contract_id=contract_id,
            symbol=contract.get("symbol", ""),
            strike=float(contract.get("strike", 0)),
            expiry=contract.get("expiry", ""),
            is_call=contract.get("is_call", True),
            score=0,
            status="REJECT",
            reject_reasons=reject_reasons,
            soft_flags=soft_flags,
            breakdown=ContractScoreBreakdown(
                liquidity_score=liq_score,
                spread_score=spread_score,
                delta_score=delta_score,
                dte_score=dte_score,
                iv_rank_score=iv_score,
                oi_score=0,
            ),
        )

    weights = cfg["weights"]
    weighted = (
        liq_score * weights["liquidity"]
        + spread_score * weights["spread"]
        + delta_score * weights["delta"]
        + dte_score * weights["dte"]
        + iv_score * weights["iv_rank"]
    )
    score = round(weighted)
    thresholds = cfg["score_thresholds"]

    if score >= thresholds["pass"]:
        status: Status = "PASS"
    elif score >= thresholds["caution"]:
        status = "CAUTION"
    else:
        status = "REJECT"

    return ContractScoreCard(
        contract_id=contract_id,
        symbol=contract.get("symbol", ""),
        strike=float(contract.get("strike", 0)),
        expiry=contract.get("expiry", ""),
        is_call=contract.get("is_call", True),
        score=score,
        status=status,
        reject_reasons=[],
        soft_flags=soft_flags,
        breakdown=ContractScoreBreakdown(
            liquidity_score=liq_score,
            spread_score=spread_score,
            delta_score=delta_score,
            dte_score=dte_score,
            iv_rank_score=iv_score,
            oi_score=0,
        ),
    )
```

---

## Section 7 — Task spec

### Acceptance criteria

1. At the default `min_volume: 0` (off), volume is never a hard reject. With an explicit floor
   (`overrides={"min_volume": 50}`), a contract with `volume=3` returns `status="REJECT"` and
   `"volume_too_low"` in `reject_reasons`; `volume=0` with `open_interest >= min_open_interest` is exempt.
2. A well-formed contract (`volume=500, oi=2000, delta=0.45, dte=35, spread_pct=0.05`) returns `status` in `{"PASS", "CAUTION"}`.
3. A contract with 4+ soft failures returns `"too_many_soft_failures"` in `reject_reasons`.
4. `validate_contract({}, 80)` returns `status="REJECT"` — no exception on empty dict.
5. `python -c "from app.scoring.contract_validator import validate_contract; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
python -c "
from app.scoring.contract_validator import validate_contract

# Hard reject — volume below an explicit floor (the default, 0, is off)
c1 = {'symbol': 'AAPL', 'strike': 190.0, 'expiry': '2025-08-15',
      'is_call': True, 'bid': 2.8, 'ask': 3.2, 'volume': 3,
      'open_interest': 5000, 'implied_vol': 0.28, 'delta': 0.45, 'theta': -0.08}
r1 = validate_contract(c1, 75, overrides={'min_volume': 50})
assert r1.status == 'REJECT', f'Expected REJECT, got {r1.status}'
assert 'volume_too_low' in r1.reject_reasons
print('Hard reject OK:', r1.reject_reasons)

# Good contract
c2 = {'symbol': 'AAPL', 'strike': 190.0, 'expiry': '2025-08-15',
      'is_call': True, 'bid': 2.9, 'ask': 3.1, 'volume': 800,
      'open_interest': 3000, 'implied_vol': 0.25, 'delta': 0.45, 'theta': -0.08,
      'iv_rank': 25.0}
r2 = validate_contract(c2, 75)
print(f'Good contract: score={r2.score} status={r2.status}')
assert r2.status in ('PASS', 'CAUTION')

# Empty dict — must not raise
r3 = validate_contract({}, 80)
assert r3.status == 'REJECT'
print('Empty dict OK')
print('All checks passed')
"
```

---

## Section 8 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify `backend/app/data/market.py`.
3. No magic numbers in `contract_validator.py` — every threshold from YAML.
4. All functions must be safe on missing or None contract fields — use `.get()` with defaults.
5. Do NOT use pandas or numpy.
6. `pyyaml` is already available.

---

## Section 9 — Dev workflow

```bash
cd backend
python -c "from app.scoring.contract_validator import validate_contract; print('OK')"
```

---

## Section 10 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-22-contract-validator.

Read `llm-contexts/22-contract-validation.md` fully before writing any code.
It is your single source of truth.

You are implementing the contract validation engine for the Bamendjou options screener
(FastAPI / Python 3.11 / pure Python).

Your owned files:
  - backend/app/scoring/contract_validator.py   (CREATE)
  - backend/config/contract_rules.yaml          (CREATE — use YAML from Section 5)

If backend/app/scoring/__init__.py does not exist, create it as an empty file.

Do not modify any file outside this list.

Task: Implement validate_contract() and all helper functions exactly as specified
in Section 6. All thresholds must come from YAML. Safe on empty/missing fields.
Run the verification block in Section 7 after implementation.
Commit after all checks pass.
```
