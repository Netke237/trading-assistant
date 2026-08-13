'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
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
  const [selectedIdx, setSelectedIdx] = useState(() => {
    const passing = result?.candidates.filter((c) => c.backtest.passes_gate) ?? [];
    const i = passing.findIndex((c) => c.symbol === selectedSymbol);
    return i >= 0 ? i : 0;
  });
  const [execMode, setExecMode] = useState<ExecutionMode>('recommendation');
  const [placingType, setPlacingType] = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const settings = useSettingsStore();

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
    if (!card || execMode === 'recommendation') return;
    setPlacingType(orderType);
    setError(null);
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
      setOrderId(res.order_id);
    } catch (e) {
      setError(String(e));
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
            onClick={() => { setSelectedIdx(i); setOrderId(null); setError(null); }}>
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
            <StatusBadge status={card.stock_status} />
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
          <div><Text size={10} tone="dim">WIN %</Text><Data size={16} weight={500} tone={card.backtest.win_rate >= 0.5 ? 'pass' : 'caution'}>{(card.backtest.win_rate * 100).toFixed(0)}%</Data></div>
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
            onClick={() => submit('LMT')} disabled={placingType !== null}>
            {placingType === 'LMT' ? 'Placing…' : `Place Limit Order @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={`${styles.btn} ${styles.btnMarket}`}
            onClick={() => submit('MKT')} disabled={placingType !== null}>
            {placingType === 'MKT' ? 'Placing…' : 'Right Now — Market Order'}
          </button>
        </div>
      )}

      {orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {error && <Text size={12} tone="reject">{error}</Text>}
    </div>
  );
}
