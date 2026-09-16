import { api } from '@/lib/api';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';

/**
 * React key for a StockPositionCard, incorporating the signal itself — not
 * just the symbol. `openSymbol` (step-4-stocks) survives a same-symbol
 * re-scan (onRun() never resets it), and StockPositionCard's own overlay-
 * reset effect only fires on a `card.symbol` change. Without this, a card
 * left open across a fresh Run Scan would silently keep showing — and let
 * the user submit — the PREVIOUS scan's entry/stop/target overlay even
 * though the signal underneath it just changed.
 *
 * Hashes the FULL ladder (`targets`), not just `target_price` (== targets[0]):
 * a third independent audit round found a concrete case via
 * resolve_multi_signal where entry/stop/targets[0] are byte-identical across
 * two scans (e.g. a re-scan that adds a third confirming mean-reversion
 * variant whose own rung is farther than the already-tightest one) while
 * targets[1]/[2] differ. Keying on target_price alone would miss that change,
 * leave the card un-remounted, and let StockPositionCard's client-fabricated
 * T2/T3 fallback (`t1 + risk`, `t1 + 2*risk`) reach Add to Portfolio instead
 * of the fresh backend-computed rungs. `?.length`, not `??`: an empty
 * `targets` array must fall back to `target_price` too, same convention as
 * StockPositionCard's own defaultOverlay().
 */
export function stockPositionCardKey(c: PositionCardData): string {
  const ladder = c.strategy.targets?.length ? c.strategy.targets : [c.strategy.target_price];
  return `${c.symbol}-${c.strategy.entry_price}-${c.strategy.stop_price}-${ladder.join(',')}`;
}

/**
 * One human-readable line explaining why a stock scan failed.
 *
 * `api.postStockScan` throws two shapes that need different text. A non-2xx
 * response arrives already formatted by api.ts's `apiError()` as
 * `API /api/stock-scan → 422: <detail>` — the backend answered and said what
 * was wrong, so pass that through untouched; surfacing that detail is the
 * whole reason this error is bound rather than swallowed. A transport failure
 * arrives as a bare `TypeError: Failed to fetch`, which on its own explains
 * nothing, so it keeps the backend-unreachable hint the call sites used to
 * print for EVERY failure — including the validation ones, where it actively
 * misdirected the user to a backend that was running and had just rejected
 * the request.
 */
export function stockScanFailureReason(err: unknown): string {
  const raw = err instanceof Error ? err.message.trim() : String(err ?? '').trim();
  // Matches apiError()'s `API ${path} → ${status}...` prefix. A thrown string
  // of that shape reads the same way, so it is not narrowed to Error.
  if (raw.startsWith('API ')) return raw;
  return `${raw || 'unknown error'} (is the backend running on port 8000?)`;
}

/** Optional per-run param overrides (the page passes its locally-edited params). */
export interface StockScanParamOverrides {
  pullbackTolerancePct?: number;
  pullbackEmaPeriod?: number;
  pullbackTrendEma?: number;
  pullbackMaType?: 'EMA' | 'SMA';
  maCrossoverFast?: number;
  maCrossoverSlow?: number;
  maCrossoverLookback?: number;
  breakoutVolumeMult?: number;
  rsiPeriod?: number;
  rsiOversold?: number;
  rsiTrendSma?: number;
  requireChoppyRegime?: boolean;
  btMinTrades?: number;
  btMinWinRate?: number;
  stockShortlistMax?: number;
}

/**
 * Run a stock scan with `strategy`, reading universe/direction/horizon from
 * scanStore.context and parameters from scanParamsStore (overridable per-run).
 * Writes result + scanState into scanStore. Returns the result or null on error.
 */
export async function runStockScan(
  strategy: string,
  overrides: StockScanParamOverrides = {},
): Promise<StockScanResult | null> {
  const store = useScanStore.getState();
  const saved = useScanParamsStore.getState();
  const p = { ...saved, ...overrides };

  const context = store.context;
  const requireReversal =
    (store.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;
  const { confidenceGate } = useSettingsStore.getState();
  const rawOverrides = store.scanOverrides;

  store.setActiveStrategy(strategy);
  store.setStockScanResult(null);
  // Clear the previous run's reason before this one starts — a FAILED pill
  // from an earlier attempt must never caption a scan that is still running,
  // and a run that succeeds must leave nothing behind for a later caller to
  // read as its own failure.
  store.setStockScanError(null);
  store.setScanState('SCANNING');

  // account_size/risk_pct are hardcoded here (not read from riskStore) —
  // this is the manual-run path's existing, already-shipped behavior,
  // unchanged by this extraction. Flagged (not silently fixed) per the
  // scheduler-timezone-awareness plan: the profile-based schedule resolver
  // (scanScheduleResolve.ts) explicitly reads live riskStore values instead,
  // since a scheduled entry firing unattended for months must never
  // silently keep a stale $50k/1% default baked in from before the user set
  // their real position sizing — fixing this same gap for the manual path
  // too is a separate, pre-existing concern outside this plan's scope.
  const requestBody = buildStockScanRequestBody({
    universe: context?.universe ? [context.universe] : ['SP500'],
    direction: context?.direction ?? 'Bullish',
    horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
    strategy,
    params: p,
    requireReversal,
    scanOverrides: rawOverrides,
    confidenceGate,
    accountSize: 50_000,
    riskPct: 0.01,
  });

  try {
    const result = await api.postStockScan(requestBody);
    store.setStockScanResult(result);
    store.setScanState('COMPLETED');
    return result;
  } catch (err) {
    // The reason goes to the store, not to the return value: RunScanButton
    // (step 3) fires this without awaiting a result it can inspect, so a
    // `null` return alone left that path with nothing to show and the
    // step-4 path guessing "backend unreachable" for every failure.
    store.setStockScanError(stockScanFailureReason(err));
    store.setScanState('FAILED');
    return null;
  } finally {
    // Refresh last-run status/strategy from the backend so TopBar/Settings
    // reflect this scan immediately (success or failure), not just after the
    // next full page load — the backend is the source of truth for what it
    // actually persisted (e.g. reverted to "idle" on a mid-scan failure).
    try {
      const s = await api.getLastStockScanStatus();
      store.setLastStockScanMeta(
        s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null, s.strategy ?? null,
      );
    } catch {
      // Backend unreachable — leave stale, StoreHydration will catch up on next load.
    }
  }
}
