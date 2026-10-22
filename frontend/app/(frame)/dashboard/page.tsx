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
import { toneForStatus } from '@/lib/status';
import { resolveIv, formatIv } from '@/lib/ivBasis';
import { SectionCard } from '@/components/molecules/SectionCard';
import { TableRow } from '@/components/molecules/TableRow';
import { AlertRow } from '@/components/molecules/AlertRow';
import { NewsCard } from '@/components/molecules/NewsCard';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { useScanStore } from '@/lib/scanStore';
import { useAlertStore } from '@/lib/alertStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { EarningsChart } from '@/components/organisms/EarningsChart';
import { scanPortfolio } from '@/lib/alertEngine';
import { openTotals, unquotedNote } from '@/lib/portfolioTotals';
import { api } from '@/lib/api';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { ToastContainer } from '@/components/organisms/ToastContainer';
import { Tooltip } from '@/components/atoms/Tooltip';
import { regimeStatusTooltip, regimeMetricTooltip } from '@/lib/statusTooltips';
import { RiskPanel } from '@/components/molecules/RiskPanel';
import type { WatchlistRow, MarketRegime, NewsItem } from '@/types/domain';
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
  const [regime, setRegime]       = useState<MarketRegime | null>(null);
  const [news, setNews]           = useState<NewsItem[]>([]);
  const [offline, setOffline]     = useState(false);

  const [marketNews, setMarketNews]           = useState<NewsItem[]>([]);
  const [marketNewsLoading, setMarketNewsLoading] = useState(true);
  const [marketNewsError, setMarketNewsError] = useState(false);

  const portfolio = usePortfolioStore((s) => s.positions);
  const premiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  const enabledTypes = useAlertStore((s) => s.config.enabledTypes);

  const performance = usePerformanceStore((s) => s.performance);
  const fetchPerformance = usePerformanceStore((s) => s.fetchPerformance);
  const [showEarnings, setShowEarnings] = useState<boolean>(false);

  const toasts = useAlertStore((s) => s.toasts);
  const top5Alerts = [...toasts]
    .sort((a, b) => new Date(b.firedAt).getTime() - new Date(a.firedAt).getTime())
    .slice(0, 5);

  useEffect(() => {
    const store = usePortfolioStore.getState();
    // Pull from backend first; only push local state if the backend has no positions.
    // This prevents a stale localStorage snapshot from overwriting a newer backend state.
    store.syncFromBackend?.()
      .then(() => {
        if (usePortfolioStore.getState().positions.length === 0) {
          return store.syncToBackend?.();
        }
      })
      .catch(() => {});

    // Every 30 s: refresh live quotes, then immediately scan alerts on the
    // fresh prices, then refresh the equity curve. Running them chained (not on
    // independent timers) guarantees the alert engine never sees stale prices.
    const runCycle = () => {
      usePortfolioStore.getState().syncFromBackend?.()
        .then(() => {
          const positions = usePortfolioStore.getState().positions;
          const pct = useSettingsStore.getState().premiumStopPct;
          const addToast = useAlertStore.getState().addToast;
          // enabledTypes is read here (not captured in the effect's closure) so
          // a Settings change takes effect on the very next 30s cycle without
          // this interval having to be torn down and re-created.
          const liveEnabledTypes = useAlertStore.getState().config.enabledTypes;
          for (const r of scanPortfolio(positions, { premiumStopPct: pct, enabledTypes: liveEnabledTypes })) addToast(r);
          usePerformanceStore.getState().fetchPerformance();
        })
        .catch(() => {});
    };
    const id = setInterval(runCycle, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    setShowEarnings(localStorage.getItem('bamendjou:showEarnings') === '1');
    fetchPerformance();
  }, [fetchPerformance]);

  const toggleEarnings = () => {
    setShowEarnings((v) => {
      const next = !v;
      localStorage.setItem('bamendjou:showEarnings', next ? '1' : '0');
      return next;
    });
  };

  useEffect(() => {
    api.getWatchlist().then(setWatchlist).catch(() => setOffline(true));
    api.getRegime().then(setRegime).catch(() => setOffline(true));

    // Expanded set disabled — 9 symbols × 1 HTTP call each adds 5-10s latency; re-enable when news endpoint is batched.
    // api.getNews(['SPY','QQQ','VIX','DIA','AAPL','MSFT','TSLA','AMZN','NVDA'])
    api.getNews(['SPY', 'QQQ', 'VIX', 'DIA'])
      .then(setMarketNews)
      .catch(() => setMarketNewsError(true))
      .finally(() => setMarketNewsLoading(false));
  }, []);

  useEffect(() => {
    if (watchlist.length === 0) return;
    api.getNews(watchlist.map((r) => r.symbol)).then(setNews).catch(() => {});
  }, [watchlist]);

  // Immediate scan when positions, stop-%, or the enabled alert types change
  // between refresh cycles.
  useEffect(() => {
    const addToast = useAlertStore.getState().addToast;
    for (const r of scanPortfolio(portfolio, { premiumStopPct, enabledTypes })) addToast(r);
  }, [portfolio, premiumStopPct, enabledTypes]);

  const top5 = watchlist.slice(0, 5);

  // Positions without a quote are left out of the totals and their rows show
  // "—" rather than a $0 that is not a price (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, openPnLPct, unquoted } = openTotals(portfolio);
  const portfolioNote = unquotedNote(unquoted);

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
        <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
      )}

      {/* Regime banner */}
      <section
        role="region"
        aria-label="Market regime"
        className={`${styles.regime} ${styles[`regime_${regime?.overall ?? 'PENDING'}`]}`}
      >
        <div className={styles.regimeLeft}>
          <StatusBadge
            status={regime?.overall ?? 'PENDING'}
            label={`REGIME ${regime?.overall ?? '…'}`}
            tooltip={regimeStatusTooltip(regime?.overall ?? 'PENDING')}
          />
          <Text size={13} weight={500}>{regime?.headline ?? ''}</Text>
        </div>
        <div className={styles.regimeMetrics}>
          {(regime?.metrics ?? []).map((m) => (
            <Tooltip key={m.label} text={regimeMetricTooltip(m.label, m.status)}>
              <div className={styles.metric}>
                <Text size={11} tone="secondary">{m.label}</Text>
                <Data size={13} weight={500} tone={toneForStatus(m.status)}>{m.value}</Data>
              </div>
            </Tooltip>
          ))}
        </div>
      </section>

      {/* Earnings graph — toggleable, persists to localStorage */}
      <div className={styles.earnings}>
        <SectionCard
          title="Earnings"
          action={{ label: showEarnings ? 'Hide graph' : 'Show graph', onClick: toggleEarnings }}
        >
          {showEarnings ? (
            performance.equityCurve.length === 0 && performance.realizedCurve.length === 0 ? (
              <Text size={12} tone="dim">No earnings data yet — close a trade to start the curve.</Text>
            ) : (
              <EarningsChart
                realizedCurve={performance.realizedCurve}
                equityCurve={performance.equityCurve}
              />
            )
          ) : (
            <Text size={12} tone="dim">Graph hidden. Use “Show graph” to display realized profit and account value over time.</Text>
          )}
        </SectionCard>
      </div>

      {/* Row 1: Watchlist + Portfolio */}
      <div className={styles.bentoTop}>
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
              <RankDelta value={row.rankDelta} context="rank" />
              {row.nextEventDays != null
                ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel ?? undefined} />
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
          {portfolioNote && <Text size={11} tone="caution">{portfolioNote}</Text>}
          <div className={styles.divider} />
          <div className={styles.positions}>
            {portfolio.slice(0, 3).map((p) => (
              <div key={p.recId} className={styles.posRow}>
                <Data size={12} weight={500}>{p.symbol}</Data>
                <Text size={11} tone="secondary">{p.contract}</Text>
                {p.quoteUnavailable ? (
                  <Data size={12} weight={500} title="Quote unavailable">—</Data>
                ) : (
                  <Data size={12} weight={500} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                    {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                  </Data>
                )}
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      {/* Row 2: Alerts + Risk */}
      <div className={styles.bentoMid}>
        <SectionCard
          title="Alerts"
          count={toasts.length}
          action={{ label: 'View all →', onClick: () => router.push('/alerts') }}
        >
          <div className={styles.alertList}>
            {top5Alerts.length === 0 ? (
              <Text size={12} tone="dim">No alerts yet.</Text>
            ) : top5Alerts.map((a) => (
              <AlertRow
                key={a.id}
                kind={a.kind}
                symbol={a.symbol}
                reason={a.reason}
                timestamp={timeAgo(a.firedAt)}
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
              <Text size={12} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
            ) : watchlist.length === 0 ? (
              <Text size={12} tone="dim">Add stocks to your watchlist to see news here.</Text>
            ) : news.length === 0 ? (
              <Text size={12} tone="dim">No recent news for your watchlist.</Text>
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
              <div key={p.recId} className={styles.contractRow}>
                <div className={styles.contractCell}>
                  <Data size={12} weight={500}>{p.symbol}</Data>
                  <Text size={10} tone="dim">{p.dteRemaining}d · Δ{p.delta?.toFixed(2) ?? '—'}</Text>
                </div>
                <div className={styles.contractCell}>
                  <Text size={11} tone="secondary">{p.contract}</Text>
                  {/* A percentile when a rank source answered, otherwise the absolute
                      implied volatility — formatIv marks which
                      (PHASE-A-NULL-IVRANK-2026-09-06). The `rank` SUFFIX has to be
                      rendered, not just the text: without it a percentile reads as
                      "IV 45" and is told apart from 45% absolute only by the absent
                      `%`, which is exactly the one-character distinction formatIv's
                      own docstring refuses to rest on. Every other converted site
                      either renders the suffix or switches its own noun. */}
                  {(() => {
                    const shownIv = formatIv(resolveIv(p), p.symbol);
                    return (
                      <span title={shownIv.title}>
                        <Text size={10} tone="dim">
                          IV {shownIv.text}{shownIv.suffix !== '' ? ` ${shownIv.suffix}` : ''} · Θ {p.theta?.toFixed(2) ?? '—'}
                        </Text>
                      </span>
                    );
                  })()}
                </div>
                {p.quoteUnavailable ? (
                  <>
                    <Data size={12} className={styles.contractRight} title="Quote unavailable">—</Data>
                    <Data size={12} weight={500} className={styles.contractRight} title="Quote unavailable">—</Data>
                  </>
                ) : (
                  <>
                    <Data size={12} className={styles.contractRight}>${p.currentPrice.toFixed(2)}</Data>
                    <Data size={12} weight={500} className={styles.contractRight} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                      {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                    </Data>
                  </>
                )}
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      <div className={styles.marketNews}>
        <SectionCard title="Market News" count={marketNews.length}>
          {marketNewsError && !marketNewsLoading
            ? <Text size={12} tone="reject">Market news unavailable — backend offline?</Text>
            : <NewsCard items={marketNews} loading={marketNewsLoading} limit={8} />}
        </SectionCard>
      </div>

      <RunScanButton />
      <ToastContainer />
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

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
