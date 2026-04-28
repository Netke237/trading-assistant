/*
 * Portfolio right-rail. Spec §4: Aggregate Greeks / risk summary.
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import styles from './page.module.css';

export default function PortfolioContextRail() {
  const deployed = MOCK_PORTFOLIO.reduce((s, p) => s + p.currentPrice * 100, 0);
  const openPnL  = MOCK_PORTFOLIO.reduce((s, p) => s + p.pnlDollar, 0);
  // Mock aggregate Greeks — Phase 6 will compute properly.
  const delta = MOCK_PORTFOLIO.reduce((s, p) => s + (p.direction === 'Bullish' ? 0.45 : -0.42), 0).toFixed(2);
  const theta = (-(MOCK_PORTFOLIO.length * 3.8)).toFixed(1);
  const vega  = (MOCK_PORTFOLIO.length * 5.4).toFixed(1);

  return (
    <>
      <RailSection title="Totals">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL >= 0 ? 'pass' : 'reject'}>
              {openPnL >= 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </Row>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{MOCK_PORTFOLIO.length}</Data></Row>
        </div>
      </RailSection>

      <RailSection title="Aggregate Greeks">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Δ Delta</Text><Data size={12}>{delta}</Data></Row>
          <Row><Text size={12} tone="secondary">Θ Theta / day</Text><Data size={12} tone="reject">{theta}</Data></Row>
          <Row><Text size={12} tone="secondary">ν Vega</Text><Data size={12}>{vega}</Data></Row>
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
