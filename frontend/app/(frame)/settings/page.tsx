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
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { api, getRiskSettings, saveRiskSettings, getHistoryRetention, saveHistoryRetention, getIngestionSchedule, saveIngestionSchedule, triggerIngestionNow, type IngestionSchedule } from '@/lib/api';
import type { RiskLimits } from '@/types/domain';
import styles from './page.module.css';

type Section = 'theme' | 'scan' | 'brokers' | 'risk' | 'regime' | 'notifications' | 'strategy' | 'data';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'theme',   label: 'Appearance', desc: 'Theme + density' },
  { key: 'scan',    label: 'Scan',       desc: 'Continuous scan + cadence' },
  { key: 'strategy',  label: 'Strategy scan',   desc: 'Signal tolerances + backtest thresholds' },
  { key: 'brokers', label: 'Brokers',   desc: 'Paper trading accounts + live IBKR preparation' },
  { key: 'risk',    label: 'Risk',       desc: 'Exposure limits and portfolio value' },
  { key: 'regime',  label: 'Regime',     desc: 'Daily OMM parameters' },
  { key: 'notifications', label: 'Notifications', desc: 'Gmail + Telegram alert delivery' },
  { key: 'data',    label: 'Data',       desc: 'Nightly OHLCV ingestion schedule' },
];

export default function SettingsPage() {
  const [active, setActive] = useState<Section>('brokers');
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
          {active === 'theme'   && <ThemeForm   />}
          {active === 'scan'    && <ScanForm    />}
          {active === 'brokers' && <BrokersForm />}
          {active === 'risk'    && <RiskForm    />}
          {active === 'regime'  && <RegimeForm markov={markov} setMarkov={setMarkov} />}
          {active === 'notifications' && <NotificationForm />}
          {active === 'strategy' && <StrategyScanForm />}
          {active === 'data'    && <DataForm />}
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
    confidenceGate, setConfidenceGate,
  } = useSettingsStore();
  const [continuous, setContinuous] = useState(false);

  // Local text buffers — let the user type freely; validate on blur
  const [cadenceText,    setCadenceText]    = useState('60');
  const [candidatesText, setCandidatesText] = useState(String(shortlistMaxCandidates));
  const [chainsText,     setChainsText]     = useState(String(maxContractsPerChain));
  const [priceText,      setPriceText]      = useState(String(maxContractPrice));
  const [cautionText,    setCautionText]    = useState(String(confidenceGate.cautionBelow));
  const [rejectText,     setRejectText]     = useState(String(confidenceGate.rejectBelow));
  const [atrText,        setAtrText]        = useState(String(confidenceGate.atrMult));

  // Sync text buffers when the store resets
  useEffect(() => { setCandidatesText(String(shortlistMaxCandidates)); }, [shortlistMaxCandidates]);
  useEffect(() => { setChainsText(String(maxContractsPerChain));        }, [maxContractsPerChain]);
  useEffect(() => { setPriceText(String(maxContractPrice));             }, [maxContractPrice]);
  useEffect(() => { setCautionText(String(confidenceGate.cautionBelow)); }, [confidenceGate.cautionBelow]);
  useEffect(() => { setRejectText(String(confidenceGate.rejectBelow));   }, [confidenceGate.rejectBelow]);
  useEffect(() => { setAtrText(String(confidenceGate.atrMult));          }, [confidenceGate.atrMult]);

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

      <SectionIntro
        title="Confidence gate"
        blurb="Confidence is how often a candidate's entry signal worked in the past (0–100%). The gate can only lower a verdict, never raise it — it protects you from setups with a weak track record."
      />
      <Row label="Enable gate" hint="When off, confidence is shown but never changes the verdict" defaultValue="On">
        <Toggle
          defaultOn={confidenceGate.enabled}
          onChange={(on) => setConfidenceGate({ ...confidenceGate, enabled: on })}
        />
      </Row>
      <Row
        label="Caution below (%)"
        hint="Confidence under this caps the verdict at CAUTION (0–100)"
        defaultValue="50"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={!confidenceGate.enabled}
          value={cautionText}
          onChange={(e) => setCautionText(e.target.value)}
          onBlur={() => {
            const val = parseInt(cautionText, 10);
            const clamped = isNaN(val) ? 50 : Math.max(0, Math.min(100, val));
            setCautionText(String(clamped));
            setConfidenceGate({ ...confidenceGate, cautionBelow: clamped });
          }}
        />
      </Row>
      <Row
        label="Reject below (%)"
        hint="Confidence under this caps the verdict at REJECT (0–100)"
        defaultValue="35"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={!confidenceGate.enabled}
          value={rejectText}
          onChange={(e) => setRejectText(e.target.value)}
          onBlur={() => {
            const val = parseInt(rejectText, 10);
            const clamped = isNaN(val) ? 35 : Math.max(0, Math.min(100, val));
            setRejectText(String(clamped));
            setConfidenceGate({ ...confidenceGate, rejectBelow: clamped });
          }}
        />
      </Row>
      <Row
        label="ATR multiple"
        hint="Backtest win/loss barrier = this × ATR. Higher = bigger move required (0.5–5)"
        defaultValue="1.5"
      >
        <input
          type="text"
          inputMode="decimal"
          className={styles.input}
          value={atrText}
          onChange={(e) => setAtrText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(atrText);
            const clamped = isNaN(val) ? 1.5 : Math.max(0.5, Math.min(5, val));
            setAtrText(String(clamped));
            setConfidenceGate({ ...confidenceGate, atrMult: clamped });
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
  const { premiumStopPct, setPremiumStopPct } = useSettingsStore();
  const [localLimits, setLocalLimits] = useState<RiskLimits>(limits);
  const [localStopPct, setLocalStopPct] = useState(premiumStopPct);
  const [saveResult, setSaveResult] = useState('');

  useEffect(() => {
    setLocalLimits(limits);
  }, [limits]);

  useEffect(() => {
    setLocalStopPct(premiumStopPct);
  }, [premiumStopPct]);

  // Fetch premiumStopPct from backend on mount
  useEffect(() => {
    getRiskSettings()
      .then((s) => {
        setPremiumStopPct(s.premiumStopPct);
        setLocalStopPct(s.premiumStopPct);
      })
      .catch(() => {});
  }, [setPremiumStopPct]);

  function updateLimit<K extends keyof RiskLimits>(key: K, value: RiskLimits[K]) {
    const next = { ...localLimits, [key]: value };
    setLocalLimits(next);
    setLimits(next);
  }

  async function handleSaveRisk() {
    setSaveResult('');
    try {
      await saveRiskSettings({ premiumStopPct: localStopPct });
      setPremiumStopPct(localStopPct);
      setSaveResult('Saved');
    } catch {
      setSaveResult('Save failed');
    } finally {
      setTimeout(() => setSaveResult(''), 2500);
    }
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
      <Row
        label="Premium stop loss"
        hint="Fraction of premium lost before stop fires (0.60 = stop at −60%)"
        defaultValue="0.60"
      >
        <input
          type="number"
          className={styles.input}
          min={0.10}
          max={1.0}
          step={0.05}
          value={localStopPct}
          onChange={(e) => setLocalStopPct(Math.max(0.10, Math.min(1.0, Number(e.target.value))))}
          onBlur={handleSaveRisk}
        />
        {saveResult && <Text size={11} tone="secondary">{saveResult}</Text>}
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
  const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

  // ── History retention ────────────────────────────────────────────────────
  const [retentionYears, setRetentionYears] = useState(10);
  const [retentionText, setRetentionText] = useState('10');
  const [retentionResult, setRetentionResult] = useState('');

  useEffect(() => {
    getHistoryRetention()
      .then((r) => { setRetentionYears(r.historyRetentionYears); setRetentionText(String(r.historyRetentionYears)); })
      .catch(() => {});
  }, []);

  async function handleSaveRetention(years: number) {
    try {
      await saveHistoryRetention({ historyRetentionYears: years });
      setRetentionResult('Saved');
    } catch {
      setRetentionResult('Save failed');
    } finally {
      setTimeout(() => setRetentionResult(''), 2500);
    }
  }

  // ── Gmail / Telegram ────────────────────────────────────────────────────
  const [gmailEnabled, setGmailEnabled] = useState(false);
  const [gmailTo, setGmailTo] = useState('');
  const [gmailUser, setGmailUser] = useState('');
  const [gmailPassword, setGmailPassword] = useState('');
  const [telegramEnabled, setTelegramEnabled] = useState(false);
  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [testing, setTesting] = useState<('gmail' | 'telegram') | null>(null);
  const [testResult, setTestResult] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState('');
  const [loaded, setLoaded] = useState(false);

  // Load saved config on mount
  useEffect(() => {
    fetch(`${BASE_URL}/settings/notifications`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) {
          setGmailEnabled(data.gmail?.enabled ?? false);
          setGmailTo(data.gmail?.to ?? '');
          setGmailUser(data.gmail?.smtp_user ?? '');
          setTelegramEnabled(data.telegram?.enabled ?? false);
          setTelegramChatId(data.telegram?.chat_id ?? '');
        }
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [BASE_URL]);

  async function handleSave() {
    setSaving(true);
    setSaveResult('');
    try {
      const res = await fetch(`${BASE_URL}/settings/notifications`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gmail: {
            enabled: gmailEnabled,
            to: gmailTo,
            smtp_user: gmailUser,
            smtp_password: gmailPassword || null,
          },
          telegram: {
            enabled: telegramEnabled,
            bot_token: telegramToken || null,
            chat_id: telegramChatId,
          },
        }),
      });
      if (res.ok) {
        setSaveResult('Settings saved');
        setGmailPassword('');   // clear password field after save
        setTelegramToken('');
      } else {
        setSaveResult(`Save failed: ${res.status}`);
      }
    } catch (e: unknown) {
      setSaveResult(`Error: ${e instanceof Error ? e.message : 'unknown'}`);
    } finally {
      setSaving(false);
      setTimeout(() => setSaveResult(''), 3000);
    }
  }

  async function sendTest(channel: 'gmail' | 'telegram') {
    setTesting(channel);
    setTestResult('');
    try {
      const body: Record<string, string> = { channel };
      if (channel === 'gmail') {
        if (gmailTo) body.to = gmailTo;
        if (gmailUser) body.smtp_user = gmailUser;
        if (gmailPassword) body.smtp_password = gmailPassword;
      } else {
        if (telegramToken) body.bot_token = telegramToken;
        if (telegramChatId) body.chat_id = telegramChatId;
      }
      const res = await fetch(`${BASE_URL}/alerts/notifications/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setTestResult(res.ok ? 'Test sent successfully' : `Failed: ${res.status}`);
    } catch (e: unknown) {
      setTestResult(`Error: ${e instanceof Error ? e.message : 'unknown'}`);
    } finally {
      setTesting(null);
    }
  }

  return (
    <>
      <SectionIntro title="Notifications" blurb="Configure alert delivery. Gmail uses SMTP (App Password), Telegram uses Bot API. Settings are persisted to the backend config file. Passwords are write-only \u2014 leave blank to keep the existing saved value." />

      <Row
        label="Trade history retention (years)"
        hint="Closed trades older than this are pruned automatically every 15 min. Set to 100 to keep everything forever."
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.input}
          min={1}
          max={100}
          step={1}
          value={retentionText}
          onChange={(e) => setRetentionText(e.target.value)}
          onBlur={() => {
            const val = parseInt(retentionText, 10);
            const clamped = isNaN(val) ? 10 : Math.max(1, Math.min(100, val));
            setRetentionText(String(clamped));
            setRetentionYears(clamped);
            handleSaveRetention(clamped);
          }}
        />
        {retentionResult && <Text size={11} tone="secondary">{retentionResult}</Text>}
      </Row>

      <div key={`gmail-${loaded}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
        <Text size={14} weight={600}>Gmail</Text>
        <Row label="Enable Gmail alerts">
          <Toggle defaultOn={gmailEnabled} onChange={setGmailEnabled} />
        </Row>
        <Row label="To address" hint="Email that receives alerts">
          <input className={styles.input} placeholder="you@gmail.com" value={gmailTo} onChange={(e) => setGmailTo(e.target.value)} />
        </Row>
        <Row label="SMTP User" hint="Your Gmail address">
          <input className={styles.input} placeholder="you@gmail.com" value={gmailUser} onChange={(e) => setGmailUser(e.target.value)} />
        </Row>
        <Row label="Password" hint="Gmail App Password">
          <input
            className={styles.input}
            type="password"
            placeholder="leave blank to keep saved value"
            value={gmailPassword}
            onChange={(e) => setGmailPassword(e.target.value)}
          />
        </Row>
        {gmailEnabled && (
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('gmail')} disabled={testing === 'gmail'}>
              {testing === 'gmail' ? 'Sending...' : 'Send test email'}
            </button>
            {testResult ? <Text size={12} tone="secondary">{testResult}</Text> : null}
          </Row>
        )}
      </div>

      <div key={`telegram-${loaded}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
        <Text size={14} weight={600}>Telegram</Text>
        <Row label="Enable Telegram alerts">
          <Toggle defaultOn={telegramEnabled} onChange={setTelegramEnabled} />
        </Row>
        <Row label="Bot token" hint="From @BotFather">
          <input
            className={styles.input}
            type="password"
            placeholder="leave blank to keep saved value"
            value={telegramToken}
            onChange={(e) => setTelegramToken(e.target.value)}
          />
        </Row>
        <Row label="Chat ID" hint="Your chat or group ID">
          <input className={styles.input} placeholder="987654321" value={telegramChatId} onChange={(e) => setTelegramChatId(e.target.value)} />
        </Row>
        {telegramEnabled && (
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('telegram')} disabled={testing === 'telegram'}>
              {testing === 'telegram' ? 'Sending...' : 'Send test message'}
            </button>
            {testResult ? <Text size={12} tone="secondary">{testResult}</Text> : null}
          </Row>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving...' : 'Save settings'}
        </button>
        {saveResult ? <Text size={12} tone="secondary">{saveResult}</Text> : null}
      </div>
    </>
  );
}

/* ---------- Brokers ---------- */

function BrokersForm() {
  const {
    ibkrPaper, setIbkrPaper,
    tradierPaper, setTradierPaper,
    tradierLive, setTradierLive,
    alpacaPaper, setAlpacaPaper,
    ibkrLive, alpacaLive,
  } = useSettingsStore();

  const [ibkrUrl,      setIbkrUrl]      = useState(ibkrPaper.baseUrl);
  const [ibkrAcct,     setIbkrAcct]     = useState(ibkrPaper.accountId);
  const [tradierTok,   setTradierTok]   = useState(tradierPaper.token);
  const [tradierAcct,  setTradierAcct]  = useState(tradierPaper.accountId);
  const [tradierLiveTok,  setTradierLiveTok]  = useState(tradierLive.token);
  const [tradierLiveAcct, setTradierLiveAcct] = useState(tradierLive.accountId);
  const [alpacaKeyId,  setAlpacaKeyId]  = useState(alpacaPaper.keyId);
  const [alpacaSecret, setAlpacaSecret] = useState(alpacaPaper.secretKey);
  const [saving, setSaving] = useState<string | null>(null);

  // Sync when store resets
  useEffect(() => { setIbkrUrl(ibkrPaper.baseUrl); },         [ibkrPaper.baseUrl]);
  useEffect(() => { setIbkrAcct(ibkrPaper.accountId); },      [ibkrPaper.accountId]);
  useEffect(() => { setTradierTok(tradierPaper.token); },      [tradierPaper.token]);
  useEffect(() => { setTradierAcct(tradierPaper.accountId); }, [tradierPaper.accountId]);
  useEffect(() => { setTradierLiveTok(tradierLive.token); },      [tradierLive.token]);
  useEffect(() => { setTradierLiveAcct(tradierLive.accountId); }, [tradierLive.accountId]);
  useEffect(() => { setAlpacaKeyId(alpacaPaper.keyId); },      [alpacaPaper.keyId]);
  useEffect(() => { setAlpacaSecret(alpacaPaper.secretKey); }, [alpacaPaper.secretKey]);

  async function saveIbkrPaper() {
    setSaving('ibkr');
    setIbkrPaper({ baseUrl: ibkrUrl, accountId: ibkrAcct });
    await api.postCredentials('ibkr_paper', { base_url: ibkrUrl, account_id: ibkrAcct });
    setSaving(null);
  }

  async function saveTradierPaper() {
    setSaving('tradier');
    setTradierPaper({ token: tradierTok, accountId: tradierAcct });
    await api.postCredentials('tradier_paper', { token: tradierTok, account_id: tradierAcct });
    setSaving(null);
  }

  async function saveTradierLive() {
    setSaving('tradierLive');
    setTradierLive({ token: tradierLiveTok, accountId: tradierLiveAcct });
    await api.postCredentials('tradier_live', { token: tradierLiveTok, account_id: tradierLiveAcct });
    setSaving(null);
  }

  async function saveAlpacaPaper() {
    setSaving('alpaca');
    setAlpacaPaper({ keyId: alpacaKeyId, secretKey: alpacaSecret });
    await api.postCredentials('alpaca_paper', { key_id: alpacaKeyId, secret_key: alpacaSecret });
    setSaving(null);
  }

  return (
    <>
      <SectionIntro
        title="IBKR Paper account"
        blurb="Connect to your IBKR paper gateway (runs locally on a separate port from the live gateway). Typical URL: https://localhost:7499/v1/api"
      />
      <Row label="Gateway URL" hint="Paper gateway port is usually 7499" defaultValue="https://localhost:7499/v1/api">
        <input
          className={styles.input}
          value={ibkrUrl}
          onChange={(e) => setIbkrUrl(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your IBKR paper account ID (DU...)" defaultValue="—">
        <input
          className={styles.input}
          value={ibkrAcct}
          onChange={(e) => setIbkrAcct(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveIbkrPaper}
            disabled={saving === 'ibkr'}
          >
            {saving === 'ibkr' ? 'Saving…' : 'Save IBKR Paper'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="Tradier Live"
        blurb="Live Tradier token — used for real-time quotes, option chains, and market data. Takes priority over the paper sandbox token. Get your token at developer.tradier.com."
      />
      <Row label="Live token" hint="Your Tradier live API token" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tradierLiveTok}
          onChange={(e) => setTradierLiveTok(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your Tradier live account ID (e.g. VA-XXXXXXXX)" defaultValue="—">
        <input
          className={styles.input}
          value={tradierLiveAcct}
          onChange={(e) => setTradierLiveAcct(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTradierLive}
            disabled={saving === 'tradierLive'}
          >
            {saving === 'tradierLive' ? 'Saving…' : 'Save Tradier Live'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="Tradier Paper (Sandbox)"
        blurb="Tradier sandbox uses a separate token from your live account. Get one at developer.tradier.com."
      />
      <Row label="Sandbox token" hint="Different from your live Tradier token" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          value={tradierTok}
          onChange={(e) => setTradierTok(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your Tradier sandbox account ID (VA...)" defaultValue="—">
        <input
          className={styles.input}
          value={tradierAcct}
          onChange={(e) => setTradierAcct(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTradierPaper}
            disabled={saving === 'tradier'}
          >
            {saving === 'tradier' ? 'Saving…' : 'Save Tradier Paper'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="Alpaca Paper account"
        blurb="Stock orders via Alpaca Paper trading. Get your paper API keys at app.alpaca.markets under Paper Trading → API Keys."
      />
      <Row label="Key ID" hint="Your Alpaca paper API key ID (PK...)" defaultValue="—">
        <input
          className={styles.input}
          value={alpacaKeyId}
          onChange={(e) => setAlpacaKeyId(e.target.value)}
        />
      </Row>
      <Row label="Secret key" hint="Write-only — leave blank to keep the saved value" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={alpacaSecret}
          onChange={(e) => setAlpacaSecret(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveAlpacaPaper}
            disabled={saving === 'alpaca'}
          >
            {saving === 'alpaca' ? 'Saving…' : 'Save Alpaca Paper'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="IBKR Live (Locked)"
        blurb={ibkrLive.note}
      />
      <Row label="Live trading" hint="Requires explicit activation — not yet enabled" defaultValue="Off">
        <button className={styles.btn} disabled title="Locked until manually activated">
          Activate live IBKR
        </button>
      </Row>

      <SectionIntro
        title="Alpaca Live (Locked)"
        blurb={alpacaLive.note}
      />
      <Row label="Live trading" hint="Requires explicit activation — not yet enabled" defaultValue="Off">
        <button className={styles.btn} disabled title="Locked until manually activated">
          Activate live Alpaca
        </button>
      </Row>
    </>
  );
}

/* ---------- Data ---------- */

function DataForm() {
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState('03:00');
  const [nextRun, setNextRun] = useState<string | null>(null);
  const [saveResult, setSaveResult] = useState('');
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState('');

  useEffect(() => {
    getIngestionSchedule()
      .then((s) => {
        setEnabled(s.enabled);
        setTime(s.time);
        setNextRun(s.next_run);
      })
      .catch(() => {});
  }, []);

  function formatNextRun(iso: string | null): string {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return iso;
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveResult('');
    try {
      const result = await saveIngestionSchedule({ enabled, time });
      setNextRun(result.next_run);
      setSaveResult('Saved');
    } catch {
      setSaveResult('Save failed');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveResult(''), 2500);
    }
  }

  async function handleTriggerNow() {
    setTriggering(true);
    setTriggerResult('');
    try {
      const r = await triggerIngestionNow(['SP500', 'NDX100', 'DOW30'], 6);
      setTriggerResult(`Started — ${r.total} symbols`);
    } catch {
      setTriggerResult('Trigger failed');
    } finally {
      setTriggering(false);
      setTimeout(() => setTriggerResult(''), 4000);
    }
  }

  return (
    <>
      <SectionIntro
        title="Nightly OHLCV ingestion"
        blurb="Automatically refreshes price history for the full SP500 + NDX100 + DOW30 universe at a fixed time each night. Keeps the screener's DB-first reads warm so scans run without live Tradier calls."
      />
      <Row label="Enable nightly schedule" hint="Runs the ingestion job at the configured time every day" defaultValue="Off">
        <Toggle
          defaultOn={enabled}
          onChange={(on) => setEnabled(on)}
        />
      </Row>
      <Row label="Run time (HH:MM)" hint="24-hour local server time, e.g. 03:00" defaultValue="03:00">
        <input
          type="time"
          className={styles.input}
          disabled={!enabled}
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </Row>
      <Row label="Next scheduled run" hint="Calculated after saving">
        <Text size={13} tone="secondary">{formatNextRun(nextRun)}</Text>
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl} style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving…' : 'Save schedule'}
          </button>
          {saveResult && <Text size={12} tone="secondary">{saveResult}</Text>}
        </div>
      </div>

      <SectionIntro
        title="Manual trigger"
        blurb="Run the ingestion job immediately in the background. Useful after first setup or after a long gap. The job runs without blocking the app — check logs for progress."
      />
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl} style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            type="button"
            className={styles.btn}
            onClick={handleTriggerNow}
            disabled={triggering}
          >
            {triggering ? 'Starting…' : 'Run now'}
          </button>
          {triggerResult && <Text size={12} tone="secondary">{triggerResult}</Text>}
        </div>
      </div>
    </>
  );
}

/* ---------- Strategy scan form ---------- */

function StrategyScanForm() {
  const store = useScanParamsStore();

  return (
    <div>
      <SectionIntro
        title="Strategy scan parameters"
        blurb="These values control how strictly each strategy filter and backtest gate applies. Lower tolerances mean fewer matches; higher means more (but potentially noisier) signals."
      />

      <Row
        label="Pullback tolerance"
        hint="How far above the 20-EMA price can be and still count as a pullback"
        defaultValue="4%"
      >
        <input
          type="number"
          className={styles.numInput}
          value={Math.round(store.pullbackTolerancePct * 100 * 10) / 10}
          min={0.5} max={15} step={0.5}
          onChange={(e) =>
            store.setParam('pullbackTolerancePct', Number(e.target.value) / 100)
          }
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>

      <Row
        label="MA crossover lookback"
        hint="How many bars ago the 20/50-SMA cross can have occurred"
        defaultValue="10 bars"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.maCrossoverLookback}
          min={1} max={30} step={1}
          onChange={(e) =>
            store.setParam('maCrossoverLookback', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">bars</Text>
      </Row>

      <Row
        label="Breakout volume multiplier"
        hint="Today's volume must exceed N × the 20-day average"
        defaultValue="1.1×"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.breakoutVolumeMult}
          min={1.0} max={3.0} step={0.05}
          onChange={(e) =>
            store.setParam('breakoutVolumeMult', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">×</Text>
      </Row>

      <Row
        label="Min backtest trades"
        hint="Minimum number of qualifying historical trades for backtest gate to pass"
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.btMinTrades}
          min={1} max={50} step={1}
          onChange={(e) =>
            store.setParam('btMinTrades', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">trades</Text>
      </Row>

      <Row
        label="Min win rate"
        hint="Minimum historical win rate for the backtest gate to pass"
        defaultValue="45%"
      >
        <input
          type="number"
          className={styles.numInput}
          value={Math.round(store.btMinWinRate * 100)}
          min={10} max={80} step={5}
          onChange={(e) =>
            store.setParam('btMinWinRate', Number(e.target.value) / 100)
          }
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>

      <div style={{ marginTop: '16px' }}>
        <button
          type="button"
          className={styles.btn}
          onClick={store.resetToDefaults}
        >
          Reset to defaults
        </button>
      </div>
    </div>
  );
}
