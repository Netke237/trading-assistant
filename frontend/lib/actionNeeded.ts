/**
 * "Action needed" items for the Portfolio page (PORTFOLIO-ALERT-ACTION, #672,
 * plan §4). Pure: no store, no fetch, the clock is passed in.
 *
 * Active conditions come from the same override-free engine as the status
 * badge and the exit reason: `scanPortfolio` with the position's alert
 * overrides removed and no `enabledTypes`, so neither a per-position mute nor
 * the notification settings hide a position past its stop.
 */
import type { PortfolioPosition } from '@/types/domain';
import type { AlertEpisode } from '@/lib/api';
import { scanPortfolio, type AlertReason } from '@/lib/alertEngine';
import { derivePositionStatus } from '@/lib/positionStatus';
import { formatMoney, readableContract, MINUS } from '@/lib/portfolioFormat';
import { EPISODE_GAP_HOURS, episodeKey, formatActiveDuration, formatSince } from '@/lib/alertEpisodes';

/** The action types, in the order an item lists its entries. */
export const ACTION_TYPES = [
  'STOP_REACHED',
  'STRUCTURAL_STOP_BREACHED',
  'PREMIUM_STOP',
  'TIME_STOP',
  'TP_HIT',
] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

/** Price-stop types: an item holding one of these sorts first. */
const STOP_TYPES: ReadonlySet<ActionType> = new Set(['STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP']);

/** Labels as the notifier writes them (backend alert_notifier
 *  `_ALERT_TYPE_LABELS`); PREMIUM_STOP by side (`_PREMIUM_STOP_LABELS_BY_SIDE`). */
const LABELS: Record<ActionType, string> = {
  STOP_REACHED: 'Stop hit',
  STRUCTURAL_STOP_BREACHED: 'Structural level hit',
  PREMIUM_STOP: 'Premium stop hit',
  TIME_STOP: 'Time stop hit',
  TP_HIT: 'Target reached',
};
const PREMIUM_STOP_LABELS_BY_SIDE: Record<string, string> = {
  'short-stock': 'Stock stop hit (short)',
  'long-stock': 'Stock stop hit',
  'option': 'Premium stop hit',
};

export const DETAIL_NEW = 'new — not yet logged';
export const DETAIL_UNAVAILABLE = 'duration unavailable';
export const DETAIL_PENDING = 'duration loading…';

/** What the episodes fetch produced. `pending` = no answer yet (or no clock
 *  yet): no duration is claimed, and nothing is called "new". */
export type EpisodesInput =
  | { status: 'loaded'; byKey: Record<string, AlertEpisode>; gapHours: number | null }
  | { status: 'failed' }
  | { status: 'pending' };

export interface ActionEntry {
  alertType: ActionType;
  label: string;
  /** "9 days, since 18 Nov" | "30+ days, since before 28 Oct" | DETAIL_*. */
  detail: string;
  /** ms the current episode has been active (a lower bound when truncated);
   *  null without a current episode. Sorting only. */
  activeMs: number | null;
}

export interface ActionItem {
  contract: string;
  recId: string;
  symbol: string;
  /** e.g. "67C · 19 Mar 27" / "Stock". */
  contractLabel: string;
  /** The stop-breach banner sentence when the derived breach is the stop or
   *  the structural stop; null otherwise. */
  breachSentence: string | null;
  entries: ActionEntry[];
}

/** `−5.2%` / `+9.6%`, one decimal, Unicode minus. */
function formatBreachPct(v: number): string {
  const s = Math.abs(v).toFixed(1);
  return Number(v.toFixed(1)) < 0 ? `${MINUS}${s}%` : `+${s}%`;
}

/** The stop-breach banner sentence (PORTFOLIO-RISK-VIEW #682), moved verbatim
 *  from portfolio/page.tsx: one per row whose derived breach is the underlying
 *  stop or the structural stop. breachPct is (underlying - level) / underlying,
 *  the OPPOSITE sign of positionRange.stopPct. */
export function stopBreachSentence(p: PortfolioPosition, premiumStopPct: number): string | null {
  const { breach } = derivePositionStatus(p, { premiumStopPct });
  if (breach !== 'stop' && breach !== 'structural') return null;
  const underlying = p.contract.endsWith('|STOCK') ? p.currentPrice : (p.currentStockPrice ?? 0);
  const level = breach === 'stop' ? p.stop : p.structuralStop;
  if (level == null || !(underlying > 0)) return null;
  const pct = ((underlying - level) / underlying) * 100;
  const label = breach === 'stop' ? 'stop' : 'structural stop';
  return (
    `${p.symbol} ${readableContract(p.contract)}: ${label} breached. ` +
    `Underlying ${formatMoney(underlying, { decimals: 2 })} is ${p.direction === 'Bearish' ? 'above' : 'below'} ` +
    `your ${label} ${formatMoney(level, { decimals: 2 })} (${formatBreachPct(pct)}).` +
    (p.quoteUnavailable === true && !p.contract.endsWith('|STOCK')
      ? ' The option has had no quote since the last sync, so its P&L and risk are unknown.'
      : '')
  );
}

function labelOf(r: AlertReason): string {
  if (r.alertType === 'PREMIUM_STOP') {
    return PREMIUM_STOP_LABELS_BY_SIDE[r.stopSide ?? ''] ?? LABELS.PREMIUM_STOP;
  }
  return LABELS[r.alertType as ActionType];
}

function entryFor(
  p: PortfolioPosition,
  r: AlertReason,
  episodes: EpisodesInput,
  now: Date,
): ActionEntry {
  const alertType = r.alertType as ActionType;
  const base = { alertType, label: labelOf(r) };
  if (episodes.status === 'failed') return { ...base, detail: DETAIL_UNAVAILABLE, activeMs: null };
  if (episodes.status === 'pending') return { ...base, detail: DETAIL_PENDING, activeMs: null };

  const ep = episodes.byKey[episodeKey(p.recId, alertType)];
  const gapMs = (episodes.gapHours ?? EPISODE_GAP_HOURS) * 3_600_000;
  const start = ep ? Date.parse(ep.startedAt) : NaN;
  const last = ep ? Date.parse(ep.lastFiredAt) : NaN;
  // Current episode = the key's latest episode with now − last fire ≤ gap.
  const current = ep != null && Number.isFinite(start) && Number.isFinite(last) && now.getTime() - last <= gapMs;
  if (!current) return { ...base, detail: DETAIL_NEW, activeMs: null };

  const duration = formatActiveDuration(ep.startedAt, now, ep.startTruncated);
  const since = formatSince(ep.startedAt, ep.startTruncated);
  if (duration == null || since == null) return { ...base, detail: DETAIL_UNAVAILABLE, activeMs: null };
  return { ...base, detail: `${duration}, ${since}`, activeMs: Math.max(0, now.getTime() - start) };
}

/** One item per position with at least one active action condition, sorted:
 *  positions with a price-stop entry first, then longest active duration
 *  first, then symbol (then contract, so the order is stable). */
export function buildActionItems(
  positions: readonly PortfolioPosition[],
  episodes: EpisodesInput,
  opts: { premiumStopPct: number; now: Date },
): ActionItem[] {
  const items: { item: ActionItem; hasStop: boolean; longest: number }[] = [];
  for (const p of positions) {
    const reasons = scanPortfolio([{ ...p, alertOverrides: {} }], { premiumStopPct: opts.premiumStopPct })
      .filter((r) => (ACTION_TYPES as readonly string[]).includes(r.alertType));
    if (reasons.length === 0) continue;
    // One entry per type, in ACTION_TYPES order.
    const byType = new Map<string, AlertReason>();
    for (const r of reasons) if (!byType.has(r.alertType)) byType.set(r.alertType, r);
    const entries = ACTION_TYPES.flatMap((t) => {
      const r = byType.get(t);
      return r ? [entryFor(p, r, episodes, opts.now)] : [];
    });
    items.push({
      item: {
        contract: p.contract,
        recId: p.recId,
        symbol: p.symbol,
        contractLabel: readableContract(p.contract),
        breachSentence: stopBreachSentence(p, opts.premiumStopPct),
        entries,
      },
      hasStop: entries.some((e) => STOP_TYPES.has(e.alertType)),
      longest: Math.max(-1, ...entries.map((e) => e.activeMs ?? -1)),
    });
  }
  items.sort((a, b) =>
    (a.hasStop === b.hasStop ? 0 : a.hasStop ? -1 : 1)
    || b.longest - a.longest
    || a.item.symbol.localeCompare(b.item.symbol)
    || a.item.contract.localeCompare(b.item.contract));
  return items.map((x) => x.item);
}
