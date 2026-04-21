/*
 * IconButton — ghost button with an icon. Used for close (×), filter, etc.
 * Spec §5 (INLINE CHART PANEL close button), Screen 6 sub-nav icons.
 */

import styles from './IconButton.module.css';

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: 'sm' | 'md' | 'lg';
  bordered?: boolean;
  /** Accessible label is mandatory — icon-only buttons need one. */
  'aria-label': string;
  children: React.ReactNode;
}

export function IconButton({
  size = 'md',
  bordered,
  className,
  children,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={[
        styles.button,
        styles[size],
        bordered ? styles.bordered : null,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      <span className={styles.icon}>{children}</span>
    </button>
  );
}
