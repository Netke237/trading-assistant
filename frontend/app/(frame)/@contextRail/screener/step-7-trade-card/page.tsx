/*
 * Trade Card right-rail. Spec §4: Pre-trade checklist + historical analogs.
 * The checklist is scoped to a SINGLE stock (the candidate being planned).
 * QuickLook below keeps watchlist + portfolio totals one glance away.
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import styles from './page.module.css';

// Mock — will be driven by the selected candidate symbol once the screener store is wired.
const SCOPE_SYMBOL = 'AAPL';

const CHECKLIST: { label: string; status: 'PASS' | 'CAUTION' | 'REJECT' }[] = [
  { label: 'Regime PASS',            status: 'PASS'    },
  { label: 'IV rank acceptable',     status: 'PASS'    },
  { label: 'Earnings > 7d away',     status: 'CAUTION' },
  { label: 'Spread < 5% of price',   status: 'PASS'    },
  { label: 'Score ≥ 70',             status: 'PASS'    },
  { label: 'R:R ≥ 2.0',              status: 'PASS'    },
  { label: 'Position sizing in limits', status: 'PASS' },
];

const ANALOGS = [
  { date: '2026-02-14', outcome: '+18% in 9d'  },
  { date: '2025-11-07', outcome: '+11% in 14d' },
  { date: '2025-08-22', outcome: '−6% stopped' },
];

export default function TradeCardContextRail() {
  return (
    <>
      <RailSection title={`Pre-trade checklist · ${SCOPE_SYMBOL}`}>
        <Text size={11} tone="dim">
          Gates for this single candidate. Portfolio-level checks live below.
        </Text>
        <div className={styles.checklistStack}>
          {CHECKLIST.map((c) => (
            <div key={c.label} className={styles.checklistRow}>
              <StatusDot tone={c.status} size="sm" />
              <Text size={12} tone={c.status === 'CAUTION' ? 'caution' : 'secondary'}>
                {c.label}
              </Text>
            </div>
          ))}
        </div>
      </RailSection>

      <RailSection title={`Historical analogs · ${SCOPE_SYMBOL}`}>
        <div className={styles.analogStack}>
          {ANALOGS.map((a) => (
            <div key={a.date} className={styles.analogRow}>
              <Data size={11} tone="secondary">{a.date}</Data>
              <Text size={12}>{a.outcome}</Text>
            </div>
          ))}
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}
