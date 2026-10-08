import { create } from 'zustand';
import type { PositionCardData, StockFirstPassageEstimate, StockExitPlan } from '@/types/stockDomain';
import { selectCardEdits, type CardEditsHost } from './cardEdits';
import type { PickedMethod } from '@/types/domain';
import type { StockScanRequestBody } from './resolveStockScanRequest';

export interface StockEditOverlay {
  entry: number;
  stop: number;
  shares: number;
  t1: number;
  t2: number;
  t3: number;
  sharesT1: number;
  sharesT2: number;
  sharesT3: number;
}

export interface StructuralStopResult {
  price: number;
  source: 'order_block' | 'swing_low' | 'swing_high' | null;
  confidence: number | null;
  distancePct: number | null;
}

export function defaultStockOverlay(card: PositionCardData): StockEditOverlay {
  const entry = card.strategy.entry_price;
  const stop  = card.strategy.stop_price;
  const risk  = Math.abs(entry - stop);
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  // T2/T3 used to be invented here as a flat 2R/3R — not strategy-derived, not
  // validated by any backtest, and invisible to the WFO tuner. They now come
  // from the backend ladder, which is built from each strategy's own exit
  // thesis. The R-step fill survives only as the fallback for a scan result
  // rehydrated from localStorage before `targets` existed (`?.length`, not
  // `??`: an empty array must fall back too).
  const round2 = (v: number) => Math.round(v * 100) / 100;
  const ladder = card.strategy.targets?.length
    ? card.strategy.targets
    : [card.strategy.target_price];
  // Missing rungs are filled by stepping ONE MORE R past the previous rung, not
  // by measuring 2R/3R from entry. Measuring from entry can place T2 nearer than
  // a strategy-derived T1 (a prior swing high 4R away leaves T2 = 2R behind it),
  // and stockPositionLevels() sorts the ladder nearest-first on the way into the
  // portfolio — so the persisted targets[0], which is the ONLY rung TP_HIT
  // fires on, would not be the rung the card showed as T1.
  // ladder is guaranteed non-empty by construction above, so ladder[0] is
  // never undefined — no `?? target_price` fallback needed here.
  const t1    = round2(ladder[0]);
  const t2    = round2(ladder[1] ?? t1 + sign * risk);
  const t3    = round2(ladder[2] ?? t2 + sign * risk);
  const s     = card.shares;
  const s1    = Math.floor(s / 3);
  const s2    = Math.floor(s / 3);
  return { entry, stop, shares: s, t1, t2, t3, sharesT1: s1, sharesT2: s2, sharesT3: s - s1 - s2 };
}


export interface StockExecutionRecord {
  // Availability metadata, never a positive execution permission. The reviewed
  // C4 adapter remains absent; hydrated/forged values are never consumed.
  validationAvailability?: 'unavailable';
  provenance?: { identity: string; symbol: string; strategy: string; direction: string; request: StockScanRequestBody | null };
  overlay?: StockEditOverlay;
  estimateInputKey?: string;
  planInputKey?: string;
  structuralInputKey?: string;
  entryRevision?: number;
  structuralRevision?: number;
  estimateRevision?: number;
  estimateRequestToken?: number;
  planRequestToken?: number;
  structuralRequestToken?: number;
  estimate?: StockFirstPassageEstimate | null;
  structural?: StructuralStopResult | null;
  plan?: StockExitPlan | null;
  estimating?: boolean;
  checkingStructure?: boolean;
  planning?: boolean;
  estimateErr?: string | null;
  structuralErr?: string | null;
  planErr?: string | null;
  err?: string | null;
  warning?: string | null;
  added?: boolean;
  queued?: boolean;
  adding?: boolean;
  execMode?: 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';
  placingType?: 'LMT' | 'MKT' | null;
  orderId?: string | null;
  orderMsg?: { text: string; tone: 'pass' | 'caution' } | null;
  clearedPickMethod?: PickedMethod | null;
}
export interface StockScanFeedback {
  error: string | null;
  notice: string | null;
}
/** Identity includes replacement generation, even when backend reuses scan_id. */
export function stockExecutionIdentity(state: {
  stockScanResult: { scan_id?: string; timestamp?: string } | null;
  stockExecutionGeneration: number;
}, symbol: string): string | null {
  const stamp = state.stockScanResult?.scan_id || state.stockScanResult?.timestamp;
  return stamp ? JSON.stringify([stamp, state.stockExecutionGeneration, symbol]) : null;
}
/** No reviewed C4 authority is installed. State, PASS, picks and hydrated
 * permission flags are never trusted positive execution authority. */
export const STOCK_VALIDATION_UNAVAILABLE =
  'Unvalidated — research only. Strategy validation is unavailable; broker sending and automatic arming are blocked.';
export function stockExecutionBlock(): string | null { return STOCK_VALIDATION_UNAVAILABLE; }

/** Mutation ownership outlives execution-evidence replacement and route mounts.
 * Like DirectSendNotes this is session-only, never hydrated numeric evidence. */
export interface StockOrderOwnership {
  identity: string | null;
  recId: string;
  status: 'in-flight' | 'placed' | 'unknown';
  message?: string;
}
export const useStockOrderOwnershipStore = create<{
  bySymbol: Record<string, StockOrderOwnership>;
  claim: (symbol: string, ownership: StockOrderOwnership) => boolean;
  finish: (symbol: string, recId: string, status: 'placed' | 'unknown' | null, message: string) => void;
}>()((set, get) => ({
  bySymbol: {},
  claim: (symbol, ownership) => {
    if (get().bySymbol[symbol]) return false;
    set(s => ({ bySymbol: { ...s.bySymbol, [symbol]: ownership } }));
    return true;
  },
  finish: (symbol, recId, status, message) => {
    const record = get().bySymbol[symbol];
    if (record?.recId !== recId) return;
    set(s => {
      const next = { ...s.bySymbol };
      if (status) next[symbol] = { ...record, status, message };
      else delete next[symbol];
      return { bySymbol: next };
    });
  },
}));

/** Existing exact share allocation clamp/scaling rules, shared with basket quantity edits. */
export function patchStockOverlay(prev: StockEditOverlay, partial: Partial<StockEditOverlay>): StockEditOverlay {
  const next = { ...prev, ...partial };
      // Each rung's share count is edited independently (one EditableField per
      // T1/T2/T3 row), so nothing stops sharesT1+T2+T3 from exceeding the
      // position's total shares — which would tell the sell-to-close plan
      // (buildPaperStockPosition's contractsToSell) to sell more shares than
      // the position holds.
      const allocated = next.sharesT1 + next.sharesT2 + next.sharesT3;
      if (allocated > next.shares) {
        const shareKeys = ['sharesT1', 'sharesT2', 'sharesT3'] as const;
        const editedShareKeys = shareKeys.filter((k) => k in partial);
        if (editedShareKeys.length > 0) {
          // The rung the user just edited pushed the total over — clamp THAT
          // rung down to what's left after the others, rather than silently
          // shrinking a different rung they didn't touch.
          const othersSum = shareKeys
            .filter((k) => !editedShareKeys.includes(k))
            .reduce((sum, k) => sum + next[k], 0);
          for (const k of editedShareKeys) next[k] = Math.max(0, next.shares - othersSum);
        } else if (allocated > 0) {
          // Total `shares` shrank below the existing allocation — scale every
          // rung down proportionally rather than favoring one arbitrarily.
          const scale = next.shares / allocated;
          next.sharesT1 = Math.floor(next.sharesT1 * scale);
          next.sharesT2 = Math.floor(next.sharesT2 * scale);
          next.sharesT3 = Math.max(0, next.shares - next.sharesT1 - next.sharesT2);
        }
      } else if ('shares' in partial && allocated > 0 && allocated < next.shares) {
        // A fifth independent audit round found the mirror gap: growing total
        // SHARES was never topped up to the sell-to-close plan, silently
        // leaving the added shares with no planned exit rung at all (e.g.
        // 100 shares allocated 33/33/34, SHARES edited up to 250, rungs stay
        // at 33/33/34 — 150 shares reach Add to Portfolio uncovered). Scale
        // every rung UP proportionally, the mirror of the shrink branch
        // above. `allocated > 0` is a pure division-by-zero guard, not a
        // reachable UI state — EditableField.save() requires `p > 0`, so a
        // rung's share count can never actually be edited down to 0.
        const scale = next.shares / allocated;
        next.sharesT1 = Math.floor(next.sharesT1 * scale);
        next.sharesT2 = Math.floor(next.sharesT2 * scale);
        next.sharesT3 = Math.max(0, next.shares - next.sharesT1 - next.sharesT2);
      }
  return next;
}

/** Resolve a current scan card. Basket consumers must first match their
 * recorded stockBasketSources identity; symbol equality alone is insufficient. */
export function resolveStockCardExecution(state: {
  stockScanResult: { scan_id?: string; timestamp?: string } | null;
  stockExecutionGeneration: number;
  stockExecution: Record<string, StockExecutionRecord>;
}, card: PositionCardData) {
  const identity = stockExecutionIdentity(state, card.symbol);
  const record = identity ? state.stockExecution[identity] : undefined;
  return { identity, overlay: record?.overlay ?? defaultStockOverlay(card), record };
}

/** Basket provenance is session-only: restored rows retain saved values and
 * cannot adopt a newer same-symbol pick or execution evidence. */
export function resolveBasketExecution(state: CardEditsHost & {
  stockExecutionGeneration: number;
  stockExecution: Record<string, StockExecutionRecord>;
  stockBasketSources: Record<string, string | null>;
  stockScanRequest?: StockScanRequestBody | null;
  stockScanResult: ({ scan_id?: string; timestamp?: string; candidates?: PositionCardData[] }) | null;
}, card: PositionCardData) {
  const identity = stockExecutionIdentity(state, card.symbol);
  const source = state.stockBasketSources[card.symbol];
  const current = !!source && source === identity && !!state.stockScanResult?.candidates?.includes(card);
  const record = current && identity ? state.stockExecution[identity] : undefined;
  const overlay = current ? record?.overlay ?? defaultStockOverlay(card) : undefined;
  const pick = current ? selectCardEdits(state, 'stocks').picks[card.symbol] ?? null : null;
  const targets = overlay ? [
    { price: overlay.t1, shares: overlay.sharesT1 },
    { price: overlay.t2, shares: overlay.sharesT2 },
    { price: overlay.t3, shares: overlay.sharesT3 },
  ] : (card.strategy.targets?.length ? card.strategy.targets : [card.strategy.target_price]).map(price => ({ price }));
  return {
    identity: current ? identity : null, current, record, overlay, pick,
    entry: overlay?.entry ?? card.strategy.entry_price,
    stop: overlay?.stop ?? card.strategy.stop_price,
    shares: overlay?.shares ?? card.shares, targets,
    structuralStop: record?.structural?.price ?? null,
    horizon: current ? record?.provenance?.request?.horizon ?? state.stockScanRequest?.horizon ?? 'Swing' : 'Swing',
    explanation: current ? null : 'Saved basket values — open the current candidate, choose a method and repin before submitting.',
  };
}
