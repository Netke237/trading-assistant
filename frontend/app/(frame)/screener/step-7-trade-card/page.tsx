'use client';

/*
 * Screener Step 7 — Trade Card.
 * Prev/Next cycles ranked candidates, basket pins multiple. Send basket
 * opens a review dialog where any row can be switched from auto-send
 * (sent to broker mock) to manual (added to portfolio tagged MANUAL).
 * Successful submits surface a bottom-right toast with a Portfolio link.
 */

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { Title, Text } from '@/components/primitives';
import { TradeCard } from '@/components/organisms/TradeCard';
import { CandidateNav } from '@/components/molecules/CandidateNav';
import { SendToBrokerDialog, type DraftOrder } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import {
  MOCK_CANDIDATE_CARDS,
  MOCK_CANDIDATE_INDEX,
} from '@/mocks/tradecards';
import type { PortfolioPosition, TradeCardData } from '@/types/domain';
import styles from '../screener.module.css';
import toastStyles from './toast.module.css';

const SYMBOLS = MOCK_CANDIDATE_CARDS.map((c) => c.symbol);

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
    target:        c.exit.target,
    status:        c.finalStatus,
    ivRank:        cd?.ivRank,
    delta:         cd?.delta,
    theta:         cd?.theta,
    vega:          0.20,
    contracts:     order.contracts,
    source:        order.autoSend ? 'broker' : 'manual',
    orderedAt:     nowISOLocal(),
  };
}

interface ToastState {
  auto:    number;
  manual:  number;
}

export default function Step7Page() {
  const [active, setActive] = useState<string>(SYMBOLS[0]!);
  const [basket, setBasket] = useState<string[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const addPosition = usePortfolioStore((s) => s.addPosition);

  const card = useMemo(
    () => MOCK_CANDIDATE_INDEX[active] ?? MOCK_CANDIDATE_CARDS[0]!,
    [active],
  );

  const basketCards = useMemo<TradeCardData[]>(
    () => basket.map((s) => MOCK_CANDIDATE_INDEX[s]).filter((c): c is TradeCardData => !!c),
    [basket],
  );

  const idx = SYMBOLS.indexOf(active);

  const goPrev = () => { if (idx > 0) setActive(SYMBOLS[idx - 1]!); };
  const goNext = () => { if (idx >= 0 && idx < SYMBOLS.length - 1) setActive(SYMBOLS[idx + 1]!); };

  const togglePin = () =>
    setBasket((b) => (b.includes(active) ? b.filter((s) => s !== active) : [...b, active]));
  const removePin = (sym: string) => setBasket((b) => b.filter((s) => s !== sym));

  const handleSubmit = (orders: DraftOrder[]) => {
    let auto = 0, manual = 0;
    for (const o of orders) {
      addPosition(positionFromOrder(o));
      if (o.autoSend) auto++; else manual++;
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
        symbols={SYMBOLS}
        activeSymbol={active}
        basket={basket}
        onPrev={goPrev}
        onNext={goNext}
        onSelect={setActive}
        onTogglePin={togglePin}
        onRemovePin={removePin}
      />

      <TradeCard
        data={card}
        onSendToBroker={() => !basketEmpty && setDialogOpen(true)}
        sendLabel={sendLabel}
        sendDisabled={basketEmpty}
      />

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
