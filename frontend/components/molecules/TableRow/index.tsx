/*
 * TableRow — status-tinted row. Drift log G3.
 *
 * Layout intentionally uses CSS Grid — the parent supplies a `columns`
 * string (grid-template-columns) so every row in a table aligns.
 */

import type { Status } from '@/lib/status';
import { useThemeStore } from '@/lib/theme';
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
  const density = useThemeStore((s) => s.density);
  return (
    <div
      role={onClick ? 'button' : 'row'}
      /* The status this row is TINTED with. The colour band down the left edge
         is the first thing the eye reads on these tables, and under jest it is
         invisible: `*.module.css` maps to `{}`, so STATUS_CLASS[status] is
         `undefined` whatever the status is. Step 5's audit round 2 measured the
         consequence -- tinting rows with the event sub-verdict instead of the
         gate shipped 1740/1740 green, so a row could show a PASS band beside a
         REJECT badge. Publishing it is what lets a caller pin the two together. */
      data-status={status}
      data-density={density.toLowerCase()}
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
