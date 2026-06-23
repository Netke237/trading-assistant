import type { ReactNode } from 'react';
import styles from './Tooltip.module.css';

interface TooltipProps {
  text: string;
  children: ReactNode;
  /** Whether the panel appears above or below the trigger. Default: top. */
  position?: 'top' | 'bottom';
  /** Horizontal anchor of the panel. Default: center. */
  align?: 'center' | 'right';
}

export function Tooltip({ text, children, position = 'top', align = 'center' }: TooltipProps) {
  return (
    <span className={styles.wrap} data-position={position} data-align={align}>
      {children}
      <span className={styles.tip} role="tooltip">{text}</span>
    </span>
  );
}
