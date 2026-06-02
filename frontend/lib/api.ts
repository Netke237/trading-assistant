import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData,
              MarketRegime, SectorTile, OptionContract, NewsItem } from '@/types/domain';
import type { Candle } from '@/types/chart';
import type { AlertRule, AlertHistory } from '@/types/alerts';

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

export interface DataSourceInfo {
  id: string;
  label: string;
  status: 'ok' | 'unavailable' | 'error' | 'unconfigured';
  provides: string[];
  detail: string | null;
}

export const api = {
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist'),
  getPortfolio:  () => get<PortfolioPosition[]>('/api/portfolio'),
  getAlerts:     () => get<AlertItem[]>('/api/alerts'),
  getRegime: (
    horizon?: string,
    markov?: { lookback?: number; threshold?: number; smoothing?: number },
  ) => {
    const params = new URLSearchParams();
    if (horizon)                   params.set('horizon',   horizon);
    if (markov?.lookback  != null) params.set('lookback',  String(markov.lookback));
    if (markov?.threshold != null) params.set('threshold', String(markov.threshold));
    if (markov?.smoothing != null) params.set('smoothing', String(markov.smoothing));
    const qs = params.toString();
    return get<MarketRegime>(`/api/regime${qs ? `?${qs}` : ''}`);
  },
  getSectors:    () => get<SectorTile[]>('/api/sectors'),
  getDataSources: () => get<DataSourceInfo[]>('/api/data-sources'),
  getEvents:     () => get<UpcomingEvent[]>('/api/events'),
  getContracts: (
    symbol: string,
    right: 'C' | 'P' = 'C',
    ctx?: { stock_score?: number; direction?: string; horizon?: string; limit?: number; max_price?: number }
  ) => get<OptionContract[]>(
    `/api/contracts?symbol=${encodeURIComponent(symbol)}&right=${right}` +
    (ctx?.stock_score != null ? `&stock_score=${ctx.stock_score}` : '') +
    (ctx?.direction ? `&direction=${encodeURIComponent(ctx.direction)}` : '') +
    (ctx?.horizon ? `&horizon=${encodeURIComponent(ctx.horizon)}` : '') +
    (ctx?.limit != null ? `&limit=${ctx.limit}` : '') +
    (ctx?.max_price != null ? `&max_price=${ctx.max_price}` : '')
  ),
  getTradecards: () => get<TradeCardData[]>('/api/tradecards'),
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`),
  getNews:         (symbols: string[]) => get<NewsItem[]>(`/api/news?symbols=${symbols.join(',')}`),
  addWatchlist:    (symbol: string) => post<{ symbol: string }>('/api/watchlist', { symbol }),
  removeWatchlist: (symbol: string) => del(`/api/watchlist/${encodeURIComponent(symbol)}`),
  getWatchedContracts:    () => get<string[]>('/api/watched-contracts'),
  addWatchedContract:     (contractId: string) => post<{ contract_id: string }>('/api/watched-contracts', { contract_id: contractId }),
  removeWatchedContract:  (contractId: string) => del(`/api/watched-contracts/${encodeURIComponent(contractId)}`),
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

  // Phase 4: Chart alert CRUD
  createAlertRule: (body: {
    name: string; symbol: string; interval: string; enabled: boolean;
    group: { logic: string; conditions: unknown[] };
    cooldown_minutes: number; expiry_date: string | null;
  }) => post<AlertRule>('/alerts/rules', body),

  getAlertRules: (symbol?: string) => {
    const qs = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
    return get<AlertRule[]>(`/alerts/rules${qs}`);
  },

  deleteAlertRule: (id: string) => del(`/alerts/rules/${encodeURIComponent(id)}`),

  getAlertHistory: (params?: { symbol?: string; interval?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.symbol) sp.set('symbol', params.symbol);
    if (params?.interval) sp.set('interval', params.interval);
    if (params?.limit) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    return get<AlertHistory[]>(`/alerts/history${qs ? `?${qs}` : ''}`);
  },

  dismissAlertHistory: (id: string) => del(`/alerts/history/${encodeURIComponent(id)}`),

  testAlertRule: (ruleId: string, body: { candles: Candle[]; indicators?: Record<string, unknown>; signals?: unknown[] }) =>
    post<{ matches: unknown[] }>(`/alerts/rules/${encodeURIComponent(ruleId)}/test`, body),

  testNotification: (channel: 'gmail' | 'telegram') =>
    post<{ status: string }>('/alerts/notifications/test', { channel }),
};

/* ---------- Risk settings ---------- */

export interface RiskSettings {
  premiumStopPct: number;
}

export async function getRiskSettings(): Promise<RiskSettings> {
  return get<RiskSettings>('/settings/risk');
}

export async function saveRiskSettings(s: RiskSettings): Promise<void> {
  await post<unknown>('/settings/risk', s);
}

/* ---------- History retention ---------- */

export interface HistoryRetention {
  historyRetentionYears: number;
}

export async function getHistoryRetention(): Promise<HistoryRetention> {
  return get<HistoryRetention>('/settings/history-retention');
}

export async function saveHistoryRetention(s: HistoryRetention): Promise<void> {
  await post<unknown>('/settings/history-retention', s);
}

export async function clearAllHistory(): Promise<void> {
  await del('/api/portfolio/history');
}
