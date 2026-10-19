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

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Title, Text } from '@/components/primitives';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { useSettingsStore, MARKOV_PRESETS, clampGateThresholds, type MarkovPreset, type MarkovConfig, type FundamentalsGate, type AtrMultPair } from '@/lib/settingsStore';
import { Row, SectionIntro } from './SettingsRow';
import { IvThresholdsSection } from './IvThresholdsSection';
import { useRiskStore } from '@/lib/riskStore';
import { useThemeStore, type Density } from '@/lib/theme';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { resolveProfileToScanRequest, scheduleRiskIgnored } from '@/lib/scanScheduleResolve';
import { api, getRiskSettings, saveRiskSettings, getHistoryRetention, saveHistoryRetention, getIngestionSchedule, saveIngestionSchedule, triggerIngestionNow, getEdgarSchedule, saveEdgarSchedule, triggerEdgarPrefetch, getSp500Schedule, saveSp500Schedule, triggerSp500Update, getTuningSchedule, saveTuningSchedule, startTuningJob, getTuningJob, getTuningJobCount, clearTuningJobs, adoptStrategyParams, type IngestionSchedule, type TuningJob, type TuningJobCount, type WfoProposal, type ScanScheduleEntry, type ScanScheduleRun } from '@/lib/api';
import type { RiskLimits } from '@/types/domain';
import { PREMIUM_STOP_MAX_PCT, premiumStopMinWholeCentEntry, premiumStopPctLabel } from '@/lib/premiumStop';
import type { SearchProfile } from '@/types/searchProfile';
import styles from './page.module.css';

type Section = 'theme' | 'scan' | 'brokers' | 'risk' | 'regime' | 'notifications' | 'strategy' | 'data' | 'tuning';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'theme',   label: 'Appearance', desc: 'Theme + density' },
  { key: 'scan',    label: 'Scan',       desc: 'Continuous scan + cadence' },
  { key: 'strategy',  label: 'Strategy scan',   desc: 'Signal tolerances + backtest thresholds' },
  { key: 'brokers', label: 'Brokers',   desc: 'Paper trading accounts + live Tradier market-data token (other Live sections locked)' },
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


/** P2-02 / R3-1 / R3-6 / R4-1 / R4-2 / R5-1 -- what the stored global premium
 *  stop actually does, said under the field.
 *
 *  - 100% or more (only a value stored before the 99% cap): the threshold is
 *    $0.00, which neither alert engine fires on.
 *  - Above 99% but below 100%: it DOES fire (at entry x (1 - pct)), so no
 *    never-fires claim -- only that saving applies the 99% maximum.
 *  - Below 100%: the smallest whole-cent entry at which the stop is NOT
 *    sub-cent, computed from the RAW value (both engines use it until
 *    Settings is saved) THROUGH the sub-cent predicate (STOP-SEMANTICS R2-2):
 *    the old closed form named a limit that was itself sub-cent at 80%, 90%
 *    and 98.75%.
 *  - Shorts are excluded throughout: a short stock's stop fires on a RISE, so
 *    neither the never-fires note nor the sub-cent hint applies to it. */
function PremiumStopSettingNotes({ pct }: { pct: number }) {
  if (!Number.isFinite(pct)) return null;
  if (pct >= 1) {
    return (
      <Text size={11} tone="caution">
        Stored 100% can never fire for long positions and options, in this browser or on the server. Save to apply 99%.
      </Text>
    );
  }
  const limit = premiumStopMinWholeCentEntry(pct);
  return (
    <>
      {pct > PREMIUM_STOP_MAX_PCT && (
        <Text size={11} tone="caution">
          {`Stored ${premiumStopPctLabel(pct)} is above the 99% maximum. Save to apply 99%.`}
        </Text>
      )}
      <Text size={11} tone="dim">
        {`At ${premiumStopPctLabel(pct)}, for long positions and options an entry below $${limit.toFixed(2)} `
          + 'puts the stop threshold below $0.01 — it can never fire.'}
      </Text>
      <Text size={11} tone="dim">
        For short stock positions this is how far the price may RISE above entry.
      </Text>
    </>
  );
}


function AtrPairRow({
  label,
  hint,
  pair,
  onChange,
}: {
  label: string;
  hint: string;
  pair: AtrMultPair;
  onChange: (pair: AtrMultPair) => void;
}) {
  const [targetText, setTargetText] = useState(String(pair.target));
  const [stopText,   setStopText]   = useState(String(pair.stop));

  useEffect(() => { setTargetText(String(pair.target)); }, [pair.target]);
  useEffect(() => { setStopText(String(pair.stop));     }, [pair.stop]);

  return (
    <Row label={label} hint={hint} defaultValue={`${pair.target} target / ${pair.stop} stop`}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
        <input
          type="text"
          inputMode="decimal"
          className={styles.input}
          value={targetText}
          onChange={(e) => setTargetText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(targetText);
            const clamped = isNaN(val) ? pair.target : Math.max(0.5, Math.min(5, val));
            setTargetText(String(clamped));
            onChange({ ...pair, target: clamped });
          }}
        />
        <Text size={11} tone="dim">target /</Text>
        <input
          type="text"
          inputMode="decimal"
          className={styles.input}
          value={stopText}
          onChange={(e) => setStopText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(stopText);
            const clamped = isNaN(val) ? pair.stop : Math.max(0.5, Math.min(5, val));
            setStopText(String(clamped));
            onChange({ ...pair, stop: clamped });
          }}
        />
        <Text size={11} tone="dim">stop</Text>
      </div>
    </Row>
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
  const density = useThemeStore((s) => s.density);
  const setDensity = useThemeStore((s) => s.setDensity);
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
          onChange={(e) => setDensity(e.target.value as Density)}
        >
          <option value="Comfortable">Comfortable</option>
          <option value="Compact">Compact</option>
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
  const lastOptionsScanStatus    = useScanStore((s) => s.lastOptionsScanStatus);
  const lastOptionsScanUpdatedAt = useScanStore((s) => s.lastOptionsScanUpdatedAt);
  const lastStockScanStatus      = useScanStore((s) => s.lastStockScanStatus);
  const lastStockScanUpdatedAt   = useScanStore((s) => s.lastStockScanUpdatedAt);
  const lastStockScanStrategy    = useScanStore((s) => s.lastStockScanStrategy);

  // Local text buffers — let the user type freely; validate on blur
  const [candidatesText, setCandidatesText] = useState(String(shortlistMaxCandidates));
  const [chainsText,     setChainsText]     = useState(String(maxContractsPerChain));
  const [priceText,      setPriceText]      = useState(String(maxContractPrice));
  const [cautionText,    setCautionText]    = useState(String(confidenceGate.cautionBelow));
  const [rejectText,     setRejectText]     = useState(String(confidenceGate.rejectBelow));
  const [gateAdjustNote, setGateAdjustNote] = useState('');
  const [fCautionText,   setFCautionText]   = useState(String(fundamentalsGate?.cautionBelow ?? 45));
  const [fRejectText,    setFRejectText]    = useState(String(fundamentalsGate?.rejectBelow ?? 30));
  const [fDeRejectText,  setFDeRejectText]  = useState(String(fundamentalsGate?.deReject ?? 3.0));

  // Sync text buffers when the store resets
  useEffect(() => { setCandidatesText(String(shortlistMaxCandidates)); }, [shortlistMaxCandidates]);
  useEffect(() => { setChainsText(String(maxContractsPerChain));        }, [maxContractsPerChain]);
  useEffect(() => { setPriceText(String(maxContractPrice));             }, [maxContractPrice]);
  useEffect(() => { setCautionText(String(confidenceGate.cautionBelow)); }, [confidenceGate.cautionBelow]);
  useEffect(() => { setRejectText(String(confidenceGate.rejectBelow));   }, [confidenceGate.rejectBelow]);
  useEffect(() => { setFCautionText(String(fundamentalsGate?.cautionBelow ?? 45)); }, [fundamentalsGate?.cautionBelow]);
  useEffect(() => { setFRejectText(String(fundamentalsGate?.rejectBelow ?? 30));   }, [fundamentalsGate?.rejectBelow]);
  useEffect(() => { setFDeRejectText(String(fundamentalsGate?.deReject ?? 3.0));   }, [fundamentalsGate?.deReject]);

  function formatLastRun(iso: string | null): string {
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

  return (
    <>
      <SectionIntro
        title="Scan behaviour"
        blurb="General scan settings — candidate/contract caps and the confidence/fundamentals gates. Scheduled, unattended scanning lives in the Scheduled scans section below."
      />
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
        hint={`Confidence under this caps the verdict at CAUTION (0–100)${gateAdjustNote === 'caution' ? ' — reject below was adjusted down to stay ≤ this value' : ''}`}
        defaultValue="50"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={!confidenceGate.enabled}
          value={cautionText}
          onChange={(e) => { setCautionText(e.target.value); setGateAdjustNote(''); }}
          onBlur={() => {
            const val = parseInt(cautionText, 10);
            const clamped = isNaN(val) ? 50 : Math.max(0, Math.min(100, val));
            const result = clampGateThresholds('cautionBelow', clamped, confidenceGate.rejectBelow);
            setCautionText(String(result.cautionBelow));
            setRejectText(String(result.rejectBelow));
            setGateAdjustNote(result.rejectBelow !== confidenceGate.rejectBelow ? 'caution' : '');
            setConfidenceGate({ ...confidenceGate, ...result });
          }}
        />
      </Row>
      <Row
        label="Reject below (%)"
        hint={`Confidence under this caps the verdict at REJECT (0–100)${gateAdjustNote === 'reject' ? ' — caution below was adjusted up to stay ≥ this value' : ''}`}
        defaultValue="35"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={!confidenceGate.enabled}
          value={rejectText}
          onChange={(e) => { setRejectText(e.target.value); setGateAdjustNote(''); }}
          onBlur={() => {
            const val = parseInt(rejectText, 10);
            const clamped = isNaN(val) ? 35 : Math.max(0, Math.min(100, val));
            const result = clampGateThresholds('rejectBelow', clamped, confidenceGate.cautionBelow);
            setRejectText(String(result.rejectBelow));
            setCautionText(String(result.cautionBelow));
            setGateAdjustNote(result.cautionBelow !== confidenceGate.cautionBelow ? 'reject' : '');
            setConfidenceGate({ ...confidenceGate, ...result });
          }}
        />
      </Row>
      <AtrPairRow
        label="ATR multiple — Intraday"
        hint="Backtest win/loss barrier for Intraday scans = target/stop × ATR (0.5–5)"
        pair={confidenceGate.atrMult.intraday}
        onChange={(pair) => setConfidenceGate({ ...confidenceGate, atrMult: { ...confidenceGate.atrMult, intraday: pair } })}
      />
      <AtrPairRow
        label="ATR multiple — Swing"
        hint="Backtest win/loss barrier for Swing scans = target/stop × ATR (0.5–5)"
        pair={confidenceGate.atrMult.swing}
        onChange={(pair) => setConfidenceGate({ ...confidenceGate, atrMult: { ...confidenceGate.atrMult, swing: pair } })}
      />
      <AtrPairRow
        label="ATR multiple — Position"
        hint="Backtest win/loss barrier for Position scans (incl. Quarterly/Semi-annual/Annual) = target/stop × ATR (0.5–5)"
        pair={confidenceGate.atrMult.position}
        onChange={(pair) => setConfidenceGate({ ...confidenceGate, atrMult: { ...confidenceGate.atrMult, position: pair } })}
      />
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
      <SpreadsSection />
      <IvThresholdsSection />

      <Row label="Last options scan" hint="Status and time of the most recent manually-triggered options-mode scan">
        <Text size={13} tone="secondary">
          {lastOptionsScanStatus ?? '—'}
          {lastOptionsScanUpdatedAt && ` · ${formatLastRun(lastOptionsScanUpdatedAt)}`}
        </Text>
      </Row>
      <Row label="Last stock scan" hint="Status, time, and strategy of the most recent manually-triggered stock-mode scan">
        <Text size={13} tone="secondary">
          {lastStockScanStatus ?? '—'}
          {lastStockScanUpdatedAt && ` · ${formatLastRun(lastStockScanUpdatedAt)}`}
          {lastStockScanStrategy && ` · ${lastStockScanStrategy}`}
        </Text>
      </Row>

      <OperatorTimezoneSection />
      <ScheduledScanRetentionSection />
      <ScheduledScansSection />
    </>
  );
}

/* ---------- Part 1: operator timezone ---------- */

function OperatorTimezoneSection() {
  const [tz, setTz] = useState('Europe/Berlin');
  const [saveResult, setSaveResult] = useState('');
  const [saving, setSaving] = useState(false);
  const isDirty = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api.getSchedulingTimezone()
      .then((r) => {
        if (!cancelled && !isDirty.current) {
          setTz(r.timezone);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    isDirty.current = true;
    const submittedTz = tz;
    setSaveResult('');
    try {
      const res = await api.putSchedulingTimezone(submittedTz);
      setTz((current) => (current === submittedTz ? res.timezone : current));
      setSaveResult('Saved');
    } catch {
      setSaveResult('Save failed — check the timezone name');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveResult(''), 2500);
    }
  }

  return (
    <>
      <SectionIntro
        title="Operator timezone"
        blurb="Governs jobs that just need a quiet, convenient local hour — nightly OHLCV ingestion, EDGAR fundamentals, S&P 500 liquidity update, strategy tuning, and audit-log rotation. Does NOT affect anything tracking real NYSE hours (e.g. the strategy-watch end-of-day trigger), which always uses America/New_York regardless of this setting. Takes effect immediately, no restart needed."
      />
      <Row label="Timezone" hint="IANA timezone name, e.g. Europe/Berlin" defaultValue="Europe/Berlin">
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            className={styles.input}
            value={tz}
            onChange={(e) => {
              isDirty.current = true;
              setTz(e.target.value);
            }}
          />
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSave}
            disabled={saving}
          >
            Save
          </button>
          {saveResult && <Text size={11} tone="secondary">{saveResult}</Text>}
        </div>
      </Row>
    </>
  );
}

/* ---------- Part 3: scheduled-scan-run retention ---------- */
// Flagged by post-implementation adversarial review: the endpoint
// (getScheduledScanRunRetention/saveScheduledScanRunRetention in api.ts)
// existed with no Settings UI field bound to it — the same class of gap
// the plan called out and fixed for operator timezone above, recurring
// here for a different setting. Mirrors OperatorTimezoneSection's pattern.

function ScheduledScanRetentionSection() {
  const [days, setDays] = useState(90);
  const [saveResult, setSaveResult] = useState('');

  useEffect(() => {
    api.getScheduledScanRunRetention()
      .then((r) => setDays(r.scheduledScanRunRetentionDays))
      .catch(() => {});
  }, []);

  async function handleSave() {
    setSaveResult('');
    try {
      // Re-sync from the response rather than assuming the posted value
      // stuck — the backend clamps to [1, 3650] — flagged by
      // post-implementation adversarial review: without this, typing e.g.
      // 99999 and saving showed "Saved" while the input kept displaying
      // 99999, silently diverging from the 3650 actually persisted.
      const r = await api.saveScheduledScanRunRetention(days);
      setDays(r.scheduledScanRunRetentionDays);
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
        title="Scheduled scan history retention"
        blurb="How long completed scheduled-scan runs (Part 3 below) are kept before being pruned — separate from the trade-history retention setting, since this is operational scan-run history, not the trade-rationale audit trail. Each entry's most recent successful run is always kept regardless of age, as the baseline for its next run's rank/score deltas."
      />
      <Row label="Retention (days)" hint="1-3650" defaultValue="90">
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="number"
            min={1}
            max={3650}
            className={styles.input}
            value={days}
            onChange={(e) => setDays(Math.min(3650, Math.max(1, Number(e.target.value) || 1)))}
          />
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSave}>
            Save
          </button>
          {saveResult && <Text size={11} tone="secondary">{saveResult}</Text>}
        </div>
      </Row>
    </>
  );
}

/* ---------- Part 3: profile-based scan scheduling ---------- */

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

function formatRunTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function ScheduledScansSection() {
  const [entries, setEntries] = useState<ScanScheduleEntry[]>([]);
  const [lastRuns, setLastRuns] = useState<Record<string, ScanScheduleRun | null>>({});
  const [loadError, setLoadError] = useState('');
  const [addError, setAddError] = useState('');
  const profiles = useSearchProfilesStore((s) => s.profiles);
  const staleIds = useSearchProfilesStore((s) => s.staleScheduleEntryIds);

  const refresh = useCallback(async () => {
    try {
      const list = await api.getScanSchedule();
      setEntries(list);
      setLoadError('');
      const pairs = await Promise.all(list.map(async (e) => {
        const runs = await api.getScanScheduleEntryRuns(e.id, 1).catch(() => [] as ScanScheduleRun[]);
        return [e.id, runs[0] ?? null] as const;
      }));
      setLastRuns(Object.fromEntries(pairs));
    } catch {
      setLoadError('Could not reach the backend — schedule entries unavailable right now.');
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function addEntry(mode: 'options' | 'stocks') {
    setAddError('');
    const candidate = profiles.find((p) => p.mode === mode);
    if (!candidate) {
      setAddError(`No saved ${mode} profile yet — save one from Step 3/5 first.`);
      return;
    }
    let resolved;
    try {
      resolved = resolveProfileToScanRequest(candidate);
    } catch (e) {
      setAddError(e instanceof Error ? e.message : 'Could not resolve this profile into a scan request.');
      return;
    }
    try {
      await api.createScanScheduleEntry({
        label: candidate.name,
        mode,
        profile_id: candidate.id,
        profile_name: candidate.name,
        profile_synced_at: new Date().toISOString(),
        resolved_request: resolved,
        pattern: 'fixed_time',
        enabled: true,
        days_of_week: [0, 1, 2, 3, 4],
        fire_time: '09:00',
      });
      void refresh();
    } catch {
      setAddError('Could not create the entry — check the backend is reachable.');
    }
  }

  async function updateEntry(entry: ScanScheduleEntry, patch: Partial<ScanScheduleEntry>) {
    const next = { ...entry, ...patch };
    try {
      await api.updateScanScheduleEntry(entry.id, {
        label: next.label, mode: next.mode, profile_id: next.profile_id,
        profile_name: next.profile_name, profile_synced_at: next.profile_synced_at,
        resolved_request: next.resolved_request, pattern: next.pattern, enabled: next.enabled,
        days_of_week: next.days_of_week, fire_time: next.fire_time,
        cadence_minutes: next.cadence_minutes, window_start_hour: next.window_start_hour,
        window_end_hour: next.window_end_hour,
      });
      void refresh();
    } catch {
      // Leave the list stale rather than silently reverting the UI's optimistic value.
    }
  }

  async function deleteEntry(id: string) {
    try {
      await api.deleteScanScheduleEntry(id);
      void refresh();
    } catch { /* best-effort */ }
  }

  async function runNow(id: string) {
    try {
      await api.runScanScheduleEntryNow(id);
      setTimeout(() => void refresh(), 1500); // give the backend a moment to record the run
    } catch { /* best-effort */ }
  }

  return (
    <>
      <SectionIntro
        title="Scheduled scans"
        blurb="Any number of independently-scheduled scan entries, each pointed at a saved search profile — options and stocks entries never share a cadence/window. 'Fixed time' fires once at a clock time on the selected weekdays; 'Loop' repeats on a cadence within a time window. A schedule entry always reflects its profile's last explicit save — editing it here changes only the schedule, not the profile."
      />
      {loadError && <Row label=""><Text size={12} tone="reject">{loadError}</Text></Row>}
      {entries.length === 0 && !loadError && (
        <Row label="" hint="No scheduled scans yet">
          <Text size={12} tone="secondary">Add one below, pointed at any saved search profile.</Text>
        </Row>
      )}
      {entries.map((entry) => (
        <ScheduleEntryRow
          key={entry.id}
          entry={entry}
          lastRun={lastRuns[entry.id] ?? null}
          stale={staleIds.includes(entry.id)}
          profiles={profiles.filter((p) => p.mode === entry.mode)}
          onUpdate={(patch) => void updateEntry(entry, patch)}
          onDelete={() => void deleteEntry(entry.id)}
          onRunNow={() => void runNow(entry.id)}
        />
      ))}
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl} style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button type="button" className={styles.btn} onClick={() => void addEntry('options')}>
            + Add options entry
          </button>
          <button type="button" className={styles.btn} onClick={() => void addEntry('stocks')}>
            + Add stocks entry
          </button>
          {addError && <Text size={11} tone="reject">{addError}</Text>}
        </div>
      </div>
    </>
  );
}

function ScheduleEntryRow({
  entry, lastRun, stale, profiles, onUpdate, onDelete, onRunNow,
}: {
  entry: ScanScheduleEntry;
  lastRun: ScanScheduleRun | null;
  stale: boolean;
  profiles: SearchProfile[];
  onUpdate: (patch: Partial<ScanScheduleEntry>) => void;
  onDelete: () => void;
  onRunNow: () => void;
}) {
  const [label, setLabel] = useState(entry.label);
  useEffect(() => { setLabel(entry.label); }, [entry.label]);

  return (
    <div className={styles.row} style={{ alignItems: 'flex-start', borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}>
      <div className={styles.rowLabel}>
        <span className={styles.defaultTag}>{entry.mode === 'options' ? 'Options' : 'Stocks'}</span>
        {stale && <Text size={11} tone="caution">May be out of date — last re-sync push failed</Text>}
        {scheduleRiskIgnored(entry) && (
          <Text size={11} tone="caution">Saved with 0% max loss per trade — ignored; this schedule runs at the 1% default (conviction-adjusted). Set it in Settings → Risk, then re-save the profile.</Text>
        )}
      </div>
      <div className={styles.rowControl} style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            className={styles.input}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onBlur={() => { if (label !== entry.label) onUpdate({ label }); }}
          />
          <select
            className={styles.input}
            value={entry.profile_id}
            onChange={(e) => {
              const p = profiles.find((pr) => pr.id === e.target.value);
              if (!p) return;
              try {
                const resolved = resolveProfileToScanRequest(p);
                onUpdate({
                  profile_id: p.id, profile_name: p.name,
                  profile_synced_at: new Date().toISOString(), resolved_request: resolved,
                });
              } catch { /* leave entry pointed at old profile if this one can't resolve yet */ }
            }}
          >
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select
            className={styles.input}
            value={entry.pattern}
            onChange={(e) => onUpdate({
              pattern: e.target.value as 'fixed_time' | 'loop',
              fire_time: e.target.value === 'fixed_time' ? (entry.fire_time ?? '09:00') : null,
              cadence_minutes: e.target.value === 'loop' ? (entry.cadence_minutes ?? 60) : null,
              window_start_hour: e.target.value === 'loop' ? (entry.window_start_hour ?? 9) : null,
              window_end_hour: e.target.value === 'loop' ? (entry.window_end_hour ?? 17) : null,
            })}
          >
            <option value="fixed_time">Fixed time</option>
            <option value="loop">Loop (cadence + window)</option>
          </select>
          <Toggle defaultOn={entry.enabled} onChange={(on) => onUpdate({ enabled: on })} />
          <button type="button" className={styles.btn} onClick={onRunNow}>Run now</button>
          <button type="button" className={styles.btn} onClick={onDelete}>Delete</button>
        </div>

        {entry.pattern === 'fixed_time' ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Text size={11} tone="secondary">Fires at</Text>
            <input
              type="time"
              className={styles.input}
              value={entry.fire_time ?? '09:00'}
              onChange={(e) => onUpdate({ fire_time: e.target.value })}
            />
            <DaysOfWeekPicker days={entry.days_of_week} onChange={(d) => onUpdate({ days_of_week: d })} />
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Text size={11} tone="secondary">Every</Text>
            <input
              type="number" min={5} max={1440} className={styles.input} style={{ width: 70 }}
              value={entry.cadence_minutes ?? 60}
              onChange={(e) => onUpdate({ cadence_minutes: Number(e.target.value) })}
            />
            <Text size={11} tone="secondary">min, between</Text>
            <input
              type="number" min={0} max={23} className={styles.input} style={{ width: 60 }}
              value={entry.window_start_hour ?? 9}
              onChange={(e) => onUpdate({ window_start_hour: Number(e.target.value) })}
            />
            <Text size={11} tone="secondary">and</Text>
            <input
              type="number" min={1} max={24} className={styles.input} style={{ width: 60 }}
              value={entry.window_end_hour ?? 17}
              onChange={(e) => onUpdate({ window_end_hour: Number(e.target.value) })}
            />
            <Text size={11} tone="secondary">(operator timezone)</Text>
            <DaysOfWeekPicker days={entry.days_of_week} onChange={(d) => onUpdate({ days_of_week: d })} />
          </div>
        )}

        <Text size={11} tone="secondary">
          {lastRun
            ? `Last run: ${lastRun.status} · ${formatRunTime(lastRun.fired_at)}` +
              (lastRun.status === 'success'
                ? ` · ${lastRun.candidate_count ?? '—'} candidate(s)`
                : ` · ${lastRun.error ?? 'unknown error'}`)
            : 'Never run yet'}
        </Text>
      </div>
    </div>
  );
}

function DaysOfWeekPicker({ days, onChange }: { days: number[]; onChange: (days: number[]) => void }) {
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {DAY_LABELS.map((label, day) => (
        <label key={day} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={days.includes(day)}
            onChange={(e) => {
              const next = e.target.checked
                ? [...days, day].sort((a, b) => a - b)
                : days.filter((d) => d !== day);
              onChange(next);
            }}
          />
          <Text size={11}>{label}</Text>
        </label>
      ))}
    </div>
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
  const [fGateAdjustNote, setFGateAdjustNote] = useState('');
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
        hint={`Fundamental health score under this caps the verdict at CAUTION (0–100)${intradayHint}${fGateAdjustNote === 'caution' ? ' — reject below was adjusted down to stay ≤ this value' : ''}`}
        defaultValue="45"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={thresholdDisabled}
          value={fCautionText}
          onChange={(e) => { setFCautionText(e.target.value); setFGateAdjustNote(''); }}
          onBlur={() => {
            const val = parseInt(fCautionText, 10);
            const clamped = isNaN(val) ? 45 : Math.max(0, Math.min(100, val));
            const result = clampGateThresholds('cautionBelow', clamped, gate.rejectBelow);
            setFCautionText(String(result.cautionBelow));
            setFRejectText(String(result.rejectBelow));
            setFGateAdjustNote(result.rejectBelow !== gate.rejectBelow ? 'caution' : '');
            setGate({ ...gate, ...result });
          }}
        />
      </Row>
      <Row
        label="Reject below (score)"
        hint={`Fundamental health score under this caps the verdict at REJECT (0–100)${intradayHint}${fGateAdjustNote === 'reject' ? ' — caution below was adjusted up to stay ≥ this value' : ''}`}
        defaultValue="30"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.input}
          disabled={thresholdDisabled}
          value={fRejectText}
          onChange={(e) => { setFRejectText(e.target.value); setFGateAdjustNote(''); }}
          onBlur={() => {
            const val = parseInt(fRejectText, 10);
            const clamped = isNaN(val) ? 30 : Math.max(0, Math.min(100, val));
            const result = clampGateThresholds('rejectBelow', clamped, gate.cautionBelow);
            setFRejectText(String(result.rejectBelow));
            setFCautionText(String(result.cautionBelow));
            setFGateAdjustNote(result.cautionBelow !== gate.cautionBelow ? 'reject' : '');
            setGate({ ...gate, ...result });
          }}
        />
      </Row>
      <Row
        label="D/E reject threshold"
        hint={`Maximum debt-to-equity ratio allowed. Companies with D/E above this value are hard-rejected regardless of fundamental health score. ↑ Higher → more leveraged companies qualify (fewer rejections) · ↓ Lower → only low-debt companies pass (more rejections). Default: 3.0`}
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

/* ---------- Spreads ---------- */

function SpreadsSection() {
  const spreads    = useSettingsStore((s) => s.spreads);
  const setSpreads = useSettingsStore((s) => s.setSpreads);

  // Local text buffers — let the user type freely; validate on blur
  const [deltaText,    setDeltaText]    = useState(String(spreads.shortLegDelta));
  const [widthText,    setWidthText]    = useState(String(spreads.widthPoints));
  const [ivRankText,   setIvRankText]   = useState(String(spreads.ivRankThreshold));
  const [ivAbsText,    setIvAbsText]    = useState(String(spreads.ivAbsThreshold));
  const [creditText,   setCreditText]   = useState(String(spreads.minCredit));
  const [debitText,    setDebitText]    = useState(String(spreads.maxDebitPctOfWidth));

  // Sync text buffers when the store resets
  useEffect(() => { setDeltaText(String(spreads.shortLegDelta));      }, [spreads.shortLegDelta]);
  useEffect(() => { setWidthText(String(spreads.widthPoints));         }, [spreads.widthPoints]);
  useEffect(() => { setIvRankText(String(spreads.ivRankThreshold));    }, [spreads.ivRankThreshold]);
  useEffect(() => { setIvAbsText(String(spreads.ivAbsThreshold));      }, [spreads.ivAbsThreshold]);
  useEffect(() => { setCreditText(String(spreads.minCredit));          }, [spreads.minCredit]);
  useEffect(() => { setDebitText(String(spreads.maxDebitPctOfWidth));  }, [spreads.maxDebitPctOfWidth]);

  return (
    <>
      <SectionIntro
        title="Spreads"
        blurb="Parameters used when screening for vertical spreads (credit and debit). These values are passed to the backend on each scan and override the strategy defaults."
      />
      <Row
        label="Short-leg delta"
        hint="Delta of the short leg — 0 to 1 (e.g. 0.30 = 30Δ)"
        defaultValue="0.30"
      >
        <input
          type="text"
          inputMode="decimal"
          className={styles.numInput}
          value={deltaText}
          onChange={(e) => setDeltaText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(deltaText);
            const clamped = isNaN(val) ? 0.30 : Math.max(0, Math.min(1, val));
            setDeltaText(String(clamped));
            setSpreads({ shortLegDelta: clamped });
          }}
        />
        <Text size={12} tone="secondary">0–1</Text>
      </Row>
      <Row
        label="Width (points)"
        hint="Strike width of the spread in points"
        defaultValue="5"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.numInput}
          value={widthText}
          onChange={(e) => setWidthText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(widthText);
            const clamped = isNaN(val) ? 5 : Math.max(0.5, Math.min(500, val));
            setWidthText(String(clamped));
            setSpreads({ widthPoints: clamped });
          }}
        />
        <Text size={12} tone="secondary">pts</Text>
      </Row>
      <Row
        label="IV rank threshold (percentile)"
        hint="At or above this IV RANK — where today's IV sits in the name's own 52-week range — a bearish spread is presented as a credit (bear call) rather than a debit (bear put). Applies only when IBKR or tastytrade supplied a real rank."
        defaultValue="50"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.numInput}
          value={ivRankText}
          onChange={(e) => setIvRankText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(ivRankText);
            const clamped = isNaN(val) ? 50 : Math.max(0, Math.min(100, val));
            setIvRankText(String(clamped));
            setSpreads({ ivRankThreshold: clamped });
          }}
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>
      <Row
        label="IV threshold (absolute)"
        hint="Same choice, judged on ABSOLUTE implied volatility — which is what most chains carry, since a true rank needs IBKR or tastytrade to answer. Separate from the rank threshold because 50% IV and the 50th percentile are different claims."
        defaultValue="50"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.numInput}
          value={ivAbsText}
          onChange={(e) => setIvAbsText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(ivAbsText);
            const clamped = isNaN(val) ? 50 : Math.max(0, Math.min(100, val));
            setIvAbsText(String(clamped));
            setSpreads({ ivAbsThreshold: clamped });
          }}
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>
      <Row
        label="Min credit"
        hint="Minimum credit received per contract (credit spreads)"
        defaultValue="$0.50"
      >
        <input
          type="text"
          inputMode="decimal"
          className={styles.numInput}
          value={creditText}
          onChange={(e) => setCreditText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(creditText);
            const clamped = isNaN(val) ? 0.50 : Math.max(0, Math.min(50, val));
            setCreditText(String(clamped));
            setSpreads({ minCredit: clamped });
          }}
        />
        <Text size={12} tone="secondary">$</Text>
      </Row>
      <Row
        label="Max debit (% of width)"
        hint="Maximum debit paid as a percentage of the spread width (debit spreads)"
        defaultValue="40"
      >
        <input
          type="text"
          inputMode="numeric"
          className={styles.numInput}
          value={debitText}
          onChange={(e) => setDebitText(e.target.value)}
          onBlur={() => {
            const val = parseFloat(debitText);
            const clamped = isNaN(val) ? 40 : Math.max(0, Math.min(100, val));
            setDebitText(String(clamped));
            setSpreads({ maxDebitPctOfWidth: clamped });
          }}
        />
        <Text size={12} tone="secondary">%</Text>
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

/** Days between an ISO timestamp and now, floored — used for the
 *  Portfolio-value staleness nudge. Returns null when there's nothing to
 *  compare (never edited yet). */
function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  return Math.max(0, Math.floor((Date.now() - then) / 86_400_000));
}

const PORTFOLIO_VALUE_STALE_DAYS = 30;

function RiskForm() {
  const { limits, setLimits, portfolioValueUpdatedAt } = useRiskStore();
  const { premiumStopPct, setPremiumStopPct, targetProfitPct, setTargetProfitPct } = useSettingsStore();
  const [localLimits, setLocalLimits] = useState<RiskLimits>(limits);
  const [localStopPct, setLocalStopPct] = useState(premiumStopPct);
  const [localTargetPct, setLocalTargetPct] = useState(targetProfitPct);
  const [saveResult, setSaveResult] = useState('');

  useEffect(() => {
    setLocalLimits(limits);
  }, [limits]);

  useEffect(() => {
    setLocalStopPct(premiumStopPct);
  }, [premiumStopPct]);

  useEffect(() => {
    setLocalTargetPct(targetProfitPct);
  }, [targetProfitPct]);

  // Fetch risk settings from backend on mount and hydrate all fields
  useEffect(() => {
    getRiskSettings()
      .then((s) => {
        setPremiumStopPct(s.premiumStopPct);
        setLocalStopPct(s.premiumStopPct);
        const nextTargetPct = {
          t1: s.targetT1Pct ?? targetProfitPct.t1,
          t2: s.targetT2Pct ?? targetProfitPct.t2,
          t3: s.targetT3Pct ?? targetProfitPct.t3,
        };
        setTargetProfitPct(nextTargetPct);
        setLocalTargetPct(nextTargetPct);
        const next = {
          ...useRiskStore.getState().limits,
          ...(s.portfolioValue           !== undefined && { portfolioValue:             s.portfolioValue }),
          ...(s.maxSinglePositionPct     !== undefined && { maxSingleTradeExposurePct:  s.maxSinglePositionPct }),
          ...(s.maxLossPerTradePct       !== undefined && { maxLossPerTradePct:         s.maxLossPerTradePct }),
          ...(s.maxTotalExposurePct      !== undefined && { maxTotalExposurePct:        s.maxTotalExposurePct }),
          ...(s.maxSingleStockPositionPct !== undefined && { maxSingleStockPositionPct: s.maxSingleStockPositionPct }),
          ...(s.maxTotalStockExposurePct !== undefined && { maxTotalStockExposurePct:   s.maxTotalStockExposurePct }),
          ...(s.maxConcurrentPositions   !== undefined && { maxConcurrentPositions:     s.maxConcurrentPositions }),
          ...(s.maxDailyRecommendations  !== undefined && { maxDailyRecommendations:    s.maxDailyRecommendations }),
        };
        setLocalLimits(next);
        // Also push the fetched values into the global riskStore, not just the
        // local displayed useState — SendToBrokerDialog enforces against the
        // global store, not this component's local state. Without this, a
        // value that changed on the backend since the last save (e.g. in
        // another session/device) shows correctly on screen but the pre-flight
        // trade-send gate keeps enforcing the stale persisted limit until the
        // user happens to touch a slider.
        useRiskStore.getState().setLimits(next, { isUserEdit: false });
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setPremiumStopPct, setTargetProfitPct]);

  function updateLimit<K extends keyof RiskLimits>(key: K, value: RiskLimits[K]) {
    const next = { ...localLimits, [key]: value };
    setLocalLimits(next);
    setLimits(next);
  }

  async function handleSaveRisk() {
    setSaveResult('');
    // Profit targets must stay non-decreasing (T1 <= T2 <= T3) — the backend
    // rejects an out-of-order ladder with a 422, so clamp locally too rather
    // than let a confusing save failure be the first sign of the problem.
    const orderedTargetPct = {
      t1: localTargetPct.t1,
      t2: Math.max(localTargetPct.t2, localTargetPct.t1),
      t3: Math.max(localTargetPct.t3, localTargetPct.t2, localTargetPct.t1),
    };
    const wasClamped = orderedTargetPct.t2 !== localTargetPct.t2 || orderedTargetPct.t3 !== localTargetPct.t3;
    // P2-02 (R2-9) -- clamped ONCE and used for the POST and both local
    // copies, so a loaded legacy 100% (which the backend now refuses) saves as
    // 99% and the caution below clears after the save.
    const stopPct = Math.min(PREMIUM_STOP_MAX_PCT, localStopPct);
    try {
      await saveRiskSettings({
        premiumStopPct:          stopPct,
        portfolioValue:          localLimits.portfolioValue,
        maxSinglePositionPct:    localLimits.maxSingleTradeExposurePct,
        maxLossPerTradePct:      localLimits.maxLossPerTradePct,
        maxTotalExposurePct:     localLimits.maxTotalExposurePct,
        maxSingleStockPositionPct: localLimits.maxSingleStockPositionPct,
        maxTotalStockExposurePct:  localLimits.maxTotalStockExposurePct,
        maxConcurrentPositions:  localLimits.maxConcurrentPositions,
        maxDailyRecommendations: localLimits.maxDailyRecommendations,
        targetT1Pct: orderedTargetPct.t1,
        targetT2Pct: orderedTargetPct.t2,
        targetT3Pct: orderedTargetPct.t3,
      });
      setPremiumStopPct(stopPct);
      setLocalStopPct(stopPct);
      setTargetProfitPct(orderedTargetPct);
      setLocalTargetPct(orderedTargetPct);
      setSaveResult(wasClamped ? 'Saved (T2/T3 raised to stay ≥ the level before them)' : 'Saved');
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
          onBlur={handleSaveRisk}
        />
      </Row>
      {(() => {
        // Static, manually-edited number — never auto-tracked from realized/
        // open P&L (see docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md
        // Feature C). This is only a nudge to go re-check it, not a gate.
        const days = daysSince(portfolioValueUpdatedAt);
        if (days === null) {
          return (
            <Text size={11} tone="dim">
              Not tracked yet — edit and save to start tracking staleness.
            </Text>
          );
        }
        const stale = days >= PORTFOLIO_VALUE_STALE_DAYS;
        return (
          <Text size={11} tone={stale ? 'caution' : 'dim'}>
            Last updated {days === 0 ? 'today' : `${days} day${days === 1 ? '' : 's'} ago`}
            {stale ? ' — consider confirming it still reflects your account.' : ''}
          </Text>
        );
      })()}
      <Row
        label="Max single trade exposure"
        hint="Options: notional of one trade as % of portfolio. Stocks have their own cap below."
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
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Max loss per trade"
        hint="Caps the premium of one OPTION trade (a long option with no protective order can lose all of it), so the effective option cap is the smaller of this and Max single trade exposure. Also checked against the exit-plan pipeline's final stop, repriced to a contract price; that stop check can be overridden per-position in the Portfolio editor."
        defaultValue="3.75%"
      >
        <input
          type="number"
          className={styles.input}
          min={0}
          max={100}
          step={0.25}
          value={Math.round(localLimits.maxLossPerTradePct * 10000) / 100}
          onChange={(e) => updateLimit('maxLossPerTradePct', Math.max(0, Math.min(100, Number(e.target.value))) / 100)}
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Max total exposure"
        hint="All open OPTION positions combined. Stocks count against their own total below."
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
          onBlur={handleSaveRisk}
        />
      </Row>
      {/* STOCK-SENDS (decision STOCK-SENDS-STOCK-CAPS-2026-09-27): the stock caps,
        * on price x shares as a % of portfolio value. */}
      <Row
        label="Max single stock position"
        hint="Price × shares of one stock position as % of portfolio. A larger stock order is resized to fit."
        defaultValue="20%"
      >
        <input
          type="number"
          aria-label="Max single stock position %"
          className={styles.input}
          min={1}
          max={100}
          step={1}
          value={Math.round(localLimits.maxSingleStockPositionPct * 100)}
          onChange={(e) => updateLimit('maxSingleStockPositionPct', Math.max(1, Math.min(100, Number(e.target.value))) / 100)}
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Max total stock exposure"
        hint="All open STOCK positions combined, as % of portfolio. 100% = no margin."
        defaultValue="100%"
      >
        <input
          type="number"
          aria-label="Max total stock exposure %"
          className={styles.input}
          min={1}
          max={100}
          step={1}
          value={Math.round(localLimits.maxTotalStockExposurePct * 100)}
          onChange={(e) => updateLimit('maxTotalStockExposurePct', Math.max(1, Math.min(100, Number(e.target.value))) / 100)}
          onBlur={handleSaveRisk}
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
          onBlur={handleSaveRisk}
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
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Premium stop loss"
        hint="Fraction of premium lost before stop fires (0.60 = stop at −60%)"
        defaultValue="0.60"
      >
        <div>
          <input
            type="number"
            className={styles.input}
            min={0.10}
            // P2-02 (decision Q7): 99% is the maximum -- the same number the
            // per-position editors use, imported so the two cannot drift.
            max={PREMIUM_STOP_MAX_PCT}
            step={0.01}
            value={localStopPct}
            onChange={(e) => setLocalStopPct(Math.max(0.10, Math.min(PREMIUM_STOP_MAX_PCT, Number(e.target.value))))}
            onBlur={handleSaveRisk}
          />
          <PremiumStopSettingNotes pct={localStopPct} />
        </div>
      </Row>
      <Row
        label="Profit target — T1"
        hint="First profit-target level, as a fraction of premium (0.20 = 20%). Used as the default when estimating a trade's exit plan — overridable per trade."
        defaultValue="0.20"
      >
        <input
          type="number"
          className={styles.input}
          min={0.01}
          max={5.0}
          step={0.05}
          value={localTargetPct.t1}
          onChange={(e) => setLocalTargetPct((prev) => ({ ...prev, t1: Math.max(0.01, Math.min(5.0, Number(e.target.value))) }))}
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Profit target — T2"
        hint="Second profit-target level (0.35 = 35%)."
        defaultValue="0.35"
      >
        <input
          type="number"
          className={styles.input}
          min={0.01}
          max={5.0}
          step={0.05}
          value={localTargetPct.t2}
          onChange={(e) => setLocalTargetPct((prev) => ({ ...prev, t2: Math.max(0.01, Math.min(5.0, Number(e.target.value))) }))}
          onBlur={handleSaveRisk}
        />
      </Row>
      <Row
        label="Profit target — T3"
        hint="Third profit-target level (0.50 = 50%)."
        defaultValue="0.50"
      >
        <input
          type="number"
          className={styles.input}
          min={0.01}
          max={5.0}
          step={0.05}
          value={localTargetPct.t3}
          onChange={(e) => setLocalTargetPct((prev) => ({ ...prev, t3: Math.max(0.01, Math.min(5.0, Number(e.target.value))) }))}
          onBlur={handleSaveRisk}
        />
      </Row>
      {saveResult && <Text size={11} tone="secondary">{saveResult}</Text>}
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
    tastytradePaper, setTastytradePaper, tastytradeLive,
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
  const [tastyClientSecret, setTastyClientSecret] = useState(tastytradePaper.clientSecret);
  const [tastyRefreshToken, setTastyRefreshToken] = useState(tastytradePaper.refreshToken);
  const [tastyAccountId,    setTastyAccountId]    = useState(tastytradePaper.accountId);
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
  useEffect(() => { setTastyClientSecret(tastytradePaper.clientSecret); }, [tastytradePaper.clientSecret]);
  useEffect(() => { setTastyRefreshToken(tastytradePaper.refreshToken); }, [tastytradePaper.refreshToken]);
  useEffect(() => { setTastyAccountId(tastytradePaper.accountId); },       [tastytradePaper.accountId]);

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

  async function saveTastytradePaper() {
    setSaving('tastytrade');
    setTastytradePaper({ clientSecret: tastyClientSecret, refreshToken: tastyRefreshToken, accountId: tastyAccountId });
    await api.postCredentials('tastytrade_paper', {
      client_secret: tastyClientSecret, refresh_token: tastyRefreshToken, account_id: tastyAccountId,
    });
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
        title="Tastytrade Paper account"
        blurb="Real IV Rank/Percentile data and paper stock/option orders via tastytrade. Create an OAuth Grant at Tastytrade → My Profile → API to get a client secret + refresh token."
      />
      <Row label="Client secret" hint="From your tastytrade OAuth application" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tastyClientSecret}
          onChange={(e) => setTastyClientSecret(e.target.value)}
        />
      </Row>
      <Row label="Refresh token" hint="Never expires — generated once via Create Grant" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tastyRefreshToken}
          onChange={(e) => setTastyRefreshToken(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your tastytrade paper account number (5WX...)" defaultValue="—">
        <input
          className={styles.input}
          value={tastyAccountId}
          onChange={(e) => setTastyAccountId(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTastytradePaper}
            disabled={saving === 'tastytrade'}
          >
            {saving === 'tastytrade' ? 'Saving…' : 'Save Tastytrade Paper'}
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

      <SectionIntro
        title="Tastytrade Live (Locked)"
        blurb={tastytradeLive.note}
      />
      <Row label="Live trading" hint="Requires explicit activation — not yet enabled" defaultValue="Off">
        <button className={styles.btn} disabled title="Locked until manually activated">
          Activate live Tastytrade
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
  showDaysOfWeek = false,
}: {
  title: string;
  blurb: string;
  manualBlurb?: string;
  defaultTime: string;
  loadSchedule: () => Promise<IngestionSchedule>;
  saveSchedule: (s: Pick<IngestionSchedule, 'enabled' | 'time'> & { days_of_week?: number[] }) => Promise<IngestionSchedule>;
  onTrigger?: () => Promise<unknown>;
  triggerLabel?: string;
  /** Only strategy tuning uses this — a Saturday-only weekly cadence
   * (Part 0/Part 1, §2a); the other three schedulers (ingestion/EDGAR/
   * S&P 500) stay nightly-every-day and don't need a picker. */
  showDaysOfWeek?: boolean;
}) {
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState(defaultTime);
  const [daysOfWeek, setDaysOfWeek] = useState<number[]>([5]);
  const [nextRun, setNextRun] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState('');
  const [triggering, setTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState('');

  useEffect(() => {
    loadSchedule()
      .then((s) => {
        setEnabled(s.enabled); setTime(s.time); setNextRun(s.next_run);
        const dow = (s as IngestionSchedule & { days_of_week?: number[] }).days_of_week;
        if (Array.isArray(dow)) setDaysOfWeek(dow);
      })
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
      const r = await saveSchedule(showDaysOfWeek ? { enabled, time, days_of_week: daysOfWeek } : { enabled, time });
      setNextRun(r.next_run);
      setSaveResult('Saved');
    } catch { setSaveResult('Save failed'); }
    finally { setSaving(false); setTimeout(() => setSaveResult(''), 2500); }
  }

  async function handleTrigger() {
    setTriggering(true); setTriggerResult('');
    try { await onTrigger?.(); setTriggerResult('Started'); }
    catch { setTriggerResult('Failed — check logs'); }
    finally { setTriggering(false); setTimeout(() => setTriggerResult(''), 4000); }
  }

  return (
    <>
      <SectionIntro title={title} blurb={blurb} />
      <Row label="Enable schedule" hint="Runs at the configured time every day" defaultValue="Off">
        <Toggle defaultOn={enabled} onChange={(on) => setEnabled(on)} />
      </Row>
      <Row label="Run time (HH:MM)" hint="24-hour operator timezone (see Scan → Operator timezone)" defaultValue={defaultTime}>
        <input type="time" className={styles.input} disabled={!enabled} value={time} onChange={(e) => setTime(e.target.value)} />
      </Row>
      {showDaysOfWeek && (
        <Row label="Active days" hint="Which weekdays this runs on" defaultValue="Saturday">
          <DaysOfWeekPicker days={daysOfWeek} onChange={setDaysOfWeek} />
        </Row>
      )}
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
      {onTrigger && (
        <>
          <SectionIntro title="Manual trigger" blurb={manualBlurb ?? ''} />
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
      )}
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

/** STOCKS-HORIZON-T1 H5: these three strategy fields are overrides of the
 *  backend horizon profile, edited here with no horizon or direction in view.
 *  Empty (null) follows the profile; a value overrides it everywhere. */
function OverrideInput({ field, label, unit, scale = 1, decimals = 0, min, max, step }: {
  field: 'pullbackTolerancePct' | 'maCrossoverLookback' | 'breakoutVolumeMult';
  label: string; unit: string; scale?: number; decimals?: number; min: number; max: number; step: number;
}) {
  const value = useScanParamsStore((s) => s[field]);
  const setParam = useScanParamsStore((s) => s.setParam);
  const f = 10 ** decimals;
  return (
    <>
      <input
        type="number"
        className={styles.numInput}
        aria-label={label}
        placeholder="follows horizon profile"
        value={value === null ? '' : Math.round(value * scale * f) / f}
        min={min} max={max} step={step}
        onChange={(e) =>
          setParam(field, e.target.value === '' ? null : Number(e.target.value) / scale)
        }
      />
      <Text size={12} tone="secondary">{unit}</Text>
      {value !== null && (
        <button type="button" className={styles.btn} aria-label={`Clear ${label}`} onClick={() => setParam(field, null)}>
          clear
        </button>
      )}
    </>
  );
}

function StrategyScanForm() {
  const store = useScanParamsStore();

  return (
    <div>
      <SectionIntro
        title="Strategy scan parameters"
        blurb="These values control how strictly each strategy filter and backtest gate applies. Lower tolerances mean fewer matches; higher means more (but potentially noisier) signals."
      />
      <Text size={12} tone="secondary">
        A value here overrides the tuned setting for every horizon and direction.
      </Text>

      <Row
        label="Pullback tolerance"
        hint="How far above the 20-EMA price can be and still count as a pullback"
        defaultValue="horizon profile"
      >
        <OverrideInput field="pullbackTolerancePct" label="Pullback tolerance" unit="%" scale={100} decimals={1}
          min={0.5} max={15} step={0.5} />
      </Row>

      <Row
        label="MA crossover lookback"
        hint="How many bars ago the 20/50-SMA cross can have occurred"
        defaultValue="horizon profile"
      >
        <OverrideInput field="maCrossoverLookback" label="MA crossover lookback" unit="bars"
          min={1} max={30} step={1} />
      </Row>

      <Row
        label="Breakout volume multiplier"
        hint="Today's volume must exceed N × the 20-day average"
        defaultValue="horizon profile"
      >
        <OverrideInput field="breakoutVolumeMult" label="Breakout volume multiplier" unit="×" decimals={2}
          min={1.0} max={3.0} step={0.05} />
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

  const handleAdopt = async (strategy: string, params: Record<string, number | string>, direction: 'Bullish' | 'Bearish') => {
    try {
      await adoptStrategyParams(strategy, params, direction);
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
        blurb="Run walk-forward optimization automatically at a fixed time — Saturday-only by default, since this is compute-heavy and doesn't need daily freshness. The job is skipped if a run is already active."
        defaultTime="05:00"
        loadSchedule={getTuningSchedule}
        saveSchedule={saveTuningSchedule}
        showDaysOfWeek
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
              onAdopt={() => handleAdopt(strategy, prop.proposed, prop.direction)}
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
            {typeof proposal.oos_metrics.n_symbols === 'number' && ` · ${proposal.oos_metrics.n_symbols} symbols`}
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
