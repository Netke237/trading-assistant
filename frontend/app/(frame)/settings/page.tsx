'use client';

/*
 * Settings — Phase 5.
 * Sub-nav on the left, form sections on the right, sticky Save / Reset footer
 * at the bottom of the workspace. Drift log Screen 6 — regular-weight labels
 * (no font-weight:600) and no card shadows on form rows.
 *
 * Each section opens with an intro block explaining what the controls affect;
 * each row shows a "Default" pill so the user knows what the out-of-the-box
 * value is and can tell at a glance if they've drifted.
 */

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { useSettingsStore } from '@/lib/settingsStore';
import type { WeightKey, CustomWeights, CustomParams } from '@/lib/settingsStore';
import styles from './page.module.css';

type Section = 'broker' | 'theme' | 'weights' | 'alerts';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'broker',  label: 'Broker',     desc: 'Credentials + paper trade toggle' },
  { key: 'theme',   label: 'Appearance', desc: 'Theme + density' },
  { key: 'weights', label: 'Score weights', desc: 'Trend, pullback, trigger, event, volatility' },
  { key: 'alerts',  label: 'Alerts',     desc: 'Stop-loss and event notifications' },
];

export default function SettingsPage() {
  const [active, setActive] = useState<Section>('broker');
  const { resetToDefaults } = useSettingsStore();

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Settings</Title>
      </div>

      <div className={styles.shell}>
        <aside className={styles.subnav}>
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => setActive(s.key)}
              className={`${styles.subnavItem} ${s.key === active ? styles.subnavActive : ''}`}
            >
              <Text size={13} weight={400}>{s.label}</Text>
              <Text size={11} tone="secondary">{s.desc}</Text>
            </button>
          ))}
        </aside>

        <div className={styles.panel}>
          {active === 'broker'  && <BrokerForm  />}
          {active === 'theme'   && <ThemeForm   />}
          {active === 'weights' && <WeightsForm />}
          {active === 'alerts'  && <AlertsForm  />}
        </div>
      </div>

      {/* Sticky footer */}
      <footer className={styles.footer}>
        <button type="button" className={styles.btn} onClick={resetToDefaults}>Reset</button>
        <SaveButton />
      </footer>
    </div>
  );
}

function SectionIntro({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className={styles.intro}>
      <Text size={14} weight={600}>{title}</Text>
      <Text size={12} tone="secondary">{blurb}</Text>
    </div>
  );
}

function Row({
  label,
  hint,
  defaultValue,
  children,
}: {
  label: string;
  hint?: string;
  defaultValue?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.row}>
      <div className={styles.rowLabel}>
        <Text size={13} weight={400}>{label}</Text>
        {hint && <Text size={11} tone="secondary">{hint}</Text>}
        {defaultValue !== undefined && (
          <span className={styles.defaultTag} title="Out-of-the-box value">
            Default: {defaultValue}
          </span>
        )}
      </div>
      <div className={styles.rowControl}>{children}</div>
    </div>
  );
}

/* ---------- Save button ---------- */

function SaveButton() {
  const [saved, setSaved] = useState(false);
  const { customW, customParams, broker } = useSettingsStore();

  function handleSave() {
    // Already persisted via Zustand — just flash confirmation.
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <button
      type="button"
      className={`${styles.btn} ${styles.btnPrimary}`}
      onClick={handleSave}
      disabled={saved}
    >
      {saved ? 'Saved' : 'Save changes'}
    </button>
  );
}

/* ---------- Broker ---------- */

function BrokerForm() {
  const { broker, setBroker } = useSettingsStore();
  const [localBroker, setLocalBroker] = useState(broker.broker);
  const [localAccount, setLocalAccount] = useState(broker.account);
  const [localToken, setLocalToken] = useState(broker.apiToken);
  const [localPaper, setLocalPaper] = useState(broker.paperTrading);

  // Sync local state when store updates (e.g. after reset)
  useEffect(() => {
    setLocalBroker(broker.broker);
    setLocalAccount(broker.account);
    setLocalToken(broker.apiToken);
    setLocalPaper(broker.paperTrading);
  }, [broker]);

  function updateBroker(patch: Partial<typeof broker>) {
    setBroker({ ...broker, ...patch });
  }

  return (
    <>
      <SectionIntro
        title="Broker connection"
        blurb="Where your trades execute. Paper mode is strongly recommended until you've run the app through a full cycle."
      />
      <Row label="Broker" hint="Interactive Brokers, Tradier, TastyTrade…" defaultValue="Interactive Brokers">
        <select
          className={styles.input}
          value={localBroker}
          onChange={(e) => {
            setLocalBroker(e.target.value);
            updateBroker({ broker: e.target.value });
          }}
        >
          <option>Interactive Brokers</option>
          <option>Tradier</option>
          <option>TastyTrade</option>
        </select>
      </Row>
      <Row label="Account ID" hint="Shown on your statements" defaultValue="—">
        <input
          className={styles.input}
          placeholder="U1234567"
          value={localAccount}
          onChange={(e) => {
            setLocalAccount(e.target.value);
            updateBroker({ account: e.target.value });
          }}
        />
      </Row>
      <Row label="API token" hint="Stored locally. Never transmitted to our servers." defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="••••••••••••"
          value={localToken}
          onChange={(e) => {
            setLocalToken(e.target.value);
            updateBroker({ apiToken: e.target.value });
          }}
        />
      </Row>
      <Row label="Paper trading" hint="Simulated fills — no real orders" defaultValue="On">
        <Toggle
          defaultOn={localPaper}
          onChange={(on) => {
            setLocalPaper(on);
            updateBroker({ paperTrading: on });
          }}
        />
      </Row>
    </>
  );
}

/* ---------- Theme ---------- */

function ThemeForm() {
  const [density, setDensity] = useState<'Comfortable' | 'Compact'>('Comfortable');
  return (
    <>
      <SectionIntro
        title="Appearance"
        blurb="Visual preferences. Theme and density persist per browser."
      />
      <Row label="Theme" hint="Persisted in localStorage; synced across tabs" defaultValue="Dark">
        <ModeToggle />
      </Row>
      <Row label="Row density" hint="Compact saves vertical space in long tables" defaultValue="Comfortable">
        <select
          className={styles.input}
          value={density}
          onChange={(e) => setDensity(e.target.value as 'Comfortable' | 'Compact')}
        >
          <option>Comfortable</option>
          <option>Compact</option>
        </select>
      </Row>
    </>
  );
}

/* ---------- Weights ---------- */

type WeightHorizon = 'Intraday' | 'Swing' | 'Position' | 'Custom';

const WEIGHT_DEFAULTS = {
  Trend: 25, Pullback: 20, Trigger: 20, Event: 15, Volatility: 20,
} as const;

const WEIGHT_HINTS: Record<keyof typeof WEIGHT_DEFAULTS, string> = {
  Trend:      'Medium-term direction — higher = bias toward trending stocks.',
  Pullback:   'Rewards healthy retracements to support, penalizes extension.',
  Trigger:    'Short-term entry signal strength (engulfing, breakout close).',
  Event:      'Event-calendar clearance — low values suppress near-earnings names.',
  Volatility: 'IV-rank sweet-spot — rich enough to earn premium, not blown-out.',
};

type WeightMap = CustomWeights;

const WEIGHT_PRESETS: Record<Exclude<WeightHorizon, 'Custom'>, WeightMap> = {
  Intraday: { Trend: 10, Pullback: 15, Trigger: 40, Event: 25, Volatility: 10 },
  Swing:    { Trend: 25, Pullback: 20, Trigger: 20, Event: 15, Volatility: 20 },
  Position: { Trend: 35, Pullback: 25, Trigger: 10, Event: 10, Volatility: 20 },
};

const HORIZON_TABS: { key: WeightHorizon; label: string; hint: string }[] = [
  { key: 'Intraday', label: 'Intraday', hint: '0–2 days'    },
  { key: 'Swing',    label: 'Swing',    hint: '5–15 days'   },
  { key: 'Position', label: 'Position', hint: '15–45 days'  },
  { key: 'Custom',   label: 'Custom',   hint: 'Your profile' },
];

interface ParamSpec {
  key:   string;
  label: string;
  unit:  string;
  min:   number;
  max:   number;
  step:  number;
}

interface MetricDef {
  name:     string;
  desc:     string;
  param?:   ParamSpec;
  presets?: Record<Exclude<WeightHorizon, 'Custom'>, number>;
}

const METRICS_DEF: Record<WeightKey, MetricDef[]> = {
  Trend: [
    {
      name: 'Long-term MA',
      desc: 'Price above = bullish structural context',
      param:   { key: 'longMa', label: 'Period', unit: 'days', min: 20, max: 500, step: 5 },
      presets: { Intraday: 50, Swing: 200, Position: 200 },
    },
    {
      name: 'Medium-term MA slope',
      desc: 'Positive slope confirms trend momentum',
      param:   { key: 'medMa', label: 'Period', unit: 'days', min: 10, max: 200, step: 5 },
      presets: { Intraday: 20, Swing: 50, Position: 50 },
    },
    {
      name: 'ADX',
      desc: '>25 = trending, <20 = ranging',
      param:   { key: 'adxPeriod', label: 'Period', unit: 'days', min: 5, max: 30, step: 1 },
      presets: { Intraday: 7, Swing: 14, Position: 14 },
    },
    { name: 'Higher-highs pattern', desc: 'Swing structure confirms uptrend' },
  ],
  Pullback: [
    {
      name: 'Short-term MA proximity',
      desc: 'Close near MA = healthy retracement zone',
      param:   { key: 'shortMa', label: 'MA period', unit: 'days', min: 5, max: 100, step: 5 },
      presets: { Intraday: 5, Swing: 20, Position: 50 },
    },
    {
      name: 'RSI',
      desc: 'Momentum check — not overbought, not broken',
      param:   { key: 'rsiPeriod', label: 'Period', unit: 'days', min: 5, max: 30, step: 1 },
      presets: { Intraday: 7, Swing: 14, Position: 14 },
    },
    { name: 'Long MA buffer',    desc: 'Price must remain above the structural MA' },
    { name: 'Volume on retrace', desc: 'Below-avg volume = weak selling pressure'  },
  ],
  Trigger: [
    { name: 'Candle pattern', desc: 'Engulfing, hammer, inside-bar breakout' },
    {
      name: 'Volume vs avg',
      desc: 'Confirms institutional interest on the move',
      param:   { key: 'volLookback', label: 'Avg lookback', unit: 'days', min: 5, max: 100, step: 5 },
      presets: { Intraday: 5, Swing: 20, Position: 50 },
    },
    {
      name: 'Volume threshold',
      desc: 'Minimum multiple of the lookback average',
      param:   { key: 'volMultiplier', label: 'Min multiple', unit: '×', min: 1.0, max: 3.0, step: 0.1 },
      presets: { Intraday: 2.0, Swing: 1.5, Position: 1.3 },
    },
    { name: 'Breakout close', desc: 'Close above prior swing high' },
  ],
  Event: [
    {
      name: 'Earnings buffer',
      desc: 'Score penalised inside this window',
      param:   { key: 'earningsBuffer', label: 'Min days out', unit: 'days', min: 0, max: 30, step: 1 },
      presets: { Intraday: 1, Swing: 7, Position: 14 },
    },
    {
      name: 'FOMC buffer',
      desc: 'Fed meetings add market-wide uncertainty',
      param:   { key: 'fomcBuffer', label: 'Min days out', unit: 'days', min: 0, max: 14, step: 1 },
      presets: { Intraday: 1, Swing: 3, Position: 5 },
    },
    {
      name: 'Ex-dividend buffer',
      desc: 'Options pricing distorts near the div date',
      param:   { key: 'divBuffer', label: 'Min days out', unit: 'days', min: 0, max: 10, step: 1 },
      presets: { Intraday: 1, Swing: 3, Position: 5 },
    },
  ],
  Volatility: [
    {
      name: 'IV Rank',
      desc: '40–70 = premium-selling sweet spot',
      param:   { key: 'ivRankLookback', label: 'Lookback', unit: 'days', min: 30, max: 365, step: 5 },
      presets: { Intraday: 30, Swing: 252, Position: 252 },
    },
    { name: 'IV Percentile', desc: 'Confirms rank using percentile calculation' },
    {
      name: 'Historical vol ratio',
      desc: 'IV / HV > threshold = premium over realised vol',
      param:   { key: 'hvLookback', label: 'HV period', unit: 'days', min: 5, max: 120, step: 5 },
      presets: { Intraday: 10, Swing: 20, Position: 60 },
    },
    { name: 'Term structure', desc: 'Front > back = contango; earns on roll' },
  ],
};

function initCustomParams(): CustomParams {
  const out = {} as CustomParams;
  for (const compKey of Object.keys(METRICS_DEF) as WeightKey[]) {
    out[compKey] = {};
    for (const m of METRICS_DEF[compKey]) {
      if (m.param && m.presets) {
        out[compKey][m.param.key] = m.presets.Swing;
      }
    }
  }
  return out;
}

function WeightsForm() {
  const [horizon,  setHorizon]  = useState<WeightHorizon>('Swing');
  const { customW, customParams, setCustomW, setCustomParams, resetToDefaults } = useSettingsStore();

  const isCustom = horizon === 'Custom';
  const w: WeightMap = isCustom ? customW : WEIGHT_PRESETS[horizon];

  const sum = Object.values(w).reduce((a, b) => a + b, 0);
  const sumTone: 'pass' | 'caution' | 'reject' =
    sum === 100 ? 'pass' : Math.abs(sum - 100) <= 5 ? 'caution' : 'reject';

  function handleWeightChange(key: WeightKey, val: number) {
    setCustomW({ ...customW, [key]: val });
  }

  function handleParamChange(compKey: WeightKey, paramKey: string, val: number) {
    setCustomParams({ ...customParams, [compKey]: { ...customParams[compKey], [paramKey]: val } });
  }

  function getParamValue(compKey: WeightKey, m: MetricDef): number | undefined {
    if (!m.param) return undefined;
    if (isCustom) return customParams[compKey]?.[m.param.key];
    return m.presets?.[horizon as Exclude<WeightHorizon, 'Custom'>];
  }

  return (
    <>
      <SectionIntro
        title="Score weights & parameters"
        blurb="Each horizon has preset indicator parameters (SMA periods, volume lookbacks, event buffers). Switch to Custom to define your own."
      />

      {/* Horizon tab strip */}
      <div className={styles.horizonTabs}>
        {HORIZON_TABS.map((h) => (
          <button
            key={h.key}
            type="button"
            onClick={() => setHorizon(h.key)}
            className={`${styles.horizonTab} ${h.key === horizon ? styles.horizonTabActive : ''}`}
          >
            <Text size={13} weight={500}>{h.label}</Text>
            <Text size={11} tone="secondary">{h.hint}</Text>
          </button>
        ))}
      </div>

      {/* Preset notice or live-sum row */}
      {isCustom ? (
        <div className={styles.sumRow}>
          <Text size={12} tone="secondary">Weight sum (must equal 100)</Text>
          <Data size={16} weight={500} tone={sumTone}>{sum}</Data>
          <button type="button" className={styles.btnInline} onClick={resetToDefaults}>Reset to Swing defaults</button>
        </div>
      ) : (
        <div className={styles.presetNotice}>
          <Text size={12} tone="secondary">
            Preset weights and parameters for <strong>{horizon}</strong> ({HORIZON_TABS.find(h => h.key === horizon)!.hint}) trading — read only.
            Switch to <strong>Custom</strong> to define your own profile.
          </Text>
        </div>
      )}

      {(Object.keys(WEIGHT_DEFAULTS) as WeightKey[]).map((compKey) => (
        <div key={compKey} className={styles.weightBlock}>
          <Row
            label={compKey}
            hint={WEIGHT_HINTS[compKey]}
            defaultValue={isCustom ? `${WEIGHT_DEFAULTS[compKey]}` : undefined}
          >
            <div className={styles.sliderRow}>
              <input
                type="range"
                min={0}
                max={60}
                value={w[compKey]}
                disabled={!isCustom}
                onChange={(e) => handleWeightChange(compKey, Number(e.target.value))}
                className={`${styles.slider} ${!isCustom ? styles.sliderReadOnly : ''}`}
              />
              <Data size={13} weight={500} className={styles.sliderValue}>{w[compKey]}</Data>
            </div>
          </Row>

          <details className={styles.metricsDetails}>
            <summary className={styles.metricsSummary}>Metrics & parameters</summary>
            <ul className={styles.metricsList}>
              {METRICS_DEF[compKey].map((m) => {
                const pVal = getParamValue(compKey, m);
                return (
                  <li key={m.name} className={styles.metricItem}>
                    <div className={styles.metricRow}>
                      <div className={styles.metricText}>
                        <Text size={12} weight={500}>{m.name}</Text>
                        <Text size={11} tone="secondary">{m.desc}</Text>
                      </div>
                      {m.param && pVal !== undefined && (
                        <div className={styles.metricParam}>
                          <Text size={10} tone="dim">{m.param.label}</Text>
                          {isCustom ? (
                            <input
                              type="number"
                              className={styles.paramInput}
                              value={pVal}
                              min={m.param.min}
                              max={m.param.max}
                              step={m.param.step}
                              onChange={(e) => handleParamChange(compKey, m.param!.key, Number(e.target.value))}
                            />
                          ) : (
                            <Data size={12} weight={500}>{pVal}</Data>
                          )}
                          <Text size={10} tone="dim">{m.param.unit}</Text>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </details>
        </div>
      ))}
    </>
  );
}

/* ---------- Alerts ---------- */

function AlertsForm() {
  return (
    <>
      <SectionIntro
        title="Notifications"
        blurb="In-app alerts only. Email / push integrations arrive in Phase 7."
      />
      <Row
        label="Stop-loss breach"
        hint="Fires when an open position closes past your stop."
        defaultValue="On"
      >
        <Toggle defaultOn />
      </Row>
      <Row
        label="Target reached"
        hint="Fires at the first take-profit level."
        defaultValue="On"
      >
        <Toggle defaultOn />
      </Row>
      <Row
        label="Earnings within 3 days"
        hint="Warns before a held name reports."
        defaultValue="On"
      >
        <Toggle defaultOn />
      </Row>
      <Row
        label="Regime flip"
        hint="Dashboard banner always updates; this is an extra toast."
        defaultValue="Off"
      >
        <Toggle />
      </Row>
    </>
  );
}

function Toggle({ defaultOn, onChange }: { defaultOn?: boolean; onChange?: (on: boolean) => void }) {
  const [on, setOn] = useState(defaultOn ?? false);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => {
        const next = !on;
        setOn(next);
        onChange?.(next);
      }}
      className={`${styles.toggle} ${on ? styles.toggleOn : ''}`}
    >
      <span className={styles.toggleDot} />
    </button>
  );
}
