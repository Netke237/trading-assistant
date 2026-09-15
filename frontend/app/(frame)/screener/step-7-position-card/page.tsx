'use client';

import { useState, useEffect, useRef } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import { useScanStore } from '@/lib/scanStore';
import { selectCardEdits, pickedFieldsFrom } from '@/lib/cardEdits';
import { useSettingsStore } from '@/lib/settingsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
import { api } from '@/lib/api';
import { checkMethodPick, MISSING_METHOD_PICK_TITLE, MISSING_METHOD_PICK_MESSAGE } from '@/lib/risk';
import { stockStatusTooltip, winRateTooltip } from '@/lib/statusTooltips';
import type { PositionCardData } from '@/types/stockDomain';
import styles from './page.module.css';

type ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';

function ExecutionModeButton({ label, desc, active, disabled, onClick }:
  { label: string; desc: string; active: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`${styles.modeBtn} ${active ? styles.modeBtnActive : ''}`}
      disabled={disabled}
      onClick={onClick}
      title={disabled ? 'Not configured — enter credentials in Settings → Brokers' : undefined}
    >
      <Text size={13} weight={600}>{label}</Text>
      <Text size={11} tone="secondary">{desc}</Text>
      {disabled && <Text size={10} tone="dim">Not configured</Text>}
    </button>
  );
}

export default function Step7PositionCardPage() {
  const result = useScanStore((s) => s.stockScanResult);
  const selectedSymbol = useScanStore((s) => s.selectedSymbol);
  // Phase G piece 5, build step 4 (§7.2, S3). This is a SEPARATE component
  // from `StockPositionCard` (§2.5) — its own `submit()`, its own
  // `postStockOrder` -> `addPosition` pair — so it needs its own read of the
  // stamped picks slice rather than inheriting one gated elsewhere.
  const stocksPicks = useScanStore((s) => selectCardEdits(s, 'stocks').picks);
  const [selectedIdx, setSelectedIdx] = useState(() => {
    const passing = result?.candidates.filter((c) => c.backtest.passes_gate) ?? [];
    const i = passing.findIndex((c) => c.symbol === selectedSymbol);
    return i >= 0 ? i : 0;
  });
  const [execMode, setExecMode] = useState<ExecutionMode>('recommendation');
  const [placingType, setPlacingType] = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  // Which candidate `orderId` belongs to. orderId itself is NOT per-candidate
  // state, but reset-on-navigate (either direction) has its own failure mode:
  // resetting it to null on every nav click re-arms the Buy buttons for a
  // candidate that already has a live order the instant the user navigates
  // away and back to it, permitting a duplicate submission. Comparing this
  // against `selectedIdx` below, instead of ever clearing orderId on
  // navigation, is what lets "does this candidate have an order" stay
  // correct regardless of how the user gets back to it.
  const [orderedIdx, setOrderedIdx] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const settings = useSettingsStore();
  const addPosition = usePortfolioStore((s) => s.addPosition);
  const scanHorizon = useScanStore((s) => s.context?.horizon ?? 'Swing');

  const ibkrConfigured = !!settings.ibkrPaper.accountId && !!settings.ibkrPaper.baseUrl;
  const tradierConfigured = !!settings.tradierPaper.token && !!settings.tradierPaper.accountId;
  const [alpacaPaperConfigured, setAlpacaPaperConfigured] = useState(false);
  const [tastytradePaperConfigured, setTastytradePaperConfigured] = useState(false);

  useEffect(() => {
    api.getBrokerStatus().then((s) => {
      setAlpacaPaperConfigured(s.alpaca_paper?.configured ?? false);
      setTastytradePaperConfigured(s.tastytrade_paper?.configured ?? false);
    }).catch(() => {/* silently ignore — button stays disabled */});
  }, []);

  const candidates = result?.candidates.filter((c) => c.backtest.passes_gate) ?? [];
  const card: PositionCardData | undefined = candidates[selectedIdx];
  const hasOrderForCurrent = orderId !== null && orderedIdx === selectedIdx;
  const pickMissing = !card || !checkMethodPick(stocksPicks[card.symbol] ?? null);

  // error/warning are transient feedback about a submit, not durable
  // per-candidate state like orderId/orderedIdx above — if the user switches
  // candidates while a submit() is still in flight, a stale response landing
  // after the switch must not stamp an error/warning onto whatever candidate
  // is now on screen. addPosition() still always runs for the
  // originally-submitted card — a real order was placed and must be tracked
  // regardless of what the user looks at next.
  const selectedIdxRef = useRef(selectedIdx);
  useEffect(() => { selectedIdxRef.current = selectedIdx; }, [selectedIdx]);

  const [spotPrice,    setSpotPrice]    = useState<number | null>(null);
  const [fetchingSpot, setFetchingSpot] = useState(false);

  useEffect(() => {
    if (!card?.symbol) { setSpotPrice(null); return; }
    let cancelled = false;
    setSpotPrice(null);
    setFetchingSpot(true);
    api.getStockQuote(card.symbol)
      .then((q) => { if (!cancelled) setSpotPrice(q.price); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setFetchingSpot(false); });
    return () => { cancelled = true; };
  }, [card?.symbol]);

  if (!card) {
    return (
      <div className={styles.main}>
        <Text size={13} tone="dim">No passing candidates. Go back to Step 6.</Text>
      </div>
    );
  }

  async function submit(orderType: 'LMT' | 'MKT') {
    if (!card || execMode === 'recommendation' || hasOrderForCurrent) return;
    // Phase G piece 5, build step 4 (§7.2, S3) — belt-and-braces beside the
    // button's own `disabled`, on the same reading `pickMissing` was derived
    // from.
    if (pickMissing) return;
    const submittedIdx = selectedIdx;
    const stillViewing = () => selectedIdxRef.current === submittedIdx;
    setPlacingType(orderType);
    setError(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: card.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? card.strategy.entry_price : null,
        tif: 'DAY',
      });
      // Recorded regardless of `stillViewing()` — unlike error/warning below
      // (transient feedback about a submit the user watched happen), this is
      // durable "does candidate X have an order" state that must stay correct
      // even after the user has navigated away, per `hasOrderForCurrent` above.
      setOrderId(res.order_id);
      setOrderedIdx(submittedIdx);
      try {
        const addRes = await addPosition({
          ...buildPaperStockPosition(
            card.symbol, card.strategy.entry_price, card.shares, card.direction as 'Bullish' | 'Bearish',
            stockCardSnapshotOf(card, scanHorizon),
            {
              stop: card.strategy.stop_price,
              targets: (card.strategy.targets?.length ? card.strategy.targets : [card.strategy.target_price])
                .map((price) => ({ price })),
            },
          ),
          source: 'broker',
          sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`,
          orderedAt: new Date().toISOString(),
          // Phase G (piece 5) — confirmed gap as of build step 4: the send
          // gate blocked an unpicked send but nothing carried a made pick's
          // VALUE into the created position.
          ...pickedFieldsFrom(stocksPicks[card.symbol] ?? null),
        });
        if (stillViewing() && (addRes.status === 'rejected' || addRes.status === 'pending')) {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        if (stillViewing()) setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      if (stillViewing()) setError(String(e));
    } finally {
      setPlacingType(null);
    }
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 7 OF 7</Text>
        <Title as="h1" size={24}>Position Card</Title>
      </div>

      <div className={styles.nav}>
        {candidates.map((c, i) => (
          <button key={c.symbol} type="button"
            className={`${styles.navBtn} ${i === selectedIdx ? styles.navBtnActive : ''}`}
            onClick={() => { setSelectedIdx(i); setError(null); setWarning(null); }}>
            <Data size={12} weight={500}>{c.symbol}</Data>
          </button>
        ))}
      </div>

      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div>
            <Text size={14} weight={600}>{card.company}</Text>
            <Text size={11} tone="secondary">{card.direction} · {card.strategy.strategy.replace(/_/g, ' ')}</Text>
          </div>
          <div className={styles.badges}>
            <ConfidenceBadge confidence={card.confidence} title={card.confidence_text ?? undefined} />
            <StatusBadge status={card.stock_status} tooltip={stockStatusTooltip(card.stock_status, card.stock_score)} />
          </div>
        </div>

        <div className={styles.grid4}>
          <div>
            <Text size={10} tone="dim">ENTRY</Text>
            <Data size={16} weight={500}>${card.strategy.entry_price}</Data>
            {fetchingSpot && <Text size={10} tone="dim">Fetching…</Text>}
            {spotPrice !== null && !fetchingSpot && (
              <Text size={10} tone="secondary">Now ${spotPrice.toFixed(2)}</Text>
            )}
          </div>
          <div><Text size={10} tone="dim">STOP</Text><Data size={16} weight={500} tone="reject">${card.strategy.stop_price}</Data></div>
          <div><Text size={10} tone="dim">TARGET</Text><Data size={16} weight={500} tone="pass">${card.strategy.target_price}</Data></div>
          <div><Text size={10} tone="dim">R:R</Text><Data size={16} weight={500}>{card.strategy.rr_ratio.toFixed(1)}</Data></div>
        </div>

        <div className={styles.grid4}>
          <div><Text size={10} tone="dim">SHARES</Text><Data size={16} weight={500}>{card.shares}</Data></div>
          <div><Text size={10} tone="dim">RISK $</Text><Data size={16} weight={500}>{card.dollar_risk.toFixed(0)}</Data></div>
          <div><Text size={10} tone="dim">SIZE $</Text><Data size={16} weight={500}>{card.dollar_size.toFixed(0)}</Data></div>
          <div><Text size={10} tone="dim">WIN %</Text><Data size={16} weight={500} tone={card.backtest.win_rate >= 0.5 ? 'pass' : 'caution'} title={winRateTooltip(card.backtest.win_rate, 0.5)}>{(card.backtest.win_rate * 100).toFixed(0)}%</Data></div>
        </div>
      </div>

      <div className={styles.execSection}>
        <Text size={13} weight={600}>Execution</Text>
        <div className={styles.modeRow}>
          <ExecutionModeButton label="Recommendation" desc="Show only — no order placed"
            active={execMode === 'recommendation'} onClick={() => setExecMode('recommendation')} />
          <ExecutionModeButton label="IBKR Paper" desc="Simulated via IBKR paper gateway"
            active={execMode === 'ibkr_paper'} disabled={!ibkrConfigured} onClick={() => setExecMode('ibkr_paper')} />
          <ExecutionModeButton label="Tradier Paper" desc="Simulated via Tradier sandbox"
            active={execMode === 'tradier_paper'} disabled={!tradierConfigured} onClick={() => setExecMode('tradier_paper')} />
          <ExecutionModeButton label="Alpaca Paper" desc="Direct stock order"
            active={execMode === 'alpaca_paper'} disabled={!alpacaPaperConfigured} onClick={() => setExecMode('alpaca_paper')} />
          <ExecutionModeButton label="Tastytrade Paper" desc="Direct stock order via tastytrade"
            active={execMode === 'tastytrade_paper'} disabled={!tastytradePaperConfigured} onClick={() => setExecMode('tastytrade_paper')} />
        </div>
      </div>

      {execMode !== 'recommendation' && (
        <div className={styles.actions}>
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={() => submit('LMT')} disabled={placingType !== null || hasOrderForCurrent || pickMissing}
            title={pickMissing ? MISSING_METHOD_PICK_TITLE : undefined}>
            {placingType === 'LMT' ? 'Placing…' : `Place Limit Order @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={`${styles.btn} ${styles.btnMarket}`}
            onClick={() => submit('MKT')} disabled={placingType !== null || hasOrderForCurrent || pickMissing}
            title={pickMissing ? MISSING_METHOD_PICK_TITLE : undefined}>
            {placingType === 'MKT' ? 'Placing…' : 'Right Now — Market Order'}
          </button>
        </div>
      )}

      {hasOrderForCurrent && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {execMode !== 'recommendation' && pickMissing && (
        <Text size={12} tone="reject">{MISSING_METHOD_PICK_MESSAGE}</Text>
      )}
      {error && <Text size={12} tone="reject">{error}</Text>}
      {warning && <Text size={12} tone="caution">{warning}</Text>}
    </div>
  );
}
