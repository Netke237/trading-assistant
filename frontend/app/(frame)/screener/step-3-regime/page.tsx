'use client';

/*
 * Screener Step 3 — Market Regime.
 * Macro snapshot — advisory for the user's trade. REJECT prompts confirmation
 * before proceeding to Step 4.
 *
 * Layout:
 *   1. Overall banner (PASS / CAUTION / REJECT + headline)
 *   2. Explainer (what this page means + how it's computed)
 *   3. Mini SPX + NDX candlestick charts (120 daily bars)
 *   4. Metric grid (SPX/NDX trend, breadth, VIX, yields, credit, put/call…)
 *   5. Sector heatmap (11 GICS sectors, 1-day change)
 */

import { useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { useScanStore } from '@/lib/scanStore';
import { MOCK_REGIME } from '@/mocks/regime';
import { MOCK_SECTORS } from '@/mocks/sectors';
import { candlesFor } from '@/mocks/candles';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

function toneFor(status: string): 'pass' | 'caution' | 'reject' | undefined {
  if (status === 'PASS')    return 'pass';
  if (status === 'CAUTION') return 'caution';
  if (status === 'REJECT')  return 'reject';
  return undefined;
}

function lastClose(symbol: string): { close: number; changePct: number } {
  const c = candlesFor(symbol);
  const last = c[c.length - 1];
  const prev = c[c.length - 2];
  if (!last || !prev) return { close: 0, changePct: 0 };
  return { close: last.close, changePct: ((last.close - prev.close) / prev.close) * 100 };
}

export default function Step3Page() {
  const setRegime = useScanStore((s) => s.setRegime);
  useEffect(() => { setRegime(MOCK_REGIME.overall); }, [setRegime]);

  const spx = lastClose('SPX');
  const ndx = lastClose('NDX');

  const sectorsUp   = MOCK_SECTORS.filter((s) => s.changePct >   0.05).length;
  const sectorsDown = MOCK_SECTORS.filter((s) => s.changePct <  -0.05).length;

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 3 OF 7</Text>
        <Title as="h1" size={24}>Market Regime</Title>
        <Text size={13} tone="secondary">
          Macro snapshot — advisory. REJECT prompts confirmation before proceeding.
        </Text>
      </div>

      {/* 1. Overall banner */}
      <section className={`${pageStyles.banner} ${pageStyles[`banner_${MOCK_REGIME.overall}`]}`}>
        <div className={pageStyles.bannerLeft}>
          <StatusBadge status={MOCK_REGIME.overall} label={`REGIME ${MOCK_REGIME.overall}`} />
          <Text size={14} weight={500}>{MOCK_REGIME.headline}</Text>
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
            <Text size={13} weight={600}>S&amp;P 500 (SPX)</Text>
            <div className={pageStyles.indexPriceGroup}>
              <Data size={14} weight={500}>{spx.close.toFixed(2)}</Data>
              <Data size={11} tone={spx.changePct > 0 ? 'pass' : spx.changePct < 0 ? 'reject' : undefined}>
                {spx.changePct > 0 ? '+' : ''}{spx.changePct.toFixed(2)}%
              </Data>
            </div>
          </header>
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={candlesFor('SPX')} height="auto" />
          </div>
        </div>
        <div className={pageStyles.indexCard}>
          <header className={pageStyles.indexHeader}>
            <Text size={13} weight={600}>Nasdaq 100 (NDX)</Text>
            <div className={pageStyles.indexPriceGroup}>
              <Data size={14} weight={500}>{ndx.close.toFixed(2)}</Data>
              <Data size={11} tone={ndx.changePct > 0 ? 'pass' : ndx.changePct < 0 ? 'reject' : undefined}>
                {ndx.changePct > 0 ? '+' : ''}{ndx.changePct.toFixed(2)}%
              </Data>
            </div>
          </header>
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={candlesFor('NDX')} height="auto" />
          </div>
        </div>
      </div>

      {/* 4. Metric grid */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>Regime inputs</Text>
        <Text size={12} tone="secondary">Each gate contributes to the overall call</Text>
      </div>
      <div className={pageStyles.grid}>
        {MOCK_REGIME.metrics.map((m) => (
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

      {/* 5. Sector heatmap */}
      <div className={pageStyles.sectionHeader}>
        <Text size={13} weight={600}>Sector heatmap</Text>
        <Text size={12} tone="secondary">
          {sectorsUp} up · {sectorsDown} down · today
        </Text>
      </div>
      <div className={pageStyles.sectors}>
        {MOCK_SECTORS.map((s) => (
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
    </div>
  );
}
