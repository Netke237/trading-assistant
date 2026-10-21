'use client';

/*
 * Screener Step 2 — Universe selection.
 * Preset cards for major indices + sector-based universes (coloured by
 * sector ETF daily changePct) + a Custom option, plus price/cap filters.
 */

import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useUniverseStore } from '@/lib/universeStore';
import type { Universe } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { api, getLastDataRefresh } from '@/lib/api';
import { applyRegimeResponse, beginRegimeFetch, fetchGateRegime } from '@/lib/regimeFetchOrder';
import type { SectorTile, IndexChangeTile } from '@/types/domain';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

const SECTOR_ETF_KEYS = [
  'XLK', 'XLC', 'XLY', 'XLI', 'XLF',
  'XLP', 'XLV', 'XLB', 'XLRE', 'XLU', 'XLE',
] as const;

type SectorEtfKey = typeof SECTOR_ETF_KEYS[number];

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

function cardStatusTooltip(label: string, status: IndexChangeTile['status'] | null, changePct: number | undefined): string | undefined {
  if (!status || changePct == null) return undefined;
  const move = status === 'PASS' ? 'up' : status === 'REJECT' ? 'down' : 'roughly flat';
  return `${label} is ${move} today (${changePct > 0 ? '+' : ''}${changePct.toFixed(2)}%) — border color reflects this.`;
}

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

export default function Step2Page() {
  const {
    pick, customRaw, minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit,
    setPick, setCustomRaw, setMinPriceRaw, setMaxPriceRaw, setMinCapRaw, setMaxCapRaw,
    setCapUnit, clearFilters,
  } = useUniverseStore();

  const watchlistCount = useWatchlistStore((s) => s.added.length);

  const [sectors, setSectors]           = useState<SectorTile[]>([]);
  const [indexChanges, setIndexChanges] = useState<IndexChangeTile[]>([]);

  // Keyed lookups built from fetched data
  const sectorByKey = useMemo<Record<string, SectorTile>>(() => {
    const m: Record<string, SectorTile> = {};
    for (const t of sectors) m[t.key] = t;
    return m;
  }, [sectors]);

  const indexByKey = useMemo<Record<string, IndexChangeTile>>(() => {
    const m: Record<string, IndexChangeTile> = {};
    for (const t of indexChanges) m[t.key] = t;
    return m;
  }, [indexChanges]);

  const statusForKey = useCallback((key: Universe): IndexChangeTile['status'] | null => {
    if (key === 'SP500' || key === 'SPY') return indexByKey['SPY']?.status ?? null;
    if (key === 'NDX100')                 return indexByKey['QQQ']?.status ?? null;
    if (key.startsWith('SECTOR:')) {
      const etfKey = key.slice(7) as SectorEtfKey;
      return sectorByKey[etfKey]?.status ?? null;
    }
    return null;
  }, [indexByKey, sectorByKey]);

  const changePctForKey = useCallback((key: Universe): number | undefined => {
    if (key === 'SP500' || key === 'SPY') return indexByKey['SPY']?.changePct;
    if (key === 'NDX100')                 return indexByKey['QQQ']?.changePct;
    if (key.startsWith('SECTOR:'))        return sectorByKey[key.slice(7)]?.changePct;
    return undefined;
  }, [indexByKey, sectorByKey]);

  const cardClasses = useCallback((key: Universe): string => {
    const isActive = pick === key;
    const status   = isActive ? null : statusForKey(key);
    return [
      formStyles.card,
      isActive             ? formStyles.cardActive  : '',
      status === 'PASS'    ? formStyles.cardPass    : '',
      status === 'CAUTION' ? formStyles.cardCaution : '',
      status === 'REJECT'  ? formStyles.cardReject  : '',
    ].filter(Boolean).join(' ');
  }, [pick, statusForKey]);

  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setRefreshError(false);
    try {
      // Same request and the same ordering as Steps 1 and 3: an older answer
      // never replaces a newer one that already landed on the shared gate.
      const ticket = beginRegimeFetch();
      const regime = await fetchGateRegime();
      if (applyRegimeResponse(ticket, regime)) setLastRefreshed(new Date().toLocaleTimeString());
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  const symbols  = useMemo(() => parseSymbols(customRaw), [customRaw]);

  const isWatchlistPick = pick === 'Watchlist';
  const isSectorPick    = pick.startsWith('SECTOR:');

  const [histYears,      setHistYears]      = useState(5);
  const [loadError,      setLoadError]      = useState<string | null>(null);
  const [lastRefreshTs,  setLastRefreshTs]  = useState<string | null>(null);
  const [histStatus, setHistStatus] = useState<{
    status: 'idle' | 'running' | 'completed' | 'error';
    total: number; done: number; failed: number;
    current_symbol: string | null; elapsed_secs: number;
  }>({ status: 'idle', total: 0, done: 0, failed: 0, current_symbol: null, elapsed_secs: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch sector heatmap data and index daily changes for button colouring.
  useEffect(() => {
    api.getSectors().then(setSectors).catch(() => {});
    api.getIndexChanges().then(setIndexChanges).catch(() => {});
  }, []);

  // Sync with backend on mount so a running prefetch is reflected immediately.
  useEffect(() => {
    api.getHistoryPrefetchStatus()
      .then(setHistStatus)
      .catch(() => { /* backend may not be running yet */ });
    getLastDataRefresh()
      .then((r) => setLastRefreshTs(r.last_refresh))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (histStatus.status === 'running' && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getHistoryPrefetchStatus();
          setHistStatus(s);
          if (s.status !== 'running' && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            // Refresh the last-refresh timestamp now that the job finished.
            getLastDataRefresh().then((r) => setLastRefreshTs(r.last_refresh)).catch(() => {});
          }
        } catch { /* silent — backend may be restarting */ }
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [histStatus.status]);

  const handleLoadHistory = useCallback(async () => {
    const universe = pick === 'Custom' ? symbols : [pick];
    if (!universe.length) return;
    try {
      await api.startHistoryPrefetch({ universe, years: histYears });
    } catch (e) {
      if (e instanceof Error && e.message.includes('→ 409')) {
        // Already running on the backend — sync state and let polling take over.
        try {
          const s = await api.getHistoryPrefetchStatus();
          setHistStatus(s);
          setLoadError(null);
        } catch {
          setLoadError('Prefetch is already running — could not fetch status.');
        }
        return;
      }
      const msg = e instanceof TypeError
        ? 'Cannot reach the backend — make sure the server is running.'
        : e instanceof Error ? e.message : 'Failed to start history load';
      setLoadError(msg);
      console.error('History prefetch failed to start:', e);
      return;
    }
    try {
      const s = await api.getHistoryPrefetchStatus();
      setHistStatus(s);
      setLoadError(null);
    } catch {
      /* prefetch started OK — status check failure is non-critical */
    }
  }, [pick, symbols, histYears]);

  const OPTIONS: { key: Universe; label: string; count: number | string; desc: string }[] = [
    { key: 'SP500',       label: 'S&P 500',      count: 503,  desc: 'Large-cap US equities. Recommended for most users.' },
    { key: 'NDX100',      label: 'Nasdaq-100',   count: 100,  desc: 'Tech-heavy large caps. Higher vol, higher signal.' },
    { key: 'DOW30',       label: 'Dow 30',       count: 30,   desc: 'Blue-chip US industrials. Narrow but liquid.' },
    { key: 'SPY',         label: 'SPY ETF',      count: 1,    desc: 'S&P 500 ETF — single contract, fast scan for testing.' },
    { key: 'Watchlist',   label: 'My Watchlist', count: watchlistCount, desc: 'Only symbols on your personal watchlist.' },
    { key: 'Custom',      label: 'Custom list',  count: symbols.length || '—',  desc: 'Paste or type your own tickers (stocks / ETFs).' },
  ];

  const SECTOR_OPTIONS = useMemo(() =>
    SECTOR_ETF_KEYS.map((etfKey) => {
      const tile   = sectorByKey[etfKey];
      const uniKey = `SECTOR:${etfKey}` as Universe;
      return { key: uniKey, etfKey, label: tile?.name ?? etfKey, tile };
    }),
  [sectorByKey]);

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
        <Text size={11} tone="dim" weight={500}>STEP 2 OF 7</Text>
        <Title as="h1" size={24}>Universe</Title>
        <Text size={13} tone="secondary">Pick the stock universe to scan.</Text>
      </div>

      <div className={formStyles.cards}>
        {OPTIONS.map((o) => {
          const changePct = pick !== o.key ? changePctForKey(o.key) : undefined;
          return (
            <button
              key={o.key}
              type="button"
              onClick={() => setPick(o.key)}
              className={cardClasses(o.key)}
              aria-pressed={pick === o.key}
              title={cardStatusTooltip(o.label, pick !== o.key ? statusForKey(o.key) : null, changePct)}
            >
              <div className={formStyles.cardHeader}>
                <Text size={14} weight={600}>{o.label}</Text>
                <div className={formStyles.cardMeta}>
                  <Data size={11} tone="secondary">
                    {typeof o.count === 'number'
                      ? `${o.count} ${o.count === 1 ? 'symbol' : 'symbols'}`
                      : o.count}
                  </Data>
                  {changePct != null && (
                    <Data
                      size={11}
                      tone={changePct > 0 ? 'pass' : changePct < 0 ? 'reject' : 'secondary'}
                    >
                      {changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%
                    </Data>
                  )}
                </div>
              </div>
              <Text size={12} tone="secondary">{o.desc}</Text>
            </button>
          );
        })}
      </div>

      {/* Sector universes — scan only stocks from one GICS sector of the S&P 500 */}
      <div className={formStyles.sectionLabel}>
        <Text size={12} weight={600}>By sector (S&P 500)</Text>
        <Text size={11} tone="dim">
          {sectors.length > 0
            ? 'Coloured by today\'s sector ETF performance'
            : 'Sector performance loading…'}
        </Text>
      </div>
      <div className={formStyles.sectorCards}>
        {SECTOR_OPTIONS.map((o) => {
          const pct     = o.tile?.changePct;
          const count   = o.tile?.symbolCount ?? 0;
          return (
            <button
              key={o.key}
              type="button"
              onClick={() => setPick(o.key)}
              className={cardClasses(o.key)}
              aria-pressed={pick === o.key}
              title={cardStatusTooltip(o.label, pick !== o.key ? (o.tile?.status ?? null) : null, pct)}
            >
              <div className={formStyles.cardHeader}>
                <Text size={13} weight={600}>{o.label}</Text>
                {pct != null && pick !== o.key && (
                  <Data
                    size={11}
                    tone={pct > 0 ? 'pass' : pct < 0 ? 'reject' : 'secondary'}
                  >
                    {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
                  </Data>
                )}
              </div>
              <Data size={11} tone="secondary">
                {sectors.length === 0
                  ? 'Loading…'
                  : count > 0 ? `${count} symbols` : '— symbols'}
              </Data>
            </button>
          );
        })}
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
        {isCustom && symbols.length === 0 && customRaw.trim().length > 0 && (
          <Text size={11} tone="reject">No valid symbols recognised — use A–Z ticker format.</Text>
        )}
        {isCustom && symbols.length === 0 && customRaw.trim().length === 0 && (
          <Text size={11} tone="reject">Enter at least one valid symbol.</Text>
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

      {/* Historical data pre-load */}
      <div className={formStyles.historyPanel}>
        <div className={formStyles.historyPanelHeader}>
          <div>
            <Text size={13} weight={600}>Historical data</Text>
            <Text size={11} tone="secondary">
              Pre-load OHLCV history for the selected universe so stock scans read from the
              local database instead of hitting Tiingo live.
            </Text>
          </div>
        </div>

        <div className={formStyles.historyControls}>
          <Text size={12} tone="dim">Horizon:</Text>
          <select
            className={formStyles.horizonSelect}
            value={histYears}
            onChange={(e) => setHistYears(Number(e.target.value))}
            disabled={histStatus.status === 'running'}
          >
            <option value={1}>1 year</option>
            <option value={2}>2 years</option>
            <option value={3}>3 years</option>
            <option value={5}>5 years (recommended)</option>
          </select>

          <button
            type="button"
            className={`${formStyles.loadBtn} ${histStatus.status === 'running' ? formStyles.loadBtnRunning : ''}`}
            onClick={handleLoadHistory}
            disabled={histStatus.status === 'running' || isWatchlistPick || isSectorPick}
          >
            {histStatus.status === 'running'
              ? `Loading… ${histStatus.done}/${histStatus.total}`
              : histStatus.status === 'completed'
                ? `Reload history (${histStatus.done} symbols)`
                : 'Load history in background'}
          </button>
        </div>

        {(isWatchlistPick || isSectorPick) && (
          <Text size={11} tone="dim">
            {isWatchlistPick
              ? 'History pre-load is not available for the Watchlist universe. Select a preset (e.g. SP500) or Custom symbols instead.'
              : 'History pre-load is not available for sector universes. Select SP500 to pre-load all sectors at once.'}
          </Text>
        )}

        {loadError && (
          <Text size={11} tone="reject">{loadError}</Text>
        )}

        {(histStatus.status === 'running' || histStatus.status === 'completed') && (
          <div className={formStyles.progressWrap}>
            <div className={formStyles.progressBar}>
              <div
                className={formStyles.progressFill}
                style={{ width: histStatus.total > 0 ? `${(histStatus.done / histStatus.total) * 100}%` : '0%' }}
              />
            </div>
            <div className={formStyles.progressLabel}>
              <Text size={11} tone="dim">
                {histStatus.status === 'running' && histStatus.current_symbol
                  ? `Fetching ${histStatus.current_symbol}…`
                  : histStatus.status === 'completed'
                    ? `Complete — ${histStatus.done} loaded, ${histStatus.failed} failed`
                    : ''}
              </Text>
              <Text size={11} tone="dim">{histStatus.elapsed_secs}s</Text>
            </div>
          </div>
        )}

        <div className={formStyles.lastRefreshRow}>
          <Text size={11} tone="dim">
            {lastRefreshTs
              ? `Last data refresh: ${new Date(lastRefreshTs).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`
              : 'No data loaded yet — click “Load history” above.'}
          </Text>
        </div>
      </div>
    </div>
  );
}
