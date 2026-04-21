'use client';

/*
 * Dashboard — Phase 5.
 * Bento layout: regime banner across top, then 3-column row
 * (Watchlist preview | Portfolio summary | Alerts).
 * Upcoming events card spans across the bottom.
 * Right context rail (events + portfolio risk) comes from the parallel slot.
 */

import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { SectionCard } from '@/components/molecules/SectionCard';
import { TableRow } from '@/components/molecules/TableRow';
import { AlertRow } from '@/components/molecules/AlertRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import { MOCK_ALERTS } from '@/mocks/alerts';
import { MOCK_REGIME } from '@/mocks/regime';
import { MOCK_NEWS } from '@/mocks/news';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import styles from './page.module.css';

const WL_COLUMNS = '60px 1fr 60px 64px 64px';

export default function DashboardPage() {
  const router = useRouter();
  const top5 = MOCK_WATCHLIST.slice(0, 5);

  const deployed = MOCK_PORTFOLIO.reduce((s, p) => s + p.currentPrice * 100, 0);
  const openPnL  = MOCK_PORTFOLIO.reduce((s, p) => s + p.pnlDollar, 0);
  const openPnLPct = (openPnL / deployed) * 100;

  // News filtered down to what's relevant to the user's watchlist.
  const wlSet = new Set(MOCK_WATCHLIST.map((r) => r.symbol));
  const watchlistNews = MOCK_NEWS.filter((n) => wlSet.has(n.symbol));

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Dashboard</Title>
        <Text size={13} tone="secondary">Today, 18 Apr 2026 · Pre-market</Text>
      </div>

      {/* Regime banner */}
      <section className={`${styles.regime} ${styles[`regime_${MOCK_REGIME.overall}`]}`}>
        <div className={styles.regimeLeft}>
          <StatusBadge status={MOCK_REGIME.overall} label={`REGIME ${MOCK_REGIME.overall}`} />
          <Text size={13} weight={500}>{MOCK_REGIME.headline}</Text>
        </div>
        <div className={styles.regimeMetrics}>
          {MOCK_REGIME.metrics.map((m) => (
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
          count={MOCK_WATCHLIST.length}
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
          count={MOCK_PORTFOLIO.length}
          action={{ label: 'View all →', onClick: () => router.push('/portfolio') }}
        >
          <div className={styles.portfolioStats}>
            <Stat label="Deployed"   value={`$${Math.round(deployed).toLocaleString()}`} />
            <Stat
              label="Open P&L"
              value={`${openPnL >= 0 ? '+' : ''}$${Math.round(openPnL).toLocaleString()}`}
              tone={openPnL >= 0 ? 'pass' : 'reject'}
            />
            <Stat
              label="Return"
              value={`${openPnLPct >= 0 ? '+' : ''}${openPnLPct.toFixed(2)}%`}
              tone={openPnLPct >= 0 ? 'pass' : 'reject'}
            />
            <Stat label="Positions" value={`${MOCK_PORTFOLIO.length}`} />
          </div>
          <div className={styles.divider} />
          <div className={styles.positions}>
            {MOCK_PORTFOLIO.slice(0, 3).map((p) => (
              <div key={p.contract} className={styles.posRow}>
                <Data size={12} weight={500}>{p.symbol}</Data>
                <Text size={11} tone="secondary">{p.contract}</Text>
                <Data size={12} weight={500} tone={p.pnlDollar >= 0 ? 'pass' : 'reject'}>
                  {p.pnlDollar >= 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                </Data>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Alerts" count={MOCK_ALERTS.length}>
          <div className={styles.alertList}>
            {MOCK_ALERTS.slice(0, 5).map((a) => (
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
      </div>

      {/* Second bento row — news tied to watchlist + open contracts overview */}
      <div className={styles.bento2}>
        <SectionCard title="News — watchlist" count={watchlistNews.length}>
          <div className={styles.newsList}>
            {watchlistNews.slice(0, 6).map((n) => (
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
            {watchlistNews.length === 0 && (
              <Text size={12} tone="dim">No news for your watchlist right now.</Text>
            )}
          </div>
        </SectionCard>

        <SectionCard
          title="Contracts"
          count={MOCK_PORTFOLIO.length}
          action={{ label: 'View all →', onClick: () => router.push('/portfolio') }}
        >
          <div className={styles.contractsList}>
            {MOCK_PORTFOLIO.map((p) => (
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
                <Data size={12} weight={500} className={styles.contractRight} tone={p.pnlDollar >= 0 ? 'pass' : 'reject'}>
                  {p.pnlDollar >= 0 ? '+' : ''}${Math.round(p.pnlDollar)}
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
