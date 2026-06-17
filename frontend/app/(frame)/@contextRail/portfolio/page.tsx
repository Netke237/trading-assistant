/*
 * Portfolio right-rail. Spec §4: Aggregate Greeks / risk summary.
 */

'use client';

import { usePortfolioStore } from '@/lib/portfolioStore';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import styles from './page.module.css';

export default function PortfolioContextRail() {
  const positions = usePortfolioStore((s) => s.positions);
  const deployed = positions.reduce((s, p) => s + p.currentPrice * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1), 0);
  const openPnL  = positions.reduce((s, p) => s + p.pnlDollar, 0);
  const hasGreeks = positions.some((p) => p.delta != null || p.theta != null);
  const aggDelta = hasGreeks
    ? positions.reduce((s, p) => s + (p.delta ?? 0) * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1), 0).toFixed(2)
    : null;
  const aggTheta = hasGreeks
    ? positions.reduce((s, p) => s + (p.theta ?? 0) * (p.contracts ?? 1), 0).toFixed(1)
    : null;

  return (
    <>
      <RailSection title="Totals">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </Row>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{positions.length}</Data></Row>
        </div>
      </RailSection>

      <RailSection title="Aggregate Greeks">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Δ Delta</Text><Data size={12}>{aggDelta ?? '—'}</Data></Row>
          <Row><Text size={12} tone="secondary">Θ Theta / day</Text><Data size={12} tone={aggTheta != null ? (parseFloat(aggTheta) < 0 ? 'reject' : 'pass') : undefined}>{aggTheta ?? '—'}</Data></Row>
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
