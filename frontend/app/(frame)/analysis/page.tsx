'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { useAnalysisStore } from '@/lib/analysisStore';
import { api } from '@/lib/api';
import type { Candle } from '@/types/chart';
import type { NewsItem } from '@/types/domain';
import styles from './page.module.css';

export default function AnalysisPage() {
  const { result, loading, error, analyze } = useAnalysisStore();
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

      {result && (
        <>
          <div className={styles.headerStrip}>
            <Data size={18} weight={500}>{result.symbol}</Data>
            <Text size={13} tone="secondary">{result.company}</Text>
            <Data size={14}>${result.price.toFixed(2)}</Data>
            <StatusBadge status={result.stock_status} />
            <span className={styles.dirPill}>{result.direction}</span>
            {result.market_backdrop && (
              <span className={styles.backdropChip}>Market: {result.market_backdrop.overall}</span>
            )}
          </div>

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
              <Text size={11} tone="dim">Market sentiment</Text>
              {result.sentiment ? (
                <Data size={14} tone={result.sentiment.conviction_pct >= 0 ? 'pass' : 'reject'}>
                  {result.sentiment.conviction_label} ({result.sentiment.conviction_pct > 0 ? '+' : ''}{result.sentiment.conviction_pct}%)
                </Data>
              ) : <Text size={12} tone="dim">—</Text>}
            </article>

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Fundamental Health</Text>
              {result.fundamentals ? (
                <>
                  <Data size={14} tone={result.fundamentals.score >= 65 ? 'pass' : result.fundamentals.score >= 40 ? 'caution' : 'reject'}>
                    {result.fundamentals.score}
                  </Data>
                  <Text size={11} tone="secondary">
                    G {result.fundamentals.growth_score} · Q {result.fundamentals.quality_score} · R {result.fundamentals.risk_score}
                  </Text>
                </>
              ) : <Text size={12} tone="dim">{result.is_index ? 'N/A (index)' : '—'}</Text>}
            </article>

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Sector</Text>
              <Data size={13}>{result.sector?.name ?? 'Unknown'}</Data>
              {result.sector_rs && (
                <div className={styles.rsStrip}>
                  {(['d1', 'w1', 'm1'] as const).map((k) => {
                    const v = result.sector_rs![k];
                    const lbl = k === 'd1' ? '1D' : k === 'w1' ? '1W' : '1M';
                    return (
                      <span key={k} className={styles.rsCell}>
                        <Text size={10} tone="dim">{lbl}</Text>
                        <Data size={12} tone={v == null ? 'dim' : v >= 0 ? 'pass' : 'reject'}>
                          {v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`}
                        </Data>
                      </span>
                    );
                  })}
                </div>
              )}
              {result.sector_rs && (
                <Text size={10} tone="dim">vs {result.sector_rs.benchmark}</Text>
              )}
            </article>
          </div>

          <div className={styles.regimeRow}>
            {(['Intraday', 'Swing', 'Position'] as const).map((h) => {
              const blk = result.regime_by_horizon[h];
              return (
                <article key={h} className={styles.regimeCard}>
                  <Text size={11} tone="dim">{h.toUpperCase()}</Text>
                  {blk && !blk.insufficient_data ? (
                    <>
                      <Data size={14}>{blk.state}</Data>
                      <Text size={11} tone="secondary">stay {(blk.p_stay * 100).toFixed(0)}% · {blk.stability}</Text>
                      {blk.hmm_state && <Text size={11} tone="dim">HMM {blk.hmm_state} · {blk.alignment}</Text>}
                    </>
                  ) : <Text size={12} tone="dim">insufficient data</Text>}
                </article>
              );
            })}
          </div>

          {/* Chart + single-symbol table */}
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
                      <StatusBadge status={g.status} />
                      <Text size={11} tone="secondary">{g.gate}: {g.detail}</Text>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.chartCol}>
              <CandlestickChart data={candles} height="auto" defaultIndicators={['volume', 'macd']} />
            </div>
          </div>

          {/* Per-component score breakdown */}
          {result.rules.length > 0 && (
            <div className={styles.scoreCards}>
              {result.rules.map((r) => {
                const tone = r.status === 'PASS' ? 'pass' : r.status === 'CAUTION' ? 'caution' : 'reject';
                return (
                  <article key={r.name} className={styles.scoreCard}>
                    <Text size={12} weight={500}>{r.name}</Text>
                    <Data size={14} tone={tone}>{r.score}/100</Data>
                    <StatusBadge status={r.status} />
                  </article>
                );
              })}
            </div>
          )}

          {/* News */}
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
