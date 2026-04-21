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

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { ModeToggle } from '@/components/atoms/ModeToggle';
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
        <button type="button" className={styles.btn}>Reset</button>
        <button type="button" className={`${styles.btn} ${styles.btnPrimary}`}>Save changes</button>
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

/* ---------- Broker ---------- */

function BrokerForm() {
  const [broker,  setBroker]  = useState('Interactive Brokers');
  const [account, setAccount] = useState('');
  return (
    <>
      <SectionIntro
        title="Broker connection"
        blurb="Where your trades execute. Paper mode is strongly recommended until you've run the app through a full cycle."
      />
      <Row label="Broker" hint="Interactive Brokers, Tradier, TastyTrade…" defaultValue="Interactive Brokers">
        <select className={styles.input} value={broker} onChange={(e) => setBroker(e.target.value)}>
          <option>Interactive Brokers</option>
          <option>Tradier</option>
          <option>TastyTrade</option>
        </select>
      </Row>
      <Row label="Account ID" hint="Shown on your statements" defaultValue="—">
        <input
          className={styles.input}
          placeholder="U1234567"
          value={account}
          onChange={(e) => setAccount(e.target.value)}
        />
      </Row>
      <Row label="API token" hint="Stored locally. Never transmitted to our servers." defaultValue="—">
        <input className={styles.input} type="password" placeholder="••••••••••••" />
      </Row>
      <Row label="Paper trading" hint="Simulated fills — no real orders" defaultValue="On">
        <Toggle defaultOn />
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

function WeightsForm() {
  const [w, setW] = useState<typeof WEIGHT_DEFAULTS>({ ...WEIGHT_DEFAULTS });
  const sum = Object.values(w).reduce((a, b) => a + b, 0);
  const sumTone: 'pass' | 'caution' | 'reject' =
    sum === 100 ? 'pass' : Math.abs(sum - 100) <= 5 ? 'caution' : 'reject';

  const reset = () => setW({ ...WEIGHT_DEFAULTS });

  return (
    <>
      <SectionIntro
        title="Score weights"
        blurb="Each candidate gets a 0–100 score per component. These weights decide how the components combine into the final rank shown in Step 4."
      />

      <div className={styles.sumRow}>
        <Text size={12} tone="secondary">Live sum (must equal 100)</Text>
        <Data size={16} weight={500} tone={sumTone}>{sum}</Data>
        <button type="button" className={styles.btnInline} onClick={reset}>Reset to defaults</button>
      </div>

      {(Object.keys(WEIGHT_DEFAULTS) as (keyof typeof WEIGHT_DEFAULTS)[]).map((key) => (
        <Row
          key={key}
          label={key}
          hint={WEIGHT_HINTS[key]}
          defaultValue={`${WEIGHT_DEFAULTS[key]}`}
        >
          <div className={styles.sliderRow}>
            <input
              type="range"
              min={0}
              max={60}
              value={w[key]}
              onChange={(e) => setW({ ...w, [key]: Number(e.target.value) })}
              className={styles.slider}
            />
            <Data size={13} weight={500} className={styles.sliderValue}>{w[key]}</Data>
          </div>
        </Row>
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

function Toggle({ defaultOn }: { defaultOn?: boolean }) {
  const [on, setOn] = useState(defaultOn ?? false);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setOn((v) => !v)}
      className={`${styles.toggle} ${on ? styles.toggleOn : ''}`}
    >
      <span className={styles.toggleDot} />
    </button>
  );
}
