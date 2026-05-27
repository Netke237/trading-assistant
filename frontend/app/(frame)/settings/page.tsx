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
import { Title, Text } from '@/components/primitives';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { useSettingsStore, MARKOV_PRESETS, type MarkovPreset, type MarkovConfig } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import type { RiskLimits } from '@/types/domain';
import styles from './page.module.css';

type Section = 'broker' | 'theme' | 'scan' | 'risk' | 'regime' | 'notifications';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'broker',  label: 'Broker',     desc: 'Credentials + paper trade toggle' },
  { key: 'theme',   label: 'Appearance', desc: 'Theme + density' },
  { key: 'scan',    label: 'Scan',       desc: 'Continuous scan + cadence' },
  { key: 'risk',    label: 'Risk',       desc: 'Exposure limits and portfolio value' },
  { key: 'regime',  label: 'Regime',     desc: 'Daily OMM parameters' },
  { key: 'notifications', label: 'Notifications', desc: 'Gmail + Telegram alert delivery' },
];

export default function SettingsPage() {
  const [active, setActive] = useState<Section>('broker');
  // Alert settings moved to /alerts page
  const { resetToDefaults, markov, setMarkov } = useSettingsStore();

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
          {active === 'scan'    && <ScanForm    />}
          {active === 'risk'    && <RiskForm    />}
          {active === 'regime'  && <RegimeForm markov={markov} setMarkov={setMarkov} />}
          {active === 'notifications' && <NotificationForm />}
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

/* ---------- Scan ---------- */

function ScanForm() {
  const {
    shortlistMaxCandidates, setShortlistMaxCandidates,
    maxContractsPerChain, setMaxContractsPerChain,
    maxContractPrice, setMaxContractPrice,
  } = useSettingsStore();
  const [continuous, setContinuous] = useState(false);

  // Local text buffers — let the user type freely; validate on blur
  const [cadenceText,    setCadenceText]    = useState('60');
  const [candidatesText, setCandidatesText] = useState(String(shortlistMaxCandidates));
  const [chainsText,     setChainsText]     = useState(String(maxContractsPerChain));
  const [priceText,      setPriceText]      = useState(String(maxContractPrice));

  // Sync text buffers when the store resets
  useEffect(() => { setCandidatesText(String(shortlistMaxCandidates)); }, [shortlistMaxCandidates]);
  useEffect(() => { setChainsText(String(maxContractsPerChain));        }, [maxContractsPerChain]);
  useEffect(() => { setPriceText(String(maxContractPrice));             }, [maxContractPrice]);

  return (
    <>
      <SectionIntro
        title="Scan behaviour"
        blurb="Continuous scan automatically re-runs the screener on a schedule."
      />
      <Row label="Continuous scan" hint="Auto-run the screener in the background" defaultValue="Off">
        <Toggle
          defaultOn={continuous}
          onChange={(on) => setContinuous(on)}
        />
      </Row>
      <Row label="Cadence (minutes)" hint="How often to re-run — 5 min to 24 h" defaultValue="60">
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={!continuous}
          value={cadenceText}
          onChange={(e) => setCadenceText(e.target.value)}
          onBlur={() => {
            const val = parseInt(cadenceText, 10);
            const clamped = isNaN(val) ? 60 : Math.max(5, Math.min(1440, val));
            setCadenceText(String(clamped));
          }}
        />
      </Row>
      <Row
        label="Shortlist max candidates"
        hint="Cap on how many stocks pass the score gate per scan (1–50)"
        defaultValue="10"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          value={candidatesText}
          onChange={(e) => setCandidatesText(e.target.value)}
          onBlur={() => {
            const val = parseInt(candidatesText, 10);
            const clamped = isNaN(val) ? 10 : Math.max(1, Math.min(50, val));
            setCandidatesText(String(clamped));
            setShortlistMaxCandidates(clamped);
          }}
        />
      </Row>
      <Row
        label="Max contracts per chain"
        hint="Show only the top N highest-scoring contracts per symbol in Step 6 (1–100)"
        defaultValue="10"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          value={chainsText}
          onChange={(e) => setChainsText(e.target.value)}
          onBlur={() => {
            const val = parseInt(chainsText, 10);
            const clamped = isNaN(val) ? 10 : Math.max(1, Math.min(100, val));
            setChainsText(String(clamped));
            setMaxContractsPerChain(clamped);
          }}
        />
      </Row>
      <Row
        label="Max contract price (USD)"
        hint="Hide contracts whose ask price exceeds this threshold — keeps premium cost manageable"
        defaultValue="$500"
      >
        <input
          type="text"
          inputMode="decimal"
          className={styles.input}
          value={priceText}
          onChange={(e) => setPriceText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(priceText);
            const clamped = isNaN(val) ? 500 : Math.max(0.01, Math.min(10000, val));
            setPriceText(String(clamped));
            setMaxContractPrice(clamped);
          }}
        />
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

/* ---------- Risk ---------- */

function RiskForm() {
  const { limits, setLimits } = useRiskStore();
  const [localLimits, setLocalLimits] = useState<RiskLimits>(limits);

  useEffect(() => {
    setLocalLimits(limits);
  }, [limits]);

  function updateLimit<K extends keyof RiskLimits>(key: K, value: RiskLimits[K]) {
    const next = { ...localLimits, [key]: value };
    setLocalLimits(next);
    setLimits(next);
  }

  return (
    <>
      <SectionIntro
        title="Risk limits"
        blurb="Enforced by the app before order submission — the screener blocks trades that breach these thresholds. The backend also has independent defaults in risk_rules.yaml; those are not configurable here and will apply server-side once trade execution is connected."
      />
      <Row
        label="Portfolio value"
        hint="Total account value used as the exposure denominator."
        defaultValue="$50,000"
      >
        <input
          type="number"
          className={styles.input}
          min={1000}
          step={1000}
          value={localLimits.portfolioValue}
          onChange={(e) => updateLimit('portfolioValue', Math.max(1000, Number(e.target.value)))}
        />
      </Row>
      <Row
        label="Max single trade exposure"
        hint="Notional of one trade as % of portfolio."
        defaultValue="5%"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={100}
          step={1}
          value={Math.round(localLimits.maxSingleTradeExposurePct * 100)}
          onChange={(e) => updateLimit('maxSingleTradeExposurePct', Math.max(1, Math.min(100, Number(e.target.value))) / 100)}
        />
      </Row>
      <Row
        label="Max total exposure"
        hint="All open positions combined."
        defaultValue="25%"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={100}
          step={1}
          value={Math.round(localLimits.maxTotalExposurePct * 100)}
          onChange={(e) => updateLimit('maxTotalExposurePct', Math.max(1, Math.min(100, Number(e.target.value))) / 100)}
        />
      </Row>
      <Row
        label="Max concurrent positions"
        hint="Open trades at the same time."
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={50}
          step={1}
          value={localLimits.maxConcurrentPositions}
          onChange={(e) => updateLimit('maxConcurrentPositions', Math.max(1, Math.min(50, Number(e.target.value))))}
        />
      </Row>
      <Row
        label="Max daily recommendations"
        hint="New trade ideas accepted per day."
        defaultValue="5"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={50}
          step={1}
          value={localLimits.maxDailyRecommendations}
          onChange={(e) => updateLimit('maxDailyRecommendations', Math.max(1, Math.min(50, Number(e.target.value))))}
        />
      </Row>
    </>
  );
}

/* ---------- Regime ---------- */

function RegimeForm({
  markov,
  setMarkov,
}: {
  markov: MarkovConfig;
  setMarkov: (cfg: MarkovConfig) => void;
}) {
  const PRESET_LABELS: { key: MarkovPreset; label: string }[] = [
    { key: 'default',      label: 'Default' },
    { key: 'conservative', label: 'Conservative' },
    { key: 'aggressive',   label: 'Aggressive' },
  ];

  return (
    <>
      <SectionIntro
        title="Daily Regime Model (OMM)"
        blurb="Controls the Observable Markov Model that classifies daily SPX bars as Bull / Bear / Choppy. Preset changes update all parameters at once; you can then fine-tune individually. The intraday session model (15-min Gaussian HMM) uses fixed parameters and is not configurable here."
      />
      <Row
        label="Preset"
        hint="Applies a standard parameter bundle."
        defaultValue="Default"
      >
        <div style={{ display: 'flex', gap: '8px' }}>
          {PRESET_LABELS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`${styles.btn} ${markov.preset === key ? styles.btnPrimary : ''}`}
              onClick={() => setMarkov({ preset: key, ...MARKOV_PRESETS[key] })}
            >
              {label}
            </button>
          ))}
        </div>
      </Row>
      <Row
        label="Lookback (bars)"
        hint="Daily trading bars for the rolling return window (5–252). Default: 20 (~1 month)."
        defaultValue="20"
      >
        <input
          type="number"
          className={styles.input}
          min={5}
          max={252}
          step={5}
          value={markov.lookback}
          onChange={(e) => {
            const val = Math.max(5, Math.min(252, Number(e.target.value)));
            setMarkov({ ...markov, lookback: val });
          }}
        />
      </Row>
      <Row
        label="Threshold"
        hint="Return threshold for Bull/Bear classification (0.001–0.1). Default: 0.02 = 2% — bars above +2% are Bull, below −2% are Bear."
        defaultValue="0.02"
      >
        <input
          type="number"
          className={styles.input}
          min={0.001}
          max={0.1}
          step={0.005}
          value={markov.threshold}
          onChange={(e) => {
            const val = Math.max(0.001, Math.min(0.1, Number(e.target.value)));
            setMarkov({ ...markov, threshold: val });
          }}
        />
      </Row>
      <Row
        label="Smoothing (0–1)"
        hint="EMA weight on the return signal before threshold comparison. 0 = raw returns (default), higher = slower state changes."
        defaultValue="0"
      >
        <input
          type="number"
          className={styles.input}
          min={0}
          max={0.99}
          step={0.05}
          value={markov.smoothing}
          onChange={(e) => {
            const val = Math.max(0, Math.min(0.99, Number(e.target.value)));
            setMarkov({ ...markov, smoothing: val });
          }}
        />
      </Row>
    </>
  );
}

function NotificationForm() {
  const [gmailEnabled, setGmailEnabled] = useState(false);
  const [gmailTo, setGmailTo] = useState('');
  const [gmailUser, setGmailUser] = useState('');
  const [gmailPassword, setGmailPassword] = useState('');
  const [telegramEnabled, setTelegramEnabled] = useState(false);
  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [testing, setTesting] = useState<('gmail' | 'telegram') | null>(null);
  const [testResult, setTestResult] = useState('');

  async function sendTest(channel: 'gmail' | 'telegram') {
    setTesting(channel);
    setTestResult('');
    try {
      const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
      const res = await fetch(`${BASE_URL}/alerts/notifications/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel }),
      });
      setTestResult(res.ok ? 'Test sent successfully' : `Failed: ${res.status}`);
    } catch (e: any) {
      setTestResult(`Error: ${e.message}`);
    } finally {
      setTesting(null);
    }
  }

  return (
    <>
      <SectionIntro title="Notifications" blurb="Configure alert delivery. Gmail uses SMTP (App Password), Telegram uses Bot API. Credentials are stored as backend environment variables. Use this panel to test your setup." />

      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
        <Text size={14} weight={600}>Gmail</Text>
        <Row label="Enable Gmail alerts">
          <Toggle defaultOn={gmailEnabled} onChange={setGmailEnabled} />
        </Row>
        {gmailEnabled && (<>
          <Row label="To address" hint="Email that receives alerts">
            <input className={styles.input} placeholder="you@gmail.com" value={gmailTo} onChange={(e) => setGmailTo(e.target.value)} />
          </Row>
          <Row label="SMTP User" hint="Your Gmail address">
            <input className={styles.input} placeholder="you@gmail.com" value={gmailUser} onChange={(e) => setGmailUser(e.target.value)} />
          </Row>
          <Row label="Password" hint="Gmail App Password">
            <input className={styles.input} type="password" placeholder={'\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'} value={gmailPassword} onChange={(e) => setGmailPassword(e.target.value)} />
          </Row>
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('gmail')} disabled={testing === 'gmail'}>
              {testing === 'gmail' ? 'Sending...' : 'Send test email'}
            </button>
            {testResult ? <Text size={12} tone="secondary">{testResult}</Text> : null}
          </Row>
        </>)}
      </div>

      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px' }}>
        <Text size={14} weight={600}>Telegram</Text>
        <Row label="Enable Telegram alerts">
          <Toggle defaultOn={telegramEnabled} onChange={setTelegramEnabled} />
        </Row>
        {telegramEnabled && (<>
          <Row label="Bot token" hint="From @BotFather">
            <input className={styles.input} placeholder="1234567890:ABC..." value={telegramToken} onChange={(e) => setTelegramToken(e.target.value)} />
          </Row>
          <Row label="Chat ID" hint="Your chat or group ID">
            <input className={styles.input} placeholder="987654321" value={telegramChatId} onChange={(e) => setTelegramChatId(e.target.value)} />
          </Row>
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('telegram')} disabled={testing === 'telegram'}>
              {testing === 'telegram' ? 'Sending...' : 'Send test message'}
            </button>
            {testResult ? <Text size={12} tone="secondary">{testResult}</Text> : null}
          </Row>
        </>)}
      </div>
    </>
  );
}
