'use client';

/*
 * Screener Step 1 — Market Regime.
 * Macro snapshot — advisory for the user's trade. REJECT prompts confirmation
 * before proceeding to Step 4.
 *
 * Layout:
 *   1. Overall banner (PASS / CAUTION / REJECT + headline)
 *   2. Explainer
 *   3. Mini SPX + NDX candlestick charts
 *   4. EMA / VIX metric grid
 *   5. Horizon regime card (Intraday | Swing | Position) — replaces old sections 5/6
 *   6. Sector heatmap
 *   7. Market news
 */

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { NewsCard } from '@/components/molecules/NewsCard';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { api } from '@/lib/api';
import type { MarketRegime, SectorTile, NewsItem } from '@/types/domain';
import type { Candle } from '@/types/chart';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

function toneFor(status: string): 'pass' | 'caution' | 'reject' | undefined {
  if (status === 'PASS')    return 'pass';
  if (status === 'CAUTION') return 'caution';
  if (status === 'REJECT')  return 'reject';
  return undefined;
}

function lastClose(candles: Candle[]): { close: number; changePct: number } {
  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  if (!last || !prev) return { close: 0, changePct: 0 };
  return { close: last.close, changePct: ((last.close - prev.close) / prev.close) * 100 };
}

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
  if (state === 'Trending')       return '▲';
  if (state === 'Mean-reverting') return '↕';
  return '≈';
}

function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

export default function Step1RegimePage() {
  const setRegime = useScanStore((s) => s.setRegime);
  const setCombinedRegime = useScanStore((s) => s.setCombinedRegime);
  const context = useScanStore((s) => s.context);
  const markov = useSettingsStore((s) => s.markov);

  const [regime, setRegimeData]     = useState<MarketRegime | null>(null);
  const [sectors, setSectors]       = useState<SectorTile[]>([]);
  const [spxCandles, setSpxCandles] = useState<Candle[]>([]);
  const [ndxCandles, setNdxCandles] = useState<Candle[]>([]);
  const [offline, setOffline]       = useState(false);
  const [news, setNews]             = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError]   = useState(false);

  useEffect(() => {
    // Always fetch with 'intraday' so the HMM is always computed —
    // the regime step is visited before horizon selection (step 3).
    api.getRegime('intraday', { lookback: markov.lookback, threshold: markov.threshold, smoothing: markov.smoothing }).then((r) => {
      setRegimeData(r);
      setRegime(r.overall);
      setCombinedRegime(r.overall);
    }).catch(() => setOffline(true));

    api.getSectors().then(setSectors).catch(() => setOffline(true));
    api.getCandles('SPY').then(setSpxCandles).catch(() => setOffline(true));
    api.getCandles('QQQ').then(setNdxCandles).catch(() => setOffline(true));

    const candidates = useScanStore.getState().scanResult?.candidates.map((c) => c.symbol) ?? [];
    const symbols = candidates.length > 0 ? candidates : ['SPY', 'QQQ', 'VIX', 'DIA'];
    setNewsLoading(true);
    api.getNews(symbols).then(setNews).catch(() => setNewsError(true)).finally(() => setNewsLoading(false));
  }, [setRegime, setCombinedRegime, markov]);

  const spx = lastClose(spxCandles);
  const ndx = lastClose(ndxCandles);
  const combinedStatus = regime?.overall ?? 'PENDING';

  const sectorsUp   = sectors.filter((s) => s.changePct >  0.05).length;
  const sectorsDown = sectors.filter((s) => s.changePct < -0.05).length;

  const omm       = regime?.omm           ?? null;
  const intraHmm  = regime?.intraday_hmm  ?? null;
  const intraOmm  = regime?.intraday_omm  ?? null;
  const vix30     = regime?.vix_pct_30d   ?? null;
  const vix252    = regime?.vix_pct_252d  ?? null;

  const pageSentiment = regime && regime.omm ? {
    horizon: context?.horizon ?? 'Swing',
    timeframe: 'daily',
    state: regime.omm.state,
    p_stay: regime.omm.p_stay,
    stability: regime.omm.stability,
    regime_age_days: regime.omm.regime_age_days,
    avg_regime_duration: regime.omm.avg_regime_duration,
    conviction_pct: regime.conviction_pct ?? 0,
    conviction_label: regime.conviction_label ?? 'Neutral',
    interpretation: `Market conviction: ${regime.conviction_label ?? 'Neutral'}`,
    hmm_state: regime.hmm_state ?? null,
    alignment: (regime.alignment ?? 'Unavailable') as 'Aligned' | 'Diverging' | 'Unavailable',
    insufficient_data: false,
  } : null;

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 1 OF 7</Text>
        <Title as="h1" size={24}>Market Regime</Title>
        <Text size={13} tone="secondary">
          Macro snapshot — advisory. REJECT prompts confirmation before proceeding.
        </Text>
      </div>

      {offline && (
        <Text size={13} tone="dim">Backend not running — start start-backend.bat to load live data.</Text>
      )}

      {/* 1. Overall banner */}
      <section className={`${pageStyles.banner} ${pageStyles[`banner_${combinedStatus}`]}`}>
        <div className={pageStyles.bannerLeft}>
          <StatusBadge status={combinedStatus} label={`REGIME ${combinedStatus}`} />
          <Text size={14} weight={500}>{regime?.headline ?? ''}</Text>
        </div>
      </section>

      {/* 2. Explainer */}
      <section className={pageStyles.explainer}>
        <div className={pageStyles.explainerBlock}>
          <Text size={12} weight={600}>What this measures</Text>
          <Text size={12} tone="secondary">
            Broad-market health of the US indices (SPX &amp; NDX) — <em>not</em> your watchlist.
            The regime answers: &ldquo;is the tide with or against a fresh directional trade?&rdquo;
          </Text>
        </div>
        <div className={pageStyles.explainerBlock}>
          <Text size={12} weight={600}>How it affects this scan</Text>
          <Text size={12} tone="secondary">
            <strong>PASS</strong> — proceed as scanned.{' '}
            <strong>CAUTION</strong> — position-size smaller, tighten stops.{' '}
            <strong>REJECT</strong> — wait or fade: a confirmation dialog will block Step&nbsp;4.
          </Text>
        </div>
      </section>

      {/* 3. Mini index charts */}
      <div className={pageStyles.indices}>
        <div className={pageStyles.indexCard}>
          <header className={pageStyles.indexHeader}>
            <Text size={13} weight={600}>S&amp;P 500 (SPY)</Text>
            <div className={pageStyles.indexPriceGroup}>
              <Data size={14} weight={500}>{spx.close.toFixed(2)}</Data>
              <Data size={11} tone={spx.changePct > 0 ? 'pass' : spx.changePct < 0 ? 'reject' : undefined}>
                {spx.changePct > 0 ? '+' : ''}{spx.changePct.toFixed(2)}%
              </Data>
            </div>
          </header>
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={spxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
        </div>
        <div className={pageStyles.indexCard}>
          <header className={pageStyles.indexHeader}>
            <Text size={13} weight={600}>Nasdaq 100 (QQQ)</Text>
            <div className={pageStyles.indexPriceGroup}>
              <Data size={14} weight={500}>{ndx.close.toFixed(2)}</Data>
              <Data size={11} tone={ndx.changePct > 0 ? 'pass' : ndx.changePct < 0 ? 'reject' : undefined}>
                {ndx.changePct > 0 ? '+' : ''}{ndx.changePct.toFixed(2)}%
              </Data>
            </div>
          </header>
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={ndxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
        </div>
      </div>

      {/* 4. EMA / VIX metric grid */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>EMA / VIX</Text>
        <Text size={12} tone="secondary">SPX &amp; NDX vs 200-day EMA, plus VIX level</Text>
      </div>
      <div className={pageStyles.grid}>
        {(regime?.metrics ?? []).map((m) => (
          <div key={m.label} className={pageStyles.metricCard}>
            <Text size={12} tone="secondary">{m.label}</Text>
            <div className={pageStyles.metricValueRow}>
              <Data size={18} weight={500} tone={toneFor(m.status)}>{m.value}</Data>
              {m.trend === 'up'   && <span className={pageStyles.trendUp}>↑</span>}
              {m.trend === 'down' && <span className={pageStyles.trendDown}>↓</span>}
            </div>
            <StatusBadge status={m.status} />
          </div>
        ))}
      </div>

      {/* 5. Horizon regime card (Intraday | Swing | Position) */}
      {(omm || intraHmm || intraOmm) && (
        <>
          <div className={pageStyles.sectionHeader}>
            <Text size={13} weight={600}>Regime by Horizon</Text>
            <Text size={12} tone="secondary">Same macro signal — emphasis varies by timeframe</Text>
          </div>
          <div className={pageStyles.horizonCard}>

            {/* Intraday column — HMM session state, OMM fallback when hmmlearn unavailable */}
            <div className={pageStyles.horizonCol}>
              <Text size={11} tone="dim" weight={500}>INTRADAY</Text>
              {intraHmm ? (
                <>
                  <Data size={14} weight={500}>
                    {hmmStateIcon(intraHmm.state)} {intraHmm.state}
                  </Data>
                  <Text size={12} tone="secondary">{pct(intraHmm.p_stay)} chance of staying in this regime</Text>
                  {intraHmm.p_transition
                    .filter((t) => t.prob > 0.08)
                    .map((t) => (
                      <Text key={t.to} size={11} tone={t.prob > 0.2 ? 'caution' : 'dim'}>
                        {pct(t.prob)} chance of switching to {t.to}
                      </Text>
                    ))}
                  {vix30 != null && (
                    <Text size={11} tone="dim">VIX at {Math.round(vix30)}th percentile (30-day window)</Text>
                  )}
                </>
              ) : intraOmm ? (
                <>
                  <Data size={14} weight={500} tone={toneForOmmState(intraOmm.state)}>
                    {ommStateIcon(intraOmm.state)} {intraOmm.state}
                  </Data>
                  <Text size={12} tone="secondary">
                    Day {intraOmm.regime_age_days} · avg ~{Math.round(intraOmm.avg_regime_duration)} days · {intraOmm.stability}
                  </Text>
                  <Text size={12} tone="secondary">{pct(intraOmm.p_stay)} chance of staying in this regime</Text>
                  {intraOmm.state_order.map((s, i) => {
                    const prob = intraOmm.transition_row[i] ?? 0;
                    if (s === intraOmm.state || prob < 0.08) return null;
                    return (
                      <Text key={s} size={11} tone={toneForOmmState(s)}>
                        {pct(prob)} chance of switching to {s}
                      </Text>
                    );
                  })}
                  {vix30 != null && (
                    <Text size={11} tone="dim">VIX at {Math.round(vix30)}th percentile (30-day window)</Text>
                  )}
                </>
              ) : regime?.intraday_hmm_status === 'insufficient_data' ? (
                <StatusBadge status="NO_DATA" label="Insufficient data" />
              ) : regime?.intraday_hmm_status === 'unavailable' ? (
                <StatusBadge status="NO_DATA" label="Data unavailable" />
              ) : (
                <Text size={11} tone="dim">Calculating…</Text>
              )}
            </div>

            {/* Swing column */}
            <div className={pageStyles.horizonCol}>
              <Text size={11} tone="dim" weight={500}>SWING</Text>
              {omm ? (
                <>
                  <Data size={14} weight={500} tone={toneForOmmState(omm.state)}>
                    {ommStateIcon(omm.state)} {omm.state}
                  </Data>
                  <Text size={12} tone="secondary">
                    Day {omm.regime_age_days} · avg ~{Math.round(omm.avg_regime_duration)} days · {omm.stability}
                  </Text>
                  <Text size={12} tone="secondary">{pct(omm.p_stay)} chance of staying in this regime</Text>
                  {omm.state_order.map((s, i) => {
                    const prob = omm.transition_row[i] ?? 0;
                    if (s === omm.state || prob < 0.08) return null;
                    return (
                      <Text key={s} size={11} tone={toneForOmmState(s)}>
                        {pct(prob)} chance of switching to {s}
                      </Text>
                    );
                  })}
                  {vix252 != null && (
                    <Text size={11} tone="dim">VIX at {Math.round(vix252)}th percentile (252-day window)</Text>
                  )}
                </>
              ) : null}
            </div>

            {/* Position column */}
            <div className={pageStyles.horizonCol}>
              <Text size={11} tone="dim" weight={500}>POSITION</Text>
              {omm ? (
                <>
                  <Data size={14} weight={500} tone={toneForOmmState(omm.state)}>
                    {ommStateIcon(omm.state)} {omm.state}
                  </Data>
                  <Text size={12} tone="secondary">
                    Day {omm.regime_age_days} · avg ~{Math.round(omm.avg_regime_duration)} days · {omm.stability}
                  </Text>
                  <Text size={12} tone="secondary">{pct(omm.p_stay)} chance of staying in this regime</Text>
                  {omm.state_order.map((s, i) => {
                    const prob = omm.transition_row[i] ?? 0;
                    if (s === omm.state || prob < 0.08) return null;
                    return (
                      <Text key={s} size={11} tone={toneForOmmState(s)}>
                        {pct(prob)} chance of switching to {s}
                      </Text>
                    );
                  })}
                  {vix252 != null && (
                    <Text size={11} tone="dim">VIX at {Math.round(vix252)}th percentile (252-day window)</Text>
                  )}
                </>
              ) : null}
            </div>

          </div>
        </>
      )}

      <MarketSentiment s={pageSentiment} />

      {/* 6. Sector heatmap */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>Sector heatmap</Text>
        <Text size={12} tone="secondary">
          {sectorsUp} up · {sectorsDown} down · today
        </Text>
      </div>
      <div className={pageStyles.sectors}>
        {sectors.map((s) => (
          <div
            key={s.key}
            className={`${pageStyles.sectorTile} ${pageStyles[`sectorTile_${s.status}`]}`}
            title={`${s.name} (${s.key})`}
          >
            <div className={pageStyles.sectorRow}>
              <Data size={12} weight={500}>{s.key}</Data>
              <Data size={12} weight={500} tone={toneFor(s.status)}>
                {s.changePct > 0 ? '+' : ''}{s.changePct.toFixed(2)}%
              </Data>
            </div>
            <Text size={11} tone="secondary">{s.name}</Text>
          </div>
        ))}
      </div>

      {/* 7. Market news */}
      <section className={pageStyles.newsSection}>
        <Text size={11} tone="dim" weight={500}>MARKET NEWS</Text>
        {newsError && !newsLoading
          ? <Text size={12} tone="reject">News unavailable — backend offline?</Text>
          : <NewsCard items={news} loading={newsLoading} />}
      </section>

      <RunScanButton />
    </div>
  );
}
