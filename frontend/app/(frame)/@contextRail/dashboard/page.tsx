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
  const { scanState, context, scanAt } = useScanStore();
  const positions = usePortfolioStore((s) => s.positions);
  const [alerts, setAlerts]   = useState<AlertItem[]>([]);
  const [events, setEvents]   = useState<UpcomingEvent[]>([]);

  useEffect(() => {
    api.getAlerts().then(setAlerts).catch(() => {});
    api.getEvents().then(setEvents).catch(() => {});
  }, []);

  const deployed = positions.reduce((s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1), 0);
  const openPnL  = positions.reduce((s, p) => s + p.pnlDollar, 0);

  const contextStr = context
    ? `${context.universe} · ${context.direction} · ${context.horizon}`
    : '—';

  const latestAlert = alerts[0];

  return (
    <>
      <RailSection title="Last Scan">
        <div className={styles.scanStack}>
          <div className={styles.scanTop}>
            <StatusBadge status={scanState === 'COMPLETED' ? 'PASS' : scanState === 'FAILED' ? 'REJECT' : 'PENDING'} label={scanState} />
            <Text size={12} tone="secondary">{formatTime(scanAt)}</Text>
          </div>
          <Text size={12} tone="secondary">{contextStr}</Text>
        </div>
      </RailSection>

      <RailSection title="Latest Alert">
        {latestAlert && (
          <div className={styles.alertBlock}>
            <div className={styles.alertTop}>
              <StatusBadge status={alertKindToStatus(latestAlert.kind)} label={latestAlert.kind.toUpperCase()} />
              <Data size={12} weight={500}>{latestAlert.symbol}</Data>
            </div>
            <Text size={12}>{latestAlert.reason}</Text>
            <Text size={11} tone="dim">{latestAlert.timestamp}</Text>
          </div>
        )}
      </RailSection>

      <RailSection title="Upcoming Events (14d)">
        <div className={styles.eventStack}>
          {events.slice(0, 5).map((e) => (
            <div key={`${e.date}-${e.symbol}`} className={styles.eventRow}>
              <StatusDot tone={e.status} size="sm" />
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
