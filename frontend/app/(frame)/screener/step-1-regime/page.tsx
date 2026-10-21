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

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { toneForStatus } from '@/lib/status';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { NewsCard } from '@/components/molecules/NewsCard';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { api } from '@/lib/api';
import type { MarketRegime, SectorTile, NewsItem, SentimentData } from '@/types/domain';
import type { Candle } from '@/types/chart';
import { alignmentVerdict, descriptorFromState } from '@/lib/regimeAlignment';
import { applyRegimeResponse, beginRegimeFetch, fetchGateRegime } from '@/lib/regimeFetchOrder';
import { formatRegimeAge, formatRegimeAverage } from '@/lib/regimeDuration';
import { formatOrdinal } from '@/lib/formatOrdinal';
import { regimeStatusTooltip, regimeMetricTooltip, regimeNoDataTooltip } from '@/lib/statusTooltips';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

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

/** The Market Sentiment reading built from a regime response — `null` when it
 *  carries no `omm`. Used for Step 1's own MarketSentiment and for
 *  `scanStore.regimeSentiment` (the Stocks Strategy page's strip). */
function sentimentFromRegime(r: MarketRegime, horizon: string): SentimentData | null {
  if (!r.omm) return null;
  return {
    horizon,
    timeframe: 'daily',
    state: r.omm.state,
    p_stay: r.omm.p_stay,
    stability: r.omm.stability,
    regime_age_days: r.omm.regime_age_days,
    avg_regime_duration: r.omm.avg_regime_duration,
    ...(r.omm.duration_stride_bars != null
      ? { duration_stride_bars: r.omm.duration_stride_bars }
      : {}),
    conviction_pct: r.conviction_pct ?? 0,
    conviction_label: r.conviction_label ?? 'Neutral',
    interpretation: `Market conviction: ${r.conviction_label ?? 'Neutral'}`,
    hmm_state: r.hmm_state ?? null,
    alignment: (r.alignment ?? 'Unavailable') as 'Aligned' | 'Diverging' | 'Unavailable',
    insufficient_data: false,
  };
}

/** Step 1's own request order, for what only Step 1 writes (the page's regime
 *  data, `regimeSentiment`, the failure banner). Separate from the shared gate
 *  ticket (`lib/regimeFetchOrder.ts`): a later Step 2/3 fetch must not stop a
 *  Step 1 response from delivering the sentiment. `step1RegimeRequestSeq` is
 *  bumped by every `fetchRegime` call; `step1LastAppliedSeq` is the newest
 *  request whose response was written. Module-level, not refs: they must
 *  outlive the component, because an earlier mount's request can still answer
 *  after a later mount's request has started (or answered). */
let step1RegimeRequestSeq = 0;
let step1LastAppliedSeq = 0;

export default function Step1RegimePage() {
  const setCombinedRegime = useScanStore((s) => s.setCombinedRegime);
  const setRegimeSentiment = useScanStore((s) => s.setRegimeSentiment);
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
  // Distinct from `offline` (which also flips on sector/candle/news fetch
  // failures): tracks specifically that the regime fetch itself failed, so
  // combinedRegime is stuck at PENDING — StepNavBar blocks Next in that
  // state, so the user needs a visible way to retry rather than being
  // silently stuck forever (see H5).
  const [regimeFetchFailed, setRegimeFetchFailed] = useState(false);

  const fetchRegime = useCallback(() => {
    setRegimeFetchFailed(false);
    // Written here, not by an effect: these callbacks still run after the
    // user leaves Step 1. The shared gate takes the response only if no newer
    // Step 1–3 response already landed (`applyRegimeResponse`); the page's own
    // reading and the sentiment likewise only if no newer Step 1 response
    // landed. A failure shows only for the latest Step 1 request started, so
    // an older request failing after a newer one started leaves it all alone.
    const ticket = beginRegimeFetch();
    const seq = ++step1RegimeRequestSeq;
    setRegimeSentiment(null);
    // `fetchGateRegime` sends 'intraday' (so the HMM is always computed — the
    // regime step is visited before horizon selection, step 3) with the
    // Settings Markov values.
    fetchGateRegime().then((r) => {
      applyRegimeResponse(ticket, r);
      if (seq > step1LastAppliedSeq) {
        step1LastAppliedSeq = seq;
        setRegimeData(r);
        setRegimeSentiment(sentimentFromRegime(r, useScanStore.getState().context?.horizon ?? 'Swing'));
      }
    }).catch(() => {
      if (seq !== step1RegimeRequestSeq) return;
      setOffline(true);
      setRegimeFetchFailed(true);
      setRegimeSentiment(null);
    });
    // `markov` is read inside fetchGateRegime, not here; it is a dependency so
    // a Settings change re-creates fetchRegime and the mount effect refetches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setRegimeSentiment, markov]);

  // The verdict follows the context's direction, not only the moment the
  // regime fetch resolved: StoreHydration can restore a scan's context
  // (STEP3-PARAM-REACH) AFTER that, and a Bearish restore would otherwise
  // leave a Bullish verdict on the Step-1 REJECT gate and the Step-7 rail.
  const direction = context?.direction ?? 'Bullish';
  useEffect(() => {
    if (!regime) return;
    setCombinedRegime(alignmentVerdict(direction, descriptorFromState(regime.omm?.state ?? '')));
  }, [direction, regime, setCombinedRegime]);

  useEffect(() => {
    fetchRegime();

    api.getSectors().then(setSectors).catch(() => setOffline(true));
    api.getCandles('SPY').then(setSpxCandles).catch(() => setOffline(true));
    api.getCandles('QQQ').then(setNdxCandles).catch(() => setOffline(true));

    const candidates = useScanStore.getState().scanResult?.candidates.map((c) => c.symbol) ?? [];
    const symbols = candidates.length > 0 ? candidates : ['SPY', 'QQQ', 'VIX', 'DIA'];
    setNewsLoading(true);
    api.getNews(symbols).then(setNews).catch(() => setNewsError(true)).finally(() => setNewsLoading(false));
  }, [fetchRegime]);

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

  const pageSentiment = useMemo(
    () => (regime ? sentimentFromRegime(regime, context?.horizon ?? 'Swing') : null),
    [regime, context?.horizon],
  );

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
        <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
      )}

      {regimeFetchFailed && (
        <div className={pageStyles.regimeRetryBanner}>
          <Text size={13} tone="reject">
            Regime check failed — Next is blocked until it loads.
          </Text>
          <button type="button" className={pageStyles.regimeRetryBtn} onClick={fetchRegime}>
            <Text size={12} weight={500}>Retry</Text>
          </button>
        </div>
      )}

      {/* 1. Overall banner */}
      <section data-testid="regime-banner" className={`${pageStyles.banner} ${pageStyles[`banner_${combinedStatus}`]}`}>
        <div className={pageStyles.bannerLeft}>
          <StatusBadge status={combinedStatus} label={`REGIME ${combinedStatus}`} tooltip={regimeStatusTooltip(combinedStatus)} />
          {regime?.regime_direction && (
            <span
              role="img"
              aria-label={
                regime.regime_direction === 'BULL' ? 'Regime direction: Bullish'
                : regime.regime_direction === 'BEAR' ? 'Regime direction: Bearish'
                : 'Regime direction: Mixed'
              }
              className={`${pageStyles.directionPill} ${pageStyles[`directionPill_${regime.regime_direction}`]}`}
            >
              {regime.regime_direction === 'BULL' ? '▲ Bullish'
               : regime.regime_direction === 'BEAR' ? '▼ Bearish'
               : '≈ Mixed'}
            </span>
          )}
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
          <div data-testid="spx-chart" className={pageStyles.indexChart}>
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
          <div data-testid="ndx-chart" className={pageStyles.indexChart}>
            <CandlestickChart data={ndxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
        </div>
      </div>

      {/* 4. EMA / VIX metric grid */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>EMA / VIX</Text>
        <Text size={12} tone="secondary">SPX &amp; NDX vs 200-day EMA, plus VIX level</Text>
      </div>
      <div data-testid="regime-metric-grid" className={pageStyles.grid}>
        {(regime?.metrics ?? []).map((m) => (
          <div key={m.label} className={pageStyles.metricCard}>
            <Text size={12} tone="secondary">{m.label}</Text>
            <div className={pageStyles.metricValueRow}>
              <Data size={18} weight={500} tone={toneForStatus(m.status)}>{m.value}</Data>
              {m.trend === 'up'   && <span className={pageStyles.trendUp}>↑</span>}
              {m.trend === 'down' && <span className={pageStyles.trendDown}>↓</span>}
            </div>
            <StatusBadge status={m.status} tooltip={regimeMetricTooltip(m.label, m.status)} />
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
                    <Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>
                  )}
                </>
              ) : intraOmm ? (
                <>
                  <Data size={14} weight={500} tone={toneForOmmState(intraOmm.state)}>
                    {ommStateIcon(intraOmm.state)} {intraOmm.state}
                  </Data>
                  <Text size={12} tone="secondary">
                    {formatRegimeAge(intraOmm.regime_age_days)} · avg {formatRegimeAverage(intraOmm.avg_regime_duration, intraOmm.duration_stride_bars)} · {intraOmm.stability}
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
                    <Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>
                  )}
                </>
              ) : regime?.intraday_hmm_status === 'insufficient_data' ? (
                <StatusBadge status="NO_DATA" label="Insufficient data" tooltip={regimeNoDataTooltip('insufficient_data')} />
              ) : regime?.intraday_hmm_status === 'unavailable' ? (
                <StatusBadge status="NO_DATA" label="Data unavailable" tooltip={regimeNoDataTooltip('unavailable')} />
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
                    {formatRegimeAge(omm.regime_age_days)} · avg {formatRegimeAverage(omm.avg_regime_duration, omm.duration_stride_bars)} · {omm.stability}
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
                    <Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>
                  )}
                </>
              ) : (
                <StatusBadge status="NO_DATA" label="Insufficient history" tooltip={regimeNoDataTooltip('insufficient_history')} />
              )}
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
                    {formatRegimeAge(omm.regime_age_days)} · avg {formatRegimeAverage(omm.avg_regime_duration, omm.duration_stride_bars)} · {omm.stability}
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
                    <Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>
                  )}
                </>
              ) : (
                <StatusBadge status="NO_DATA" label="Insufficient history" tooltip={regimeNoDataTooltip('insufficient_history')} />
              )}
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
      <div data-testid="sector-heatmap" className={pageStyles.sectors}>
        {sectors.map((s) => (
          <div
            key={s.key}
            className={`${pageStyles.sectorTile} ${pageStyles[`sectorTile_${s.status}`]}`}
            title={`${s.name} (${s.key})`}
          >
            <div className={pageStyles.sectorRow}>
              <Data size={12} weight={500}>{s.key}</Data>
              <Data size={12} weight={500} tone={toneForStatus(s.status)}>
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
