/*
 * Data — JetBrains Mono, for ALL numeric values.
 *
 * Use for: prices ($185.20), percentages (+2.4%), scores (87/100), tickers (AAPL),
 * contracts (AAPL 220C 05/16), timestamps (09:42), DTE counts, ratios (2.4:1).
 *
 * This is the spec's strongest rule — mixing fonts for numbers is what makes
 * a trading UI look amateur. Drift log G1.
 */

import styles from './Data.module.css';

export type DataSize = 10 | 11 | 12 | 13 | 14 | 16 | 18 | 24;
export type DataWeight = 400 | 500;
export type DataTone = 'primary' | 'secondary' | 'dim' | 'accent' | 'pass' | 'caution' | 'reject';
type DataTag = 'span' | 'p' | 'div' | 'td' | 'strong';

interface DataProps {
  as?: DataTag;
  size?: DataSize;
  weight?: DataWeight;
  tone?: DataTone;
  className?: string;
  children: React.ReactNode;
}

const SIZE_CLASS: Record<DataSize, string> = {
  10: styles.s10,
  11: styles.s11,
  12: styles.s12,
  13: styles.s13,
  14: styles.s14,
  16: styles.s16,
  18: styles.s18,
  24: styles.s24,
};

const WEIGHT_CLASS: Record<DataWeight, string> = {
  400: styles.w400,
  500: styles.w500,
};

const TONE_CLASS: Record<Exclude<DataTone, 'primary'>, string> = {
  secondary: styles.toneSecondary,
  dim:       styles.toneDim,
  accent:    styles.toneAccent,
  pass:      styles.tonePass,
  caution:   styles.toneCaution,
  reject:    styles.toneReject,
};

export function Data({
  as = 'span',
  size = 12,
  weight = 400,
  tone = 'primary',
  className,
  children,
}: DataProps) {
  const Tag = as;
  const classes = [
    styles.data,
    SIZE_CLASS[size],
    WEIGHT_CLASS[weight],
    tone !== 'primary' ? TONE_CLASS[tone] : null,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <Tag className={classes}>{children}</Tag>;
}
