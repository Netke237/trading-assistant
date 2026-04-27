import { Text, Data } from '@/components/primitives';
import { IconButton } from '@/components/atoms/IconButton';
import { WatchStar } from '@/components/atoms/WatchStar';
import styles from './ChartPanelHeader.module.css';

interface ChartPanelHeaderProps {
  symbol: string;
  onClose: () => void;
}

export function ChartPanelHeader({ symbol, onClose }: ChartPanelHeaderProps) {
  return (
    <header className={styles.root}>
      <div className={styles.titleGroup}>
        <Text size={14} weight={600}>Chart</Text>
        <Data size={13} weight={500}>{symbol}</Data>
        {symbol && <WatchStar symbol={symbol} size="sm" />}
        <Text size={11} tone="dim">1D · 120 bars</Text>
      </div>
      <IconButton aria-label="Close chart" onClick={onClose}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M3 3L11 11M11 3L3 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </IconButton>
    </header>
  );
}
