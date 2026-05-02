import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData } from '@/types/domain';
import type { MarketRegime } from '@/mocks/regime';
import type { SectorTile } from '@/mocks/sectors';
import type { OptionContract } from '@/mocks/contracts';
import type { Candle } from '@/types/chart';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import { MOCK_ALERTS } from '@/mocks/alerts';
import { MOCK_REGIME } from '@/mocks/regime';
import { MOCK_SECTORS } from '@/mocks/sectors';
import { MOCK_EVENTS } from '@/mocks/events';
import { MOCK_CONTRACTS } from '@/mocks/contracts';
import { MOCK_CANDIDATE_CARDS } from '@/mocks/tradecards';
import { candlesFor } from '@/mocks/candles';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist').catch(() => MOCK_WATCHLIST),
  getPortfolio:  () => get<PortfolioPosition[]>('/api/portfolio').catch(() => MOCK_PORTFOLIO),
  getAlerts:     () => get<AlertItem[]>('/api/alerts').catch(() => MOCK_ALERTS),
  getRegime:     () => get<MarketRegime>('/api/regime').catch(() => MOCK_REGIME),
  getSectors:    () => get<SectorTile[]>('/api/sectors').catch(() => MOCK_SECTORS),
  getEvents:     () => get<UpcomingEvent[]>('/api/events').catch(() => MOCK_EVENTS),
  getContracts:  () => get<OptionContract[]>('/api/contracts').catch(() => MOCK_CONTRACTS),
  getTradecards: () => get<TradeCardData[]>('/api/tradecards').catch(() => MOCK_CANDIDATE_CARDS),
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`).catch(() => candlesFor(symbol)),
};
