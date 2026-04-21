/*
 * TableRow — status-tinted row. Drift log G3.
 *
 * Layout intentionally uses CSS Grid — the parent supplies a `columns`
 * string (grid-template-columns) so every row in a table aligns.
 */

import type { Status } from '@/lib/status';
import styles from './TableRow.module.css';

interface TableRowProps {
  status: Status;
  /** grid-template-columns string, e.g. "80px 1fr 80px 60px". */
  columns: string;
  selected?: boolean;
  onClick?: () => void;
  className?: string;
  children: React.ReactNode;
}

const STATUS_CLASS: Record<Status, string> = {
  PASS:    styles.pass,
  CAUTION: styles.caution,
  REJECT:  styles.reject,
  PENDING: styles.pending,
  NO_DATA: styles.noData,
};

export function TableRow({
  status,
  columns,
  selected,
  onClick,
  className,
  children,
}: TableRowProps) {
  return (
    <div
      role={onClick ? 'button' : 'row'}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      style={{ gridTemplateColumns: columns }}
      className={[
        styles.row,
        STATUS_CLASS[status],
        selected ? styles.selected : null,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </div>
  );
}
