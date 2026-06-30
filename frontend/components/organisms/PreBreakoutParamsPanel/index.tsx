'use client';

import { Text } from '@/components/primitives';
import styles from './PreBreakoutParamsPanel.module.css';

export interface PreBreakoutParams {
  atrCompressionRatio: number;    // 0.1–1.0,  default 0.7
  atrAvgLookback: number;         // 5–50,     default 20
  rangeAtrMult: number;           // 0.1–2.0,  default 0.8
  rangeLookbackBars: number;      // 3–30,     default 10
  volCompressionRatio: number;    // 0.1–1.0,  default 0.8
  resistanceProximityPct: number; // 0.01–0.20,default 0.08
  swingLookback: number;          // 10–100,   default 50
  // Fibonacci pullback
  fibEnabled: boolean;            // default false
  fibSwingLookback: number;       // 10–200,   default 100
  fibLevels: number[];            // subset of [23.6, 38.2, 50.0, 61.8, 78.6]
  fibTolerancePct: number;        // 0.005–0.05, default 0.015 (stored as fraction)
}

export const PREBREAKOUT_DEFAULTS: PreBreakoutParams = {
  atrCompressionRatio: 0.7,
  atrAvgLookback: 20,
  rangeAtrMult: 0.8,
  rangeLookbackBars: 10,
  volCompressionRatio: 0.8,
  resistanceProximityPct: 0.08,
  swingLookback: 50,
  fibEnabled: false,
  fibSwingLookback: 100,
  fibLevels: [23.6, 38.2, 50.0, 61.8],
  fibTolerancePct: 0.015,
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
          <Text size={11} tone="dim">ATR average lookback</Text>
          <Text size={10} tone="dim">
            Number of bars used to compute the average ATR that current ATR is compared against.
            ↑ Higher → smoother average (less noise) · ↓ Lower → reacts faster to recent volatility
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.atrAvgLookback}
              min={5} max={50} step={1}
              onChange={(e) => setParams((p) => ({ ...p, atrAvgLookback: Number(e.target.value) }))}
            />
            <Text size={11} tone="dim">bars</Text>
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

        {/* ── Fibonacci pullback ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Fibonacci pullback (optional)</Text>
          <Text size={10} tone="dim">
            When enabled, the scanner also checks if the close is within tolerance of a
            key Fibonacci retracement level (measured from the dominant swing move).
            Price landing near 38.2% or 61.8% of a prior up-move is a high-probability
            support zone. Increases confidence score by up to 20 pts when at a level.
          </Text>
        </div>

        <label className={styles.paramLabel}>
          <div className={styles.paramInput}>
            <input
              type="checkbox"
              checked={params.fibEnabled}
              onChange={(e) => setParams((p) => ({ ...p, fibEnabled: e.target.checked }))}
              id="fib-enabled"
            />
            <Text size={11} tone={params.fibEnabled ? 'primary' : 'dim'}>
              Enable Fibonacci proximity check
            </Text>
          </div>
        </label>

        {params.fibEnabled && (
          <>
            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Fibonacci retracement levels</Text>
              <Text size={10} tone="dim">
                Which levels to treat as support. 38.2% and 61.8% are the most reliable.
                More levels mean more results but more false positives.
              </Text>
              <div className={styles.fibLevels}>
                {[23.6, 38.2, 50.0, 61.8, 78.6].map((lvl) => (
                  <label key={lvl} className={styles.fibLevelCheck}>
                    <input
                      type="checkbox"
                      checked={params.fibLevels.includes(lvl)}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...params.fibLevels, lvl].sort((a, b) => a - b)
                          : params.fibLevels.filter((l) => l !== lvl);
                        setParams((p) => ({ ...p, fibLevels: next }));
                      }}
                    />
                    <Text size={11} tone={params.fibLevels.includes(lvl) ? 'primary' : 'dim'}>
                      {lvl}%
                    </Text>
                  </label>
                ))}
              </div>
            </label>

            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Swing lookback for fib move</Text>
              <Text size={10} tone="dim">
                How many bars back to search for the significant swing high and low
                that define the Fibonacci move. Higher values capture larger structural moves.
              </Text>
              <div className={styles.paramInput}>
                <input
                  type="number"
                  value={params.fibSwingLookback}
                  min={20} max={200} step={5}
                  onChange={(e) => setParams((p) => ({ ...p, fibSwingLookback: Number(e.target.value) }))}
                />
                <Text size={11} tone="dim">bars</Text>
              </div>
            </label>

            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Fib tolerance</Text>
              <Text size={10} tone="dim">
                How close (in %) the close must be to a fib level to count as &quot;at level&quot;.
                Higher values widen the net (more results); lower values require very precise hits.
              </Text>
              <div className={styles.paramInput}>
                <input
                  type="number"
                  value={Math.round(params.fibTolerancePct * 100 * 10) / 10}
                  min={0.5} max={5.0} step={0.1}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, fibTolerancePct: Number(e.target.value) / 100 }))
                  }
                />
                <Text size={11} tone="dim">%</Text>
              </div>
            </label>
          </>
        )}

        <button type="button" className={styles.resetBtn} onClick={onReset}>
          Reset to defaults
        </button>

      </div>
    </details>
  );
}
