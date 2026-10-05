import type { TradeCardData } from '@/types/domain';
import { scoreEvidenceFor } from '@/lib/tradeCardOverride';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import styles from './TradeCardQualification.module.css';

export interface QualificationPresentation {
  card: TradeCardData;
  kind: 'stock' | 'contract';
}

/** Preserve captured units and precision; never evaluate rules or sum contributions. */
function Fields({ values }: { values: object }) {
  return <dl className={styles.fields}>{Object.entries(values).map(([key, value]) => (
    <div key={key}>
      <dt>{key.replace(/_/g, ' ')}</dt>
      <dd>{value === null || value === undefined ? 'Not supplied' : typeof value === 'object'
        ? Object.keys(value).length === 0 ? 'None captured' : <Fields values={value} /> : String(value)}</dd>
    </div>
  ))}</dl>;
}

export function TradeCardQualification({ card, kind }: QualificationPresentation) {
  const evidence = scoreEvidenceFor(card)[kind];
  if (evidence.state === 'not_captured') {
    return <Text size={12} tone="dim">{evidence.message}</Text>;
  }
  const exp = evidence.explanation;
  const stock = kind === 'stock' ? scoreEvidenceFor(card).stock : null;
  const contract = kind === 'contract' ? scoreEvidenceFor(card).contract : null;
  return <section className={styles.evidence} aria-label={`${kind} captured score evidence`}>
    <Text size={12}>Captured {kind === 'stock' ? card.symbol : card.contract} evidence · {exp.evaluated_at}</Text>
    <Text size={12}>Composite thresholds: PASS ≥ {exp.pass_threshold} · CAUTION ≥ {exp.caution_threshold}</Text>
    <Text size={12}>Authoritative score: {exp.score} · Unrounded: {exp.unrounded_score ?? 'Not supplied'}</Text>
    <StatusBadge status={exp.status} />
    {stock?.state === 'captured' && <>
      <Text size={12}>Raw band: {stock.explanation.raw_status} · Server rounding: Python round, ties to even</Text>
      <Text size={12}>Horizon: {stock.explanation.horizon} · Mode: {stock.explanation.scoring_mode} · IV basis: {stock.explanation.iv_basis}</Text>
    </>}
    {contract?.state === 'captured' && <>
      <Text size={12}>Outcome: {contract.explanation.outcome} · Server rounded score: {contract.explanation.rounded_score ?? 'Not supplied'}</Text>
      {contract.explanation.outcome === 'blocked' && <Text size={12} tone="reject">Score forced to 0 by blocking rules. Component contributions are diagnostic, not the final score.</Text>}
      <Text size={12}>Soft fails: {contract.explanation.soft_fail_count} · Maximum: {contract.explanation.max_soft_fail_count}</Text>
      <Fields values={{ blockers: contract.explanation.blockers, reject_reasons: contract.explanation.reject_reasons, soft_flags: contract.explanation.soft_flags }} />
    </>}
    <div className={styles.factors}>
      {Object.entries(exp.components).map(([key, component]) => <section key={key} className={styles.factor} aria-label={`${key} captured factor`}>
        <Text size={12} weight={500}>{key.replace(/_/g, ' ')}</Text>
        <Data size={12}>Score: {component.raw_score} · Weight (fraction): {component.weight} · Contribution (points): {component.contribution}</Data>
        {/* Remaining captured observations/configuration keep their own labels and units. */}
        <Fields values={Object.fromEntries(Object.entries(component).filter(([field]) => !['raw_score', 'weight', 'contribution'].includes(field)))} />
      </section>)}
    </div>
    {stock?.state === 'captured' && <>
      <Text size={12} weight={500}>Gate reasons and captured configuration</Text>
      {stock.explanation.caps.map((cap, i) => <section key={`${cap.name}-${i}`} className={styles.factor}>
        <Text size={12}>{cap.name}: {cap.before} → {cap.after} · Gate status: {cap.status}</Text>
        <Fields values={{ observations: cap.detail, configuration: cap.config }} />
      </section>)}
      <details><summary>Effective gate configuration and weights</summary><Fields values={{ gate_config: stock.explanation.gate_config, weights: stock.explanation.weights }} /></details>
    </>}
    {contract?.state === 'captured' && <details>
      <summary>Effective bounds, raw inputs and weighted losses</summary>
      <Fields values={{ hard_bounds: contract.explanation.hard_bounds, raw_inputs: contract.explanation.raw_inputs, weights: contract.explanation.weights, largest_losses: contract.explanation.largest_losses }} />
    </details>}
  </section>;
}
