'use client';
import { useChartStore, type Interval, type ChartType } from '@/lib/chartStore';
import styles from './ChartTopBar.module.css';

const INTERVALS: Interval[] = ['1min', '5min', '15min', '1h', '4h', '1D', '1W'];

interface Props {
  onToggleIndicators: () => void;
  onToggleStructure: () => void;
  onToggleAlerts?: () => void;
}

export default function ChartTopBar({ onToggleIndicators, onToggleStructure, onToggleAlerts }: Props) {
  const { symbol, interval, chartType, setSymbol, setInterval, setChartType } = useChartStore();

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
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />

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

      <div className={styles.spacer} />

      <button className={styles.popOut} onClick={handlePopOut} title="Open in new window">
        ⧉ Pop out
      </button>
    </div>
  );
}
