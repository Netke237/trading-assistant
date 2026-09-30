// Settings' shared row and section-intro layout, out of page.tsx so a section
// can live in its own file (and be rendered alone in a test): a Next.js page
// module may not carry named exports.
import React from 'react';
import { Text } from '@/components/primitives';
import styles from './page.module.css';

export function SectionIntro({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className={styles.intro}>
      <Text size={14} weight={600}>{title}</Text>
      <Text size={12} tone="secondary">{blurb}</Text>
    </div>
  );
}

export function Row({
  label,
  hint,
  defaultValue,
  children,
}: {
  label: string;
  hint?: string;
  defaultValue?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.row}>
      <div className={styles.rowLabel}>
        <Text size={13} weight={400}>{label}</Text>
        {hint && <Text size={11} tone="secondary">{hint}</Text>}
        {defaultValue !== undefined && (
          <span className={styles.defaultTag} title="Out-of-the-box value">
            Default: {defaultValue}
          </span>
        )}
      </div>
      <div className={styles.rowControl}>{children}</div>
    </div>
  );
}
