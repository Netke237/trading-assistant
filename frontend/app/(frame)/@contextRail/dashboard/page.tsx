'use client';

/*
 * Dashboard right-rail.
 * Spec: Last Scan summary · Latest Alert · Portfolio Risk · QuickLook.
 */

import { useEffect, useState } from 'react';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { StatusDot } from '@/components/atoms/StatusDot';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import { openTotals, unquotedNote } from '@/lib/portfolioTotals';
import { scanPipelineStatusTooltip, regimeStatusTooltip, alertStatusTooltip, eventProximityGateTooltip } from '@/lib/statusTooltips';
import type { AlertItem, UpcomingEvent } from '@/types/domain';
import styles from './page.module.css';

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' });
}

export default function DashboardContextRail() {
  const { scanState, context, scanAt, optionsScanAt, stockScanAt } = useScanStore();
  const combinedRegime = useScanStore((s) => s.combinedRegime);
  const positions = usePortfolioStore((s) => s.positions);
  const [alerts, setAlerts]   = useState<AlertItem[]>([]);
  const [events, setEvents]   = useState<UpcomingEvent[]>([]);

  useEffect(() => {
    api.getAlerts()
      .then((data) => setAlerts([...data].sort((a, b) => b.timestamp > a.timestamp ? 1 : -1)))
      .catch(() => {});
    api.getEvents().then(setEvents).catch(() => {});
  }, []);

  // Positions without a quote are left out of the totals (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, unquoted } = openTotals(positions);
  const note = unquotedNote(unquoted);

  const contextStr = context
    ? `${context.universe} · ${context.direction} · ${context.horizon}`
    : '—';

  const latestAlert = alerts[0];

  return (
    <>
      <RailSection title="Last Scan">
        <div className={styles.scanStack}>
          <div className={styles.scanRow}>
            <Text size={11} tone="dim">Option scan</Text>
            <div className={styles.scanTop}>
              <StatusBadge
                status={scanState === 'COMPLETED' ? 'PASS' : scanState === 'FAILED' ? 'REJECT' : 'PENDING'}
                label={scanState}
                tooltip={scanPipelineStatusTooltip(scanState)}
              />
              <Text size={12} tone="secondary">{formatTime(optionsScanAt ?? scanAt)}</Text>
            </div>
          </div>
          <Text size={12} tone="secondary" >{contextStr}</Text>
          <div className={styles.scanRow}>
            <Text size={11} tone="dim">Stock scan</Text>
            <div className={styles.scanTop}>
              {stockScanAt
                ? <><StatusBadge status="PASS" label="COMPLETED" tooltip={scanPipelineStatusTooltip('COMPLETED')} /><Text size={12} tone="secondary">{formatTime(stockScanAt)}</Text></>
                : <Text size={12} tone="dim">—</Text>
              }
            </div>
          </div>
        </div>
      </RailSection>

      <RailSection title="Market Regime">
        <div className={styles.regimeRow}>
          <StatusDot tone={combinedRegime} size="sm" title={regimeStatusTooltip(combinedRegime)} />
          <Text size={12} tone="secondary">
            {combinedRegime === 'PASS'    && 'Clear — EMA/VIX + HMM aligned.'}
            {combinedRegime === 'CAUTION' && 'Caution — mixed signals.'}
            {combinedRegime === 'REJECT'  && 'Reject — adverse regime.'}
            {combinedRegime === 'PENDING' && 'Run Step 1 to assess regime.'}
          </Text>
        </div>
      </RailSection>

      <RailSection title="Latest Alert">
        {latestAlert && (
          <div className={styles.alertBlock}>
            <div className={styles.alertTop}>
              <StatusBadge
                status={alertKindToStatus(latestAlert.kind)}
                label={latestAlert.kind.toUpperCase()}
                tooltip={alertStatusTooltip(latestAlert.kind)}
              />
              <Data size={12} weight={500}>{latestAlert.symbol}</Data>
            </div>
            <Text size={12}>{latestAlert.reason}</Text>
            <Text size={11} tone="dim">{latestAlert.timestamp}</Text>
          </div>
        )}
      </RailSection>

      <RailSection title="Upcoming Events">
        <div className={styles.eventStack}>
          {events.slice(0, 5).map((e) => (
            <div key={`${e.date}-${e.symbol}`} className={styles.eventRow}>
              <StatusDot tone={e.status} size="sm" title={eventProximityGateTooltip(e.status)} />
              <Data size={11} tone="secondary">{shortDate(e.date)}</Data>
              <Data size={11} weight={500}>{e.symbol}</Data>
              <Text size={12} tone="secondary">{e.label}</Text>
            </div>
          ))}
        </div>
      </RailSection>

      <RailSection title="Portfolio Risk">
        <div className={styles.riskStack}>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Deployed</Text>
            <Data size={12}>${Math.round(deployed).toLocaleString()}</Data>
          </div>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </div>
          <div className={styles.riskRow}>
            <Text size={12} tone="secondary">Positions</Text>
            <Data size={12}>{positions.length}</Data>
          </div>
          {note && <Text size={11} tone="caution">{note}</Text>}
        </div>
      </RailSection>

      <RailQuickLook />
    </>
  );
}

function alertKindToStatus(kind: string): 'PASS' | 'CAUTION' | 'REJECT' {
  if (kind === 'Critical') return 'REJECT';
  if (kind === 'Action')   return 'CAUTION';
  return 'PASS';
}

