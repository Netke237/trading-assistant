'use client';

/*
 * InlineChartPanel — slide-up chart panel below the TradeCard / Watchlist row.
 * Spec §5 / drift log G8: chart is inline (not a modal), ~420px tall, animates
 * in/out with Framer Motion.
 *
 * Renders the real CandlestickChart (Lightweight Charts) when `open`, hydrating
 * data from /mocks/candles.ts.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { Text, Data } from '@/components/primitives';
import { IconButton } from '@/components/atoms/IconButton';
import { WatchStar } from '@/components/atoms/WatchStar';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { candlesFor } from '@/mocks/candles';
import styles from './InlineChartPanel.module.css';

interface InlineChartPanelProps {
  open: boolean;
  symbol: string;
  onClose: () => void;
}

export function InlineChartPanel({ open, symbol, onClose }: InlineChartPanelProps) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.section
          key="chart"
          className={styles.panel}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 420, opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          aria-label={`${symbol} chart panel`}
        >
          <header className={styles.header}>
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
          <div className={styles.chartArea}>
            <CandlestickChart data={candlesFor(symbol)} height={360} />
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
