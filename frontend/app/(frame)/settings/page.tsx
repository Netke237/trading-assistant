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

import React, { useState, useEffect } from 'react';
import { Title, Text } from '@/components/primitives';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { useSettingsStore, MARKOV_PRESETS, type MarkovPreset, type MarkovConfig, type FundamentalsGate } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { api, getRiskSettings, saveRiskSettings, getHistoryRetention, saveHistoryRetention, getIngestionSchedule, saveIngestionSchedule, triggerIngestionNow, getEdgarSchedule, saveEdgarSchedule, triggerEdgarPrefetch, getSp500Schedule, saveSp500Schedule, triggerSp500Update, getTuningSchedule, saveTuningSchedule, startTuningJob, getTuningJob, getTuningJobCount, clearTuningJobs, adoptStrategyParams, type IngestionSchedule, type TuningJob, type TuningJobCount, type WfoProposal } from '@/lib/api';
import type { RiskLimits } from '@/types/domain';
import styles from './page.module.css';

type Section = 'theme' | 'scan' | 'brokers' | 'risk' | 'regime' | 'notifications' | 'strategy' | 'data' | 'tuning';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'theme',   label: 'Appearance', desc: 'Theme + density' },
  { key: 'scan',    label: 'Scan',       desc: 'Continuous scan + cadence' },
  { key: 'strategy',  label: 'Strategy scan',   desc: 'Signal tolerances + backtest thresholds' },
  { key: 'brokers', label: 'Brokers',   desc: 'Paper trading accounts + live IBKR preparation' },
  { key: 'risk',    label: 'Risk',       desc: 'Exposure limits and portfolio value' },
  { key: 'regime',  label: 'Regime',     desc: 'Daily OMM parameters' },
  { key: 'notifications', label: 'Notifications', desc: 'Gmail + Telegram alert delivery' },
  { key: 'data',    label: 'Data',       desc: 'Nightly OHLCV ingestion schedule' },
  { key: 'tuning',  label: 'Strategy Tuning', desc: 'Walk-forward parameter optimization' },
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
          {active === 'tuning'  && <StrategyTuningForm />}
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
    fundamentalsGate, setFundamentalsGate,
  } = useSettingsStore();
  const horizon = useScanStore((s) => s.context?.horizon);
  const isIntraday = horizon?.toLowerCase().includes('intraday') ?? false;
  const [continuous, setContinuous] = useState(false);

  // Local text buffers — let the user type freely; validate on blur
  const [cadenceText,    setCadenceText]    = useState('60');
  const [candidatesText, setCandidatesText] = useState(String(shortlistMaxCandidates));
  const [chainsText,     setChainsText]     = useState(String(maxContractsPerChain));
  const [priceText,      setPriceText]      = useState(String(maxContractPrice));
  const [cautionText,    setCautionText]    = useState(String(confidenceGate.cautionBelow));
  const [rejectText,     setRejectText]     = useState(String(confidenceGate.rejectBelow));
  const [atrText,        setAtrText]        = useState(String(confidenceGate.atrMult));
  const [fCautionText,   setFCautionText]   = useState(String(fundamentalsGate?.cautionBelow ?? 45));
  const [fRejectText,    setFRejectText]    = useState(String(fundamentalsGate?.rejectBelow ?? 30));
  const [fDeRejectText,  setFDeRejectText]  = useState(String(fundamentalsGate?.deReject ?? 3.0));

  // Sync text buffers when the store resets
  useEffect(() => { setCandidatesText(String(shortlistMaxCandidates)); }, [shortlistMaxCandidates]);
  useEffect(() => { setChainsText(String(maxContractsPerChain));        }, [maxContractsPerChain]);
  useEffect(() => { setPriceText(String(maxContractPrice));             }, [maxContractPrice]);
  useEffect(() => { setCautionText(String(confidenceGate.cautionBelow)); }, [confidenceGate.cautionBelow]);
  useEffect(() => { setRejectText(String(confidenceGate.rejectBelow));   }, [confidenceGate.rejectBelow]);
  useEffect(() => { setAtrText(String(confidenceGate.atrMult));          }, [confidenceGate.atrMult]);
  useEffect(() => { setFCautionText(String(fundamentalsGate?.cautionBelow ?? 45)); }, [fundamentalsGate?.cautionBelow]);
  useEffect(() => { setFRejectText(String(fundamentalsGate?.rejectBelow ?? 30));   }, [fundamentalsGate?.rejectBelow]);
  useEffect(() => { setFDeRejectText(String(fundamentalsGate?.deReject ?? 3.0));   }, [fundamentalsGate?.deReject]);

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

      <FundamentalsGateSection
        gate={fundamentalsGate}
        setGate={setFundamentalsGate}
        fCautionText={fCautionText}
        setFCautionText={setFCautionText}
        fRejectText={fRejectText}
        setFRejectText={setFRejectText}
        fDeRejectText={fDeRejectText}
        setFDeRejectText={setFDeRejectText}
        isIntraday={isIntraday}
      />
    </>
  );
}

function FundamentalsGateSection({
  gate,
  setGate,
  fCautionText, setFCautionText,
  fRejectText,  setFRejectText,
  fDeRejectText, setFDeRejectText,
  isIntraday,
}: {
  gate: FundamentalsGate;
  setGate: (g: FundamentalsGate) => void;
  fCautionText: string;  setFCautionText: (v: string) => void;
  fRejectText: string;   setFRejectText:  (v: string) => void;
  fDeRejectText: string; setFDeRejectText: (v: string) => void;
  isIntraday: boolean;
}) {
  const thresholdDisabled = !gate?.enabled || isIntraday;
  const intradayHint = isIntraday ? ' — no-op for the active Intraday horizon' : '';
  return (
    <>
      <SectionIntro
        title="Fundamentals gate"
        blurb="Scores fundamentals (balance sheet health, growth, risk) on a 0–100 scale. Applies to Swing and Position horizons only — no-op for Intraday scans. The gate can lower a verdict but never raise it."
      />
      <Row label="Enable gate" hint="When off, fundamentals are shown but never change the verdict" defaultValue="On">
        <Toggle
          defaultOn={gate?.enabled ?? true}
          onChange={(on) => setGate({ ...gate, enabled: on })}
        />
      </Row>
      <Row
        label="Caution below (score)"
        hint={`Fundamental health score under this caps the verdict at CAUTION (0–100)${intradayHint}`}
        defaultValue="45"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={thresholdDisabled}
          value={fCautionText}
          onChange={(e) => setFCautionText(e.target.value)}
          onBlur={() => {
            const val = parseInt(fCautionText, 10);
            const clamped = isNaN(val) ? 45 : Math.max(0, Math.min(100, val));
            setFCautionText(String(clamped));
            setGate({ ...gate, cautionBelow: clamped });
          }}
        />
      </Row>
      <Row
        label="Reject below (score)"
        hint={`Fundamental health score under this caps the verdict at REJECT (0–100)${intradayHint}`}
        defaultValue="30"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={thresholdDisabled}
          value={fRejectText}
          onChange={(e) => setFRejectText(e.target.value)}
          onBlur={() => {
            const val = parseInt(fRejectText, 10);
            const clamped = isNaN(val) ? 30 : Math.max(0, Math.min(100, val));
            setFRejectText(String(clamped));
            setGate({ ...gate, rejectBelow: clamped });
          }}
        />
      </Row>
      <Row
        label="De-reject threshold"
        hint={`Minimum R:R ratio that can override a fundamental REJECT verdict (0.5–10)${intradayHint}`}
        defaultValue="3.0"
      >
        <input
          type="text"
          inputMode="decimal"
          className={styles.input}
          disabled={thresholdDisabled}
          value={fDeRejectText}
          onChange={(e) => setFDeRejectText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(fDeRejectText);
            const clamped = isNaN(val) ? 3.0 : Math.max(0.5, Math.min(10, val));
            setFDeRejectText(String(clamped));
            setGate({ ...gate, deReject: clamped });
          }}
        />
      </Row>
    </>
  );
}

function Toggle({ defaultOn, onChange }: { defaultOn?: boolean; onChange?: (on: boolean) => void }) {
  const [on, setOn] = useState(defaultOn ?? false);
  // Sync with external state changes (e.g., Reset button updates the store).
  useEffect(() => { setOn(defaultOn ?? false); }, [defaultOn]);
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

      <EdgarScheduleSection />
      <Sp500ScheduleSection />
    </>
  );
}

/* ---------- Reusable schedule section ---------- */

function ScheduleSection({
  title,
  blurb,
  manualBlurb,
  defaultTime,
  loadSchedule,
  saveSchedule,
  onTrigger,
  triggerLabel = 'Run now',
}: {
  title: string;
  blurb: string;
  manualBlurb: string;
  defaultTime: string;
  loadSchedule: () => Promise<IngestionSchedule>;
  saveSchedule: (s: Pick<IngestionSchedule, 'enabled' | 'time'>) => Promise<IngestionSchedule>;
  onTrigger: () => Promise<unknown>;
  triggerLabel?: string;
}) {
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState(defaultTime);
  const [nextRun, setNextRun] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState('');
  const [triggering, setTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState('');

  useEffect(() => {
    loadSchedule()
      .then((s) => { setEnabled(s.enabled); setTime(s.time); setNextRun(s.next_run); })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function formatNextRun(iso: string | null) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return iso; }
  }

  async function handleSave() {
    setSaving(true); setSaveResult('');
    try {
      const r = await saveSchedule({ enabled, time });
      setNextRun(r.next_run);
      setSaveResult('Saved');
    } catch { setSaveResult('Save failed'); }
    finally { setSaving(false); setTimeout(() => setSaveResult(''), 2500); }
  }

  async function handleTrigger() {
    setTriggering(true); setTriggerResult('');
    try { await onTrigger(); setTriggerResult('Started'); }
    catch { setTriggerResult('Failed — check logs'); }
    finally { setTriggering(false); setTimeout(() => setTriggerResult(''), 4000); }
  }

  return (
    <>
      <SectionIntro title={title} blurb={blurb} />
      <Row label="Enable schedule" hint="Runs at the configured time every day" defaultValue="Off">
        <Toggle defaultOn={enabled} onChange={(on) => setEnabled(on)} />
      </Row>
      <Row label="Run time (HH:MM)" hint="24-hour local server time" defaultValue={defaultTime}>
        <input type="time" className={styles.input} disabled={!enabled} value={time} onChange={(e) => setTime(e.target.value)} />
      </Row>
      <Row label="Next scheduled run" hint="Calculated after saving">
        <Text size={13} tone="secondary">{formatNextRun(nextRun)}</Text>
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl} style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save schedule'}
          </button>
          {saveResult && <Text size={12} tone="secondary">{saveResult}</Text>}
        </div>
      </div>
      <SectionIntro title="Manual trigger" blurb={manualBlurb} />
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl} style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button type="button" className={styles.btn} onClick={handleTrigger} disabled={triggering}>
            {triggering ? 'Starting…' : triggerLabel}
          </button>
          {triggerResult && <Text size={12} tone="secondary">{triggerResult}</Text>}
        </div>
      </div>
    </>
  );
}

function EdgarScheduleSection() {
  return (
    <ScheduleSection
      title="EDGAR fundamentals"
      blurb="Refreshes SEC fundamental data (revenue, margins, EPS, debt) for the full SP500 + NDX100 + DOW30 universe. Runs after OHLCV so the DB is warm before market open."
      manualBlurb="Fetch fundamentals immediately in the background. Takes several minutes for the full universe — check logs for progress."
      defaultTime="04:00"
      loadSchedule={getEdgarSchedule}
      saveSchedule={saveEdgarSchedule}
      onTrigger={triggerEdgarPrefetch}
      triggerLabel="Run now"
    />
  );
}

function Sp500ScheduleSection() {
  return (
    <ScheduleSection
      title="S&P 500 list update"
      blurb="Re-fetches 20-day average dollar volume for every symbol in sp500.csv and updates the liquidity column. Run after market close so the day's data is included."
      manualBlurb="Run the S&P 500 liquidity update immediately. Downloads ~500 symbols from Yahoo Finance — takes 1–3 minutes."
      defaultTime="16:30"
      loadSchedule={getSp500Schedule}
      saveSchedule={saveSp500Schedule}
      onTrigger={triggerSp500Update}
      triggerLabel="Run now"
    />
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

/* ---------- Strategy Tuning ---------- */

const SESSION_JOB_KEY = 'bamendjou:wfo:jobId';
const SESSION_ADOPTED_KEY = 'bamendjou:wfo:adopted';
const MAX_POLL_COUNT = 450; // 15 minutes at 2s intervals

function StrategyTuningForm() {
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [job, setJob] = React.useState<TuningJob | null>(null);
  const [polling, setPolling] = React.useState(false);
  const [adoptedStrategies, setAdoptedStrategies] = React.useState<Set<string>>(new Set());

  const [error, setError] = React.useState<string | null>(null);
  const pollCountRef = React.useRef(0);
  const [jobCount, setJobCount] = React.useState<TuningJobCount | null>(null);
  const [clearing, setClearing] = React.useState(false);

  const refreshCount = React.useCallback(() => {
    getTuningJobCount().then(setJobCount).catch(() => {});
  }, []);

  React.useEffect(() => { refreshCount(); }, [refreshCount]);

  // Hydrate from sessionStorage after mount (avoids SSR/hydration mismatch) and
  // reconnect to any in-flight job in one effect so the stored jobId is available
  // synchronously for the getTuningJob call without waiting for a re-render.
  React.useEffect(() => {
    try {
      const raw = sessionStorage.getItem(SESSION_ADOPTED_KEY);
      if (raw) setAdoptedStrategies(new Set<string>(JSON.parse(raw) as string[]));
    } catch {
      // Corrupt sessionStorage — start fresh.
    }

    const stored = sessionStorage.getItem(SESSION_JOB_KEY);
    if (!stored) return;
    setJobId(stored);
    getTuningJob(stored)
      .then(j => {
        setJob(j);
        if (j.status === 'running') setPolling(true);
      })
      .catch(() => {
        // Backend was restarted — job is gone, clear the stale id.
        sessionStorage.removeItem(SESSION_JOB_KEY);
        setJobId(null);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = async () => {
    setError(null);
    try {
      const { job_id } = await startTuningJob();
      sessionStorage.setItem(SESSION_JOB_KEY, job_id);
      setJobId(job_id);
      setJob(null);
      setPolling(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start tuning job');
    }
  };

  const handleClearHistory = async () => {
    setClearing(true);
    try {
      await clearTuningJobs();
      if (job && job.status !== 'running') {
        setJob(null);
        setJobId(null);
        sessionStorage.removeItem(SESSION_JOB_KEY);
      }
      refreshCount();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to clear history');
    } finally {
      setClearing(false);
    }
  };

  React.useEffect(() => {
    if (!polling || !jobId) return;
    pollCountRef.current = 0;
    const interval = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current >= MAX_POLL_COUNT) {
        clearInterval(interval);
        setPolling(false);
        setError('Optimization timed out after 15 minutes — job may still be running. Try refreshing to reconnect.');
        return;
      }
      try {
        const j = await getTuningJob(jobId);
        setJob(j);
        if (j.status !== 'running') { setPolling(false); refreshCount(); }
      } catch {
        setPolling(false);
        setError('Lost connection to job — try refreshing.');
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, jobId]);

  const handleAdopt = async (strategy: string, params: Record<string, number | string>) => {
    try {
      await adoptStrategyParams(strategy, params);
      setAdoptedStrategies(prev => {
        const next = new Set(prev).add(strategy);
        sessionStorage.setItem(SESSION_ADOPTED_KEY, JSON.stringify([...next]));
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to adopt params');
    }
  };

  const proposals: [string, WfoProposal][] = job?.proposals ? Object.entries(job.proposals) : [];

  return (
    <div>
      <ScheduleSection
        title="Automatic tuning schedule"
        blurb="Run walk-forward optimization automatically at a fixed time each day. The job is skipped if a run is already active."
        manualBlurb="Trigger a walk-forward optimization run immediately. The job runs in the background — results appear below when complete."
        defaultTime="02:00"
        loadSchedule={getTuningSchedule}
        saveSchedule={saveTuningSchedule}
        onTrigger={async () => { await startTuningJob(); }}
        triggerLabel="Run now"
      />

      <SectionIntro
        title="Strategy Tuning"
        blurb="Run a walk-forward optimization to find robust parameter sets for each strategy. Review in-sample vs out-of-sample results, then adopt the proposed parameters."
      />

      <Row
        label="Optimization history"
        hint="Completed and failed runs stay in memory until cleared or until the backend restarts."
      >
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', marginRight: 12 }}>
          {jobCount
            ? `${jobCount.completed} completed · ${jobCount.failed} failed · ${jobCount.running} running`
            : '—'}
        </span>
        <button
          type="button"
          className={styles.btn}
          onClick={handleClearHistory}
          disabled={clearing || (jobCount !== null && jobCount.completed === 0 && jobCount.failed === 0)}
        >
          {clearing ? 'Clearing…' : 'Clear history'}
        </button>
      </Row>

      <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
        <button
          onClick={handleRun}
          disabled={polling}
          style={{
            padding: '8px 20px',
            background: 'var(--accent)',
            color: 'var(--bg-base)',
            border: 'none',
            borderRadius: 6,
            cursor: polling ? 'not-allowed' : 'pointer',
            opacity: polling ? 0.6 : 1,
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {polling ? 'Running…' : 'Run Optimization'}
        </button>
        {job && job.status === 'running' && job.total > 0 && (
          <span style={{ color: 'var(--text-secondary)', fontSize: 13, alignSelf: 'center' }}>
            {job.done} / {job.total} strategies
          </span>
        )}
        {job && job.status === 'completed' && (
          <span style={{ color: 'var(--pass)', fontSize: 13, alignSelf: 'center' }}>
            Done — {proposals.length} proposals ready
          </span>
        )}
        {job && job.status === 'failed' && (
          <span style={{ color: 'var(--reject)', fontSize: 13, alignSelf: 'center' }}>
            Failed: {job.error}
          </span>
        )}
      </div>

      {error && (
        <div style={{ color: 'var(--reject)', fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {proposals.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {proposals.map(([strategy, prop]) => (
            <ProposalCard
              key={strategy}
              strategy={strategy}
              proposal={prop}
              adopted={adoptedStrategies.has(strategy)}
              onAdopt={() => handleAdopt(strategy, prop.proposed)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ProposalCardProps {
  strategy: string;
  proposal: WfoProposal;
  adopted: boolean;
  onAdopt: () => void;
}

function ProposalCard({ strategy, proposal, adopted, onAdopt }: ProposalCardProps) {
  const [expanded, setExpanded] = React.useState(false);
  const deg = proposal.verdict.degradation_pct;
  const degColor = deg > 0.6 ? 'var(--reject)' : deg > 0.3 ? 'var(--caution)' : 'var(--pass)';

  return (
    <div style={{
      border: '1px solid var(--border-subtle)',
      borderRadius: 8,
      padding: 16,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', marginBottom: 4 }}>
            {strategy}
          </div>
          <div style={{
            fontSize: 12,
            color: proposal.eligible ? 'var(--pass)' : 'var(--reject)',
          }}>
            {proposal.eligible ? 'Eligible' : 'Not eligible'} · Consistency: {(proposal.consistency * 100).toFixed(0)}% positive folds
          </div>
        </div>
        <button
          onClick={onAdopt}
          disabled={adopted || !proposal.eligible}
          style={{
            padding: '6px 14px',
            background: adopted ? 'transparent' : 'var(--accent)',
            color: adopted ? 'var(--text-secondary)' : 'var(--bg-base)',
            border: adopted ? '1px solid var(--border-subtle)' : 'none',
            borderRadius: 6,
            cursor: adopted || !proposal.eligible ? 'not-allowed' : 'pointer',
            opacity: !proposal.eligible && !adopted ? 0.5 : 1,
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          {adopted ? 'Adopted' : 'Adopt'}
        </button>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12, fontStyle: 'italic' }}>
        {proposal.recommendation}
      </div>

      {/* Verdict row */}
      <div style={{ display: 'flex', gap: 24, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>In-sample return</div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {proposal.verdict.in_sample_return.toFixed(1)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>Walk-forward return</div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {proposal.verdict.walk_forward_return.toFixed(1)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>Curve-fit degradation</div>
          <div style={{ fontSize: 13, fontWeight: 500, color: degColor, fontFamily: 'var(--font-mono)' }}>
            {(proposal.verdict.degradation_pct * 100).toFixed(0)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>OOS Sharpe</div>
          <div style={{ fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-mono)', color: proposal.oos_metrics.sharpe > 0.5 ? 'var(--pass)' : 'var(--text-secondary)' }}>
            {proposal.oos_metrics.sharpe.toFixed(2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>OOS trades</div>
          <div style={{ fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
            {proposal.oos_metrics.n_trades}
          </div>
        </div>
      </div>

      {/* Proposed params */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 6 }}>Proposed parameters</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {Object.entries(proposal.proposed).map(([k, v]) => (
            <div key={k} style={{
              background: 'color-mix(in srgb, var(--accent) 8%, var(--bg-surface))',
              border: '1px solid var(--border-subtle)',
              borderRadius: 4,
              padding: '3px 8px',
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
            }}>
              {k}: {String(v)}
            </div>
          ))}
        </div>
      </div>

      {/* Fold winners accordion */}
      {proposal.fold_winners.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button
            onClick={() => setExpanded(e => !e)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              fontSize: 12,
              padding: 0,
            }}
          >
            {expanded ? '▾' : '▸'} {proposal.fold_winners.length} fold winners
          </button>
          {expanded && (
            <div style={{ marginTop: 8, overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text-dim)', fontWeight: 400, borderBottom: '1px solid var(--border-subtle)' }}>Fold</th>
                    {Object.keys(proposal.fold_winners[0] || {}).map(k => (
                      <th key={k} style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text-dim)', fontWeight: 400, borderBottom: '1px solid var(--border-subtle)' }}>{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {proposal.fold_winners.map((w, i) => (
                    <tr key={i}>
                      <td style={{ padding: '4px 8px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{i + 1}</td>
                      {Object.values(w).map((v, j) => (
                        <td key={j} style={{ padding: '4px 8px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{String(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
