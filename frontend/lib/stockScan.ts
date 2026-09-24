import { api, API_BASE_URL } from '@/lib/api';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildStockScanRequestBody, type StockScanRequestBody } from '@/lib/resolveStockScanRequest';
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

/** Orders the last-run status refreshes: an earlier run's response landing
 *  after a later run's would pin TopBar/Settings to the older scan — the
 *  staleness the refresh exists to prevent. Module-level because the runs it
 *  orders are separate calls, not state any one of them owns.
 *
 *  Two counters, not one. `metaRefreshSeq` only hands out increasing ids;
 *  `metaAppliedSeq` is the id whose answer is currently on screen, and an
 *  answer applies when it is NEWER than that. Gating on "is this the latest
 *  id issued" instead meant every failed request permanently discarded the
 *  older answers still in flight: with two later requests failing, no amount
 *  of yielding a token back one step let the good answer through, and the
 *  pill stayed at neither run's result. */
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
function refreshLastStockScanMeta(): void {
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
          if (seq <= metaAppliedSeq) return;
          metaAppliedSeq = seq;
          useScanStore.getState().setLastStockScanMeta(
            s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null, s.strategy ?? null,
          );
        } catch { /* a malformed payload or a failed store write — bookkeeping only */ }
      },
      // Two-argument form on purpose: this swallows a FAILED REQUEST (backend
      // unreachable — leave the meta stale, StoreHydration catches up on the
      // next load) and not a throw from the handler above it, which has its
      // own guard. A failed request applies nothing and blocks nothing: an
      // older answer still in flight is still newer than what is on screen.
      () => {},
    );
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
 * The body a manual stock scan posts: universe/direction/horizon from
 * scanStore.context, params = saved scanParamsStore merged with the caller's
 * per-run edits, Step-3 scanOverrides, settingsStore.confidenceGate.
 * Shared by runStockScan (Step-3 / Step-4 Run) and Step 5's runScan so the two
 * cannot drift again (A5b). Reads stores; may throw on a malformed persisted
 * store — callers call it inside their try.
 */
export function manualStockScanRequest(
  strategy: string,
  overrides: StockScanParamOverrides = {},
  opts: { accountSize?: number } = {},
): StockScanRequestBody {
  const store = useScanStore.getState();
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
  // Step 5 passes opts.accountSize (riskStore portfolioValue), decision
  // A5B-ACCOUNT-SIZE-2026-09-24; Steps 3/4 keep the 50k default.
  return buildStockScanRequestBody({
    universe: context?.universe ? [context.universe] : ['SP500'],
    direction: context?.direction ?? 'Bullish',
    horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
    strategy,
    params: p,
    requireReversal,
    scanOverrides: rawOverrides,
    confidenceGate,
    accountSize: opts.accountSize ?? 50_000,
    riskPct: 0.01,
  });
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
  try {
    store.setActiveStrategy(strategy);
    store.setStockScanResult(null);
    // Clear the previous run's reason before this one starts — a FAILED pill
    // from an earlier attempt must never caption a scan that is still running,
    // and a run that succeeds must leave nothing behind for a later caller to
    // read as its own failure.
    store.setStockScanError(null);
    store.setScanState('SCANNING');

    const requestBody = manualStockScanRequest(strategy, overrides);

    reachedRequest = true;
    const result = await api.postStockScan(requestBody);
    // A5: the request travels with its result, so Analysis replays this run.
    store.setStockScanResult(result, requestBody);
    store.setScanState('COMPLETED');
    return result;
  } catch (err) {
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
    try {
      store.setStockScanError(stockScanFailureReason(err, reachedRequest));
    } catch { /* see above — the null return is the signal that survives */ }
    try {
      store.setScanState('FAILED');
    } catch { /* ditto */ }
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
