/*
 * Title — Sora Bold, for wordmark + H1 page titles.
 *
 * Enforces the three-font rule: you cannot pass a different font-family.
 * Allowed sizes are restricted to the spec's size scale (spec §2).
 */

import styles from './Title.module.css';

type TitleSize = 20 | 24 | 32;
type TitleTag = 'h1' | 'h2' | 'span' | 'div';

interface TitleProps {
  as?: TitleTag;
  size?: TitleSize;
  className?: string;
  children: React.ReactNode;
}

const SIZE_CLASS: Record<TitleSize, string> = {
  20: styles.s20,
  24: styles.s24,
  32: styles.s32,
};

export function Title({ as = 'h1', size = 24, className, children }: TitleProps) {
  const Tag = as;
  return (
    <Tag className={[styles.title, SIZE_CLASS[size], className].filter(Boolean).join(' ')}>
      {children}
    </Tag>
  );
}
