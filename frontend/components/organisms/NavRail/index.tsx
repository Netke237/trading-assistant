'use client';

/*
 * NavRail — Route-driven branch between nav items and the Stepper.
 * Drift log G4. Spec §4.
 *
 * On /screener/*, NavItems is replaced by the vertical Stepper and the rail
 * widens to fit the step labels. No manual state — the URL is the source of truth.
 */

import { usePathname } from 'next/navigation';
import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { NavItems } from '@/components/organisms/NavItems';
import { Stepper } from '@/components/organisms/Stepper';
import { useScanStore } from '@/lib/scanStore';
import type { ScanState } from '@/lib/scanStore';
import type { Status } from '@/lib/status';
import styles from './NavRail.module.css';

const SCAN_DOT: Record<ScanState, Status | 'ACCENT'> = {
  IDLE:      'PENDING',
  SCANNING:  'ACCENT',
  COMPLETED: 'PASS',
  FAILED:    'REJECT',
};

export function NavRail() {
  const pathname  = usePathname() ?? '';
  const scanState = useScanStore((s) => s.scanState);
  const inScreener = pathname.startsWith('/screener');

  return (
    <aside className={[styles.rail, inScreener ? styles.railExpanded : null].filter(Boolean).join(' ')}>
      {inScreener ? <Stepper /> : <NavItems />}
      <div className={styles.footer}>
        <StatusDot tone={SCAN_DOT[scanState]} size="sm" />
        <Text size={10} tone="secondary">Scan</Text>
      </div>
    </aside>
  );
}
