/*
 * ContextRail — the styled 300px right column. Pages supply content via
 * the @contextRail parallel route slot (see app/(frame)/@contextRail/).
 *
 * RailSection is a helper for per-page rail content — consistent header +
 * body styling without every page reinventing the markup.
 */

import { Text } from '@/components/primitives';
import styles from './ContextRail.module.css';

export function ContextRail({ children }: { children: React.ReactNode }) {
  return <aside className={styles.rail}>{children}</aside>;
}

interface RailSectionProps {
  title: string;
  children: React.ReactNode;
}

export function RailSection({ title, children }: RailSectionProps) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <Text size={10} weight={500} tone="secondary">
          {title}
        </Text>
      </div>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  );
}
