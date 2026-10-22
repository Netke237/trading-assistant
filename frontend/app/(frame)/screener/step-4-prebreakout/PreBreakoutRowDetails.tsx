'use client';
/** Evidence presentation selectively adapted from PR #224 head 5e8a2d2.
 * No chart fetch or confidence recalculation: every raw field remains inspectable. */
import type { PreBreakoutResultRow, FibPullbackResultRow, PositionCardData } from '@/types/stockDomain';
import type { ScanSnapshot, ScanMode } from './scanThresholds';
import { fmtThreshold } from './scanThresholds';
import { RawEvidence } from './RawEvidence';
import styles from './page.module.css';

export function fibLabel(label: string | null | undefined): string {
  return label == null || label === '' ? '—' : `${label.replace(/%$/, '')}%`;
}
export function confidenceWeights(row: PreBreakoutResultRow): string {
  const b = row.confidence_breakdown;
  if (!b) return 'Confidence weights unavailable (legacy evidence missing).';
  return Object.entries(b.weights).map(([key, value]) => `${key} ${fmtThreshold(value * 100, 0)}%`).join(', ');
}
const raw = (value: unknown): string => value === undefined ? 'Unavailable (absent)' : value === null ? 'Unavailable (null)' : String(value);
function Fields({values}: {values: object}) {
 const entries=Object.entries(values);
 if (!entries.length) return <p>No fields recorded.</p>;
 return <dl className={styles.evidenceFields}>{entries.map(([key,value])=><div key={key}>
  <dt>{Array.isArray(values)?`Item ${Number(key)+1}`:key.replace(/_/g,' ')}</dt>
  <dd>{value!==null && typeof value==='object'
   ? <details className={styles.evidenceGroup}><summary>{Array.isArray(value)?`${value.length} items`:'View fields'}</summary><Fields values={value}/></details>
   : raw(value)}</dd>
 </div>)}</dl>;
}
function Swing({swing}: {swing: {low:number|null;high:number|null}|null|undefined}) {
 const price=(x:number|null|undefined)=>typeof x==='number' ? `$${x.toFixed(2)}` : 'Unavailable';
 return <p>Swing low {price(swing?.low)} · Swing high {price(swing?.high)}</p>;
}
export function SelectedRowEvidence({row,mode,scanned}: {row: PreBreakoutResultRow|FibPullbackResultRow|PositionCardData; mode: ScanMode; scanned?: ScanSnapshot}) {
 const pre=mode==='prebreakout' ? row as PreBreakoutResultRow : null;
 const fib=mode==='fib' ? row as FibPullbackResultRow : null;
 const p=scanned?.pre;
 return <section role="region" aria-label={`Evidence for ${row.symbol}`} className={styles.evidence}>
 <details key={`${mode}-${row.symbol}`}><summary>{row.symbol} · Setup evidence</summary>
 {pre && <>
 <h3>Why it’s a setup</h3>
 <p>ATR ratio = current ATR(14) / configured average ATR. Range ratio = N-bar high–low / current ATR. Volume ratio = last bar / preceding 20-bar volume average. ATR and range ratios are dimensionless; current_atr and swing_level use price units. fib_dist_pct is percent and fib_level_hit is a percentage label. Proximity is already percent: distance / swing level × 100, using the {row.direction==='Bullish'?'swing high':'swing low'}.</p>
 <p>{p ? `Applied thresholds: ATR below ${fmtThreshold(p.atrCompressionRatio,2)} (${p.atrAvgLookback} bars); range below ${fmtThreshold(p.rangeAtrMult,1)} × ATR (${p.rangeLookbackBars} bars); volume below ${fmtThreshold(p.volCompressionRatio,2)}; proximity within ${fmtThreshold(p.resistanceProximityPct*100,1)}%.` : 'Applied scan thresholds unavailable.'}</p>
 <p>Range is a qualification gate, not a confidence component. Trend filtering also applies. Setup confidence is a returned setup score, not profit probability.</p>
 <Fields values={pre.metrics ?? {}}/>
 <h3>Confidence breakdown</h3>
 {pre.confidence_breakdown ? <>
 <p>{confidenceWeights(pre)}</p>
 {Object.entries(pre.confidence_breakdown.components).map(([key,c])=><p key={key}>{key}: Raw score {raw(c.score)} · Weight {raw(c.weight)} · Contribution {raw(c.contribution)}</p>)}
 <Fields values={pre.confidence_breakdown}/>
 </> : <p>Confidence breakdown unavailable — this result contains no returned evidence.</p>}
 <h3>Optional Fib swing</h3><Swing swing={pre.fib_swing}/>
 </>}
 {fib && <><p>Fib confidence measures proximity only. It does not assert volatility, volume or trend qualification; the endpoint applies EMA filtering separately.</p><p>{scanned?.fib ? `Applied tolerance ${fmtThreshold(scanned.fib.fibTolerancePct*100,1)}%.` : 'Applied scan tolerance unavailable.'}</p><Swing swing={fib.fib_swing}/></>}
 {mode==='pullback' && <p>Stock score and historical signal confidence are separate returned values. Conditional status, qualification and evidence below belong to this Pullback scan.</p>}
 <h3>Complete returned evidence</h3><Fields values={row}/>
 <RawEvidence value={row} label="complete returned evidence" />
 </details></section>;
}
