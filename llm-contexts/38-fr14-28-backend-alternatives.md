# Context Doc 38 — FR-14/28 Backend: AlternativeContract schema + scanner runner-ups

**Workstream:** WT-7a — Add `AlternativeContract` to the schema and attach runner-up contracts to every `TradeCardData` produced by the scanner
**Conflict class:** Low — modifies two backend files only (`schemas/__init__.py`, `routers/scan.py`)

---

## 1. Mission

The scanner currently calls `max(valid_scores, ...)` and discards every contract except the winner. `valid_scores` already contains all scored, non-rejected contracts — the runner-ups exist but are thrown away. This workstream:

1. Adds an `AlternativeContract` Pydantic model to the schema.
2. Adds `alternatives: list[AlternativeContract] = []` and `alternativesCount: int = 0` to `TradeCardData`.
3. Changes the scanner to keep the top-3 valid contracts, use the first as the primary (existing behaviour), and attach positions 2–3 as `alternatives` with a generated `reason` string and their own `rrRatio`.

The frontend already has the matching TypeScript types and mock data (from WT-6). Once this lands, `GET /api/tradecards` returns the populated `alternatives` array automatically because it reads from the persisted `ScanResult`.

---

## 2. Owned files

| File | Action |
|---|---|
| `backend/app/schemas/__init__.py` | Add `AlternativeContract` model; add `alternatives` + `alternativesCount` fields to `TradeCardData` |
| `backend/app/routers/scan.py` | Replace single `max()` with sorted top-N; build and attach `AlternativeContract` objects |

Do not touch any other file.

---

## 3. Read-only references

| File | Why |
|---|---|
| `backend/app/scoring/contract_validator.py` | `ContractScoreCard` dataclass — fields you read: `score`, `status`, `breakdown` (has `dte_score`, `delta_score`, `iv_rank_score`, `liquidity_score`, `spread_score`) |
| `backend/app/scoring/reward_risk.py` | `estimate_rr(stock_price, target_price, invalidation_price, strike, expiry_years, current_premium, is_call, heston_params) -> RrResult` — fields you use: `rr_ratio`, `model_used` |
| `backend/app/schemas/__init__.py` | Existing `ContractScoreBreakdown`, `TradeCardData`, `RrModel` — match field names exactly |
| `frontend/types/domain.ts` lines 171–187 | The TypeScript `AlternativeContract` interface — your Pydantic model must be field-for-field compatible with it |

---

## 4. Schema changes

### 4a. New model — add above `TradeCardData`

```python
class AlternativeContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:             str
    strike:             int
    expiry:             str
    right:              OptionRight          # 'C' | 'P'
    dte:                int
    mid:                float
    delta:              float
    theta:              float
    ivRank:             int
    score:              int
    contractConfidence: Status
    contractBreakdown:  ContractScoreBreakdown
    rrRatio:            float
    rrModel:            RrModel
    reason:             str
```

### 4b. Add two optional fields to `TradeCardData`

```python
class TradeCardData(BaseModel):
    ...                                          # all existing fields unchanged
    alternatives:      list[AlternativeContract] = []
    alternativesCount: int = 0
```

Add these at the end of `TradeCardData` so field order doesn't shift for existing JSON.

---

## 5. Scanner changes (routers/scan.py)

### What to change

Find this block (around line 225–232):

```python
valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
if not valid_scores:
    rejected.append(...)
    continue

best_score, contract = max(valid_scores, key=lambda x: x[0].score)
contract_card: ContractScoreCard = best_score
```

Replace with:

```python
valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
if not valid_scores:
    rejected.append(...)
    continue

# Sort descending by score; primary = index 0, alternatives = indices 1–2
valid_scores.sort(key=lambda x: x[0].score, reverse=True)
best_score, contract = valid_scores[0]
contract_card: ContractScoreCard = best_score
runner_ups = valid_scores[1:3]   # up to 2 alternatives
```

### Building the AlternativeContract objects

After building the `trade_card` (around line 347), before `candidates.append(trade_card)`, attach alternatives:

```python
alts: list[AlternativeContract] = []
for alt_card, alt_c in runner_ups:
    alt_strike = float(alt_c.get("strike", price))
    alt_expiry_years = alt_c.get("dte", 30) / 365.0
    alt_premium = float(alt_c.get("price", 0.10))
    alt_rr = estimate_rr(
        stock_price=price,
        target_price=target_price,
        invalidation_price=invalidation_price,
        strike=alt_strike,
        expiry_years=alt_expiry_years,
        current_premium=alt_premium,
        is_call=(req.direction == "Bullish"),
        heston_params=heston_params,
    )
    alts.append(AlternativeContract(
        symbol=symbol,
        strike=int(alt_strike),
        expiry=alt_c.get("expiry", "TBD"),
        right="C" if req.direction == "Bullish" else "P",
        dte=int(alt_c.get("dte", 30)),
        mid=round(float(alt_c.get("price", 0)), 2),
        delta=round(float(alt_c.get("delta", 0.45)), 3),
        theta=round(float(alt_c.get("theta", -0.05)), 3),
        ivRank=int(alt_c.get("ivRank", 50)),
        score=alt_card.score,
        contractConfidence=alt_card.status,
        contractBreakdown=ContractScoreBreakdown(
            dteFit=alt_card.breakdown.dte_score,
            delta=alt_card.breakdown.delta_score,
            ivAttractiveness=alt_card.breakdown.iv_rank_score,
            liquidity=alt_card.breakdown.liquidity_score,
            spread=alt_card.breakdown.spread_score,
        ),
        rrRatio=alt_rr.rr_ratio,
        rrModel=alt_rr.model_used,
        reason=_alt_reason(alt_c, contract, is_call=(req.direction == "Bullish")),
    ))

trade_card.alternatives = alts
trade_card.alternativesCount = len(alts)
```

### Reason helper function

Add this pure function near the top of `scan.py` (after imports, before the router):

```python
def _alt_reason(alt: dict, primary: dict, *, is_call: bool) -> str:
    """Generate a one-line rationale comparing an alternative contract to the primary."""
    alt_strike = float(alt.get("strike", 0))
    pri_strike = float(primary.get("strike", 0))
    alt_dte    = int(alt.get("dte", 0))
    pri_dte    = int(primary.get("dte", 0))

    parts: list[str] = []
    if alt_dte > pri_dte + 7:
        parts.append("longer DTE — more time for thesis to develop")
    elif alt_dte < pri_dte - 7:
        parts.append("shorter DTE — lower theta cost")

    if is_call:
        if alt_strike < pri_strike - 1:
            parts.append("lower strike — higher delta, more directional exposure")
        elif alt_strike > pri_strike + 1:
            parts.append("higher strike — lower cost, higher leverage if stock moves strongly")
    else:
        if alt_strike > pri_strike + 1:
            parts.append("higher strike — higher delta for downside move")
        elif alt_strike < pri_strike - 1:
            parts.append("lower strike — lower cost, higher leverage on further decline")

    return "; ".join(parts) if parts else "similar profile — alternative liquidity/spread characteristics"
```

---

## 6. Import checklist

`AlternativeContract` is a new schema class. Make sure it is imported in `scan.py`:

```python
from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
    ScanDelta, ContinuousScanConfig, ScanState,
    AlternativeContract,          # ← add this
)
```

---

## 7. Test requirement

Add one test to `backend/tests/` that verifies:

- After a mocked scan run, each `TradeCardData` in `result.candidates` with more than one valid contract has `alternativesCount >= 1` and `alternatives` is non-empty.
- Each `AlternativeContract` in `alternatives` has `score < primary contractScore` (runner-up, not better than the winner).
- All 136 existing tests still pass.

Use the existing test patterns (mock `fetch_option_chain`, `fetch_candles`, `fetch_price`). Look at `backend/tests/test_scan_*.py` for examples.

---

## 8. Hard rules

- Do not modify `contract_validator.py`, `reward_risk.py`, or any other file.
- `trade_card.alternatives` is set after the `TradeCardData(...)` constructor call, not inside it — Pydantic v2 allows attribute assignment on models with `model_config = ConfigDict(populate_by_name=True)`.
- Alternatively, pass `alternatives=alts, alternativesCount=len(alts)` directly in the constructor — either approach is fine.
- `runner_ups = valid_scores[1:3]` — maximum 2 alternatives; never more, even if many valid contracts exist.
- If a symbol has only one valid contract, `alternatives = []`, `alternativesCount = 0`. This is the default, so no special case needed.
- `estimate_rr` for alternatives reuses the same `heston_params` and `target_price`/`invalidation_price` as the primary — do not call `calibrate_heston` again.
- `npm run typecheck` is not your concern — frontend is a separate worktree. Run `pytest backend/tests/ -v` only.

---

## 9. Acceptance criteria

- `pytest backend/tests/ -v` → all tests pass (136 existing + new test = 137+).
- A scan on a universe with 2+ valid contracts per symbol produces `alternatives` with 1–2 entries per candidate.
- A scan on a universe where each symbol has only one valid contract produces `alternatives = []` and `alternativesCount = 0` — no crash.
- `GET /api/tradecards` after a scan returns the `alternatives` array (it reads from the persisted `ScanResult` — no extra wiring needed).

---

## 10. Dev workflow

```bash
cd backend
python -m pytest tests/ -v          # must stay green throughout
uvicorn app.main:app --reload       # integration smoke-test
# POST /api/scan {"universe":["AAPL","NVDA"],"direction":"Bullish","horizon":"Swing","overrides":{}}
# GET /api/tradecards  →  each candidate should have alternatives[] populated
```
