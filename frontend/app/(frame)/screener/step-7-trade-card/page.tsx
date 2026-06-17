'use client';

/*
 * Screener Step 7 — Trade Card.
 * Prev/Next cycles ranked candidates, basket pins multiple. Send basket
 * opens a review dialog where any row can be switched from auto-send
 * (sent to broker mock) to manual (added to portfolio tagged MANUAL).
 * Successful submits surface a bottom-right toast with a Portfolio link.
 */

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Title, Text } from '@/components/primitives';
import { TradeCard } from '@/components/organisms/TradeCard';
import { CandidateNav } from '@/components/molecules/CandidateNav';
import { SendToBrokerDialog, type DraftOrder } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { contractId as buildContractId } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import { logAudit } from '@/lib/audit';
import { statusForScore } from '@/lib/status';
import type { Status } from '@/lib/status';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { PortfolioPosition, TradeCardData } from '@/types/domain';
import { BrokerPicker }      from '@/components/organisms/BrokerPicker';
import { AutoTradeArm }      from '@/components/organisms/AutoTradeArm';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api }               from '@/lib/api';
import styles from '../screener.module.css';
import toastStyles from './toast.module.css';
import paperStyles from './page.module.css';

function nowISOLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function todayISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

function positionFromOrder(order: DraftOrder): PortfolioPosition {
  const c   = order.card;
  const cd  = c.contractDetails;
  const mid = cd?.mid ?? c.entry.limit;
  const dte = cd?.dte ?? 24;
  return {
    symbol:        c.symbol,
    contract:      c.contract,
    direction:     c.direction,
    entryDate:     todayISO(),
    expiry:        cd?.expiry ?? new Date(Date.now() + dte * 86_400_000).toISOString().slice(0, 10),
    dteRemaining:  dte,
    dteTotal:      dte,
    entryPrice:    mid,
    currentPrice:  mid,
    pnlDollar:     0,
    pnlPct:        0,
    stop:          c.exit.invalidation,
    targets:       c.exit.targets,
    status:        c.finalStatus,
    ivRank:        cd?.ivRank,
    delta:         cd?.delta,
    theta:         cd?.theta,
    vega:          0.20,
    contracts:     order.contracts,
    source:        order.autoSend ? 'broker' : 'manual',
    orderedAt:     nowISOLocal(),
    recId:         generateRecId(),
  };
}

interface ToastState {
  auto:    number;
  manual:  number;
}

export default function Step7Page() {
  const [cards, setCards]         = useState<TradeCardData[]>([]);
  const [active, setActive]       = useState<string>('');
  const [basket, setBasket]       = useState<string[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast]         = useState<ToastState | null>(null);
  const [recIdMap, setRecIdMap]   = useState<Record<string, string>>({});

  useEffect(() => {
    setRecIdMap((prev) => {
      const next: Record<string, string> = {};
      for (const c of cards) {
        next[c.symbol] = prev[c.symbol] || generateRecId();
      }
      return next;
    });
  }, [cards]);

  const { selectedBroker, setSelectedBroker } = useAutoTradeStore();
  const [limitPlacing,   setLimitPlacing]     = useState(false);
  const [marketPlacing,  setMarketPlacing]    = useState(false);
  const [paperOrderId,   setPaperOrderId]     = useState<string | null>(null);
  const [orderError,     setOrderError]       = useState<string | null>(null);

  const scanResult          = useScanStore((s) => s.scanResult);
  const setSelectedSymbol   = useScanStore((s) => s.setSelectedSymbol);
  const pickedContracts     = useScanStore((s) => s.pickedContracts);
  const contractsBySymbol   = useScanStore((s) => s.contractsBySymbol);

  useEffect(() => {
    if (scanResult?.candidates?.length) {
      setCards(scanResult.candidates);
      if (scanResult.candidates[0]) setActive(scanResult.candidates[0].symbol);
    } else {
      setCards([]);
      setActive('');
    }
  }, [scanResult]);

  useEffect(() => {
    if (active) setSelectedSymbol(active);
  }, [active, setSelectedSymbol]);

  // Clear paper order feedback when the user navigates to a different candidate.
  useEffect(() => { setPaperOrderId(null); setOrderError(null); }, [active]);

  const addPosition = usePortfolioStore((s) => s.addPosition);
  const incrementDaily = useRiskStore((s) => s.incrementDaily);

  const cardIndex = useMemo(
    () => Object.fromEntries(cards.map((c) => [c.symbol, c])),
    [cards],
  );
  const symbols = cards.map((c) => c.symbol);

  const card = cardIndex[active] ?? cards[0];

  const pickedId = pickedContracts[card?.symbol ?? ''];
  const pickedContract = pickedId
    ? contractsBySymbol[card?.symbol ?? '']?.find((c) => c.id === pickedId)
    : undefined;

  const effectiveCard = pickedContract && pickedContract.id !== card?.contract
    ? {
        ...card,
        contract: pickedContract.id,
        contractScore: pickedContract.score,
        contractConfidence: statusForScore(pickedContract.score) as Status,
        contractBreakdown: card?.contractBreakdown,
        contractDetails: {
          strike:       pickedContract.strike,
          expiry:       pickedContract.expiry,
          right:        pickedContract.right,
          mid:          pickedContract.price,
          delta:        pickedContract.delta,
          theta:        pickedContract.theta,
          ivRank:       pickedContract.ivRank,
          ivPercentile: pickedContract.ivPercentile,
          dte:          pickedContract.dte,
        },
        _userOverride: true,
      }
    : card;

  const basketCards = useMemo<TradeCardData[]>(
    () => basket.map((s) => cardIndex[s]).filter((c): c is TradeCardData => !!c),
    [basket, cardIndex],
  );

  /** Build the pipe-delimited option id the OCC converter and broker adapters expect. */
  function toOptionSymbol(card: TradeCardData): string {
    const cd = card.contractDetails;
    if (cd?.strike != null && cd.expiry && cd.right) {
      return buildContractId(card.symbol, cd.strike, cd.expiry, cd.right);
    }
    return card.contract; // fallback (display label — broker may reject, best effort)
  }

  /** Add a successfully executed paper order to the portfolio for tracking. */
  function addPaperPosition(card: TradeCardData, orderType: 'LMT' | 'MKT', broker: string, orderId: string) {
    const cd  = card.contractDetails;
    const mid = cd?.mid ?? card.entry.limit;
    const dte = cd?.dte ?? 24;
    const brokerLabel = broker === 'tradier_paper' ? 'Tradier Paper' : 'IBKR Paper';
    const typeLabel   = orderType === 'LMT' ? 'Limit' : 'Market';
    addPosition({
      symbol:        card.symbol,
      contract:      card.contract,
      direction:     card.direction,
      entryDate:     todayISO(),
      expiry:        cd?.expiry ?? '2026-12-31',
      dteRemaining:  dte,
      dteTotal:      dte,
      entryPrice:    mid,
      currentPrice:  mid,
      pnlDollar:     0,
      pnlPct:        0,
      stop:          card.exit.invalidation,
      targets:       card.exit.targets,
      status:        card.finalStatus,
      ivRank:        cd?.ivRank,
      delta:         cd?.delta,
      theta:         cd?.theta,
      vega:          0.20,
      contracts:     1,
      source:        'paper',
      sourceLabel:   `${brokerLabel} — ${typeLabel} (ID: ${orderId})`,
      orderedAt:     nowISOLocal(),
      recId:         generateRecId(),
    });
  }

  async function placeLimitPaper() {
    const card = effectiveCard;
    if (!card || !selectedBroker) return;
    setLimitPlacing(true); setOrderError(null);
    try {
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),   // pipe format → OCC converter
        action:        'BUY',   // long single-leg option (call or put) is always buy-to-open
        quantity:      1,
        order_type:    'LMT',
        limit_price:   card.entry.limit,
        tif:           'DAY',
      });
      setPaperOrderId(res.order_id);
      addPaperPosition(card, 'LMT', selectedBroker, res.order_id);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setLimitPlacing(false);
    }
  }

  async function placeMarketNow() {
    const card = effectiveCard;
    if (!card || !selectedBroker) return;
    setMarketPlacing(true); setOrderError(null);
    try {
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),   // pipe format → OCC converter
        action:        'BUY',   // long single-leg option (call or put) is always buy-to-open
        quantity:      1,
        order_type:    'MKT',
        limit_price:   null,
        tif:           'DAY',
      });
      setPaperOrderId(res.order_id);
      addPaperPosition(card, 'MKT', selectedBroker, res.order_id);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setMarketPlacing(false);
    }
  }

  const idx = symbols.indexOf(active);

  const goPrev = () => { if (idx > 0) setActive(symbols[idx - 1]!); };
  const goNext = () => { if (idx >= 0 && idx < symbols.length - 1) setActive(symbols[idx + 1]!); };

  const togglePin = () =>
    setBasket((b) => (b.includes(active) ? b.filter((s) => s !== active) : [...b, active]));
  const removePin = (sym: string) => setBasket((b) => b.filter((s) => s !== sym));

  const handleSubmit = (orders: DraftOrder[], _riskOverridden: boolean) => {
    let auto = 0, manual = 0;
    for (const o of orders) {
      // One canonical recId per order: addPosition syncs it to the backend
      // (a single POST), so there is no second POST to conflict (409) with.
      const recId = recIdMap[o.card.symbol] ?? generateRecId();
      addPosition({ ...positionFromOrder(o), recId });
      incrementDaily();

      if (o.autoSend) auto++;
      else manual++;

      logAudit('APPROVE', recId, {
        symbol: o.card.symbol,
        contract: o.card.contract,
        contracts: o.contracts,
      });
    }
    setDialogOpen(false);
    setBasket([]);
    setToast({ auto, manual });
    window.setTimeout(() => setToast(null), 6000);
  };

  const basketEmpty = basket.length === 0;
  const sendLabel = basketEmpty ? 'Send to broker' : `Send basket (${basket.length})`;

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 7 OF 7</Text>
        <Title as="h1" size={24}>Trade Card</Title>
        <Text size={13} tone="secondary">
          Cycle candidates with Prev / Next. Pin multiple to the basket, then Send to broker — uncheck
          Auto-send for any contract you&apos;d rather place manually.
        </Text>
      </div>

      <CandidateNav
        symbols={symbols}
        activeSymbol={active}
        basket={basket}
        onPrev={goPrev}
        onNext={goNext}
        onSelect={setActive}
        onTogglePin={togglePin}
        onRemovePin={removePin}
      />

      {cards.length === 0 && (
        <Text size={13} tone="dim">Run a scan to generate trade cards.</Text>
      )}

      {effectiveCard && (
        <>
          {(effectiveCard as any)._userOverride && (
            <StatusBadge status="PENDING" label="User-selected" />
          )}
          <TradeCard
            data={effectiveCard}
            recId={recIdMap[effectiveCard.symbol]}
            onSendToBroker={() => !basketEmpty && setDialogOpen(true)}
            sendLabel={sendLabel}
            sendDisabled={basketEmpty}
          />
        </>
      )}

      {/* Paper broker execution */}
      {effectiveCard && (
        <div className={paperStyles.paperSection}>
          <BrokerPicker selected={selectedBroker} onChange={setSelectedBroker} />
          {selectedBroker && (
            <>
              <div className={paperStyles.paperButtons}>
                <button
                  type="button"
                  className={paperStyles.paperBtnLimit}
                  onClick={placeLimitPaper}
                  disabled={limitPlacing || marketPlacing}
                >
                  {limitPlacing ? 'Placing…' : `Place Limit @ $${effectiveCard.entry.limit}`}
                </button>
                <button
                  type="button"
                  className={paperStyles.paperBtnMarket}
                  onClick={placeMarketNow}
                  disabled={limitPlacing || marketPlacing}
                >
                  {marketPlacing ? 'Placing…' : 'Right Now — Market'}
                </button>
              </div>
              {paperOrderId && <Text size={12} tone="pass">Order placed — ID: {paperOrderId}</Text>}
              {orderError   && <Text size={12} tone="reject">{orderError}</Text>}
              <AutoTradeArm card={effectiveCard} broker={selectedBroker} />
            </>
          )}
        </div>
      )}

      {dialogOpen && (
        <SendToBrokerDialog
          cards={basketCards}
          onClose={() => setDialogOpen(false)}
          onSubmit={handleSubmit}
        />
      )}

      {toast && (
        <div className={toastStyles.toast} role="status" aria-live="polite">
          <div>
            <Text size={13} weight={500}>
              {toast.auto + toast.manual} order{toast.auto + toast.manual === 1 ? '' : 's'} queued
            </Text>
            <Text size={11} tone="secondary">
              {toast.auto} sent to broker · {toast.manual} added manually
            </Text>
          </div>
          <Link href="/portfolio" className={toastStyles.link}>
            View Portfolio →
          </Link>
        </div>
      )}
    </div>
  );
}
