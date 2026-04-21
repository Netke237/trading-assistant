/*
 * SectionCard — bento card with header (title + count badge + action link)
 * and a body slot. Drift log Screen 1 — used by Dashboard bento rows.
 */

import { Text } from '@/components/primitives';
import styles from './SectionCard.module.css';

interface SectionCardProps {
  title: string;
  count?: number;
  action?: { label: string; onClick?: () => void };
  className?: string;
  children: React.ReactNode;
}

export function SectionCard({ title, count, action, className, children }: SectionCardProps) {
  return (
    <section className={[styles.card, className].filter(Boolean).join(' ')}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <Text size={14} weight={600}>
            {title}
          </Text>
          {count !== undefined && <span className={styles.countBadge}>{count}</span>}
        </div>
        {action && (
          <button type="button" className={styles.actionLink} onClick={action.onClick}>
            <Text size={12} tone="accent">
              {action.label}
            </Text>
          </button>
        )}
      </header>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
