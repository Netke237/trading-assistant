/*
 * Watchlist right-rail. Spec §4: Filter + flag summary.
 */

'use client';

import { useEffect, useState } from 'react';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { GENERIC_STATUS_TOOLTIP } from '@/lib/statusTooltips';
import { api } from '@/lib/api';
import type { WatchlistRow } from '@/types/domain';
import styles from './page.module.css';

export default function WatchlistContextRail() {
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  useEffect(() => { api.getWatchlist().then(setRows).catch(() => {}); }, []);

  const pass    = rows.filter((r) => r.status === 'PASS').length;
  const caution = rows.filter((r) => r.status === 'CAUTION').length;
  const reject  = rows.filter((r) => r.status === 'REJECT').length;
  const evtSoon = rows.filter((r) => (r.nextEventDays ?? 999) <= 7).length;

  return (
    <>
      <RailSection title="Status breakdown">
        <div className={styles.statStack}>
          <Row><StatusBadge status="PASS"    tooltip={GENERIC_STATUS_TOOLTIP.PASS} /><Data size={12}>{pass}</Data></Row>
          <Row><StatusBadge status="CAUTION" tooltip={GENERIC_STATUS_TOOLTIP.CAUTION} /><Data size={12}>{caution}</Data></Row>
          <Row><StatusBadge status="REJECT"  tooltip={GENERIC_STATUS_TOOLTIP.REJECT} /><Data size={12}>{reject}</Data></Row>
        </div>
      </RailSection>

      <RailSection title="Flags">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Events ≤ 7d</Text><Data size={12}>{evtSoon}</Data></Row>
          <Row><Text size={12} tone="secondary">Total</Text><Data size={12}>{rows.length}</Data></Row>
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
