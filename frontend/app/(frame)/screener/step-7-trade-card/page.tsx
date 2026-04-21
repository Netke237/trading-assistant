/*
 * Screener Step 7 — Trade Card.
 * Renders the final TradeCard organism with mock data. Real data (from Step 6
 * contract selection) is wired in Phase 5.
 */

import { Title, Text } from '@/components/primitives';
import { TradeCard } from '@/components/organisms/TradeCard';
import { MOCK_TRADE_CARD } from '@/mocks/tradecard';
import styles from '../screener.module.css';

export default function Step7Page() {
  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 7 OF 7</Text>
        <Title as="h1" size={24}>Trade Card</Title>
      </div>
      <TradeCard data={MOCK_TRADE_CARD} />
    </div>
  );
}
