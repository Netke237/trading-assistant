import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Status } from '@/lib/status';
import { worstStatus } from '@/lib/status';
import { hasInvalidation } from '@/lib/risk';
import type {
  TradeCardData,
  PortfolioPosition,
  RiskLimits,
  RiskCheckResult,
  PortfolioRiskMetrics,
} from '@/types/domain';

const DEFAULT_LIMITS: RiskLimits = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 50000,
};

const DEFAULT_METRICS: PortfolioRiskMetrics = {
  totalExposurePct: 0,
  concurrentPositions: 0,
  dailyRecommendations: 0,
  largestConcentrationPct: 0,
  largestConcentrationSymbol: '—',
  status: 'PASS',
};

interface RiskState {
  limits: RiskLimits;
  dailyRecommendations: number;
  lastResetDate: string;
  metrics: PortfolioRiskMetrics;
  symbols: string[];
  setLimits: (l: RiskLimits) => void;
  checkTrade: (card: TradeCardData, proposedContracts: number) => RiskCheckResult;
  incrementDaily: () => void;
  computeMetrics: (positions: PortfolioPosition[]) => void;
}

export const useRiskStore = create<RiskState>()(
  persist(
    (set, get) => ({
      limits: { ...DEFAULT_LIMITS },
      dailyRecommendations: 0,
      lastResetDate: new Date().toISOString().split('T')[0],
      metrics: { ...DEFAULT_METRICS },
      symbols: [],
      setLimits: (l) => set({ limits: l }),
      checkTrade: (card, proposedContracts) => {
        const { limits, metrics, symbols } = get();
        const reasons: string[] = [];
        const mid = card.contractDetails?.mid ?? 0;
        const notional = mid * proposedContracts * 100;
        const portfolioValue = limits.portfolioValue || 1;
        const singleExposurePct = notional / portfolioValue;
        const currentTotalNotional = metrics.totalExposurePct * portfolioValue;
        const totalExposurePct = (currentTotalNotional + notional) / portfolioValue;
        const capitalAtRisk = notional;

        if (!hasInvalidation(card.exit.invalidation)) {
          reasons.push('missing_invalidation');
        }
        if (symbols.includes(card.symbol)) {
          reasons.push('duplicate_symbol');
        }
        if (metrics.concurrentPositions >= limits.maxConcurrentPositions) {
          reasons.push('max_concurrent_positions_reached');
        }
        if (singleExposurePct > limits.maxSingleTradeExposurePct) {
          reasons.push('single_trade_exposure_too_high');
        }
        if (totalExposurePct > limits.maxTotalExposurePct) {
          reasons.push('total_exposure_limit_reached');
        }
        if (metrics.dailyRecommendations >= limits.maxDailyRecommendations) {
          reasons.push('max_daily_recommendations_reached');
        }

        return {
          approved: reasons.length === 0,
          reasons,
          singleExposurePct,
          totalExposurePct,
          capitalAtRisk,
        };
      },
      incrementDaily: () => {
        const today = new Date().toISOString().split('T')[0];
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
          const notional = p.currentPrice * 100 * (p.contracts ?? 1);
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
          concurrentPositions > limits.maxConcurrentPositions
            ? 'REJECT'
            : concurrentPositions > limits.maxConcurrentPositions * 0.8
              ? 'CAUTION'
              : 'PASS'
        );
        statuses.push(
          dailyRecommendations > limits.maxDailyRecommendations
            ? 'REJECT'
            : dailyRecommendations > limits.maxDailyRecommendations * 0.8
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
      partialize: (state) => ({
        limits: state.limits,
        dailyRecommendations: state.dailyRecommendations,
        lastResetDate: state.lastResetDate,
      }),
    }
  )
);
