import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Status } from '@/lib/status';
import { worstStatus } from '@/lib/status';
import type {
  PortfolioPosition,
  RiskLimits,
  PortfolioRiskMetrics,
} from '@/types/domain';

// portfolioValue is the account size the risk checks measure exposure against.
// It is user-editable in Settings; this is only the first-run default. Exposure
// caps (maxSingleTradeExposurePct etc.) are fractions of THIS value, so a value
// far below the real paper balance will reject otherwise-normal option trades.
const DEFAULT_LIMITS: RiskLimits = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 100000,
  maxLossPerTradePct: 0.0375,
};

const DEFAULT_METRICS: PortfolioRiskMetrics = {
  totalExposurePct: 0,
  concurrentPositions: 0,
  dailyRecommendations: 0,
  largestConcentrationPct: 0,
  largestConcentrationSymbol: '—',
  status: 'PASS',
};

// `new Date().toISOString().split('T')[0]` derives the date string from the UTC calendar day of
// the live instant, not the user's local calendar day — for a user behind UTC (e.g. US Eastern),
// this resets the daily recommendation counter hours before their actual local midnight, silently
// granting extra daily slots early. Derive the ISO date from local calendar fields instead.
function localTodayIso(): string {
  const d = new Date();
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())).toISOString().split('T')[0];
}

export interface RiskState {
  limits: RiskLimits;
  dailyRecommendations: number;
  lastResetDate: string;
  metrics: PortfolioRiskMetrics;
  symbols: string[];
  /** ISO timestamp of the last time `portfolioValue` actually changed value
   *  (not merely re-saved at the same figure) — drives the Settings page's
   *  staleness nudge. `portfolioValue` itself is never auto-tracked from
   *  realized/open P&L, so this is the only signal for "is this still
   *  accurate?" null until the user's first edit. */
  portfolioValueUpdatedAt: string | null;
  /** `opts.isUserEdit` (default true) gates the `portfolioValueUpdatedAt`
   *  stamp — pass `false` from a backend-resync path (e.g. RiskForm's
   *  fetch-on-mount hydration effect) so reconciling the store with a value
   *  that merely changed in another session doesn't masquerade as "the user
   *  just edited this," silently resetting the staleness nudge. */
  setLimits: (l: RiskLimits, opts?: { isUserEdit?: boolean }) => void;
  incrementDaily: () => void;
  computeMetrics: (positions: PortfolioPosition[]) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function boundedNumber(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = finiteNumber(value, fallback);
  return parsed >= min && parsed <= max ? parsed : fallback;
}

export function migrateRisk(persistedState: unknown, _version: number): Partial<RiskState> {
  const prev = (persistedState as Partial<RiskState> | null) ?? {};
  const rawLimits: Record<string, unknown> = isRecord(prev.limits) ? prev.limits : {};
  return {
    ...prev,
    limits: {
      maxSingleTradeExposurePct: boundedNumber(
        rawLimits.maxSingleTradeExposurePct,
        DEFAULT_LIMITS.maxSingleTradeExposurePct,
        0.01,
        1,
      ),
      maxTotalExposurePct: boundedNumber(
        rawLimits.maxTotalExposurePct,
        DEFAULT_LIMITS.maxTotalExposurePct,
        0.01,
        1,
      ),
      maxConcurrentPositions: boundedNumber(
        rawLimits.maxConcurrentPositions,
        DEFAULT_LIMITS.maxConcurrentPositions,
        1,
        50,
      ),
      maxDailyRecommendations: boundedNumber(
        rawLimits.maxDailyRecommendations,
        DEFAULT_LIMITS.maxDailyRecommendations,
        1,
        50,
      ),
      portfolioValue: boundedNumber(
        rawLimits.portfolioValue,
        DEFAULT_LIMITS.portfolioValue,
        1000,
        Number.MAX_SAFE_INTEGER,
      ),
      maxLossPerTradePct: boundedNumber(
        rawLimits.maxLossPerTradePct,
        DEFAULT_LIMITS.maxLossPerTradePct,
        0,
        1,
      ),
    },
    dailyRecommendations: Math.max(
      0,
      Math.floor(finiteNumber(prev.dailyRecommendations, 0)),
    ),
    lastResetDate: typeof prev.lastResetDate === 'string'
      ? prev.lastResetDate
      : localTodayIso(),
    symbols: Array.isArray(prev.symbols)
      ? prev.symbols.filter((symbol): symbol is string => typeof symbol === 'string')
      : [],
    // Pre-v3 stores never tracked this — null means "unknown", not "stale
    // today"; the staleness nudge treats null as neutral rather than caution.
    portfolioValueUpdatedAt: typeof prev.portfolioValueUpdatedAt === 'string'
      ? prev.portfolioValueUpdatedAt
      : null,
  };
}

export const useRiskStore = create<RiskState>()(
  persist(
    (set, get) => ({
      limits: { ...DEFAULT_LIMITS },
      dailyRecommendations: 0,
      lastResetDate: localTodayIso(),
      metrics: { ...DEFAULT_METRICS },
      symbols: [],
      portfolioValueUpdatedAt: null,
      setLimits: (l, opts) => set((s) => ({
        limits: l,
        portfolioValueUpdatedAt: (opts?.isUserEdit ?? true) && l.portfolioValue !== s.limits.portfolioValue
          ? new Date().toISOString()
          : s.portfolioValueUpdatedAt,
      })),
      incrementDaily: () => {
        const today = localTodayIso();
        set((s) => {
          if (s.lastResetDate !== today) {
            return { dailyRecommendations: 1, lastResetDate: today };
          }
          return { dailyRecommendations: s.dailyRecommendations + 1 };
        });
      },
      computeMetrics: (positions) => {
        const { limits, dailyRecommendations } = get();
        const portfolioValue = limits.portfolioValue || 1;
        let totalNotional = 0;
        const symbolNotional: Record<string, number> = {};
        for (const p of positions) {
          const notional = p.currentPrice * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1);
          totalNotional += notional;
          symbolNotional[p.symbol] = (symbolNotional[p.symbol] ?? 0) + notional;
        }
        const totalExposurePct = totalNotional / portfolioValue;
        const concurrentPositions = positions.length;
        let largestConcentrationPct = 0;
        let largestConcentrationSymbol = '—';
        for (const [sym, notional] of Object.entries(symbolNotional)) {
          const pct = notional / portfolioValue;
          if (pct > largestConcentrationPct) {
            largestConcentrationPct = pct;
            largestConcentrationSymbol = sym;
          }
        }

        const statuses: Status[] = [];
        statuses.push(
          totalExposurePct > limits.maxTotalExposurePct
            ? 'REJECT'
            : totalExposurePct > limits.maxTotalExposurePct * 0.8
              ? 'CAUTION'
              : 'PASS'
        );
        statuses.push(
          concurrentPositions >= limits.maxConcurrentPositions
            ? 'REJECT'
            : concurrentPositions >= Math.floor(limits.maxConcurrentPositions * 0.8)
              ? 'CAUTION'
              : 'PASS'
        );
        statuses.push(
          dailyRecommendations >= limits.maxDailyRecommendations
            ? 'REJECT'
            : dailyRecommendations >= Math.floor(limits.maxDailyRecommendations * 0.8)
              ? 'CAUTION'
              : 'PASS'
        );
        statuses.push(
          largestConcentrationPct > limits.maxSingleTradeExposurePct
            ? 'REJECT'
            : largestConcentrationPct > limits.maxSingleTradeExposurePct * 0.8
              ? 'CAUTION'
              : 'PASS'
        );

        const status = worstStatus(...statuses);

        set({
          metrics: {
            totalExposurePct,
            concurrentPositions,
            dailyRecommendations,
            largestConcentrationPct,
            largestConcentrationSymbol,
            status,
          },
          symbols: positions.map((p) => p.symbol),
        });
      },
    }),
    {
      name: 'bamendjou-risk-v1',
      skipHydration: true,
      version: 3,
      migrate: migrateRisk,
      partialize: (state) => ({
        limits: state.limits,
        dailyRecommendations: state.dailyRecommendations,
        lastResetDate: state.lastResetDate,
        symbols: state.symbols,
        portfolioValueUpdatedAt: state.portfolioValueUpdatedAt,
      }),
    }
  )
);
