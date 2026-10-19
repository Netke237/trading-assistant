/**
 * Returns the English ordinal suffix ('st', 'nd', 'rd', 'th') for a number.
 * Returns an empty string for non-finite values.
 */
export function ordinalSuffix(n: number): string {
  if (!Number.isFinite(n)) return '';
  const abs = Math.abs(Math.round(n));
  const mod100 = abs % 100;
  if (mod100 >= 11 && mod100 <= 13) {
    return 'th';
  }
  switch (abs % 10) {
    case 1:
      return 'st';
    case 2:
      return 'nd';
    case 3:
      return 'rd';
    default:
      return 'th';
  }
}

/**
 * Formats a number as a rounded integer with its English ordinal suffix,
 * e.g. 0 -> "0th", 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 4 -> "4th", 11 -> "11th", 21 -> "21st", 2.7 -> "3rd".
 * Returns an empty string for non-finite values.
 */
export function formatOrdinal(n: number): string {
  if (!Number.isFinite(n)) return '';
  const rounded = Math.round(n);
  return `${rounded}${ordinalSuffix(rounded)}`;
}
