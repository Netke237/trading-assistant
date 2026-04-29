import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData } from '@/types/domain';
import type { MarketRegime } from '@/mocks/regime';
import type { SectorTile } from '@/mocks/sectors';
import type { OptionContract } from '@/mocks/contracts';
import type { Candle } from '@/types/chart';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist'),
  getPortfolio:  () => get<PortfolioPosition[]>('/api/portfolio'),
  getAlerts:     () => get<AlertItem[]>('/api/alerts'),
  getRegime:     () => get<MarketRegime>('/api/regime'),
  getSectors:    () => get<SectorTile[]>('/api/sectors'),
  getEvents:     () => get<UpcomingEvent[]>('/api/events'),
  getContracts:  () => get<OptionContract[]>('/api/contracts'),
  getTradecards: () => get<TradeCardData[]>('/api/tradecards'),
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`),
};
