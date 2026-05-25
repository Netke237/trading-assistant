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
 *   5. OMM regime quality strip (transition persistence, age, VIX percentile)
 *   6. Intraday HMM session panel (Trending / Choppy / Mean-reverting)
 *   7. Sector heatmap
 *   8. Market news
 */

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { NewsCard } from '@/components/molecules/NewsCard';
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

function pctLabel(val: number | null | undefined): string {
  if (val == null) return '—';
  return `${Math.round(val)}th pct`;
}

function ommStateIcon(state: string): string {
  if (state === 'Bull') return '↑';
  if (state === 'Bear') return '↓';
  return '≈';
}

function hmmStateIcon(state: string): string {
  if (state === 'Trending')       return '▲';
  if (state === 'Mean-reverting') return '↕';
  return '≈';
}

function toApiHorizon(h: string | null | undefined): string {
  const s = (h ?? '').toLowerCase();
  if (s.startsWith('intraday')) return 'intraday';
  if (s.startsWith('position')) return 'position';
  return 'swing';
}

export default function Step1RegimePage() {
  const setRegime = useScanStore((s) => s.setRegime);
  const setCombinedRegime = useScanStore((s) => s.setCombinedRegime);
  const contextHorizon = useScanStore((s) => s.context?.horizon ?? null);
  const apiHorizon = toApiHorizon(contextHorizon);

  const [regime, setRegimeData]   = useState<MarketRegime | null>(null);
  const [sectors, setSectors]     = useState<SectorTile[]>([]);
  const [spxCandles, setSpxCandles] = useState<Candle[]>([]);
  const [ndxCandles, setNdxCandles] = useState<Candle[]>([]);
  const [offline, setOffline]     = useState(false);
  const [news, setNews]           = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState(false);

  useEffect(() => {
    api.getRegime(apiHorizon).then((r) => {
      setRegimeData(r);
      setRegime(r.overall);
      setCombinedRegime(r.overall);
    }).catch(() => setOffline(true));

    api.getSectors().then(setSectors).catch(() => setOffline(true));
    api.getCandles('SPY').then(setSpxCandles).catch(() => setOffline(true));
    api.getCandles('QQQ').then(setNdxCandles).catch(() => setOffline(true));

    const symbols = useScanStore.getState().scanResult?.candidates.map((c) => c.symbol) ?? [];
    if (symbols.length > 0) {
      setNewsLoading(true);
      api.getNews(symbols).then(setNews).catch(() => setNewsError(true)).finally(() => setNewsLoading(false));
    }
  }, [setRegime, setCombinedRegime, apiHorizon]);

  const spx = lastClose(spxCandles);
  const ndx = lastClose(ndxCandles);
  const combinedStatus = regime?.overall ?? 'PENDING';

  const sectorsUp   = sectors.filter((s) => s.changePct >   0.05).length;
  const sectorsDown = sectors.filter((s) => s.changePct <  -0.05).length;

  const omm = regime?.omm ?? null;
  const intraHmm = regime?.intraday_hmm ?? null;
  const vix30  = regime?.vix_pct_30d  ?? null;
  const vix252 = regime?.vix_pct_252d ?? null;

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

      {/* 5. OMM regime quality strip */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>Regime Persistence (OMM)</Text>
        <Text size={12} tone="secondary">Rolling 500-day transition matrix — how durable is the current state?</Text>
      </div>
      {omm ? (
        <div className={pageStyles.qualityStrip}>
          {/* State */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">State</Text>
            <Data size={14} weight={500} tone={toneFor(omm.state === 'Bull' ? 'PASS' : omm.state === 'Bear' ? 'REJECT' : 'CAUTION')}>
              {ommStateIcon(omm.state)} {omm.state}
            </Data>
          </div>

          <div className={pageStyles.qualityDivider} />

          {/* Stability */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">Stability</Text>
            <StatusBadge
              status={omm.stability === 'Stable' ? 'PASS' : 'CAUTION'}
              label={omm.stability}
            />
          </div>

          <div className={pageStyles.qualityDivider} />

          {/* Age */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">Age</Text>
            <Text size={13} weight={500}>
              Day {omm.regime_age_days} of ~{Math.round(omm.avg_regime_duration)} avg
            </Text>
          </div>

          <div className={pageStyles.qualityDivider} />

          {/* P(stay) */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">Continue</Text>
            <Data size={13} weight={500} tone={omm.p_stay >= 0.75 ? 'pass' : omm.p_stay >= 0.5 ? 'caution' : 'reject'}>
              {Math.round(omm.p_stay * 100)}%
            </Data>
          </div>

          <div className={pageStyles.qualityDivider} />

          {/* Transition risk — show states with risk > 8% */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">Transition risk</Text>
            <div className={pageStyles.transitionRow}>
              {omm.state_order.map((s, i) => {
                const prob = omm.transition_row[i] ?? 0;
                if (s === omm.state || prob < 0.08) return null;
                return (
                  <Text key={s} size={12} tone={s === 'Bear' ? 'reject' : 'caution'}>
                    →{s} {Math.round(prob * 100)}%
                  </Text>
                );
              })}
            </div>
          </div>

          <div className={pageStyles.qualityDivider} />

          {/* VIX percentile */}
          <div className={pageStyles.qualityItem}>
            <Text size={11} tone="dim">VIX context</Text>
            <Text size={12} weight={500}>
              {pctLabel(vix30)} (30d) · {pctLabel(vix252)} (252d)
            </Text>
          </div>
        </div>
      ) : (
        <div className={pageStyles.qualityStrip}>
          <Text size={12} tone="dim" className={pageStyles.noData}>
            Insufficient data for OMM — need 600+ daily bars from Tradier.
          </Text>
        </div>
      )}

      {/* 6. Intraday HMM session panel */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>Intraday Session Character (HMM)</Text>
        <Text size={12} tone="secondary">Gaussian HMM on 15-min SPY bars — session state detection</Text>
      </div>
      {intraHmm ? (
        <div className={pageStyles.hmmPanel}>
          <div className={pageStyles.hmmPanelRow}>
            {/* Session state */}
            <div className={pageStyles.hmmStateLabel}>
              <Data size={18} weight={500}>
                {hmmStateIcon(intraHmm.state)} {intraHmm.state}
              </Data>
            </div>

            {/* P(stay) progress bar */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 140 }}>
              <Text size={11} tone="dim">P(stay in {intraHmm.state}): {Math.round(intraHmm.p_stay * 100)}%</Text>
              <div className={pageStyles.progressBarWrap}>
                <div
                  className={`${pageStyles.progressBarFill}${intraHmm.p_stay < 0.6 ? ` ${pageStyles.progressBarFill_fragile}` : ''}`}
                  style={{ width: `${Math.round(intraHmm.p_stay * 100)}%` }}
                />
              </div>
            </div>

            {/* Transition warnings */}
            {intraHmm.p_transition.length > 0 && (
              <div className={pageStyles.hmmTransitions}>
                {intraHmm.p_transition.map((t) => (
                  <Text key={t.to} size={12} tone={t.prob > 0.2 ? 'caution' : 'secondary'}>
                    →{t.to} {Math.round(t.prob * 100)}%
                  </Text>
                ))}
              </div>
            )}

            {/* VIX intraday context */}
            {vix30 != null && (
              <div className={pageStyles.qualityItem}>
                <Text size={11} tone="dim">VIX today</Text>
                <Text size={12} weight={500}>{pctLabel(vix30)} vs last 30 sessions</Text>
              </div>
            )}
          </div>

          <Text size={11} tone="secondary">
            {intraHmm.state === 'Trending'       && 'Directional momentum detected — price making consistent progress.'}
            {intraHmm.state === 'Choppy'         && 'Low-variance, directionless session — range-bound, ideal for premium selling.'}
            {intraHmm.state === 'Mean-reverting' && 'High-variance whipsaw session — large moves that reverse; avoid breakout plays.'}
          </Text>
        </div>
      ) : (
        <div className={pageStyles.hmmPanel}>
          <Text size={12} tone="dim" className={pageStyles.noData}>
            Insufficient intraday data — need 500+ 15-min bars (≈120 days) from Tradier.
          </Text>
        </div>
      )}

      {/* 7. Sector heatmap */}
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

      {/* 8. Market news */}
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
