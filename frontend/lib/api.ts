import type { BacktestArtifact, OriginalBacktestUnavailableReason } from '@/types/backtest';
import { useScanReportUpdates, type LatestScanReport, type ScanReport, type ScanReportCategory, type ScanReportMetadata } from './scanReports';
import type { WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent, TradeCardData,
              MarketRegime, SectorTile, IndexChangeTile, OptionContract, NewsItem, DteWindow, ExitPlan, BarrierRace, StopCostOut, FinalStop,
              PickedMethod, PickedStopBasis, Direction, TargetLevel, MaxLossOverride,
              ContractGrading, StockExplanation } from '@/types/domain';
import type { StockScanResult, StockFirstPassageEstimate, StockExitPlan, PreBreakoutResultRow, FibPullbackResultRow } from '@/types/stockDomain';
import type { OptionsPipeline, ScanResult, ScanSessionStatus } from '@/lib/scanStore';
import type { Candle } from '@/types/chart';
import { validationMessages } from '@/lib/pydanticError';
import type { AlertRule, AlertHistory } from '@/types/alerts';
import type { JournalEntry, JournalEntryInput, JournalEntryFilters } from '@/types/journal';
import type { OptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import type { StockScanRequestBody } from '@/lib/resolveStockScanRequest';
import type { ScoringHorizon, TunedHorizon } from '@/lib/horizonPresets';

// ── Part 3: profile-based scan schedule entries ────────────────────────────
// Mirrors backend/app/schemas/scan_schedule.py's ScanScheduleEntry.
/** O4 step 6 — the ten booking fields `POST /auto-trade/arm` carries so a
 *  fired auto-trade can book its PortfolioPosition (backend `ArmRequest`, O4
 *  step 3). ONE declaration, used twice: `armAutoTrade`'s request type takes it
 *  as optional keys, and `armBookingFieldsFrom` (lib/armBookingFields.ts)
 *  returns it with every key required. A misspelled key in that mapping is
 *  therefore an excess-property error in `tsc`. Since P6 the endpoint also
 *  has `extra='forbid'`, so a key that slips past `tsc` is a 422 at arm
 *  rather than a silent drop with a 200.
 *
 *  snake_case, like every other key on this endpoint. Nested objects
 *  (`exit_plan`, `targets`, ...) travel verbatim, as `POST /api/portfolio`
 *  sends them. */
export interface ArmBookingFields {
  stop: number | null;
  /** Never null: the booking re-anchors `stop` by (live - scan_stock_price)
   *  unless this is true, so "unknown" would shift a typed stop. */
  stop_is_user_set: boolean;
  scan_stock_price: number | null;
  structural_stop: number | null;
  exit_plan: ExitPlan | null;
  /** `[]`, never null: the backend field is a list, not Optional. */
  targets: TargetLevel[];
  dte_total: number | null;
  premium_stop_dollar: number | null;
  max_loss_override: MaxLossOverride | null;
  trade_card_snapshot: Record<string, unknown> | null;
}

/** What `POST /auto-trade/fire` returns once the order went through (always
 *  200 then, whatever the booking did -- O4 steps 4+5). The four booking keys
 *  are OPTIONAL: a backend predating them omits them, and `undefined` means
 *  "not reported", never "not booked". Read `booked === false`, not `!booked`. */
export interface FireAutoTradeResult {
  order_id: string;
  status: string;
  broker: string;
  booked?: boolean;
  rec_id?: string | null;
  book_error?: string | null;
  over_exposure?: boolean;
}

export interface ScanScheduleEntry {
  id: string;
  label: string;
  mode: 'options' | 'stocks';
  profile_id: string;
  profile_name: string;
  profile_synced_at: string;
  resolved_request: OptionsScanRequestBody | StockScanRequestBody;
  pattern: 'fixed_time' | 'loop';
  enabled: boolean;
  days_of_week: number[];
  fire_time?: string | null;
  cadence_minutes?: number | null;
  window_start_hour?: number | null;
  window_end_hour?: number | null;
}

export type ScanScheduleEntryInput = Omit<ScanScheduleEntry, 'id'>;

export interface ScanScheduleRun {
  id: string;
  schedule_entry_id: string;
  mode: 'options' | 'stocks';
  fired_at: string;
  status: 'success' | 'error';
  error: string | null;
  candidate_count: number | null;
}

/** Where every call in this module goes. Exported because a caller that has
 *  to TELL the user the backend could not be reached (lib/stockScan.ts) must
 *  name the address it actually tried — the old hardcoded "port 8000" hint
 *  was a lie in any deployment that sets NEXT_PUBLIC_API_URL. */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const BASE_URL = API_BASE_URL;

async function apiError(path: string, res: Response): Promise<never> {
  const text = await res.text().catch(() => '');
  let detail = text;
  try {
    const json = JSON.parse(text);
    if (typeof json?.detail === 'string') {
      detail = json.detail;
    } else if (Array.isArray(json?.detail)) {
      // FastAPI/Pydantic validation errors (e.g. a 422 on a Field(..., gt=0)
      // violation) shape `detail` as a list of {loc, msg, type} objects, not a
      // string — the `typeof === 'string'` check above misses this shape
      // entirely and used to fall through to the raw JSON text, dumping a
      // machine-formatted validation payload straight into a caller's error UI.
      //
      // Each message is prefixed with its field (see lib/pydanticError.ts).
      // Without that, two fields failing the same check render the identical
      // sentence twice naming neither, and pydantic's message for a MISSING
      // required field is the bare "Field required" — which is what a stale
      // client posting an arm body without `direction` produces, and the
      // rollout note in routers/auto_trade.py calls that failure "loud".
      detail = validationMessages(json.detail) ?? text;
    }
  } catch { /* not JSON — use raw text */ }
  throw new Error(`API ${path} → ${res.status}${detail ? `: ${detail}` : ''}`);
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { signal });
  if (!res.ok) return apiError(path, res);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal, onReport?: (metadata: ScanReportMetadata) => void): Promise<T> {
  const category: ScanReportCategory | null = path === '/api/scan' ? 'options' : path === '/api/stock-scan' ? ((body as {category?: 'stocks' | 'pullback'}).category ?? 'stocks') : path === '/api/scan/prebreakout' ? 'prebreakout' : path === '/api/scan/fib-pullback' ? 'fib' : null;
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  const runId = res.headers?.get('X-Scan-Report-Run-Id');
  const generationHeader = res.headers?.get('X-Scan-Report-Generation');
  const generation = generationHeader == null ? NaN : Number(generationHeader);
  if (!res.ok) {
    if (category && runId && Number.isSafeInteger(generation) && generation > 0) useScanReportUpdates.getState().record(category, {run_id:runId,generation,persistence:res.headers.get('X-Scan-Report-Persistence') ?? 'unavailable',failed:true});
    return apiError(path, res);
  }
  const value = await res.json();
  const id = value?.report_run_id ?? runId;
  const gen = value?.report_generation ?? generation;
  if (category && id && Number.isSafeInteger(gen) && gen > 0) {
    const metadata = {run_id:id,generation:gen,persistence:value?.report_persistence ?? res.headers?.get('X-Scan-Report-Persistence') ?? 'unavailable',accepted_symbols:(Array.isArray(value) ? value : value?.candidates ?? []).map((row: {symbol?:unknown})=>row.symbol).filter((symbol:unknown): symbol is string => typeof symbol==='string' && /^[A-Z][A-Z0-9.\-]{0,10}$/.test(symbol)),pipeline_counts:value?.pipeline ? Object.fromEntries(Object.entries(value.pipeline).filter((entry): entry is [string,number] => ['scanned','candidates','failed_data','failed_pre_screen','no_chain','failed_score','failed_contracts','other_rejected','failed_direction','failed_shortlist','failed_direction_unmeasured','direction_min_trend','failed_history','failed_regime','failed_signal','failed_backtest'].includes(entry[0]) && typeof entry[1]==='number' && Number.isFinite(entry[1]))) : undefined};
    useScanReportUpdates.getState().record(category, metadata);
    onReport?.(metadata);
  }
  return value as T;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) return apiError(path, res);
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) return apiError(path, res);
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE_URL}${path}`, { method: 'DELETE' });
  if (!res.ok) return apiError(path, res);
}

export interface DataSourceInfo {
  id: string;
  label: string;
  status: 'connected' | 'degraded' | 'down' | 'unconfigured';
  provides: string[];
  detail: string | null;
}

export interface SymbolNote {
  symbol: string;
  body: string;
  updatedAt: string | null;
}

export interface StrategyWatchState {
  phase: 'idle' | 'armed';
  direction: 'Bullish' | 'Bearish' | null;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  last_event: 'entry' | 'time_stop' | 'exit_stop' | 'exit_target' | 'reversal' | null;
  last_event_at: string | null;
}

export interface StrategyWatch {
  id: string;
  symbol: string;
  strategy_key: string;
  direction: 'Bullish' | 'Bearish';
  params_override: Record<string, unknown>;
  /** STOCKS-HORIZON-T1 H7: the tuned horizon whose profile the watch reads and
   *  whose hold time-stops it. Absent/null on a watch without a horizon. */
  params_horizon?: TunedHorizon | null;
  hold_max_days?: number | null;
  enabled: boolean;
  created_at: string;
  last_state: StrategyWatchState;
}

export interface CompositeWatch {
  id: string;
  watch_type: 'composite';
  symbol: string;
  direction: string;
  interval: string;
  trigger_def: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  last_state: Record<string, unknown>;
}

export interface CompositeWatchDefaults {
  conviction_min: number;
  p_transition_min: number;
  p_stay_min: number;
  min_confirmations: number;
}

export interface SymbolRegimeSnapshot {
  model: string;
  state: string;
  p_stay: number;
  conviction_pct?: number;
  conviction_label?: string;
  p_transition?: { to: string; prob: number }[];
}

export interface StrategyWatchSchedule {
  enabled: boolean;
  mode: 'eod' | 'poll';
  eod_time: string;
  poll_hours: number;
  sustain_minutes: number;
}

export interface AnalysisStrategySignal {
  strategy: string;
  entry_price: number;
  stop_price: number;
  target_price: number;
  rr_ratio: number;
  atr: number;
  detail: Record<string, unknown>;
}

export interface AnalysisBacktest {
  n_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  expectancy: number;
  sharpe: number;
  confidence: number | null;
  passes_gate: boolean;
  summary_text: string;
  n_time_exits?: number | null;
  hold_max_days?: number | null;
}

export interface AnalysisSentiment {
  horizon: string;
  timeframe: string;
  state: string;
  p_stay: number;
  stability: string;
  regime_age_days: number;
  avg_regime_duration: number;
  conviction_pct: number;
  conviction_label: string;
  interpretation: string;
  hmm_state: string | null;
  alignment: string;
  insufficient_data: boolean;
}

export interface AnalysisFundamentals {
  score: number;
  quality_label: string;
  risk_label: string;
  growth_score: number;
  quality_score: number;
  risk_score: number;
  safety_flags: string[];
  detail: Record<string, unknown>;
}

export interface RuleContribution {
  name: string;
  status: 'PASS' | 'CAUTION' | 'REJECT';
  score: number;
  detail: Record<string, unknown>;
}

export interface GateFlag {
  gate: string;
  status: 'PASS' | 'CAUTION' | 'REJECT';
  detail: string;
}

export interface EmaTrend {
  state: 'Above' | 'Below';
  ema: number;
  last: number;
  status: string;
}

export interface RegimeHorizonBlock {
  horizon: string;
  timeframe: string;
  state: string;
  p_stay: number;
  stability: string;
  regime_age_days: number;
  avg_regime_duration: number;
  conviction_pct: number;
  conviction_label: string;
  hmm_state: string | null;
  alignment: string;
  transition_row: number[];
  state_order: string[];
  insufficient_data: boolean;
}

export interface SectorTileLite {
  name: string;
  etf: string | null;
  change_pct: number | null;
}

export interface SectorRs {
  benchmark: string;
  d1: number | null;
  w1: number | null;
  m1: number | null;
}

export interface MarketBackdrop {
  overall: string;
  direction: string | null;
  vix: number | null;
}

export interface StockAnalysis {
  symbol: string;
  company: string;
  price: number;
  direction: string;
  stock_score: number;
  stock_explanation?: StockExplanation | null;
  stock_status: 'PASS' | 'CAUTION' | 'REJECT';
  is_index: boolean;
  strategy: AnalysisStrategySignal | null;
  backtest: AnalysisBacktest | null;
  confidence: number | null;
  confidence_text: string | null;
  sentiment: AnalysisSentiment | null;
  fundamentals: AnalysisFundamentals | null;
  next_event_days: number | null;
  next_event_label: string | null;
  /** STOCKS-HORIZON-P0B B6: as on PositionCardData. Optional for a backend
   *  from before B6. */
  earnings_days?: number | null;
  earnings_veto?: boolean;
  rules: RuleContribution[];
  gate_flags: GateFlag[];
  ema_trend: EmaTrend | null;
  iv_rank: number | null;
  regime_by_horizon: Record<string, RegimeHorizonBlock>;
  sector: SectorTileLite | null;
  sector_rs: SectorRs | null;
  market_backdrop: MarketBackdrop | null;
}

/** A5: the stock scan's own request body with `symbol` in place of `universe`,
 *  so this type cannot drift from what the scan sends (the page mirrors the
 *  scan, decision A5-ANALYSIS-MIRRORS-SCAN-2026-09-24). */
export type AnalyzeStockRequest = Omit<StockScanRequestBody, 'universe' | 'horizon'> & {
  symbol: string;
  horizon: 'Intraday' | 'Swing' | 'Position';
};

/** GET /api/stock-scan/last-request — the request behind /stock-scan/last's
 *  result, keyed by its scan_id; null unless the backend's last run completed. */
export interface LastStockScanRequest {
  scan_id: string;
  request: StockScanRequestBody;
}

export class BacktestArtifactError extends Error {
  constructor(public readonly reason: OriginalBacktestUnavailableReason, public readonly status: number) {
    super(`Original backtest unavailable (${reason})`);
    this.name = 'BacktestArtifactError';
  }
}

export const api = {
  getOriginalBacktest: async (artifactId: string, symbol: string, signal?: AbortSignal): Promise<BacktestArtifact> => {
    const res = await fetch(`${BASE_URL}/api/backtest-artifacts/${encodeURIComponent(artifactId)}?symbol=${encodeURIComponent(symbol)}`, {signal});
    if (!res.ok) {
      const reason = res.status === 404 ? 'missing' : res.status === 410 ? 'expired' : res.status === 422 ? 'invalid_input' : res.status === 503 ? 'storage_unavailable' : 'failed';
      throw new BacktestArtifactError(reason, res.status);
    }
    return res.json() as Promise<BacktestArtifact>;
  },
  getWatchlist:  () => get<WatchlistRow[]>('/api/watchlist'),
  getPortfolio:  () => get<PortfolioPosition[]>('/api/portfolio'),
  /** Hard DELETE of one tracked row by rec_id (204; 404 when absent). A plain
   *  `del`, so a non-2xx throws; only Step 7 reads a `→ 404` as already gone. */
  deletePortfolioPosition: (recId: string) => del(`/api/portfolio/${encodeURIComponent(recId)}`),
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
  getSectors:       () => get<SectorTile[]>('/api/sectors'),
  getIndexChanges:  () => get<IndexChangeTile[]>('/api/index-changes'),
  getDataSources: () => get<DataSourceInfo[]>('/api/data-sources'),
  getEvents:     () => get<UpcomingEvent[]>('/api/events'),
  getContracts: (
    symbol: string,
    right: 'C' | 'P' = 'C',
    ctx?: { stock_score?: number; direction?: string; horizon?: string; limit?: number; max_price?: number;
            hold_min_days?: number; hold_max_days?: number;
            /** The scan's ScanResult.contract_rules. Absent = contract_rules.yaml. */
            contract_rules?: Record<string, number>;
            /** One expiry's chain, filtered to it (the Watchlist's starred expiry). */
            expiry?: string;
            /** Only these strikes; the backend then applies neither `limit` nor `max_price`. */
            strikes?: number[] },
    signal?: AbortSignal,
  ) => get<OptionContract[]>(
    `/api/contracts?symbol=${encodeURIComponent(symbol)}&right=${right}` +
    (ctx?.stock_score != null ? `&stock_score=${ctx.stock_score}` : '') +
    (ctx?.direction ? `&direction=${encodeURIComponent(ctx.direction)}` : '') +
    (ctx?.horizon ? `&horizon=${encodeURIComponent(ctx.horizon)}` : '') +
    (ctx?.limit != null ? `&limit=${ctx.limit}` : '') +
    (ctx?.max_price != null ? `&max_price=${ctx.max_price}` : '') +
    (ctx?.hold_min_days != null ? `&hold_min_days=${ctx.hold_min_days}` : '') +
    (ctx?.hold_max_days != null ? `&hold_max_days=${ctx.hold_max_days}` : '') +
    (ctx?.contract_rules && Object.keys(ctx.contract_rules).length > 0
      ? `&contract_rules=${encodeURIComponent(JSON.stringify(ctx.contract_rules))}` : '') +
    (ctx?.expiry ? `&expiry=${encodeURIComponent(ctx.expiry)}` : '') +
    (ctx?.strikes && ctx.strikes.length > 0 ? `&strikes=${encodeURIComponent(ctx.strikes.join(','))}` : ''),
    signal,
  ),
  getTradecards: () => get<TradeCardData[]>('/api/tradecards'),
  getContractQuote: (symbol: string, strike: number, expiry: string, right: 'C' | 'P', signal?: AbortSignal) =>
    // `ivRank` is a percentile and is null unless IBKR/tastytrade answered;
    // the absolute level rides in `iv`. Resolve via lib/ivBasis.ts.
    get<{ price: number; delta: number; theta: number; ivRank: number | null; iv: number | null; spread: number; volume: number; quoteLive?: boolean | null; quoteState?: string | null }>(
      `/api/quote/option?symbol=${encodeURIComponent(symbol)}&strike=${strike}&expiry=${encodeURIComponent(expiry)}&right=${right}`,
      signal,
    ),
  getStockQuote: (symbol: string, signal?: AbortSignal) =>
    get<{ symbol: string; price: number }>(`/api/quote/stock?symbol=${encodeURIComponent(symbol)}`, signal),
  /** Recompute Entry/Exit/RR/targets for a user-selected contract (Step 6 override). */
  recomputePlan: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    stock_price: number;
    strike: number;
    dte: number;
    premium: number;
    delta: number;
    spread: number;
    quote_live?: boolean | null;
    rr_target_r_multiple?: number;
    target_stock_price?: number;
    target_source?: TradeCardData['exit']['targetSource'];
    rr_bullish_invalidation_pct?: number;
    rr_bearish_invalidation_pct?: number;
    /** Feed the reprice-horizon fallback behind the Fixed % Ladder. Same field,
     *  same meaning and the same "omitted means Swing" default as
     *  getFirstPassageEstimate's — a Step-6 contract override must not reprice
     *  the ladder at a different horizon from the Monte Carlo card beside it. */
    horizon_preset?: string;
    hold_min?: number;
    hold_max?: number;
    /** PIECE 3 — the stop the card already carries (`exit.finalStop`),
     *  round-tripped so a Step 6 contract override cannot move it. The
     *  endpoint uses its `price` as the plan's stop and echoes the block back;
     *  omitting it makes the endpoint fall back to the flat percentage, which
     *  is correct only for a card that genuinely has no resolved stop. */
    final_stop?: FinalStop | null;
  }, signal?: AbortSignal) =>
    post<{
      entry: TradeCardData['entry'];
      exit: TradeCardData['exit'];
      rrRatio: number;
      rrModel: TradeCardData['rrModel'];
    }>('/api/contracts/recompute-plan', req, signal),
  /** On-demand structural (order block / swing) invalidation lookup — fired by the
   *  trade card's "Check structure" button, or by its "Estimate" button when a
   *  structural stop hasn't been fetched yet for the current candidate. Never fired
   *  automatically on candidate navigation. */
  getStructuralStop: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    stock_price: number;
    /** The contract, for the stop-vs-premium gate. ALL THREE OR NONE — the
     *  endpoint 422s a partial set rather than silently skipping the gate,
     *  because a contract with no verdict reads exactly like an unremarkable
     *  one. Omitted entirely by the stocks-mode card, which has no contract.
     *  The IV is solved from `premium` server-side, so it is not sent. */
    strike?: number;
    dte?: number;
    premium?: number;
    /** Picks the horizon whose pass_max_fraction applies. Omitted means Swing,
     *  the app's own default preset — same convention as the first-passage and
     *  exit-plan requests. */
    horizon_preset?: string;
  }, signal?: AbortSignal) =>
    post<{
      available: boolean;
      price: number | null;
      source: 'order_block' | 'swing_low' | 'swing_high' | null;
      confidence: number | null;
      distancePct: number | null;
      /** Null whenever the gate has no honest answer — no contract sent, no
       *  level found, or the arithmetic refused. "Not computed", never PASS. */
      stopCost?: StopCostOut | null;
    }>('/api/contracts/structural-stop', req, signal),
  /** On-demand Monte Carlo first-passage-time estimate — fired only by the
   *  trade card's "Estimate" button, never automatically. */
  getFirstPassageEstimate: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    stock_price: number;
    strike: number;
    dte: number;
    premium: number;
    delta: number;
    trend_score: number;
    invalidation_price: number;
    t1_pct?: number;
    t2_pct?: number;
    t3_pct?: number;
    /** The barrier race's third barrier. Omitted resolves to risk_rules.yaml's
     *  reward_risk.premium_stop_pct, same as the t*_pct fields. */
    premium_stop_pct?: number;
    /** Feed the reprice-horizon fallback. Omitted means "Swing". */
    horizon_preset?: string;
    hold_min?: number;
    hold_max?: number;
  }, signal?: AbortSignal) =>
    post<{
      targets: { pct: number; stockPrice: number | null; optionPrice: number; probability: number; expectedDays: number | null }[];
      invalidation: { probability: number; expectedDays: number | null };
      race?: BarrierRace | null;
    }>('/api/contracts/first-passage', req, signal),
  /** On-demand exit-plan pipeline compute — fired only by the trade card's/
   *  Portfolio editor's "Compute Exit Plan" button, never automatically. See
   *  docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md. */
  getExitPlan: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    entry_price: number;
    strike: number;
    dte: number;
    premium: number;
    trend_score: number;
    target_r_multiple?: number;
    /** Same meaning as on `getStructuralStop` — the stop-vs-premium gate is
     *  per-horizon and this is where the line comes from. */
    horizon_preset?: string;
  }, signal?: AbortSignal) =>
    // `computedAt` is a client-only field the caller stamps on receipt (see
    // ExitPlan's doc comment) — the endpoint itself is stateless and doesn't
    // return one.
    post<Omit<ExitPlan, 'computedAt'>>('/api/contracts/exit-plan', req, signal),
  /** On-demand Monte Carlo first-passage estimate for a STOCK position's exit
   *  ladder — fired only by the stock position card's "Estimate" button.
   *  `targets` is the ladder the user intends to trade (their edited overlay),
   *  not the pristine strategy signal. */
  getStockFirstPassage: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    horizon: 'Intraday' | 'Swing' | 'Position';
    strategy: string;
    stock_price: number;
    stop_price: number;
    targets: number[];
    trend_score: number;
  }, signal?: AbortSignal) =>
    post<StockFirstPassageEstimate>('/api/stocks/first-passage', req, signal),
  /** The stocks arithmetic plan — the options exit plan with the premium half
   *  removed (piece 6). Its own endpoint because /api/contracts/exit-plan
   *  requires strike, dte and premium, none of which a stock has.
   *
   *  Unlike getStockFirstPassage, this does NOT take a stop or a target ladder:
   *  it DERIVES them (the wider of the structural level and an ATR floor, then
   *  one target per R:R ratio), which is the whole point of the card. It takes
   *  the entry price they are measured from.
   *
   *  `strategy` only decides whether the probabilities carry the GBM model
   *  caveat; the plan itself does not depend on it, so it is optional. */
  getStockExitPlan: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    entry_price: number;
    trend_score: number;
    horizon: 'Intraday' | 'Swing' | 'Position';
    strategy?: string;
    rr_ratios?: number[];
  }, signal?: AbortSignal) =>
    post<StockExitPlan>('/api/stocks/exit-plan', req, signal),
  getCandles:    (symbol: string) => get<Candle[]>(`/api/candles/${encodeURIComponent(symbol)}`),
  getSymbolInfo: (symbol: string) =>
    get<{ symbol: string; name: string }>(`/api/symbol/${encodeURIComponent(symbol)}/info`),
  getNews:         (symbols: string[]) => get<NewsItem[]>(`/api/news?symbols=${symbols.join(',')}`),
  analyzeStock:    (req: AnalyzeStockRequest) => post<StockAnalysis>('/api/analyze-stock', req),
  addWatchlist:    (symbol: string) => post<{ symbol: string }>('/api/watchlist', { symbol }),
  removeWatchlist: (symbol: string) => del(`/api/watchlist/${encodeURIComponent(symbol)}`),
  getWatchedContracts:    () => get<string[]>('/api/watched-contracts'),
  getWatchedContractsDetail: () =>
    get<{ contract_id: string; grading: ContractGrading | null }[]>('/api/watched-contracts/detail'),
  /** `grading` undefined = no key (the server keeps an existing row's grading);
   *  `null` = sent as `"grading": null` (clears it); an object stores/overwrites. */
  addWatchedContract:     (contractId: string, grading?: ContractGrading | null) =>
    post<{ contract_id: string }>('/api/watched-contracts',
      grading !== undefined ? { contract_id: contractId, grading } : { contract_id: contractId }),
  removeWatchedContract:  (contractId: string) => del(`/api/watched-contracts/${encodeURIComponent(contractId)}`),
  postScan: (
    universe: string[],
    direction: string,
    horizon: string,
    hold: { hold_min_days: number; hold_max_days: number },
    filters?: {
      min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number;
      confidence_caution_below?: number; confidence_reject_below?: number;
      confidence_atr_mult_target?: number; confidence_atr_mult_stop?: number;
      fundamentals_enabled?: boolean;
      fundamentals_caution_below?: number;
      fundamentals_reject_below?: number;
      fundamentals_de_reject?: number;
      fundamentals_caution_above?: number;
      fundamentals_reject_above?:  number;
    },
    overrides?: Record<string, number | boolean | string>,
    spreads?: {
      spread_width?: number;
      short_leg_delta?: number;
      iv_rank_threshold?: number;
      iv_abs_threshold?: number;
      min_credit?: number;
      max_debit_pct?: number;
    },
  ) =>
    post<{ scan_id: string; timestamp: string; candidates: TradeCardData[]; rejected: { symbol: string; reason: string }[]; pipeline?: OptionsPipeline; dte_window?: DteWindow }>(
      '/api/scan',
      { universe, direction, horizon, ...hold, overrides: overrides ?? {}, ...filters, ...spreads },
    ),

  /** Posts an already-fully-resolved options-mode request body (the shape
   * `resolveOptionsScanRequest.ts`'s buildOptionsScanRequestBody() returns) —
   * used by RunScanButton after that extraction (Part 3 of the
   * scheduler-timezone-awareness plan), instead of the positional-args
   * postScan() above. */
  postScanBody: (body: import('./resolveOptionsScanRequest').OptionsScanRequestBody) =>
    post<ScanResult>('/api/scan', body),

  postStockScan: (
    req: import('./resolveStockScanRequest').StockScanRequestBody & {
      category?: 'stocks' | 'pullback'; symbols?: string[]; risk_fixed_usd?: number; min_price?: number; max_price?: number;
    },
  ) => post<StockScanResult>('/api/stock-scan', req),

  getLatestScanReport: (category: ScanReportCategory, signal?: AbortSignal) => get<LatestScanReport>(`/api/scan-reports/latest/${category}`, signal),
  getScanReport: (runId: string, signal?: AbortSignal) => get<ScanReport>(`/api/scan-reports/runs/${encodeURIComponent(runId)}`, signal),
  getLegacyScanReports: (signal?: AbortSignal) => get<Record<string, unknown>[]>('/api/scan-reports/legacy', signal),

  getLastScan: () => get<ScanResult | null>('/api/scan/last'),
  getLastStockScan: () => get<StockScanResult | null>('/api/stock-scan/last'),
  getLastStockScanRequest: () => get<LastStockScanRequest | null>('/api/stock-scan/last-request'),
  getLastScanStatus: () => get<ScanSessionStatus>('/api/scan/last-run'),
  getLastStockScanStatus: () => get<ScanSessionStatus>('/api/stock-scan/last-run'),

  postStockOrder: (req: {
    broker: string; symbol: string; action: 'BUY' | 'SELL'; effect: 'OPEN' | 'CLOSE';
    quantity: number; order_type: 'MKT' | 'LMT';
    limit_price: number | null; tif: 'DAY' | 'GTC';
  }) => post<{ order_id: string; status: string; broker: string }>('/broker/stock-order', req),

  postOptionOrder: (req: {
    broker: string; symbol: string; option_symbol: string;
    action: 'BUY' | 'SELL'; effect: 'OPEN' | 'CLOSE'; quantity: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null;
    tif: 'DAY' | 'GTC'; conid?: number;
  }) => post<{ order_id: string; status: string; broker: string }>('/broker/option-order', req),

  armAutoTrade: (req: {
    broker: string; symbol: string; option_symbol: string;
    /** 'BUY' only. The backend narrowed `ArmRequest.action` to Literal["BUY"]
     *  because `effect` is hardcoded to OPEN, making SELL a sell-to-open — a
     *  naked short. Narrowed here too so `action: 'SELL'` fails TYPECHECK
     *  rather than arriving as a runtime 422, which is the same standard
     *  `direction` below is held to. */
    action: 'BUY'; quantity: number;
    /** The trade's own direction, carried from the card. REQUIRED -- not
     *  optional and not defaulted -- so a caller that forgets fails typecheck
     *  here rather than arming a wrongly-sized trade. The backend decides
     *  position size off this: `action` is always 'BUY' for a long single-leg
     *  option (a bearish trade is a long PUT), so it never encoded direction,
     *  and inferring direction from it sized every bearish trade off the
     *  bullish conviction frame. Never write `card.direction ?? 'Bullish'`
     *  here -- that typechecks and silently reinstates that exact defect. */
    direction: Direction;
    /** The scoring horizon this card was scanned at — 'Intraday' | 'Swing' |
     *  'Position'. REQUIRED, same standard as `direction` above and for a
     *  related reason: the backend now measures THIS SYMBOL's own regime at
     *  fire time to decide the headwind gate, and the horizon picks the window
     *  it measures in (Intraday 26/1000/60 vs Position 50/750/100 — genuinely
     *  different measurements). Derive it with `scoringHorizonFromLabel` from
     *  the scan context rather than hand-writing a literal; never default it
     *  here, which would typecheck while measuring the wrong window. */
    horizon: ScoringHorizon;
    /** Actual sanitized scan hold, including Custom ranges. Required at arm. */
    hold_max_days: number;
    /** The Regime Gate thresholds this card's scan RESOLVED, read off the
     *  card's own `regimeGate` snapshot so neither a Step-3 edit, a reset nor
     *  a reload can change the rule the trade is judged by — the same freeze
     *  `quantity`, `premium_stop_pct` and the method pick get. Omitted means
     *  the resolved block carried no such key and the scan read
     *  scoring_rules.yaml. Build them with `regimeGateFromCard`, NOT
     *  `regimeGateOverridesFrom`: the latter reads the live Step-3 store,
     *  which need not hold what the card's scan used (arm-door round 1, F1). */
    regime_headwind_caution_pct?: number;
    regime_headwind_reject_pct?: number;
    order_type: 'MKT' | 'LMT'; limit_price: number | null; conid?: number;
    /** REQUIRED and > 0 on the backend (audit round 2, R2-F2): it is what the
     *  D5 cap is judged from at fire, and an arm without it is a 422. */
    entry_premium: number;
    portfolio_value?: number;
    /** Piece 4 — the per-trade premium stop as a FRACTION of `entry_premium`.
     *  Omitted inherits `auto_trade.premium_stop_pct`. Declared here because
     *  the backend has accepted it since the field was added, but no caller
     *  could pass it: the type did not have it, so every armed strategy sized
     *  off the global while the router, the schema bound and both
     *  `resolve_premium_stop_pct` call sites in auto_trader.py sat unreachable. */
    premium_stop_pct?: number;
    /** Phase G piece 5, build step 5 (§8) — the trader's explicit method pick,
     *  captured at arm. snake_case, like every other field on this endpoint and
     *  unlike `POST /api/portfolio`'s camelCase: `ArmedStrategy(**req.model_dump())`
     *  keys off ArmRequest's field NAMES. Sending the camelCase spelling here
     *  was SILENT until P6 (pydantic's `extra='ignore'`: 200, armed with all five
     *  NULL); `ArmRequest` now has `extra='forbid'`, so it is a 422 at arm.
     *
     *  `| null` and not just optional: `armPickedFieldsFrom` (lib/cardEdits.ts)
     *  maps "no pick" to five explicit nulls rather than omitting them, since
     *  unlike `premium_stop_pct` directly above there is no global pick for an
     *  omission to mean "inherit". */
    picked_method?: PickedMethod | null;
    picked_row_stock_price?: number | null;
    picked_row_option_price?: number | null;
    picked_stop_basis?: PickedStopBasis | null;
    picked_at?: string | null;
  } & Partial<ArmBookingFields>) => post<{ armed: boolean }>('/auto-trade/arm', req),

  disarmAutoTrade: () => del('/auto-trade/arm'),

  fireAutoTrade: () =>
    post<FireAutoTradeResult>('/auto-trade/fire', {}),

  getAutoTradeStatus: () =>
    // Models ALL SEVEN keys the endpoint returns. It used to declare five:
    // adding `direction` while leaving `broker` and `history_count` undeclared
    // would have left this contract selectively complete for no reason, and
    // this was the moment it was being edited anyway (ROUND 1 finding 10).
    get<{ armed: boolean; symbol: string | null; option: string | null;
          broker: string | null;
          /** Null when nothing is armed. An armed trade's direction now decides
           *  its size, so a wrong one is otherwise invisible until the fill.
           *  `last_order` does NOT carry it: history entries record no direction
           *  (that is O4's territory).
           *
           *  OPTIONAL, not merely nullable: a backend predating this field omits
           *  the key altogether, so the runtime value is `undefined` — which a
           *  bare `Direction | null` would have promised could not happen. The
           *  rollout note in routers/auto_trade.py contemplates exactly that
           *  deployment order. */
          direction?: Direction | null;
          history_count: number; last_order: unknown }>('/auto-trade/status'),

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
      ibkr_paper:       { configured: boolean };
      tradier_paper:    { configured: boolean };
      ibkr_live:        { configured: boolean; enabled: boolean; note: string };
      alpaca_paper:     { configured: boolean };
      tastytrade_paper: { configured: boolean };
      tastytrade_live:  { configured: boolean; enabled: boolean; note: string };
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
  addStrategyWatch: (symbol: string, strategy_key: string, direction: 'Bullish' | 'Bearish' = 'Bullish',
                     params_horizon: TunedHorizon | null = null) =>
    post<StrategyWatch>('/api/strategy-watch/', { symbol, strategy_key, direction, params_horizon }),
  addStrategyWatchesBulk: (symbols: string[], strategy_key: string, direction: 'Bullish' | 'Bearish' = 'Bullish',
                           params_horizon: TunedHorizon | null = null) =>
    post<{ added: number; watches: StrategyWatch[] }>('/api/strategy-watch/bulk', { symbols, strategy_key, direction, params_horizon }),
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

  // ── Composite watches ────────────────────────────────────────────────────────
  listCompositeWatches: () =>
    get<CompositeWatch[]>('/api/composite-watches/'),
  addCompositeWatch: (symbol: string, triggerDef: Record<string, unknown>, direction: string = 'Bullish', interval: string = '1D') =>
    post<CompositeWatch>('/api/composite-watches/', { symbol, trigger_def: triggerDef, direction, interval }),
  removeCompositeWatch: (id: string) =>
    del(`/api/composite-watches/${id}`),
  setCompositeWatchEnabled: (id: string, enabled: boolean) =>
    patch<{ id: string; enabled: boolean }>(`/api/composite-watches/${id}`, { enabled }),
  getCompositeWatchDefaults: () =>
    get<CompositeWatchDefaults>('/api/composite-watches/defaults'),
  getSymbolRegimeSnapshot: (symbol: string, model: string, direction: string = 'Bullish', interval: string = '15min') =>
    get<SymbolRegimeSnapshot>(
      `/api/composite-watches/regime-snapshot?symbol=${encodeURIComponent(symbol)}&model=${model}&direction=${direction}&interval=${interval}`,
    ),
  // Live composite RULE (WS-checked, only while chart tab is open) — distinct from
  // a Composite Watch (scheduled/background). Stored as an alert_rules row.
  addCompositeAlertRule: (
    name: string,
    symbol: string,
    interval: string,
    triggerDef: Record<string, unknown>,
  ) =>
    post<AlertRule>('/alerts/rules', {
      name,
      symbol,
      interval,
      rule_type: 'composite',
      composite_def: triggerDef,
    }),

  // ── Pre-breakout scan ────────────────────────────────────────────────────────
  prebreakoutScan: (
    symbols: string[],
    direction: string,
    paramsOverride?: Record<string, unknown>,
    universe?: string[],
    onReport?: (metadata: ScanReportMetadata) => void,
  ) =>
    post<PreBreakoutResultRow[]>(
      '/api/scan/prebreakout',
      { symbols, direction, params_override: paramsOverride ?? null, universe: universe ?? null }, undefined, onReport
    ),

  // ── Fibonacci pullback scan ──────────────────────────────────────────────────
  fibPullbackScan: (
    symbols: string[],
    direction: string,
    paramsOverride?: { fib_swing_lookback?: number; fib_levels?: number[]; fib_tolerance_pct?: number; ema_filter_period?: number },
    universe?: string[],
    onReport?: (metadata: ScanReportMetadata) => void,
  ) =>
    post<FibPullbackResultRow[]>(
      '/api/scan/fib-pullback',
      { symbols, direction, params_override: paramsOverride ?? null, universe: universe ?? null }, undefined, onReport
    ),

  // ── Regime series (for chart overlay) ────────────────────────────────────────
  getRegimeSeries: (symbol: string, limit?: number, model?: 'OMM' | 'HMM') =>
    get<Array<{ time: string; state: string; conviction?: number }>>(
      `/api/regime/series?symbol=${encodeURIComponent(symbol)}${limit != null ? `&limit=${limit}` : ''}${model ? `&model=${model}` : ''}`
    ),
  getIntradayRegimeSeries: (symbol: string, interval?: string, limit?: number) =>
    get<Array<{ time: string; state: string; conviction: number }>>(
      `/api/regime/intraday-series?symbol=${encodeURIComponent(symbol)}${interval ? `&interval=${encodeURIComponent(interval)}` : ''}${limit != null ? `&limit=${limit}` : ''}`
    ),

  // Two threshold sets, named for the quantity each judges — see
  // lib/ivThresholdsStore.ts (PHASE-A-NULL-IVRANK-2026-09-06).
  getIvThresholds: () =>
    get<Record<string, {
      abs_pass_max: number | null; abs_caution_max: number | null;
      rank_pass_max: number | null; rank_caution_max: number | null;
    }>>(
      '/api/config/iv-thresholds'
    ),

  getEventThresholds: () =>
    get<Record<string, { reject_days: number; caution_days: number }>>(
      '/api/config/event-thresholds'
    ),

  // STOCKS-HORIZON-T1 H4/H5: per-horizon strategy parameter profiles.
  // Untyped on purpose: lib/strategyProfilesStore.ts parseStrategyProfiles validates it.
  getStrategyProfiles: () => get<unknown>('/api/config/strategy-profiles'),

  // DOCC-5: GET /api/config/health (DOCC-4). Always 200; parsed by lib/configHealth.ts.
  getConfigHealth: (signal?: AbortSignal) => get<unknown>('/api/config/health', signal),

  // ── Part 1: operator timezone ────────────────────────────────────────────
  getSchedulingTimezone: () => get<{ timezone: string }>('/settings/scheduling'),
  putSchedulingTimezone: (timezone: string) => put<{ timezone: string }>('/settings/scheduling', { timezone }),

  // ── Part 3: scheduled-scan-run retention ─────────────────────────────────
  getScheduledScanRunRetention: () =>
    get<{ scheduledScanRunRetentionDays: number }>('/settings/scheduled-scan-retention'),
  saveScheduledScanRunRetention: (days: number) =>
    post<{ scheduledScanRunRetentionDays: number }>('/settings/scheduled-scan-retention', { scheduledScanRunRetentionDays: days }),

  // ── Part 3: profile-based scan schedule entries ──────────────────────────
  getScanSchedule: () => get<ScanScheduleEntry[]>('/api/scan-schedule'),
  createScanScheduleEntry: (body: ScanScheduleEntryInput) =>
    post<ScanScheduleEntry>('/api/scan-schedule', body),
  updateScanScheduleEntry: (id: string, body: ScanScheduleEntryInput) =>
    put<ScanScheduleEntry>(`/api/scan-schedule/${encodeURIComponent(id)}`, body),
  deleteScanScheduleEntry: (id: string) =>
    del(`/api/scan-schedule/${encodeURIComponent(id)}`),
  runScanScheduleEntryNow: (id: string) =>
    post<{ triggered: boolean; id: string }>(`/api/scan-schedule/${encodeURIComponent(id)}/run-now`, {}),
  getScanScheduleEntryRuns: (id: string, limit = 20) =>
    get<ScanScheduleRun[]>(`/api/scan-schedule/${encodeURIComponent(id)}/runs?limit=${limit}`),

  // ── Symbol notes ─────────────────────────────────────────────────────────
  getSymbolNote: (symbol: string) =>
    get<SymbolNote>(`/api/notes/${encodeURIComponent(symbol)}`),
  putSymbolNote: (symbol: string, body: string) =>
    put<SymbolNote>(`/api/notes/${encodeURIComponent(symbol)}`, { body }),

  // ── Trading Journal ──────────────────────────────────────────────────────
  // Query string built the same way getRegime() above builds one: conditionally
  // `.set(...)` per present key, never an empty string for an absent filter — an
  // empty string against the router's `Optional[datetime]` date_from/date_to
  // params would fail Pydantic's datetime parser (422).
  getJournalEntries: (filters?: JournalEntryFilters) => {
    const params = new URLSearchParams();
    if (filters?.symbol)        params.set('symbol',        filters.symbol);
    if (filters?.strategy_tag)  params.set('strategy_tag',  filters.strategy_tag);
    if (filters?.status)        params.set('status',        filters.status);
    if (filters?.entry_type)    params.set('entry_type',    filters.entry_type);
    if (filters?.date_from)     params.set('date_from',     filters.date_from);
    if (filters?.date_to)       params.set('date_to',       filters.date_to);
    const qs = params.toString();
    return get<JournalEntry[]>(`/journal/entries${qs ? `?${qs}` : ''}`);
  },
  createJournalEntry: (body: JournalEntryInput) =>
    post<JournalEntry>('/journal/entries', body),
  updateJournalEntry: (id: string, body: JournalEntryInput) =>
    put<JournalEntry>(`/journal/entries/${encodeURIComponent(id)}`, body),
  deleteJournalEntry: (id: string) =>
    del(`/journal/entries/${encodeURIComponent(id)}`),
};

/* ---------- Risk settings ---------- */

export interface RiskSettings {
  premiumStopPct: number;
  portfolioValue?: number;
  maxSinglePositionPct?: number;
  maxLossPerTradePct?: number;
  maxTotalExposurePct?: number;
  /** STOCK-SENDS: the stock caps (price x shares / portfolio value). */
  maxSingleStockPositionPct?: number;
  maxTotalStockExposurePct?: number;
  maxConcurrentPositions?: number;
  maxDailyRecommendations?: number;
  targetT1Pct?: number;
  targetT2Pct?: number;
  targetT3Pct?: number;
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

/* ---------- EDGAR schedule ---------- */

export async function getEdgarSchedule(): Promise<IngestionSchedule> {
  return get<IngestionSchedule>('/api/data/edgar/schedule');
}

export async function saveEdgarSchedule(s: Pick<IngestionSchedule, 'enabled' | 'time'>): Promise<IngestionSchedule> {
  return post<IngestionSchedule>('/api/data/edgar/schedule', s);
}

export async function triggerEdgarPrefetch(): Promise<{ status: string; total: number }> {
  return post<{ status: string; total: number }>('/api/data/edgar/prefetch', {});
}

export async function getEdgarStatus(): Promise<{ total: number; done: number; failed: number; in_progress: boolean }> {
  return get('/api/data/edgar/status');
}

/* ---------- S&P 500 schedule ---------- */

export async function getSp500Schedule(): Promise<IngestionSchedule> {
  return get<IngestionSchedule>('/api/data/sp500/schedule');
}

export async function saveSp500Schedule(s: Pick<IngestionSchedule, 'enabled' | 'time'>): Promise<IngestionSchedule> {
  return post<IngestionSchedule>('/api/data/sp500/schedule', s);
}

export async function triggerSp500Update(): Promise<{ status: string }> {
  return post<{ status: string }>('/api/data/sp500/update', {});
}

export async function getSp500Status(): Promise<{ status: string; last_updated: string | null; symbols_updated: number; in_progress: boolean }> {
  return get('/api/data/sp500/status');
}

/* ---------- Tuning schedule ---------- */

export interface TuningSchedule extends IngestionSchedule {
  days_of_week: number[];   // 0=Mon…6=Sun — Saturday-only ([5]) by default
}

export async function getTuningSchedule(): Promise<TuningSchedule> {
  return get<TuningSchedule>('/api/strategy-tuning/schedule');
}

export async function saveTuningSchedule(
  s: Pick<IngestionSchedule, 'enabled' | 'time'> & { days_of_week?: number[] },
): Promise<TuningSchedule> {
  return post<TuningSchedule>('/api/strategy-tuning/schedule', s);
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
  /** Pooled OOS trade count across the basket — the figure `min_trades` gates. */
  n_trades: number;
  /** Phase C T5: pooled trades / contributing symbols. Absent on proposals persisted before Phase C T5. */
  n_trades_per_symbol?: number;
  /** Phase C T5: symbols that contributed OOS trades — the figure `min_symbols` gates. Absent on older proposals. */
  n_symbols?: number;
}

export interface WfoProposal {
  strategy: string;
  direction: 'Bullish' | 'Bearish';
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

export interface TuningJobCount { count: number; completed: number; failed: number; running: number; }

export async function startTuningJob(): Promise<{ job_id: string }> {
  return post('/api/strategy-tuning/run', {});
}

export async function getTuningJob(jobId: string): Promise<TuningJob> {
  return get(`/api/strategy-tuning/jobs/${jobId}`);
}

export async function getTuningJobCount(): Promise<TuningJobCount> {
  return get('/api/strategy-tuning/jobs');
}

export async function clearTuningJobs(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE_URL}/api/strategy-tuning/jobs`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`API /api/strategy-tuning/jobs → ${res.status}`);
  return res.json() as Promise<{ cleared: number }>;
}

export async function adoptStrategyParams(strategy: string, params: Record<string, number | string>, direction: 'Bullish' | 'Bearish'): Promise<{ ok: boolean; active: Record<string, number | string> }> {
  return post('/api/strategy-tuning/adopt', { strategy, params, direction });
}
