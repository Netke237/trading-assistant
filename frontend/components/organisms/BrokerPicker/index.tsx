'use client';

import { Text } from '@/components/primitives';
import { useSettingsStore } from '@/lib/settingsStore';
import type { OptionsBroker } from '@/lib/autoTradeStore';
import styles from './BrokerPicker.module.css';

interface BrokerPickerProps {
  selected: OptionsBroker | null;
  onChange: (b: OptionsBroker) => void;
}

export function BrokerPicker({ selected, onChange }: BrokerPickerProps) {
  const { ibkrPaper, tradierPaper } = useSettingsStore();
  const ibkrOk    = !!ibkrPaper.accountId;
  const tradierOk = !!tradierPaper.token && !!tradierPaper.accountId;

  return (
    <div className={styles.wrap}>
      <Text size={11} tone="dim">Execute via</Text>
      <div className={styles.row}>
        {([
          { key: 'ibkr_paper' as OptionsBroker, label: 'IBKR Paper', ok: ibkrOk },
          { key: 'tradier_paper' as OptionsBroker, label: 'Tradier Paper', ok: tradierOk },
        ] as const).map(({ key, label, ok }) => (
          <button
            key={key}
            type="button"
            className={`${styles.btn} ${selected === key ? styles.btnActive : ''}`}
            disabled={!ok}
            onClick={() => onChange(key)}
            title={!ok ? 'Configure in Settings → Brokers' : undefined}
          >
            <Text size={12} weight={selected === key ? 600 : 400}>{label}</Text>
            {!ok && <Text size={10} tone="dim">Not configured</Text>}
          </button>
        ))}
      </div>
    </div>
  );
}
