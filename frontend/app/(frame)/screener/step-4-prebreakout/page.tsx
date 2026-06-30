'use client';

import { useState, useCallback, useEffect } from 'react';
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
import { statusForScore } from '@/lib/status';
import styles from './page.module.css';

type ScanRow = { symbol: string; confidence: number; direction: string; metrics: Record<string, number> };
type ScanMode = 'prebreakout' | 'pullback';

const SECTOR_LABELS: Record<string, string> = {
  'SECTOR:XLK': 'Technology',
  'SECTOR:XLC': 'Communication Services',
  'SECTOR:XLY': 'Consumer Discretionary',
  'SECTOR:XLI': 'Industrials',
  'SECTOR:XLF': 'Financials',
  'SECTOR:XLP': 'Consumer Staples',
  'SECTOR:XLV': 'Health Care',
  'SECTOR:XLB': 'Materials',
  'SECTOR:XLRE': 'Real Estate',
  'SECTOR:XLU': 'Utilities',
  'SECTOR:XLE': 'Energy',
};

function universeDisplayName(pick: string): string {
  return SECTOR_LABELS[pick] ?? pick;
}

const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,5}$/;

function parseSymbols(raw: string): string[] {
  return raw
    .split(/[\s,;\n]+/)
    .map((s) => s.trim().toUpperCase())
    .filter((s) => TICKER_RE.test(s));
}

function _confidenceTone(c: number): 'pass' | 'caution' | 'reject' {
  const s = statusForScore(c);
  return s === 'PASS' ? 'pass' : s === 'REJECT' ? 'reject' : 'caution';
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

  useEffect(() => {
    setResults([]);
  }, [params, universePick, direction, setResults]);

  const runScan = useCallback(async () => {
    // Universe resolution mirrors RunScanButton/index.tsx lines 76–91
    const manualSymbols = parseSymbols(symbolOverride);
    let symbols: string[];
    let universe: string[] | undefined;

    if (manualSymbols.length > 0) {
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
      universe = [universePick];
    }

    if (symbols.length === 0 && !universe) {
      if (universePick === 'Custom') {
        setError('Custom universe is empty — add symbols in Step 2 (Universe) or enter them above.');
      } else if (universePick === 'Watchlist') {
        setError('Watchlist is empty — star some symbols or enter them above.');
      } else {
        setError('No symbols to scan.');
      }
      return;
    }

    setError(null);
    setScanning(true);
    try {
      const paramsOverride: Record<string, unknown> = {
        atr_compression_ratio:    params.atrCompressionRatio,
        atr_avg_lookback:         params.atrAvgLookback,
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
    symbolOverride.trim()          ? 'manual symbols'
    : universePick === 'Custom'    ? 'custom symbols'
    : universePick === 'Watchlist' ? 'watchlist'
    : universeDisplayName(universePick);

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
          aria-pressed={scanMode === 'prebreakout'}
          className={`${styles.modeBtn} ${scanMode === 'prebreakout' ? styles.modeBtnActive : ''}`}
          onClick={() => setScanMode('prebreakout')}
        >
          Pre-Breakout
        </button>
        <button
          type="button"
          aria-pressed={scanMode === 'pullback'}
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
