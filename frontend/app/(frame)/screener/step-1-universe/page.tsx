'use client';

/*
 * Screener Step 1 — Universe selection. Phase 5 / Round 1.
 * Preset cards for major indices + a Custom option with paste/type input
 * for arbitrary single symbols / ETFs, plus min/max price and min/max
 * market-cap filters that apply to any selected universe.
 */

import { useMemo, useState, useCallback } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

type Universe =
  | 'SP500'
  | 'NDX100'
  | 'DOW30'
  | 'SPY'
  | 'Watchlist'
  | 'Custom';

type CapUnit = 'M' | 'B';

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
  const {
    pick, customRaw, minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit,
    setPick, setCustomRaw, setMinPriceRaw, setMaxPriceRaw, setMinCapRaw, setMaxCapRaw,
    setCapUnit, clearFilters,
  } = useUniverseStore();

  const watchlistCount = useWatchlistStore((s) => s.added.length);

  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setRefreshError(false);
    try {
      const regime = await api.getRegime();
      useScanStore.getState().setRegime(regime.overall);
      setLastRefreshed(new Date().toLocaleTimeString());
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  const symbols  = useMemo(() => parseSymbols(customRaw), [customRaw]);

  const OPTIONS: { key: Universe; label: string; count: number | string; desc: string }[] = [
    { key: 'SP500',       label: 'S&P 500',      count: 503,  desc: 'Large-cap US equities. Recommended for most users.' },
    { key: 'NDX100',      label: 'Nasdaq-100',   count: 100,  desc: 'Tech-heavy large caps. Higher vol, higher signal.' },
    { key: 'DOW30',       label: 'Dow 30',       count: 30,   desc: 'Blue-chip US industrials. Narrow but liquid.' },
    { key: 'SPY',         label: 'SPY ETF',      count: 1,    desc: 'S&P 500 ETF — single contract, fast scan for testing.' },
    { key: 'Watchlist',   label: 'My Watchlist', count: watchlistCount, desc: 'Only symbols on your personal watchlist.' },
    { key: 'Custom',      label: 'Custom list',  count: symbols.length || '—',  desc: 'Paste or type your own tickers (stocks / ETFs).' },
  ];

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
                {typeof o.count === 'number'
                  ? `${o.count} ${o.count === 1 ? 'symbol' : 'symbols'}`
                  : o.count}
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
                  aria-describedby={priceInvalid ? 'filter-warning' : undefined}
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
                  aria-describedby={priceInvalid ? 'filter-warning' : undefined}
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
                  aria-describedby={capInvalid ? 'filter-warning' : undefined}
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
                  aria-describedby={capInvalid ? 'filter-warning' : undefined}
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

        {(priceInvalid || capInvalid) && (
          <div
            id="filter-warning"
            className={formStyles.filterWarning}
            role="alert"
          >
            <Text size={12} tone="reject">
              {priceInvalid && capInvalid
                ? 'Fix filter ranges before proceeding — both minimums are above their maximums.'
                : 'Fix filter range before proceeding — minimum is above maximum.'}
            </Text>
          </div>
        )}

        <div className={formStyles.filtersFooter}>
          {hasFilters ? (
            <>
              {!(priceInvalid || capInvalid) && (
                <Text size={11} tone="secondary">
                  Filters:&nbsp;
                  {priceSummary && <>price {priceSummary}</>}
                  {priceSummary && capSummary && <> · </>}
                  {capSummary && <>cap {capSummary}</>}
                </Text>
              )}
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

        <div className={formStyles.refreshRow}>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className={formStyles.refreshBtn}
            aria-label="Refresh regime data"
          >
            {refreshing ? 'Refreshing\u2026' : 'Refresh regime'}
          </button>
          {lastRefreshed && !refreshError && (
            <Text size={11} tone="dim">Updated {lastRefreshed}</Text>
          )}
          {refreshError && (
            <Text size={11} tone="reject">Refresh failed</Text>
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
          value={customRaw}
          onChange={(e) => setCustomRaw(e.target.value)}
          disabled={!isCustom}
          aria-label="Custom ticker list"
        />
        {isCustom && (
          <div className={formStyles.uploadRow}>
            <input
              type="file"
              accept=".csv"
              id="csv-upload"
              className={formStyles.fileInput}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                  const text = String(ev.target?.result ?? '');
                  const lines = text
                    .split(/\r?\n/)
                    .map((s) => s.trim().toUpperCase())
                    .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s));
                  const unique = Array.from(new Set(lines));
                  if (unique.length > 0) {
                    setCustomRaw(unique.join(' '));
                  }
                };
                reader.readAsText(file);
                // Reset so the same file can be selected again
                e.target.value = '';
              }}
            />
            <label htmlFor="csv-upload" className={formStyles.uploadBtn}>
              Upload CSV
            </label>
            <Text size={11} tone="dim">One symbol per line</Text>
          </div>
        )}
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
                    setCustomRaw(symbols.filter((x) => x !== s).join(' '));
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
