/*
 * Portfolio store — Zustand with localStorage persistence.
 *
 * Holds open positions. Step 7's direct sends (Place Limit / Right Now —
 * Market) and its tracked-only basket (fix #5 / D6: no broker order) call
 * `addPosition` — tagged `paper` or `manual` via `source`.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { PortfolioPosition, TargetLevel, Direction, ExitPlan, MaxLossOverride, AlertOverrides, TpMethod, PickedMethod, PickedStopBasis } from '@/types/domain';
import { useRiskStore } from '@/lib/riskStore';
import { stripLegacyIvFields } from '@/lib/ivBasis';
import { validationMessages } from '@/lib/pydanticError';
import { premiumStopDropReason, premiumStopIsSubCent, type PremiumStopDropReason } from '@/lib/premiumStop';
import { premiumStopPctFromDollars } from '@/lib/barrierRace';

type BackendPosition = {
  id: string;
  recId: string;
  symbol: string;
  contract: string;
  direction: string;
  entryPrice: number;
  qty: number;
  entryDate: string;
  stop: number | null;
  structuralStop?: number | null;
  exitPlan?: ExitPlan | null;
  maxLossOverride?: MaxLossOverride | null;
  /** Piece 4 — per-position premium stop. Null means the row inherits the
   *  global; it is NOT resolved server-side, because the drawer renders the
   *  inherited-vs-set difference. */
  premiumStopPct?: number | null;
  activeTpMethod?: TpMethod | null;
  resolvedTpPrice?: number | null;
  resolvedTpUpdatedAt?: string | null;
  // Phase G (piece 5) — the raw pick, distinct from activeTpMethod/
  // resolvedTpPrice above. See PortfolioPosition's own doc for why these five
  // are read here rather than left to fall through with the rest.
  pickedMethod?: PickedMethod | null;
  pickedRowStockPrice?: number | null;
  pickedRowOptionPrice?: number | null;
  pickedStopBasis?: PickedStopBasis | null;
  pickedAt?: string | null;
  /** STOCKS-HORIZON-T1 H6 -- null = no hold. */
  holdMaxDays?: number | null;
  alertOverrides?: AlertOverrides | null;
  targets: TargetLevel[];
  dteTotal: number | null;
  createdAt: string;
  // Live fields enriched by GET /portfolio via Tradier
  currentPrice?: number;
  currentStockPrice?: number | null;
  pnlDollar?: number;
  pnlPct?: number;
  quoteUnavailable?: boolean;
  dteRemaining?: number;
  delta?: number | null;
  theta?: number | null;
  ivRank?: number | null;
  iv?: number | null;
};

function fromBackend(p: BackendPosition): PortfolioPosition {
  const parts = p.contract.split('|');
  const expiry = parts[2] ?? '';

  return {
    symbol:       p.symbol,
    contract:     p.contract,
    direction:    p.direction as Direction,
    entryPrice:   p.entryPrice,
    contracts:    p.qty,
    entryDate:    p.entryDate,
    expiry,
    stop:         floorStop(p.stop),
    structuralStop: floorStop(p.structuralStop),
    exitPlan:     p.exitPlan ?? null,
    maxLossOverride: p.maxLossOverride ?? null,
    premiumStopPct: p.premiumStopPct ?? null,
    // The backend column defaults to 'ladder' server-side, but a row written
    // before that default (or a payload that omits the key) still arrives as
    // null — normalise to 'ladder' here so the drawer's segmented control and
    // alertEngine's TP resolution never have to special-case a null method.
    activeTpMethod: (p.activeTpMethod ?? 'ladder') as TpMethod,
    resolvedTpPrice: p.resolvedTpPrice ?? null,
    resolvedTpUpdatedAt: p.resolvedTpUpdatedAt ?? null,
    // Phase G (piece 5) — the raw pick. NULL is a real, already-supported
    // state (pre-G positions, and every S5 auto-executed one) so this reads
    // straight through with no 'ladder'-style default, unlike activeTpMethod
    // just above: the portfolio renders a genuinely absent pick as "—", never
    // as a method nobody chose.
    pickedMethod: p.pickedMethod ?? null,
    pickedRowStockPrice: p.pickedRowStockPrice ?? null,
    pickedRowOptionPrice: p.pickedRowOptionPrice ?? null,
    pickedStopBasis: p.pickedStopBasis ?? null,
    pickedAt: p.pickedAt ?? null,
    holdMaxDays: p.holdMaxDays ?? null,
    alertOverrides: p.alertOverrides ?? {},
    targets:      p.targets ?? [],
    dteTotal:     p.dteTotal ?? 0,
    dteRemaining: p.dteRemaining ?? 0,
    status:       'PENDING',
    recId:        p.recId,
    currentPrice: p.currentPrice ?? 0,
    currentStockPrice: p.currentStockPrice ?? undefined,
    pnlDollar:    p.pnlDollar ?? 0,
    pnlPct:       p.pnlPct ?? 0,
    quoteUnavailable: p.quoteUnavailable ?? false,
    delta:        p.delta ?? undefined,
    theta:        p.theta ?? undefined,
    // Two quantities, kept apart (PHASE-A-NULL-IVRANK-2026-09-06):
    // `ivRank` is a percentile and is usually absent; `iv` is the absolute
    // implied volatility. Resolve them via lib/ivBasis.ts at the display site.
    ivRank:       p.ivRank ?? undefined,
    iv:           p.iv ?? undefined,
    syncStatus:   'synced',
    syncedAt:     Date.now(),
  };
}

export type PremiumStopDropNotice = {
  /** Null when the create sent only a fraction (STOP-SEMANTICS S3). */
  symbol: string; contract: string; requestedDollar: number | null; at: number;
  reason: PremiumStopDropReason;
  /** Set when the dollar could not be applied but the server kept the
   *  card's own fraction (PREMIUM-STOP-FALLBACK-USER-FRACTION-2026-10-03). */
  keptPct?: number;
};

/** STOP-SEMANTICS-2026-10-02 -- did the server drop the per-position stop this
 *  create asked for, and why? One rule for all three create signals.
 *
 *  "Asked for" is what `toBackendBody` actually POSTs: a positive
 *  `premiumStopDollar`, or a `premiumStopPct` inside (0, 1). A null resolved
 *  `premiumStopPct` in the 201 then means the server could not store it -- a
 *  total loss at the persisted entry, or a stop that would fire below $0.01.
 *  A response carrying the CLIENT fraction (the server's fallback when only
 *  the dollar was unusable) is not a drop to the global, but the dollar was
 *  still not applied: that returns a notice with `keptPct` set. */
export function premiumStopDropOf(
  p: Pick<PortfolioPosition, 'premiumStopDollar' | 'premiumStopPct'>,
  savedPremiumStopPct: number | null | undefined,
  savedEntry: number | null | undefined,
): { requestedDollar: number | null; reason: PremiumStopDropReason; keptPct?: number } | null {
  const dollar = (p.premiumStopDollar ?? 0) > 0 ? (p.premiumStopDollar as number) : null;
  const pct = (p.premiumStopPct ?? 0) > 0 && (p.premiumStopPct as number) < 1 ? p.premiumStopPct : null;
  if (dollar == null && pct == null) return null;
  if (savedPremiumStopPct != null) {
    // PREMIUM-STOP-FALLBACK-USER-FRACTION-2026-10-03 -- the card now sends its
    // own fraction beside the dollar, so a dollar the server could not apply
    // no longer leaves a null: it stores that fraction. Same test the writer
    // makes (total loss or sub-cent at the SAVED entry); the stored fraction is
    // then not the dollar's, so say which one applies. Card sends are options
    // only, hence `shortStock = false`, as in premiumStopDropReason.
    if (dollar == null || savedEntry == null || !Number.isFinite(savedEntry) || savedEntry <= 0) return null;
    const ratio = premiumStopPctFromDollars(dollar, savedEntry);
    if (ratio !== undefined && !premiumStopIsSubCent(savedEntry, ratio, false)) return null;
    return {
      requestedDollar: dollar,
      reason: ratio === undefined ? 'total_loss' : 'below_one_cent',
      keptPct: savedPremiumStopPct,
    };
  }
  return { requestedDollar: dollar, reason: premiumStopDropReason(dollar, savedEntry) };
}

/** P2-09 (R1-7) -- adopt the server's entry price on a row, and reset the
 *  row's mark to it.
 *
 *  The three sites that fold the server's `entryPrice` onto a row used to keep
 *  the client's `currentPrice`/`pnlDollar`/`pnlPct`, which were computed
 *  against the CARD'S mid: a $5.20 mid filled at $4.00 showed a +30% P&L on a
 *  position that had not moved. The row has no quote newer than the booking,
 *  so its mark is the entry and its P&L is 0 until the next sync brings the
 *  live mark. A stock row's `currentStockPrice` mirrors `currentPrice`
 *  (see AlertPosition), so it moves with it. No entry reported -> the row is
 *  returned unchanged. */
export function withServerEntry<T extends PortfolioPosition>(row: T, entry: number | null | undefined): T {
  if (entry == null) return row;
  const isStock = row.contract.endsWith('|STOCK');
  return {
    ...row,
    entryPrice: entry,
    currentPrice: entry,
    pnlDollar: 0,
    pnlPct: 0,
    ...(isStock ? { currentStockPrice: entry } : {}),
  };
}

interface PortfolioStoreState {
  positions: PortfolioPosition[];
  /** Last backend rejection of a save, for the UI to surface. Null when clean. */
  lastSyncError: { symbol: string; contract: string; detail: string; at: number } | null;
  /** A reported fill the server stored in full even though it is over the cap.
   *  Not a rejection: the quantity was not cut. */
  lastExposureBreach: { symbol: string; contract: string; detail: string; at: number } | null;
  /** ROUND 9 -- the OFFLINE RETRY's version of the "premium stop could not be
   *  applied" notice. That path re-POSTs a queued row from a background sync
   *  with no UI callback in scope, so it could not use the two the order paths
   *  do, and folded `premiumStopPct ?? null` onto the row saying nothing. The
   *  row inherits the global, which is a TIGHTER stop than the one asked for.
   *  The portfolio page renders this the same way it renders lastSyncError. */
  lastPremiumStopDropped: PremiumStopDropNotice | null;
  /** P2-08 -- every undismissed drop, oldest first. `lastPremiumStopDropped`
   *  is always this queue's head, so the page renders one notice at a time
   *  and a second drop is shown after the first is dismissed instead of being
   *  lost. Not persisted (partialize keeps only `positions`). */
  premiumStopDropQueue: PremiumStopDropNotice[];
  /** Dismisses the notice on screen (the queue head); the next one shows. */
  clearPremiumStopDropped: () => void;
  clearSyncError: () => void;
  hydrate:        (positions: PortfolioPosition[]) => void;
  /** status: 'ok' saved; 'rejected' backend refused (dropped); 'pending' network
   *  error, kept locally and retried by syncFromBackend. `ok` === (status==='ok').
   *  `adjustedQty` is set when the backend's risk check auto-reduced the
   *  requested size to fit exposure limits — the position was still saved,
   *  just at a smaller quantity than requested; callers should surface this
   *  rather than silently showing the originally-requested size. */
  /** `opts.skipPost` skips this call's own internal POST — for a caller that
   *  already got a real, backend-confirmed successful response from its own
   *  `persistPosition` call and just needs local state to reflect that. Do
   *  NOT pass this based on `persistPosition`'s offline-optimistic fallback
   *  (see `persistPosition`'s `offline` field) — only on a genuine confirmed
   *  success, or a network hiccup would get marked `synced` despite never
   *  reaching the backend. */
  /** `premiumStopDropped` carries the per-share dollar stop the caller ASKED
   *  for when the server could not apply it and the row inherited the global
   *  instead (a TIGHTER stop than requested). Undefined means nothing was
   *  dropped. Without it the basket path could not report the fallback at all
   *  -- see the note in step-7-trade-card's handleSubmit. */
  addPosition:    (p: PortfolioPosition, opts?: { skipPost?: boolean }) => Promise<{ ok: boolean; status: 'ok' | 'rejected' | 'pending'; detail?: string; adjustedQty?: number; premiumStopDropped?: number; premiumStopDropReason?: PremiumStopDropReason; premiumStopKeptPct?: number }>;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  /** Record an added fill. Sends the total, the fill price, and the saved
   *  base together. Does not change quantity or entry until the server
   *  confirms them, and does not debounce a quantity that has no price. */
  confirmAddedFill: (contract: string, totalQty: number, fillPrice: number) => Promise<{ ok: boolean; detail?: string }>;
  closePosition:  (contract: string) => void;
  closePositionRemote: (
    recId: string,
    opts: { qtyToClose?: number | null; exitPrice?: number | null; exitDate?: string | null; sendToBroker?: boolean },
  ) => Promise<{ ok: boolean; detail?: string }>;
  /** Returns whether the pull actually reached the backend and updated state
   *  (false on network failure — callers that just mutated local state around
   *  this call may need to know so they don't assume the pull "saw" their change).
   *  force=true bypasses the concurrent-sync dedup by SERIALIZING a fresh run
   *  after any in-flight one — used by closePositionRemote, which needs a GET
   *  that post-dates its own write. */
  syncFromBackend: (force?: boolean) => Promise<boolean>;
  syncToBackend:  () => Promise<void>;
}

const _BASE_URL = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** The account value the backend risk check must measure exposure against —
 *  the user's configured value, identical to the Step-7 pre-check. Using the
 *  sum of deployed premiums here made a single option read as a huge fraction
 *  of the account and got otherwise-valid trades rejected (the ABT 422). */
function accountValue(): number {
  return useRiskStore.getState().limits.portfolioValue || 100_000;
}

// A stock price is never <= 0, so a non-positive stop/structuralStop can only
// mean "unset" — mirrors the backend's own `_floor_stop` (portfolio.py).
// alertEngine.ts's `stop != null` gate treats an unfloored 0 as a permanent
// STOP_REACHED/STRUCTURAL_STOP_BREACHED for a Bearish position, so this must
// run at EVERY point a stop value enters store state, not just the ones that
// happen to go over the network. A "this is now the complete list" comment
// here has been wrong FOUR times running (rounds 2-5 each missed at least
// one site — most recently addPosition's own optimistic set(), which let
// paperTrade.ts's buildPaperStockPosition() send stop: 0 straight into live
// state for every paper stock buy). Treat any future "found the last one"
// claim, including this one, as unverified until re-derived from the code —
// this list is a snapshot, not a guarantee:
//   - fromBackend (GET /api/portfolio reconcile — syncFromBackend)
//   - toBackendPayload (POST /api/portfolio)
//   - toUpdatePayload (PATCH /api/portfolio/{recId})
//   - updatePosition's optimistic set() (local state, before the PATCH fires)
//   - addPosition's optimistic set() (local state, before the POST fires)
//   - hydrate (no live caller today, floored anyway — the next one may not audit first)
//   - migratePortfolioPersist (localStorage version migration)
//   - the persist `merge` callback (every rehydration, migration or not —
//     the backstop for a pre-round-2 stop:0 already sitting in a browser)
function floorStop(value: number | null | undefined): number | null {
  return value != null && value > 0 ? value : null;
}

function toBackendPayload(p: PortfolioPosition, portfolioValue = 100_000) {
  return {
    recId:          p.recId,
    symbol:         p.symbol,
    contract:       p.contract,
    direction:      p.direction,
    entryPrice:     p.entryPrice,
    qty:            p.contracts ?? 1,
    entryDate:      p.entryDate ?? new Date().toISOString().slice(0, 10),
    stop:           floorStop(p.stop),
    structuralStop: floorStop(p.structuralStop),
    exitPlan:       p.exitPlan ?? null,
    // Feature 5 — without this key, a pre-trade override set on the
    // Arithmetic card appears to work in the client's optimistic local UI
    // state right after submit, but the backend never receives it: the row
    // is created with max_loss_override=None regardless of schema/router
    // wiring, and the next backend sync silently overwrites the optimistic
    // value with null. Mirrors toUpdatePayload's existing
    // `if ('maxLossOverride' in patch) body.maxLossOverride = ...` handling
    // for the post-trade PATCH path.
    maxLossOverride: p.maxLossOverride ?? null,
    // Piece 4 — the DOLLAR amount, not a fraction. The backend derives the
    // fraction against the entry price it persists; sending a client-derived
    // fraction re-anchors the user's stop to a price the server replaced.
    //
    // `?? null` is not enough: the schema is `gt=0`, and the card's SEEDED
    // premium stop is `round(premium * pct, 2)`, which is 0.00 for a premium
    // under about $0.0084. A posted 0 fails validation and 422s the whole
    // create with an opaque Pydantic error instead of falling back to
    // inherit-the-global. Same `??`-does-not-catch-0 guard this file already
    // applies to floorStop and resolvedTpPrice.
    premiumStopDollar: (p.premiumStopDollar ?? 0) > 0 ? p.premiumStopDollar : null,
    // Piece 4 — same reasoning as maxLossOverride above: omit this key and the
    // row is created with premium_stop_pct=NULL no matter how the schema and
    // router are wired, so the trade silently falls back to the global on its
    // first alert while the optimistic local state shows the value the user
    // chose.
    //
    // This is NOT redundant with premiumStopDollar beside it. That field is
    // create-only transport and is DELETED from a row on its way to 'synced'
    // (see the `syncStatus === 'synced'` branch below and the retry path in
    // syncFromBackend), leaving a synced row carrying the server-derived
    // FRACTION alone. Any path that re-POSTs such a row -- syncToBackend, from
    // dashboard/page.tsx -- was therefore sending neither field, recreating
    // the position with no per-position stop at all and silently reverting it
    // to the global. The router prefers premiumStopDollar when both are
    // present, so sending both is safe on the first create and correct on a
    // re-POST.
    //
    // Guarded the same way: the column's contract is the open interval (0, 1),
    // so a stray 0 or 1 must become null rather than 422 the whole create.
    premiumStopPct: (p.premiumStopPct ?? 0) > 0 && (p.premiumStopPct as number) < 1
      ? p.premiumStopPct
      : null,
    targets:        p.targets ?? [],
    dteTotal:       p.dteTotal ?? null,
    portfolioValue,
    // P2-10 (R2-2) -- a row the server has ACCEPTED ('synced') carries stop,
    // structuralStop and targets the server already re-anchored to the live
    // price (position_writer.create_position). Re-sending its scan price would
    // shift them a second time on any re-POST (syncToBackend, the close-after-
    // 404 re-send), and `stopIsUserSet: true` would switch on the wrong-side
    // 422 there. So a synced row sends neither: the writer stores the levels
    // as they stand. A row the server has never accepted (pending) still
    // sends both, as the create needs them. Residual, logged: a promoted row
    // not yet reconciled by a GET that is re-POSTed after a backend loss
    // stores its levels unshifted.
    scanStockPrice: p.syncStatus === 'synced' ? null : (p.scanStockPrice ?? null),
    // Round 9 — tells the router NOT to re-anchor `stop` by
    // (live price - scanStockPrice). A stop the user typed on the trade card
    // is an absolute price against today's quote; the plan-derived levels
    // beside it still scale with the underlying. Without this a $180 stop
    // typed on a $200 stock scanned at $145 was stored as $235 -- above spot,
    // firing a Critical STOP_REACHED on the first backend scan.
    stopIsUserSet: p.syncStatus === 'synced' ? false : (p.stopIsUserSet ?? false),
    tradeCardSnapshot: p.tradeCardSnapshot ?? null,
    // Phase G (piece 5) — sent explicitly null rather than omitted when no
    // pick exists (the S5 auto-executor's shape, spec §7.3), matching every
    // builder that sets these five via `pickedFieldsFrom`: an omitted key and
    // an explicit null are the same to the schema, but omitting here would
    // silently reintroduce the send-path gap `pickedFieldsFrom` exists to
    // close for a caller that forgets to spread it in.
    pickedMethod: p.pickedMethod ?? null,
    pickedRowStockPrice: p.pickedRowStockPrice ?? null,
    pickedRowOptionPrice: p.pickedRowOptionPrice ?? null,
    pickedStopBasis: p.pickedStopBasis ?? null,
    pickedAt: p.pickedAt ?? null,
    // STOCKS-HORIZON-T1 H6 -- the scan's hold (stock sends only); null = none.
    holdMaxDays: p.holdMaxDays ?? null,
  };
}

/** FastAPI's `detail` is not always a string.
 *
 *  A risk rejection returns `detail: "code code"` (a string, space-joined), and
 *  every call site here assumed that shape. A Pydantic VALIDATION failure
 *  returns a LIST of error objects instead -- `[{type, loc, msg, input}, ...]`
 *  -- and casting that to `string` and storing it in `lastSyncError.detail`
 *  crashed the Portfolio page: `rejectionMessage` does `detail.split(' ')`,
 *  which throws inside JSX and takes the whole page down. The position vanished
 *  AND the screen that would explain why went with it.
 *
 *  Piece 4's `entryPrice: Field(gt=0)` is what made a VALIDATION 422 newly
 *  possible on this endpoint at all, which is why the crash surfaced now. A
 *  round-6 audit could not find a producer of a literal $0 mid: `cd.mid` is
 *  `round(premium, 2)` off the chain, and `market.py` skips any row with no
 *  positive ask and no positive last, so the known paths do not emit one
 *  today. The normalisation stays regardless -- it costs nothing, it is
 *  correct for EVERY validation 422 on any field (not just entryPrice), and
 *  the failure it prevents is the whole Portfolio page going white. What is
 *  genuinely unguarded is the `livePrice ?? cd?.mid ?? card.entry.limit`
 *  chains that feed this: `??` does not catch 0, the same rule this file
 *  already applies to `floorStop` and `premiumStopDollar`.
 *
 *  Normalises every shape to a string so no consumer has to. Validation errors
 *  are rendered through lib/pydanticError.ts, the same helper `apiError` uses,
 *  so the identical wire shape cannot render two different ways depending on
 *  which call site produced it.
 *
 *  That helper NAMES THE FIELD. This comment used to say the location was
 *  "dropped because these are all single-position posts", which does not
 *  follow: a single position posts several `gt=0` fields, and they fail with
 *  byte-identical messages, so the old output repeated one sentence per bad
 *  field and named none of them. */
function errorDetail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof d === 'string' && d.trim() !== '') return d;
  if (Array.isArray(d)) {
    const msgs = validationMessages(d);
    if (msgs) return msgs;
  }
  if (d && typeof d === 'object') {
    const msg = (d as { msg?: unknown }).msg;
    if (typeof msg === 'string' && msg.trim() !== '') return msg;
  }
  return `HTTP ${status}`;
}

type SaveOutcome =
  // `premiumStopPct` is the fraction the SERVER derived for this create (piece
  // 4) — the client sends dollars, so this is the only place the stored
  // fraction is known before the next full sync.
  // `entryPrice` rides WITH it and is not optional cosmetics: both engines
  // compare `price <= entry * (1 - pct)`, so a fraction adopted without the
  // entry it was derived against puts them on different thresholds.
  | { kind: 'ok'; adjustedQty?: number; premiumStopPct?: number | null; entryPrice?: number | null }
  | { kind: 'rejected'; detail: string }   // backend 4xx (except 409) — do not keep the row
  | { kind: 'duplicate' }                  // 409 — backend already has this contract
  | { kind: 'network' };                   // unreachable — keep the row pending

async function postPosition(p: PortfolioPosition, portfolioValue = accountValue()): Promise<SaveOutcome> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      // Piece 4 — the SERVER derives premiumStopPct (from premiumStopDollar,
      // against the entry price it actually persisted), so the created row is
      // the only place that fraction exists. Discarding it left the optimistic
      // local row at `premiumStopPct: undefined` until the next 30s
      // syncFromBackend, and in that window the frontend alert engine resolved
      // the position to the GLOBAL while the backend used the derived value —
      // the two engines disagreeing, which is the one thing lib/premiumStop.ts
      // says must not happen.
      const premiumStopPct = (body as { premiumStopPct?: number | null }).premiumStopPct ?? null;
      // The entry the router actually persisted -- it replaces the submitted
      // one with its save-time quote. See SaveOutcome.entryPrice.
      const serverEntry = (body as { entryPrice?: number | null }).entryPrice;
      return {
        kind: 'ok',
        ...(typeof adjustedQty === 'number' ? { adjustedQty } : {}),
        premiumStopPct,
        entryPrice: typeof serverEntry === 'number' && serverEntry > 0 ? serverEntry : null,
      };
    }
    if (res.status === 409) return { kind: 'duplicate' };
    const body = await res.json().catch(() => ({}));
    return { kind: 'rejected', detail: errorDetail(body, res.status) };
  } catch {
    return { kind: 'network' };
  }
}

/** POST to the backend and return whether it was accepted.
 *  Used by the single-order buttons in Step 7 so rejections (risk check, duplicate
 *  contract) surface to the user instead of being silently dropped.
 *
 *  A 409 is *not* success: the backend keeps one open position per contract and
 *  has no scale-in path, so it recorded nothing. Reporting it as ok would let the
 *  caller add quantity that only ever existed in local state.
 *
 *  On a network failure, `ok` is `false` and `offline` is `true` — this is
 *  DELIBERATELY distinguishable from a genuine rejection. A caller must not
 *  treat `offline: true` the same as `ok: true` (nothing was actually
 *  persisted) nor the same as a hard rejection (the position may well be
 *  valid — the backend just couldn't be reached to confirm it). The correct
 *  handling is to fall back to `addPosition`'s own POST + pending/retry path,
 *  exactly as every other call site (without a `persistPosition` step) does. */
export async function persistPosition(
  p: PortfolioPosition,
  portfolioValue = accountValue(),
  /** Audit round 1, F1 — the order this save precedes (Step 7's direct send).
   *  The server judges the D5 premium cap at the price that order can FILL at
   *  (`portfolio_risk.premium_cap_basis`: max(mid, limit) for LMT, the ask for
   *  MKT), not at the stored mid. Create-only transport, never a field of the
   *  position. Omitted means no order follows (judged at the mid). */
  order?: { orderType: 'LMT' | 'MKT'; limitPrice: number | null },
): Promise<{ ok: boolean; offline?: boolean; detail?: string; adjustedQty?: number; premiumStopPct?: number | null; entryPrice?: number | null }> {
  try {
    const payload = {
      ...toBackendPayload(p, portfolioValue),
      ...(order ? { orderType: order.orderType, orderLimitPrice: order.limitPrice } : {}),
    };
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      // Same reason as postPosition's: the server derives premiumStopPct from
      // the dollar stop against the entry price it persisted, so this response
      // is the only place that fraction exists before the next full sync.
      // `applyPersistedPosition` folds it onto the row it hands to addPosition.
      const premiumStopPct = (body as { premiumStopPct?: number | null }).premiumStopPct ?? null;
      // ...and the ENTRY PRICE that fraction was derived against. The router
      // replaces the submitted entry with its own save-time quote, so keeping
      // the client's mid beside the server's fraction makes the two engines
      // fire at different prices: a $3.12 stop on a $5.20 card filled at $4.00
      // stores pct 0.78, which against the local 5.20 is a $4.06 stop, not the
      // $3.12 typed. Both halves of the pair or neither.
      const serverEntry = (body as { entryPrice?: number | null }).entryPrice;
      return {
        ok: true,
        ...(typeof adjustedQty === 'number' ? { adjustedQty } : {}),
        premiumStopPct,
        entryPrice: typeof serverEntry === 'number' && serverEntry > 0 ? serverEntry : null,
      };
    }
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: errorDetail(body, res.status) };
  } catch {
    // Backend unreachable. Do NOT report ok:true here — nothing was actually
    // persisted, and a caller that skips its own retry path on ok:true would
    // silently lose this position on the next reconcile (see the `offline`
    // doc comment above).
    return { ok: false, offline: true };
  }
}

export type PersistPositionResult = Awaited<ReturnType<typeof persistPosition>>;

/**
 * The three-way outcome every `persistPosition` call site must branch on — extracted here
 * (rather than left inline at each call site) so the real production branching logic can be
 * unit-tested directly, instead of only via a hand-reimplemented copy in a test file:
 *  - offline (network failure): `persistPosition` did NOT confirm anything was saved. Fall
 *    through to `addPosition`'s own POST + pending/retry path, same as every call site that
 *    never calls `persistPosition` at all.
 *  - rejected (backend responded, said no): surface the error, do not add the position.
 *  - confirmed success: skip `addPosition`'s own POST (already persisted) but still sync local
 *    state via `addPosition(pos, { skipPost: true })`.
 * Returns `{ rejected: true }` when the caller should show `saved.detail` and stop, mirroring
 * the `if (!saved.ok) { setOrderError(...); return; }` shape each call site used inline before.
 */
export function applyPersistedPosition(
  saved: PersistPositionResult,
  pos: PortfolioPosition,
  addPosition: (p: PortfolioPosition, opts?: { skipPost?: boolean }) => unknown,
  onAdjusted?: (adjustedQty: number) => void,
  /** Fired when the position asked for a per-share dollar premium stop and the
   *  server could not apply it, so the row inherits the global instead.
   *
   *  The router derives `pct = premiumStopDollar / entry_price` against the
   *  price it actually persists -- which is the save-time live quote, not the
   *  card's mid -- and when that ratio reaches 1 (the stop is at or past a
   *  total loss on the re-anchored premium) it logs a warning and falls back to
   *  `body.premiumStopPct`, which the card never sends. Result: `NULL`, i.e.
   *  the global. Reachable through an ordinary fill: a $4.50 stop typed against
   *  a $5.20 mid, filled at $4.20.
   *
   *  The router's own comment says "nothing on screen says why". This is the
   *  hook that lets a call site say it: the response already carries the
   *  resolved `premiumStopPct`, so no extra request is needed. */
  onPremiumStopDropped?: (requestedDollar: number | null, reason: PremiumStopDropReason, keptPct?: number) => void,
): { rejected: boolean; detail?: string } {
  if (saved.offline) {
    void addPosition(pos);
    return { rejected: false };
  }
  if (!saved.ok) {
    return { rejected: true, detail: saved.detail };
  }
  if (saved.adjustedQty != null) onAdjusted?.(saved.adjustedQty);
  const dropped = premiumStopDropOf(pos, saved.premiumStopPct, saved.entryPrice);
  if (dropped) onPremiumStopDropped?.(dropped.requestedDollar, dropped.reason, dropped.keptPct);
  // Piece 4 — carry the server's derived premium-stop fraction onto the row
  // that goes into local state. `skipPost: true` means nothing else will fetch
  // it until the next 30s syncFromBackend, and until then the frontend alert
  // engine would resolve this position to the GLOBAL while the backend used
  // the derived value.
  //
  // Round 9 — and carry the ENTRY PRICE it was derived against, whenever the
  // response reports one. ROUND 10 finding 15 corrects how this was stated:
  // the pct is adopted unconditionally and the entry only when present, so
  // "the pair or neither" was never what the code did. The router guarantees a
  // positive `entryPrice` in a 201 body, so the two do arrive together on
  // every live path; the fallback keeps the row's own entry rather than
  // blanking it, which is why the asymmetry is safe rather than merely
  // tolerated. `premiumStopPct` is meaningless on its own:
  // both engines compare `price <= entry * (1 - pct)`, so adopting the
  // server's fraction while keeping the client's mid puts them on different
  // thresholds. Card mid $5.20, typed stop $3.12, filled at $4.00 -> the
  // server stores 0.78 and fires at $0.88; the local row kept 5.20 and fired
  // at $1.14, raising a PREMIUM_STOP toast at a quote where the backend raises
  // nothing. The dashboard rescans the moment the row lands, so the window is
  // not theoretical -- it is immediate, and lasts until the next 30s sync.
  //
  // This is also why round 7's rejection of the entry-limit finding does not
  // cover this case. That argument -- entry x (1 - dollar/entry) = entry -
  // dollar, so the dollar loss survives any entry -- holds only when ONE entry
  // is used for both the derivation and the threshold. Here they differed.
  void addPosition(withServerEntry({
    ...pos,
    premiumStopPct: saved.premiumStopPct ?? null,
  }, saved.entryPrice), { skipPost: true });
  return { rejected: false };
}

async function deletePosition(recId: string): Promise<void> {
  try {
    await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, { method: 'DELETE' });
  } catch { /* network unavailable */ }
}

/** Whitelists the drawer's persistable fields out of an `updatePosition` patch.
 *  `currentPrice`/`pnlDollar`/`pnlPct` are deliberately excluded — they're
 *  live-computed by the backend from a broker quote on every GET, so a manual
 *  override here would just be overwritten by the next sync anyway.
 *
 *  `contracts` (-> `qty`) always carries `portfolioValue` alongside it — the
 *  backend re-runs the exposure gate when a PATCH increases qty (same gate
 *  POST /api/portfolio enforces at creation) and requires it for that check,
 *  the same way the store's own `postPosition` already does for a new order. */
function toUpdatePayload(patch: Partial<PortfolioPosition>): Record<string, unknown> | null {
  const body: Record<string, unknown> = {};
  if ('stop' in patch) body.stop = floorStop(patch.stop);
  if ('structuralStop' in patch) body.structuralStop = floorStop(patch.structuralStop);
  if ('exitPlan' in patch) body.exitPlan = patch.exitPlan;
  if ('maxLossOverride' in patch) body.maxLossOverride = patch.maxLossOverride;
  // Piece 4 — an explicit null CLEARS the override and returns the position to
  // inheriting the global, same `in`-check contract as the fields above (an
  // omitted key must not touch the stored value).
  if ('premiumStopPct' in patch) body.premiumStopPct = patch.premiumStopPct;
  if ('activeTpMethod' in patch) body.activeTpMethod = patch.activeTpMethod;
  if ('resolvedTpPrice' in patch) body.resolvedTpPrice = floorStop(patch.resolvedTpPrice);
  if ('resolvedTpUpdatedAt' in patch) body.resolvedTpUpdatedAt = patch.resolvedTpUpdatedAt;
  if ('alertOverrides' in patch) body.alertOverrides = patch.alertOverrides;
  if ('targets' in patch) body.targets = patch.targets;
  if ('contracts' in patch) {
    body.qty = patch.contracts;
    body.portfolioValue = accountValue();
  }
  return Object.keys(body).length > 0 ? body : null;
}

async function patchPosition(
  recId: string,
  payload: Record<string, unknown>,
): Promise<{
  ok: boolean;
  detail?: string;
  adjustedQty?: number;
  targets?: TargetLevel[];
  contracts?: number;
  entryPrice?: number;
  exposureBreach?: string;
}> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      // `qty` is the size the server stores (PortfolioPositionSchema.qty).
      const { adjustedQty, targets, qty, entryPrice, exposureBreach } = body as {
        adjustedQty?: number; targets?: unknown; qty?: unknown; entryPrice?: unknown; exposureBreach?: unknown;
      };
      return {
        ok: true,
        ...(typeof adjustedQty === 'number' ? { adjustedQty } : {}),
        ...(Array.isArray(targets) ? { targets: targets as TargetLevel[] } : {}),
        ...(typeof qty === 'number' ? { contracts: qty } : {}),
        ...(typeof entryPrice === 'number' && Number.isFinite(entryPrice) ? { entryPrice } : {}),
        ...(typeof exposureBreach === 'string' && exposureBreach ? { exposureBreach } : {}),
      };
    }
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: errorDetail(body, res.status) };
  } catch {
    return { ok: false, detail: 'Could not reach the backend — edit was not saved.' };
  }
}

const REMOTE_PATCH_DEBOUNCE_MS = 600;

type PendingPatch = {
  timer: ReturnType<typeof setTimeout>;
  payload: Record<string, unknown>;
  symbol: string;
  contract: string;
  /** `_rungEditSeq` for this recId when this payload was last merged. */
  rungSeq: number;
};

// Debounces `updatePosition` edits per recId so rapid keystrokes in the drawer
// coalesce into one PATCH instead of one per keystroke. Module-level (not store
// state) — timers are not serializable Zustand state, and this is purely
// network-scheduling plumbing, not UI state.
const _pendingPatches = new Map<string, PendingPatch>();

// Counts, per recId, the edits that touch the rungs or the size (`targets` or
// `qty`). The backend caps stored rungs at the held qty on such a PATCH (open
// question 54), so its response carries the rungs it stored -- adopted only
// when no later rung/size edit exists, pending OR in flight; a later one gets
// its own capped response.
const _rungEditSeq = new Map<string, number>();

// Tracks the in-flight PATCH request for a recId, from the moment it leaves
// `_pendingPatches` (debounce fired) until its response settles. Two jobs:
//  1. A second edit arriving mid-flight awaits this promise before sending its
//     own PATCH, so responses can never resolve out of order and silently let
//     an older edit overwrite a newer one.
//  2. `syncFromBackend`'s poll guard checks this alongside `_pendingPatches` —
//     without it, the poll's stale-value protection ends the instant the
//     debounce timer fires, not once the request actually completes.
const _inFlightPatches = new Map<string, Promise<void>>();

// A rejected added fill must show the server row. The in-flight guard would
// otherwise keep the pre-fill quantity and hide a base that moved.
const _fillRejectionResync = new Set<string>();

/** Recompute mark P&L the same way the drawer's current-price edit does.
 *  A missing quote stays a missing quote: 0 is not a price. */
function withFillEconomics(row: PortfolioPosition, entry: number, qty: number): PortfolioPosition {
  const next: PortfolioPosition = { ...row, entryPrice: entry, contracts: qty };
  if (row.quoteUnavailable || !(row.currentPrice > 0) || !(entry > 0)) {
    return { ...next, pnlDollar: 0, pnlPct: 0 };
  }
  const mult = row.contract.endsWith('|STOCK') ? 1 : 100;
  const pnlDollar = (row.currentPrice - entry) * mult * qty;
  const pnlPct = ((row.currentPrice - entry) / entry) * 100;
  return { ...next, pnlDollar, pnlPct };
}

/** Keep fields a newer unsent edit already changed; the rejected fill's
 *  quantity and entry come from the server. */
function overlayPendingDraft(
  server: PortfolioPosition,
  local: PortfolioPosition,
  payload: Record<string, unknown>,
): PortfolioPosition {
  const next: PortfolioPosition = { ...server };
  if ('stop' in payload) next.stop = local.stop;
  if ('structuralStop' in payload) next.structuralStop = local.structuralStop;
  if ('exitPlan' in payload) next.exitPlan = local.exitPlan;
  if ('maxLossOverride' in payload) next.maxLossOverride = local.maxLossOverride;
  if ('premiumStopPct' in payload) next.premiumStopPct = local.premiumStopPct;
  if ('activeTpMethod' in payload) next.activeTpMethod = local.activeTpMethod;
  if ('resolvedTpPrice' in payload) next.resolvedTpPrice = local.resolvedTpPrice;
  if ('resolvedTpUpdatedAt' in payload) next.resolvedTpUpdatedAt = local.resolvedTpUpdatedAt;
  if ('alertOverrides' in payload) next.alertOverrides = local.alertOverrides;
  if ('targets' in payload) next.targets = local.targets;
  if ('qty' in payload) next.contracts = local.contracts;
  return next;
}

async function _flushOne(recId: string): Promise<void> {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  _pendingPatches.delete(recId);

  const previous = _inFlightPatches.get(recId);

  const run = async (): Promise<void> => {
    if (previous) await previous.catch(() => {});
    const result = await patchPosition(recId, entry.payload);
    // `cancelPendingPositionPatch` (called by closePosition/closePositionRemote)
    // only drops a not-yet-sent debounced edit — it can't cancel one already
    // in flight. If the position was closed while this PATCH was in the air,
    // the edit is moot: don't surface a "could not be saved" toast for a row
    // the user just successfully closed, and don't bother resyncing it back.
    const stillOpen = usePortfolioStore.getState().positions.some((p) => p.recId === recId);
    if (!stillOpen) return;
    if (!result.ok) {
      usePortfolioStore.setState({
        lastSyncError: {
          symbol: entry.symbol,
          contract: entry.contract,
          detail: result.detail ?? 'Edit could not be saved',
          at: Date.now(),
        },
      });
      // The optimistic update `updatePosition` already applied locally was
      // never true — the backend rejected it (e.g. the exposure gate on a qty
      // increase). Force a resync so the drawer/table snap back to whatever
      // the backend actually holds, rather than keeping the rejected value
      // on screen until the next 30s poll happens to run.
      void usePortfolioStore.getState().syncFromBackend(true);
      return;
    }
    // The rungs the backend stored (capped at the held qty, open question 54),
    // considered only for the latest rung/size edit -- see `_rungEditSeq`.
    const serverRungs = ('targets' in entry.payload || 'qty' in entry.payload)
      && (_rungEditSeq.get(recId) ?? 0) === entry.rungSeq
      ? result.targets : undefined;
    if (result.adjustedQty != null) {
      // The backend's exposure gate approved the qty increase at a SMALLER size
      // than requested (mirrors addPosition's own adjustedQty handling above).
      // Correct the local value immediately rather than leaving the drawer show
      // the requested size until the next 30s sync poll silently snaps it back
      // with no explanation — same failure mode Step 4 below prevents for an
      // in-flight edit, but this is a resolved edit the poll would otherwise
      // still be free to overwrite without warning.
      // The server resized the row, so its rungs (scaled to the booked size,
      // open question 54) replace the local ones -- the one case where stored
      // rungs are written back, because the user did not type this size.
      usePortfolioStore.setState((s) => ({
        positions: s.positions.map((p) =>
          p.recId === recId
            ? { ...p, contracts: result.adjustedQty, ...(serverRungs ? { targets: serverRungs } : {}) }
            : p
        ),
        lastSyncError: {
          symbol: entry.symbol,
          contract: entry.contract,
          detail: `Size reduced to ${result.adjustedQty} contracts to fit your exposure limit.`,
          at: Date.now(),
        },
      }));
    } else if (serverRungs && Array.isArray(entry.payload.targets)) {
      // No resize: the rungs on screen are what the user TYPED, and are never
      // overwritten with the capped ones -- a rung edit can be over-planned
      // mid-typing (60/50 of 100 before rung 2 is changed), and writing the
      // cap back made the next keystroke build on it (open question 54, X1).
      // Every rung/size edit sends the local rungs, so the next one heals an
      // intermediate cap. Only SAY what was stored, when it differs from what
      // was sent, against the size the server holds.
      const sells = (ts: TargetLevel[]) => JSON.stringify(ts.map((t) => t.contractsToSell ?? null));
      if (sells(entry.payload.targets as TargetLevel[]) !== sells(serverRungs)) {
        const held = result.contracts;
        usePortfolioStore.setState({
          lastSyncError: {
            symbol: entry.symbol,
            contract: entry.contract,
            detail: `Sell targets plan to sell more than the ${held ?? ''}${held != null ? ' ' : ''}held — `
              + 'saved scaled down to fit until you change them.',
            at: Date.now(),
          },
        });
      }
    }
  };

  const promise = run().finally(() => {
    if (_inFlightPatches.get(recId) === promise) _inFlightPatches.delete(recId);
  });
  _inFlightPatches.set(recId, promise);
  return promise;
}

function scheduleRemotePositionPatch(
  recId: string,
  symbol: string,
  contract: string,
  payload: Record<string, unknown>,
): void {
  const existing = _pendingPatches.get(recId);
  if (existing) clearTimeout(existing.timer);
  const merged = { ...(existing?.payload ?? {}), ...payload };
  if ('targets' in payload || 'qty' in payload) _rungEditSeq.set(recId, (_rungEditSeq.get(recId) ?? 0) + 1);
  const rungSeq = _rungEditSeq.get(recId) ?? 0;
  const timer = setTimeout(() => { void _flushOne(recId); }, REMOTE_PATCH_DEBOUNCE_MS);
  _pendingPatches.set(recId, { timer, payload: merged, symbol, contract, rungSeq });
}

/** Sends a pending debounced edit immediately instead of waiting out the
 *  debounce window — called when the drawer closes (or switches to editing a
 *  different row) so a fast edit-then-navigate is never silently dropped.
 *  With no `recId`, flushes every pending edit. */
export function flushPendingPositionPatches(recId?: string): void {
  const ids = recId ? [recId] : Array.from(_pendingPatches.keys());
  for (const id of ids) {
    const entry = _pendingPatches.get(id);
    if (!entry) continue;
    clearTimeout(entry.timer);
    void _flushOne(id);
  }
}

/** Send one added fill now. A queued companion edit (a stop, a decrease)
 *  lands first, then `expectedQty` is the base that edit left behind. */
async function sendAddedFill(
  contract: string,
  totalQty: number,
  fillPrice: number,
): Promise<{ ok: boolean; detail?: string }> {
  if (!Number.isInteger(totalQty) || totalQty < 1 || !(Number.isFinite(fillPrice) && fillPrice > 0)) {
    return { ok: false, detail: 'added_fill_price_required' };
  }
  const initial = usePortfolioStore.getState().positions.find((p) => p.contract === contract);
  if (!initial?.recId) return { ok: false, detail: 'Position is not open.' };
  const recId = initial.recId;

  const queued = _pendingPatches.get(recId);
  if (queued) {
    clearTimeout(queued.timer);
    await _flushOne(recId);
  }

  const previous = _inFlightPatches.get(recId);
  let outcome: { ok: boolean; detail?: string } = { ok: false, detail: 'Edit could not be saved' };
  const run = async (): Promise<void> => {
    if (previous) await previous.catch(() => {});
    const latest = usePortfolioStore.getState().positions.find((p) => p.recId === recId);
    if (!latest) { outcome = { ok: false, detail: 'Position is not open.' }; return; }
    const expectedQty = latest.contracts ?? 1;
    if (totalQty <= expectedQty) { outcome = { ok: false, detail: 'not_an_increase' }; return; }

    _rungEditSeq.set(recId, (_rungEditSeq.get(recId) ?? 0) + 1);
    const rungSeq = _rungEditSeq.get(recId) ?? 0;
    const payload: Record<string, unknown> = {
      qty: totalQty,
      addedFillPrice: fillPrice,
      expectedQty,
      portfolioValue: accountValue(),
      ...(Array.isArray(latest.targets) ? { targets: latest.targets } : {}),
    };
    const result = await patchPosition(recId, payload);
    const stillOpen = usePortfolioStore.getState().positions.some((p) => p.recId === recId);
    if (!stillOpen) { outcome = { ok: false, detail: 'Position is not open.' }; return; }
    if (!result.ok) {
      usePortfolioStore.setState((s) => ({
        lastSyncError: {
          symbol: latest.symbol,
          contract: latest.contract,
          detail: result.detail ?? 'Edit could not be saved',
          at: Date.now(),
        },
        lastExposureBreach: s.lastExposureBreach?.contract === latest.contract ? null : s.lastExposureBreach,
      }));
      _fillRejectionResync.add(recId);
      try {
        await usePortfolioStore.getState().syncFromBackend(true);
      } finally {
        _fillRejectionResync.delete(recId);
      }
      outcome = { ok: false, detail: result.detail ?? 'Edit could not be saved' };
      return;
    }
    const qty = typeof result.contracts === 'number' ? result.contracts : totalQty;
    const adoptRungs = (_rungEditSeq.get(recId) ?? 0) === rungSeq ? result.targets : undefined;
    usePortfolioStore.setState((s) => ({
      positions: s.positions.map((p) => {
        if (p.recId !== recId) return p;
        const priced = typeof result.entryPrice === 'number'
          ? withFillEconomics(p, result.entryPrice, qty)
          : { ...p, contracts: qty };
        return adoptRungs ? { ...priced, targets: adoptRungs } : priced;
      }),
      lastExposureBreach: result.exposureBreach
        ? { symbol: latest.symbol, contract: latest.contract, detail: result.exposureBreach, at: Date.now() }
        : (s.lastExposureBreach?.contract === latest.contract ? null : s.lastExposureBreach),
    }));
    outcome = { ok: true };
  };

  const promise = run().finally(() => {
    if (_inFlightPatches.get(recId) === promise) _inFlightPatches.delete(recId);
  });
  _inFlightPatches.set(recId, promise);
  await promise;
  return outcome;
}

/** Drops a pending debounced edit without sending it — used when the position
 *  is being deleted (closePosition/closePositionRemote), so a stale PATCH
 *  never races a DELETE for the same recId. */
function cancelPendingPositionPatch(recId: string): void {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  clearTimeout(entry.timer);
  _pendingPatches.delete(recId);
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

/* The backend enforces one open position per contract (409 on a second POST),
 * so `contract` — not `recId` — is a position's identity. Dedupe on it, keeping
 * the earliest record, which is the one the backend accepted. */
function dedupePositions(positions: PortfolioPosition[]): PortfolioPosition[] {
  const map = new Map<string, PortfolioPosition>();
  for (const p of positions) {
    const existing = map.get(p.contract);
    if (!existing) {
      map.set(p.contract, p);
    } else {
      const existingTime = existing.orderedAt ?? existing.entryDate ?? '';
      const incomingTime = p.orderedAt ?? p.entryDate ?? '';
      if (incomingTime < existingTime) {
        map.set(p.contract, p);
      }
    }
  }
  return Array.from(map.values());
}

function validatePositions(positions: unknown): PortfolioPosition[] {
  if (!Array.isArray(positions)) return [];
  return positions.filter((p): p is PortfolioPosition => {
    if (typeof p !== 'object' || p === null) return false;
    const po = p as Record<string, unknown>;
    return (
      typeof po.recId === 'string' &&
      typeof po.symbol === 'string' &&
      typeof po.contract === 'string'
    );
  });
}

/** Persist migration. Legacy rows (persisted before sync tracking existed) have
 *  no syncStatus. Tag them synced with syncedAt=0 so the authoritative reconcile
 *  drops them if the backend does not have them (clears old phantom rows), while
 *  a row the backend DOES have is simply confirmed on the next sync. */
export function migratePortfolioPersist(state: unknown, version: number): unknown {
  const s = state as { positions?: unknown } | undefined;
  if (!s || !Array.isArray(s.positions)) return state;
  return {
    ...s,
    positions: s.positions.map((p) => {
      const po = p as Record<string, unknown>;
      const synced = po.syncStatus ? po : { ...po, syncStatus: 'synced', syncedAt: 0 };
      // A row saved to localStorage before the stop=0 fix (round 2 onward) can
      // still hold a literal 0 — floor it here too, not just on the live write
      // paths, since this rehydrates straight into state on every app load,
      // before syncFromBackend has had a chance to overwrite it with a clean
      // backend value. See floorStop's own comment for why 0 is never real.
      const floored = { ...synced } as Record<string, unknown>;
      if ('stop' in floored) floored.stop = floorStop(floored.stop as number | null | undefined);
      if ('structuralStop' in floored) floored.structuralStop = floorStop(floored.structuralStop as number | null | undefined);
      // v2 -> v3, piece 4. Normalise the per-position premium stop to the
      // shape the resolver expects, and drop `premiumStopDollar`.
      //
      // Both are benign by luck rather than design: a v2 row has neither key,
      // and `undefined` already reads as "inherit the global". CLAUDE.md asks
      // for the bump and the branch anyway, and the reason is visible here --
      // stating it costs two lines, while the next reader otherwise has to
      // re-derive that `undefined` is safe by reading resolvePremiumStopPct.
      //
      // `premiumStopDollar` is a CREATE-ONLY transport field: the server
      // divides it by the persisted entry price and stores the fraction, so
      // keeping it on a synced row persists a number that no longer describes
      // the position and that nothing reads back.
      //
      // P2-07 -- each version step is gated by the version it upgrades from.
      // The synced-row `premiumStopDollar` clean-up moved to the v5 -> v6 step
      // below, which covers every older version too.
      if (version < 3 && floored.premiumStopPct === undefined) floored.premiumStopPct = null;
      // v3 -> v4, ROUND 10 finding 16. `stopIsUserSet` was added to
      // PortfolioPosition (a persisted shape) with no version bump, which is
      // the same omission PROJECT_STATE records round 3 catching on this very
      // store -- and CLAUDE.md's rule was written after that.
      //
      // Benign, and stated rather than left to be re-derived: a v3 row has no
      // such key, `toBackendPayload` sends `?? false`, and false is exactly
      // what an existing row means -- its stop came from a plan, so the server
      // SHOULD keep re-anchoring it. Normalising here rather than relying on
      // the `??` keeps the persisted shape honest about itself.
      if (version < 4 && floored.stopIsUserSet === undefined) floored.stopIsUserSet = false;
      // v4 -> v5, ROUND 1 finding (b). Phase A split `ivRank` (a true
      // percentile) from `iv` (the absolute level); a row persisted before
      // that carries ONE number of unknown basis under the percentile's name,
      // so the portfolio table would print "IV rank 45" for what is most
      // likely a 45% absolute IV. Dropped rather than guessed -- see
      // stripLegacyIvFields in lib/ivBasis.ts for why.
      //
      // NOTE this is the only branch here that is NOT idempotent, hence the
      // version gate: run unconditionally it would throw away the genuine
      // `ivRank` a post-split row does carry, on every single load.
      //
      // Worse here than in scanStore: `syncFromBackend` overwrites these
      // fields only on rows the reconcile confirms against the backend, so on
      // a row it keeps as pending/offline the stale figure would never be
      // replaced and the mislabel would be permanent.
      const ivClean = version < 5 ? (stripLegacyIvFields(floored) as Record<string, unknown>) : floored;
      // v5 -> v6, P2-06/P2-07. Two promotions to 'synced' (skipPost and the
      // ok path) kept `premiumStopDollar` on the row, and a v5 store never ran
      // the old unconditional clean-up again. Idempotent.
      if (version < 6 && ivClean.syncStatus === 'synced') delete ivClean.premiumStopDollar;
      // v6 -> v7, STOCKS-HORIZON-T1 H6. `holdMaxDays` joins the persisted
      // shape; a stored row predates the hold, so it has none (null = never a
      // stock time stop) until the next sync reads the backend's value.
      if (version < 7 && ivClean.holdMaxDays === undefined) ivClean.holdMaxDays = null;
      return ivClean;
    }),
  };
}

// Dedupes concurrent closePositionRemote calls for the same recId — without
// this, a double-click or slow-network retry can send two overlapping close
// requests; the second one's 404-drift-recovery branch can then re-persist
// the position the first call just closed.
const _inFlightCloses = new Map<string, Promise<{ ok: boolean; detail?: string }>>();

// Dedupes overlapping syncFromBackend calls. The reconcile now awaits POST
// retries for pending rows, so two concurrent syncs (portfolio + dashboard 30s
// intervals, or two tabs) could each read the same snapshot and clobber each
// other's final write. A single shared in-flight promise serializes them.
let _syncInFlight: Promise<boolean> | null = null;

export const usePortfolioStore = create<PortfolioStoreState>()(
  persist(
    (set) => ({
      positions: [],
      lastSyncError: null,
      lastExposureBreach: null,
      lastPremiumStopDropped: null,
      premiumStopDropQueue: [],
      // ROUND 10 finding 14 -- these clear SEPARATELY. One action wiping both
      // meant dismissing the (informational) premium-stop notice also silently
      // dropped the (rejection) sync error the user may not have read yet.
      clearSyncError: () => set({ lastSyncError: null }),
      clearPremiumStopDropped: () => set((s) => {
        const queue = s.premiumStopDropQueue.slice(1);
        return { premiumStopDropQueue: queue, lastPremiumStopDropped: queue[0] ?? null };
      }),
      hydrate: (positions) =>
        set({
          positions: positions.map((p) => ({
            ...((p as PortfolioPosition).recId ? p : { ...p, recId: generateRecId() }),
            stop: floorStop(p.stop),
            structuralStop: floorStop(p.structuralStop),
          })),
        }),
      addPosition: async (p, opts) => {
        const recId = (p as PortfolioPosition & { recId?: string }).recId || generateRecId();
        const value = accountValue();

        // Capture — inside the optimistic set — which row to promote on success
        // and exactly how to undo the mutation on a hard rejection:
        //  - insert  → remove the new row (identified by recId)
        //  - replace → restore the prior row that shared this recId
        //  - merge   → restore the prior same-contract row (undoes the count bump)
        // Capturing closures here avoids reading a nested-reassigned flag in the
        // outer scope (which TS narrows to its initializer).
        let promoteRecId = recId;
        let didMerge = false;
        let rollback: (positions: PortfolioPosition[]) => PortfolioPosition[] =
          (positions) => positions.filter((x) => x.recId !== recId);

        set((s) => {
          const incoming: PortfolioPosition = {
            ...p, recId, syncStatus: 'pending', syncPendingSince: Date.now(),
            // Round-6 audit finding: this optimistic write landed the caller's
            // raw stop/structuralStop straight into live state, unfloored —
            // paperTrade.ts's buildPaperStockPosition() sends stop: 0 for
            // every paper stock buy, and this was the one write site that
            // let it straight through to a real false STOP_REACHED on the
            // dashboard before the next sync corrected it.
            stop: floorStop(p.stop),
            structuralStop: floorStop(p.structuralStop),
          };

          const idxByRecId = s.positions.findIndex((x) => x.recId === recId);
          if (idxByRecId >= 0) {
            const prev = s.positions[idxByRecId]!;
            promoteRecId = recId;
            rollback = (positions) => positions.map((x) => (x.recId === prev.recId ? prev : x));
            const next = [...s.positions];
            next[idxByRecId] = { ...prev, ...incoming };
            return { positions: next };
          }
          const idxByKey = s.positions.findIndex(
            (x) => x.symbol === incoming.symbol && x.contract === incoming.contract,
          );
          if (idxByKey >= 0) {
            // eslint-disable-next-line no-console
            console.warn('[portfolioStore] merging duplicate position for', incoming.symbol, incoming.contract);
            const prev = s.positions[idxByKey]!;
            promoteRecId = prev.recId;
            didMerge = true;
            rollback = (positions) => positions.map((x) => (x.recId === prev.recId ? prev : x));
            const next = [...s.positions];
            next[idxByKey] = { ...prev, contracts: (prev.contracts ?? 0) + (incoming.contracts ?? 0) };
            return { positions: next };
          }
          promoteRecId = recId;
          rollback = (positions) => positions.filter((x) => x.recId !== recId);
          return { positions: [...s.positions, incoming] };
        });

        if (opts?.skipPost) {
          // Caller already got a genuine, backend-confirmed successful response
          // from its own persistPosition call (never the offline-optimistic
          // fallback — see persistPosition's `offline` field) — just promote
          // the optimistic row to synced without a second POST.
          // P2-06 -- `premiumStopDollar` is create-only transport and is
          // dropped on the way to 'synced', as on every other promotion.
          set((s) => ({
            positions: s.positions.map((x) => {
              if (x.recId !== promoteRecId) return x;
              const { premiumStopDollar: _createOnly, ...rest } = x;
              void _createOnly;
              return { ...rest, syncStatus: 'synced' as const, syncedAt: Date.now(), syncPendingSince: undefined };
            }),
          }));
          return { ok: true, status: 'ok' as const };
        }

        const outcome = await postPosition({ ...p, recId } as PortfolioPosition, value);

        // A 409 on a MERGE means the backend refused a scale-in (it keeps one open
        // position per contract — no add-to-existing). Don't report the local qty
        // bump as saved: roll it back and surface it, so the UI never shows a
        // quantity the backend rejected (which the next sync would silently revert).
        const scaleInRefused = outcome.kind === 'duplicate' && didMerge;

        if ((outcome.kind === 'ok' || outcome.kind === 'duplicate') && !scaleInRefused) {
          const adjustedQty = outcome.kind === 'ok' ? outcome.adjustedQty : undefined;
          set((s) => ({
            positions: s.positions.map((x) => {
              if (x.recId !== promoteRecId) return x;
              // P2-06 -- drop the create-only `premiumStopDollar` on the way
              // to 'synced', matching the other promotions.
              const { premiumStopDollar: _createOnly, ...rest } = x;
              void _createOnly;
              const promoted: PortfolioPosition = {
                    ...rest,
                    syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined,
                    // The backend's risk check auto-reduced the size to fit exposure
                    // limits — reflect the persisted quantity locally, don't keep
                    // showing what was requested. Skipped on a MERGE: the POST only
                    // ever sends the incoming increment (not the locally-summed
                    // total), so adjustedQty there describes that increment alone —
                    // overwriting the already-merged `contracts` with it would be
                    // wrong, not just imprecise. The caller is still told via the
                    // returned adjustedQty below; only the merged local total is left
                    // untouched, same as before this fix, to be corrected by the next
                    // authoritative sync.
                    ...(adjustedQty != null && !didMerge ? { contracts: adjustedQty } : {}),
                    // Piece 4 — adopt the server's derived fraction now rather
                    // than waiting for the next syncFromBackend, so the local
                    // alert engine and the backend generator resolve this
                    // position to the same percentage from the first scan.
                    // Skipped on a MERGE for the same reason as `contracts`:
                    // the POST described the incoming increment, not the row
                    // that already existed.
                    ...(!didMerge && outcome.kind === 'ok'
                      ? { premiumStopPct: outcome.premiumStopPct ?? null }
                      : {}),
              };
              // The entry that fraction is relative to. Adopting one without
              // the other is what makes the two engines fire at different
              // prices -- see applyPersistedPosition, and round 10's note
              // there on why this is "when reported" rather than "or
              // neither". withServerEntry also resets the mark (P2-09).
              return !didMerge && outcome.kind === 'ok'
                ? withServerEntry(promoted, outcome.entryPrice)
                : promoted;
            }),
          }));
          // ROUND 9 -- report a premium stop the server could not apply, the
          // same signal applyPersistedPosition gives its two callers. The
          // router logs a warning and the row silently inherits the global,
          // which is TIGHTER than what was asked for, and the router's own
          // comment concedes "nothing on screen says why". Reachable through
          // an ordinary fill: a $4.50 stop typed against a $5.20 mid, filled
          // at $4.20.
          // STOP-SEMANTICS -- a fraction-only create counts too, and the
          // reason travels with it. `premiumStopDropped` stays the dollar
          // (null for a fraction-only create); a drop is signalled by
          // `premiumStopDropReason`, which is set exactly when one happened.
          const drop = outcome.kind === 'ok'
            ? premiumStopDropOf(p, outcome.premiumStopPct, outcome.entryPrice)
            : null;
          return {
            ok: true, status: 'ok' as const, adjustedQty,
            premiumStopDropped: drop?.requestedDollar ?? undefined,
            premiumStopDropReason: drop?.reason,
            premiumStopKeptPct: drop?.keptPct,
          };
        }
        if (outcome.kind === 'rejected' || scaleInRefused) {
          const detail = outcome.kind === 'rejected'
            ? outcome.detail
            : 'A position for this contract is already open — scale-in is not supported.';
          set((s) => ({
            positions: rollback(s.positions),
            lastSyncError: { symbol: p.symbol, contract: p.contract, detail, at: Date.now() },
          }));
          return { ok: false, status: 'rejected' as const, detail };
        }
        // network — leave the row pending; the reconcile retries it. Never silently dropped.
        return { ok: false, status: 'pending' as const, detail: 'queued — will retry when the backend is reachable' };
      },
      updatePosition: (contract, patch) => {
        // Floor stop/structuralStop once, up front, so the SAME value lands
        // in both the optimistic local state below and the network payload —
        // relying on every future call site to remember its own inline
        // coercion (as the drawer's EditField does today) is exactly the gap
        // that produced the round-2 stop=0 bug.
        const flooredPatch: Partial<PortfolioPosition> = { ...patch };
        if ('stop' in flooredPatch) flooredPatch.stop = floorStop(flooredPatch.stop);
        if ('structuralStop' in flooredPatch) flooredPatch.structuralStop = floorStop(flooredPatch.structuralStop);

        // Capture the pre-patch row during the set() updater (the same closure
        // pattern closePosition below already uses), but fire the network side
        // effect AFTER set() returns rather than from inside the updater —
        // every other action in this file (closePosition, addPosition) does
        // its network call after the state update, not inside it.
        let target: PortfolioPosition | undefined;
        set((s) => {
          target = s.positions.find((r) => r.contract === contract);
          return {
            positions: s.positions.map((r) =>
              r.contract === contract ? { ...r, ...flooredPatch } : r
            ),
          };
        });
        if (target) {
          // A size edit carries the row's current rungs (open question 54):
          // the backend caps stored rungs at the stored qty, so an
          // intermediate size typed on the way to the final one (6 while
          // typing 60) can cap them -- resending the local rungs with the
          // next size keystroke restores them. The local rungs are never
          // overwritten with a cap (see _flushOne).
          const sendPatch: Partial<PortfolioPosition> =
            'contracts' in flooredPatch && !('targets' in flooredPatch) && Array.isArray(target.targets)
              ? { ...flooredPatch, targets: target.targets }
              : flooredPatch;
          const payload = toUpdatePayload(sendPatch);
          if (payload) scheduleRemotePositionPatch(target.recId, target.symbol, target.contract, payload);
        }
      },
      confirmAddedFill: (contract, totalQty, fillPrice) => sendAddedFill(contract, totalQty, fillPrice),
      closePosition: (contract) => {
        let closedRecId: string | undefined;
        set((s) => {
          closedRecId = s.positions.find((r) => r.contract === contract)?.recId;
          return { positions: s.positions.filter((r) => r.contract !== contract) };
        });
        if (closedRecId) {
          cancelPendingPositionPatch(closedRecId);
          deletePosition(closedRecId);
        }
      },
      closePositionRemote: async (recId, opts) => {
        const existing = _inFlightCloses.get(recId);
        if (existing) return existing;

        const run = async (): Promise<{ ok: boolean; detail?: string }> => {
          cancelPendingPositionPatch(recId);
          const doClose = async (id: string): Promise<Response> =>
            fetch(`${_BASE_URL()}/api/portfolio/${id}/close`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                qtyToClose: opts.qtyToClose ?? null,
                exitPrice: opts.exitPrice ?? null,
                exitDate: opts.exitDate ?? null,
                sendToBroker: opts.sendToBroker ?? false,
              }),
            });
          const local = usePortfolioStore.getState().positions.find((p) => p.recId === recId);

          // Fetch the authoritative open positions, or null if the backend is
          // unreachable / errors. Used to decide recId drift vs a genuinely-gone
          // position WITHOUT guessing from a persist failure code.
          const fetchRemote = async (): Promise<BackendPosition[] | null> => {
            try {
              const r = await fetch(`${_BASE_URL()}/api/portfolio`);
              if (!r.ok) return null;
              return (await r.json()) as BackendPosition[];
            } catch {
              return null;
            }
          };

          // Tracks whichever recId the successful close actually landed under —
          // starts as the caller's id, but drift recovery below may retry against
          // the backend's real id instead. Anything restored to local state after
          // a successful close must use THIS id, not the original parameter, or a
          // drift-recovered restore would carry a recId that 404s on every
          // subsequent action until the next sync heals it.
          let effectiveRecId = recId;

          try {
            let res = await doClose(recId);

            // A 404 means the backend has no open position under this recId:
            // either the original POST never landed, or the backend holds the same
            // *contract* under a different recId (drift, e.g. a DB reset while
            // localStorage kept the old id). Recover carefully — and only drop a
            // local row when the backend POSITIVELY confirms the contract is gone.
            if (res.status === 404 && local) {
              const persisted = await persistPosition(local);
              if (persisted.ok) {
                res = await doClose(recId);
              } else {
                const remote = await fetchRemote();
                if (remote) {
                  const match = remote.find((p) => p.contract === local.contract);
                  if (match?.recId && match.recId !== recId) {
                    effectiveRecId = match.recId;
                    res = await doClose(match.recId);            // drift: close the real row
                  } else if (!match) {
                    // Backend reachable AND has no such contract → genuinely gone.
                    set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
                    return {
                      ok: false,
                      detail: 'This position was no longer on the server (already closed or cleared) — removed it from your list.',
                    };
                  }
                  // match with same recId shouldn't 404 — fall through to the error below.
                }
                // Backend unreachable: do NOT drop a possibly-valid position.
              }
            }

            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              return { ok: false, detail: errorDetail(body, res.status) };
            }

            // Success: remove the acted-upon local row so a fully-closed position
            // can't linger via syncFromBackend's localOnly retention (its contract
            // is now absent from the backend). A partial close re-appears from the
            // authoritative pull below with its reduced qty.
            const closedRow = usePortfolioStore.getState().positions.find((p) => p.recId === recId);
            const wasFullClose = !opts.qtyToClose || opts.qtyToClose >= (closedRow?.contracts ?? 1);
            set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
            // Force a fresh GET that post-dates this close — must not be satisfied
            // by an in-flight sync whose GET predates it (would resurrect the row).
            const synced = await usePortfolioStore.getState().syncFromBackend(true);
            // The close itself succeeded server-side regardless of this GET. But if
            // it was only a PARTIAL close and the follow-up pull failed (network),
            // the row above is now gone from local state with no way to learn its
            // reduced qty until the next successful sync — restore it locally
            // (qty adjusted, price/P&L stale until next sync) rather than making a
            // still-open position disappear from the list entirely.
            if (!synced && !wasFullClose && closedRow) {
              const remainingQty = Math.max(0, (closedRow.contracts ?? 1) - (opts.qtyToClose ?? 0));
              if (remainingQty > 0) {
                // Restore under effectiveRecId (the id the backend actually closed
                // against) — if drift recovery kicked in above, the backend no
                // longer recognizes the original `recId`, and restoring under the
                // stale id would just 404 again on the next action.
                set((s) => ({ positions: [...s.positions, { ...closedRow, recId: effectiveRecId, contracts: remainingQty }] }));
              }
            }
            return { ok: true };
          } catch (e) {
            return { ok: false, detail: e instanceof Error ? e.message : 'Network error' };
          }
        };

        const promise = run().finally(() => _inFlightCloses.delete(recId));
        _inFlightCloses.set(recId, promise);
        return promise;
      },
      syncFromBackend: async (force = false) => {
        const run = async (): Promise<boolean> => {
          const fetchStartedAt = Date.now();
          try {
            const res = await fetch(`${_BASE_URL()}/api/portfolio`);
            if (!res.ok) return false;
            const remote: BackendPosition[] = await res.json();
            const localForPending = usePortfolioStore.getState().positions;
            const remotePositions = remote.map(fromBackend).map((rp) => {
              const pending = _pendingPatches.get(rp.recId);
              const inFlight = _inFlightPatches.has(rp.recId);
              if (!pending && !inFlight) return rp;
              const local = localForPending.find((p) => p.recId === rp.recId) ?? rp;
              // A rejected added fill has no saved quantity to protect. A
              // newer companion edit still waiting in `pending` is kept.
              if (_fillRejectionResync.has(rp.recId)) {
                return pending ? overlayPendingDraft(rp, local, pending.payload) : rp;
              }
              // An edit for this row is debounced, or its PATCH is still in
              // flight, and hasn't been confirmed by the backend yet — keep
              // the local value instead of snapping a focused input back to
              // what the server still has.
              return local;
            });
            const remoteContracts = new Set(remotePositions.map((p) => p.contract));

            const snapshot = usePortfolioStore.getState().positions;
            const snapshotRecIds = new Set(snapshot.map((p) => p.recId));
            const localAbsent = snapshot.filter(
              (p) => p.recId && !remoteContracts.has(p.contract),
            );

            const keep: PortfolioPosition[] = [];
            for (const p of localAbsent) {
              if (p.syncStatus === 'pending') {
                // Retry the save. Never silently drop a pending row: on success
                // promote it, on a hard rejection surface it, on network keep it.
                const outcome = await postPosition(p, accountValue());
                if (outcome.kind === 'ok' || outcome.kind === 'duplicate') {
                  // Fold the SERVER-DERIVED premiumStopPct onto the row, the
                  // same way addPosition and applyPersistedPosition do. This
                  // path was missed: a row created while the backend was
                  // unreachable went pending, and this 30s retry saved it
                  // successfully — but dropped the fraction the server derived
                  // from premiumStopDollar. The row stayed at `undefined`, so
                  // alertEngine.scanPortfolio resolved it to the GLOBAL while
                  // alert_generator used the per-position value, which is the
                  // two-engines-disagree window piece 4 exists to close. It
                  // self-healed only on the next GET.
                  // `duplicate` carries no body, so keep what the row has.
                  // `premiumStopDollar` is dropped on the way to 'synced',
                  // matching migratePortfolioPersist's rule for the same
                  // transition ("a CREATE-ONLY transport field ... keeping it
                  // on a synced row persists a number that no longer describes
                  // the position"). This retry is the one path that reached
                  // 'synced' without going through the migration, and since
                  // `version` is already 3 the migration never runs again to
                  // clean it up -- so the rule was broken by the same commit
                  // that wrote it. Inert today (nothing reads it back off a
                  // synced row), which is exactly why it has to be kept
                  // consistent rather than argued away.
                  const { premiumStopDollar: _createOnly, ...rest } = p;
                  void _createOnly;
                  // Say so when the server could not apply the stop this row
                  // asked for -- the fourth and last create path to get the
                  // notice the other three now have.
                  const drop = outcome.kind === 'ok'
                    ? premiumStopDropOf(p, outcome.premiumStopPct, outcome.entryPrice)
                    : null;
                  if (drop) {
                    // QUEUED, not first-wins (P2-08). This runs inside a
                    // for-loop over every queued row and on every 30s cycle;
                    // one banner names one position, so each later drop waits
                    // in the queue and shows when the one before it is
                    // dismissed -- a second drop is never silent.
                    set((s) => {
                      const queue = [...s.premiumStopDropQueue, {
                        symbol: p.symbol, contract: p.contract,
                        requestedDollar: drop.requestedDollar, reason: drop.reason,
                        keptPct: drop.keptPct,
                        at: Date.now(),
                      }];
                      return { premiumStopDropQueue: queue, lastPremiumStopDropped: queue[0] ?? null };
                    });
                  }
                  // ...and the entry it was derived against, the third and
                  // last site that adopts the server's fraction.
                  // `premiumStopPct` alone, over the client's own mid, is a
                  // DIFFERENT dollar stop from the one the user typed -- so
                  // all three sites take the entry whenever the response
                  // reports one (withServerEntry, which also resets the mark,
                  // P2-09), and keep the row's existing entry when it does not.
                  keep.push(withServerEntry({
                    ...rest,
                    premiumStopPct:
                      outcome.kind === 'ok' ? outcome.premiumStopPct ?? null : p.premiumStopPct,
                    syncStatus: 'synced',
                    syncedAt: Date.now(),
                    syncPendingSince: undefined,
                  }, outcome.kind === 'ok' ? outcome.entryPrice : null));
                } else if (outcome.kind === 'rejected') {
                  set({ lastSyncError: { symbol: p.symbol, contract: p.contract, detail: outcome.detail, at: Date.now() } });
                  // dropped — do not push
                } else {
                  keep.push(p); // network — stays pending, retried next cycle
                }
              } else if (typeof p.syncedAt === 'number' && p.syncedAt >= fetchStartedAt) {
                // Confirmed after this GET's snapshot could have been taken — keep
                // (the GET simply predates it); avoids the 30s-poll race dropping it.
                keep.push(p);
              } else {
                // A synced row confirmed before this snapshot but absent from the
                // backend is a genuine phantom (e.g. legacy row, DB reset) — drop it,
                // and cancel any edit still debounced for it so a stale PATCH doesn't
                // fire against a rec_id we just forgot.
                cancelPendingPositionPatch(p.recId);
              }
            }

            // Preserve any row inserted into the store DURING the awaited retry
            // loop above so a concurrent addPosition is not clobbered by our final
            // write. Key on recId (NOT contract): a legitimate re-add of a contract
            // that was a phantom in this run's snapshot has a NEW recId, so it must
            // survive even though its contract was in the snapshot.
            const accountedRecIds = new Set([...remotePositions, ...keep].map((x) => x.recId));
            set((s) => {
              const addedDuringSync = s.positions.filter(
                (x) => x.recId && !snapshotRecIds.has(x.recId) && !accountedRecIds.has(x.recId),
              );
              const positions = dedupePositions([...remotePositions, ...keep, ...addedDuringSync]);
              // P2-08 -- a notice whose contract is no longer held (closed)
              // names nothing; drop it so the next one can show.
              const held = new Set(positions.map((x) => x.contract));
              const queue = s.premiumStopDropQueue.filter((n) => held.has(n.contract));
              return { positions, premiumStopDropQueue: queue, lastPremiumStopDropped: queue[0] ?? null };
            });
            return true;
          } catch {
            // network unavailable — keep localStorage state untouched
            return false;
          }
        };

        // Concurrent-sync dedup. A non-forced caller (the 30s interval pollers)
        // shares any in-flight run. A forced caller (closePositionRemote, which
        // must observe a GET that post-dates its own write) SERIALIZES a fresh
        // run after the in-flight one rather than reusing its stale result.
        // NOTE: `_syncInFlight` must hold the SAME promise the finally callback
        // compares against, so attach `.finally` as a side-effect and store/return
        // the original promise — do not store the value `.finally()` returns.
        if (_syncInFlight && !force) return _syncInFlight;

        const started: Promise<boolean> = _syncInFlight
          ? _syncInFlight.catch(() => false).then(() => run()) // forced: chain after in-flight
          : run();
        _syncInFlight = started;
        started.finally(() => { if (_syncInFlight === started) _syncInFlight = null; });
        return started;
      },
      syncToBackend: async () => {
        // Push all local positions to the backend (409 = already there, safe to ignore).
        const { positions } = usePortfolioStore.getState();
        const value = accountValue();
        await Promise.all(positions.map((p) => postPosition(p, value)));
      },
    }),
    {
      name: 'bamendjou-portfolio-v1',
      version: 7,
      skipHydration: true,
      migrate: migratePortfolioPersist,
      partialize: (state) => ({ positions: state.positions }),
      merge: (persistedState, currentState) => {
        const ps = persistedState as Partial<PortfolioStoreState> | undefined;
        if (!ps || !Array.isArray(ps.positions)) {
          return currentState;
        }
        const valid = validatePositions(ps.positions).map((p) => ({
          ...(p.recId ? p : { ...p, recId: generateRecId() }),
          // Guaranteed to run on every rehydration (unlike migrate, which only
          // fires on a version bump) — the last-resort backstop against a
          // stray persisted stop=0/structuralStop=0 reaching live state.
          stop: floorStop(p.stop),
          structuralStop: floorStop(p.structuralStop),
        }));
        return {
          ...currentState,
          positions: dedupePositions(valid),
        };
      },
    }
  )
);

/** Whether the symbol has at least one open portfolio position — used to
 *  gate symbol-notes editing (a note is editable if watchlisted OR held). */
export function useIsSymbolHeld(symbol: string): boolean {
  const s = symbol.trim().toUpperCase();
  return usePortfolioStore((state) => state.positions.some((p) => p.symbol.toUpperCase() === s));
}
