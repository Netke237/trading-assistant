'use client';

/*
 * Dashboard — Phase 5.
 * Bento layout: regime banner across top, then 3-column row
 * (Watchlist preview | Portfolio summary | Alerts).
 * Second bento row: News tied to watchlist + Contracts overview.
 * Right context rail (events + portfolio risk) comes from the parallel slot.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { SectionCard } from '@/components/molecules/SectionCard';
import { TableRow } from '@/components/molecules/TableRow';
import { AlertRow } from '@/components/molecules/AlertRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { RiskPanel } from '@/components/molecules/RiskPanel';
import type { WatchlistRow, PortfolioPosition, AlertItem, MarketRegime, NewsItem } from '@/types/domain';
import styles from './page.module.css';

const WL_COLUMNS = '60px 1fr 60px 64px 64px';

function formatScanAt(iso: string | null): string {
  if (!iso) return 'No scan yet';
  const d = new Date(iso);
  const day = d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: '2-digit', year: 'numeric' });
  const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  return `${day} · ${time}`;
}

export default function DashboardPage() {
  const router = useRouter();
  const { context, scanAt } = useScanStore();

  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioPosition[]>([]);
  const [alerts, setAlerts]       = useState<AlertItem[]>([]);
  const [regime, setRegime]       = useState<MarketRegime | null>(null);
  const [news, setNews]           = useState<NewsItem[]>([]);
  const [offline, setOffline]     = useState(false);

  useEffect(() => {
    api.getWatchlist().then(setWatchlist).catch(() => setOffline(true));
    api.getPortfolio().then(setPortfolio).catch(() => setOffline(true));
    api.getAlerts().then(setAlerts).catch(() => setOffline(true));
    api.getRegime().then(setRegime).catch(() => setOffline(true));
  }, []);

  useEffect(() => {
    if (watchlist.length === 0) return;
    api.getNews(watchlist.map((r) => r.symbol)).then(setNews).catch(() => {});
  }, [watchlist]);

  const top5 = watchlist.slice(0, 5);

  const deployed = portfolio.reduce((s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1), 0);
  const openPnL  = portfolio.reduce((s, p) => s + p.pnlDollar, 0);
  const openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0;

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <div>
          <Title as="h1" size={24}>Dashboard</Title>
          <Text size={13} tone="secondary">{formatScanAt(scanAt)}</Text>
        </div>
        {context && (
          <div className={styles.contextPill}>
            <Text size={12} tone="secondary">{context.universe} · {context.direction} · {context.horizon}</Text>
          </div>
        )}
      </div>

      {offline && (
        <Text size={13} tone="dim">Backend not running — start start-backend.bat to load live data.</Text>
      )}

      {/* Regime banner */}
      <section className={`${styles.regime} ${styles[`regime_${regime?.overall ?? 'PENDING'}`]}`}>
        <div className={styles.regimeLeft}>
          <StatusBadge status={regime?.overall ?? 'PENDING'} label={`REGIME ${regime?.overall ?? '…'}`} />
          <Text size={13} weight={500}>{regime?.headline ?? ''}</Text>
        </div>
        <div className={styles.regimeMetrics}>
          {(regime?.metrics ?? []).map((m) => (
            <div key={m.label} className={styles.metric}>
              <Text size={11} tone="secondary">{m.label}</Text>
              <Data size={13} weight={500} tone={toneFor(m.status)}>{m.value}</Data>
            </div>
          ))}
        </div>
      </section>

      {/* Bento row: Watchlist preview | Portfolio | Alerts */}
      <div className={styles.bento}>
        <SectionCard
          title="Watchlist (Top 5)"
          count={watchlist.length}
          action={{ label: 'View all →', onClick: () => router.push('/watchlist') }}
        >
          <div className={styles.tableHeader} style={{ gridTemplateColumns: WL_COLUMNS }}>
            <Text size={11} tone="dim">SYM</Text>
            <Text size={11} tone="dim">NAME</Text>
            <Text size={11} tone="dim">SCORE</Text>
            <Text size={11} tone="dim">RANK Δ</Text>
            <Text size={11} tone="dim">NEXT</Text>
          </div>
          {top5.map((row) => (
            <TableRow
              key={row.symbol}
              status={row.status}
              columns={WL_COLUMNS}
              onClick={() => router.push(`/watchlist?symbol=${row.symbol}`)}
            >
              <Data size={12} weight={500}>{row.symbol}</Data>
              <Text size={12} tone="secondary">{row.company}</Text>
              <Data size={12} weight={500}>{row.score}</Data>
              <RankDelta value={row.rankDelta} />
              {row.nextEventDays !== undefined
                ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel} />
                : <Text size={11} tone="dim">—</Text>}
            </TableRow>
          ))}
        </SectionCard>

        <SectionCard
          title="Portfolio"
          count={portfolio.length}
          action={{ label: 'View all →', onClick: () => router.push('/portfolio') }}
        >
          <div className={styles.portfolioStats}>
            <Stat label="Deployed"   value={`$${Math.round(deployed).toLocaleString()}`} />
            <Stat
              label="Open P&L"
              value={`${openPnL > 0 ? '+' : ''}$${Math.round(openPnL).toLocaleString()}`}
              tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}
            />
            <Stat
              label="Return"
              value={`${openPnLPct > 0 ? '+' : ''}${openPnLPct.toFixed(2)}%`}
              tone={openPnLPct > 0 ? 'pass' : openPnLPct < 0 ? 'reject' : undefined}
            />
            <Stat label="Positions" value={`${portfolio.length}`} />
          </div>
          <div className={styles.divider} />
          <div className={styles.positions}>
            {portfolio.slice(0, 3).map((p) => (
              <div key={p.contract} className={styles.posRow}>
                <Data size={12} weight={500}>{p.symbol}</Data>
                <Text size={11} tone="secondary">{p.contract}</Text>
                <Data size={12} weight={500} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                  {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                </Data>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Alerts" count={alerts.length}>
          <div className={styles.alertList}>
            {alerts.slice(0, 5).map((a) => (
              <AlertRow
                key={a.id}
                kind={a.kind}
                symbol={a.symbol}
                reason={a.reason}
                timestamp={a.timestamp}
              />
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Risk">
          <RiskPanel />
        </SectionCard>
      </div>

      {/* Second bento row — news + open contracts overview */}
      <div className={styles.bento2}>
        <SectionCard title="News — watchlist" count={news.length}>
          <div className={styles.newsList}>
            {offline ? (
              <Text size={12} tone="dim">Backend not running — start start-backend.bat to load live data.</Text>
            ) : news.length === 0 ? (
              <Text size={12} tone="dim">No news for your watchlist right now.</Text>
            ) : news.slice(0, 6).map((n) => (
              <article key={n.id} className={styles.newsItem}>
                <span className={`${styles.newsDot} ${styles[`newsDot_${n.sentiment}`]}`} aria-hidden />
                <Data size={12} weight={500}>{n.symbol}</Data>
                <Text size={12}>{n.headline}</Text>
                <div className={styles.newsMeta}>
                  <Text size={11} tone="dim">{n.source}</Text>
                  <Text size={11} tone="dim">{n.timestamp}</Text>
                </div>
              </article>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          title="Contracts"
          count={portfolio.length}
          action={{ label: 'View all →', onClick: () => router.push('/portfolio') }}
        >
          <div className={styles.contractsList}>
            {portfolio.map((p) => (
              <div key={p.contract} className={styles.contractRow}>
                <div className={styles.contractCell}>
                  <Data size={12} weight={500}>{p.symbol}</Data>
                  <Text size={10} tone="dim">{p.dteRemaining}d · Δ{p.delta?.toFixed(2) ?? '—'}</Text>
                </div>
                <div className={styles.contractCell}>
                  <Text size={11} tone="secondary">{p.contract}</Text>
                  <Text size={10} tone="dim">IV {p.ivRank ?? '—'} · Θ {p.theta?.toFixed(2) ?? '—'}</Text>
                </div>
                <Data size={12} className={styles.contractRight}>${p.currentPrice.toFixed(2)}</Data>
                <Data size={12} weight={500} className={styles.contractRight} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                  {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                </Data>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      <RunScanButton />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'pass' | 'caution' | 'reject';
}) {
  return (
    <div className={styles.stat}>
      <Text size={11} tone="secondary">{label}</Text>
      <Data size={18} weight={500} tone={tone}>{value}</Data>
    </div>
  );
}

function toneFor(status: string): 'pass' | 'caution' | 'reject' | undefined {
  if (status === 'PASS')    return 'pass';
  if (status === 'CAUTION') return 'caution';
  if (status === 'REJECT')  return 'reject';
  return undefined;
}
