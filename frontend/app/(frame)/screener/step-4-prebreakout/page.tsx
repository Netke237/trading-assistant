'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { SavedScanReportInspector } from '@/components/organisms/SavedScanReportInspector';
import { Title, Text, Data } from '@/components/primitives';
import { WatchStar } from '@/components/atoms/WatchStar';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import { CompositeAlertDialog } from '@/components/organisms/CompositeAlertDialog';
import {
  PreBreakoutParamsPanel,
  PREBREAKOUT_DEFAULTS,
  type PreBreakoutParams,
} from '@/components/organisms/PreBreakoutParamsPanel';
import {
  FibPullbackParamsPanel,
  FIB_PULLBACK_DEFAULTS,
  type FibPullbackParams,
} from '@/components/organisms/FibPullbackParamsPanel';
import { _horizonEnum } from '@/lib/analysisStore';
import { confidenceTier, confidenceTone } from '@/lib/confidenceText';
import { statusForScore, toneForStatus } from '@/lib/status';
import styles from './page.module.css';
import { fmtThreshold, truncPreBreakoutInts, truncFibInts, rememberScan, scanSnapshot, type ScanSnapshot } from './scanThresholds';
import { useRiskStore } from '@/lib/riskStore';
import { scanSizingFromRisk } from '@/lib/stockScan';

type ScanRowMetrics = {
  atr_ratio?: number;
  range_ratio?: number;
  vol_ratio?: number;
  proximity_pct?: number;
  swing_level?: number;
  current_atr?: number;
  fib_at_level?: boolean;
  fib_level_hit?: string | null;
  fib_dist_pct?: number | null;
  [key: string]: number | boolean | string | null | undefined;
};
type ScanRow = { symbol: string; confidence: number; direction: string; metrics: ScanRowMetrics };
type ScanMode = 'prebreakout' | 'pullback' | 'fib';

type FibScanRow = {
  symbol: string;
  direction: string;
  fib_level_hit: string;
  fib_dist_pct: number | null;
  at_level: boolean;
  confidence: number;
};

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
  'SP500': 'S&P 500',
  'NDX100': 'Nasdaq 100',
  'DOW30': 'Dow 30',
  'SPY': 'SPY ETF',
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

export default function Step4PreBreakoutPage() {
  const context     = useScanStore((s) => s.context);
  const direction   = context?.direction ?? 'Bullish';
  const preResults  = useScanStore((s) => s.preBreakoutResults);
  const setResults  = useScanStore((s) => s.setPreBreakoutResults);

  const universePick = useUniverseStore((s) => s.pick);
  const customRaw    = useUniverseStore((s) => s.customRaw);

  const [symbolOverride, setSymbolOverride] = useState('');
  const [tableRunIds, setTableRunIds] = useState<Partial<Record<ScanMode,string | null>>>({});
  const [scanMode, setScanMode]             = useState<ScanMode>('prebreakout');
  const [params, setParams]                 = useState<PreBreakoutParams>({ ...PREBREAKOUT_DEFAULTS });
  const [fibParams, setFibParams]           = useState<FibPullbackParams>({ ...FIB_PULLBACK_DEFAULTS });
  const [pullbackEmaParams, setPullbackEmaParams] = useState({ emaPeriod: 50, trendEma: 100 });
  const fibResults = useScanStore((s) => s.fibPullbackResults);
  const setFibResults = useScanStore((s) => s.setFibPullbackResults);
  const [pullbackResults, setPullbackResults] = useState<PositionCardData[]>([]);
  const [scanning, setScanning]             = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [alertSymbol, setAlertSymbol]       = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const requestToken = useRef(0);
  const isFirstRender                       = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    requestToken.current += 1;
    setScanning(false);
    setTableRunIds({});
    setResults([]);
    setFibResults([]);
    setPullbackResults([]);
  }, [params, fibParams, pullbackEmaParams, universePick, direction, setResults, setFibResults]);

  useEffect(() => { requestToken.current += 1; setScanning(false); }, [scanMode, symbolOverride, customRaw, context?.horizon]);
  useEffect(() => () => { requestToken.current += 1; }, []);

  const runScan = useCallback(async () => {
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

    const token = ++requestToken.current;
    let runId: string | null = null;
    const snapshot: ScanSnapshot = {
      scope: Object.freeze({mode: scanMode, direction, horizon: context?.horizon, symbols: Object.freeze([...symbols]), universe: universe ? Object.freeze([...universe]) : undefined, runId: null}),
      pre: truncPreBreakoutInts(params), fib: truncFibInts(fibParams),
      pullback: {emaPeriod: Math.trunc(pullbackEmaParams.emaPeriod), trendEma: Math.trunc(pullbackEmaParams.trendEma)},
    };
    const remember = (rows: object) => rememberScan(rows, {...snapshot, scope: Object.freeze({...snapshot.scope, runId})});
    setError(null);
    setScanning(true);
    try {
      if (scanMode === 'pullback') {
        // The user's sizing (P3a). This body is a hand-built SNAKE_CASE literal
        // (not buildStockScanRequestBody) and the backend ignores unknown keys,
        // so the two fields are named explicitly -- never spread the helper's
        // camelCase result. Throws ScanSizingError on 0%; the catch shows it.
        const sizing = scanSizingFromRisk();
        const result = await api.postStockScan({
          category: 'pullback',
          universe: universe ?? symbols,
          direction,
          horizon: _horizonEnum(context?.horizon),
          strategy: 'pullback_ema',
          pullback_ema_period: pullbackEmaParams.emaPeriod,
          pullback_trend_ema: pullbackEmaParams.trendEma,
          account_size: sizing.accountSize,
          risk_pct: sizing.riskPct,
        });
        if (token !== requestToken.current) return;
        runId = result.report_run_id ?? null;
        remember(result.candidates);
        setTableRunIds(ids=>({...ids,pullback:result.report_run_id}));
        setPullbackResults(result.candidates);
      } else if (scanMode === 'fib') {
        const results = await api.fibPullbackScan(
          symbols,
          direction,
          {
            fib_swing_lookback: fibParams.fibSwingLookback,
            fib_levels: [...fibParams.fibLevels],
            fib_tolerance_pct: fibParams.fibTolerancePct,
            ema_filter_period: fibParams.emaFilterPeriod,
          },
          universe,
          metadata => { runId = metadata.run_id; },
        );
        if (token !== requestToken.current) return;
        remember(results);
        setTableRunIds(ids=>({...ids,fib:runId}));
        setFibResults(results);
      } else {
        const paramsOverride: Record<string, unknown> = {
          atr_compression_ratio:    params.atrCompressionRatio,
          atr_avg_lookback:         params.atrAvgLookback,
          range_atr_mult:           params.rangeAtrMult,
          range_lookback_bars:      params.rangeLookbackBars,
          vol_compression_ratio:    params.volCompressionRatio,
          resistance_proximity_pct: params.resistanceProximityPct,
          swing_lookback:           params.swingLookback,
        };
        const results = await api.prebreakoutScan(symbols, direction, paramsOverride, universe, metadata => { runId = metadata.run_id; });
        if (token !== requestToken.current) return;
        remember(results);
        setTableRunIds(ids=>({...ids,prebreakout:runId}));
        setResults(results);
      }
    } catch (e) {
      if (token === requestToken.current) setError((e as Error).message);
    } finally {
      if (token === requestToken.current) setScanning(false);
    }
  }, [scanMode, symbolOverride, universePick, customRaw, direction, params, fibParams, context?.horizon, pullbackEmaParams.emaPeriod, pullbackEmaParams.trendEma, setResults, setFibResults]);

  const inspectionRisk = useRiskStore(s=>s.limits);
  const inspectionWatchlist = useWatchlistStore(s=>s.added);
  const manualSymbols = parseSymbols(symbolOverride);
  const inspectionSymbols = manualSymbols.length ? manualSymbols : universePick === 'Custom' ? parseSymbols(customRaw) : universePick === 'Watchlist' ? inspectionWatchlist : [];
  const inspectionUniverse = inspectionSymbols.length || universePick === 'Custom' || universePick === 'Watchlist' ? null : [universePick];
  const inspectionInputs = scanMode === 'pullback' ? {universe:inspectionUniverse??inspectionSymbols,direction,horizon:_horizonEnum(context?.horizon),strategy:'pullback_ema',pullback_ema_period:pullbackEmaParams.emaPeriod,pullback_trend_ema:pullbackEmaParams.trendEma,account_size:inspectionRisk.portfolioValue,risk_pct:inspectionRisk.maxLossPerTradePct} : {symbols:inspectionSymbols,universe:inspectionUniverse,direction,params_override:scanMode==='fib'?{fib_swing_lookback:fibParams.fibSwingLookback,fib_levels:fibParams.fibLevels,fib_tolerance_pct:fibParams.fibTolerancePct,ema_filter_period:fibParams.emaFilterPeriod}:{atr_compression_ratio:params.atrCompressionRatio,atr_avg_lookback:params.atrAvgLookback,range_atr_mult:params.rangeAtrMult,range_lookback_bars:params.rangeLookbackBars,vol_compression_ratio:params.volCompressionRatio,resistance_proximity_pct:params.resistanceProximityPct,swing_lookback:params.swingLookback}};
  const sorted: ScanRow[] = [...preResults].sort((a, b) => b.confidence - a.confidence);

  const activeRows = scanMode === 'prebreakout' ? sorted : scanMode === 'fib' ? fibResults : pullbackResults;
  const sourceRows = scanMode === 'prebreakout' ? preResults : scanMode === 'fib' ? fibResults : pullbackResults;
  const applied = scanSnapshot(sourceRows);
  const preApplied = scanSnapshot(preResults)?.pre;
  const fibApplied = scanSnapshot(fibResults)?.fib;
  const selected = activeRows.find(row => row.symbol === selectedSymbol) ?? null;
  useEffect(() => { setSelectedSymbol(null); }, [scanMode]);
  useEffect(() => { if (!activeRows.some(row => row.symbol === selectedSymbol)) setSelectedSymbol(null); }, [activeRows, selectedSymbol]);
  const selectionProps = (symbol: string) => ({
    role: 'button' as const, tabIndex: 0, 'aria-label': `Select ${symbol}`, 'aria-pressed': selectedSymbol === symbol,
    onClick: (event: React.MouseEvent) => { if (!(event.target as HTMLElement).closest('button')) setSelectedSymbol(symbol); },
    onKeyDown: (event: React.KeyboardEvent) => { if (event.target !== event.currentTarget) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedSymbol(symbol); } },
  });
  const chartShell = <section className={styles.chartShell} role="region" aria-label="Selected setup chart">
    <Title as="h2" size={20}>Selected setup</Title>
    <div aria-label="Selected setup"><Text size={13} tone="secondary">{selected?.symbol ?? 'Select a candidate'}</Text></div>
    <Text size={12} tone="dim">{selected ? 'Chart data unavailable.' : 'Select a row to inspect its chart.'}</Text>
    {selected && <Text size={11} tone="dim">{applied ? `${applied.scope.direction} · ${applied.scope.horizon ?? 'Horizon unavailable'} · ${applied.scope.mode}` : 'Scan snapshot unavailable'}</Text>}
  </section>;

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
          Scanning {universeLabel} · {direction} · {context?.horizon ?? 'Horizon unavailable'}
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
          Pullback to EMA {pullbackEmaParams.emaPeriod}
        </button>
        <button
          type="button"
          aria-pressed={scanMode === 'fib'}
          className={`${styles.modeBtn} ${scanMode === 'fib' ? styles.modeBtnActive : ''}`}
          onClick={() => setScanMode('fib')}
        >
          Fib Pullback
        </button>
      </div>

      <details><summary>Analysis log</summary><SavedScanReportInspector category={scanMode} currentInputs={inspectionInputs} tableRunId={tableRunIds[scanMode]} /></details>

      {scanMode === 'pullback' ? (
        <>
          <Text size={12} tone="dim">
            Trending stocks that have pulled back to EMA {pullbackEmaParams.emaPeriod} (confirmed by EMA {pullbackEmaParams.trendEma} trend). Results are ranked by stock score.
          </Text>

          <details className={styles.paramsPanel}>
            <summary className={styles.paramsSummary}>
              <Text size={12} tone="secondary">Scan parameters</Text>
            </summary>
            <div className={styles.pullbackParamsGrid}>
              <label className={styles.paramLabel}>
                <Text size={11} tone="dim">Signal MA — EMA {pullbackEmaParams.emaPeriod}</Text>
                <Text size={10} tone="dim">
                  Price must pull back to within 4% of this EMA from above (bullish) or bounce up to within 4% from below (bearish).
                  ↑ Higher period → longer-term support level · ↓ Lower → faster-reacting MA
                </Text>
                <div className={styles.paramInput}>
                  <input
                    type="number"
                    value={pullbackEmaParams.emaPeriod}
                    min={5} max={200} step={1}
                    onChange={(e) => setPullbackEmaParams((p) => ({ ...p, emaPeriod: Number(e.target.value) }))}
                  />
                  <Text size={11} tone="dim">periods</Text>
                </div>
              </label>
              <label className={styles.paramLabel}>
                <Text size={11} tone="dim">Trend MA — EMA {pullbackEmaParams.trendEma}</Text>
                <Text size={10} tone="dim">
                  Confirms the overall trend direction. Signal EMA must be above this for bullish, below for bearish.
                  ↑ Higher period → filters for stronger established trends only
                </Text>
                <div className={styles.paramInput}>
                  <input
                    type="number"
                    value={pullbackEmaParams.trendEma}
                    min={20} max={500} step={5}
                    onChange={(e) => setPullbackEmaParams((p) => ({ ...p, trendEma: Number(e.target.value) }))}
                  />
                  <Text size={11} tone="dim">periods</Text>
                </div>
              </label>
              <button
                type="button"
                className={styles.resetBtn}
                onClick={() => setPullbackEmaParams({ emaPeriod: 50, trendEma: 100 })}
              >
                Reset to defaults
              </button>
            </div>
          </details>

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

          {error && <Text size={12} tone="reject">{error}</Text>}

          {(
            <div className={styles.resultsGrid}><div className={styles.tableWrap}>
              <div className={styles.tableHeader}>
                <span />
                <Text size={11} tone="dim" weight={500}>Symbol</Text>
                <Text size={11} tone="dim" weight={500}>Company</Text>
                <Text size={11} tone="dim" weight={500}>Dir</Text>
                <Text size={11} tone="dim" weight={500}>Score</Text>
                <Text size={11} tone="dim" weight={500}>Price</Text>
                <Text size={11} tone="dim" weight={500}>Confidence</Text>
                <span />
              </div>
              {pullbackResults.map((row) => (
                <div key={row.symbol} {...selectionProps(row.symbol)} className={styles.tableRow}>
                  <WatchStar symbol={row.symbol} size="sm" />
                  <Text size={13} weight={500}>{row.symbol}</Text>
                  <Text size={12} tone="secondary">{row.company}</Text>
                  <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : 'reject'}>
                    {row.direction === 'Bullish' ? '↑' : '↓'}
                  </Text>
                  <Data
                    size={13}
                    tone={toneForStatus(statusForScore(row.stock_score))}
                    title={`Pullback setup score: ${row.stock_score}/100. ≥70 = strong setup, 40-69 = borderline, <40 = weak.`}
                  >
                    {row.stock_score}
                  </Data>
                  <Data size={12} tone="secondary">${row.price.toFixed(2)}</Data>
                  <Data
                    size={13}
                    tone={confidenceTone(confidenceTier(row.confidence))}
                    title={row.confidence != null
                      ? `Backtest-based signal confidence: ${row.confidence}%.\nHow it's calculated: the strategy engine ran this setup against historical data. The score reflects how often similar pullback-to-EMA setups led to a profitable move within the selected horizon. 60%+ = PASS gate.`
                      : undefined}
                  >
                    {row.confidence != null ? `${row.confidence}%` : '—'}
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
            </div>{chartShell}</div>
          )}

          {pullbackResults.length === 0 && !scanning && !error && (
            <Text size={12} tone="dim">No results yet — run the scan.</Text>
          )}
        </>
      ) : scanMode === 'fib' ? (
        <>
          <Text size={12} tone="dim">
            Stocks retracing to a key Fibonacci level ({fibApplied ? fibApplied.fibLevels.map(level => `${level}%`).join(', ') : 'scanned levels unavailable'}) after a significant swing move.
            At-level hits are sorted first. Set a regime alert to be notified when conditions align.
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

          <FibPullbackParamsPanel
            params={fibParams}
            setParams={setFibParams}
            onReset={() => setFibParams({ ...FIB_PULLBACK_DEFAULTS })}
          />

          {error && <Text size={12} tone="reject">{error}</Text>}

          {(
            <div className={styles.resultsGrid}><div className={styles.tableWrap}>
              <div className={styles.fibTableHeader}>
                <span />
                <Text size={11} tone="dim" weight={500}>Symbol</Text>
                <Text size={11} tone="dim" weight={500}>Dir</Text>
                <Text size={11} tone="dim" weight={500}>Fib Level</Text>
                <Text size={11} tone="dim" weight={500}>Distance</Text>
                <Text size={11} tone="dim" weight={500}>At Level</Text>
                <Text size={11} tone="dim" weight={500}>Confidence</Text>
                <span />
              </div>
              {(fibResults as FibScanRow[]).map((row) => (
                <div key={row.symbol} {...selectionProps(row.symbol)} className={styles.fibTableRow}>
                  <div className={styles.iconCell}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={() => window.open(`/chart?symbol=${row.symbol}`, '_blank')}
                    >
                      📈
                    </button>
                  </div>
                  <Text size={13} weight={500}>{row.symbol}</Text>
                  <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : 'reject'}>
                    {row.direction === 'Bullish' ? '↑' : '↓'}
                  </Text>
                  <Data size={12} tone="secondary">{row.fib_level_hit}%</Data>
                  <Data
                    size={12}
                    tone={fibApplied && row.fib_dist_pct != null ? row.fib_dist_pct <= fibApplied.fibTolerancePct * 100 ? 'pass' : 'caution' : 'secondary'}
                    title={fibApplied ? `Distance from current price to the nearest Fibonacci level. ≤${fmtThreshold(fibApplied.fibTolerancePct * 100, 1)}% scanned tolerance = within range.` : 'Scanned tolerance unavailable'}
                  >
                    {row.fib_dist_pct != null ? `${row.fib_dist_pct.toFixed(1)}%` : '—'}
                  </Data>
                  <Data
                    size={12}
                    tone={row.at_level ? 'pass' : 'dim'}
                    title={row.at_level ? 'Price is currently within the tolerance band of the Fib level.' : 'Price is outside the tolerance band right now.'}
                  >
                    {row.at_level ? 'YES' : 'no'}
                  </Data>
                  <Data
                    size={13}
                    tone={confidenceTone(confidenceTier(row.confidence))}
                    title={`Fib proximity confidence: ${row.confidence}%.\nHow it's calculated: 100% = exactly at the Fibonacci level. Drops toward 60% the further price is within the tolerance band (default 1.5%). Falls below 60% once price is outside that band. This score only measures distance to the fib level — it does NOT check volatility, volume, or trend.`}
                  >
                    {row.confidence}%
                  </Data>
                  <button
                    type="button"
                    className={styles.alertBtn}
                    onClick={() => setAlertSymbol(row.symbol)}
                    title="Set alert"
                  >
                    +
                  </button>
                </div>
              ))}
            </div>{chartShell}</div>
          )}

          {fibResults.length === 0 && !scanning && !error && (
            <Text size={12} tone="dim">No results yet — run the scan.</Text>
          )}
        </>
      ) : (
        <>
          <Text size={12} tone="dim">
            Stocks coiling near a key swing level — ATR compressed, volume dry, close
            within {preApplied ? fmtThreshold(preApplied.resistanceProximityPct * 100, 1) + '%' : 'an unavailable scanned distance'} of the {direction === 'Bullish' ? 'swing high' : 'swing low'}.
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

          {(
            <div className={styles.resultsGrid}><div className={styles.tableWrap}>
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
                <div key={row.symbol} {...selectionProps(row.symbol)} className={styles.tableRow}>
                  <div className={styles.iconCell}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={() => window.open(`/chart?symbol=${row.symbol}`, '_blank')}
                    >
                      📈
                    </button>
                  </div>
                  <Text size={13} weight={500}>{row.symbol}</Text>
                  <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : 'reject'}>
                    {row.direction === 'Bullish' ? '↑' : '↓'}
                  </Text>
                  <Data
                    size={13}
                    tone={confidenceTone(confidenceTier(row.confidence))}
                    title={`Setup quality confidence: ${row.confidence}%.\nHow it's calculated: weighted composite of three factors — ATR compression (30%), volume quiet (25%), proximity to key level (45%). Each factor scores 0–100 based on how extreme the reading is. Example: ATR ratio 0.60 on a 0.85 threshold scores ~29/100 on that factor. All four hard gates must pass first (ATR compressed, range tight, volume quiet, price near resistance) — the score then reflects how good each factor is within the gates.`}
                  >
                    {row.confidence}%
                  </Data>
                  <Data
                    size={12}
                    tone="secondary"
                    title={row.metrics.atr_ratio != null
                      ? `ATR Ratio: ${row.metrics.atr_ratio.toFixed(3)}\nCurrent ATR ÷ ${preApplied ? preApplied.atrAvgLookback : 'unknown'}-bar average ATR. Lower = more compressed volatility = tighter coil. Must be below ${preApplied ? fmtThreshold(preApplied.atrCompressionRatio, 2) : 'unavailable (scan snapshot unknown)'} to pass. Contributes 30% of the confidence score.`
                      : undefined}
                  >
                    {row.metrics.atr_ratio != null ? row.metrics.atr_ratio.toFixed(2) : '—'}
                  </Data>
                  <Data
                    size={12}
                    tone="secondary"
                    title={row.metrics.vol_ratio != null
                      ? `Volume Ratio: ${row.metrics.vol_ratio.toFixed(3)}\nLast bar volume ÷ 20-bar average volume. Lower = quieter volume = stock coiling without distribution. Must be below ${preApplied ? fmtThreshold(preApplied.volCompressionRatio, 2) : 'unavailable (scan snapshot unknown)'} to pass. Contributes 25% of the confidence score.`
                      : undefined}
                  >
                    {row.metrics.vol_ratio != null ? row.metrics.vol_ratio.toFixed(2) : '—'}
                  </Data>
                  <Data
                    size={12}
                    tone="secondary"
                    title={row.metrics.proximity_pct != null
                      ? `Proximity: ${row.metrics.proximity_pct.toFixed(2)}% from key level\nHow far price is from the ${row.direction === 'Bullish' ? 'swing high (resistance)' : 'swing low (support)'} as a percentage. Lower = closer to the level = better setup. Must be within ${preApplied ? fmtThreshold(preApplied.resistanceProximityPct * 100, 1) : 'unavailable (scan snapshot unknown)'}% to pass. Contributes 45% of the confidence score — the heaviest weight.`
                      : undefined}
                  >
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
            </div>{chartShell}</div>
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
