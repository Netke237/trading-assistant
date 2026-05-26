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
import { useScanStore } from '@/lib/scanStore';
import { logAudit } from '@/lib/audit';
import { statusForScore } from '@/lib/status';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { PortfolioPosition, Status, TradeCardData } from '@/types/domain';
import styles from '../screener.module.css';
import toastStyles from './toast.module.css';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

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
    expiry:        cd?.expiry ?? '2026-05-15',
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

  const addPosition = usePortfolioStore((s) => s.addPosition);

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

  const idx = symbols.indexOf(active);

  const goPrev = () => { if (idx > 0) setActive(symbols[idx - 1]!); };
  const goNext = () => { if (idx >= 0 && idx < symbols.length - 1) setActive(symbols[idx + 1]!); };

  const togglePin = () =>
    setBasket((b) => (b.includes(active) ? b.filter((s) => s !== active) : [...b, active]));
  const removePin = (sym: string) => setBasket((b) => b.filter((s) => s !== sym));

  const handleSubmit = (orders: DraftOrder[], _riskOverridden: boolean) => {
    let auto = 0, manual = 0;
    for (const o of orders) {
      const pos = positionFromOrder(o);
      const recId = recIdMap[o.card.symbol] ?? generateRecId();
      addPosition(pos);

      if (o.autoSend) auto++;
      else manual++;

      const body = JSON.stringify({
        recId,
        symbol: pos.symbol,
        contract: pos.contract,
        direction: pos.direction,
        entryPrice: pos.entryPrice,
        qty: pos.contracts ?? 1,
        entryDate: pos.entryDate,
        stop: pos.stop,
        targets: pos.targets,
        dteTotal: pos.dteTotal,
      });

      fetch(`${BASE_URL}/api/portfolio`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
        .then(() => {
          logAudit('APPROVE', recId, {
            symbol: o.card.symbol,
            contract: o.card.contract,
            contracts: o.contracts,
          });
        })
        .catch(() => {
          // network error — position is still in local store
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
