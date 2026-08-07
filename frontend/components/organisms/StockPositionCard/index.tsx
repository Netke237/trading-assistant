'use client';

import { useState, useEffect, useCallback } from 'react';
import { Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
import { api } from '@/lib/api';
import { winRateTooltip } from '@/lib/statusTooltips';
import type { PositionCardData } from '@/types/stockDomain';
import { StockAutoTradeArm } from '@/components/organisms/StockAutoTradeArm';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { FundamentalHealthCard } from '@/components/molecules/FundamentalHealthCard';
import styles from './StockPositionCard.module.css';

// ─── Types ────────────────────────────────────────────────────────────────────

interface StockEditOverlay {
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

interface StockPositionCardProps {
  card: PositionCardData;
  strategyKey: string;
  afterScanArmed?: boolean;
  onAfterScanToggle?: (symbol: string, armed: boolean) => void;
}

type ExecMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function defaultOverlay(card: PositionCardData): StockEditOverlay {
  const entry = card.strategy.entry_price;
  const stop  = card.strategy.stop_price;
  const risk  = Math.abs(entry - stop);
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  const t1    = card.strategy.target_price;
  const t2    = Math.round((entry + sign * 2 * risk) * 100) / 100;
  const t3    = Math.round((entry + sign * 3 * risk) * 100) / 100;
  const s     = card.shares;
  const s1    = Math.floor(s / 3);
  const s2    = Math.floor(s / 3);
  return { entry, stop, shares: s, t1, t2, t3, sharesT1: s1, sharesT2: s2, sharesT3: s - s1 - s2 };
}

// ─── EditableField ────────────────────────────────────────────────────────────

function EditableField({
  label,
  value,
  onChange,
  tone,
  decimals = 2,
  integer = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  tone?: 'pass' | 'caution' | 'reject';
  decimals?: number;
  integer?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState('');

  const startEdit = () => { setDraft(String(value)); setEditing(true); };
  const save = () => {
    const p = parseFloat(draft);
    if (!isNaN(p) && p > 0) onChange(integer ? Math.round(p) : Math.round(p * 100) / 100);
    setEditing(false);
  };

  return (
    <div className={styles.editCell}>
      <Text size={10} tone="dim">{label}</Text>
      {editing ? (
        <input
          type="number"
          className={styles.editInput}
          value={draft}
          min={0.01}
          step={integer ? 1 : 0.01}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') setEditing(false);
          }}
          autoFocus
        />
      ) : (
        <span
          className={styles.editValue}
          onClick={startEdit}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') startEdit(); }}
        >
          <Data size={14} weight={500} tone={tone}>
            {integer ? String(value) : value.toFixed(decimals)}
          </Data>
        </span>
      )}
    </div>
  );
}

// ─── StockPositionCard ────────────────────────────────────────────────────────

export function StockPositionCard({
  card,
  strategyKey,
  afterScanArmed,
  onAfterScanToggle,
}: StockPositionCardProps) {
  const [overlay, setOverlay] = useState<StockEditOverlay>(() => defaultOverlay(card));

  // Reset overlay and per-symbol outcome state when the selected symbol changes
  useEffect(() => {
    setOverlay(defaultOverlay(card));
    setAdded(false);
    setErr(null);
    setQueued(false);
    setAdding(false);
    setOrderId(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.symbol]);

  const patch = useCallback((partial: Partial<StockEditOverlay>) => {
    setOverlay((prev) => ({ ...prev, ...partial }));
  }, []);

  // Derived values
  const riskPerShare = Math.abs(overlay.entry - overlay.stop);
  const riskDollars  = overlay.shares * riskPerShare;
  const sizeDollars  = overlay.shares * overlay.entry;
  const rrAt = (t: number) =>
    riskPerShare > 0 ? Math.abs(t - overlay.entry) / riskPerShare : 0;

  // Store selectors
  const stockBasket  = useScanStore((s) => s.stockBasket);
  const addToBasket  = useScanStore((s) => s.addToStockBasket);
  const removeBasket = useScanStore((s) => s.removeFromStockBasket);
  const addPosition  = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper    = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper = useSettingsStore((s) => s.tradierPaper);

  const [execMode, setExecMode]         = useState<ExecMode>('recommendation');
  const [placingType, setPlacingType]   = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId]           = useState<string | null>(null);
  const [err, setErr]                   = useState<string | null>(null);
  const [added, setAdded]               = useState(false);
  const [queued, setQueued]             = useState(false);
  const [adding, setAdding]             = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);
  const [tastytradeConfigured, setTastytradeConfigured] = useState(false);

  const pinned            = stockBasket.some((c) => c.symbol === card.symbol);
  const ibkrConfigured    = !!ibkrPaper.accountId && !!ibkrPaper.baseUrl;
  const tradierConfigured = !!tradierPaper.token && !!tradierPaper.accountId;

  useEffect(() => {
    api.getBrokerStatus()
      .then((s) => {
        setAlpacaConfigured(s.alpaca_paper?.configured ?? false);
        setTastytradeConfigured(s.tastytrade_paper?.configured ?? false);
      })
      .catch(() => {});
  }, []);

  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation') return;
    setPlacingType(orderType);
    setErr(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        quantity: overlay.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? overlay.entry : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }

  async function onAddToPortfolio() {
    if (adding || added || queued) return; // guards against a double-click firing two adds
    setAdding(true);
    setErr(null);
    try {
      const res = await addPosition(
        buildPaperStockPosition(card.symbol, overlay.entry, overlay.shares, stockCardSnapshotOf(card)),
      );
      if (res.status === 'rejected') {
        setErr(res.detail ?? 'Portfolio rejected this position.');
        return;
      }
      if (res.status === 'pending') {
        // Optimistically added but not confirmed by the backend — syncFromBackend's
        // poll will retry. Show it as queued, NOT as saved, and block re-clicks
        // (the row is already in the store; another add would merge/duplicate).
        setQueued(true);
        return;
      }
      setAdded(true);
    } finally {
      setAdding(false);
    }
  }

  const rrT1 = rrAt(overlay.t1);
  const rrT2 = rrAt(overlay.t2);
  const rrT3 = rrAt(overlay.t3);

  const winTone = card.backtest.win_rate >= 0.5 ? 'pass' : 'caution';

  return (
    <div className={styles.wrap}>

      {/* Section 1 — Sizing grid, Row 1 */}
      <div className={styles.grid4}>
        <EditableField label="ENTRY"    value={overlay.entry} onChange={(v) => patch({ entry: v })} />
        <EditableField label="STOP"     value={overlay.stop}  onChange={(v) => patch({ stop: v })}  tone="reject" />
        <EditableField label="T1 TARGET" value={overlay.t1}  onChange={(v) => patch({ t1: v })}    tone="pass" />
        <div className={styles.editCell}>
          <Text size={10} tone="dim">R:R AT T1</Text>
          <Data size={14} weight={500}>{rrT1.toFixed(1)}×</Data>
        </div>
      </div>

      {/* Section 1 — Sizing grid, Row 2 */}
      <div className={styles.grid4}>
        <EditableField
          label="SHARES"
          value={overlay.shares}
          onChange={(v) => patch({ shares: Math.max(1, Math.round(v)) })}
          integer
        />
        <div className={styles.editCell}>
          <Text size={10} tone="dim">RISK $</Text>
          <Data size={14} weight={500} tone="reject">{riskDollars.toFixed(0)}</Data>
        </div>
        <div className={styles.editCell}>
          <Text size={10} tone="dim">SIZE $</Text>
          <Data size={14} weight={500}>{sizeDollars.toFixed(0)}</Data>
        </div>
        <div className={styles.editCell}>
          <Text size={10} tone="dim">WIN %</Text>
          <Data size={14} weight={500} tone={winTone} title={winRateTooltip(card.backtest.win_rate, 0.5)}>
            {(card.backtest.win_rate * 100).toFixed(0)}%
          </Data>
        </div>
      </div>

      {/* Section 2 — Sell-to-Close plan (T1 / T2 / T3) */}
      <div className={styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <Text size={11} tone="dim">SELL-TO-CLOSE PLAN</Text>
        </div>

        {([
          {
            id: 'T1',
            price: overlay.t1,
            onPrice: (v: number) => patch({ t1: v }),
            shares: overlay.sharesT1,
            onShares: (v: number) => patch({ sharesT1: v }),
            rr: rrT1,
          },
          {
            id: 'T2',
            price: overlay.t2,
            onPrice: (v: number) => patch({ t2: v }),
            shares: overlay.sharesT2,
            onShares: (v: number) => patch({ sharesT2: v }),
            rr: rrT2,
          },
          {
            id: 'T3',
            price: overlay.t3,
            onPrice: (v: number) => patch({ t3: v }),
            shares: overlay.sharesT3,
            onShares: (v: number) => patch({ sharesT3: v }),
            rr: rrT3,
          },
        ] as const).map(({ id, price, onPrice, shares: sh, onShares, rr }) => {
          const profitPct = overlay.entry > 0
            ? (card.direction === 'Bullish'
                ? (price - overlay.entry) / overlay.entry
                : (overlay.entry - price) / overlay.entry) * 100
            : 0;
          const retPct = profitPct.toFixed(1);
          return (
            <div key={id} className={styles.targetRow}>
              <div className={styles.targetLabel}>
                <Text size={12} weight={500}>{id}</Text>
              </div>
              <div className={styles.targetValues}>
                <EditableField label="" value={price} onChange={onPrice} />
                <Data size={12} tone={rr >= 1.5 ? 'pass' : rr >= 1 ? 'caution' : 'reject'}>
                  {rr.toFixed(1)}×
                </Data>
                <Data size={12} tone={profitPct > 0 ? 'pass' : 'reject'}>
                  {retPct}%
                </Data>
                <EditableField
                  label=""
                  value={sh}
                  onChange={(v) => onShares(Math.max(0, Math.round(v)))}
                  integer
                />
              </div>
            </div>
          );
        })}
      </div>

      <MarketSentiment s={card.sentiment} />

      <FundamentalHealthCard f={card.fundamentals} />

      {/* Section 3 — Action buttons */}
      <div className={styles.actionRow}>
        <a
          href={`/chart?symbol=${encodeURIComponent(card.symbol)}`}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.actionBtn}
        >
          <Text size={12}>View Chart</Text>
        </a>
        <button
          type="button"
          className={styles.actionBtn}
          onClick={() => (pinned ? removeBasket(card.symbol) : addToBasket(card))}
        >
          <Text size={12}>{pinned ? 'Unpin from Basket' : 'Pin to Basket'}</Text>
        </button>
        <button
          type="button"
          className={styles.actionBtn}
          onClick={onAddToPortfolio}
          disabled={added || adding || queued}
        >
          <Text size={12}>
            {added ? 'Added to Portfolio' : queued ? 'Queued — will sync' : adding ? 'Adding…' : 'Add to Portfolio'}
          </Text>
        </button>
      </div>

      {/* Section 4 — Broker mode selector */}
      <div className={styles.modeRow}>
        {([
          ['recommendation', 'Recommendation', true],
          ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
          ['tradier_paper', 'Tradier Paper',   tradierConfigured],
          ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
          ['tastytrade_paper', 'Tastytrade Paper', tastytradeConfigured],
        ] as Array<[ExecMode, string, boolean]>).map(([mode, label, ok]) => (
          <button
            key={mode}
            type="button"
            className={`${styles.modeBtn} ${execMode === mode ? styles.modeBtnActive : ''}`}
            disabled={!ok}
            title={!ok ? 'Not configured — Settings → Brokers' : undefined}
            onClick={() => setExecMode(mode)}
          >
            <Text size={12} weight={500}>{label}</Text>
          </button>
        ))}
      </div>

      {/* Section 5 — Order buttons */}
      {execMode !== 'recommendation' && (
        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={() => submit('LMT')}
            disabled={placingType !== null}
          >
            <Text size={12}>{placingType === 'LMT' ? 'Placing…' : `Limit @ $${overlay.entry.toFixed(2)}`}</Text>
          </button>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={() => submit('MKT')}
            disabled={placingType !== null}
          >
            <Text size={12}>{placingType === 'MKT' ? 'Placing…' : 'Market Order'}</Text>
          </button>
        </div>
      )}

      {/* Section 6 — Order result / error */}
      {orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {err      && <Text size={12} tone="reject">{err}</Text>}
      {queued   && <Text size={12} tone="caution">Queued — backend unreachable, will sync automatically.</Text>}

      {/* Section 7 — Auto-trade arm */}
      <StockAutoTradeArm
        symbol={card.symbol}
        strategyKey={strategyKey}
        direction={card.direction === 'Bullish' ? 'Bullish' : 'Bearish'}
        afterScanArmed={afterScanArmed ?? false}
        onAfterScanToggle={onAfterScanToggle ?? (() => {})}
      />

    </div>
  );
}
