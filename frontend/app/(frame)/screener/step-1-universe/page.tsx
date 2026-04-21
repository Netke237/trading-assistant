'use client';

/*
 * Screener Step 1 — Universe selection. Phase 5 / Round 1.
 * Preset cards for major indices + a Custom option with paste/type input
 * for arbitrary single symbols / ETFs.
 */

import { useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

type Universe =
  | 'SP500'
  | 'NDX100'
  | 'DOW30'
  | 'RUSSELL2000'
  | 'STOXX600'
  | 'DAX40'
  | 'Watchlist'
  | 'Custom';

const OPTIONS: { key: Universe; label: string; count: number | string; desc: string }[] = [
  { key: 'SP500',       label: 'S&P 500',      count: 503,  desc: 'Large-cap US equities. Recommended for most users.' },
  { key: 'NDX100',      label: 'Nasdaq-100',   count: 100,  desc: 'Tech-heavy large caps. Higher vol, higher signal.' },
  { key: 'DOW30',       label: 'Dow 30',       count: 30,   desc: 'Blue-chip US industrials. Narrow but liquid.' },
  { key: 'RUSSELL2000', label: 'Russell 2000', count: 2000, desc: 'US small caps. Broader breadth, thinner liquidity.' },
  { key: 'STOXX600',    label: 'STOXX 600',    count: 600,  desc: 'European large/mid caps.' },
  { key: 'DAX40',       label: 'DAX 40',       count: 40,   desc: 'German blue chips. Liquid European single-stock options.' },
  { key: 'Watchlist',   label: 'My Watchlist', count: 10,   desc: 'Only symbols on your personal watchlist.' },
  { key: 'Custom',      label: 'Custom list',  count: '—',  desc: 'Paste or type your own tickers (stocks / ETFs).' },
];

/** Parse raw textarea → unique upper-cased tickers (1–6 chars A–Z + digits). */
function parseSymbols(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,;\n]+/)
        .map((s) => s.trim().toUpperCase())
        .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)),
    ),
  );
}

export default function Step1Page() {
  const [pick, setPick] = useState<Universe>('SP500');
  const [raw, setRaw]   = useState('');

  const symbols = useMemo(() => parseSymbols(raw), [raw]);
  const isCustom = pick === 'Custom';

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 1 OF 7</Text>
        <Title as="h1" size={24}>Universe</Title>
        <Text size={13} tone="secondary">Pick the stock universe to scan.</Text>
      </div>

      <div className={formStyles.cards}>
        {OPTIONS.map((o) => (
          <button
            key={o.key}
            type="button"
            onClick={() => setPick(o.key)}
            className={`${formStyles.card} ${pick === o.key ? formStyles.cardActive : ''}`}
            aria-pressed={pick === o.key}
          >
            <div className={formStyles.cardHeader}>
              <Text size={14} weight={600}>{o.label}</Text>
              <Data size={11} tone="secondary">
                {typeof o.count === 'number' ? `${o.count} symbols` : o.count}
              </Data>
            </div>
            <Text size={12} tone="secondary">{o.desc}</Text>
          </button>
        ))}
      </div>

      {/* Custom symbols panel — enabled only when Custom is picked */}
      <div className={`${formStyles.customPanel} ${isCustom ? '' : formStyles.customPanelDim}`}>
        <div className={formStyles.customHint}>
          <Text size={12} weight={600}>Your symbols</Text>
          <Text size={11} tone="secondary">
            {symbols.length > 0 ? `${symbols.length} parsed` : 'Space, comma, or new-line separated'}
          </Text>
        </div>
        <textarea
          className={formStyles.symInput}
          placeholder="AAPL NVDA TSLA SPY QQQ IWM …"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          disabled={!isCustom}
          aria-label="Custom ticker list"
        />
        {symbols.length > 0 && (
          <div className={formStyles.chips} aria-label="Parsed tickers">
            {symbols.map((s) => (
              <span key={s} className={formStyles.chip}>
                {s}
                <button
                  type="button"
                  className={formStyles.chipRemove}
                  aria-label={`Remove ${s}`}
                  onClick={() => {
                    // Rewrite the raw textarea minus this symbol.
                    setRaw(symbols.filter((x) => x !== s).join(' '));
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
