# LLM Context — Full /api/scan Endpoint (Workstream 25)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new router file and adds three new Pydantic schemas to the existing schemas file. It wires together all the scoring modules built in Waves 1 and 2. It does not touch `frontend/` or any existing router.

**Goal:**
Implement `POST /api/scan` — the main scan pipeline endpoint. Given a universe of symbols and scan context, it runs the full pipeline: score stocks, validate contracts, assess entry quality, estimate reward-risk, generate trade cards, and log to the audit trail.

**What NOT to touch:**
- Any file under `frontend/`
- Any existing router (alerts, watchlist, candles, etc.)
- `backend/app/main.py` — you WILL add the new router there (see Section 2)
- Any scoring module, model, or service file — all read-only dependencies

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/routers/scan.py` | **Create** | POST /api/scan pipeline |
| `backend/app/schemas/__init__.py` | **Modify** (append only) | Add `ScanRequest`, `RejectedCandidate`, `ScanResult` |
| `backend/app/main.py` | **Modify** (one line import + one include_router call) | Register scan router |

---

## Section 3 — Read-only dependencies

| Module | Import | What it provides |
|---|---|---|
| `app.data.market` | `fetch_candles`, `fetch_price`, `fetch_option_chain` | Live market data |
| `app.scoring.stock_scorer` | `score_stock`, `StockScoreCard` | Stock score per symbol |
| `app.scoring.contract_validator` | `validate_contract`, `ContractScoreCard` | Contract validation |
| `app.scoring.entry_quality` | `assess_entry`, `EntryConfig` | Entry limit price + quality |
| `app.scoring.reward_risk` | `estimate_rr`, `RrResult` | R:R ratio |
| `app.models.heston` | `calibrate_heston`, `HestonParams` | Heston calibration |
| `app.services.audit` | `new_rec_id`, `log_event` | Audit trail logging |

**Import pattern for scoring modules — all handle exceptions internally and never raise:**
```python
from app.data.market import fetch_candles, fetch_price, fetch_option_chain
from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.contract_validator import validate_contract
from app.scoring.entry_quality import assess_entry, EntryConfig
from app.scoring.reward_risk import estimate_rr
from app.models.heston import calibrate_heston, HestonParams
from app.services.audit import new_rec_id, log_event
```

---

## Section 4 — New schemas (append to `backend/app/schemas/__init__.py`)

Add these three classes at the end of the file, after `TradeCardData`:

```python
# ── Scan ──────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    universe: list[str]           # e.g. ["AAPL", "NVDA", "MSFT"]
    direction: Direction          # "Bullish" | "Bearish"
    horizon: Horizon              # "Swing" | "Position"
    overrides: dict = {}          # reserved for future per-symbol config


class RejectedCandidate(BaseModel):
    symbol: str
    reason: str                   # e.g. "stock REJECT (score 42)", "no option chain"


class ScanResult(BaseModel):
    scan_id: str                  # REC-YYYYMMDD-XXXXXXXX from audit service
    timestamp: str                # ISO datetime string
    candidates: list[TradeCardData]
    rejected: list[RejectedCandidate]
```

---

## Section 5 — Pipeline specification

`POST /api/scan` executes this pipeline for each symbol in `universe`:

### Step 1 — Fetch market data
```python
candles = fetch_candles(symbol)          # list[dict] with time/open/high/low/close/volume
price   = fetch_price(symbol)            # float, current close
```
If `price <= 0` or `candles` is empty → append `RejectedCandidate(symbol, "no market data")` and skip.

### Step 2 — Score the stock
```python
card: StockScoreCard = score_stock(symbol, direction, horizon, candles)
```
If `card.status == "REJECT"` → append `RejectedCandidate(symbol, f"stock REJECT (score {card.score})")` and skip.

### Step 3 — Fetch and validate contracts
```python
chain = fetch_option_chain(symbol)       # list[dict]
```
If `chain` is empty → append `RejectedCandidate(symbol, "no option chain")` and skip.

Pick the **best contract**: call `validate_contract(contract_dict, card.score)` for each contract in `chain`. Take the one with the highest `ContractScoreCard.score`. If all contracts are REJECT, append `RejectedCandidate(symbol, "all contracts rejected")` and skip.

### Step 4 — Calibrate Heston (optional, best-effort)
```python
heston_result = calibrate_heston(chain, price, r=0.05)
heston_params = heston_result.params   # may be a fallback — still usable
```
This never fails (calibrate_heston handles thin chains). Use `heston_params` for R:R estimation.

### Step 5 — Assess entry quality
```python
bid = contract.get("bid", contract.get("price", 0) * 0.98)
ask = contract.get("ask", contract.get("price", 0) * 1.02)
mid = contract.get("price", (bid + ask) / 2)
entry = assess_entry(bid=bid, ask=ask, mid=mid)
```

### Step 6 — Estimate reward-risk
```python
target_price       = price * (1.08 if direction == "Bullish" else 0.92)
invalidation_price = price * (0.97 if direction == "Bullish" else 1.03)
strike       = float(contract.get("strike", price))
expiry_years = contract.get("dte", 30) / 365.0
premium      = float(contract.get("price", 0.10))

rr = estimate_rr(
    stock_price=price,
    target_price=target_price,
    invalidation_price=invalidation_price,
    strike=strike,
    expiry_years=expiry_years,
    current_premium=premium,
    is_call=(direction == "Bullish"),
    heston_params=heston_params,
)
```

### Step 7 — Build TradeCardData
Map the pipeline outputs into the existing `TradeCardData` schema:

```python
from app.schemas import (
    TradeCardData, ScoreBreakdown, ContractScoreBreakdown,
    ContractDetails, TradeEntry, TradeExit
)

trade_card = TradeCardData(
    symbol=symbol,
    company=symbol,            # placeholder until company name lookup is available
    price=price,
    direction=direction,
    status=card.status,
    stockScore=card.score,
    stockConfidence=card.status,
    stockBreakdown=ScoreBreakdown(
        trend=     _rule_score(card, "trend"),
        pullback=  _rule_score(card, "pullback"),
        trigger=   _rule_score(card, "trigger"),
        event=     _rule_score(card, "event"),
        volatility=_rule_score(card, "vol"),
    ),
    contract=f"{symbol}|{int(strike)}|{contract.get('expiry','TBD')}|{'C' if direction=='Bullish' else 'P'}",
    contractScore=contract_card.score,
    contractConfidence=contract_card.status,
    contractBreakdown=ContractScoreBreakdown(
        dteFit=          contract_card.breakdown.dte_score,
        delta=           contract_card.breakdown.delta_score,
        ivAttractiveness=contract_card.breakdown.iv_rank_score,
        liquidity=       contract_card.breakdown.liquidity_score,
        spread=          contract_card.breakdown.spread_score,
    ),
    contractDetails=ContractDetails(
        strike=int(strike),
        expiry=contract.get("expiry", "TBD"),
        right="C" if direction == "Bullish" else "P",
        mid=round(premium, 2),
        delta=float(contract.get("delta", 0.45)),
        theta=float(contract.get("theta", -0.05)),
        ivRank=int(contract.get("iv_rank", 50)),
        dte=int(contract.get("dte", 30)),
    ),
    entry=TradeEntry(
        limit=round(entry.limit_price, 2),
        maxFill=round(entry.max_fill, 2),
        orderType=entry.order_type,
    ),
    exit=TradeExit(
        invalidation=round(invalidation_price, 2),
        premiumStop=round(premium * 0.6, 2),
        timeStopDays=max(3, int(contract.get("dte", 30) * 0.4)),
        target=round(target_price, 2),
    ),
    rrRatio=rr.rr_ratio,
    rrModel=rr.model_used,
    finalStatus=_final_status(card.status, contract_card.status, entry.quality_status),
)
```

**Helper `_rule_score`:** returns the `score` field of the matching `RuleResult` from `card.rules`, or 50 if not found.
```python
def _rule_score(card: StockScoreCard, name: str) -> int:
    for r in card.rules:
        if r.name == name:
            return r.score
    return 50
```

**Helper `_final_status`:** worst-of three statuses.
```python
_ORDER = {"REJECT": 0, "CAUTION": 1, "PASS": 2}
def _final_status(s1: str, s2: str, s3: str) -> str:
    return min([s1, s2, s3], key=lambda s: _ORDER.get(s, 1))
```

### Step 8 — Audit log
```python
log_event("trade_card_created", scan_id, {"symbol": symbol, "score": card.score})
```

### Final response assembly

```python
from datetime import datetime, timezone

scan_id = new_rec_id()
log_event("scan_started", scan_id, {"universe": universe, "direction": direction})

# ... run pipeline for each symbol ...

return ScanResult(
    scan_id=scan_id,
    timestamp=datetime.now(timezone.utc).isoformat(),
    candidates=candidates,
    rejected=rejected,
)
```

---

## Section 6 — Router skeleton

```python
# backend/app/routers/scan.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
)
from app.data.market import fetch_candles, fetch_price, fetch_option_chain
from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.contract_validator import validate_contract
from app.scoring.entry_quality import assess_entry
from app.scoring.reward_risk import estimate_rr
from app.models.heston import calibrate_heston
from app.services.audit import new_rec_id, log_event

router = APIRouter(prefix='/api', tags=['scan'])


@router.post('/scan', response_model=ScanResult)
async def run_scan(req: ScanRequest) -> ScanResult:
    ...
```

---

## Section 7 — `main.py` changes

Add these two lines at the appropriate places:
```python
# Import (add with other router imports):
from app.routers.scan import router as scan_router

# Registration (add with other include_router calls):
app.include_router(scan_router)
```

---

## Section 8 — Task spec

### Acceptance criteria

1. `POST /api/scan` with `{"universe":["AAPL"],"direction":"Bullish","horizon":"Swing","overrides":{}}` returns HTTP 200.
2. Response has `scan_id` matching `REC-\d{8}-[A-F0-9]{8}` pattern.
3. Response has `candidates: list` (may be empty if market data unavailable) and `rejected: list`.
4. `POST /api/scan` with `{"universe":[],"direction":"Bullish","horizon":"Swing","overrides":{}}` returns `{"candidates":[],"rejected":[]}` with HTTP 200 — no error.
5. `python -c "from app.routers.scan import router; print('OK')"` prints `OK`.

### Verify

```bash
cd backend
python -c "from app.routers.scan import router; print('OK')"

# Start the server and hit the endpoint
uvicorn app.main:app --port 8000 &
curl -s -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"universe":["AAPL"],"direction":"Bullish","horizon":"Swing","overrides":{}}' \
  | python -m json.tool | grep scan_id
```

---

## Section 9 — Hard rules

1. Do NOT touch any existing router, fixture, model, or scoring file.
2. `backend/app/schemas/__init__.py` — append only. Do not modify existing classes.
3. `backend/app/main.py` — only add the import line and `include_router` call.
4. The pipeline must never raise an unhandled exception — wrap each symbol's processing in a try/except that appends to `rejected`.
5. No pandas, no numpy — all scoring modules handle their own math.
6. `yfinance` may fail for unknown symbols — `fetch_candles` and `fetch_price` handle this gracefully (return empty list / 0.0); the pipeline's Step 1 guard catches it.

---

## Section 10 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-25-scan-endpoint.

Read `llm-contexts/25-scan-endpoint.md` fully before writing any code.
It is your single source of truth.

You are implementing the full POST /api/scan pipeline for the Bamendjou options screener
(FastAPI / Python 3.11).

Your owned files:
  - backend/app/routers/scan.py                   (CREATE)
  - backend/app/schemas/__init__.py               (MODIFY — append 3 new classes only)
  - backend/app/main.py                           (MODIFY — 2 lines only)

Do not modify any other file.
Implement the full pipeline as specified in Sections 5 and 6.
Wrap each symbol's processing in try/except so one bad symbol never crashes the scan.
Run the verification in Section 8 after implementation.
Commit after all checks pass.
```
