/*
 * Dashboard right-rail. Spec §4: Upcoming events + Portfolio risk summary.
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { MOCK_EVENTS } from '@/mocks/events';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import styles from './page.module.css';

function shortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' });
}

export default function DashboardContextRail() {
  const deployed = MOCK_PORTFOLIO.reduce((s, p) => s + p.currentPrice * 100, 0);
  const openPnL  = MOCK_PORTFOLIO.reduce((s, p) => s + p.pnlDollar, 0);

  return (
    <>
      <RailSection title="Upcoming Events (14d)">
        <div className={styles.eventStack}>
          {MOCK_EVENTS.slice(0, 5).map((e) => (
            <div key={`${e.date}-${e.symbol}`} className={styles.eventRow}>
              <StatusDot tone={e.status} size="sm" />
              <Data size={11} tone="secondary">{shortDate(e.date)}</Data>
              <Data size={11} weight={500}>{e.symbol}</Data>
              <Text size={12} tone="secondary">{e.label}</Text>
            </div>
          ))}
        </div>
      </RailSection>

      <RailSection title="Portfolio Risk">
        <div className={styles.riskStack}>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Deployed</Text>
            <Data size={12}>${Math.round(deployed).toLocaleString()}</Data>
          </div>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL >= 0 ? 'pass' : 'reject'}>
              {openPnL >= 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </div>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Positions</Text>
            <Data size={12}>{MOCK_PORTFOLIO.length}</Data>
          </div>
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}
