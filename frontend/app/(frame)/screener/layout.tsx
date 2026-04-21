/*
 * Screener nested layout — spec §4.
 * Adds the 52px StepNavBar at the bottom of the workspace column.
 * The persistent frame (TopBar, NavRail, ContextRail) comes from (frame)/layout.tsx.
 *
 * Structure inside the workspace grid cell:
 *   ┌───────────────────────────────────┐
 *   │  scrollable step content          │
 *   │  (children)                       │
 *   ├───────────────────────────────────┤
 *   │  StepNavBar (Back | step | Next)  │
 *   └───────────────────────────────────┘
 */

import { StepNavBar } from '@/components/organisms/StepNavBar';
import styles from './screenerLayout.module.css';

export default function ScreenerLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.wrap}>
      <div className={styles.scroll}>{children}</div>
      <StepNavBar />
    </div>
  );
}
