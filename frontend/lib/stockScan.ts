import { usePortfolioStore } from './portfolioStore';
import { buildPaperStockPosition } from './paperTrade';
import type { Direction } from '@/types/domain';
import { stockExecutionBlock } from './stockExecutionSession';
import { api, API_BASE_URL } from '@/lib/api';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useScanParamsStore, type ScanParams } from '@/lib/scanParamsStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { StrategyScanValidationError } from './strategyScanValidation';
import { tunedParamsHorizon } from '@/lib/horizonPresets';
import { useRiskStore } from '@/lib/riskStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from './watchlistStore';
import { resolveUniverseSymbols, universeEmptyReason } from '@/lib/universeResolution';
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

/** The message every manual scan path shows when "Max loss per trade" is 0%
 *  (decision P3A-SCAN-RISK-ZERO-STOPS-2026-09-25). */
export const SCAN_RISK_ZERO_MESSAGE = 'Max loss per trade is 0% — set it in Settings → Risk';

/** Thrown by `scanSizingFromRisk` instead of posting a scan the backend would
 *  refuse (`risk_pct` is `gt=0`). Its message is shown as-is. */
export class ScanSizingError extends Error {
  constructor(message: string = SCAN_RISK_ZERO_MESSAGE) {
    super(message);
    this.name = 'ScanSizingError';
  }
}

/**
 * The sizing every MANUAL scan path sends (P3a, decision Q2): the user's
 * account value and max loss per trade from Settings → Risk, read at call time.
 * It used to be a hardcoded 50_000 / 1% on Steps 3/4 and Analysis, and 1% on
 * Step 5. A 0% max loss throws `ScanSizingError`: nothing is posted, and the
 * path shows `SCAN_RISK_ZERO_MESSAGE`.
 */
export function scanSizingFromRisk(): { accountSize: number; riskPct: number } {
  const { portfolioValue, maxLossPerTradePct } = useRiskStore.getState().limits;
  if (!Number.isFinite(maxLossPerTradePct) || maxLossPerTradePct <= 0) {
    throw new ScanSizingError();
  }
  return { accountSize: portfolioValue, riskPct: maxLossPerTradePct };
}

/** Longest reason that still reads as a sentence in a toast row or the thin
 *  inline error line on step 4. */
const MAX_REASON_CHARS = 200;

/** Is the backend's "detail" a markup error page rather than prose? Anchored:
 *  an unanchored probe fired on any detail that MENTIONED a tag (`symbol
 *  column must not contain <html> tags`) and threw the real explanation away.
 *  Deliberately wider than HTML — `<?xml` bodies from a load balancer and bare
 *  `<h1>502 Bad Gateway</h1>` fragments are the same problem. */
const MARKUP_DETAIL = /^<[!?a-z]/i;

/** Splits apiError()'s `API ${path} → ${status}: ${detail}` — the throw at
 *  api.ts's `apiError()`. Change the arrow, the separator or the spacing there
 *  and every backend detail quietly stops being recognised here, which is why
 *  `stockScanApiError.test.ts` drives the real apiError() through this. */
const API_ERROR = /^(API \S+ → \d+)(?::\s*([\s\S]*))?$/;

/** The parts of a thrown value this module reads. Structural, not
 *  `instanceof`: `instanceof Error` is realm-bound exactly as `instanceof
 *  TypeError` is, so an error from an iframe, a `vm` context or a fetch
 *  polyfill built in another realm fails it and loses both its message and
 *  the transport hint. */
interface ErrorLike { name: string; message: string; cause?: unknown }

function asErrorLike(value: unknown): ErrorLike | null {
  if (typeof value !== 'object' || value === null) return null;
  const e = value as { name?: unknown; message?: unknown; cause?: unknown };
  if (typeof e.message !== 'string') return null;
  return { name: typeof e.name === 'string' ? e.name : '', message: e.message, cause: e.cause };
}

/** `cause` is unconstrained by spec: undici sets an Error, other libraries set
 *  a string or `{ code: 'ECONNREFUSED' }`. Reading only Errors discarded the
 *  real explanation for the rest. */
function causeText(cause: unknown): string {
  if (typeof cause === 'string') return oneLine(cause);
  const like = asErrorLike(cause);
  if (like) return oneLine(like.message);
  const code = (cause as { code?: unknown } | null)?.code;
  return typeof code === 'string' ? oneLine(code) : '';
}

/** What a manual scan shows when building its request from the saved stores
 *  threw — nothing was sent. The likely cause (not the only possible one) is a
 *  malformed persisted setting, e.g. `confidenceGate: null`. Points at the
 *  footer Reset because the Settings → Scan form reads the same gate while
 *  rendering. Reset also restores the broker accounts, regime and gate
 *  settings, so the message says so. A5d. */
export const STOCK_SCAN_SETTINGS_INVALID =
  "Couldn't read your saved scan settings. Open Settings and press Reset to restore the defaults (this also resets your broker accounts, regime and gate settings).";

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
 *    goes through as-is — unless the detail is a markup error page, which is
 *    the raw body apiError() falls back to and explains nothing, so only the
 *    status line survives.
 *  - the request was sent and `fetch` rejected with a transport failure. A
 *    bare "Failed to fetch" explains nothing on its own, so this is the one
 *    case that earns the backend-unreachable hint. Note the hint says the
 *    request did not get through, NOT that the backend is down: a CORS or
 *    mixed-content block rejects identically from a backend that is up and
 *    answering, and the browser gives us no way to tell them apart.
 *  - anything else: a `SyntaxError` from a 200 whose body was not JSON, an
 *    `AbortError`, a `TypeError` raised by our own code (`api.postStockScan is
 *    not a function`, a bad `NEXT_PUBLIC_API_URL`) before a socket was ever
 *    opened. Show it verbatim. Appending "could not reach the backend" here
 *    would repeat the original defect — pointing at a backend that answered,
 *    or was never asked.
 *
 * @param reachedRequest false when the throw happened before `postStockScan`
 *   was called at all, so our own request-building code can never borrow the
 *   network hint.
 */
export function stockScanFailureReason(err: unknown, reachedRequest = true): string {
  const like = asErrorLike(err);
  const raw = oneLine(like ? like.message : String(err ?? ''));
  const cause = like ? causeText(like.cause) : '';

  // apiError() builds the `API ${path} → ${status}` head itself and
  // interpolates the backend's detail AFTER it, so the head cannot be forged
  // from the wire.
  const api = API_ERROR.exec(raw);
  if (api) {
    const [, head, detail = ''] = api;
    return clampReason(MARKUP_DETAIL.test(detail)
      ? `${head}: the server returned an error page, not JSON`
      : raw);
  }

  // `cause` alone when there is no message of our own — otherwise an empty
  // message composed into a dangling " — ECONNREFUSED".
  const detail = cause && cause !== raw ? (raw ? `${raw} — ${cause}` : cause) : raw;

  if (reachedRequest && isTransportFailure(like)) {
    const hint = `could not reach the backend at ${API_BASE_URL}`;
    if (!detail) return clampReason(hint);
    // Clamp the DETAIL, not the composed string. Clamping the whole thing
    // truncated the hint off the end — i.e. it ate the actionable half and
    // kept 200 characters of "Failed to fetch xxxxx…". The hint always
    // survives; the detail gets whatever room is left (a floor of 20 chars,
    // for an API_BASE_URL long enough that both cannot fit).
    const room = Math.max(MAX_REASON_CHARS - hint.length - 3, 20);
    return `${clampReason(detail, room)} (${hint})`;
  }
  return clampReason(detail) || 'unknown error';
}

/** The WHOLE message each engine uses when a request got no response at all:
 *  Chrome/WebKit "Failed to fetch", undici "fetch failed", Safari "Load
 *  failed", Firefox "NetworkError when attempting to fetch resource.".
 *
 *  (Plus a bare "Network error", which some polyfills and older engines send.)
 *
 *  Anchored, and matched whole rather than searched. Searching for these
 *  phrases inside a longer message is what kept re-admitting the misdirection
 *  this module exists to remove: word boundaries still matched the identifier
 *  in `api.networkError is not a function`, and "Failed to fetch dynamically
 *  imported module: …/chunk.js" is webpack's stale-asset error, nothing to do
 *  with the API host. Both are TypeErrors; neither is the backend's fault.
 *
 *  An engine whose wording is not listed here loses the hint and shows its
 *  message verbatim — the safe direction to be wrong in. */
const FETCH_FAILURE_MESSAGE =
  /^(?:failed to fetch|fetch failed|load failed|network error|networkerror when attempting to fetch resource\.?)$/i;

/** Did the request fail before any response came back? */
function isTransportFailure(err: ErrorLike | null): boolean {
  return !!err && err.name === 'TypeError' && FETCH_FAILURE_MESSAGE.test(oneLine(err.message));
}

function oneLine(message: string): string {
  return message.replace(/\s+/g, ' ').trim();
}

/** Slices by CODE POINT: a UTF-16 slice cuts a non-BMP character (emoji, some
 *  CJK) in half and leaves a lone surrogate that renders as `�`. */
function clampReason(message: string, max = MAX_REASON_CHARS): string {
  const points = [...message];
  return points.length > max
    ? `${points.slice(0, max - 1).join('').trimEnd()}…`
    : message;
}

/** Metadata refreshes retain monotonic response ordering AND manual-run
 * ownership. An older run's refresh cannot caption a newer run, even if the
 * newer metadata request failed. In that case the prior displayed metadata
 * stays stale until a current refresh or hydration supplies a new answer. */
let metaRefreshSeq = 0;
let metaAppliedSeq = 0;

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
 * Never throws, and never leaves an unhandled rejection: the scan's own
 * outcome must not depend on this bookkeeping.
 */
function refreshLastStockScanMeta(token: number): void {
  try {
    // Inside the try, and only once the call is actually being made: bumping
    // it first meant a `getLastStockScanStatus` that is not callable (a
    // partially-mocked api) permanently invalidated a refresh that WAS in
    // flight, and the meta then stopped updating altogether.
    const request = api.getLastStockScanStatus();
    const seq = ++metaRefreshSeq;
    void request.then(
      (s) => {
        try {
          // A NEWER answer is already on screen, so this older response must
          // not overwrite it. Responses can arrive out of order; ids cannot.
          if (seq <= metaAppliedSeq || useScanStore.getState().stockManualRunToken !== token) return;
          metaAppliedSeq = seq;
          useScanStore.getState().setLastStockScanMeta(
            s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null, s.strategy ?? null,
          );
        } catch { /* a malformed payload or a failed store write — bookkeeping only */ }
      },
      // Two-argument form on purpose: this swallows a FAILED REQUEST (backend
      // unreachable — leave the meta stale, StoreHydration catches up on the
      // next load) and not a throw from the handler above it, which has its
      // own guard. A failed request leaves the last displayed metadata; the
      // current-run metadata is refreshed on the next request/hydration.
      () => {},
    );
  } catch { /* not callable (a test double, a partially-mocked api) — ignore */ }
}

/** Optional per-run param overrides (the page passes its locally-edited
 *  params). A `null` strategy field means "follow the backend profile" and
 *  wins over a saved override, as the panel shows it (STOCKS-HORIZON-T1 H5). */
export type StockScanParamOverrides = Partial<ScanParams>;

/**
 * Run a stock scan with `strategy`, reading universe/direction/horizon from
 * scanStore.context and parameters from scanParamsStore (overridable per-run).
 * Writes result + scanState into scanStore. Returns the result or null on error.
 */
export async function runStockScanWithContinuation(
  strategy: string,
  overrides: StockScanParamOverrides = {},
): Promise<StockManualScanOutcome> {
  const store = useScanStore.getState();
  const token = store.beginStockManualRun();
  const intent = { ...store.stockAfterScanIntent };
  const current = () => useScanStore.getState().stockManualRunToken === token;

  // Everything else is inside the try, the store writes below included. The
  // store reads and the request-body build used to sit outside it, so a throw
  // there (a malformed persisted confidenceGate is enough; so is a
  // QuotaExceededError out of a persist() write) escaped runStockScan with
  // `scanState` pinned at SCANNING — disabling the Run button for the rest of
  // the session — and rejected the promise instead of returning null, which
  // the fire-and-forget call site could not see at all. Both call sites still
  // carry a catch for a rejection that gets past even this (`setScanState`
  // itself throwing), and both reset scanState there.
  let reachedRequest = false;
  // True only while the request is being BUILT from the saved stores. A throw
  // in that window (not ScanSizingError, which carries its own message) is a
  // malformed saved setting -- A5d's STOCK_SCAN_SETTINGS_INVALID, moved here
  // from Step 5 so Step 4 and the floating Run button say it too. A store
  // write failing before the build is NOT that, hence a flag of its own.
  let building = false;
  try {
    if (!current()) return { kind: 'obsolete', token };
    store.setActiveStrategy(strategy);
    if (!current()) return { kind: 'obsolete', token };
    store.setStockScanResult(null);
    // Clear the previous run's reason before this one starts — a FAILED pill
    // from an earlier attempt must never caption a scan that is still running,
    // and a run that succeeds must leave nothing behind for a later caller to
    // read as its own failure.
    if (!current()) return { kind: 'obsolete', token };
    store.setStockScanError(null);
    if (!current()) return { kind: 'obsolete', token };
    store.setScanState('SCANNING');

    building = true;
    const saved = useScanParamsStore.getState();
    const p = { ...saved, ...overrides };
    const context = store.context;
    const requireReversal =
      (store.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;
    const { confidenceGate } = useSettingsStore.getState();
    const rawOverrides = store.scanOverrides;

    // The user's sizing from Settings → Risk, read now (P3a). Throws
    // ScanSizingError on a 0% max loss; the catch shows its message.
    const sizing = scanSizingFromRisk();
    const uStore = useUniverseStore.getState();
    const watch = useWatchlistStore.getState();
    const activePick = context?.universe ?? uStore.pick;
    const universeSymbols = resolveUniverseSymbols(activePick, uStore.customRaw, watch.added);

    if (universeSymbols.length === 0) {
      building = false;
      const reason = universeEmptyReason(activePick);
      store.setStockScanError(reason);
      store.setScanState('FAILED');
      return { kind: 'failure', reason, token };
    }

    const requestBody = buildStockScanRequestBody({
      universe: universeSymbols,
      direction: context?.direction ?? 'Bullish',
      horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
      strategy,
      params: p,
      // STOCKS-HORIZON-T1 H5: the backend profile the strategy fields follow.
      paramsHorizon: context ? tunedParamsHorizon(context.horizonPreset, context.holdMax) : null,
      requireReversal,
      scanOverrides: rawOverrides,
      confidenceGate,
      accountSize: sizing.accountSize,
      riskPct: sizing.riskPct,
      // The scan context's hold, Custom included (B6): the backend's earnings
      // veto window is max(reject_days, hold_max_days).
      holdMinDays: context?.holdMin,
      holdMaxDays: context?.holdMax,
      minPriceRaw: uStore.minPriceRaw,
      maxPriceRaw: uStore.maxPriceRaw,
      minCapRaw: uStore.minCapRaw,
      maxCapRaw: uStore.maxCapRaw,
      capUnit: uStore.capUnit,
    });
    building = false;

    if (!current()) return { kind: 'obsolete', token };
    reachedRequest = true;
    const result = await api.postStockScan(requestBody);
    if (!current()) return { kind: 'obsolete', token };
    // A5: the request travels with its result, so Analysis replays this run.
    store.setStockScanResult(result, requestBody);
    if (!current()) return { kind: 'obsolete', token };
    store.setScanState('COMPLETED');
    const failures: string[] = [];
    const queued: string[] = [];
    const adjusted: string[] = [];
    const skipped: string[] = [];
    for (const candidate of result.candidates) {
      if (!current()) return { kind: 'obsolete', token };
      if (!intent[candidate.symbol]) continue;
      if (candidate.stock_status !== 'PASS') {
        skipped.push(`${candidate.symbol}: not PASS (${candidate.stock_status})`);
        continue;
      }
      // These saves are an automatic execution intent, not a human research
      // save. Guard the actual mutation, preserving pristine scan levels.
      const blocked = stockExecutionBlock();
      if (blocked) { skipped.push(`${candidate.symbol}: ${blocked}`); continue; }
      if (!current()) return { kind: 'obsolete', token };
      const key = `${token}:${candidate.symbol}`;
      store.recordStockAfterScanOutcome(key, { token, symbol: candidate.symbol, status: 'saving' });
      try {
        if (!current()) {
          store.recordStockAfterScanOutcome(key, { token, symbol: candidate.symbol, status: 'rejected', detail: 'Superseded before saving' });
          return { kind: 'obsolete', token };
        }
        const boundaryBlock = stockExecutionBlock();
        if (boundaryBlock) {
          store.recordStockAfterScanOutcome(key, { token, symbol: candidate.symbol, status: 'rejected', detail: boundaryBlock });
          skipped.push(`${candidate.symbol}: ${boundaryBlock}`);
          continue;
        }
        const saved = await usePortfolioStore.getState().addPosition(buildPaperStockPosition(
          candidate.symbol, candidate.strategy.entry_price, candidate.shares, candidate.direction as Direction, undefined,
          { stop: candidate.strategy.stop_price,
            targets: (candidate.strategy.targets?.length ? candidate.strategy.targets : [candidate.strategy.target_price]).map(price => ({ price })),
          },
        ));
        // Started saves always finish their own bookkeeping, even after a
        // newer scan takes ownership. They cannot start another save or route.
        store.recordStockAfterScanOutcome(key, { token, symbol: candidate.symbol, status: saved.status, detail: saved.detail, adjustedQty: saved.adjustedQty });
        if (saved.status === 'rejected') failures.push(`${candidate.symbol}: ${saved.detail ?? 'not saved'}`);
        else if (saved.status === 'pending') queued.push(candidate.symbol);
        else if (saved.adjustedQty != null) adjusted.push(`${candidate.symbol} (${saved.adjustedQty} sh)`);
      } catch (error) {
        const detail = String(error);
        store.recordStockAfterScanOutcome(key, { token, symbol: candidate.symbol, status: 'rejected', detail });
        failures.push(`${candidate.symbol}: ${detail}`);
      }
    }
    if (!current()) return { kind: 'obsolete', token };
    const notices: string[] = [];
    if (queued.length) notices.push(`Queued — backend unreachable, will sync automatically: ${queued.join(', ')}`);
    if (adjusted.length) notices.push(`Size reduced to fit exposure limits — ${adjusted.join(', ')}`);
    if (skipped.length) notices.push(`Not fired — ${skipped.join('; ')}`);
    store.setStockScanFeedback(token, {
      error: failures.length ? `Some auto-executed positions were not saved — ${failures.join('; ')}` : null,
      notice: notices.length ? notices.join(' · ') : null,
    });
    if (!current()) return { kind: 'obsolete', token };
    return { kind: 'success', token, result };
  } catch (err) {
    if (!current()) return { kind: 'obsolete', token };
    // The reason goes to the store, not to the return value: RunScanButton
    // (step 3) fires this without awaiting a result it can inspect, so a
    // `null` return alone left that path with nothing to show and the
    // step-4 path guessing "backend unreachable" for every failure.
    //
    // Guarded, because scanStore is persist()ed and zustand writes storage
    // synchronously on every set: whatever made a store write throw in the try
    // (a QuotaExceededError, blocked storage) makes these throw too, and an
    // unguarded catch block re-throws — which is how the escape route the try
    // was widened to close came back out through the failure path instead.
    // One try EACH, not one around both: zustand applies the in-memory update
    // and then writes storage, so a QuotaExceededError out of the first write
    // would skip the second — and the one that must not be skipped is FAILED,
    // which is what re-enables the Run button.
    const isValidationError = err instanceof StrategyScanValidationError;
    const settingsUnreadable = building && !(err instanceof ScanSizingError) && !isValidationError;
    if (settingsUnreadable) console.error('runStockScan: building the stock-scan request failed', err);
    try {
      store.setStockScanError(
        isValidationError
          ? err.message
          : settingsUnreadable ? STOCK_SCAN_SETTINGS_INVALID : stockScanFailureReason(err, reachedRequest),
      );
    } catch { /* see above — the null return is the signal that survives */ }
    try {
      if (current()) store.setScanState('FAILED');
    } catch { /* ditto */ }
    const reason = isValidationError
      ? err.message
      : settingsUnreadable ? STOCK_SCAN_SETTINGS_INVALID : stockScanFailureReason(err, reachedRequest);
    store.setStockScanFeedback(token, { error: `Scan failed — ${reason}`, notice: null });
    return { kind: 'failure', token, reason };
  } finally {
    // Refresh last-run status/strategy from the backend so TopBar/Settings
    // reflect this scan immediately (success or failure), not just after the
    // next full page load — the backend is the source of truth for what it
    // actually persisted (e.g. reverted to "idle" on a mid-scan failure).
    // Fire-and-forget: see refreshLastStockScanMeta's header for why awaiting
    // it here used to cost the failure reason outright.
    if (current()) refreshLastStockScanMeta(token);
  }
}

/** UI continuation checks ownership immediately before navigation/toasts.
 * Obsolete runs must never caption or navigate a newer run. */
export type StockManualScanOutcome =
  | { kind: 'success'; token: number; result: StockScanResult }
  | { kind: 'failure'; token: number; reason: string }
  | { kind: 'obsolete'; token: number };
export function isStockManualScanCurrent(outcome: StockManualScanOutcome): boolean {
  return outcome.kind !== 'obsolete' && useScanStore.getState().stockManualRunToken === outcome.token;
}
/** Compatibility for non-workflow callers. Workflow triggers use the explicit
 * outcome API so null failures cannot be confused with superseded runs. */
export async function runStockScan(strategy: string, overrides: StockScanParamOverrides = {}): Promise<StockScanResult | null> {
  const outcome = await runStockScanWithContinuation(strategy, overrides);
  return outcome.kind === 'success' ? outcome.result : null;
}
