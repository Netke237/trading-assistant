'use client';

/*
 * Watchlist — Phase 5.
 * Tabs:
 *   - Stocks:    sortable table of ranked candidates + inline chart on select.
 *   - Contracts: every option contract the user has starred on Step 6.
 */

import { useEffect, useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { WatchStar } from '@/components/atoms/WatchStar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { statusForScore } from '@/lib/status';
import { api } from '@/lib/api';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { contractLabel, type OptionContract } from '@/types/domain';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import type { WatchlistRow } from '@/types/domain';
import styles from './page.module.css';

type Tab     = 'stocks' | 'contracts';
type SortKey = 'score' | 'symbol' | 'price' | 'rank' | 'scoreDelta';
type SortDir = 'asc' | 'desc';
type ContractSortKey = 'score' | 'dte' | 'price';

const COLUMNS          = '32px 72px 1.4fr 90px 80px 80px 90px 80px 60px 90px';
const CONTRACT_COLUMNS = '28px 72px 1.3fr 120px 80px 72px 80px 80px 100px';

export default function WatchlistPage() {
  const [tab, setTab]         = useState<Tab>('stocks');
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<string | null>(null);
  const [contractSortKey, setContractSortKey] = useState<ContractSortKey>('score');
  const [contractSortDir, setContractSortDir] = useState<SortDir>('desc');
  const [watchlist, setWatchlist]   = useState<WatchlistRow[]>([]);
  const [contracts, setContracts]   = useState<OptionContract[]>([]);
  const [offline, setOffline]       = useState(false);

  const watchedSymbols = useWatchlistStore((s) => s.added);

  useEffect(() => {
    api.getWatchlist().then(setWatchlist).catch(() => setOffline(true));
    api.getContracts().then(setContracts).catch(() => setOffline(true));
  }, []);

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

  const watchedSet = useMemo(
    () => new Set(watchedSymbols.map((s) => s.toUpperCase())),
    [watchedSymbols],
  );

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
    const filtered = sorted.filter((r) => watchedSet.has(r.symbol.toUpperCase()));
    return filtered.length > 0 ? filtered : offlineRows;
  }, [offline, offlineRows, sorted, watchedSet]);

  const watchedIds = useWatchedContractsStore((s) => s.ids);
  const watchedContracts = useMemo<OptionContract[]>(
    () => {
      const idx = Object.fromEntries(contracts.map((c) => [c.id, c]));
      return watchedIds.map((id) => idx[id]).filter((c): c is OptionContract => !!c);
    },
    [contracts, watchedIds],
  );

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

  const onSelect = (symbol: string) => {
    setSelected((cur) => (cur === symbol ? null : symbol));
  };

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Watchlist</Title>
        <Text size={13} tone="secondary">
          {tab === 'stocks'
            ? `${displayRows.length} starred · sorted by ${sortKey} ${sortDir === 'asc' ? '↑' : '↓'}`
            : `${sortedContracts.length} starred contract${sortedContracts.length === 1 ? '' : 's'} · sorted by ${contractSortKey} ${contractSortDir === 'asc' ? '↑' : '↓'}`}
        </Text>
        {offline && (
          <Text size={13} tone="dim">Backend not running — start start-backend.bat to load live data.</Text>
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
      </div>

      {tab === 'stocks' ? (
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
                    onClick={() => onSelect(row.symbol)}
                  >
                    <WatchStar symbol={row.symbol} size="sm" />
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
                      <StatusBadge status={row.status} />
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
            onClose={() => setSelected(null)}
          />
        </>
      ) : (
        <ContractsTab
          contracts={sortedContracts}
          sortKey={contractSortKey}
          sortDir={contractSortDir}
          onSort={toggleContractSort}
        />
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
          const status = statusForScore(c.score);
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
                <StatusBadge status={status} />
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
