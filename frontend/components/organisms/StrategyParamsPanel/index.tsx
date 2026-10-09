'use client';

import { Text } from '@/components/primitives';
import type { OverrideField, ScanParams } from '@/lib/scanParamsStore';
import type { ProfileView, TunedStrategy } from '@/lib/strategyProfilesStore';
import type { TunedHorizon } from '@/lib/horizonPresets';
import styles from './StrategyParamsPanel.module.css';

type PanelOverride = Exclude<OverrideField,
  'meanReversionVariants' | 'meanReversionMinConfirm' | 'vwapLookback' | 'vwapDeviationPct'>;

/** The panel's slice of the scan params. Strategy fields are overrides of the
 *  backend horizon profile: `null` = follow the profile (STOCKS-HORIZON-T1 H5). */
export type StrategyParams = Pick<ScanParams,
  PanelOverride | 'btMinTrades' | 'btMinWinRate' | 'eventFilter' | 'stockShortlistMax'>;

interface Props {
  params: StrategyParams;
  setParams: React.Dispatch<React.SetStateAction<StrategyParams>>;
  onReset: () => void;
  /** The backend profile for the scan's direction x params horizon; null when
   *  none is in hand. */
  profile: ProfileView | null;
  /** True when the profile fetch failed: the panel shows overrides only. */
  profileUnavailable: boolean;
  /** For a Custom horizon, the tuned horizon whose settings the scan uses. */
  customHorizon: TunedHorizon | null;
}

type Setter = Props['setParams'];

function ResetToProfile({ field, label, params, setParams }: {
  field: PanelOverride; label: string; params: StrategyParams; setParams: Setter;
}) {
  if (params[field] === null) return null;
  return (
    <button
      type="button"
      className={styles.fieldReset}
      aria-label={`Reset ${label} to profile`}
      onClick={() => setParams((p) => ({ ...p, [field]: null }))}
    >
      reset to profile
    </button>
  );
}

/** A numeric override input: shows the override if set, else the profile value
 *  (empty when neither is known). Clearing the input drops the override. */
function NumField({ field, label, hint, unit, scale = 1, decimals = 0, min, max, step, params, setParams, profile }: {
  field: PanelOverride; label: string; hint: string; unit?: string; scale?: number; decimals?: number;
  min: number; max: number; step: number;
  params: StrategyParams; setParams: Setter; profile: ProfileView | null;
}) {
  const raw = (params[field] ?? profile?.values[field] ?? null) as number | null;
  const f = 10 ** decimals;
  const shown = raw === null ? '' : Math.round(raw * scale * f) / f;
  return (
    <label className={styles.paramLabel}>
      <Text size={11} tone="dim">{label}</Text>
      <Text size={10} tone="dim">{hint}</Text>
      <div className={styles.paramInput}>
        <input
          type="number"
          aria-label={label}
          value={shown}
          min={min} max={max} step={step}
          onChange={(e) => {
            const v = e.target.value;
            setParams((p) => ({ ...p, [field]: v === '' ? null : Number(v) / scale }));
          }}
        />
        {unit && <Text size={11} tone="dim">{unit}</Text>}
        <ResetToProfile field={field} label={label} params={params} setParams={setParams} />
      </div>
    </label>
  );
}

function SectionHeader({ title, blurb, strategy, profile }: {
  title: string; blurb: string; strategy: TunedStrategy; profile: ProfileView | null;
}) {
  return (
    <div className={styles.paramSection}>
      <div className={styles.sectionTitle}>
        <Text size={11} weight={500} tone="secondary">{title}</Text>
        {profile && (
          <span className={styles.sourceTag} data-testid={`profile-source-${strategy}`}>
            <Text size={10} tone={profile.sources[strategy] === 'tuned' ? 'pass' : 'dim'}>
              {profile.sources[strategy]}
            </Text>
          </span>
        )}
      </div>
      <Text size={10} tone="dim">{blurb}</Text>
    </div>
  );
}

export function StrategyParamsPanel({
  params, setParams, onReset, profile, profileUnavailable, customHorizon,
}: Props) {
  const maType = params.pullbackMaType ?? profile?.values.pullbackMaType ?? null;
  const choppy = params.requireChoppyRegime ?? profile?.values.requireChoppyRegime ?? false;
  const common = { params, setParams, profile };
  return (
    <details className={styles.paramsPanel}>
      <summary className={styles.paramsSummary}>
        <Text size={12} tone="secondary">Scan parameters</Text>
      </summary>

      <div className={styles.paramsGrid}>

        <div className={styles.profileNote}>
          <Text size={10} tone="dim">
            Values follow the backend profile for this direction and horizon. An edit overrides it for this scan.
          </Text>
          {customHorizon && <Text size={11} tone="secondary">{`Custom: using ${customHorizon} settings`}</Text>}
          {profileUnavailable && (
            <Text size={11} tone="caution">{'Profile unavailable — the scan uses the backend\'s values'}</Text>
          )}
        </div>

        {/* ── Pullback to EMA ── */}
        <SectionHeader
          title="Pullback to EMA" strategy="pullback_ema" profile={profile}
          blurb={'Controls the "Pullback to EMA" strategy — how far a stock can be below the moving average and still qualify, and how the uptrend is confirmed.'}
        />

        <NumField {...common} field="pullbackTolerancePct" label="Pullback tolerance" unit="%" scale={100} decimals={1}
          min={0.5} max={15} step={0.5}
          hint="Max % below the EMA to still count as a pullback. ↑ Higher → deeper pullbacks qualify (more results) · ↓ Lower → only tight pullbacks pass (fewer)" />

        <NumField {...common} field="pullbackEmaPeriod" label="Pullback EMA period" min={5} max={200} step={5}
          hint="The EMA the stock must pull back to. ↑ Higher → slower EMA used (e.g. 50), longer trend needed (fewer) · ↓ Lower → faster EMA, more setups (more)" />

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Pullback MA type</Text>
          <Text size={10} tone="dim">Type of moving average. EMA reacts faster to recent price; SMA is smoother and less reactive.</Text>
          <div className={styles.maToggle}>
            {(['EMA', 'SMA'] as const).map((t) => (
              <button
                key={t}
                type="button"
                className={`${styles.maToggleBtn} ${maType === t ? styles.maToggleBtnActive : ''}`}
                onClick={() => setParams((p) => ({ ...p, pullbackMaType: t }))}
              >
                <Text size={11} weight={500}>{t}</Text>
              </button>
            ))}
            <ResetToProfile field="pullbackMaType" label="Pullback MA type" params={params} setParams={setParams} />
          </div>
        </label>

        <NumField {...common} field="pullbackTrendEma" label="Trend EMA period" min={10} max={500} step={10}
          hint="Longer EMA that defines whether the stock is in an uptrend at all. ↑ Higher → more established trend required (fewer) · ↓ Lower → shorter uptrends qualify (more)" />

        {/* ── MA Crossover ── */}
        <SectionHeader
          title="MA Crossover" strategy="ma_crossover" profile={profile}
          blurb={'Controls the "MA Crossover" strategy — defines the two moving averages and how recently the crossover must have occurred.'}
        />

        <NumField {...common} field="maCrossoverFast" label="MA crossover fast" min={2} max={100} step={1}
          hint="Short MA period. ↑ Higher → fewer, more deliberate crossover signals · ↓ Lower → more frequent but noisier crossovers" />

        <NumField {...common} field="maCrossoverSlow" label="MA crossover slow" min={5} max={300} step={5}
          hint="Long MA period. ↑ Higher → crossover requires a bigger trend reversal (fewer) · ↓ Lower → shorter moves trigger a signal (more)" />

        <NumField {...common} field="maCrossoverLookback" label="MA crossover lookback" unit="bars" min={1} max={30} step={1}
          hint="How many bars back a crossover can still be counted as fresh. ↑ Higher → older crossovers qualify (more results) · ↓ Lower → only very recent crossovers (fewer)" />

        {/* ── Mean Reversion RSI ── */}
        <SectionHeader
          title="Mean Reversion RSI" strategy="mean_reversion_rsi" profile={profile}
          blurb={'Controls the "Mean Reversion RSI" strategy — defines how oversold a stock must be and what uptrend baseline it must still sit above.'}
        />
        <div className={styles.sectionNote}>
          <Text size={10} tone="dim">These RSI settings apply to the RSI strategy and to the RSI signal of Mean Reversion Multi-Signal.</Text>
        </div>

        <NumField {...common} field="rsiPeriod" label="RSI period" min={2} max={50} step={1}
          hint="Bars used to calculate RSI. ↑ Higher → smoother, slower RSI reading · ↓ Lower → more sensitive, triggers faster" />

        <NumField {...common} field="rsiOversold" label="RSI oversold level" min={10} max={50} step={1}
          hint="Bullish: RSI must be below this to qualify as oversold. ↑ Higher → easier to trigger (less oversold needed), more results · ↓ Lower → deep oversold required, fewer results" />

        <NumField {...common} field="rsiOverbought" label="RSI overbought level" min={50} max={90} step={1}
          hint="Bearish: RSI must be above this to qualify as overbought. ↓ Lower → easier to trigger, more results · ↑ Higher → deep overbought required, fewer results" />

        <NumField {...common} field="rsiTrendSma" label="RSI trend SMA" min={20} max={500} step={10}
          hint="SMA the stock must be trading above to confirm it's still in an uptrend. ↑ Higher → only stocks in longer established uptrends qualify (fewer) · ↓ Lower → shorter uptrends allowed (more)" />

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Require Choppy regime (mean reversion RSI only)</Text>
          <Text size={10} tone="dim">When enabled, the mean-reversion RSI signal only fires when the OMM market regime is Choppy — more selective but higher precision in range-bound markets.</Text>
          <div className={styles.paramInput}>
            <input
              type="checkbox"
              checked={choppy}
              onChange={(e) =>
                setParams((p) => ({ ...p, requireChoppyRegime: e.target.checked }))
              }
            />
            <Text size={11} tone="secondary">Require Choppy regime</Text>
            <ResetToProfile field="requireChoppyRegime" label="Require Choppy regime" params={params} setParams={setParams} />
          </div>
        </label>

        {/* ── Breakout ── */}
        <SectionHeader
          title="Breakout from Tight Base" strategy="breakout_base" profile={profile}
          blurb={'Controls the "Breakout" strategy — how much volume surge is required to confirm a genuine breakout above the base high.'}
        />

        <NumField {...common} field="breakoutVolumeMult" label="Breakout vol multiplier" unit="×" decimals={2}
          min={1.0} max={3.0} step={0.05}
          hint="Required volume as a multiple of average on the breakout day. ↑ Higher → only high-conviction volume spikes pass (fewer, stronger signals) · ↓ Lower → lower volume breakouts qualify (more)" />

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
