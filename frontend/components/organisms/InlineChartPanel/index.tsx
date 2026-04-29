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

import { ChartPanelHeader } from '@/components/molecules/ChartPanelHeader';
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
          <ChartPanelHeader symbol={symbol} onClose={onClose} />
          <div className={styles.chartArea}>
            <CandlestickChart data={candlesFor(symbol)} height={360} />
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
