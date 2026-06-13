# Scan Log Pipeline Funnel + Tradier Live Settings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured per-stage pipeline counters to both the options scan (Step 3) and stock scan (Step 6), show a funnel summary alongside the existing log, clean up scan-type-crossing noise in rejection reasons, and add a Tradier Live credential section to Settings → Brokers.

**Architecture:**  
Backend adds `OptionsPipeline` / `StockPipeline` Pydantic models to the result schemas and counts per-stage rejections in the scan routers. The options scan also renames "stock REJECT" reason strings to clearer prefixes ("Pre-screen:" / "Score gate:") so the frontend can categorise them without string hacks. Frontend extends result types to carry pipeline counts, creates a new `ScanFunnel` organism, shows it in Step 3 (options) and Step 6 (stock backtest), and adds a Tradier Live form to Settings.

**Tech Stack:** FastAPI + Pydantic v2, pytest; Next.js 15 App Router, TypeScript 5.7 strict, CSS Modules, Zustand v5.

---

### Task 1: Backend — `OptionsPipeline` schema + add to `ScanResult`

**Files:**
- Modify: `backend/app/schemas/__init__.py` (around line 388 — between `RejectedCandidate` and `ScanResult`)

- [ ] **Step 1: Add `OptionsPipeline` model**

Open `backend/app/schemas/__init__.py`. After the `RejectedCandidate` class (around line 387) and before `class ScanResult`, insert:

```python
class OptionsPipeline(BaseModel):
    scanned:          int   # total symbols attempted
    failed_data:      int   # "no market data" + price/cap filters
    failed_pre_screen: int  # Pass 1 score gate (reason starts with "Pre-screen:")
    no_chain:         int   # "no option chain"
    failed_score:     int   # Pass 2 score gate (reason starts with "Score gate:")
    failed_contracts: int   # "all contracts rejected"
    candidates:       int   # made it through everything
```

- [ ] **Step 2: Add `pipeline` field to `ScanResult`**

In the same file, add `pipeline: Optional[OptionsPipeline] = None` to `ScanResult`:

```python
class ScanResult(BaseModel):
    scan_id: str
    timestamp: str
    candidates: list[TradeCardData]
    rejected: list[RejectedCandidate]
    state: ScanState = 'COMPLETED'
    previous_run_id: Optional[str] = None
    deltas: list[ScanDelta] = []
    shortlist_truncated: bool = False
    original_count: int = 0
    pipeline: Optional['OptionsPipeline'] = None   # add this line
```

- [ ] **Step 3: Verify backend still imports**

```bash
cd backend && python -c "from app.schemas import ScanResult, OptionsPipeline; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Run existing scan tests**

```bash
cd backend && pytest tests/test_scan_endpoint.py -v
```

Expected: all tests pass (the new optional field has no default impact).

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/schemas/__init__.py
git commit -m "feat(schema): add OptionsPipeline model + optional pipeline field to ScanResult"
```

---

### Task 2: Backend — `StockPipeline` schema + add to `StockScanResult`

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`

- [ ] **Step 1: Add `StockPipeline` model**

At the bottom of `backend/app/schemas/stock_scan.py` (after `StockScanResult`), add:

```python
class StockPipeline(BaseModel):
    scanned:         int   # total symbols attempted
    failed_history:  int   # "insufficient history" / "no price data" / "price $..."
    failed_score:    int   # "REJECT score=..."
    failed_signal:   int   # "no {strategy} setup"
    failed_backtest: int   # "backtest gate: ..."
    other_rejected:  int   # exceptions / unclassified
    candidates:      int
```

- [ ] **Step 2: Add `pipeline` field to `StockScanResult`**

```python
class StockScanResult(BaseModel):
    scan_id:    str
    timestamp:  str
    candidates: list[PositionCardOut]
    rejected:   list[dict]
    pipeline:   Optional['StockPipeline'] = None
```

Add `from typing import Optional` if not already imported (it already is via `from typing import Literal, Optional`).

- [ ] **Step 3: Verify import**

```bash
cd backend && python -c "from app.schemas.stock_scan import StockScanResult, StockPipeline; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/schemas/stock_scan.py
git commit -m "feat(schema): add StockPipeline model + optional pipeline field to StockScanResult"
```

---

### Task 3: Backend — Options scan pipeline counting + log cleanup

**Files:**
- Modify: `backend/app/routers/scan.py`

This task does two things:
1. Renames the two "stock REJECT" reason strings to clearer prefixes so the frontend can identify them without ambiguity.
2. After gathering results, counts per-stage and attaches `OptionsPipeline` to `ScanResult`.

- [ ] **Step 1: Rename Pass 1 rejection reason**

In `backend/app/routers/scan.py` find (around line 285):

```python
        if card_pre.status == "REJECT":
            bd = {r.name: r.score for r in card_pre.rules}
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card_pre.score})"})
            return RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card_pre.score})", breakdown=bd)
```

Replace with:

```python
        if card_pre.status == "REJECT":
            bd = {r.name: r.score for r in card_pre.rules}
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"Pre-screen: score {card_pre.score} rejected"})
            return RejectedCandidate(symbol=symbol, reason=f"Pre-screen: score {card_pre.score} rejected", breakdown=bd)
```

- [ ] **Step 2: Rename Pass 2 rejection reason**

Find (around line 344):

```python
    if card.status == "REJECT":
        bd = {r.name: r.score for r in card.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card.score})"})
        return RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card.score})", breakdown=bd)
```

Replace with:

```python
    if card.status == "REJECT":
        bd = {r.name: r.score for r in card.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"Score gate: score {card.score} rejected"})
        return RejectedCandidate(symbol=symbol, reason=f"Score gate: score {card.score} rejected", breakdown=bd)
```

- [ ] **Step 3: Add pipeline import**

Near the top of the router (around line 33 with other schema imports):

```python
from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
    ScanDelta, ContinuousScanConfig, ScanState, OptionsPipeline,
)
```

- [ ] **Step 4: Count pipeline stages and attach to `ScanResult`**

After the `for result in results:` loop (around line 659, after rejected/candidates lists are built), and before the shortlist cap block, add:

```python
    # ── Pipeline funnel counters ───────────────────────────────────────────────
    _data_kw = ("no market data", "price filter", "cap filter")
    _pipeline = OptionsPipeline(
        scanned=len(symbols),
        failed_data=sum(1 for r in rejected if any(k in r.reason for k in _data_kw)),
        failed_pre_screen=sum(1 for r in rejected if r.reason.startswith("Pre-screen:")),
        no_chain=sum(1 for r in rejected if r.reason == "no option chain"),
        failed_score=sum(1 for r in rejected if r.reason.startswith("Score gate:")),
        failed_contracts=sum(1 for r in rejected if "contracts rejected" in r.reason),
        candidates=len(candidates),
    )
    _log.info(
        "SCAN %s pipeline: scanned=%d data_fail=%d pre_screen_fail=%d no_chain=%d score_fail=%d contract_fail=%d candidates=%d",
        scan_id, _pipeline.scanned, _pipeline.failed_data, _pipeline.failed_pre_screen,
        _pipeline.no_chain, _pipeline.failed_score, _pipeline.failed_contracts, _pipeline.candidates,
    )
```

Then update the `ScanResult(...)` constructor call (around line 684) to pass `pipeline=_pipeline`:

```python
    result = ScanResult(
        scan_id=scan_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        rejected=rejected,
        state=state,
        previous_run_id=_last_result.scan_id if _last_result else None,
        deltas=deltas,
        shortlist_truncated=shortlist_truncated,
        original_count=original_count,
        pipeline=_pipeline,
    )
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_scan_endpoint.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/routers/scan.py
git commit -m "feat(scan): pipeline funnel counters + rename 'stock REJECT' to Pre-screen/Score-gate"
```

---

### Task 4: Backend — Stock scan pipeline counting

**Files:**
- Modify: `backend/app/routers/stock_scan.py`

- [ ] **Step 1: Add `StockPipeline` import**

Near line 18-21 (existing schema imports):

```python
from app.schemas.stock_scan import (
    StockScanRequest, StockScanResult, PositionCardOut,
    StrategySignalOut, BacktestOut, StockPipeline,
)
```

- [ ] **Step 2: Count stages and attach `StockPipeline` to result**

After the `for r in results:` loop (after line 263, where `candidates` and `rejected` are built), replace the `return StockScanResult(...)` with:

```python
    _hist_kw = ("insufficient history", "no price data", "price $")
    _pipeline = StockPipeline(
        scanned=len(symbols),
        failed_history=sum(
            1 for r in rejected
            if isinstance(r, dict) and any(k in r.get("reason", "") for k in _hist_kw)
        ),
        failed_score=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason", "").startswith("REJECT score=")
        ),
        failed_signal=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason", "").startswith("no ") and "setup" in r.get("reason", "")
        ),
        failed_backtest=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason", "").startswith("backtest gate:")
        ),
        other_rejected=sum(
            1 for r in rejected
            if isinstance(r, Exception)
        ),
        candidates=len(candidates),
    )
    logger.info(
        "STOCK SCAN pipeline: scanned=%d hist_fail=%d score_fail=%d signal_fail=%d bt_fail=%d other=%d candidates=%d",
        _pipeline.scanned, _pipeline.failed_history, _pipeline.failed_score,
        _pipeline.failed_signal, _pipeline.failed_backtest, _pipeline.other_rejected, _pipeline.candidates,
    )
    return StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
    )
```

- [ ] **Step 3: Run tests**

```bash
cd backend && pytest tests/test_strategy_backtest.py tests/test_market_data_fixes.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/routers/stock_scan.py
git commit -m "feat(stock-scan): add StockPipeline funnel counters to scan result"
```

---

### Task 5: Frontend — Pipeline types

**Files:**
- Modify: `frontend/types/stockDomain.ts`
- Modify: `frontend/lib/scanStore.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add `StockPipeline` type and update `StockScanResult`**

In `frontend/types/stockDomain.ts`, add before `StockScanResult`:

```typescript
export interface StockPipeline {
  scanned:         number;
  failed_history:  number;
  failed_score:    number;
  failed_signal:   number;
  failed_backtest: number;
  other_rejected:  number;
  candidates:      number;
}
```

And update `StockScanResult`:

```typescript
export interface StockScanResult {
  scan_id: string; timestamp: string;
  candidates: PositionCardData[]; rejected: Array<{symbol: string; reason: string}>;
  pipeline?: StockPipeline;
}
```

- [ ] **Step 2: Add `OptionsPipeline` type and update `ScanResult` in `scanStore.ts`**

In `frontend/lib/scanStore.ts`, after the `RejectedEntry` interface (around line 22), add:

```typescript
export interface OptionsPipeline {
  scanned:           number;
  failed_data:       number;
  failed_pre_screen: number;
  no_chain:          number;
  failed_score:      number;
  failed_contracts:  number;
  candidates:        number;
}
```

Update `ScanResult`:

```typescript
export interface ScanResult {
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected: RejectedEntry[];
  pipeline?: OptionsPipeline;
}
```

- [ ] **Step 3: Update `postScan` return type in `api.ts`**

In `frontend/lib/api.ts`, update the `postScan` return type (around line 87). First add the import at the top of the file:

```typescript
import type { OptionsPipeline } from '@/lib/scanStore';
```

Then update the `postScan` generic:

```typescript
  postScan: (
    universe: string[],
    direction: string,
    horizon: string,
    filters?: {
      min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number;
      confidence_caution_below?: number; confidence_reject_below?: number;
    },
    overrides?: Record<string, number | boolean | string>,
  ) =>
    post<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[]; pipeline?: OptionsPipeline }>(
      '/api/scan',
      { universe, direction, horizon, overrides: overrides ?? {}, ...filters },
    ),
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero TypeScript errors.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add types/stockDomain.ts lib/scanStore.ts lib/api.ts
git commit -m "feat(types): add OptionsPipeline + StockPipeline types, wire into ScanResult / StockScanResult"
```

---

### Task 6: Frontend — `ScanFunnel` component

**Files:**
- Create: `frontend/components/organisms/ScanFunnel/index.tsx`
- Create: `frontend/components/organisms/ScanFunnel/ScanFunnel.module.css`

- [ ] **Step 1: Create the CSS module**

```css
/* ScanFunnel.module.css */
.funnel {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 0 4px;
}

.title {
  margin-bottom: 6px;
}

.row {
  display: grid;
  grid-template-columns: 120px 48px auto;
  align-items: center;
  gap: 8px;
}

.bar {
  height: 4px;
  background: var(--border-subtle);
  border-radius: 2px;
  overflow: hidden;
  grid-column: 1 / -1;
  margin: 0 0 2px;
}

.barFill {
  height: 100%;
  background: var(--pass);
  border-radius: 2px;
  transition: width 0.3s;
}

.rejected {
  display: flex;
  align-items: center;
  gap: 4px;
}

.divider {
  height: 1px;
  background: var(--border-subtle);
  margin: 8px 0 4px;
}
```

- [ ] **Step 2: Create the component**

```tsx
// frontend/components/organisms/ScanFunnel/index.tsx
'use client';
import type { OptionsPipeline } from '@/lib/scanStore';
import type { StockPipeline } from '@/types/stockDomain';
import { Text, Data } from '@/components/primitives';
import styles from './ScanFunnel.module.css';

interface StageRow {
  label: string;
  count: number;
  rejected?: number;
  rejectedLabel?: string;
  isFinal?: boolean;
}

function FunnelStage({ label, count, rejected, rejectedLabel, isFinal, total }: StageRow & { total: number }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className={styles.row}>
      <Text size={11} tone={isFinal ? 'pass' : 'secondary'} weight={isFinal ? 500 : 400}>{label}</Text>
      <Data size={12} weight={500} tone={isFinal ? 'pass' : 'primary'}>{count}</Data>
      {rejected != null && rejected > 0 ? (
        <span className={styles.rejected}>
          <Text size={10} tone="reject">−{rejected}</Text>
          {rejectedLabel && <Text size={10} tone="dim">{rejectedLabel}</Text>}
        </span>
      ) : <span />}
      <div className={styles.bar} style={{ gridColumn: '1 / -1' }}>
        <div className={styles.barFill} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

interface Props {
  mode: 'options' | 'stock';
  pipeline: OptionsPipeline | StockPipeline;
}

export function ScanFunnel({ mode, pipeline }: Props) {
  if (mode === 'stock') {
    const p = pipeline as StockPipeline;
    return (
      <div className={styles.funnel}>
        <div className={styles.title}>
          <Text size={11} tone="dim" weight={500}>STOCK PIPELINE</Text>
        </div>
        <FunnelStage label="Universe"     count={p.scanned}   total={p.scanned} />
        <FunnelStage label="History"      count={p.scanned - p.failed_history}  rejected={p.failed_history}  rejectedLabel="no history"  total={p.scanned} />
        <FunnelStage label="Score gate"   count={p.scanned - p.failed_history - p.failed_score}  rejected={p.failed_score}   rejectedLabel="REJECT"      total={p.scanned} />
        <FunnelStage label="Signal"       count={p.scanned - p.failed_history - p.failed_score - p.failed_signal} rejected={p.failed_signal}  rejectedLabel="no setup"    total={p.scanned} />
        <FunnelStage label="Backtest"     count={p.candidates + p.failed_backtest} rejected={p.failed_backtest} rejectedLabel="gate fail" total={p.scanned} />
        <div className={styles.divider} />
        <FunnelStage label="Candidates"   count={p.candidates} total={p.scanned} isFinal />
      </div>
    );
  }

  const p = pipeline as OptionsPipeline;
  const afterData = p.scanned - p.failed_data;
  const afterPreScreen = afterData - p.failed_pre_screen;
  const afterChain = afterPreScreen - p.no_chain;
  return (
    <div className={styles.funnel}>
      <div className={styles.title}>
        <Text size={11} tone="dim" weight={500}>OPTIONS PIPELINE</Text>
      </div>
      <FunnelStage label="Universe"     count={p.scanned}        total={p.scanned} />
      <FunnelStage label="Data / Filters" count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"   total={p.scanned} />
      <FunnelStage label="Pre-screen"   count={afterPreScreen}   rejected={p.failed_pre_screen} rejectedLabel="score low"  total={p.scanned} />
      <FunnelStage label="Option chain" count={afterChain}       rejected={p.no_chain}          rejectedLabel="no chain"   total={p.scanned} />
      <FunnelStage label="Score + contracts" count={p.candidates + p.failed_score + p.failed_contracts}
        rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      <div className={styles.divider} />
      <FunnelStage label="Candidates"   count={p.candidates}     total={p.scanned} isFinal />
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
cd frontend
git add components/organisms/ScanFunnel/
git commit -m "feat(ui): ScanFunnel organism — per-stage pipeline bar for options and stock scans"
```

---

### Task 7: Frontend — Step 3 options log: add funnel + fix labels

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`

The log currently filters `entries.reason.startsWith('stock REJECT')` for the grouped reject section. After Task 3, the backend now returns "Pre-screen: score X rejected" and "Score gate: score X rejected". This task updates the filter and adds the `ScanFunnel`.

- [ ] **Step 1: Import `ScanFunnel`**

Find the existing imports in `page.tsx`. Add:

```typescript
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
```

- [ ] **Step 2: Update `ScanLogSection` filter**

Find this code (around line 104):

```typescript
  const stockRejects = entries.filter((e) => e.reason.startsWith('stock REJECT'));
  const otherRejects = entries.filter((e) => !e.reason.startsWith('stock REJECT'));
```

Replace with:

```typescript
  const GROUPED_PREFIXES = ['Pre-screen:', 'Score gate:'];
  const stockRejects = entries.filter((e) => GROUPED_PREFIXES.some((p) => e.reason.startsWith(p)));
  const otherRejects = entries.filter((e) => !GROUPED_PREFIXES.some((p) => e.reason.startsWith(p)));
```

- [ ] **Step 3: Place `ScanFunnel` before the log section**

Find the `SCAN LOG` section in the JSX (around line 951). The structure is:

```tsx
<div className={formStyles.scanLog}>
  <div className={formStyles.logHeader}>
    <Text size={11} tone="dim" weight={500}>SCAN LOG</Text>
    ...stats...
  </div>
  <ScanLogSection entries={rejectedLog} horizonKey={horizonKey} />
</div>
```

Add the funnel between the header and the `ScanLogSection`:

```tsx
  {scanResult?.pipeline && (
    <ScanFunnel mode="options" pipeline={scanResult.pipeline} />
  )}
  <ScanLogSection entries={rejectedLog} horizonKey={horizonKey} />
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add app/\(frame\)/screener/step-3-direction/page.tsx
git commit -m "feat(step-3): show OptionsPipeline ScanFunnel in scan log; update reject label filter"
```

---

### Task 8: Frontend — Step 6 backtest: add stock pipeline funnel

**Files:**
- Modify: `frontend/app/(frame)/screener/step-6-backtest/page.tsx`

Step 6 Backtest is where stock scan results are displayed. The header already shows a plain-text summary; we add the `ScanFunnel` underneath it.

- [ ] **Step 1: Import `ScanFunnel` and `StockPipeline`**

```typescript
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
```

- [ ] **Step 2: Add funnel to the header area**

Find the header block (around line 93):

```tsx
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 7</Text>
        <Title as="h1" size={24}>Backtest Gate</Title>
        <Text size={13} tone="secondary">
          {filteredPassing.length} candidates passed · {result.candidates.length - passing.length} failed ·
          {rejected.length} rejected before backtest
        </Text>
      </div>
```

After the header `</div>`, add:

```tsx
      {result.pipeline && (
        <ScanFunnel mode="stock" pipeline={result.pipeline} />
      )}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
cd frontend
git add app/\(frame\)/screener/step-6-backtest/page.tsx
git commit -m "feat(step-6): show StockPipeline ScanFunnel above backtest candidate table"
```

---

### Task 9: Frontend — Settings Tradier Live (store + UI)

**Files:**
- Modify: `frontend/lib/settingsStore.ts`
- Modify: `frontend/app/(frame)/settings/page.tsx`

- [ ] **Step 1: Add `TradierLiveConfig` interface and default to `settingsStore.ts`**

After the existing `TradierPaperConfig` interface (around line 63), add:

```typescript
export interface TradierLiveConfig {
  token:     string;
  accountId: string;
}

export const DEFAULT_TRADIER_LIVE: TradierLiveConfig = {
  token:     '',
  accountId: '',
};
```

- [ ] **Step 2: Add `tradierLive` + `setTradierLive` to `SettingsState` interface**

In the `interface SettingsState` block (around line 120), add after `tradierPaper`:

```typescript
  tradierLive:                 TradierLiveConfig;
  setTradierLive:              (c: TradierLiveConfig) => void;
```

- [ ] **Step 3: Add migration branch for version 15**

In `migrateSettings`, after the `version < 14` branch (around line 164):

```typescript
  if (version < 15) {
    next.tradierLive = { ...DEFAULT_TRADIER_LIVE };
  }
```

- [ ] **Step 4: Add initial value, action, `resetToDefaults`, `partialize` entries**

In `useSettingsStore` initial state (set block, around line 185):
```typescript
      tradierLive: { ...DEFAULT_TRADIER_LIVE },
```

In the actions section:
```typescript
      setTradierLive: (c) => set({ tradierLive: c }),
```

In `resetToDefaults`:
```typescript
        tradierLive: { ...DEFAULT_TRADIER_LIVE },
```

In `partialize`:
```typescript
        tradierLive: state.tradierLive,
```

- [ ] **Step 5: Bump store version to 15**

Find `version: 14` (around line 225) and change to `version: 15`.

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 7: Add Tradier Live UI section to `settings/page.tsx`**

In `BrokersForm` function (starting around line 839), add state variables for Tradier Live. After the existing `tradierTok`/`tradierAcct` state declarations (around line 849):

```typescript
  const { tradierLive, setTradierLive, ... } = useSettingsStore();
  const [tradierLiveTok,  setTradierLiveTok]  = useState(tradierLive.token);
  const [tradierLiveAcct, setTradierLiveAcct] = useState(tradierLive.accountId);
```

(Add `tradierLive, setTradierLive` to the destructured `useSettingsStore()` call at the top of `BrokersForm`.)

Add the useEffect syncs (after the existing Tradier Paper syncs, around line 860):

```typescript
  useEffect(() => { setTradierLiveTok(tradierLive.token); },      [tradierLive.token]);
  useEffect(() => { setTradierLiveAcct(tradierLive.accountId); }, [tradierLive.accountId]);
```

Add the save function (after `saveTradierPaper`, around line 875):

```typescript
  async function saveTradierLive() {
    setSaving('tradierLive');
    setTradierLive({ token: tradierLiveTok, accountId: tradierLiveAcct });
    await api.postCredentials('tradier_live', { token: tradierLiveTok, account_id: tradierLiveAcct });
    setSaving(null);
  }
```

- [ ] **Step 8: Add Tradier Live UI section BEFORE the Tradier Paper section**

Find the existing Tradier Paper `<SectionIntro ...>` (around line 917):

```tsx
      <SectionIntro
        title="Tradier Paper (Sandbox)"
        blurb="Tradier sandbox uses a separate token from your live account..."
      />
```

Insert BEFORE it:

```tsx
      <SectionIntro
        title="Tradier Live"
        blurb="Live Tradier token — used for real-time quotes, option chains, and market data. Get your token at developer.tradier.com."
      />
      <Row label="Live token" hint="Your Tradier live API token" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tradierLiveTok}
          onChange={(e) => setTradierLiveTok(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your Tradier live account ID (e.g. VA-XXXXXXXX)" defaultValue="—">
        <input
          className={styles.input}
          value={tradierLiveAcct}
          onChange={(e) => setTradierLiveAcct(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTradierLive}
            disabled={saving === 'tradierLive'}
          >
            {saving === 'tradierLive' ? 'Saving…' : 'Save Tradier Live'}
          </button>
        </div>
      </div>
```

- [ ] **Step 9: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 10: Commit**

```bash
cd frontend
git add lib/settingsStore.ts app/\(frame\)/settings/page.tsx
git commit -m "feat(settings): add Tradier Live credential section — store version 15"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Covered by |
|---|---|
| Options pipeline funnel in Step 3 log | Tasks 1, 3, 5, 6, 7 |
| Stock pipeline funnel in Step 6 (backtest) | Tasks 2, 4, 5, 6, 8 |
| No "stock REJECT" label in options scan | Task 3 (backend rename) + Task 7 (filter update) |
| No options-specific errors in stock scan log | Stock scan never emits "stock REJECT" or "no option chain" — already clean; pipeline is separate |
| Existing log information preserved | ScanLogSection unchanged except filter prefix; all rejection entries still shown |
| Tradier Live credentials in Settings → Brokers | Task 9 |
| Tradier Live token used by backend | Already handled by `get_tradier_creds()` priority: credential store live > paper > env — saving to `tradier_live` slot is enough |

**Placeholder scan:** All steps contain actual code. No TBDs.

**Type consistency:**
- `OptionsPipeline` defined in `lib/scanStore.ts` and imported in `ScanFunnel/index.tsx` and `api.ts`
- `StockPipeline` defined in `types/stockDomain.ts` and imported in `ScanFunnel/index.tsx`
- `ScanFunnel` accepts `mode: 'options' | 'stock'` with the matching pipeline union type

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-13-scan-log-pipeline-funnel.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
