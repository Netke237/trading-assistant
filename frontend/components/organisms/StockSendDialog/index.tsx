'use client';

import { useState, useMemo, useEffect } from 'react';
import { Text } from '@/components/primitives/Text';
import { Data } from '@/components/primitives/Data';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
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

type BrokerMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper';

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
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);

  const addPosition  = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper    = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper = useSettingsStore((s) => s.tradierPaper);

  const ibkrConfigured    = !!ibkrPaper.accountId && !!ibkrPaper.baseUrl;
  const tradierConfigured = !!tradierPaper.token && !!tradierPaper.accountId;

  useEffect(() => {
    api
      .getBrokerStatus()
      .then((s) => setAlpacaConfigured(s.alpaca_paper?.configured ?? false))
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
    setErrors({});

    const errs: Record<string, string> = {};
    for (const c of cards) {
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      if (!r.autoSend) {
        // Manual → paper portfolio
        addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares));
      } else if (broker !== 'recommendation') {
        // Auto-send → broker
        try {
          await api.postStockOrder({
            broker,
            symbol: c.symbol,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL',
            quantity: r.shares,
            order_type: 'LMT',
            limit_price: c.strategy.entry_price,
            tif: 'DAY',
          });
        } catch (e) {
          errs[c.symbol] = String(e);
        }
      } else {
        // Auto-send but broker = recommendation → fall back to paper
        addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares));
      }
    }

    setSubmitting(false);

    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }

    const orders: StockDraftOrder[] = cards.map((c) => {
      const r = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
      return { card: c, shares: Math.max(1, Math.round(r.shares)), autoSend: r.autoSend };
    });
    onSubmit(orders);
  }

  const brokerOptions: Array<[BrokerMode, string, boolean]> = [
    ['recommendation', 'Recommendation', true],
    ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
    ['tradier_paper', 'Tradier Paper',   tradierConfigured],
    ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
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
            const r      = rows[c.symbol] ?? { shares: c.shares, autoSend: true };
            const risk   = (c.strategy.entry_price - c.strategy.stop_price) * r.shares;
            const size   = c.strategy.entry_price * r.shares;
            const hasErr = !!errors[c.symbol];
            return (
              <div key={c.symbol} className={`${styles.row} ${hasErr ? styles.rowErr : ''}`}>
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
              disabled={cards.length === 0 || submitting}
            >
              <Text size={13}>
                {submitting
                  ? 'Submitting…'
                  : `Submit ${cards.length} order${cards.length === 1 ? '' : 's'}`}
              </Text>
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
