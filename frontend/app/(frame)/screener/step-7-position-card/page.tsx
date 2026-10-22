'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Title, Text, Data } from '@/components/primitives';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { DirectSendNotesPanel } from '@/components/organisms/DirectSendNotesPanel';
import { useScanStore } from '@/lib/scanStore';
import { stockExecutionIdentity } from '@/lib/stockExecutionSession';
import styles from './page.module.css';

export default function Step7PositionCardPage() {
  const result = useScanStore((s) => s.stockScanResult);
  const selectedSymbol = useScanStore((s) => s.selectedSymbol);
  const setSelectedSymbol = useScanStore((s) => s.setSelectedSymbol);
  const generation = useScanStore((s) => s.stockExecutionGeneration);
  const stockBasket = useScanStore((s) => s.stockBasket);
  const [showSendDialog, setShowSendDialog] = useState(false);

  const candidates = result?.candidates.filter((c) => c.backtest.passes_gate) ?? [];
  const selectedIdx = Math.max(0, candidates.findIndex((c) => c.symbol === selectedSymbol));
  const card = candidates[selectedIdx];
  const resolvedSymbol = card?.symbol;

  // Resolve synchronously so a replaced/removed candidate cannot render at an
  // old array index. Reconcile the store for Backtest and route remounts too.
  useEffect(() => {
    if (resolvedSymbol && resolvedSymbol !== selectedSymbol) setSelectedSymbol(resolvedSymbol);
  }, [resolvedSymbol, selectedSymbol, setSelectedSymbol]);

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 6</Text>
        <Title as="h1" size={24}>Position Card</Title>
        {stockBasket.length > 0 && (
          <button type="button" className={styles.navBtn} onClick={() => setShowSendDialog(true)}>
            Send basket ({stockBasket.length})
          </button>
        )}
      </div>

      {card ? (
        <>
          <nav className={styles.nav} aria-label="Position candidates">
            <button type="button" className={styles.navBtn} disabled={selectedIdx === 0}
              onClick={() => setSelectedSymbol(candidates[selectedIdx - 1].symbol)}>Prev</button>
            <Text size={12} tone="secondary">{selectedIdx + 1} of {candidates.length}</Text>
            <button type="button" className={styles.navBtn} disabled={selectedIdx === candidates.length - 1}
              onClick={() => setSelectedSymbol(candidates[selectedIdx + 1].symbol)}>Next</button>
            {candidates.map((candidate) => (
              <button key={candidate.symbol} type="button"
                className={`${styles.navBtn} ${candidate.symbol === card.symbol ? styles.navBtnActive : ''}`}
                aria-current={candidate.symbol === card.symbol ? 'true' : undefined}
                onClick={() => setSelectedSymbol(candidate.symbol)}>
                <Data size={12} weight={500}>{candidate.symbol}</Data>
              </button>
            ))}
          </nav>

          <section className={styles.card} aria-label={`${card.symbol} position`}>
            <StockPositionCard
              key={stockExecutionIdentity({ stockScanResult: result, stockExecutionGeneration: generation }, card.symbol) ?? card.symbol}
              presentation="position"
              card={card}
              strategyKey={card.strategy.strategy}
            />
          </section>
        </>
      ) : (
        <Text size={13} tone="dim">No passing candidates. <Link href="/screener/step-6-backtest">Go back to Step 5 (Backtest).</Link></Text>
      )}

      <DirectSendNotesPanel />
      {showSendDialog && (
        <StockSendDialog cards={stockBasket} onClose={() => setShowSendDialog(false)}
          onSubmit={() => setShowSendDialog(false)} />
      )}
    </div>
  );
}
