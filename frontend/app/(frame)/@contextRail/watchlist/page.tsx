/*
 * Watchlist right-rail. Spec §4: Filter + flag summary.
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';

export default function WatchlistContextRail() {
  const pass    = MOCK_WATCHLIST.filter((r) => r.status === 'PASS').length;
  const caution = MOCK_WATCHLIST.filter((r) => r.status === 'CAUTION').length;
  const reject  = MOCK_WATCHLIST.filter((r) => r.status === 'REJECT').length;
  const evtSoon = MOCK_WATCHLIST.filter((r) => (r.nextEventDays ?? 999) <= 7).length;

  return (
    <>
      <RailSection title="Status breakdown">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Row><StatusBadge status="PASS"    /><Data size={12}>{pass}</Data></Row>
          <Row><StatusBadge status="CAUTION" /><Data size={12}>{caution}</Data></Row>
          <Row><StatusBadge status="REJECT"  /><Data size={12}>{reject}</Data></Row>
        </div>
      </RailSection>

      <RailSection title="Flags">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Row><Text size={12} tone="secondary">Earnings ≤ 7d</Text><Data size={12}>{evtSoon}</Data></Row>
          <Row><Text size={12} tone="secondary">Total</Text><Data size={12}>{MOCK_WATCHLIST.length}</Data></Row>
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>{children}</div>;
}
