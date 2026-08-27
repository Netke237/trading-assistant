'use client';

import { useState, useMemo, useEffect } from 'react';
import { Text } from '@/components/primitives/Text';
import { Data } from '@/components/primitives/Data';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
import { api } from '@/lib/api';
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

// Both add-to-portfolio paths below send the PRISTINE strategy levels: this dialog
// has no per-row level editor, so there is no overlay to prefer. `strategy.targets`
// is the backend exit ladder; the fallback covers a scan result restored from
// localStorage that predates that field.
//
// `?.length ? … : …`, NOT `?? …`: nullish coalescing does not catch an EMPTY array,
// and a backend (or a rehydrated scan result) carrying `targets: []` would otherwise
// persist a position with no take-profit at all.
const pristineLevels = (c: PositionCardData) => ({
  stop: c.strategy.stop_price,
  targets: (c.strategy.targets?.length ? c.strategy.targets : [c.strategy.target_price])
    .map((price) => ({ price })),
});

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
  const scanHorizon = useScanStore((s) => s.context?.horizon ?? 'Swing');

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
      t += r.shares * c.strategy.entry_price;
    }
    return { autoCount: a, manualCount: m, estTotal: t };
  }, [cards, rows]);

  async function submit() {
    if (submitting) return;
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
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      if (!r.autoSend) {
        // Manual → paper portfolio
        const res = await addPosition(
          buildPaperStockPosition(
            c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction,
            stockCardSnapshotOf(c, scanHorizon), pristineLevels(c),
          ),
        );
        if (res.status === 'rejected') errs[c.symbol] = res.detail ?? 'not saved';
        else if (res.status === 'pending') q[c.symbol] = 'queued — backend unreachable, will sync';
      } else if (broker !== 'recommendation') {
        // Auto-send → broker, then mirror the fill into the local portfolio
        // (same pattern as the manual branch just above) so this position
        // carries a tradeCardSnapshot and real stop/target too — without
        // this, a broker-executed stock position has no local record at all
        // and the Portfolio EditDrawer's Monte Carlo estimate has nothing to
        // work from.
        try {
          const res = await api.postStockOrder({
            broker,
            symbol: c.symbol,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL',
            effect: 'OPEN',
            quantity: r.shares,
            order_type: 'LMT',
            limit_price: c.strategy.entry_price,
            tif: 'DAY',
          });
          // The broker order has ALREADY succeeded at this point — a failure
          // below must never be written to `errs`/`q` (those drive the retry
          // set; retrying here would resubmit an already-filled order). It's
          // tracked in `warn` instead, purely informational.
          try {
            const addRes = await addPosition({
              ...buildPaperStockPosition(
                c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction,
                stockCardSnapshotOf(c, scanHorizon), pristineLevels(c),
              ),
              source: 'broker',
              sourceLabel: `${broker} — Limit (ID: ${res.order_id})`,
              orderedAt: new Date().toISOString(),
            });
            if (addRes.status === 'rejected' || addRes.status === 'pending') {
              warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
            }
          } catch {
            warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
          }
        } catch (e) {
          errs[c.symbol] = String(e);
        }
      } else {
        // Auto-send but broker = recommendation → fall back to paper
        const res = await addPosition(
          buildPaperStockPosition(
            c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction,
            stockCardSnapshotOf(c, scanHorizon), pristineLevels(c),
          ),
        );
        if (res.status === 'rejected') errs[c.symbol] = res.detail ?? 'not saved';
        else if (res.status === 'pending') q[c.symbol] = 'queued — backend unreachable, will sync';
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
      return { card: c, shares: Math.max(1, Math.round(r.shares)), autoSend: r.autoSend };
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
            const risk     = (c.strategy.entry_price - c.strategy.stop_price) * r.shares;
            const size     = c.strategy.entry_price * r.shares;
            const hasErr   = !!errors[c.symbol];
            const isQueued = !!queued[c.symbol];
            return (
              <div key={c.symbol} className={`${styles.row} ${hasErr ? styles.rowErr : ''} ${isQueued ? styles.rowQueued : ''}`}>
                <Data size={13} weight={500}>{c.symbol}</Data>
                <Data size={12}>${c.strategy.entry_price.toFixed(2)}</Data>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={r.shares}
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
                    onChange={(e) => patch(c.symbol, { autoSend: e.target.checked })}
                    aria-label={`Auto-send ${c.symbol}`}
                  />
                  <Text size={11} tone={r.autoSend ? 'pass' : 'caution'}>
                    {r.autoSend ? 'Auto' : 'Manual'}
                  </Text>
                </label>
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
              disabled={cards.length === 0 || submitting || (hasQueued && !hasRetryableErrors) || (hasWarnings && !hasRetryableErrors && !hasQueued)}
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
