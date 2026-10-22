'use client';

/*
 * Watchlist — Phase 5.
 * Tabs:
 *   - Stocks:    sortable table of ranked candidates + inline chart on select.
 *   - Contracts: every option contract the user has starred on Step 6, graded
 *                with the inputs Step 6 used when it was starred
 *                (WATCHLIST-SCAN-CONTRACT-RULES). Every star is a row: live, or
 *                Loading / Expired / Not in the current chain / Could not load
 *                the chain / Unreadable contract id.
 *   - Composite Alerts: Markov regime alerts created from the Pre-Breakout scanner.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { NoLiveQuoteTag } from '@/components/atoms/NoLiveQuoteTag';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { WatchStar } from '@/components/atoms/WatchStar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { GENERIC_STATUS_TOOLTIP, contractScoreTooltip } from '@/lib/statusTooltips';
import { resolveIv, formatIv, ivColumnLabel, ivBasesOf } from '@/lib/ivBasis';
import { api, type CompositeWatch } from '@/lib/api';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { contractLabel, type OptionContract } from '@/types/domain';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import {
  planContractGroups, resolveWatchedRows, compareWatchedRows, rowId, localTodayIso,
  MISSING_NOTE, INVALID_NOTE, YAML_MARKER,
  type ContractSortKey, type KeptGroupResult, type WatchedContractRow,
} from '@/lib/contractGrading';
import type { WatchlistRow } from '@/types/domain';
import { useChartStore } from '@/lib/chartStore';
import { useWatchlistUiStore } from '@/lib/watchlistUiStore';
import styles from './page.module.css';

type Tab     = 'stocks' | 'contracts' | 'composite';
type SortKey = 'score' | 'symbol' | 'price' | 'rank' | 'scoreDelta';
type SortDir = 'asc' | 'desc';

// Type only (erased): every runtime helper lives in lib/contractGrading.ts.
export type { WatchedContractRow };

const COLUMNS          = '32px 28px 72px 1.4fr 90px 80px 80px 90px 80px 60px 90px';
const CONTRACT_COLUMNS = '28px 72px 1.3fr 120px 80px 72px 80px 80px 100px';

/** IV cell for the watchlist Contracts tab — percentile when one exists,
 *  otherwise the absolute implied volatility, labelled as such
 *  (PHASE-A-NULL-IVRANK-2026-09-06). */
function IvContractCell({ contract }: { contract: OptionContract }) {
  const shown = formatIv(resolveIv(contract), contract.symbol);
  return (
    <Data size={12} className={styles.right} title={shown.title}>
      {shown.text}
      {shown.suffix !== '' && <Text size={10} tone="dim">{` ${shown.suffix}`}</Text>}
    </Data>
  );
}

export default function WatchlistPage() {
  const [tab, setTab]         = useState<Tab>('stocks');
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<string | null>(null);
  const [contractSortKey, setContractSortKey] = useState<ContractSortKey>('score');
  const [contractSortDir, setContractSortDir] = useState<SortDir>('desc');
  const [watchlist, setWatchlist]             = useState<WatchlistRow[]>([]);
  // Settled per-group results, replaced atomically when a non-aborted refresh
  // settles; kept on screen while a refresh is in flight.
  const [kept, setKept]                       = useState<KeptGroupResult[]>([]);
  // The local date the rows are classified against (set by each refresh).
  const [today, setToday]                     = useState<string>(() => localTodayIso());
  // The Stocks tab's flag. The Contracts tab has its own, so a success on one
  // tab can no longer hide a failure on the other.
  const [offline, setOffline]                 = useState(false);
  const [contractsOffline, setContractsOffline] = useState(false);
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
  const grading    = useWatchedContractsStore((s) => s.grading);

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
    // Abort any in-flight contracts fetch before anything else (CRITICAL-3 fix),
    // including on the early returns: a slow fetch rejecting after the last
    // unstar is then discarded as aborted and cannot raise the banner.
    contractsAbortRef.current?.abort();
    const t = localTodayIso();
    setToday(t);
    const plan = planContractGroups(watchedIds, grading, t);
    if (plan.groups.length === 0) {
      // No stars, or every star expired / unreadable: nothing to fetch.
      setKept([]);
      setContractsOffline(false);
      setRefreshingContracts(false);
      return;
    }
    const controller = new AbortController();
    contractsAbortRef.current = controller;
    setRefreshingContracts(true);
    try {
      // One request per (symbol, right, expiry, grading): the star's own expiry
      // and strikes, graded with the inputs it was starred with. `strikes`
      // disables `limit` and `max_price` server-side.
      const settled = await Promise.allSettled(plan.groups.map((g) =>
        api.getContracts(g.symbol, g.right, { expiry: g.expiry, strikes: g.strikes, ...g.ctx }, controller.signal)));
      if (controller.signal.aborted) return;
      setKept(plan.groups.map((g, i): KeptGroupResult => {
        const r = settled[i]!;
        return { groupKey: g.key, strikes: new Set(g.strikes), outcome: r.status === 'fulfilled' ? r.value : 'rejected' };
      }));
      // Partial failures show per-row "Could not load the chain"; the banner
      // only when every fetched group failed.
      setContractsOffline(settled.every((r) => r.status === 'rejected'));
    } finally {
      if (!controller.signal.aborted) setRefreshingContracts(false);
    }
  }, [watchedIds, grading]);

  useEffect(() => {
    syncFromBackend();
    syncContractsFromBackend();
    refreshWatchlist();
    refreshComposite();
  }, [syncFromBackend, syncContractsFromBackend, refreshWatchlist, refreshComposite]);

  useEffect(() => {
    refreshContracts();
    return () => {
      contractsAbortRef.current?.abort();
    };
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

  const contractPlan = useMemo(
    () => planContractGroups(watchedIds, grading, today),
    [watchedIds, grading, today],
  );

  const watchedContracts = useMemo<WatchedContractRow[]>(
    () => resolveWatchedRows(contractPlan, kept, grading),
    [contractPlan, kept, grading],
  );

  const sortedContracts = useMemo<WatchedContractRow[]>(() => {
    const order = new Map(contractPlan.ids.map((id, i) => [id, i] as const));
    return [...watchedContracts].sort((a, b) =>
      compareWatchedRows(a, b, contractSortKey, contractSortDir, order));
  }, [watchedContracts, contractPlan, contractSortKey, contractSortDir]);

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
        {tab === 'stocks' && offline ? (
          <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
        ) : tab === 'contracts' && contractsOffline ? (
          <Text size={13} tone="dim">Could not load option chains — retry</Text>
        ) : null}
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
  contracts: WatchedContractRow[];
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

  const live = contracts.flatMap((r) => (r.kind === 'live' ? [r.contract] : []));

  return (
    <div className={styles.tableWrap}>
      <div className={styles.tableHeader} style={{ gridTemplateColumns: CONTRACT_COLUMNS }}>
        <span aria-hidden />
        <Text size={11} tone="dim">SYMBOL</Text>
        <Text size={11} tone="dim">CONTRACT</Text>
        <SortBtn label="DTE"   active={sortKey === 'dte'}   dir={sortDir} onClick={() => onSort('dte')} />
        <SortBtn label="PRICE" active={sortKey === 'price'} dir={sortDir} onClick={() => onSort('price')} align="right" />
        <Text size={11} tone="dim" className={styles.right}>DELTA</Text>
        <Text size={11} tone="dim" className={styles.right}>{ivColumnLabel(ivBasesOf(live))}</Text>
        <Text size={11} tone="dim" className={styles.right}>Θ/DAY</Text>
        <SortBtn label="SCORE" active={sortKey === 'score'} dir={sortDir} onClick={() => onSort('score')} align="right" />
      </div>

      <div className={styles.tableBody}>
        {contracts.map((row) => (row.kind === 'live'
          ? <LiveContractRow key={rowId(row)} contract={row.contract} yamlGraded={row.yamlGraded} />
          : <MissingContractRow key={rowId(row)} row={row} />))}
      </div>
    </div>
  );
}

function LiveContractRow({ contract: c, yamlGraded }: { contract: OptionContract; yamlGraded: boolean }) {
  const status = c.contractConfidence;
  return (
    <TableRow status={status} columns={CONTRACT_COLUMNS}>
      <ContractStar contractId={c.id} size="sm" />
      <Data size={13} weight={500}>{c.symbol}</Data>
      <div>
        <Data size={12}>{contractLabel(c)}</Data>
        {yamlGraded && <div><Text size={10} tone="caution">{YAML_MARKER}</Text></div>}
      </div>
      <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
      <Data size={12} className={styles.right}>${c.price.toFixed(2)}</Data>
      <Data size={12} className={styles.right}>{c.delta.toFixed(2)}</Data>
      <IvContractCell contract={c} />
      <Data size={12} className={styles.right}>{c.theta.toFixed(2)}</Data>
      <div className={styles.scoreCell}>
        <Data size={13} weight={500}>{c.score}</Data>
        <StatusBadge status={status} tooltip={contractScoreTooltip(c)} />
                    <NoLiveQuoteTag noLiveQuote={c.noLiveQuote} quoteState={c.quoteState} />
      </div>
    </TableRow>
  );
}

/** A star with no live row: still listed, with why, and a working unstar. */
function MissingContractRow({ row }: { row: Exclude<WatchedContractRow, { kind: 'live' }> }) {
  const note   = row.kind === 'invalid' ? INVALID_NOTE : MISSING_NOTE[row.reason];
  const status = row.kind === 'missing' && row.reason === 'loading' ? 'PENDING' : 'NO_DATA';
  const label  = row.kind === 'invalid'
    ? row.id
    : contractLabel({ symbol: row.symbol, strike: row.strike, right: row.right, expiry: row.expiry });
  const dash = <Text size={12} tone="dim" className={styles.right}>—</Text>;
  return (
    <TableRow status={status} columns={CONTRACT_COLUMNS}>
      <ContractStar contractId={row.id} size="sm" />
      {row.kind === 'invalid' ? <Text size={13} tone="dim">—</Text> : <Data size={13} weight={500}>{row.symbol}</Data>}
      <div title={note}>
        <Data size={12}>{label}</Data>
        <div><Text size={10} tone="dim">{note}</Text></div>
      </div>
      <Text size={12} tone="dim">—</Text>
      {dash}
      {dash}
      {dash}
      {dash}
      {dash}
    </TableRow>
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
