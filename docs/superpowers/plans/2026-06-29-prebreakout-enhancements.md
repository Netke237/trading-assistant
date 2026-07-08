# Pre-Breakout Scanner Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Pre-Breakout scanner self-sufficient — expose all tuning parameters in-page, wire it to the Universe selection from Step 2, link it from the Step 3 Run Scan button, and add a Pullback mode description so the user understands where to go for each setup type.

**Architecture:** Four independent changes stacked in order of risk. (1) Raise proximity default in YAML + new `PreBreakoutParamsPanel` component modelled after `StrategyParamsPanel`. (2) Extend the backend prebreakout endpoint to accept `universe: list[str] | None` and call the existing `expand_universe` helper (same as the stock scan endpoint). (3) The frontend pre-breakout page mirrors `RunScanButton`'s universe-resolution pattern: `Custom` → parse `customRaw`, `Watchlist` → watchlist store, anything else → `[pick]` sent as the universe list. (4) Add a `prebreakout` branch inside `RunScanButton/index.tsx` that navigates to `/screener/step-4-prebreakout` instead of running the options scan.

**Tech Stack:** Next.js 15 App Router, TypeScript strict, CSS Modules, Zustand v5, FastAPI + Pydantic v2, `expand_universe` from `app.data.universe_presets`, `useUniverseStore`, `useWatchlistStore`, `useScanStore`, `api.prebreakoutScan`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `backend/config/strategy_params.yaml` | Raise `resistance_proximity_pct` 0.05 → 0.08 |
| Modify | `backend/app/routers/stock_scan.py` | `PreBreakoutScanRequest.universe: list[str] \| None`; call `expand_universe` |
| Create | `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` | Collapsible params panel, 6 breakout params |
| Create | `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css` | Styles (reuse StrategyParamsPanel token pattern) |
| Modify | `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` | Mount panel, wire params + universe to scan call, add Pullback mode info |
| Modify | `frontend/components/organisms/RunScanButton/index.tsx` | Add `prebreakout` branch → navigate to step-4-prebreakout |
| Modify | `frontend/lib/api.ts` | Extend `prebreakoutScan` to accept `universe?: string[]` |

---

## Task 1 — Raise default proximity threshold

**Files:**
- Modify: `backend/config/strategy_params.yaml`

- [ ] **Step 1: Change resistance_proximity_pct in both bullish and bearish blocks**

  In `backend/config/strategy_params.yaml`, under `breakout_setup.active`, change **both** occurrences:
  ```yaml
  resistance_proximity_pct: 0.05
  ```
  to:
  ```yaml
  resistance_proximity_pct: 0.08
  ```

- [ ] **Step 2: Verify the change loaded (note: module is `strategy_param_store`, not `strategy_params`)**

  ```bash
  cd backend
  python -c "from app.services.strategy_param_store import get_active; print(get_active('breakout_setup','Bullish'))"
  ```
  Expected output contains: `'resistance_proximity_pct': 0.08`

- [ ] **Step 3: Commit**

  ```bash
  git add backend/config/strategy_params.yaml
  git commit -m "config: raise pre-breakout proximity default to 8%"
  ```

---

## Task 2 — PreBreakoutParamsPanel component

**Files:**
- Create: `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`
- Create: `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css`

- [ ] **Step 1: Create the CSS module**

  Create `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css`:
  ```css
  .paramsPanel {
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    margin-bottom: 16px;
  }
  .paramsSummary {
    padding: 10px 14px;
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .paramsSummary::-webkit-details-marker { display: none; }
  .paramsGrid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
    padding: 0 14px 14px;
    border-top: 1px solid var(--border-subtle);
  }
  .paramSection {
    grid-column: 1 / -1;
    padding: 12px 0 4px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .paramLabel {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .paramInput {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .paramInput input[type="number"] {
    width: 70px;
    background: var(--bg-input, var(--bg-surface));
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 13px;
    padding: 4px 8px;
  }
  .resetRow {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    padding-top: 10px;
  }
  .resetBtn {
    background: none;
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    color: var(--text-secondary);
    font-size: 11px;
    padding: 4px 10px;
    cursor: pointer;
  }
  .resetBtn:hover { border-color: var(--text-primary); color: var(--text-primary); }
  ```

- [ ] **Step 2: Create the component**

  Create `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`:
  ```tsx
  'use client';

  import { Text } from '@/components/primitives';
  import styles from './PreBreakoutParamsPanel.module.css';

  export interface PreBreakoutParams {
    atrCompressionRatio: number;    // 0.1–1.0,  default 0.7
    rangeAtrMult: number;           // 0.1–2.0,  default 0.8
    rangeLookbackBars: number;      // 3–30,     default 10
    volCompressionRatio: number;    // 0.1–1.0,  default 0.8
    resistanceProximityPct: number; // 0.01–0.20,default 0.08
    swingLookback: number;          // 10–100,   default 50
  }

  export const PREBREAKOUT_DEFAULTS: PreBreakoutParams = {
    atrCompressionRatio: 0.7,
    rangeAtrMult: 0.8,
    rangeLookbackBars: 10,
    volCompressionRatio: 0.8,
    resistanceProximityPct: 0.08,
    swingLookback: 50,
  };

  interface Props {
    params: PreBreakoutParams;
    setParams: React.Dispatch<React.SetStateAction<PreBreakoutParams>>;
    onReset: () => void;
  }

  export function PreBreakoutParamsPanel({ params, setParams, onReset }: Props) {
    return (
      <details className={styles.paramsPanel}>
        <summary className={styles.paramsSummary}>
          <Text size={12} tone="secondary">Scan parameters</Text>
        </summary>

        <div className={styles.paramsGrid}>

          {/* ── ATR / Range compression ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">ATR &amp; Range compression</Text>
            <Text size={10} tone="dim">
              How tight the consolidation must be. The stock&apos;s recent volatility (ATR) and
              price range must be compressed vs their average. Lower ratios = tighter squeeze
              required (fewer, higher-quality setups).
            </Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">ATR compression ratio</Text>
            <Text size={10} tone="dim">
              Current ATR must be below this fraction of the 20-bar average ATR.
              ↑ Higher → less compression required (more results) · ↓ Lower → very tight squeezes only
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.atrCompressionRatio}
                min={0.1} max={1.0} step={0.05}
                onChange={(e) => setParams((p) => ({ ...p, atrCompressionRatio: Number(e.target.value) }))}
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Range / ATR multiplier</Text>
            <Text size={10} tone="dim">
              High-low range of the last N bars must be below this multiple of current ATR.
              ↑ Higher → wider consolidation accepted · ↓ Lower → only very flat bases qualify
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.rangeAtrMult}
                min={0.1} max={2.0} step={0.05}
                onChange={(e) => setParams((p) => ({ ...p, rangeAtrMult: Number(e.target.value) }))}
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Range lookback bars</Text>
            <Text size={10} tone="dim">
              How many bars to measure the range over.
              ↑ Higher → longer consolidation window · ↓ Lower → only very recent tightness counted
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.rangeLookbackBars}
                min={3} max={30} step={1}
                onChange={(e) => setParams((p) => ({ ...p, rangeLookbackBars: Number(e.target.value) }))}
              />
              <Text size={11} tone="dim">bars</Text>
            </div>
          </label>

          {/* ── Volume compression ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Volume compression</Text>
            <Text size={10} tone="dim">
              Quiet volume confirms the stock is coiling, not distributing.
              The last bar&apos;s volume must fall below this fraction of the 20-bar average.
            </Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Volume compression ratio</Text>
            <Text size={10} tone="dim">
              Last bar volume must be below this fraction of 20-bar average.
              ↑ Higher → higher relative volume accepted (more results) · ↓ Lower → only very quiet bars qualify
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.volCompressionRatio}
                min={0.1} max={1.0} step={0.05}
                onChange={(e) => setParams((p) => ({ ...p, volCompressionRatio: Number(e.target.value) }))}
              />
            </div>
          </label>

          {/* ── Resistance proximity ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Resistance proximity</Text>
            <Text size={10} tone="dim">
              How close the stock must be to its key swing level to qualify.
              Bullish: close must be within X% below the N-bar swing high.
              Bearish: close must be within X% above the N-bar swing low.
            </Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Proximity to key level</Text>
            <Text size={10} tone="dim">
              ↑ Higher % → stock can be further away (many more results) · ↓ Lower % → only near-the-level setups qualify
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={Math.round(params.resistanceProximityPct * 100 * 10) / 10}
                min={1} max={20} step={0.5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, resistanceProximityPct: Number(e.target.value) / 100 }))
                }
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Swing lookback</Text>
            <Text size={10} tone="dim">
              How many bars back to search for the key swing high / low.
              ↑ Higher → looks further back · ↓ Lower → only very recent levels used
            </Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.swingLookback}
                min={10} max={100} step={5}
                onChange={(e) => setParams((p) => ({ ...p, swingLookback: Number(e.target.value) }))}
              />
              <Text size={11} tone="dim">bars</Text>
            </div>
          </label>

          <div className={styles.resetRow}>
            <button type="button" className={styles.resetBtn} onClick={onReset}>
              Reset to defaults
            </button>
          </div>

        </div>
      </details>
    );
  }
  ```

- [ ] **Step 3: Run typecheck**
  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: no errors in new files.

- [ ] **Step 4: Commit**
  ```bash
  git add frontend/components/organisms/PreBreakoutParamsPanel/
  git commit -m "feat(prebreakout): PreBreakoutParamsPanel component with 6 tuning params"
  ```

---

## Task 3 — Backend: accept universe list in pre-breakout endpoint

**Files:**
- Modify: `backend/app/routers/stock_scan.py` (lines ~52–55 and ~855–892)

`expand_universe(list[str])` is the existing helper (imported inline in the stock scan handler from `app.data.universe_presets`). It handles `SP500`, `NDX100`, `DOW30`, all `SECTOR:*` keys, `Watchlist` symbols, and individual tickers. We reuse it here.

- [ ] **Step 1: Change PreBreakoutScanRequest to accept universe as list**

  In `backend/app/routers/stock_scan.py`, find `class PreBreakoutScanRequest` (around line 52) and change it to:
  ```python
  class PreBreakoutScanRequest(BaseModel):
      symbols: list[str] = []
      universe: list[str] | None = None   # e.g. ["SP500"] or ["SECTOR:XLK"] or individual tickers
      direction: str = "Bullish"
      params_override: dict | None = None
  ```

- [ ] **Step 2: Add universe resolution to the handler**

  In the `prebreakout_scan` handler (around line 855), replace the existing symbol loop preamble with:
  ```python
  async def prebreakout_scan(body: PreBreakoutScanRequest) -> list[dict]:
      """Scan symbols for pre-breakout consolidation setups using breakout_setup_signal."""
      from datetime import date, timedelta
      from app.data.universe_presets import expand_universe, PresetUnavailableError
      from fastapi import HTTPException

      end = date.today()
      start = end - timedelta(days=365)

      # Resolve symbol list: universe takes precedence over manual symbols list
      if body.universe:
          try:
              symbols_to_scan = expand_universe(body.universe)
          except PresetUnavailableError as exc:
              raise HTTPException(status_code=400, detail=str(exc))
      else:
          symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

      if not symbols_to_scan:
          return []

      base_params = get_active("breakout_setup", body.direction)
      if body.params_override:
          base_params.update(body.params_override)

      results: list[dict] = []
      for sym in symbols_to_scan:
          sym = sym.strip().upper()
          if not sym:
              continue
          try:
              bars = await get_historical_bars(sym, start, end)
          except Exception as exc:
              logger.warning("prebreakout scan: get_bars failed for %s — %s", sym, exc)
              continue
          if not bars:
              continue
          try:
              signal = breakout_setup_signal(bars, sym, direction=body.direction, **base_params)
          except Exception as exc:
              logger.warning("prebreakout scan: signal failed for %s — %s", sym, exc)
              continue
          if signal is None:
              continue
          results.append({
              "symbol": sym,
              "confidence": signal.confidence,
              "direction": signal.direction,
              "metrics": signal.metrics,
          })

      results.sort(key=lambda r: r["confidence"], reverse=True)
      return results
  ```

- [ ] **Step 3: Write tests**

  Create `backend/tests/test_prebreakout_universe.py`:
  ```python
  import pytest
  from unittest.mock import patch, AsyncMock
  from httpx import AsyncClient
  from app.main import app

  @pytest.mark.asyncio
  async def test_prebreakout_accepts_universe_field():
      """universe field is accepted and passed to expand_universe."""
      with patch(
          "app.routers.stock_scan.expand_universe",
          return_value=["AAPL", "MSFT"],
      ) as mock_expand, patch(
          "app.routers.stock_scan.get_historical_bars",
          new_callable=AsyncMock,
          return_value=[],
      ):
          async with AsyncClient(app=app, base_url="http://test") as client:
              resp = await client.post("/api/scan/prebreakout", json={
                  "universe": ["DOW30"],
                  "direction": "Bullish",
              })
          assert resp.status_code == 200
          mock_expand.assert_called_once_with(["DOW30"])

  @pytest.mark.asyncio
  async def test_prebreakout_empty_symbols_and_no_universe_returns_empty():
      async with AsyncClient(app=app, base_url="http://test") as client:
          resp = await client.post("/api/scan/prebreakout", json={
              "symbols": [],
              "direction": "Bullish",
          })
      assert resp.status_code == 200
      assert resp.json() == []

  @pytest.mark.asyncio
  async def test_prebreakout_unknown_preset_returns_400():
      async with AsyncClient(app=app, base_url="http://test") as client:
          resp = await client.post("/api/scan/prebreakout", json={
              "universe": ["RUSSELL2000"],
              "direction": "Bullish",
          })
      assert resp.status_code == 400
  ```

- [ ] **Step 4: Run tests**
  ```bash
  cd backend && pytest tests/test_prebreakout_universe.py -v
  ```
  Expected: all three tests pass.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/app/routers/stock_scan.py backend/tests/test_prebreakout_universe.py
  git commit -m "feat(prebreakout): accept universe list in scan endpoint, resolve via expand_universe"
  ```

---

## Task 4 — Frontend: wire PreBreakoutParamsPanel + Universe into step-4-prebreakout

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`
- Modify: `frontend/lib/api.ts`

The universe-resolution pattern here **exactly mirrors `RunScanButton`** (lines 76–91): `Custom` → parse `customRaw`, `Watchlist` → watchlist store, anything else → `[pick]`.

- [ ] **Step 1: Extend api.ts prebreakoutScan to accept universe list**

  In `frontend/lib/api.ts`, find `prebreakoutScan` (around line 498) and replace it with:
  ```ts
  prebreakoutScan: (
    symbols: string[],
    direction: string,
    paramsOverride?: Record<string, unknown>,
    universe?: string[],
  ) =>
    post<Array<{ symbol: string; confidence: number; direction: string; metrics: Record<string, number> }>>(
      '/api/scan/prebreakout',
      { symbols, direction, params_override: paramsOverride ?? null, universe: universe ?? null }
    ),
  ```

- [ ] **Step 2: Rewrite step-4-prebreakout/page.tsx**

  Replace the entire file:
  ```tsx
  'use client';

  import { useState, useCallback } from 'react';
  import { Title, Text, Data } from '@/components/primitives';
  import { WatchStar } from '@/components/atoms/WatchStar';
  import { useScanStore } from '@/lib/scanStore';
  import { useUniverseStore } from '@/lib/universeStore';
  import { useWatchlistStore } from '@/lib/watchlistStore';
  import { api } from '@/lib/api';
  import { CompositeAlertDialog } from '@/components/organisms/CompositeAlertDialog';
  import {
    PreBreakoutParamsPanel,
    PREBREAKOUT_DEFAULTS,
    type PreBreakoutParams,
  } from '@/components/organisms/PreBreakoutParamsPanel';
  import styles from './page.module.css';

  type ScanRow = { symbol: string; confidence: number; direction: string; metrics: Record<string, number> };
  type ScanMode = 'prebreakout' | 'pullback';

  function parseSymbols(raw: string): string[] {
    return raw.split(/[\s,\n]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
  }

  function _confidenceTone(c: number): 'pass' | 'caution' | 'reject' {
    return c >= 70 ? 'pass' : c >= 40 ? 'caution' : 'reject';
  }

  export default function Step4PreBreakoutPage() {
    const context     = useScanStore((s) => s.context);
    const direction   = context?.direction ?? 'Bullish';
    const preResults  = useScanStore((s) => s.preBreakoutResults);
    const setResults  = useScanStore((s) => s.setPreBreakoutResults);

    const universePick = useUniverseStore((s) => s.pick);
    const customRaw    = useUniverseStore((s) => s.customRaw);

    const [symbolOverride, setSymbolOverride] = useState('');
    const [scanMode, setScanMode]             = useState<ScanMode>('prebreakout');
    const [params, setParams]                 = useState<PreBreakoutParams>({ ...PREBREAKOUT_DEFAULTS });
    const [scanning, setScanning]             = useState(false);
    const [error, setError]                   = useState<string | null>(null);
    const [alertSymbol, setAlertSymbol]       = useState<string | null>(null);

    const runScan = useCallback(async () => {
      // Resolve symbols — identical logic to RunScanButton (lines 76–91 of RunScanButton/index.tsx)
      const manualSymbols = parseSymbols(symbolOverride);
      let symbols: string[];
      let universe: string[] | undefined;

      if (manualSymbols.length > 0) {
        // Manual override wins
        symbols = manualSymbols;
        universe = undefined;
      } else if (universePick === 'Custom') {
        symbols = parseSymbols(customRaw);
        universe = undefined;
      } else if (universePick === 'Watchlist') {
        symbols = useWatchlistStore.getState().added;
        universe = undefined;
      } else {
        symbols = [];
        universe = [universePick]; // e.g. ['SP500'], ['SECTOR:XLK']
      }

      if (symbols.length === 0 && !universe) {
        setError('Add symbols to the Watchlist or enter them manually.');
        return;
      }

      setError(null);
      setScanning(true);
      try {
        const paramsOverride: Record<string, unknown> = {
          atr_compression_ratio:    params.atrCompressionRatio,
          range_atr_mult:           params.rangeAtrMult,
          range_lookback_bars:      params.rangeLookbackBars,
          vol_compression_ratio:    params.volCompressionRatio,
          resistance_proximity_pct: params.resistanceProximityPct,
          swing_lookback:           params.swingLookback,
        };
        const results = await api.prebreakoutScan(symbols, direction, paramsOverride, universe);
        setResults(results);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setScanning(false);
      }
    }, [symbolOverride, universePick, customRaw, direction, params, setResults]);

    const sorted: ScanRow[] = [...preResults].sort((a, b) => b.confidence - a.confidence);

    const universeLabel =
      symbolOverride.trim()       ? 'manual symbols'
      : universePick === 'Custom'  ? 'custom symbols'
      : universePick === 'Watchlist' ? 'watchlist'
      : universePick;

    return (
      <div className={styles.main}>
        <div className={styles.header}>
          <Title as="h2" size={20}>Setup Scanner</Title>
          <Text size={13} tone="secondary">
            Scanning {universeLabel} · {direction}
          </Text>
        </div>

        {/* Mode toggle */}
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={`${styles.modeBtn} ${scanMode === 'prebreakout' ? styles.modeBtnActive : ''}`}
            onClick={() => setScanMode('prebreakout')}
          >
            Pre-Breakout
          </button>
          <button
            type="button"
            className={`${styles.modeBtn} ${scanMode === 'pullback' ? styles.modeBtnActive : ''}`}
            onClick={() => setScanMode('pullback')}
          >
            Pullback to EMA
          </button>
        </div>

        {scanMode === 'pullback' ? (
          <div className={styles.pullbackInfo}>
            <Text size={13} tone="secondary">
              Trending stocks that have pulled back to their EMA are handled in the full
              <strong> Stocks screener</strong> (Steps 1–3 → Stocks mode → Step 4 → pick
              <em> Pullback to 20-EMA</em>). That flow includes a historical backtest, confidence
              gate, and broker execution. Use this tab for pre-breakout consolidation setups only.
            </Text>
          </div>
        ) : (
          <>
            <Text size={12} tone="dim">
              Stocks coiling near a key resistance level — ATR compressed, volume dry, close
              within {(params.resistanceProximityPct * 100).toFixed(1)}% of swing high.
              Set a regime alert to be notified when conditions align.
            </Text>

            <div className={styles.inputRow}>
              <textarea
                className={styles.symbolInput}
                rows={2}
                placeholder={`Leave blank to use universe (${universeLabel}) · or enter specific symbols to override`}
                value={symbolOverride}
                onChange={(e) => setSymbolOverride(e.target.value)}
              />
              <button
                type="button"
                className={styles.runBtn}
                onClick={runScan}
                disabled={scanning}
              >
                {scanning ? 'Scanning…' : 'Run Scan'}
              </button>
            </div>

            <PreBreakoutParamsPanel
              params={params}
              setParams={setParams}
              onReset={() => setParams({ ...PREBREAKOUT_DEFAULTS })}
            />

            {error && <Text size={12} tone="reject">{error}</Text>}

            {sorted.length > 0 && (
              <div className={styles.tableWrap}>
                <div className={styles.tableHeader}>
                  <span />
                  <Text size={11} tone="dim" weight={500}>Symbol</Text>
                  <Text size={11} tone="dim" weight={500}>Dir</Text>
                  <Text size={11} tone="dim" weight={500}>Confidence</Text>
                  <Text size={11} tone="dim" weight={500}>ATR Ratio</Text>
                  <Text size={11} tone="dim" weight={500}>Vol Ratio</Text>
                  <Text size={11} tone="dim" weight={500}>Proximity %</Text>
                  <span />
                </div>
                {sorted.map((row) => (
                  <div key={row.symbol} className={styles.tableRow}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <Text size={13} weight={500}>{row.symbol}</Text>
                    <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : 'reject'}>
                      {row.direction === 'Bullish' ? '↑' : '↓'}
                    </Text>
                    <Data size={13} tone={_confidenceTone(row.confidence)}>{row.confidence}%</Data>
                    <Data size={12} tone="secondary">
                      {row.metrics.atr_ratio != null ? row.metrics.atr_ratio.toFixed(2) : '—'}
                    </Data>
                    <Data size={12} tone="secondary">
                      {row.metrics.vol_ratio != null ? row.metrics.vol_ratio.toFixed(2) : '—'}
                    </Data>
                    <Data size={12} tone="secondary">
                      {row.metrics.proximity_pct != null ? row.metrics.proximity_pct.toFixed(1) : '—'}
                    </Data>
                    <button
                      type="button"
                      className={styles.alertBtn}
                      onClick={() => setAlertSymbol(row.symbol)}
                    >
                      <Text size={11} weight={500}>Set Alert</Text>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {sorted.length === 0 && !scanning && (
              <Text size={13} tone="dim">No results yet — run the scan.</Text>
            )}
          </>
        )}

        {alertSymbol && (
          <CompositeAlertDialog
            symbol={alertSymbol}
            direction={direction}
            onClose={() => setAlertSymbol(null)}
          />
        )}
      </div>
    );
  }
  ```

- [ ] **Step 3: Add modeToggle CSS to page.module.css**

  Open `frontend/app/(frame)/screener/step-4-prebreakout/page.module.css` and append:
  ```css
  .modeToggle {
    display: flex;
    gap: 0;
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    overflow: hidden;
    width: fit-content;
    margin-bottom: 12px;
  }
  .modeBtn {
    background: none;
    border: none;
    padding: 6px 18px;
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 12px;
    transition: background 0.15s;
  }
  .modeBtn + .modeBtn {
    border-left: 1px solid var(--border-subtle);
  }
  .modeBtnActive {
    background: var(--bg-card, var(--bg-surface));
    color: var(--text-primary);
    font-weight: 500;
  }
  .pullbackInfo {
    padding: 16px;
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    margin-bottom: 16px;
  }
  ```

- [ ] **Step 4: Run typecheck**
  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: clean.

- [ ] **Step 5: Commit**
  ```bash
  git add frontend/app/(frame)/screener/step-4-prebreakout/ frontend/lib/api.ts
  git commit -m "feat(prebreakout): params panel, universe wiring, Pullback info panel"
  ```

---

## Task 5 — Wire Run Scan button to pre-breakout mode

The Run Scan button is the `RunScanButton` organism, **not** the Step 3 page. The page renders `<RunScanButton />` and does not own the scan routing. Add the `prebreakout` branch inside `RunScanButton/index.tsx`.

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx`

- [ ] **Step 1: Check current screenerMode branches and router import**

  ```bash
  grep -n "screenerMode\|useRouter\|router.push\|import.*router" \
    frontend/components/organisms/RunScanButton/index.tsx
  ```
  Confirm that `useRouter` is NOT currently imported (the component uses store state only). You will need to add it.

- [ ] **Step 2: Add router import at the top of RunScanButton/index.tsx**

  Find the existing imports block (starts around line 1) and add after the last import:
  ```tsx
  import { useRouter } from 'next/navigation';
  ```

- [ ] **Step 3: Add router initialisation inside the component**

  Find the line `const scanning = scanState === 'SCANNING';` (around line 61) and add immediately after it:
  ```tsx
  const router = useRouter();
  ```

- [ ] **Step 4: Add prebreakout branch to the onClick handler**

  Find the `onClick` callback (around line 67). Currently it starts with:
  ```tsx
  if (screenerMode === 'stocks') {
    if (!activeStrategy) return;
    void runStockScan(activeStrategy);
    return;
  }
  ```

  Add a `prebreakout` branch before the `stocks` check:
  ```tsx
  if (screenerMode === 'prebreakout') {
    router.push('/screener/step-4-prebreakout');
    return;
  }
  ```

  The final start of onClick should look like:
  ```tsx
  const onClick = useCallback(() => {
    if (scanning) return;

    if (screenerMode === 'prebreakout') {
      router.push('/screener/step-4-prebreakout');
      return;
    }

    if (screenerMode === 'stocks') {
      if (!activeStrategy) return;
      void runStockScan(activeStrategy);
      return;
    }
    // ... rest of options scan logic unchanged
  ```

- [ ] **Step 5: Update the button label for prebreakout mode**

  Find the button's label expression (around line 227–233). It currently reads:
  ```tsx
  screenerMode === 'stocks' ? 'Run Stock Scan' : 'Run Scan'
  ```
  Change it to:
  ```tsx
  screenerMode === 'stocks'
    ? 'Run Stock Scan'
    : screenerMode === 'prebreakout'
    ? 'Go to Setup Scanner'
    : 'Run Scan'
  ```
  Do the same for the `aria-label` attribute on the same button.

- [ ] **Step 6: Run typecheck**
  ```bash
  cd frontend && npm run typecheck
  ```

- [ ] **Step 7: Commit**
  ```bash
  git add frontend/components/organisms/RunScanButton/index.tsx
  git commit -m "feat(prebreakout): Run Scan button routes to Setup Scanner in prebreakout mode"
  ```

---

## Self-review

| Requirement | Covered? | Task |
|---|---|---|
| Expose all 6 breakout params in UI | ✓ | Task 2 |
| Raise default proximity to 8% | ✓ | Task 1 |
| Default values shown with explanatory text | ✓ | Task 2 |
| Panel styled like Stock's StrategyParamsPanel | ✓ | Task 2 (same CSS token pattern) |
| Universe drives scan (SP500/NDX100/DOW30/SECTOR/Watchlist/Custom) | ✓ | Task 3 + 4 |
| Manual symbol override still works | ✓ | Task 4 — override wins when non-empty |
| Watchlist universe handled client-side | ✓ | Task 4 — mirrors RunScanButton line 79 |
| Step 3 Run Scan routes to pre-breakout when in that mode | ✓ | Task 5 (RunScanButton, not page) |
| Pullback mode explained, not broken | ✓ | Task 4 — info panel, no dead scan call |
| `expand_universe` correctly called with `list[str]` | ✓ | Task 3 |
| Backend test verifies `expand_universe` was actually called | ✓ | Task 3 — mock asserts call |
| Typecheck clean at each commit | ✓ | Each task |
| No stale closures in useCallback | ✓ | Task 4 — all deps in array, no lint suppression |
| `CompositeAlertDialog` reused as-is (already exists) | ✓ | Task 4 — no creation step needed |
