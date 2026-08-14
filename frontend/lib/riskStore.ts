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

interface RiskState {
  limits: RiskLimits;
  dailyRecommendations: number;
  lastResetDate: string;
  metrics: PortfolioRiskMetrics;
  symbols: string[];
  setLimits: (l: RiskLimits) => void;
  incrementDaily: () => void;
  computeMetrics: (positions: PortfolioPosition[]) => void;
}

export const useRiskStore = create<RiskState>()(
  persist(
    (set, get) => ({
      limits: { ...DEFAULT_LIMITS },
      dailyRecommendations: 0,
      lastResetDate: localTodayIso(),
      metrics: { ...DEFAULT_METRICS },
      symbols: [],
      setLimits: (l) => set({ limits: l }),
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
      partialize: (state) => ({
        limits: state.limits,
        dailyRecommendations: state.dailyRecommendations,
        lastResetDate: state.lastResetDate,
        symbols: state.symbols,
      }),
    }
  )
);
