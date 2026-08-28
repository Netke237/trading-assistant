'use client';

/*
 * Watchlist — Phase 5.
 * Tabs:
 *   - Stocks:    sortable table of ranked candidates + inline chart on select.
 *   - Contracts: every option contract the user has starred on Step 6.
 *   - Composite Alerts: Markov regime alerts created from the Pre-Breakout scanner.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { WatchStar } from '@/components/atoms/WatchStar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { GENERIC_STATUS_TOOLTIP, contractScoreTooltip } from '@/lib/statusTooltips';
import { api, type CompositeWatch } from '@/lib/api';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { contractLabel, type OptionContract } from '@/types/domain';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import type { WatchlistRow } from '@/types/domain';
import { useChartStore } from '@/lib/chartStore';
import { useWatchlistUiStore } from '@/lib/watchlistUiStore';
import styles from './page.module.css';

type Tab     = 'stocks' | 'contracts' | 'composite';
type SortKey = 'score' | 'symbol' | 'price' | 'rank' | 'scoreDelta';
type SortDir = 'asc' | 'desc';
type ContractSortKey = 'score' | 'dte' | 'price';

const COLUMNS          = '32px 28px 72px 1.4fr 90px 80px 80px 90px 80px 60px 90px';
const CONTRACT_COLUMNS = '28px 72px 1.3fr 120px 80px 72px 80px 80px 100px';

export default function WatchlistPage() {
  const [tab, setTab]         = useState<Tab>('stocks');
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<string | null>(null);
  const [contractSortKey, setContractSortKey] = useState<ContractSortKey>('score');
  const [contractSortDir, setContractSortDir] = useState<SortDir>('desc');
  const [watchlist, setWatchlist]             = useState<WatchlistRow[]>([]);
  const [contracts, setContracts]             = useState<OptionContract[]>([]);
  const [offline, setOffline]                 = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [refreshingWatchlist, setRefreshingWatchlist] = useState(false);
  const [refreshingContracts, setRefreshingContracts] = useState(false);
  const [compositeWatches, setCompositeWatches] = useState<CompositeWatch[]>([]);
  const contractsAbortRef = useRef<AbortController | null>(null);

  const setChartSymbol     = useChartStore((s) => s.setSymbol);
  const setChartSymbolName = useChartStore((s) => s.setSymbolName);
  const setUiSelectedSymbol = useWatchlistUiStore((s) => s.setSelectedSymbol);

  const watchedSymbols            = useWatchlistStore((s) => s.added);
  const syncFromBackend           = useWatchlistStore((s) => s.syncFromBackend);
  const syncContractsFromBackend  = useWatchedContractsStore((s) => s.syncFromBackend);
  const watchedIds = useWatchedContractsStore((s) => s.ids);

  const refreshWatchlist = useCallback(async () => {
    setRefreshingWatchlist(true);
    try {
      const data = await api.getWatchlist();
      setWatchlist(data);
      setLastRefreshedAt(new Date());
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setRefreshingWatchlist(false);
    }
  }, []);

  const refreshComposite = useCallback(async () => {
    try {
      const data = await api.listCompositeWatches();
      setCompositeWatches(Array.isArray(data) ? data : []);
    } catch { /* ignore */ }
  }, []);

  const refreshContracts = useCallback(async () => {
    if (watchedIds.length === 0) { setContracts([]); return; }
    // Abort any in-flight contracts fetch before starting a new one (CRITICAL-3 fix).
    contractsAbortRef.current?.abort();
    const controller = new AbortController();
    contractsAbortRef.current = controller;
    setRefreshingContracts(true);
    const pairs = [...new Set(
      watchedIds.map((id) => {
        const parts = id.split('|');
        return `${parts[0]}|${parts[3] ?? 'C'}`;
      })
    )].map((key) => {
      const [sym, right] = key.split('|');
      return { sym: sym!, right: (right === 'P' ? 'P' : 'C') as 'C' | 'P' };
    });
    try {
      const results = await Promise.all(pairs.map(({ sym, right }) => api.getContracts(sym, right, undefined, controller.signal)));
      if (!controller.signal.aborted) {
        setContracts(results.flat());
        setOffline(false);
      }
    } catch {
      if (!controller.signal.aborted) setOffline(true);
    } finally {
      if (!controller.signal.aborted) setRefreshingContracts(false);
    }
  }, [watchedIds]);

  useEffect(() => {
    syncFromBackend();
    syncContractsFromBackend();
    refreshWatchlist();
    refreshComposite();
  }, [syncFromBackend, syncContractsFromBackend, refreshWatchlist, refreshComposite]);

  useEffect(() => {
    refreshContracts();
  }, [refreshContracts]);

  const sorted = useMemo<WatchlistRow[]>(() => {
    const rows = [...watchlist];
    rows.sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1;
      switch (sortKey) {
        case 'symbol':     return a.symbol.localeCompare(b.symbol) * mul;
        case 'price':      return (a.price - b.price) * mul;
        case 'rank':       return (a.rankDelta - b.rankDelta) * mul;
        case 'scoreDelta': return ((a.scoreDelta ?? 0) - (b.scoreDelta ?? 0)) * mul;
        case 'score':
        default:           return (a.score - b.score) * mul;
      }
    });
    return rows;
  }, [watchlist, sortKey, sortDir]);

  const offlineRows = useMemo<WatchlistRow[]>(
    () =>
      watchedSymbols.map((sym) => ({
        symbol:         sym,
        company:        sym,
        price:          0,
        direction:      'Bullish' as const,
        horizon:        'Swing' as const,
        score:          0,
        rankDelta:      0,
        status:         'NO_DATA' as const,
        breakdown:      { trend: 0, pullback: 0, trigger: 0, event: 0, volatility: 0 },
        nextEventDays:  null,
        nextEventLabel: null,
      })),
    [watchedSymbols],
  );

  const displayRows = useMemo<WatchlistRow[]>(() => {
    if (offline) return offlineRows;
    return sorted.length > 0 ? sorted : offlineRows;
  }, [offline, offlineRows, sorted]);

  const watchedContracts = useMemo<OptionContract[]>(() => {
    const seen = new Set<string>();
    return watchedIds
      .map((storedId) => {
        if (seen.has(storedId)) return null;
        seen.add(storedId);
        const [sym, strike, expiry, type] = storedId.split('|');
        const exact = contracts.find((c) => c.id === storedId);
        if (exact) return exact;
        const storedStrike = String(Math.round(parseFloat(strike)));
        const fallback = contracts.find(
          (c) =>
            c.symbol === sym &&
            String(Math.round(parseFloat(String(c.strike)))) === storedStrike &&
            c.expiry === expiry &&
            c.right === ((type ?? 'C') as 'C' | 'P'),
        );
        // Normalise the id so ContractStar.isWatched(c.id) returns true
        return fallback ? { ...fallback, id: storedId } : null;
      })
      .filter((c): c is OptionContract => c !== null);
  }, [contracts, watchedIds]);

  const sortedContracts = useMemo<OptionContract[]>(() => {
    const list = [...watchedContracts];
    list.sort((a, b) => {
      const mul = contractSortDir === 'asc' ? 1 : -1;
      switch (contractSortKey) {
        case 'price': return (a.price - b.price) * mul;
        case 'dte':   return (a.dte - b.dte) * mul;
        case 'score':
        default:      return (a.score - b.score) * mul;
      }
    });
    return list;
  }, [watchedContracts, contractSortKey, contractSortDir]);

  const toggleContractSort = (k: ContractSortKey) => {
    if (k === contractSortKey) setContractSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setContractSortKey(k); setContractSortDir('desc'); }
  };

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(k); setSortDir(k === 'symbol' ? 'asc' : 'desc'); }
  };

  const onSelect = (symbol: string, company: string) => {
    // Computed from the closure, not a setSelected functional updater — a
    // click handler runs once per click, so there's no rapid-fire staleness
    // risk here, and calling setUiSelectedSymbol (a different store's
    // setter) from inside a useState updater triggers React's "Cannot
    // update a component while rendering a different component" warning
    // under StrictMode.
    const next = selected === symbol ? null : symbol;
    setSelected(next);
    setUiSelectedSymbol(next);
    setChartSymbol(symbol);
    setChartSymbolName(company);
  };

  // Clear the rail's selected-symbol note when leaving this page (mirrors
  // Portfolio's own cleanup), so a stale selection never lingers into a
  // future visit — even though chartStore's own persisted symbol keeps
  // whatever was last clicked, this dedicated store deliberately doesn't.
  useEffect(() => {
    return () => setUiSelectedSymbol(null);
  }, [setUiSelectedSymbol]);

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <div className={styles.headingTop}>
          <Title as="h1" size={24}>Watchlist</Title>
          <div className={styles.refreshRow}>
            {tab === 'stocks' && lastRefreshedAt && (
              <Text size={11} tone="dim">Scan data refreshed {timeAgoLabel(lastRefreshedAt)}</Text>
            )}
            <button
              type="button"
              className={styles.refreshBtn}
              onClick={tab === 'stocks' ? refreshWatchlist : refreshContracts}
              disabled={tab === 'stocks' ? refreshingWatchlist : refreshingContracts}
            >
              {(tab === 'stocks' ? refreshingWatchlist : refreshingContracts) ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
        <Text size={13} tone="secondary">
          {tab === 'stocks'
            ? `${displayRows.length} starred · sorted by ${sortKey} ${sortDir === 'asc' ? '↑' : '↓'}`
            : tab === 'contracts'
            ? `${sortedContracts.length} starred contract${sortedContracts.length === 1 ? '' : 's'} · sorted by ${contractSortKey} ${contractSortDir === 'asc' ? '↑' : '↓'}`
            : `${compositeWatches.length} composite alert${compositeWatches.length === 1 ? '' : 's'}`}
        </Text>
        {offline && (
          <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
        )}
      </div>

      <div className={styles.tabs} role="tablist" aria-label="Watchlist views">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'stocks'}
          className={`${styles.tab} ${tab === 'stocks' ? styles.tabActive : ''}`}
          onClick={() => setTab('stocks')}
        >
          Stocks <span className={styles.tabCount}>{displayRows.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'contracts'}
          className={`${styles.tab} ${tab === 'contracts' ? styles.tabActive : ''}`}
          onClick={() => setTab('contracts')}
        >
          Contracts <span className={styles.tabCount}>{watchedContracts.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'composite'}
          className={`${styles.tab} ${tab === 'composite' ? styles.tabActive : ''}`}
          onClick={() => setTab('composite')}
        >
          Composite Alerts
        </button>
      </div>

      {tab === 'stocks' && (
        <>
          {displayRows.length === 0 ? (
            <div className={styles.empty}>
              <Text size={14} tone="secondary">No stocks in watchlist yet.</Text>
              <Text size={12} tone="dim">
                Star a stock on the Screener → Step 4 to track it here.
              </Text>
            </div>
          ) : (
            <div className={styles.tableWrap}>
              <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
                <span aria-hidden />
                <span aria-hidden />
                <SortBtn label="SYMBOL"     active={sortKey === 'symbol'} dir={sortDir} onClick={() => toggleSort('symbol')} />
                <Text size={11} tone="dim">NAME</Text>
                <SortBtn label="PRICE"      active={sortKey === 'price'}  dir={sortDir} onClick={() => toggleSort('price')}  align="right" />
                <Text size={11} tone="dim">DIR</Text>
                <Text size={11} tone="dim">HORIZON</Text>
                <SortBtn label="SCORE"      active={sortKey === 'score'}  dir={sortDir} onClick={() => toggleSort('score')}  align="right" />
                <SortBtn label="RANK Δ"     active={sortKey === 'rank'}   dir={sortDir} onClick={() => toggleSort('rank')} />
                <SortBtn label="SCORE Δ"    active={sortKey === 'scoreDelta'} dir={sortDir} onClick={() => toggleSort('scoreDelta')} />
                <Text size={11} tone="dim">NEXT EVENT</Text>
              </div>

              <div className={styles.tableBody}>
                {displayRows.map((row) => (
                  <TableRow
                    key={row.symbol}
                    status={row.status}
                    columns={COLUMNS}
                    selected={selected === row.symbol}
                    onClick={() => onSelect(row.symbol, row.company)}
                  >
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={(e) => { e.stopPropagation(); window.open(`/chart?symbol=${row.symbol}`, '_blank'); }}
                    >
                      📈
                    </button>
                    <Data size={13} weight={500}>{row.symbol}</Data>
                    <Text size={12} tone="secondary">{row.company}</Text>
                    <Data size={12} weight={500} className={styles.right}>${row.price.toFixed(2)}</Data>
                    <span className={row.direction === 'Bullish' ? styles.dirBull : styles.dirBear}>
                      {row.direction === 'Bullish' ? 'Bull' : 'Bear'}
                    </span>
                    <Text size={11} tone="secondary">{row.horizon}</Text>
                    <div className={styles.scoreCell}>
                      {/*
                       * ScoreBar (label + track + value, 3-col grid) is designed for the
                       * ContextRail or detail panels.  Embedding it in the 90px score column
                       * would require hiding label & value text and shrinking the track to
                       * ~50px — the result is too cramped to add meaningful visual signal.
                       * The StatusBadge + numeric score already communicate the score quality.
                       */}
                      <Data size={13} weight={500}>{row.score}</Data>
                      <StatusBadge status={row.status} tooltip={GENERIC_STATUS_TOOLTIP[row.status]} />
                    </div>
                    <RankDelta value={row.rankDelta} context="rank" />
                    <RankDelta value={row.scoreDelta ?? 0} context="score pt" />
                    {row.nextEventDays != null
                      ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel ?? undefined} />
                      : <Text size={11} tone="dim">—</Text>}
                  </TableRow>
                ))}
              </div>
            </div>
          )}

          <InlineChartPanel
            open={selected !== null}
            symbol={selected ?? ''}
            companyName={displayRows.find((r) => r.symbol === selected)?.company}
            onClose={() => setSelected(null)}
          />
        </>
      )}

      {tab === 'contracts' && (
        <ContractsTab
          contracts={sortedContracts}
          sortKey={contractSortKey}
          sortDir={contractSortDir}
          onSort={toggleContractSort}
        />
      )}

      {tab === 'composite' && (
        <div className={styles.section}>
          <Title as="h2" size={20}>Composite Alerts</Title>
          <Text size={13} tone="secondary">Markov regime alerts created from the Pre-Breakout scanner.</Text>
          {compositeWatches.length === 0 ? (
            <Text size={13} tone="dim">No composite alerts yet. Create one from the Pre-Breakout Scanner in the Screener.</Text>
          ) : (
            <div className={styles.compositeList}>
              {compositeWatches.map((w) => {
                const primary = (w.trigger_def as Record<string, unknown>)?.primary as Record<string, unknown> | undefined;
                return (
                  <div key={w.id} className={styles.compositeRow}>
                    <div className={styles.compositeInfo}>
                      <Text size={13} weight={500}>{w.symbol}</Text>
                      <Text size={11} tone="secondary">{w.direction} · {(primary?.model as string | undefined) ?? 'OMM'} → {(primary?.to_state as string | undefined) ?? 'any'} · {w.interval}</Text>
                    </div>
                    <div className={styles.compositeActions}>
                      <label className={styles.toggleLabel}>
                        <input
                          type="checkbox"
                          checked={w.enabled}
                          onChange={async (e) => {
                            const enabled = e.target.checked;
                            try {
                              await api.setCompositeWatchEnabled(w.id, enabled);
                              setCompositeWatches((prev) =>
                                prev.map((x) => x.id === w.id ? { ...x, enabled } : x)
                              );
                            } catch { /* ignore */ }
                          }}
                        />
                        <Text size={11} tone="secondary">{w.enabled ? 'Active' : 'Paused'}</Text>
                      </label>
                      <button
                        type="button"
                        className={styles.deleteBtn}
                        onClick={async () => {
                          try {
                            await api.removeCompositeWatch(w.id);
                            setCompositeWatches((prev) => prev.filter((x) => x.id !== w.id));
                          } catch { /* ignore */ }
                        }}
                      >
                        <Text size={11} tone="reject">Remove</Text>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ContractsTab({
  contracts,
  sortKey,
  sortDir,
  onSort,
}: {
  contracts: OptionContract[];
  sortKey: ContractSortKey;
  sortDir: SortDir;
  onSort: (k: ContractSortKey) => void;
}) {
  if (contracts.length === 0) {
    return (
      <div className={styles.empty}>
        <Text size={14} tone="secondary">No starred contracts yet.</Text>
        <Text size={12} tone="dim">
          Star a contract on the Screener → Step 6 to track it here.
        </Text>
      </div>
    );
  }

  return (
    <div className={styles.tableWrap}>
      <div className={styles.tableHeader} style={{ gridTemplateColumns: CONTRACT_COLUMNS }}>
        <span aria-hidden />
        <Text size={11} tone="dim">SYMBOL</Text>
        <Text size={11} tone="dim">CONTRACT</Text>
        <SortBtn label="DTE"   active={sortKey === 'dte'}   dir={sortDir} onClick={() => onSort('dte')} />
        <SortBtn label="PRICE" active={sortKey === 'price'} dir={sortDir} onClick={() => onSort('price')} align="right" />
        <Text size={11} tone="dim" className={styles.right}>DELTA</Text>
        <Text size={11} tone="dim" className={styles.right}>IV RANK</Text>
        <Text size={11} tone="dim" className={styles.right}>Θ/DAY</Text>
        <SortBtn label="SCORE" active={sortKey === 'score'} dir={sortDir} onClick={() => onSort('score')} align="right" />
      </div>

      <div className={styles.tableBody}>
        {contracts.map((c) => {
          const status = c.contractConfidence;
          return (
            <TableRow key={c.id} status={status} columns={CONTRACT_COLUMNS}>
              <ContractStar contractId={c.id} size="sm" />
              <Data size={13} weight={500}>{c.symbol}</Data>
              <Data size={12}>{contractLabel(c)}</Data>
              <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
              <Data size={12} className={styles.right}>${c.price.toFixed(2)}</Data>
              <Data size={12} className={styles.right}>{c.delta.toFixed(2)}</Data>
              <Data size={12} className={styles.right}>{c.ivRank}</Data>
              <Data size={12} className={styles.right}>{c.theta.toFixed(2)}</Data>
              <div className={styles.scoreCell}>
                <Data size={13} weight={500}>{c.score}</Data>
                <StatusBadge status={status} tooltip={contractScoreTooltip(c)} />
              </div>
            </TableRow>
          );
        })}
      </div>
    </div>
  );
}

function SortBtn({
  label,
  active,
  dir,
  onClick,
  align,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: 'left' | 'right';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${styles.sortBtn} ${align === 'right' ? styles.sortRight : ''} ${active ? styles.sortActive : ''}`}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  );
}

function timeAgoLabel(d: Date): string {
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return 'just now';
  return `${Math.floor(diff / 60_000)} min ago`;
}
