'use client';

/* ---------- IV thresholds (session override) ----------
 *
 * These edit the ABSOLUTE ceiling (`abs_pass_max`), not the percentile one. On
 * any chain where neither IBKR nor tastytrade supplied a rank -- the default
 * configuration -- the absolute set is the one the gate actually applies
 * (PHASE-A-NULL-IVRANK-2026-09-06). Wiring this knob to the percentile set
 * would give the trader a control that changes nothing they can see.
 *
 * AN OVERRIDE LAYER, NOT AN EDIT OF THE FETCHED RECORD (decision
 * DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29). Apply writes
 * `ivThresholdsStore.overrides`, which fetch() never touches, so an edit
 * survives the re-fetch every page now does on mount. Nothing here quotes a
 * hardcoded number: with no fetched record the inputs are blank and Apply is
 * disabled.
 *
 * WHAT EACH INPUT SHOWS IS WHAT IS APPLIED, or it is marked as not applied.
 *   - Apply writes an override ONLY for an input edited since the last
 *     Apply/Reset (dirty flag), so editing Swing alone never freezes Position
 *     at today's YAML value past a later re-fetch.
 *   - An accepted field's buffer becomes String(v), the value just written.
 *   - A refused field keeps its text, stays dirty and keeps its inline error,
 *     so the next Apply refuses it again. Rules are per field: a valid field
 *     is still applied beside a refused one.
 *   - Reset clears the overrides and rewrites both buffers to the fetched
 *     values explicitly -- a value-keyed effect would not fire when the seed
 *     does not change (type 60, Reset, with no override ever set).
 *   - The sync effects cover store changes from elsewhere (a re-fetch) and
 *     overwrite a field only while it is not dirty.
 */

import { useEffect, useState } from 'react';
import { setDraft, discardDraft, clearDiscarded } from '@/lib/settingsSaveStatus';
import { Text } from '@/components/primitives';
import {
  useIvThresholdsStore, type HorizonIvThresholds, type IvOverrideHorizon, type IvOverrides,
} from '@/lib/ivThresholdsStore';
import type { ThresholdHorizon } from '@/lib/eventThresholdsStore';
import { Row, SectionIntro } from './SettingsRow';
import styles from './page.module.css';

type Fetched = Record<ThresholdHorizon, HorizonIvThresholds> | null;
type PerField<T> = Record<IvOverrideHorizon, T>;

const FIELDS: IvOverrideHorizon[] = ['Swing', 'Position'];

/** The fetched YAML value as input text, or '' when there is none. */
function yamlText(h: IvOverrideHorizon, t: Fetched): string {
  const v = t?.[h].abs_pass_max;
  return v == null ? '' : String(v);
}

/** What the input shows when not being edited: the override, else the YAML. */
function seedText(h: IvOverrideHorizon, t: Fetched, o: IvOverrides): string {
  const ov = o[h];
  return ov !== undefined ? String(ov.abs_pass_max) : yamlText(h, t);
}

/** A number in [1, 100], or null when the text is not one. */
function parsePassMax(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  const v = Number(trimmed);
  return Number.isFinite(v) && v >= 1 && v <= 100 ? v : null;
}

export function IvThresholdsSection() {
  const thresholds = useIvThresholdsStore((s) => s.thresholds);
  const overrides  = useIvThresholdsStore((s) => s.overrides);
  const status     = useIvThresholdsStore((s) => s.status);
  const error      = useIvThresholdsStore((s) => s.error);

  useEffect(() => { void useIvThresholdsStore.getState().fetch(); }, []);

  const swingSeed    = seedText('Swing', thresholds, overrides);
  const positionSeed = seedText('Position', thresholds, overrides);

  const [text,  setText]  = useState<PerField<string>>({ Swing: swingSeed, Position: positionSeed });
  const [dirty, setDirty] = useState<PerField<boolean>>({ Swing: false, Position: false });
  const [refused, setRefused] = useState<PerField<boolean>>({ Swing: false, Position: false });

  useEffect(() => {
    setDraft('iv-thresholds', 'IV thresholds (session)', dirty.Swing || dirty.Position);
  }, [dirty.Swing, dirty.Position]);
  useEffect(() => () => discardDraft('iv-thresholds'), []);

  // Store changes from elsewhere (a re-fetch): follow them while not dirty.
  useEffect(() => {
    if (!dirty.Swing) setText((t) => ({ ...t, Swing: swingSeed }));
  }, [swingSeed, dirty.Swing]);
  useEffect(() => {
    if (!dirty.Position) setText((t) => ({ ...t, Position: positionSeed }));
  }, [positionSeed, dirty.Position]);

  const hasRecord = thresholds !== null;

  function edit(h: IvOverrideHorizon, value: string) {
    setText((t) => ({ ...t, [h]: value }));
    setDirty((d) => ({ ...d, [h]: true }));
  }

  function handleApply() {
    if (!hasRecord) return;
    const { setAbsPassOverride } = useIvThresholdsStore.getState();
    const nextText    = { ...text };
    const nextDirty   = { ...dirty };
    const nextRefused = { ...refused };
    for (const h of FIELDS) {
      if (!dirty[h]) continue;   // untouched: writes nothing
      const v = parsePassMax(text[h]);
      if (v === null) {
        nextRefused[h] = true;   // keeps its text and stays dirty
        continue;
      }
      setAbsPassOverride(h, v);
      nextText[h]    = String(v);
      nextDirty[h]   = false;
      nextRefused[h] = false;
    }
    if (!nextDirty.Swing && !nextDirty.Position) clearDiscarded('iv-thresholds');
    setText(nextText);
    setDirty(nextDirty);
    setRefused(nextRefused);
  }

  function handleReset() {
    useIvThresholdsStore.getState().clearOverrides();
    clearDiscarded('iv-thresholds');
    setText({ Swing: yamlText('Swing', thresholds), Position: yamlText('Position', thresholds) });
    setDirty({ Swing: false, Position: false });
    setRefused({ Swing: false, Position: false });
  }

  const defaultTag = (h: IvOverrideHorizon): string | undefined => {
    const v = thresholds?.[h].abs_pass_max;
    return v == null ? undefined : String(v);
  };

  return (
    <>
      <SectionIntro
        title="IV thresholds"
        blurb="Maximum implied volatility that counts as PASS for each horizon. These edit the ABSOLUTE IV ceiling — the one that applies whenever no IV-rank source (IBKR or tastytrade) is connected, which is the usual case. The values come from scoring_rules.yaml; an edit here is a session-only override on top of them. It changes the Step 5 gate and the Step 7 checklist only, never the scan. Edit scoring_rules.yaml to change them permanently."
      />
      {FIELDS.map((h) => (
        <Row
          key={h}
          label={`${h} — pass max`}
          hint={`Absolute IV at or below this → PASS for ${h} scans (1–100)`}
          defaultValue={defaultTag(h)}
        >
          <input
            type="text"
            inputMode="numeric"
            className={styles.numInput}
            aria-label={`${h} pass max`}
            data-field={h}
            value={text[h]}
            onChange={(e) => edit(h, e.target.value)}
          />
          <Text size={12} tone="secondary">%</Text>
          {refused[h] && (
            <span data-refused={h}>
              <Text size={11} tone="reject">Not applied — enter a number from 1 to 100.</Text>
            </span>
          )}
        </Row>
      ))}
      {!hasRecord && (
        <span data-part="iv-thresholds-status" data-status={status}>
          <Text size={12} tone={status === 'failed' ? 'reject' : 'dim'}>
            {status === 'failed'
              ? `The IV thresholds could not be loaded from scoring_rules.yaml (${error ?? 'unknown error'}). Nothing can be applied.`
              : 'Loading the IV thresholds from scoring_rules.yaml…'}
          </Text>
        </span>
      )}
      <div className={styles.applyRow}>
        <button
          type="button"
          className={styles.btn}
          onClick={handleApply}
          disabled={!hasRecord}
        >
          Apply thresholds
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={handleReset}
        >
          Reset to scoring_rules.yaml
        </button>
      </div>
    </>
  );
}
