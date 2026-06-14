'use client';

import { Text } from '@/components/primitives';
import styles from './StrategyParamsPanel.module.css';

export interface StrategyParams {
  pullbackTolerancePct: number;
  pullbackEmaPeriod: number;
  pullbackTrendEma: number;
  pullbackMaType: 'EMA' | 'SMA';
  maCrossoverFast: number;
  maCrossoverSlow: number;
  maCrossoverLookback: number;
  breakoutVolumeMult: number;
  rsiPeriod: number;
  rsiOversold: number;
  rsiTrendSma: number;
  btMinTrades: number;
  btMinWinRate: number;
  eventFilter: 'include' | 'avoid' | 'only_pre_event';
  stockShortlistMax: number;
}

interface Props {
  params: StrategyParams;
  setParams: React.Dispatch<React.SetStateAction<StrategyParams>>;
  onReset: () => void;
}

export function StrategyParamsPanel({ params, setParams, onReset }: Props) {
  return (
    <details className={styles.paramsPanel}>
      <summary className={styles.paramsSummary}>
        <Text size={12} tone="secondary">Scan parameters</Text>
      </summary>

      <div className={styles.paramsGrid}>

        {/* ── Pullback to EMA ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Pullback to EMA</Text>
          <Text size={10} tone="dim">Controls the &quot;Pullback to EMA&quot; strategy — how far a stock can be below the moving average and still qualify, and how the uptrend is confirmed.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Pullback tolerance</Text>
          <Text size={10} tone="dim">Max % below the EMA to still count as a pullback. ↑ Higher → deeper pullbacks qualify (more results) · ↓ Lower → only tight pullbacks pass (fewer)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={Math.round(params.pullbackTolerancePct * 100 * 10) / 10}
              min={0.5} max={15} step={0.5}
              onChange={(e) =>
                setParams((p) => ({ ...p, pullbackTolerancePct: Number(e.target.value) / 100 }))
              }
            />
            <Text size={11} tone="dim">%</Text>
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Pullback EMA period</Text>
          <Text size={10} tone="dim">The EMA the stock must pull back to. ↑ Higher → slower EMA used (e.g. 50), longer trend needed (fewer) · ↓ Lower → faster EMA, more setups (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.pullbackEmaPeriod}
              min={5} max={200} step={5}
              onChange={(e) =>
                setParams((p) => ({ ...p, pullbackEmaPeriod: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Pullback MA type</Text>
          <Text size={10} tone="dim">Type of moving average. EMA reacts faster to recent price; SMA is smoother and less reactive.</Text>
          <div className={styles.maToggle}>
            {(['EMA', 'SMA'] as const).map((t) => (
              <button
                key={t}
                type="button"
                className={`${styles.maToggleBtn} ${params.pullbackMaType === t ? styles.maToggleBtnActive : ''}`}
                onClick={() => setParams((p) => ({ ...p, pullbackMaType: t }))}
              >
                <Text size={11} weight={500}>{t}</Text>
              </button>
            ))}
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Trend EMA period</Text>
          <Text size={10} tone="dim">Longer EMA that defines whether the stock is in an uptrend at all. ↑ Higher → more established trend required (fewer) · ↓ Lower → shorter uptrends qualify (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.pullbackTrendEma}
              min={10} max={500} step={10}
              onChange={(e) =>
                setParams((p) => ({ ...p, pullbackTrendEma: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        {/* ── MA Crossover ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">MA Crossover</Text>
          <Text size={10} tone="dim">Controls the &quot;MA Crossover&quot; strategy — defines the two moving averages and how recently the crossover must have occurred.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">MA crossover fast</Text>
          <Text size={10} tone="dim">Short MA period. ↑ Higher → fewer, more deliberate crossover signals · ↓ Lower → more frequent but noisier crossovers</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.maCrossoverFast}
              min={2} max={100} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, maCrossoverFast: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">MA crossover slow</Text>
          <Text size={10} tone="dim">Long MA period. ↑ Higher → crossover requires a bigger trend reversal (fewer) · ↓ Lower → shorter moves trigger a signal (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.maCrossoverSlow}
              min={5} max={300} step={5}
              onChange={(e) =>
                setParams((p) => ({ ...p, maCrossoverSlow: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">MA crossover lookback</Text>
          <Text size={10} tone="dim">How many bars back a crossover can still be counted as fresh. ↑ Higher → older crossovers qualify (more results) · ↓ Lower → only very recent crossovers (fewer)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.maCrossoverLookback}
              min={1} max={30} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, maCrossoverLookback: Number(e.target.value) }))
              }
            />
            <Text size={11} tone="dim">bars</Text>
          </div>
        </label>

        {/* ── Mean Reversion RSI ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Mean Reversion RSI</Text>
          <Text size={10} tone="dim">Controls the &quot;Mean Reversion RSI&quot; strategy — defines how oversold a stock must be and what uptrend baseline it must still sit above.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">RSI period</Text>
          <Text size={10} tone="dim">Bars used to calculate RSI. ↑ Higher → smoother, slower RSI reading · ↓ Lower → more sensitive, triggers faster</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.rsiPeriod}
              min={2} max={50} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, rsiPeriod: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">RSI oversold level</Text>
          <Text size={10} tone="dim">RSI must be below this to qualify as oversold. ↑ Higher → easier to trigger (less oversold needed), more results · ↓ Lower → deep oversold required, fewer results</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.rsiOversold}
              min={10} max={50} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, rsiOversold: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">RSI trend SMA</Text>
          <Text size={10} tone="dim">SMA the stock must be trading above to confirm it&apos;s still in an uptrend. ↑ Higher → only stocks in longer established uptrends qualify (fewer) · ↓ Lower → shorter uptrends allowed (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.rsiTrendSma}
              min={20} max={500} step={10}
              onChange={(e) =>
                setParams((p) => ({ ...p, rsiTrendSma: Number(e.target.value) }))
              }
            />
          </div>
        </label>

        {/* ── Breakout ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Breakout from Tight Base</Text>
          <Text size={10} tone="dim">Controls the &quot;Breakout&quot; strategy — how much volume surge is required to confirm a genuine breakout above the base high.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Breakout vol multiplier</Text>
          <Text size={10} tone="dim">Required volume as a multiple of average on the breakout day. ↑ Higher → only high-conviction volume spikes pass (fewer, stronger signals) · ↓ Lower → lower volume breakouts qualify (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.breakoutVolumeMult}
              min={1.0} max={3.0} step={0.05}
              onChange={(e) =>
                setParams((p) => ({ ...p, breakoutVolumeMult: Number(e.target.value) }))
              }
            />
            <Text size={11} tone="dim">×</Text>
          </div>
        </label>

        {/* ── Backtest quality gate ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Backtest quality gate</Text>
          <Text size={10} tone="dim">Minimum historical performance a stock&apos;s setup must have shown before it qualifies. Applied to all strategies — stocks that fail are excluded from results.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Min backtest trades</Text>
          <Text size={10} tone="dim">Minimum number of historical signals required for the backtest to be statistically meaningful. ↑ Higher → more data required (fewer qualify) · ↓ Lower → sparse history accepted (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.btMinTrades}
              min={1} max={50} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, btMinTrades: Number(e.target.value) }))
              }
            />
            <Text size={11} tone="dim">trades</Text>
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Min win rate</Text>
          <Text size={10} tone="dim">Minimum % of historical trades that were winners. ↑ Higher → only well-performing past setups qualify (fewer, more accurate) · ↓ Lower → looser past performance accepted (more)</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={Math.round(params.btMinWinRate * 100)}
              min={10} max={80} step={5}
              onChange={(e) =>
                setParams((p) => ({ ...p, btMinWinRate: Number(e.target.value) / 100 }))
              }
            />
            <Text size={11} tone="dim">%</Text>
          </div>
        </label>

        {/* ── Shortlist cap ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Shortlist</Text>
          <Text size={10} tone="dim">Maximum number of stock candidates returned after all gates. Same cap applies to all strategies.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Max candidates</Text>
          <Text size={10} tone="dim">↑ Higher → more stocks pass to Position Card · ↓ Lower → only top-ranked setups shown</Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.stockShortlistMax}
              min={1} max={50} step={1}
              onChange={(e) =>
                setParams((p) => ({ ...p, stockShortlistMax: Math.max(1, Number(e.target.value)) }))
              }
            />
          </div>
        </label>

        {/* ── Event exposure ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Event exposure</Text>
          <Text size={10} tone="dim">Controls whether stocks with upcoming catalysts (earnings, FOMC, dividends) are included, excluded, or exclusively targeted.</Text>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Event exposure</Text>
          <Text size={10} tone="dim">Include = all stocks regardless of events · Avoid = exclude stocks with near-term catalysts (safer, fewer) · Events only = only stocks with upcoming events</Text>
          <div className={styles.maToggle}>
            {(['include', 'avoid', 'only_pre_event'] as const).map((v) => (
              <button
                key={v}
                type="button"
                className={`${styles.maToggleBtn} ${params.eventFilter === v ? styles.maToggleBtnActive : ''}`}
                onClick={() => setParams((p) => ({ ...p, eventFilter: v }))}
              >
                <Text size={11} weight={500}>
                  {v === 'include' ? 'Include' : v === 'avoid' ? 'Avoid' : 'Events only'}
                </Text>
              </button>
            ))}
          </div>
        </label>

        <button type="button" className={styles.resetBtn} onClick={onReset}>
          Reset to saved
        </button>
      </div>
    </details>
  );
}
