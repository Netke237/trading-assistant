'use client';

import { Text, Data } from '@/components/primitives';
import {
  formatRaceRisk,
  formatRaceRR,
  formatRacePremiumRR,
  formatRaceEdge,
  money,
} from '@/lib/barrierRace';
import type { BarrierRace, BarrierRaceOutcome } from '@/types/domain';
import styles from './BarrierRaceCard.module.css';

export interface BarrierRaceCardProps {
  /** `undefined` while nothing has been run, `null` when the simulation was
   *  refused (dte < 1). The two render differently and neither renders bars. */
  race: BarrierRace | null | undefined;
  /** The premium the estimate was computed against — the baseline every printed
   *  chain subtracts. Comes from `firstPassageContext`, never from
   *  `contractDetails.mid`, which is a scan-time snapshot. */
  premium: number;
  /** True only while the estimate on screen was fetched THIS mount. See the
   *  freshness note below. */
  isFresh: boolean;
  /** Set when a barrier moved after the race was computed. The race is CLEARED,
   *  not recomputed: its bars were measured against a stop the user has since
   *  moved, and re-running is a click, not something that happens on its own. */
  barriersChanged?: boolean;
}

function pctLabel(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function daysLabel(v: number | null): string {
  return v == null ? '—' : `~${v.toFixed(0)}d`;
}

/**
 * The Barrier Race.
 *
 * A REFEREE, not a fourth profit-target method: it proposes no level of its
 * own. Every barrier it races is a level one of the three existing cards
 * already produced — the profit target, the structural stock stop, and the
 * card's own editable premium stop.
 *
 * What it adds is that the outcomes are an ATTRIBUTION. The Monte Carlo card
 * above measures "did the option ever cross the target" and "did the stock ever
 * cross the invalidation price" on the same paths, independently, so the two can
 * sum past 100% and a path that hit both is counted twice. Here every path is
 * assigned to whichever barrier it reached FIRST, so each row sums to exactly
 * 100% and the medians mean something.
 */
export default function BarrierRaceCard({
  race,
  premium,
  isFresh,
  barriersChanged = false,
}: BarrierRaceCardProps) {
  if (race === null) {
    return (
      <section className={styles.card}>
        <Header />
        <Text size={12} tone="dim">
          Not simulated — contract expires today. A zero-length simulation has no paths to
          attribute, and four zeroes would read as a result rather than a refusal.
        </Text>
      </section>
    );
  }

  if (barriersChanged) {
    return (
      <section className={styles.card}>
        <Header />
        <Text size={12} tone="caution">
          Barriers changed — re-run the estimate. These bars were measured against a stop that has
          since moved, so they no longer describe this trade.
        </Text>
      </section>
    );
  }

  // A restored estimate can be arbitrarily old, and its two barrier inputs
  // (the shared stop, the editable premium stop) are live. Rendering it beside
  // current inputs is the same mixed-vintage hazard five audit rounds built
  // structuralRR's freshness machinery to prevent.
  if (!race || !isFresh) return null;

  return (
    <section className={styles.card}>
      <Header />

      {/* 1. The three barriers ------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>The three barriers</Text>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col"><Text size={10} tone="dim">Barrier</Text></th>
              <th scope="col"><Text size={10} tone="dim">Level</Text></th>
              <th scope="col"><Text size={10} tone="dim">How it is set</Text></th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><Text size={11}>Profit target</Text></td>
              <td><Data size={11}>per row below</Data></td>
              <td><Text size={11} tone="secondary">Your T1/T2/T3 % of premium</Text></td>
            </tr>
            <tr>
              <td><Text size={11}>Stock stop</Text></td>
              {/* Always with its unit. A bare number here would be ambiguous
                  against the option-value barrier on the next row. */}
              <td><Data size={11}>{money(race.stockStopPrice)} stock</Data></td>
              <td><Text size={11} tone="secondary">Structural level, or structural + ATR once an Arithmetic Plan has run</Text></td>
            </tr>
            <tr>
              <td><Text size={11}>Premium stop</Text></td>
              <td><Data size={11}>{money(race.premiumStopPrice)} option</Data></td>
              <td><Text size={11} tone="secondary">{pctLabel(race.premiumStopPct)} of premium, from the editable field above</Text></td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* 2. Race outcome -------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Which barrier is reached first</Text>
        <div className={styles.legend}>
          <LegendKey className={styles.swatchTarget} label="Target first" />
          <LegendKey className={styles.swatchStock} label="Stock stop first" />
          <LegendKey className={styles.swatchPremium} label="Premium stop first" />
          <LegendKey className={styles.swatchNeither} label="Neither, held to expiry" />
        </div>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col"><Text size={10} tone="dim">Target</Text></th>
              <th scope="col"><Text size={10} tone="dim">Split</Text></th>
              <th scope="col"><Text size={10} tone="dim">Target</Text></th>
              <th scope="col"><Text size={10} tone="dim">Stock stop</Text></th>
              <th scope="col"><Text size={10} tone="dim">Premium stop</Text></th>
              <th scope="col"><Text size={10} tone="dim">Neither</Text></th>
              <th scope="col"><Text size={10} tone="dim">Median to target</Text></th>
            </tr>
          </thead>
          <tbody>
            {race.outcomes.map((o) => (
              <tr key={o.targetPct}>
                <td>
                  <Text size={11} weight={500}>{pctLabel(o.targetPct)}</Text>
                  <Data size={10} tone="dim">{money(o.targetOptionPrice)}</Data>
                </td>
                <td><StackedBar o={o} /></td>
                <td><Data size={11}>{pctLabel(o.pTargetFirst)}</Data></td>
                <td><Data size={11}>{pctLabel(o.pStockStopFirst)}</Data></td>
                <td><Data size={11}>{pctLabel(o.pPremiumStopFirst)}</Data></td>
                <td><Data size={11}>{pctLabel(o.pNeither)}</Data></td>
                <td><Data size={11}>{daysLabel(o.daysTarget)}</Data></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Text size={10} tone="dim">
          Every row sums to 100% because each of the {race.nPaths.toLocaleString()} simulated paths
          is counted once, for whichever barrier it reached first. The Monte Carlo card above
          measures each barrier on its own, so its numbers can sum past 100%.
        </Text>
        <Text size={10} tone="dim">
          The medians are conditional: &quot;{daysLabel(race.outcomes[0]?.daysTarget ?? null)} to{' '}
          {pctLabel(race.outcomes[0]?.targetPct ?? 0)}&quot; is the median over the paths that got
          there first, not over all paths.
        </Text>
      </div>

      {/* 3. Risk / reward ------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Risk and reward, per target</Text>
        {race.outcomes.map((o) => (
          <div key={o.targetPct} className={styles.chainGroup}>
            <Text size={11} weight={500}>{pctLabel(o.targetPct)} target</Text>
            <div className={styles.chain}>
              <Text size={10} tone="dim">Risk</Text>
              <Data size={11}>{formatRaceRisk(o, premium)}</Data>
            </div>
            <div className={styles.chain}>
              <Text size={10} tone="dim">R:R vs stock stop</Text>
              <Data size={11} weight={500}>{formatRaceRR(o)}</Data>
            </div>
            <div className={`${styles.chain} ${styles.muted}`}>
              <Text size={10} tone="dim">R:R vs premium stop</Text>
              <Data size={11} tone="dim">{formatRacePremiumRR(o, race.premiumStopPct)}</Data>
            </div>
          </div>
        ))}
        <Text size={10} tone="dim">
          Only the first ratio is a measurement. Its risk leg is the premium minus what the
          contract would still be worth at the stock stop, which depends on strike, spot, time and
          IV independently — so it genuinely differs between contracts. The greyed one divides two
          numbers that are both a fixed fraction of premium, so premium cancels and it reduces to
          your target % over your stop %. It is the same on every contract you could pick.
        </Text>
      </div>

      {/* 4. Edge ---------------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Edge per contract</Text>
        {race.outcomes.map((o) => (
          <div key={o.targetPct} className={styles.chainGroup}>
            <Text size={11} weight={500}>{pctLabel(o.targetPct)} target</Text>
            <Data size={11}>{formatRaceEdge(o, premium)}</Data>
          </div>
        ))}
        <Text size={10} tone="dim">
          The &quot;Neither&quot; term is the mean value of those paths at expiry minus the premium
          paid. It is signed, not a loss — those paths can end above what you paid.
        </Text>
        <Text size={10} tone="dim">
          Assumes implied volatility is unchanged when a barrier is reached. On a long call that is
          pessimistic at the stop and optimistic at the target — a real fear bid would leave more
          premium than shown.
        </Text>
      </div>
    </section>
  );
}

function Header() {
  return (
    <>
      <Text size={14} weight={600}>Barrier Race</Text>
      <Text size={10} tone="dim">
        Same simulation as the Monte Carlo card above, read differently: every path is attributed to
        whichever barrier it reached first. It proposes no level of its own.
      </Text>
    </>
  );
}

function LegendKey({ className, label }: { className: string; label: string }) {
  return (
    <span className={styles.legendKey}>
      <span className={`${styles.swatch} ${className}`} aria-hidden="true" />
      <Text size={10} tone="dim">{label}</Text>
    </span>
  );
}

/** A 100%-stacked bar. Widths come straight from the returned shares, which sum
 *  to 1 by construction, so the segments always fill the track exactly. */
function StackedBar({ o }: { o: BarrierRaceOutcome }) {
  const segments: Array<[string, number, string]> = [
    [styles.swatchTarget, o.pTargetFirst, 'Target first'],
    [styles.swatchStock, o.pStockStopFirst, 'Stock stop first'],
    [styles.swatchPremium, o.pPremiumStopFirst, 'Premium stop first'],
    [styles.swatchNeither, o.pNeither, 'Neither'],
  ];
  return (
    <div
      className={styles.bar}
      role="img"
      aria-label={
        `${(o.targetPct * 100).toFixed(0)}% target: `
        + segments.map(([, v, label]) => `${label} ${(v * 100).toFixed(0)}%`).join(', ')
      }
    >
      {segments.map(([cls, v, label]) => (
        v > 0 ? (
          <span
            key={label}
            className={`${styles.segment} ${cls}`}
            // toFixed, not `v * 100`: 0.14 * 100 is 14.000000000000002 in
            // binary floating point, and that tail ends up in the rendered
            // style attribute verbatim.
            style={{ width: `${(v * 100).toFixed(4)}%` }}
            data-testid={`segment-${label}`}
          />
        ) : null
      ))}
    </div>
  );
}
