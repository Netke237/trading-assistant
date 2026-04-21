/*
 * Text — DM Sans, the UI font.
 *
 * Use for: nav items, labels, body text, button labels, form hints, descriptions.
 * Do NOT use for numeric data, tickers, prices, timestamps — that's <Data>.
 * Do NOT use for the wordmark or H1 — that's <Title>.
 *
 * Sizes and weights are restricted to values in the spec's size scale (§2).
 */

import styles from './Text.module.css';

export type TextSize = 10 | 11 | 12 | 13 | 14 | 16;
export type TextWeight = 400 | 500 | 600;
export type TextTone = 'primary' | 'secondary' | 'dim' | 'accent' | 'pass' | 'caution' | 'reject';
type TextTag = 'span' | 'p' | 'div' | 'label' | 'small' | 'strong' | 'li';

interface TextProps {
  as?: TextTag;
  size?: TextSize;
  weight?: TextWeight;
  tone?: TextTone;
  className?: string;
  children: React.ReactNode;
}

const SIZE_CLASS: Record<TextSize, string> = {
  10: styles.s10,
  11: styles.s11,
  12: styles.s12,
  13: styles.s13,
  14: styles.s14,
  16: styles.s16,
};

const WEIGHT_CLASS: Record<TextWeight, string> = {
  400: styles.w400,
  500: styles.w500,
  600: styles.w600,
};

const TONE_CLASS: Record<Exclude<TextTone, 'primary'>, string> = {
  secondary: styles.toneSecondary,
  dim:       styles.toneDim,
  accent:    styles.toneAccent,
  pass:      styles.tonePass,
  caution:   styles.toneCaution,
  reject:    styles.toneReject,
};

export function Text({
  as = 'span',
  size = 13,
  weight = 400,
  tone = 'primary',
  className,
  children,
}: TextProps) {
  const Tag = as;
  const classes = [
    styles.text,
    SIZE_CLASS[size],
    WEIGHT_CLASS[weight],
    tone !== 'primary' ? TONE_CLASS[tone] : null,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <Tag className={classes}>{children}</Tag>;
}
