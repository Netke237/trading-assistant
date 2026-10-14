'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { WatchStar } from '@/components/atoms/WatchStar';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { FundamentalHealthCard } from '@/components/molecules/FundamentalHealthCard';
import { useAnalysisStore } from '@/lib/analysisStore';
import { alignmentVerdict, descriptorFromState } from '@/lib/regimeAlignment';
import { formatRegimeAge, formatRegimeAverage } from '@/lib/regimeDuration';
import { GENERIC_STATUS_TOOLTIP, regimeStatusTooltip, regimeNoDataTooltip, ruleContributionTooltip } from '@/lib/statusTooltips';
import type { FundamentalsOut } from '@/types/domain';
import { api } from '@/lib/api';
import type { Candle } from '@/types/chart';
import type { NewsItem } from '@/types/domain';
import styles from './page.module.css';

/* ── Regime helpers (mirrors step-1-regime) ─────────────────────────── */
function ommStateIcon(state: string): string {
  if (state === 'Bull') return '↑';
  if (state === 'Bear') return '↓';
  return '≈';
}
function toneForOmmState(state: string): 'pass' | 'caution' | 'reject' {
  if (state === 'Bull') return 'pass';
  if (state === 'Bear') return 'reject';
  return 'caution';
}
function hmmStateIcon(state: string): string {
  if (state === 'Trending') return '▲';
  if (state === 'Mean-reverting') return '↕';
  return '≈';
}
function pct(p: number): string { return `${Math.round(p * 100)}%`; }

/* ── Score-card signal helper ────────────────────────────────────────── */
function signalFromStatus(status: string): 'pos' | 'neu' | 'neg' {
  if (status === 'PASS')    return 'pos';
  if (status === 'REJECT')  return 'neg';
  return 'neu';
}
function signalLabel(sig: 'pos' | 'neu' | 'neg'): string {
  if (sig === 'pos') return 'Positive';
  if (sig === 'neg') return 'Negative';
  return 'Neutral';
}

export default function AnalysisPage() {
  const router = useRouter();
  const { result, basis, loading, error, analyze } = useAnalysisStore();
  const [input, setInput] = useState('');
  const [candles, setCandles] = useState<Candle[]>([]);
  const [stockNews, setStockNews] = useState<NewsItem[]>([]);
  const [marketNews, setMarketNews] = useState<NewsItem[]>([]);

  useEffect(() => {
    if (!result?.symbol) return;
    let cancelled = false;
    (async () => {
      try {
        const [c, sn, mn] = await Promise.all([
          api.getCandles(result.symbol),
          api.getNews([result.symbol]),
          api.getNews(['SPY', 'QQQ']),
        ]);
        if (!cancelled) { setCandles(c); setStockNews(sn); setMarketNews(mn); }
      } catch { /* non-fatal */ }
    })();
    return () => { cancelled = true; };
  }, [result?.symbol]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    analyze(input);
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Title as="h1" size={24}>Analysis</Title>
        <Text size={13} tone="secondary">Analyse any stock or index on demand — regime, sentiment, fundamentals, and score.</Text>
        <form className={styles.searchRow} onSubmit={onSubmit}>
          <input
            className={styles.search}
            placeholder="Search ticker or index (e.g. AMD, SPY)…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Symbol search"
          />
          <button type="submit" className={styles.searchBtn} disabled={loading}>
            {loading ? 'Analysing…' : 'Analyse'}
          </button>
        </form>
      </div>

      {error && <Text size={12} tone="reject">{error}</Text>}

      {/* A5: which settings this analysis ran on — the last stock scan's own
          request, or (no request on record) the current settings, said aloud. */}
      {result && basis === 'last-scan' && (
        <Text size={11} tone="dim">Settings: the last stock scan&apos;s</Text>
      )}
      {result && basis === 'current-settings' && (
        <Text size={11} tone="caution">
          Settings: current Step-3 and saved settings — no stock scan request on record; re-run the scan to mirror it.
        </Text>
      )}

      {result && (
        <>
          {/* ── Header strip ─────────────────────────────────────────── */}
          <div className={styles.headerStrip}>
            <WatchStar symbol={result.symbol} />
            <div className={styles.symbolName}>
              <Data size={18} weight={500}>{result.symbol}</Data>
              <Text size={14} tone="secondary">{result.company}</Text>
            </div>
            <Data size={14}>${result.price.toFixed(2)}</Data>
            <StatusBadge status={result.stock_status} tooltip={GENERIC_STATUS_TOOLTIP[result.stock_status]} />
            <span className={styles.dirPill}>{result.direction}</span>
            {result.market_backdrop && (
              <span className={styles.backdropChip}>
                Market: <StatusBadge
                  status={result.market_backdrop.overall as 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'}
                  tooltip={regimeStatusTooltip(result.market_backdrop.overall as 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA')}
                />
              </span>
            )}
            <button
              className={styles.chartLinkBtn}
              title="Open in Chart"
              onClick={() => window.open(`/chart?symbol=${result.symbol}`, '_blank')}
            >
              Open in Chart ↗
            </button>
          </div>

          {/* ── Context row ──────────────────────────────────────────── */}
          <div className={styles.contextRow}>
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">EMA / IV</Text>
              {result.ema_trend ? (
                <Data size={14} tone={result.ema_trend.state === 'Above' ? 'pass' : 'caution'}>
                  {result.ema_trend.state} 200-EMA
                </Data>
              ) : <Text size={12} tone="dim">N/A</Text>}
              <Text size={11} tone="secondary">
                IV rank: {result.iv_rank != null ? result.iv_rank.toFixed(0) : (result.is_index ? 'N/A' : '—')}
              </Text>
            </article>

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Stock regime</Text>
              {result.sentiment ? (() => {
                const descriptor = descriptorFromState(result.sentiment.state);
                const verdict = alignmentVerdict(result.direction as 'Bullish' | 'Bearish', descriptor);
                const verdictLabel = verdict === 'PASS' ? 'Tailwind' : verdict === 'REJECT' ? 'Headwind' : 'Choppy';
                const verdictTone = verdict === 'PASS' ? 'pass' : verdict === 'REJECT' ? 'reject' : 'caution';
                return (
                  <>
                    <Data
                      size={14}
                      tone={verdictTone}
                      title={`Regime ${result.sentiment.state} vs. a ${result.direction} scan direction → ${verdictLabel}. Tailwind = regime supports the direction, Headwind = opposes it, Choppy = unclear.`}
                    >
                      {ommStateIcon(result.sentiment.state)} {result.sentiment.state} · {verdictLabel}
                    </Data>
                    <Text size={11} tone="secondary">
                      Conviction: {result.sentiment.conviction_pct > 0 ? '+' : ''}{result.sentiment.conviction_pct}% ({result.sentiment.conviction_label})
                    </Text>
                    <Text size={11} tone="dim">
                      {formatRegimeAge(result.sentiment.regime_age_days)} · {result.sentiment.stability}
                    </Text>
                  </>
                );
              })() : <Text size={12} tone="dim">—</Text>}
            </article>

            <FundamentalHealthCard f={result.is_index ? null : (result.fundamentals as FundamentalsOut | null)} />

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Sector vs stock</Text>
              <Data size={13}>{result.sector?.name ?? 'Unknown'}</Data>
              {result.sector_rs ? (
                <>
                  <Text size={11} tone="secondary">
                    Stock return minus {result.sector_rs.benchmark} ETF return:
                  </Text>
                  <div className={styles.rsStrip}>
                    {(['d1', 'w1', 'm1'] as const).map((k) => {
                      const v = result.sector_rs![k];
                      const lbl = k === 'd1' ? '1D' : k === 'w1' ? '1W' : '1M';
                      const verdict = v == null ? null : v > 0.5 ? 'outperforming' : v < -0.5 ? 'lagging' : 'in line';
                      return (
                        <span key={k} className={styles.rsCell}>
                          <Text size={10} tone="dim">{lbl}</Text>
                          <Data
                            size={12}
                            tone={v == null ? 'dim' : v > 0.5 ? 'pass' : v < -0.5 ? 'reject' : 'secondary'}
                            title={v == null ? undefined : `Stock ${lbl} return minus ${result.sector_rs!.benchmark} ETF return. >+0.5% outperforming, <-0.5% lagging, else in line.`}
                          >
                            {v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
                          </Data>
                          {verdict && (
                            <Text size={10} tone={v! > 0.5 ? 'pass' : v! < -0.5 ? 'reject' : 'dim'}>
                              {verdict}
                            </Text>
                          )}
                        </span>
                      );
                    })}
                  </div>
                </>
              ) : (
                <Text size={11} tone="dim">No sector data</Text>
              )}
            </article>
          </div>

          {/* ── Regime by horizon — same text / colour as Market Regime step ── */}
          <div className={styles.sectionHeader}>
            <Text size={13} weight={600}>Regime by Horizon</Text>
            <Text size={12} tone="secondary">Same macro signal — emphasis varies by timeframe</Text>
          </div>
          <div className={styles.horizonCard}>
            {(['Intraday', 'Swing', 'Position'] as const).map((h) => {
              const blk = result.regime_by_horizon[h];
              return (
                <div key={h} className={styles.horizonCol}>
                  <Text size={11} tone="dim" weight={500}>{h.toUpperCase()}</Text>
                  {blk && !blk.insufficient_data ? (
                    <>
                      <Data size={14} weight={500} tone={toneForOmmState(blk.state)}>
                        {ommStateIcon(blk.state)} {blk.state}
                      </Data>
                      <Text size={12} tone="secondary">
                        {formatRegimeAge(blk.regime_age_days)} · avg {formatRegimeAverage(blk.avg_regime_duration)} · {blk.stability}
                      </Text>
                      <Text size={12} tone="secondary">
                        {pct(blk.p_stay)} chance of staying in this regime
                      </Text>
                      {blk.state_order.map((s, i) => {
                        const prob = blk.transition_row[i] ?? 0;
                        if (s === blk.state || prob < 0.08) return null;
                        return (
                          <Text key={s} size={11} tone={toneForOmmState(s)}>
                            {pct(prob)} chance of switching to {s}
                          </Text>
                        );
                      })}
                      {blk.hmm_state && (
                        <Text size={11} tone="dim">
                          {hmmStateIcon(blk.hmm_state)} HMM {blk.hmm_state} · {blk.alignment}
                        </Text>
                      )}
                    </>
                  ) : (
                    <StatusBadge status="NO_DATA" label="Insufficient data" tooltip={regimeNoDataTooltip('insufficient_data')} />
                  )}
                </div>
              );
            })}
          </div>

          {/* ── Chart + single-symbol table ───────────────────────────── */}
          <div className={styles.chartRegion}>
            <div className={styles.tableCol}>
              <div className={styles.tableHeader}>
                <Text size={11} tone="dim">SYMBOL</Text>
                <Text size={11} tone="dim">SCORE</Text>
                <Text size={11} tone="dim">WIN %</Text>
                <Text size={11} tone="dim">TRADES</Text>
                <Text size={11} tone="dim">RETURN</Text>
                <Text size={11} tone="dim">MAX DD</Text>
                <Text size={11} tone="dim">HEALTH</Text>
              </div>
              <div className={styles.row}>
                <Data size={12} weight={500}>{result.symbol}</Data>
                <Data size={12}>{result.stock_score}</Data>
                <Data size={12}>{result.backtest ? `${(result.backtest.win_rate * 100).toFixed(0)}%` : 'N/A'}</Data>
                <Data size={12}>{result.backtest?.n_trades ?? 'N/A'}</Data>
                <Data size={12}>{result.backtest ? `${result.backtest.total_return_pct.toFixed(1)}%` : 'N/A'}</Data>
                <Data size={12}>{result.backtest ? `${Math.abs(result.backtest.max_drawdown_pct).toFixed(1)}%` : 'N/A'}</Data>
                <Data size={12}>{result.fundamentals?.score ?? (result.is_index ? 'N/A' : '—')}</Data>
              </div>

              {result.gate_flags.length > 0 && (
                <div className={styles.gateFlags}>
                  <Text size={11} tone="dim">Advisory — would not pass scanner:</Text>
                  {result.gate_flags.map((g, i) => (
                    <span key={i} className={styles.gateFlag}>
                      <StatusBadge status={g.status} tooltip={g.detail} />
                      <Text size={11} tone="secondary">{g.gate}: {g.detail}</Text>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.chartCol}>
              <SymbolHeader
                ticker={result.symbol}
                company={result.company}
                price={result.price}
                direction={result.direction as 'Bullish' | 'Bearish'}
                status={result.stock_status}
                size={14}
              />
              <div className={styles.chartBox}>
                <CandlestickChart data={candles} height="auto" defaultIndicators={['volume', 'rsi']} />
              </div>
            </div>
          </div>

          {/* ── Score breakdown — same card style as Stock Ranking page ── */}
          {result.rules.length > 0 && (
            <>
              <div className={styles.detailsHeader}>
                <Text size={13} weight={600}>{result.symbol} · Score details</Text>
                <Text size={12} tone="secondary">
                  Points = raw score per component
                </Text>
              </div>
              <div className={styles.components}>
                {result.rules.map((r) => {
                  const sig = signalFromStatus(r.status);
                  return (
                    <article key={r.name} className={`${styles.compCard} ${styles[`compCard_${sig}`]}`}>
                      <header className={styles.compHeader}>
                        <Text size={13} weight={600}>{r.name}</Text>
                        <Text size={11} weight={500} tone={sig === 'pos' ? 'pass' : sig === 'neg' ? 'reject' : 'caution'}>
                          {signalLabel(sig)}
                        </Text>
                      </header>
                      <div className={styles.meter} aria-hidden>
                        <div
                          className={`${styles.meterFill} ${styles[`meterFill_${sig}`]}`}
                          style={{ width: `${r.score}%` }}
                        />
                      </div>
                      <div className={styles.compMeta}>
                        <div className={styles.compMetaCell}>
                          <Text size={10} tone="dim">RAW</Text>
                          <Data size={13} weight={500}>{r.score}/100</Data>
                        </div>
                        <div className={styles.compMetaCell}>
                          <Text size={10} tone="dim">STATUS</Text>
                          <StatusBadge status={r.status} tooltip={ruleContributionTooltip(r.name, r.status, r.detail)} />
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          )}

          {/* ── News ─────────────────────────────────────────────────── */}
          <div className={styles.newsRegion}>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>{result.symbol} news</Text>
              {stockNews.length === 0 && <Text size={11} tone="dim">No headlines.</Text>}
              {stockNews.map((n) => (
                <Text key={n.id} size={12} tone="secondary">{n.headline}</Text>
              ))}
            </div>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>Market news</Text>
              {marketNews.length === 0 && <Text size={11} tone="dim">No headlines.</Text>}
              {marketNews.map((n) => (
                <Text key={n.id} size={12} tone="secondary">{n.headline}</Text>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
