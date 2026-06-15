import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData,
              MarketRegime, SectorTile, OptionContract, NewsItem } from '@/types/domain';
import type { StockScanResult } from '@/types/stockDomain';
import type { OptionsPipeline } from '@/lib/scanStore';
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

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
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
  status: 'connected' | 'degraded' | 'down' | 'unconfigured';
  provides: string[];
  detail: string | null;
}

export interface StrategyWatchState {
  phase: 'idle' | 'armed';
  direction: 'Bullish' | 'Bearish' | null;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  last_event: 'entry' | 'exit_stop' | 'exit_target' | 'reversal' | null;
  last_event_at: string | null;
}

export interface StrategyWatch {
  id: string;
  symbol: string;
  strategy_key: string;
  params_override: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  last_state: StrategyWatchState;
}

export interface StrategyWatchSchedule {
  enabled: boolean;
  mode: 'eod' | 'poll';
  eod_time: string;
  poll_hours: number;
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
    filters?: {
      min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number;
      confidence_caution_below?: number; confidence_reject_below?: number;
    },
    overrides?: Record<string, number | boolean | string>,
  ) =>
    post<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[]; pipeline?: OptionsPipeline }>(
      '/api/scan',
      { universe, direction, horizon, overrides: overrides ?? {}, ...filters },
    ),

  postStockScan: (req: {
    universe: string[]; direction: string; horizon: string;
    strategy: string; symbols?: string[];
    pullback_tolerance_pct?: number;
    pullback_ema_period?: number;
    pullback_trend_ema?: number;
    pullback_ma_type?: 'EMA' | 'SMA';
    pullback_require_reversal?: boolean;
    ma_crossover_fast?: number;
    ma_crossover_slow?: number;
    ma_crossover_lookback?: number;
    breakout_volume_mult?: number;
    rsi_period?: number;
    rsi_oversold?: number;
    rsi_trend_sma?: number;
    account_size?: number; risk_pct?: number;
    risk_fixed_usd?: number; bt_min_trades?: number; bt_min_win_rate?: number;
    min_price?: number; max_price?: number;
    shortlist_max_candidates?: number;
  }) => post<StockScanResult>('/api/stock-scan', req),

  postStockOrder: (req: {
    broker: string; symbol: string; action: 'BUY' | 'SELL';
    quantity: number; order_type: 'MKT' | 'LMT';
    limit_price: number | null; tif: 'DAY' | 'GTC';
  }) => post<{ order_id: string; status: string; broker: string }>('/broker/stock-order', req),

  postOptionOrder: (req: {
    broker: string; symbol: string; option_symbol: string;
    action: 'BUY' | 'SELL'; quantity: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null;
    tif: 'DAY' | 'GTC'; conid?: number;
  }) => post<{ order_id: string; status: string; broker: string }>('/broker/option-order', req),

  armAutoTrade: (req: {
    broker: string; symbol: string; option_symbol: string;
    action: 'BUY' | 'SELL'; quantity: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null; conid?: number;
  }) => post<{ armed: boolean }>('/auto-trade/arm', req),

  disarmAutoTrade: () => del('/auto-trade/arm'),

  fireAutoTrade: () =>
    post<{ order_id: string; status: string }>('/auto-trade/fire', {}),

  getAutoTradeStatus: () =>
    get<{ armed: boolean; symbol: string | null; option: string | null; last_order: unknown }>('/auto-trade/status'),

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

  postCredentials: (key: string, values: Record<string, string>) =>
    post<{ ok: boolean; key: string }>('/settings/credentials', { key, values }),

  getBrokerStatus: () =>
    get<{
      ibkr_paper:    { configured: boolean };
      tradier_paper: { configured: boolean };
      ibkr_live:     { configured: boolean; enabled: boolean; note: string };
      alpaca_paper:  { configured: boolean };
    }>('/broker/status'),

  startHistoryPrefetch: (req: {
    universe: string[];
    years?: number;
    delay_secs?: number;
  }) => post<{ message: string; total: number }>('/api/historical-data/prefetch', req),

  getHistoryPrefetchStatus: () =>
    get<{
      status: 'idle' | 'running' | 'completed' | 'error';
      total: number;
      done: number;
      failed: number;
      current_symbol: string | null;
      elapsed_secs: number;
      started_at: string | null;
    }>('/api/historical-data/prefetch/status'),

  getStrategyWatches: () =>
    get<StrategyWatch[]>('/api/strategy-watch/'),
  addStrategyWatch: (symbol: string, strategy_key: string) =>
    post<StrategyWatch>('/api/strategy-watch/', { symbol, strategy_key }),
  addStrategyWatchesBulk: (symbols: string[], strategy_key: string) =>
    post<{ added: number; watches: StrategyWatch[] }>('/api/strategy-watch/bulk', { symbols, strategy_key }),
  removeStrategyWatch: (id: string) =>
    del(`/api/strategy-watch/${id}`),
  setStrategyWatchEnabled: (id: string, enabled: boolean) =>
    patch<{ id: string; enabled: boolean }>(`/api/strategy-watch/${id}`, { enabled }),
  getStrategyWatchSchedule: () =>
    get<StrategyWatchSchedule>('/api/strategy-watch/schedule'),
  setStrategyWatchSchedule: (cfg: StrategyWatchSchedule) =>
    put<StrategyWatchSchedule>('/api/strategy-watch/schedule', cfg),
  evaluateStrategyWatches: () =>
    post<{ fired: number; events: unknown[] }>('/api/strategy-watch/evaluate', {}),
  getStrategyWatchStatus: () =>
    get<{ running: boolean; last_run_at: string | null; mode: string; enabled: boolean }>('/api/strategy-watch/status'),
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

/* ---------- Ingestion schedule ---------- */

export interface IngestionSchedule {
  enabled: boolean;
  time: string;       // "HH:MM"
  next_run: string | null;
}

export async function getIngestionSchedule(): Promise<IngestionSchedule> {
  return get<IngestionSchedule>('/api/data/ingest/schedule');
}

export async function saveIngestionSchedule(s: Pick<IngestionSchedule, 'enabled' | 'time'>): Promise<IngestionSchedule> {
  return post<IngestionSchedule>('/api/data/ingest/schedule', s);
}

export async function triggerIngestionNow(symbols: string[], years = 6): Promise<{ status: string; total: number }> {
  return post<{ status: string; total: number }>('/api/data/ingest', { symbols, years });
}

export async function getLastDataRefresh(): Promise<{ last_refresh: string | null }> {
  return get<{ last_refresh: string | null }>('/api/data/ingest/last-refresh');
}

/* ---------- Walk-Forward Optimization ---------- */

export interface WfoVerdict {
  in_sample_return: number;
  walk_forward_return: number;
  degradation_pct: number;
}

export interface WfoOosMetrics {
  sharpe: number;
  expectancy: number;
  win_rate: number;
  total_return: number;
  max_drawdown: number;
  n_trades: number;
}

export interface WfoProposal {
  strategy: string;
  proposed: Record<string, number | string>;
  consistency: number;
  eligible: boolean;
  oos_metrics: WfoOosMetrics;
  fold_winners: Record<string, number | string>[];
  verdict: WfoVerdict;
  recommendation: string;
}

export interface TuningJob {
  status: 'running' | 'completed' | 'failed';
  done: number;
  total: number;
  proposals: Record<string, WfoProposal>;
  error?: string;
}

export async function startTuningJob(): Promise<{ job_id: string }> {
  return post('/api/strategy-tuning/run', {});
}

export async function getTuningJob(jobId: string): Promise<TuningJob> {
  return get(`/api/strategy-tuning/jobs/${jobId}`);
}

export async function adoptStrategyParams(strategy: string, params: Record<string, number | string>): Promise<{ ok: boolean; active: Record<string, number | string> }> {
  return post('/api/strategy-tuning/adopt', { strategy, params });
}
