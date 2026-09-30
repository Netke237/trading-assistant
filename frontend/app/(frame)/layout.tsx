/*
 * Persistent Frame — spec §4.
 * Receives two slots from App Router:
 *   children     → main workspace content (the page's page.tsx)
 *   contextRail  → right-rail content from @contextRail/... parallel route
 *
 * This is the route-group layout: every page under /dashboard, /watchlist,
 * /portfolio, /calendar, /settings, /screener/* is wrapped by this shell.
 */

import { TopBar } from '@/components/organisms/TopBar';
import { NavRail } from '@/components/organisms/NavRail';
import { ContextRail } from '@/components/organisms/ContextRail';
import { KeyboardShortcuts } from '@/components/KeyboardShortcuts';
import { InitStores } from '@/components/molecules/InitStores';
import styles from '@/components/organisms/Frame.module.css';

export default function FrameLayout({
  children,
  contextRail,
}: {
  children: React.ReactNode;
  contextRail: React.ReactNode;
}) {
  return (
    <div className={styles.frame}>
      <InitStores />
      <a href="#workspace" className={styles.skipLink}>Skip to content</a>
      <TopBar />
      <NavRail />
      <main id="workspace" className={styles.workspace} tabIndex={-1}>{children}</main>
      <ContextRail>{contextRail}</ContextRail>
      <KeyboardShortcuts />
    </div>
  );
}
