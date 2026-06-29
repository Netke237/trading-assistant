'use client';

import { useState, useEffect, useCallback } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { WatchStar } from '@/components/atoms/WatchStar';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { CompositeAlertDialog } from '@/components/organisms/CompositeAlertDialog';
import styles from './page.module.css';

type ScanRow = { symbol: string; confidence: number; direction: string; metrics: Record<string, number> };

function _confidenceTone(c: number): 'pass' | 'caution' | 'reject' {
  return c >= 70 ? 'pass' : c >= 40 ? 'caution' : 'reject';
}

export default function Step4PreBreakoutPage() {
  const context     = useScanStore((s) => s.context);
  const direction   = context?.direction ?? 'Bullish';
  const prevResults = useScanStore((s) => s.stockScanResult);
  const preResults  = useScanStore((s) => s.preBreakoutResults);
  const setResults  = useScanStore((s) => s.setPreBreakoutResults);

  const [symbolInput, setSymbolInput] = useState('');
  const [scanning, setScanning]       = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [alertSymbol, setAlertSymbol] = useState<string | null>(null);

  useEffect(() => {
    if (prevResults?.candidates?.length) {
      setSymbolInput(prevResults.candidates.map((c) => c.symbol).join(', '));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const runScan = useCallback(async () => {
    const symbols = symbolInput
      .split(/[\s,\n]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!symbols.length) { setError('Enter at least one symbol.'); return; }
    setError(null);
    setScanning(true);
    try {
      const results = await api.prebreakoutScan(symbols, direction);
      setResults(results);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScanning(false);
    }
  }, [symbolInput, direction, setResults]);

  const sorted: ScanRow[] = [...preResults].sort((a, b) => b.confidence - a.confidence);

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Title as="h2" size={20}>Pre-Breakout Scanner</Title>
        <Text size={13} tone="secondary">
          Identify stocks in consolidation near a key level, ready to break out. Set a Markov regime alert to be notified when conditions align.
        </Text>
      </div>

      <div className={styles.inputRow}>
        <textarea
          className={styles.symbolInput}
          rows={3}
          placeholder="AAPL, MSFT, TSLA..."
          value={symbolInput}
          onChange={(e) => setSymbolInput(e.target.value)}
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
        <Text size={13} tone="dim">No results yet — enter symbols and run the scan.</Text>
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
