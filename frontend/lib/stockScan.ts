import { api, API_BASE_URL } from '@/lib/api';
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

/** Longest reason that still reads as a sentence in a toast row or the thin
 *  inline error line on step 4. A 502 from a proxy arrives as a whole HTML
 *  document (api.ts's apiError() falls back to the raw body text), and both
 *  of those surfaces render it unclamped. */
const MAX_REASON_CHARS = 200;

/**
 * One human-readable line explaining why a stock scan failed — collapsed to a
 * single line and clamped, because the caller renders it verbatim.
 *
 * Three cases, and the difference matters because the WRONG hint is what this
 * whole change exists to stop:
 *
 *  - `api.ts`'s `apiError()` already formatted it as
 *    `API /api/stock-scan → 422: <detail>`. The backend answered and said what
 *    was wrong; that detail is the entire point of binding the error, so it
 *    goes through as-is (clamped).
 *  - `fetch` rejected with a `TypeError` on a request that was actually sent.
 *    That, and only that, means nothing at the other end took it, so it is the
 *    one case the backend-unreachable hint is TRUE for — and a bare "Failed to
 *    fetch" needs it, since it explains nothing on its own.
 *  - anything else: a `SyntaxError` from a 200 whose body was not JSON, an
 *    `AbortError`, a `TypeError` thrown by our own request-building code
 *    before anything was sent (`reachedRequest === false`). Show it verbatim.
 *    Appending "is the backend reachable" here would repeat the original
 *    defect — pointing at a backend that answered, or was never asked.
 *
 * @param reachedRequest false when the throw happened before `postStockScan`
 *   was called, so a TypeError from our own code can never borrow the network
 *   hint.
 */
export function stockScanFailureReason(err: unknown, reachedRequest = true): string {
  const raw = clampReason(err instanceof Error ? err.message : String(err ?? ''));
  // Matches apiError()'s `API ${path} → ${status}` prefix, which it builds
  // itself; the backend-supplied detail is interpolated after it and so cannot
  // forge it. A thrown string of that shape reads the same way, hence no
  // `instanceof Error` narrowing here.
  if (raw.startsWith('API ')) return raw;
  if (reachedRequest && err instanceof TypeError) {
    const hint = `is the backend reachable at ${API_BASE_URL}?`;
    return raw ? `${raw} (${hint})` : hint;
  }
  return raw || 'unknown error';
}

function clampReason(message: string): string {
  const oneLine = message.replace(/\s+/g, ' ').trim();
  return oneLine.length > MAX_REASON_CHARS
    ? `${oneLine.slice(0, MAX_REASON_CHARS - 1).trimEnd()}…`
    : oneLine;
}

/**
 * Refresh TopBar/Settings' last-run status from the backend — deliberately
 * NOT awaited by the scan itself.
 *
 * This was an `await` inside runStockScan's `finally`, which meant the scan's
 * own promise only resolved after a second, unrelated round trip. Two ways
 * that lost the failure reason this module exists to deliver:
 *
 *  - the reason was unreadable until the extra trip finished, while the Run
 *    button was already re-enabled (`scanState` leaves SCANNING the moment the
 *    catch runs). A user who clicked Run again in that window started a scan
 *    that cleared the reason before the first one's caller ever read it;
 *  - `fetch` has no default timeout, so a backend that accepts the socket and
 *    then hangs left the promise pending forever — no inline error, no toast,
 *    for precisely the unreachable-backend case the hint is written for.
 *
 * Never throws: the scan's own outcome must not depend on this bookkeeping.
 */
function refreshLastStockScanMeta(): void {
  try {
    void api.getLastStockScanStatus()
      .then((s) => useScanStore.getState().setLastStockScanMeta(
        s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null, s.strategy ?? null,
      ))
      // Backend unreachable — leave stale, StoreHydration catches up on next load.
      .catch(() => {});
  } catch { /* not callable (a test double, a partially-mocked api) — ignore */ }
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

  store.setActiveStrategy(strategy);
  store.setStockScanResult(null);
  // Clear the previous run's reason before this one starts — a FAILED pill
  // from an earlier attempt must never caption a scan that is still running,
  // and a run that succeeds must leave nothing behind for a later caller to
  // read as its own failure.
  store.setStockScanError(null);
  store.setScanState('SCANNING');

  // Everything below is inside the try — including reading the stores and
  // building the request body. Those ran BEFORE it, so a throw there (a
  // malformed persisted confidenceGate is enough) escaped runStockScan with
  // `scanState` pinned at SCANNING, disabling the Run button for the rest of
  // the session, and rejected the promise instead of returning null — which
  // the fire-and-forget call site could not see at all.
  let reachedRequest = false;
  try {
    const saved = useScanParamsStore.getState();
    const p = { ...saved, ...overrides };
    const context = store.context;
    const requireReversal =
      (store.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;
    const { confidenceGate } = useSettingsStore.getState();
    const rawOverrides = store.scanOverrides;

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

    reachedRequest = true;
    const result = await api.postStockScan(requestBody);
    store.setStockScanResult(result);
    store.setScanState('COMPLETED');
    return result;
  } catch (err) {
    // The reason goes to the store, not to the return value: RunScanButton
    // (step 3) fires this without awaiting a result it can inspect, so a
    // `null` return alone left that path with nothing to show and the
    // step-4 path guessing "backend unreachable" for every failure.
    store.setStockScanError(stockScanFailureReason(err, reachedRequest));
    store.setScanState('FAILED');
    return null;
  } finally {
    // Refresh last-run status/strategy from the backend so TopBar/Settings
    // reflect this scan immediately (success or failure), not just after the
    // next full page load — the backend is the source of truth for what it
    // actually persisted (e.g. reverted to "idle" on a mid-scan failure).
    // Fire-and-forget: see refreshLastStockScanMeta's header for why awaiting
    // it here used to cost the failure reason outright.
    refreshLastStockScanMeta();
  }
}
