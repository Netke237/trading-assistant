'use client';

import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { useScanStore } from '@/lib/scanStore';
import { STATUS_LABEL } from '@/lib/status';
import { regimeStatusTooltip } from '@/lib/statusTooltips';
import styles from './RegimeIndicator.module.css';

export function RegimeIndicator() {
  const regime = useScanStore((s) => s.regime);

  return (
    <div className={styles.root}>
      <StatusDot tone={regime} size="sm" title={regimeStatusTooltip(regime)} />
      <Text size={12} tone="secondary">{STATUS_LABEL[regime]}</Text>
    </div>
  );
}
