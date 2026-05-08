import styles from './AlertBadge.module.css';

interface AlertBadgeProps {
  count: number;
}

export function AlertBadge({ count }: AlertBadgeProps) {
  if (count === 0) {
    return <span className={styles.dot} aria-hidden="true" />;
  }
  return (
    <span className={styles.badge} aria-label={`${count} unread alerts`}>
      {count > 99 ? '99+' : count}
    </span>
  );
}
