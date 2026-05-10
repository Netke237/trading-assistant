'use client';

import { useScanStore } from '@/lib/scanStore';
import { exportValidationToXlsx } from '@/lib/export';
import { ValidationTable } from '@/components/organisms/ValidationTable';
import { Text, Title } from '@/components/primitives';
import styles from './page.module.css';

export default function ValidationPage() {
  const candidates = useScanStore((s) => s.scanResult?.candidates);
  const safeCandidates = candidates ?? [];

  if (safeCandidates.length === 0) {
    return (
      <div className={styles.main}>
        <div className={styles.stepHeader}>
          <Text size={11} tone="dim" weight={500}>VALIDATION</Text>
          <Title as="h1" size={24}>Validation Table</Title>
        </div>
        <Text size={13} tone="dim">Run a scan to see rule-level validation breakdown for every candidate.</Text>
      </div>
    );
  }

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>VALIDATION</Text>
        <Title as="h1" size={24}>Validation Table</Title>
      </div>

      <header className={styles.panelHeader}>
        <Text size={12} tone="secondary">
          Rule-level pass / fail breakdown across Trend, Pullback, Trigger, Event, Volatility for every ranked stock.
        </Text>
        <button
          className={styles.exportBtn}
          onClick={() => exportValidationToXlsx(safeCandidates, 'bamendjou-validation')}
        >
          Export .xlsx
        </button>
      </header>

      <ValidationTable candidates={safeCandidates} />
    </div>
  );
}
