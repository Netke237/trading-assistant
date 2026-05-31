# Stream A–G Fix-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 unimplemented or partially-implemented workstreams (A–G) that were audited and found to be incomplete.

**Architecture:** Each task is self-contained. Tasks 1–3 have no cross-dependencies and can be executed in parallel. Tasks 4–7 depend only on their own file sets. Task 6 (scanStore picks) should be done after Task 5 (Step 6 TOP N) because it extends Step 6 behaviour.

**Tech Stack:** Next.js 15 / TypeScript (frontend), FastAPI / Python (backend), Zustand v5, pytest

---

## Task 1 — Stream C: Fix settingsStore field names and defaults

**Files:**
- Modify: `frontend/lib/settingsStore.ts`
- Modify: `frontend/app/(frame)/settings/page.tsx`

**Context:** The audit found that `maxContracts` (default 5) and `maxPrice` (default 10) were implemented but the spec requires `maxContractsPerChain` (default 10) and `maxContractPrice` (default $50). The store is at version 9 and the migration backfills wrong defaults.

- [ ] **Step 1: Rename fields and fix defaults in settingsStore.ts**

In `frontend/lib/settingsStore.ts`, replace the interface, state, setters, reset, partialize, and migration so that:

```typescript
// interface SettingsState — change two field declarations:
  maxContractsPerChain: number;   // was maxContracts
  maxContractPrice:     number;   // was maxPrice
  setMaxContractsPerChain: (n: number) => void;  // was setMaxContracts
  setMaxContractPrice:     (n: number) => void;  // was setMaxPrice

// initial state:
      maxContractsPerChain: 10,   // was maxContracts: 5
      maxContractPrice:     50,   // was maxPrice: 10

// setters:
      setMaxContractsPerChain: (n) => set({ maxContractsPerChain: n }),
      setMaxContractPrice:     (n) => set({ maxContractPrice: n }),

// resetToDefaults:
        maxContractsPerChain: 10,
        maxContractPrice:     50,

// partialize:
        maxContractsPerChain: state.maxContractsPerChain,
        maxContractPrice:     state.maxContractPrice,

// migrate — version < 9 branch (fix the wrong defaults):
        if (version < 9) {
          return { ...prev, maxContractsPerChain: 10, maxContractPrice: 50 } as unknown as SettingsState;
        }

// Keep version: 9 — no bump needed, migration logic is corrected in place.
```

- [ ] **Step 2: Update ScanForm in settings/page.tsx**

In `frontend/app/(frame)/settings/page.tsx`, update `ScanForm` to use the new names:

```tsx
function ScanForm() {
  const {
    shortlistMaxCandidates, setShortlistMaxCandidates,
    maxContractsPerChain, setMaxContractsPerChain,
    maxContractPrice, setMaxContractPrice,
  } = useSettingsStore();
  const [continuous, setContinuous] = useState(false);
  const [cadence, setCadence] = useState(60);

  return (
    <>
      <SectionIntro
        title="Scan behaviour"
        blurb="Continuous scan automatically re-runs the screener on a schedule."
      />
      <Row label="Continuous scan" hint="Auto-run the screener in the background" defaultValue="Off">
        <Toggle defaultOn={continuous} onChange={(on) => setContinuous(on)} />
      </Row>
      <Row label="Cadence (minutes)" hint="How often to re-run — 5 min to 24 h" defaultValue="60">
        <input
          type="number"
          className={styles.input}
          min={5}
          max={1440}
          value={cadence}
          disabled={!continuous}
          onChange={(e) => {
            const val = Number(e.target.value);
            setCadence(val < 5 ? 5 : val > 1440 ? 1440 : val);
          }}
        />
      </Row>
      <Row
        label="Shortlist max candidates"
        hint="Cap on how many stocks pass the score gate per scan (1–50)"
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={50}
          value={shortlistMaxCandidates}
          onChange={(e) => {
            const val = Number(e.target.value);
            if (val >= 1 && val <= 50) setShortlistMaxCandidates(val);
          }}
        />
      </Row>
      <Row
        label="Max contracts per chain"
        hint="How many contracts to show per candidate in Step 6 (1–20)"
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={20}
          value={maxContractsPerChain}
          onChange={(e) => {
            const val = Number(e.target.value);
            if (val >= 1 && val <= 20) setMaxContractsPerChain(val);
          }}
        />
      </Row>
      <Row
        label="Max contract price ($)"
        hint="Exclude contracts priced above this premium (0.50–500)"
        defaultValue="50"
      >
        <input
          type="number"
          className={styles.input}
          min={0.5}
          max={500}
          step={0.5}
          value={maxContractPrice}
          onChange={(e) => {
            const val = Number(e.target.value);
            if (val >= 0.5 && val <= 500) setMaxContractPrice(val);
          }}
        />
      </Row>
    </>
  );
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/settingsStore.ts "frontend/app/(frame)/settings/page.tsx"
git commit -m "fix(settings): rename maxContracts→maxContractsPerChain (default 10), maxPrice→maxContractPrice (default $50)"
```

---

## Task 2 — Stream B: Fix HMM lookback and MIN_BARS

**Files:**
- Modify: `backend/app/routers/regime.py` line 147
- Modify: `backend/app/services/regime_hmm.py` line 18

**Context:** Lookback is still `days=120` (spec: 55) and `MIN_BARS = 500` (spec: 200). With ~416 bars available in 60 days, the HMM almost never fires.

- [ ] **Step 1: Change lookback in regime.py**

In `backend/app/routers/regime.py` line 147, change:
```python
        intra_bars = fetch_intraday_candles('SPY', interval='15min', days=120)
```
to:
```python
        intra_bars = fetch_intraday_candles('SPY', interval='15min', days=55)
```

- [ ] **Step 2: Change MIN_BARS in regime_hmm.py**

In `backend/app/services/regime_hmm.py` line 18, change:
```python
MIN_BARS = 500           # minimum 15-min bars needed
```
to:
```python
MIN_BARS = 200           # minimum 15-min bars needed
```

- [ ] **Step 3: Run existing HMM tests**

```bash
cd backend && pytest tests/test_regime_hmm.py tests/test_regime_no_lookahead.py -v
```

Expected: all pass (these tests generate their own bars; the constant change only affects production thresholds).

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/regime.py backend/app/services/regime_hmm.py
git commit -m "fix(hmm): lookback 120→55 days, MIN_BARS 500→200"
```

---

## Task 3 — Stream F: Regime NO_DATA badge

**Files:**
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx`

**Context:** The intraday column fallback renders plain text `"Calculating…"` instead of a `<StatusBadge status="NO_DATA" />`. The SWING and POSITION columns render nothing when `omm` is null.

- [ ] **Step 1: Replace "Calculating…" with StatusBadge**

In `frontend/app/(frame)/screener/step-1-regime/page.tsx`, find the else branch at line ~244:

```tsx
              ) : (
                <Text size={11} tone="dim">Calculating…</Text>
              )}
```

Replace with:
```tsx
              ) : (
                <StatusBadge status="NO_DATA" />
              )}
```

- [ ] **Step 2: Add NO_DATA badge to SWING and POSITION null fallbacks**

Find the SWING column (line ~270) which currently renders `null` when `omm` is falsy:
```tsx
              ) : null}
```
Replace both occurrences (SWING and POSITION) with:
```tsx
              ) : (
                <StatusBadge status="NO_DATA" />
              )}
```

- [ ] **Step 3: Verify StatusBadge is already imported**

Check the import at the top of `step-1-regime/page.tsx`. `StatusBadge` should already be imported. If not, add:
```tsx
import { StatusBadge } from '@/components/atoms/StatusBadge';
```

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-1-regime/page.tsx"
git commit -m "fix(regime): replace Calculating text with NO_DATA StatusBadge for missing intraday/omm data"
```

---

## Task 4 — Stream A: Wire validate_contract() into /api/contracts

**Files:**
- Modify: `backend/app/routers/contracts.py`
- Modify: `backend/app/fixtures/contracts.py` (add open_interest)
- Create: `backend/tests/test_contracts_scoring.py`

**Context:** `/api/contracts` returns all contracts with `score: 0` (hardcoded in `market.py`). `validate_contract()` exists in `backend/app/scoring/contract_validator.py` and is already used by the scan pipeline. The fix is to call it on each raw dict returned by `fetch_option_chain`, then sort by score descending.

The `validate_contract(contract: dict, stock_score: int)` function expects a dict with keys:
- `symbol`, `strike`, `expiry` — present in raw dict
- `is_call` — derive from `right == 'C'`
- `delta` — present
- `bid`, `ask` — derive: `bid = price - spread/2`, `ask = price + spread/2`
- `volume`, `open_interest` — present in production raw dict; missing from test fixtures
- `iv_rank` — map from `ivRank` (raw dict uses camelCase)

- [ ] **Step 1: Add open_interest to MOCK_CONTRACTS so tests produce real scores**

In `backend/app/fixtures/contracts.py`, add `open_interest` to the OptionContract schema calls. First add the field to `OptionContract` in `backend/app/schemas/__init__.py`:

```python
class OptionContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    symbol: str
    strike: int
    expiry: str
    right: OptionRight
    dte: int
    dteTotal: int
    price: float
    delta: float
    theta: float
    ivRank: int
    ivPercentile: int
    spread: float
    volume: int
    openInterest: int = Field(default=0, validation_alias=AliasChoices('openInterest', 'open_interest'))
    score: int
```

Then update `backend/app/fixtures/contracts.py` to add realistic open interest values:
```python
OptionContract(
    id='AAPL|190|2026-05-15|C', symbol='AAPL', strike=190,
    expiry='2026-05-15', right='C', dte=24, dteTotal=38,
    price=4.85, delta=0.45, theta=-0.11,
    ivRank=42, ivPercentile=51, spread=0.05, volume=8420, openInterest=15200, score=82,
),
OptionContract(
    id='AAPL|195|2026-05-15|C', symbol='AAPL', strike=195,
    expiry='2026-05-15', right='C', dte=24, dteTotal=38,
    price=3.10, delta=0.38, theta=-0.10,
    ivRank=45, ivPercentile=54, spread=0.06, volume=6180, openInterest=11400, score=78,
),
OptionContract(
    id='AAPL|190|2026-06-19|C', symbol='AAPL', strike=190,
    expiry='2026-06-19', right='C', dte=59, dteTotal=71,
    price=7.90, delta=0.48, theta=-0.07,
    ivRank=38, ivPercentile=46, spread=0.08, volume=3250, openInterest=8900, score=73,
),
OptionContract(
    id='AAPL|200|2026-05-15|C', symbol='AAPL', strike=200,
    expiry='2026-05-15', right='C', dte=24, dteTotal=38,
    price=1.85, delta=0.32, theta=-0.09,
    ivRank=48, ivPercentile=58, spread=0.07, volume=4710, openInterest=7300, score=67,
),
OptionContract(
    id='AAPL|185|2026-04-24|C', symbol='AAPL', strike=185,
    expiry='2026-04-24', right='C', dte=3, dteTotal=17,
    price=1.20, delta=0.58, theta=-0.25,
    ivRank=61, ivPercentile=68, spread=0.04, volume=11850, openInterest=19600, score=54,
),
OptionContract(
    id='AAPL|210|2026-05-15|C', symbol='AAPL', strike=210,
    expiry='2026-05-15', right='C', dte=24, dteTotal=38,
    price=0.72, delta=0.22, theta=-0.08,
    ivRank=52, ivPercentile=62, spread=0.12, volume=1940, openInterest=3100, score=42,
),
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_contracts_scoring.py`:

```python
"""Tests: /api/contracts returns scored contracts sorted by score descending."""
import pytest


def test_contracts_scores_are_not_all_zero(client):
    """validate_contract() must be called — raw score=0 fallback is gone."""
    r = client.get("/api/contracts")
    assert r.status_code == 200
    data = r.json()
    scores = [c["score"] for c in data]
    assert any(s > 0 for s in scores), f"All scores are 0: {scores}"


def test_contracts_sorted_by_score_descending(client):
    """Contracts must be sorted highest score first."""
    r = client.get("/api/contracts")
    data = r.json()
    scores = [c["score"] for c in data]
    assert scores == sorted(scores, reverse=True), f"Not sorted desc: {scores}"


def test_contracts_score_field_present(client):
    """Every returned contract has a 'score' key."""
    r = client.get("/api/contracts")
    data = r.json()
    for c in data:
        assert "score" in c, f"Missing score on {c.get('id')}"


def test_contracts_high_quality_scores_higher(client):
    """AAPL|190|2026-05-15|C has better liquidity/spread than AAPL|185|2026-04-24|C
    (dte=3 is too short). The 24-DTE contract must outrank the 3-DTE one."""
    r = client.get("/api/contracts")
    data = r.json()
    by_id = {c["id"]: c["score"] for c in data}
    score_good = by_id.get("AAPL|190|2026-05-15|C", -1)
    score_short_dte = by_id.get("AAPL|185|2026-04-24|C", -1)
    assert score_good > score_short_dte, (
        f"24-DTE contract ({score_good}) should outscore 3-DTE ({score_short_dte})"
    )
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_contracts_scoring.py -v
```

Expected: `test_contracts_scores_are_not_all_zero` FAILS (all scores are 0 currently).

- [ ] **Step 4: Implement scoring in contracts.py**

Replace `backend/app/routers/contracts.py` entirely:

```python
from fastapi import APIRouter, Query
from app.schemas import OptionContract
from app.data.market import fetch_option_chain
from app.scoring.contract_validator import validate_contract

router = APIRouter(prefix='/api', tags=['trading'])


def _to_validator_dict(raw: dict) -> dict:
    """Map fetch_option_chain / OptionContract.model_dump dict to validate_contract format."""
    price  = float(raw.get("price") or 0)
    spread = float(raw.get("spread") or 0)
    return {
        **raw,
        "is_call":        raw.get("right") == "C",
        "iv_rank":        raw.get("ivRank") or raw.get("iv_rank") or 0,
        "bid":            round(price - spread / 2, 4),
        "ask":            round(price + spread / 2, 4),
        "open_interest":  raw.get("openInterest") or raw.get("open_interest") or 0,
    }


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(
    symbol: str = Query(default='AAPL'),
    right: str = Query(default='C'),
) -> list[OptionContract]:
    opt_type = 'C' if right.upper() == 'C' else 'P'
    raw_list = fetch_option_chain(symbol.upper(), option_type=opt_type) or []

    scored: list[dict] = []
    for raw in raw_list:
        card = validate_contract(_to_validator_dict(raw), stock_score=50)
        scored.append({**raw, "score": card.score})

    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_contracts_scoring.py tests/test_routes.py -v
```

Expected: all 4 new tests pass; existing `test_contracts_length_and_id` still passes (6 contracts, id check). Note: the first-position id assertion in `test_contracts_length_and_id` checks `data[0]["id"] == "AAPL|190|2026-05-15|C"` — this should still pass because that contract should have the highest score after real validation.

If `test_contracts_length_and_id` fails on the id check, update it to just verify the response is 200 and length is 6 (the ordering may legitimately change with real scoring).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/contracts.py backend/app/schemas/__init__.py \
        backend/app/fixtures/contracts.py backend/tests/test_contracts_scoring.py
git commit -m "feat(contracts): score every contract via validate_contract(), sort by score desc"
```

---

## Task 5 — Stream D: Step 6 TOP N — score-anchored recommended

**Files:**
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx`

**Context:** `recommended = sorted[0]` uses the user's current sort order, not score. If sorted by DTE ascending, the shortest-DTE contract becomes "recommended". The section label is `A — RECOMMENDED`; spec requires `TOP N`.

- [ ] **Step 1: Split top-pick computation from sort**

In `step-6-contracts/page.tsx`, inside the `candidates.map()` at line ~115, change:

```tsx
            const sorted = sortContracts(contracts, sortKey, sortDir);
            const recommended = sorted[0];
            const chain = sorted.slice(1);
```

to:

```tsx
            const sorted = sortContracts(contracts, sortKey, sortDir);
            // Top contract is always highest score, regardless of current sort column.
            const topContract = [...contracts].sort((a, b) => b.score - a.score)[0];
            const chain = sorted.filter((c) => c.id !== topContract?.id);
```

Then replace every reference to `recommended` in the render with `topContract`.

- [ ] **Step 2: Rename section label**

Find:
```tsx
                          <Text size={10} tone="dim" weight={500}>A — RECOMMENDED</Text>
```

Replace with:
```tsx
                          <Text size={10} tone="dim" weight={500}>TOP N</Text>
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-6-contracts/page.tsx"
git commit -m "fix(step6): anchor recommended to highest-score contract regardless of sort; rename section to TOP N"
```

---

## Task 6 — Stream E: pickedContracts + contractsBySymbol in scanStore + User-selected badge in Step 7

**Files:**
- Modify: `frontend/lib/scanStore.ts`
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`

**Context:** When the user picks a contract in Step 6 and navigates to Step 7, the pick is lost because it lives in local component state. `pickedContracts` (symbol → contractId) and `contractsBySymbol` (symbol → contracts array) need to persist in the scanStore so Step 7 can read them and show a "User-selected" badge when the user's pick differs from the score-anchored top contract.

**Note:** Complete Task 5 before this task, as Step 6 now uses `topContract` instead of `recommended`.

- [ ] **Step 1: Add pickedContracts and contractsBySymbol to scanStore**

In `frontend/lib/scanStore.ts`, add to the `ScanStoreState` interface:

```typescript
  /** User's contract pick per symbol: symbol → contractId */
  pickedContracts:    Record<string, string>;
  /** Contracts loaded in Step 6 per symbol */
  contractsBySymbol:  Record<string, import('@/types/domain').OptionContract[]>;
  setPickedContract:  (symbol: string, contractId: string) => void;
  setContractsBySymbol: (bySymbol: Record<string, import('@/types/domain').OptionContract[]>) => void;
```

Add initial state in the `create` call:
```typescript
      pickedContracts:      {},
      contractsBySymbol:    {},
      setPickedContract:    (symbol, id) =>
        set((s) => ({ pickedContracts: { ...s.pickedContracts, [symbol]: id } })),
      setContractsBySymbol: (bySymbol) => set({ contractsBySymbol: bySymbol }),
```

Do NOT add these to `partialize` — they're session-only state, no localStorage persistence needed.

- [ ] **Step 2: Wire Step 6 to write picks into the store**

In `frontend/app/(frame)/screener/step-6-contracts/page.tsx`, add store selectors:

```tsx
  const setPickedContract    = useScanStore((s) => s.setPickedContract);
  const setContractsBySymbol = useScanStore((s) => s.setContractsBySymbol);
```

In the `useEffect` that calls `api.getContracts`, after building `bySymbol`, also write it to the store:

```tsx
        setContractsBySymbol(bySymbol);
```

Where `setPick(c.id)` is called (when user clicks a row), also call:

```tsx
        setPickedContract(candidate.symbol, c.id);
```

Replace all `onClick={() => setPick(c.id)}` occurrences with the two-call version. There are two locations: the `topContract` row and each `chain` row. Example:

```tsx
              onClick={() => {
                setPick(c.id);
                setPickedContract(candidate.symbol, c.id);
              }}
```

Also set the initial pick in the store when contracts first load:

```tsx
        // In the useEffect, after setting pick for the first contract:
        if (first && candidates[0]) {
          setPick(first.id);
          setPickedContract(candidates[0].symbol, first.id);
        }
```

- [ ] **Step 3: Add User-selected badge in Step 7**

In `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, add store selectors near the top of the component:

```tsx
  const pickedContracts   = useScanStore((s) => s.pickedContracts);
  const contractsBySymbol = useScanStore((s) => s.contractsBySymbol);
```

Find the `<TradeCard ... />` render and add a badge above or inside it when the user's pick differs from the top-score contract:

```tsx
{(() => {
  const symbol    = candidates[currentIdx]?.symbol;
  const contracts = symbol ? contractsBySymbol[symbol] ?? [] : [];
  const topId     = [...contracts].sort((a, b) => b.score - a.score)[0]?.id;
  const pickedId  = symbol ? pickedContracts[symbol] : undefined;
  const isOverride = pickedId && topId && pickedId !== topId;
  return isOverride ? (
    <div style={{ marginBottom: 8 }}>
      <Text size={11} tone="caution" weight={500}>User-selected · overrides top-ranked contract</Text>
    </div>
  ) : null;
})()}
```

Place this block immediately before the `<TradeCard />` call.

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/scanStore.ts \
        "frontend/app/(frame)/screener/step-6-contracts/page.tsx" \
        "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(scan): persist pickedContracts + contractsBySymbol in scanStore; User-selected badge in Step 7"
```

---

## Task 7 — Stream G: FVG detection

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Create: `backend/tests/test_fvg.py`

**Context:** Fair Value Gap (FVG) is a 3-candle pattern. A bullish FVG: `bars[i].high < bars[i+2].low` (a gap between bar 1's high and bar 3's low that price has not yet filled). A bearish FVG: `bars[i].low > bars[i+2].high`. When the current close is inside a recent unfilled FVG, the pullback score gets a soft +8 confluence bonus. Two fields are added to the pullback detail dict: `fvg_hit` (bool) and `fvg_gap` (float, size of the gap in price terms, 0.0 if no hit).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_fvg.py`:

```python
"""Tests for _detect_fvg() and the pullback bonus it contributes."""
import pytest
from app.scoring.stock_scorer import _detect_fvg


def _make_bars(highs, lows, closes=None):
    """Build minimal bar dicts from parallel high/low/close lists."""
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return [
        {"high": h, "low": l, "close": c, "open": l, "volume": 1000}
        for h, l, c in zip(highs, lows, closes)
    ]


def test_detect_bullish_fvg():
    """Bar 1 high < Bar 3 low → bullish FVG; current price inside gap → fvg_hit=True."""
    # bars[0].high=100, bars[2].low=102 → gap 100–102
    # current close=101 → inside gap
    bars = _make_bars(
        highs=[100, 103, 105],
        lows=[98,  100, 102],
        closes=[99, 101, 101],
    )
    result = _detect_fvg(bars)
    assert result is not None
    assert result["fvg_hit"] is True
    assert result["fvg_gap"] == pytest.approx(2.0)


def test_detect_no_fvg_when_gap_filled():
    """If current close is outside the FVG range, fvg_hit=False but gap is still measured."""
    bars = _make_bars(
        highs=[100, 103, 105],
        lows=[98,  100, 102],
        closes=[99, 101, 108],  # close=108 is above the gap (102–100), not inside it
    )
    result = _detect_fvg(bars)
    # Gap exists (bar0.high=100 < bar2.low=102) but current price is not in it
    assert result is not None
    assert result["fvg_hit"] is False


def test_no_fvg_when_bars_overlap():
    """Bars that overlap (no gap) → returns None."""
    bars = _make_bars(
        highs=[100, 103, 101],   # bar2.low=99 < bar0.high=100 → no gap
        lows=[98,  100, 99],
        closes=[99, 101, 100],
    )
    result = _detect_fvg(bars)
    assert result is None


def test_detect_fvg_insufficient_bars():
    """Fewer than 3 bars → returns None."""
    bars = _make_bars(highs=[100, 103], lows=[98, 100])
    result = _detect_fvg(bars)
    assert result is None


def test_fvg_gap_size():
    """Gap size is bar2.low - bar0.high for a bullish FVG."""
    bars = _make_bars(
        highs=[100, 104, 106],
        lows=[97,  102, 103],
        closes=[99, 103, 104],  # close=104 is above gap (100–103) → not inside
    )
    result = _detect_fvg(bars)
    assert result is not None
    assert result["fvg_gap"] == pytest.approx(3.0)  # 103 - 100
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && pytest tests/test_fvg.py -v
```

Expected: ImportError — `_detect_fvg` does not exist yet.

- [ ] **Step 3: Implement _detect_fvg in stock_scorer.py**

Add this function to `backend/app/scoring/stock_scorer.py` after the `_adx` helper and before the first scoring rule function:

```python
def _detect_fvg(bars: list[dict]) -> dict | None:
    """
    Detect the most recent unfilled Fair Value Gap in `bars`.

    A bullish FVG exists between three consecutive candles when
    bars[i].high < bars[i+2].low (a price gap that has not been filled).

    Returns:
        {'fvg_hit': bool, 'fvg_gap': float}  where fvg_gap = gap size in points.
        fvg_hit is True when the final bar's close is inside the gap zone.
        Returns None when no FVG pattern is found in the last 10 candles.
    """
    if len(bars) < 3:
        return None

    window = bars[-10:] if len(bars) >= 10 else bars
    current_close = float(bars[-1]["close"])

    # Scan from newest to oldest 3-bar window
    for i in range(len(window) - 3, -1, -1):
        b0_high = float(window[i]["high"])
        b2_low  = float(window[i + 2]["low"])

        if b0_high < b2_low:
            # Bullish FVG: gap between b0.high and b2.low
            gap_size = round(b2_low - b0_high, 4)
            fvg_hit  = b0_high <= current_close <= b2_low
            return {"fvg_hit": fvg_hit, "fvg_gap": gap_size}

        b0_low  = float(window[i]["low"])
        b2_high = float(window[i + 2]["high"])
        if b0_low > b2_high:
            # Bearish FVG: gap between b2.high and b0.low
            gap_size = round(b0_low - b2_high, 4)
            fvg_hit  = b2_high <= current_close <= b0_low
            return {"fvg_hit": fvg_hit, "fvg_gap": gap_size}

    return None
```

- [ ] **Step 4: Run FVG tests**

```bash
cd backend && pytest tests/test_fvg.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Wire FVG bonus into pullback rule**

Find the pullback scoring rule in `backend/app/scoring/stock_scorer.py`. It populates a `detail` dict with keys like `fib_level`, `retracement_pct`, etc. Add FVG detection at the end of the pullback rule, after the base score is computed, and before returning the `RuleResult`:

```python
    # FVG confluence bonus (+8 soft if price is inside a recent Fair Value Gap)
    fvg = _detect_fvg(bars) if bars else None
    fvg_hit  = fvg["fvg_hit"]  if fvg else False
    fvg_gap  = fvg["fvg_gap"]  if fvg else 0.0
    if fvg_hit:
        score = min(100, score + 8)

    detail = {
        **detail,   # existing pullback detail keys
        "fvg_hit":  fvg_hit,
        "fvg_gap":  fvg_gap,
    }
```

(Insert this block just before the `return RuleResult(...)` in the pullback rule.)

- [ ] **Step 6: Run all backend tests**

```bash
cd backend && pytest -v
```

Expected: all pass (no regressions). The pullback score changes slightly for some test inputs; if existing tests assert exact pullback scores, update them to accept the +8 FVG bonus range.

- [ ] **Step 7: Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_fvg.py
git commit -m "feat(scoring): add _detect_fvg() with +8 pullback confluence bonus; fvg_hit/fvg_gap in detail"
```

---

## Task 8 — Stream H: Score detail Pydantic models (deferred)

Stream H requires adding Pydantic detail models for each `RuleResult`, wiring them through `ScanResult` → `TradeCardData`, and consuming them in the Step 4 ranking cards as dim explanatory lines. This is the most invasive change: it touches the scan pipeline, all schema models, and the frontend ranking UI.

**Defer until streams A–G are merged.** When ready, the key steps are:
1. Add `class PullbackDetail(BaseModel)` etc. for each of the 5 rule names to `backend/app/schemas/__init__.py`
2. Add a `detail: Optional[RuleDetailUnion]` field to `ScoreBreakdown`
3. Populate it in `scan.py` when building `ScoreBreakdown` from `StockScoreCard.rules`
4. In Step 4 frontend, read `candidate.breakdown.trend.detail` etc. and render as `<Text size={11} tone="dim">` lines below each score bar

---

## Self-Review Against Audit Findings

| Stream | Task | Audit issue | Addressed? |
|--------|------|-------------|-----------|
| C | 1 | Wrong field names + defaults | ✅ Renamed + corrected |
| B | 2 | days=120 (need 55), MIN_BARS=500 (need 200) | ✅ Fixed |
| F | 3 | "Calculating…" text instead of NO_DATA badge | ✅ Fixed |
| A | 4 | score=0 hardcoded, validate_contract() not called | ✅ Wired in |
| D | 5 | Recommended is sort-dependent, label wrong | ✅ Score-anchored + renamed |
| E | 6 | pickedContracts/contractsBySymbol not in store, no badge | ✅ Added |
| G | 7 | _detect_fvg() missing entirely | ✅ Implemented |
| H | 8 | Complex, deferred | ⏳ Deferred |

**Placeholder scan:** No TBD, TODO, or vague steps found. All code blocks are complete.

**Type consistency:** `pickedContracts: Record<string, string>` and `contractsBySymbol: Record<string, OptionContract[]>` used consistently across Tasks 6. `_detect_fvg` named consistently across Tasks 7.
