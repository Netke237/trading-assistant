'use client';

import { stockExecutionBlock, resolveBasketExecution, patchStockOverlay, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';

import { useState, useMemo, useEffect } from 'react';
import { Text } from '@/components/primitives/Text';
import { Data } from '@/components/primitives/Data';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { pickedFieldsFrom } from '@/lib/cardEdits';
import { buildPaperStockPosition, stockCardSnapshotOf, invalidTargetRungs } from '@/lib/paperTrade';
import { BEARISH_UNVALIDATED_MESSAGE, isBearishUnvalidated } from '@/lib/unvalidated';
import { stockEarningsGate, EARNINGS_VETO_MESSAGE } from '@/lib/earningsGate';
import { api } from '@/lib/api';
import { sendStockSaveFirst } from '@/lib/stockDirectSend';
import { sanitizeHoldDays } from '@/lib/horizonPresets';
import { checkMethodPick, MISSING_METHOD_PICK_MESSAGE, MISSING_METHOD_PICK_TITLE } from '@/lib/risk';
import type { PositionCardData } from '@/types/stockDomain';
import type { Direction } from '@/types/domain';
import styles from './StockSendDialog.module.css';

export interface StockDraftOrder {
  card: PositionCardData;
  shares: number;
  autoSend: boolean;
}

interface RowState {
  shares: number;
  autoSend: boolean;
}

type BrokerMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';

interface Props {
  cards: PositionCardData[];
  onClose: () => void;
  onSubmit: (orders: StockDraftOrder[]) => void;
}

export function StockSendDialog({ cards, onClose, onSubmit }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(cards.map((c) => [c.symbol, { shares: c.shares, autoSend: true }])),
  );

  const [broker, setBroker] = useState<BrokerMode>('recommendation');
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [queued, setQueued] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<Record<string, string>>({});
  const [hasSubmittedOnce, setHasSubmittedOnce] = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);
  const [tastytradeConfigured, setTastytradeConfigured] = useState(false);

  const addPosition  = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper    = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper = useSettingsStore((s) => s.tradierPaper);
  const scan = useScanStore();
  const ownerships = useStockOrderOwnershipStore(s => s.bySymbol);
  const effective = (c: PositionCardData) => resolveBasketExecution(scan, c);
  const alreadyOwned = (c: PositionCardData) => !!ownerships[c.symbol] || !!(effective(c).record?.adding || effective(c).record?.added || effective(c).record?.queued);
  const hasMissingMethodPick = cards.some(c => !alreadyOwned(c) && !checkMethodPick(effective(c).pick));
  const hasBearishOpening = broker !== 'recommendation' && cards.some(c =>
    !alreadyOwned(c) && (rows[c.symbol]?.autoSend ?? true) && isBearishUnvalidated(c.direction));
  // STOCKS-HORIZON-P0B B7: earnings inside the scan's veto window
  // max(reject_days, hold), aged by the scan's age. Unknown never blocks; a
  // research save (auto-send off) is not an order and stays available.
  const earningsVetoed = (c: PositionCardData) =>
    stockEarningsGate(c, scan.stockScanResult?.timestamp, scan.stockScanResult?.veto_days).veto;
  const hasEarningsVeto = broker !== 'recommendation' && cards.some(c =>
    !alreadyOwned(c) && (rows[c.symbol]?.autoSend ?? true) && earningsVetoed(c));

  const ibkrConfigured    = !!ibkrPaper.accountId && !!ibkrPaper.baseUrl;
  const tradierConfigured = !!tradierPaper.token && !!tradierPaper.accountId;

  useEffect(() => {
    api
      .getBrokerStatus()
      .then((s) => {
        setAlpacaConfigured(s.alpaca_paper?.configured ?? false);
        setTastytradeConfigured(s.tastytrade_paper?.configured ?? false);
      })
      .catch(() => {});
  }, []);

  const patch = (sym: string, p: Partial<RowState>) => {
    const card = cards.find(c => c.symbol === sym);
    if (card && p.shares != null) {
      const execution = resolveBasketExecution(useScanStore.getState(), card);
      if (execution.identity && execution.overlay) useScanStore.getState().patchStockExecution(execution.identity, { overlay: patchStockOverlay(execution.overlay, { shares: Math.max(1, Math.round(p.shares)) }) });
    }
    setRows((r) => ({ ...r, [sym]: { ...(r[sym] ?? { shares: 1, autoSend: true }), ...p } }));
  };

  const { autoCount, manualCount, estTotal } = useMemo(() => {
    let a = 0,
      m = 0,
      t = 0;
    for (const c of cards) {
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      if (r.autoSend) a++;
      else m++;
      const execution = effective(c);
      t += (execution.current ? execution.shares : r.shares) * execution.entry;
    }
    return { autoCount: a, manualCount: m, estTotal: t };
  }, [cards, rows, scan]);

  async function submit() {
    if (submitting || hasBearishOpening || hasEarningsVeto) return;
    // Phase G piece 5, build step 4 (§7.2, S4) — belt-and-braces beside the
    // button's own `disabled`, on the same reading `hasMissingMethodPick`
    // was derived from. Same shape as SendToBrokerDialog.submit()'s
    // `hasMissingInvalidation` guard.
    if (hasMissingMethodPick) return;
    setSubmitting(true);

    // On a retry (i.e. a prior attempt already ran), only re-process symbols
    // that failed last time — already-succeeded symbols must not be
    // resubmitted (would double-place broker orders / duplicate positions).
    const targets = hasSubmittedOnce ? cards.filter((c) => c.symbol in errors) : cards;
    setHasSubmittedOnce(true);
    setErrors({});

    const errs: Record<string, string> = {};
    // Seed with the PRIOR queued state on a retry — a queued symbol is never
    // in `targets` (queued and errored are mutually exclusive outcomes), so
    // it never runs through the loop below to re-earn its `q[...]` entry.
    // Without this, a retry that only fixes the errored symbol would drop
    // the queued symbol's tracking entirely: `q` ends up {} for this pass,
    // the "stay open on any unconfirmed row" gate below sees nothing
    // unconfirmed, and the dialog reports the FULL basket (including the
    // still-unconfirmed queued symbol) as placed via onSubmit.
    const q: Record<string, string> = hasSubmittedOnce ? { ...queued } : {};
    const warn: Record<string, string> = hasSubmittedOnce ? { ...warnings } : {};
    for (const c of targets) {
      const owner = useStockOrderOwnershipStore.getState().bySymbol[c.symbol];
      if (owner) { warn[c.symbol] = owner.message ?? 'Submission pending or completed; no duplicate will be sent.'; continue; }
      const execution = resolveBasketExecution(useScanStore.getState(), c);
      if (execution.record?.adding || execution.record?.added || execution.record?.queued) {
        warn[c.symbol] = 'Candidate already saved or saving — no duplicate will be submitted.'; continue;
      }
      if (!checkMethodPick(execution.pick)) { errs[c.symbol] = execution.explanation ?? MISSING_METHOD_PICK_MESSAGE; continue; }
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      const shares = execution.current ? execution.shares : r.shares;
      if (invalidTargetRungs(execution.entry, c.direction as Direction, execution.targets).length) {
        errs[c.symbol] = 'Targets are on the wrong side of entry — fix the candidate before saving.'; continue;
      }
      const pos = {
        ...buildPaperStockPosition(c.symbol, execution.entry, shares, c.direction as Direction,
          stockCardSnapshotOf(c, execution.horizon, execution.overlay ? {
            entry: execution.entry, stop: execution.stop, targets: execution.targets.map(t => t.price), shares,
          } : undefined),
          { stop: execution.stop, targets: execution.targets, structuralStop: execution.structuralStop }),
        ...pickedFieldsFrom(execution.pick),
        // STOCKS-HORIZON-T1 H6: the scan's hold; no scan context -> no hold.
        holdMaxDays: scan.context
          ? sanitizeHoldDays(scan.context.holdMin, scan.context.holdMax).hold_max_days
          : null,
      };
      if (r.autoSend && broker !== 'recommendation') {
        const vetoed = earningsVetoed(c);
        const blocked = isBearishUnvalidated(c.direction) ? BEARISH_UNVALIDATED_MESSAGE
          : vetoed ? EARNINGS_VETO_MESSAGE : stockExecutionBlock();
        if (blocked) { errs[c.symbol] = blocked; continue; }
        try {
          const outcome = await sendStockSaveFirst({ pos, broker, orderType: 'LMT', limitPrice: execution.entry,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL', addPosition, earningsVeto: vetoed });
          if (outcome.kind === 'refused' || outcome.kind === 'not-placed') errs[c.symbol] = outcome.message;
          else if (outcome.kind === 'unknown') warn[c.symbol] = outcome.message;
          else if (outcome.resizedFrom != null) warn[c.symbol] = `${outcome.message} Portfolio sized it to ${outcome.qty} shares; the order was sent for ${outcome.qty}.`;
        } catch (e) { errs[c.symbol] = `No order was sent — ${String(e)}`; }
      } else {
        const ownership = useStockOrderOwnershipStore.getState();
        if (!ownership.claim(c.symbol, { identity: execution.identity, recId: pos.recId, status: 'in-flight' })) {
          warn[c.symbol] = 'Submission already pending or completed.'; continue;
        }
        try {
          const res = await addPosition(pos);
          if (res.status === 'rejected') {
            errs[c.symbol] = res.detail ?? 'not saved'; ownership.finish(c.symbol, pos.recId, null, errs[c.symbol]);
          } else {
            const message = res.status === 'pending' ? 'queued — backend unreachable, will sync'
              : res.adjustedQty != null && res.adjustedQty !== shares ? `Portfolio sized it to ${res.adjustedQty} shares (exposure limit).` : 'Saved to research portfolio.';
            ownership.finish(c.symbol, pos.recId, res.status === 'pending' ? 'unknown' : 'placed', message);
            if (execution.identity) useScanStore.getState().patchStockExecution(execution.identity, { added: res.status !== 'pending', queued: res.status === 'pending' });
            if (res.status === 'pending') q[c.symbol] = message;
            else if (res.adjustedQty != null && res.adjustedQty !== shares) warn[c.symbol] = message;
          }
        } catch (e) {
          const message = `Save status unknown — ${String(e)}`;
          ownership.finish(c.symbol, pos.recId, 'unknown', message); warn[c.symbol] = message;
        }
      }
    }

    setSubmitting(false);
    setErrors(errs);
    setQueued(q);
    setWarnings(warn);

    // Stay open on ANY unconfirmed row — hard rejections (red) OR queued/pending
    // (caution) OR a warn-only outcome (broker order placed but local tracking
    // failed). Only a fully-confirmed submit advances to onSubmit + close.
    if (Object.keys(errs).length > 0 || Object.keys(q).length > 0 || Object.keys(warn).length > 0) return;

    // All symbols (across this attempt and any prior successful ones) are
    // now placed. Report the full original card set/shares to the caller,
    // since callers (e.g. Step 7) expect one onSubmit describing the whole
    // basket that is now fully placed.
    const orders: StockDraftOrder[] = cards.map((c) => {
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      return { card: c, shares: effective(c).current ? effective(c).shares : Math.max(1, Math.round(r.shares)), autoSend: r.autoSend };
    });
    onSubmit(orders);
  }

  // Once any row is queued (backend unreachable), block a same-mount re-submit
  // of THAT row: a second pass would mint a fresh recId and merge/double it in
  // the store. But a mixed attempt (some rows queued, others hard-rejected)
  // must not get stuck forever — `targets` above already only re-processes
  // `errors` symbols on retry (queued symbols are never in `errors`, so they
  // can't be touched by a retry), so only fully block the button when there's
  // nothing left to retry.
  const hasQueued = Object.keys(queued).length > 0;
  const hasRetryableErrors = Object.keys(errors).length > 0;
  const hasWarnings = Object.keys(warnings).length > 0;

  const brokerOptions: Array<[BrokerMode, string, boolean]> = [
    ['recommendation', 'Recommendation', true],
    ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
    ['tradier_paper', 'Tradier Paper',   tradierConfigured],
    ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
    ['tastytrade_paper', 'Tastytrade Paper', tastytradeConfigured],
  ];

  return (
    <div className={styles.backdrop} onClick={onClose} role="presentation">
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Send stock basket to broker"
      >
        <header className={styles.header}>
          <div>
            <Text size={14} weight={500}>Send basket to broker</Text>
            <Text size={11} tone="secondary">
              Uncheck Auto-send to add to portfolio manually. Auto-send rows are submitted as Limit
              orders at entry price.
            </Text>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close dialog"
          >
            ×
          </button>
        </header>

        {/* Broker picker */}
        <div className={styles.brokerRow}>
          {brokerOptions.map(([mode, label, ok]) => (
            <button
              key={mode}
              type="button"
              className={`${styles.brokerBtn} ${broker === mode ? styles.brokerBtnActive : ''}`}
              disabled={!ok}
              title={!ok ? 'Not configured — Settings → Brokers' : undefined}
              onClick={() => setBroker(mode)}
            >
              <Text size={12}>{label}</Text>
            </button>
          ))}
        </div>

        {/* Table header */}
        <div className={styles.tableHead}>
          <Text size={10} tone="dim">SYMBOL</Text>
          <Text size={10} tone="dim">ENTRY</Text>
          <Text size={10} tone="dim">SHARES</Text>
          <Text size={10} tone="dim">RISK $</Text>
          <Text size={10} tone="dim">SIZE $</Text>
          <Text size={10} tone="dim">AUTO-SEND</Text>
        </div>

        {/* Table body */}
        <div className={styles.tableBody}>
          {cards.map((c) => {
            const r        = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
            const execution = effective(c);
            const shares = execution.current ? execution.shares : r.shares;
            const risk = Math.abs(execution.entry - execution.stop) * shares;
            const size = execution.entry * shares;
            const hasErr   = !!errors[c.symbol];
            const isQueued = !!queued[c.symbol];
            return (
              <div key={c.symbol} className={`${styles.row} ${hasErr ? styles.rowErr : ''} ${isQueued ? styles.rowQueued : ''}`}>
                <Data size={13} weight={500}>{c.symbol}</Data>
                <Data size={12}>${execution.entry.toFixed(2)}</Data>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={shares}
                  disabled={alreadyOwned(c)}
                  className={styles.sharesInput}
                  onChange={(e) =>
                    patch(c.symbol, { shares: Math.max(1, Number(e.target.value) || 1) })
                  }
                  aria-label={`Shares for ${c.symbol}`}
                />
                <Data size={12} tone="reject">${Math.round(risk).toLocaleString()}</Data>
                <Data size={12}>${Math.round(size).toLocaleString()}</Data>
                <label className={styles.autoCell}>
                  <input
                    type="checkbox"
                    checked={r.autoSend}
                    disabled={alreadyOwned(c)}
                    onChange={(e) => patch(c.symbol, { autoSend: e.target.checked })}
                    aria-label={`Auto-send ${c.symbol}`}
                  />
                  <Text size={11} tone={r.autoSend ? 'pass' : 'caution'}>
                    {r.autoSend ? 'Auto' : 'Manual'}
                  </Text>
                </label>
                {(execution.explanation || alreadyOwned(c)) && !hasErr && !isQueued && !warnings[c.symbol] && <span className={styles.errCell}><Text size={11} tone="caution">{ownerships[c.symbol]?.message ?? execution.explanation ?? 'Candidate already saved or saving — no duplicate will be sent.'}</Text></span>}
                {hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="reject">{errors[c.symbol]}</Text>
                  </span>
                )}
                {isQueued && !hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{queued[c.symbol]}</Text>
                  </span>
                )}
                {warnings[c.symbol] && !hasErr && !isQueued && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{warnings[c.symbol]}</Text>
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {hasMissingMethodPick && (
          <Text size={12} tone="reject">{MISSING_METHOD_PICK_MESSAGE}</Text>
        )}

        {hasBearishOpening && <Text size={12} tone="reject">{BEARISH_UNVALIDATED_MESSAGE}</Text>}
        {hasEarningsVeto && <Text size={12} tone="reject">{EARNINGS_VETO_MESSAGE}</Text>}

        <footer className={styles.footer}>
          <Text size={12} tone="secondary">
            {autoCount} auto · {manualCount} manual · Est total $
            {Math.round(estTotal).toLocaleString()}
          </Text>
          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>
              <Text size={13}>Cancel</Text>
            </button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0 || submitting || cards.every(c => alreadyOwned(c)) || (hasQueued && !hasRetryableErrors) || (hasWarnings && !hasRetryableErrors && !hasQueued) || hasMissingMethodPick || hasBearishOpening || hasEarningsVeto}
              title={hasBearishOpening ? BEARISH_UNVALIDATED_MESSAGE : hasEarningsVeto ? EARNINGS_VETO_MESSAGE : hasMissingMethodPick ? MISSING_METHOD_PICK_TITLE : undefined}
            >
              <Text size={13}>
                {submitting
                  ? 'Submitting…'
                  : hasRetryableErrors
                    ? `Retry ${Object.keys(errors).length} failed order${Object.keys(errors).length === 1 ? '' : 's'}`
                    // A real broker fill with no local record outranks a
                    // merely-deferred paper save — a mixed queued+warn state
                    // must surface the warning, not bury it behind "Queued."
                    : hasWarnings
                      ? 'Placed — close to continue'
                      : hasQueued
                        ? 'Queued — close to continue'
                        : `Submit ${cards.length} order${cards.length === 1 ? '' : 's'}`}
              </Text>
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
