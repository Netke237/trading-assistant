'use client';

/*
 * Screener Step 1 — Universe selection. Phase 5 / Round 1.
 * Preset cards for major indices + a Custom option with paste/type input
 * for arbitrary single symbols / ETFs, plus min/max price and min/max
 * market-cap filters that apply to any selected universe.
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

type CapUnit = 'M' | 'B';

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

function parseNumOrNull(raw: string): number | null {
  if (raw.trim() === '') return null;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function fmtPrice(n: number): string { return `$${n}`; }
function fmtCap(n: number, u: CapUnit): string { return `$${n}${u}`; }

function rangeSummary<T>(
  min: T | null,
  max: T | null,
  fmt: (v: T) => string,
): string | null {
  if (min === null && max === null) return null;
  if (min !== null && max !== null) return `${fmt(min)}–${fmt(max)}`;
  if (min !== null)                 return `≥ ${fmt(min)}`;
  return `≤ ${fmt(max as T)}`;
}

export default function Step1Page() {
  const [pick, setPick] = useState<Universe>('SP500');
  const [raw, setRaw]   = useState('');

  // Filters — kept local for now, lifted into a shared scan store when the
  // backend lands and we need them to survive step navigation.
  const [minPriceRaw, setMinPriceRaw] = useState<string>('');
  const [maxPriceRaw, setMaxPriceRaw] = useState<string>('');
  const [minCapRaw,   setMinCapRaw]   = useState<string>('');
  const [maxCapRaw,   setMaxCapRaw]   = useState<string>('');
  const [capUnit,     setCapUnit]     = useState<CapUnit>('B');

  const symbols  = useMemo(() => parseSymbols(raw), [raw]);
  const isCustom = pick === 'Custom';

  const minPrice = parseNumOrNull(minPriceRaw);
  const maxPrice = parseNumOrNull(maxPriceRaw);
  const minCap   = parseNumOrNull(minCapRaw);
  const maxCap   = parseNumOrNull(maxCapRaw);

  const priceInvalid = minPrice !== null && maxPrice !== null && minPrice > maxPrice;
  const capInvalid   = minCap   !== null && maxCap   !== null && minCap   > maxCap;

  const priceSummary = rangeSummary(minPrice, maxPrice, fmtPrice);
  const capSummary   = rangeSummary(minCap,   maxCap,   (v) => fmtCap(v, capUnit));
  const hasFilters   = priceSummary !== null || capSummary !== null;

  const clearFilters = () => {
    setMinPriceRaw('');
    setMaxPriceRaw('');
    setMinCapRaw('');
    setMaxCapRaw('');
  };

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

      {/* Filters — apply to any universe */}
      <div className={formStyles.filters}>
        <div className={formStyles.filtersHeader}>
          <Text size={12} weight={600}>Filters</Text>
          <Text size={11} tone="secondary">Optional. Applied on top of the universe above.</Text>
        </div>

        <div className={formStyles.filterRow}>
          {/* Price range */}
          <div className={formStyles.filterGroup}>
            <Text size={11} tone="secondary">Price range</Text>
            <div className={formStyles.pairInputs}>
              <div className={formStyles.moneyInput}>
                <span className={formStyles.moneyPrefix}>$</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  placeholder="Min"
                  value={minPriceRaw}
                  onChange={(e) => setMinPriceRaw(e.target.value)}
                  className={formStyles.numInput}
                  aria-label="Minimum stock price in dollars"
                />
              </div>
              <span className={formStyles.pairDash}>–</span>
              <div className={formStyles.moneyInput}>
                <span className={formStyles.moneyPrefix}>$</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  placeholder="Max"
                  value={maxPriceRaw}
                  onChange={(e) => setMaxPriceRaw(e.target.value)}
                  className={formStyles.numInput}
                  aria-label="Maximum stock price in dollars"
                />
              </div>
            </div>
            <Text size={10} tone={priceInvalid ? 'reject' : 'dim'}>
              {priceInvalid
                ? 'Min price is above max price.'
                : 'Keep the price band where you usually trade.'}
            </Text>
          </div>

          {/* Market cap range */}
          <div className={formStyles.filterGroup}>
            <div className={formStyles.groupLabelRow}>
              <Text size={11} tone="secondary">Market cap range</Text>
              <div className={formStyles.unitToggle} role="tablist" aria-label="Market cap unit">
                <button
                  type="button"
                  role="tab"
                  aria-selected={capUnit === 'M'}
                  className={`${formStyles.unitBtn} ${capUnit === 'M' ? formStyles.unitBtnActive : ''}`}
                  onClick={() => setCapUnit('M')}
                >
                  M
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={capUnit === 'B'}
                  className={`${formStyles.unitBtn} ${capUnit === 'B' ? formStyles.unitBtnActive : ''}`}
                  onClick={() => setCapUnit('B')}
                >
                  B
                </button>
              </div>
            </div>
            <div className={formStyles.pairInputs}>
              <div className={formStyles.moneyInput}>
                <span className={formStyles.moneyPrefix}>$</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  placeholder="Min"
                  value={minCapRaw}
                  onChange={(e) => setMinCapRaw(e.target.value)}
                  className={formStyles.numInput}
                  aria-label={`Minimum market cap in ${capUnit === 'B' ? 'billions' : 'millions'}`}
                />
                <span className={formStyles.moneySuffix}>{capUnit}</span>
              </div>
              <span className={formStyles.pairDash}>–</span>
              <div className={formStyles.moneyInput}>
                <span className={formStyles.moneyPrefix}>$</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  placeholder="Max"
                  value={maxCapRaw}
                  onChange={(e) => setMaxCapRaw(e.target.value)}
                  className={formStyles.numInput}
                  aria-label={`Maximum market cap in ${capUnit === 'B' ? 'billions' : 'millions'}`}
                />
                <span className={formStyles.moneySuffix}>{capUnit}</span>
              </div>
            </div>
            <Text size={10} tone={capInvalid ? 'reject' : 'dim'}>
              {capInvalid
                ? 'Min cap is above max cap.'
                : 'Exclude names outside your size band.'}
            </Text>
          </div>
        </div>

        <div className={formStyles.filtersFooter}>
          {hasFilters ? (
            <>
              <Text size={11} tone="secondary">
                Filters:&nbsp;
                {priceSummary && <>price {priceSummary}</>}
                {priceSummary && capSummary && <> · </>}
                {capSummary && <>cap {capSummary}</>}
              </Text>
              <button
                type="button"
                className={formStyles.clearBtn}
                onClick={clearFilters}
              >
                Clear filters
              </button>
            </>
          ) : (
            <Text size={11} tone="dim">No filters — all symbols included.</Text>
          )}
        </div>
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
