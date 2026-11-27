// frontend/lib/exitReason.ts
// Why a position was closed (PORTFOLIO-EXIT-RECORD). The 8 values mirror the
// backend's `ClosePositionRequest.exitReason` Literal; a closed row whose
// reason was never sent reads null ("Not recorded").
import type { PortfolioPosition } from '@/types/domain';
import { derivePositionStatus } from '@/lib/positionStatus';
import { scanPortfolio } from '@/lib/alertEngine';
import { parseContractId } from '@/lib/contractGrading';

export const EXIT_REASONS = [
  'stop',
  'structural_stop',
  'premium_stop',
  'target',
  'time_stop',
  'expiry',
  'manual',
  'unknown',
] as const;

export type ExitReason = typeof EXIT_REASONS[number];

const LABELS: Record<ExitReason, string> = {
  stop: 'Stop',
  structural_stop: 'Structural stop',
  premium_stop: 'Premium stop',
  target: 'Target',
  time_stop: 'Time stop',
  expiry: 'Expiry',
  manual: 'Manual',
  unknown: 'Unknown',
};

export function exitReasonLabel(r: ExitReason | null | undefined): string {
  return r == null ? 'Not recorded' : LABELS[r];
}

/** The reason the close dialog pre-selects. First match wins:
 *  a breach (stop / structural / percent stop — the percent stop covers
 *  stocks too), an option expiring on/before the exit date, a time stop,
 *  a reached target, otherwise manual. Same engine as the row badge. */
export function defaultExitReason(
  p: PortfolioPosition,
  opts: { premiumStopPct: number; exitDate: string },
): ExitReason {
  const { breach } = derivePositionStatus(p, { premiumStopPct: opts.premiumStopPct });
  if (breach === 'stop') return 'stop';
  if (breach === 'structural') return 'structural_stop';
  if (breach === 'premium') return 'premium_stop';

  const parsed = parseContractId(p.contract);
  if (parsed && opts.exitDate && parsed.expiry <= opts.exitDate) return 'expiry';

  // Per-position alert mutes do not change why a trade closed — the same
  // override-free scan derivePositionStatus runs.
  const types = new Set(
    scanPortfolio([{ ...p, alertOverrides: {} }], { premiumStopPct: opts.premiumStopPct })
      .map((r) => r.alertType),
  );
  if (types.has('TIME_STOP')) return 'time_stop';
  if (types.has('TP_HIT')) return 'target';
  return 'manual';
}
