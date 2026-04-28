'use client';

/*
 * NavRail — Route-driven branch between nav items and the Stepper.
 * Drift log G4. Spec §4.
 *
 * On /screener/*, NavItems is replaced by the vertical Stepper and the rail
 * widens to fit the step labels. No manual state — the URL is the source of truth.
 */

import { usePathname } from 'next/navigation';

import { ScanIndicator } from '@/components/molecules/ScanIndicator';
import { NavItems } from '@/components/organisms/NavItems';
import { Stepper } from '@/components/organisms/Stepper';
import styles from './NavRail.module.css';

export function NavRail() {
  const pathname  = usePathname() ?? '';
  const inScreener = pathname.startsWith('/screener');

  return (
    <aside className={[styles.rail, inScreener ? styles.railExpanded : null].filter(Boolean).join(' ')}>
      {inScreener ? <Stepper /> : <NavItems />}
      <div className={styles.footer}>
        <ScanIndicator />
      </div>
    </aside>
  );
}
