/*
 * Watchlist mock fixtures — Phase 5. Swapped for real `fetch()` later.
 * Shapes match `types/domain.ts`.
 */

import type { WatchlistRow } from '@/types/domain';
import { statusForScore } from '@/lib/status';

function row(partial: Omit<WatchlistRow, 'status'>): WatchlistRow {
  return { ...partial, status: statusForScore(partial.score) };
}

export const MOCK_WATCHLIST: WatchlistRow[] = [
  row({
    symbol: 'AAPL', company: 'Apple Inc', price: 185.20,
    direction: 'Bullish', horizon: 'Swing', score: 82, rankDelta: 2, scoreDelta: 3,
    breakdown: { trend: 88, pullback: 78, trigger: 85, event: 72, volatility: 74 },
    nextEventDays: 14, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'NVDA', company: 'NVIDIA Corp', price: 903.10,
    direction: 'Bullish', horizon: 'Swing', score: 79, rankDelta: 1, scoreDelta: -2,
    breakdown: { trend: 92, pullback: 62, trigger: 80, event: 70, volatility: 71 },
    nextEventDays: 3, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'MSFT', company: 'Microsoft Corp', price: 417.50,
    direction: 'Bullish', horizon: 'Position', score: 74, rankDelta: 0, scoreDelta: 0,
    breakdown: { trend: 82, pullback: 70, trigger: 68, event: 78, volatility: 70 },
    nextEventDays: 21, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'META', company: 'Meta Platforms', price: 512.80,
    direction: 'Bullish', horizon: 'Swing', score: 71, rankDelta: -1, scoreDelta: 1,
    breakdown: { trend: 78, pullback: 68, trigger: 70, event: 65, volatility: 74 },
    nextEventDays: 10, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'GOOGL', company: 'Alphabet Inc', price: 156.20,
    direction: 'Bullish', horizon: 'Swing', score: 68, rankDelta: 1, scoreDelta: -4,
    breakdown: { trend: 72, pullback: 66, trigger: 64, event: 68, volatility: 70 },
    nextEventDays: 9, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'AMZN', company: 'Amazon.com Inc', price: 184.30,
    direction: 'Bullish', horizon: 'Position', score: 64, rankDelta: 0, scoreDelta: 2,
    breakdown: { trend: 66, pullback: 62, trigger: 60, event: 66, volatility: 66 },
    nextEventDays: 16, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'AMD', company: 'Adv Micro Devices', price: 158.40,
    direction: 'Bullish', horizon: 'Swing', score: 61, rankDelta: 2, scoreDelta: 5,
    breakdown: { trend: 68, pullback: 55, trigger: 60, event: 62, volatility: 60 },
    nextEventDays: 11, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'TSLA', company: 'Tesla Inc', price: 172.90,
    direction: 'Bearish', horizon: 'Swing', score: 55, rankDelta: -2, scoreDelta: -3,
    breakdown: { trend: 44, pullback: 60, trigger: 55, event: 58, volatility: 58 },
    nextEventDays: 2, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'NFLX', company: 'Netflix Inc', price: 610.20,
    direction: 'Bullish', horizon: 'Position', score: 52, rankDelta: 0, scoreDelta: 0,
    breakdown: { trend: 58, pullback: 48, trigger: 50, event: 54, volatility: 50 },
    nextEventDays: 8, nextEventLabel: 'Earnings',
  }),
  row({
    symbol: 'INTC', company: 'Intel Corp', price: 35.10,
    direction: 'Bearish', horizon: 'Position', score: 42, rankDelta: -3, scoreDelta: -6,
    breakdown: { trend: 30, pullback: 48, trigger: 40, event: 50, volatility: 42 },
    nextEventDays: 19, nextEventLabel: 'Earnings',
  }),
];
