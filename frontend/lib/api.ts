import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData,
              MarketRegime, SectorTile, OptionContract, NewsItem } from '@/types/domain';
import type { Candle } from '@/types/chart';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE_URL}${path}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
}

export const api = {
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist'),
  getPortfolio:  () => get<PortfolioPosition[]>('/api/portfolio'),
  getAlerts:     () => get<AlertItem[]>('/api/alerts'),
  getRegime:     () => get<MarketRegime>('/api/regime'),
  getSectors:    () => get<SectorTile[]>('/api/sectors'),
  getEvents:     () => get<UpcomingEvent[]>('/api/events'),
  getContracts:  (symbol?: string) =>
    get<OptionContract[]>(`/api/contracts${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),
  getTradecards: () => get<TradeCardData[]>('/api/tradecards'),
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`),
  getNews:         (symbols: string[]) => get<NewsItem[]>(`/api/news?symbols=${symbols.join(',')}`),
  addWatchlist:    (symbol: string) => post<{ symbol: string }>('/api/watchlist', { symbol }),
  removeWatchlist: (symbol: string) => del(`/api/watchlist/${encodeURIComponent(symbol)}`),
  postScan: (
    universe: string[],
    direction: string,
    horizon: string,
    filters?: { min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number },
    overrides?: Record<string, number | boolean | string>,
  ) =>
    post<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[] }>(
      '/api/scan',
      { universe, direction, horizon, overrides: overrides ?? {}, ...filters },
    ),
};
