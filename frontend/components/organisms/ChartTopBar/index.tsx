'use client';
import { useEffect } from 'react';
import { useChartStore, type Interval, type ChartType } from '@/lib/chartStore';
import { WatchStar } from '@/components/atoms/WatchStar';
import { api } from '@/lib/api';
import type { ConnectionState } from '@/lib/chartWS';
import styles from './ChartTopBar.module.css';

const INTERVALS: Interval[] = ['1min', '5min', '15min', '1h', '4h', '1D', '1W'];

const CONN_STATE_CLASS: Record<ConnectionState, string> = {
  connecting:   styles.connecting,
  connected:    '',
  reconnecting: styles.reconnecting,
  error:        styles.error,
};

interface Props {
  onToggleIndicators: () => void;
  onToggleStructure: () => void;
  onToggleAlerts?: () => void;
  onToggleRegime?: () => void;
  showRegime?: boolean;
  regimeModel?: 'OMM' | 'HMM';
  onSetRegimeModel?: (model: 'OMM' | 'HMM') => void;
  connState?: ConnectionState;
  wsError?: string | null;
}

export default function ChartTopBar({ onToggleIndicators, onToggleStructure, onToggleAlerts, onToggleRegime, showRegime, regimeModel, onSetRegimeModel, connState, wsError }: Props) {
  const { symbol, interval, chartType, symbolName, setSymbol, setInterval, setChartType, setSymbolName } = useChartStore();

  // Fetch company name whenever the active symbol changes.
  useEffect(() => {
    let cancelled = false;
    api.getSymbolInfo(symbol)
      .then(({ name }) => { if (!cancelled) setSymbolName(name); })
      .catch(() => { if (!cancelled) setSymbolName(symbol); });
    return () => { cancelled = true; };
  }, [symbol, setSymbolName]);

  const handleSymbolKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      setSymbol(e.currentTarget.value.toUpperCase().trim());
    }
  };

  const handlePopOut = () => {
    window.open(`/chart/standalone?symbol=${symbol}&interval=${interval}`, '_blank', 'width=1400,height=900');
  };

  return (
    <div className={styles.bar}>
      <WatchStar symbol={symbol} size="sm" />
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        key={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />

      {symbolName && symbolName !== symbol && (
        <span className={styles.symbolName}>{symbolName}</span>
      )}

      <div className={styles.intervals}>
        {INTERVALS.map(i => (
          <button
            key={i}
            className={`${styles.tf} ${interval === i ? styles.tfActive : ''}`}
            onClick={() => setInterval(i)}
          >
            {i}
          </button>
        ))}
      </div>

      <select
        className={styles.chartType}
        value={chartType}
        onChange={(e) => setChartType(e.target.value as ChartType)}
        aria-label="Chart type"
      >
        <option value="candle">Candles</option>
        <option value="bar">Bars</option>
        <option value="line">Line</option>
      </select>

      <button className={styles.btn} onClick={onToggleIndicators}>Indicators</button>
      <button className={styles.btn} onClick={onToggleStructure}>Structure</button>
      {onToggleAlerts && <button className={styles.btn} onClick={onToggleAlerts}>Alerts</button>}
      {onToggleRegime && (
        <button
          className={`${styles.btn} ${showRegime ? styles.btnActive : ''}`}
          onClick={onToggleRegime}
        >
          Regime
        </button>
      )}
      {showRegime && onSetRegimeModel && (
        <>
          <button
            className={`${styles.modelBtn} ${regimeModel === 'OMM' ? styles.modelBtnActive : ''}`}
            onClick={() => onSetRegimeModel('OMM')}
            title="Observable Markov Model — Bull / Bear / Choppy"
          >
            OMM
          </button>
          <button
            className={`${styles.modelBtn} ${regimeModel === 'HMM' ? styles.modelBtnActive : ''}`}
            onClick={() => onSetRegimeModel('HMM')}
            title="Hidden Markov Model — Bull / Bear / Sideways (daily) or Trending / Choppy / Mean-reverting (intraday)"
          >
            HMM
          </button>
        </>
      )}

      {connState && connState !== 'connected' && (
        <span
          className={`${styles.connBadge} ${CONN_STATE_CLASS[connState]}`}
          title={wsError ?? connState}
        >
          {connState === 'connecting'   ? 'Connecting…'  :
           connState === 'reconnecting' ? 'Reconnecting…' :
           wsError ?? 'Error'}
        </span>
      )}

      <div className={styles.spacer} />

      <button className={styles.popOut} onClick={handlePopOut} title="Open in new window">
        ⧉ Pop out
      </button>
    </div>
  );
}
