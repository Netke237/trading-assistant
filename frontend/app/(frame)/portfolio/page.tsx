'use client';

/*
 * Portfolio — open positions, synced from the backend every 30 s, with a
 * totals footer, an editor drawer per row (pencil), a close dialog, and a
 * History tab of closed trades with the realized P&L views.
 */

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import Link from 'next/link';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { BrokerAttemptPanel } from '@/components/organisms/BrokerAttemptPanel';
import { ClosePositionDrawer } from '@/components/organisms/ClosePositionDrawer';
import { exitReasonLabel, type ExitReason } from '@/lib/exitReason';
import { PnlChart } from '@/components/organisms/PnlChart';
import { PnlHeatmap } from '@/components/organisms/PnlHeatmap';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { usePortfolioCycle } from '@/lib/usePortfolioCycle';
import { useClientClock } from '@/lib/useClientNow';
import { syncStatusView, positionsLoadState } from '@/lib/syncStatus';
import { hhmmss } from '@/lib/configHealth';
import { staleCurveNotice } from '@/lib/staleCurve';
import { toHistoryCsv } from '@/lib/portfolioHistory';
import { positionStatusTooltip } from '@/lib/statusTooltips';
import { derivePositionStatus } from '@/lib/positionStatus';
import { positionRange } from '@/lib/positionRange';
import { riskAtStopOf } from '@/lib/risk';
import type { PortfolioPosition } from '@/types/domain';
import { resolveIv, formatIv, ivColumnLabel, ivBasesOf, type IvBasis } from '@/lib/ivBasis';
import styles from './page.module.css';
import { EditDrawer } from './EditDrawer';
import { isPartialSave, rejectionMessage } from '@/lib/portfolioRejection';
import { premiumStopDropText } from '@/lib/premiumStop';
import { openTotals, unquotedNote, aggregateGreeks, positionThetaDollars, riskAtStopTotal } from '@/lib/portfolioTotals';
import { formatMoney, formatSignedPct, readableContract, moneyTone, MINUS } from '@/lib/portfolioFormat';
import {
  computeTradeStats, filterTrades, sortTrades, exitCheck, stopPctFor, holdDays, returnPct, tradeLabel,
  type TradeFilter, type SortKey, type SortDir,
} from '@/lib/tradeStats';
import { TradeStatsStrip, stopTooltip, rowStopTooltip } from './TradeStatsStrip';

/** `−5.2%` / `+9.6%`, one decimal, Unicode minus. */
function formatBreachPct(v: number): string {
  const s = Math.abs(v).toFixed(1);
  return Number(v.toFixed(1)) < 0 ? `${MINUS}${s}%` : `+${s}%`;
}

// Existing columns first; RETURN, HOLD, EXIT CHECK, EXIT REASON sit between P&L and the remove button.
// Keep in step with `.historyRow` in page.module.css.
const HISTORY_COLUMNS = '64px 1.6fr 1fr 168px 80px 72px 56px 1.3fr 1fr 56px';

/** Tone for the resolved volatility figure. The bands are the same numbers on
 *  both bases today — 70 is `max_iv_abs`/`max_iv_rank` in contract_rules.yaml,
 *  which are seeded equal — so one function serves both, but it takes the
 *  basis so the split stays visible if those ever diverge
 *  (PHASE-A-NULL-IVRANK-2026-09-06). */
function ivTone(value: number | null, _basis: IvBasis): 'pass' | 'caution' | 'reject' | undefined {
  if (value == null) return undefined;
  // ROUND 5 finding 13. 70 is the hard ceiling (max_iv_abs / max_iv_rank), but
  // 40 corresponded to NOTHING in config -- preferred_iv_*_max is 55 -- so this
  // column tinted a 45% IV "caution" on a position the scorer calls PASS. 55 is
  // the preferred ceiling the contract scorer actually uses.
  if (value >= 70) return 'reject';      // above the hard ceiling
  if (value >= 55) return 'caution';     // above preferred_iv_*_max
  return 'pass';
}

/** IV cell for one open position. A percentile when a rank source answered,
 *  otherwise the absolute implied volatility, labelled as such — this column
 *  showed an absolute level under the heading "IV RK" before the split
 *  (PHASE-A-NULL-IVRANK-2026-09-06). */
function IvPositionCell({ position }: { position: PortfolioPosition }) {
  const iv = resolveIv(position);
  const shown = formatIv(iv, position.symbol);
  return (
    <Data size={12} className={styles.right} tone={ivTone(iv.value, iv.basis)} title={shown.title}>
      {shown.text}
      {shown.suffix !== '' && <Text size={10} tone="dim">{` ${shown.suffix}`}</Text>}
    </Data>
  );
}

// chart, symbol + contract, DIR, DTE, entry -> now, P&L, IV, Δ · Θ, range, risk, status, edit
const COLUMNS = '28px minmax(150px, 1.4fr) 56px minmax(80px, 1fr) 110px 104px 60px 112px minmax(210px, 1.6fr) 84px 150px 40px';

const RISK_NEEDS_PLAN = 'Needs a computed exit plan (options only)';
const RISK_STOCK = 'Risk at stop is computed for options only';

/** Underlying vs stop / T1: a bar from the low price (left) to the high price
 *  (right), a tick for the structural stop, a marker for the live underlying,
 *  and the same facts as text so colour is never the only cue. Without a T1 the
 *  bar has no right end. */
function RangeCell({ position }: { position: PortfolioPosition }) {
  const r = positionRange(position);
  if (!r) {
    return (
      <Data size={12} title="Needs an underlying price and a stop">—</Data>
    );
  }
  const low = r.t1 != null ? Math.min(r.stop, r.t1) : null;
  const high = r.t1 != null ? Math.max(r.stop, r.t1) : null;
  const at = (level: number) => (low != null && high != null && high > low
    ? Math.min(1, Math.max(0, (level - low) / (high - low))) * 100
    : null);
  const structAt = r.structural != null ? at(r.structural) : null;
  return (
    <div className={styles.rangeCell}>
      <div
        className={r.t1 == null ? styles.rangeBarOpen : styles.rangeBar}
        role="img"
        aria-label={r.text}
      >
        {structAt != null && <span className={styles.rangeStruct} style={{ left: `${structAt}%` }} />}
        {r.fraction != null && (
          <span
            className={r.pinned ? styles.rangeMarkerPinned : styles.rangeMarker}
            style={{ left: `${r.fraction * 100}%` }}
          />
        )}
      </div>
      <Text size={10} tone="secondary">{r.text}</Text>
    </div>
  );
}

function downloadCsv(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 100);
}

export default function PortfolioPage() {
  const positions      = usePortfolioStore((s) => s.positions);
  const lastSyncError  = usePortfolioStore((s) => s.lastSyncError);
  // ROUND 9 — the offline retry's channel for the "stop could not be applied"
  // notice; the three foreground create paths report it at the point of sale.
  const lastPremiumStopDropped = usePortfolioStore((s) => s.lastPremiumStopDropped);
  // ROUND 10 finding 14 — its OWN dismiss. Sharing `clearSyncError` meant
  // closing this informational notice also wiped the rejection banner above it.
  const clearPremiumStopDropped = usePortfolioStore((s) => s.clearPremiumStopDropped);
  const clearSyncError = usePortfolioStore((s) => s.clearSyncError);
  const lastSyncAt = usePortfolioStore((s) => s.lastSyncAt);
  const lastSyncFailedAt = usePortfolioStore((s) => s.lastSyncFailedAt);
  const firstSyncAt = usePortfolioStore((s) => s.firstSyncAt);
  const updatePosition = usePortfolioStore((s) => s.updatePosition);
  const premiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  const [editing, setEditing] = useState<string | null>(null);
  const setSelectedSymbol = usePortfolioUiStore((s) => s.setSelectedSymbol);
  const [tab, setTab] = useState<'open' | 'history'>('open');
  const [closing, setClosing] = useState<string | null>(null); // contract being closed
  const [closeError, setCloseError] = useState<string | null>(null);
  const closeRemote = usePortfolioStore((s) => s.closePositionRemote);
  const history = usePerformanceStore((s) => s.history);
  const performance = usePerformanceStore((s) => s.performance);
  const fetchHistory = usePerformanceStore((s) => s.fetchHistory);
  const fetchPerformance = usePerformanceStore((s) => s.fetchPerformance);
  const performanceFetchedAt = usePerformanceStore((s) => s.fetchedAt);
  const syncStatus = syncStatusView({ lastSyncAt, lastSyncFailedAt, firstSyncAt });
  const loadState = positionsLoadState(positions.length, lastSyncAt, lastSyncFailedAt);
  const removeHistory = usePerformanceStore((s) => s.removeHistory);
  const clearAllHistory = usePerformanceStore((s) => s.clearAllHistory);
  const [clearConfirm, setClearConfirm] = useState(false);
  const [removePending, setRemovePending] = useState<string | null>(null);
  const [removeFailed, setRemoveFailed] = useState(false);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [histFilter, setHistFilter] = useState<TradeFilter>('all');
  const [histQuery, setHistQuery] = useState('');
  const [histSort, setHistSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);
  // Stats follow the filter (never the sort); the list is the filtered rows, sorted.
  const filteredHistory = useMemo(() => filterTrades(history, histFilter, histQuery), [history, histFilter, histQuery]);
  const historyStats = useMemo(() => computeTradeStats(filteredHistory, premiumStopPct), [filteredHistory, premiumStopPct]);
  const sortedHistory = useMemo(
    () => sortTrades(filteredHistory, histSort?.key ?? null, histSort?.dir ?? 'asc'),
    [filteredHistory, histSort],
  );
  // The remove confirm closes when its row leaves history or the visible list
  // (filter, search, tab change), so it can never act on a row the user cannot see.
  const pendingRow = removePending === null ? null : sortedHistory.find((h) => h.id === removePending) ?? null;
  useEffect(() => {
    if (removePending !== null && pendingRow === null) { setRemovePending(null); setRemoveFailed(false); }
  }, [removePending, pendingRow]);
  async function confirmRemove(id: string) {
    setRemoveBusy(true);
    try {
      const ok = await removeHistory(id);
      if (ok) {
        await fetchPerformance();
        setRemovePending(null);
        setRemoveFailed(false);
      } else {
        setRemoveFailed(true);
      }
    } finally {
      setRemoveBusy(false);
    }
  }
  // asc -> desc -> off (API order).
  const cycleSort = (key: SortKey) => setHistSort((cur) => {
    if (cur === null || cur.key !== key) return { key, dir: 'asc' };
    return cur.dir === 'asc' ? { key, dir: 'desc' } : null;
  });
  const ariaSort = (...keys: SortKey[]): 'ascending' | 'descending' | 'none' =>
    histSort !== null && keys.includes(histSort.key) ? (histSort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
  const sortBtn = (key: SortKey, label: string) => (
    <button type="button" className={styles.sortBtn} onClick={() => cycleSort(key)}>
      {label}
      <span aria-hidden className={styles.sortMark}>
        {histSort?.key === key ? (histSort.dir === 'asc' ? '▲' : '▼') : ''}
      </span>
    </button>
  );

  // 30 s cycle (sync -> alert scan -> performance), paused while the tab is
  // hidden; see lib/usePortfolioCycle.ts.
  const { now, refreshNow } = useClientClock();
  usePortfolioCycle(refreshNow);
  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Clear the sidebar's selected-symbol note when leaving this page, so a
  // stale selection doesn't linger for the next visit.
  useEffect(() => {
    return () => setSelectedSymbol(null);
  }, [setSelectedSymbol]);

  // A row with no quote carries 0 defaults, not a price: the totals leave it
  // out and say so, rather than adding a silent 0 (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, openPnLPct, winners, losers, unquoted } = openTotals(positions);
  // Stale-curve notices (Open P&L and Total value only). `ready`: a performance
  // request was ISSUED at or after the first successful sync, so the curve is
  // not older than that sync's snapshot write. `now` is effect-set (hydration).
  const staleReady = firstSyncAt !== null && performanceFetchedAt !== null && performanceFetchedAt >= firstSyncAt;
  const unquotedSymbols = Array.from(new Set(positions.filter((p) => p.quoteUnavailable === true).map((p) => p.symbol)));
  const staleFor = (kind: 'open' | 'equity') => now === null ? null : staleCurveNotice({
    kind,
    lastSnapshotDate: performance.lastSnapshotDate,
    curve: kind === 'open' ? performance.openPnlCurve : performance.equityCurve,
    positionsCount: positions.length,
    openPnlToday: openPnL,
    unquotedSymbols,
    skippedContracts: performance.snapshotSkippedContracts,
    now,
    ready: staleReady,
  });
  const staleNotices = { open: staleFor('open'), equity: staleFor('equity') };
  const { thetaDollars } = aggregateGreeks(positions);
  const riskTotal = riskAtStopTotal(positions);

  // Stop-breach banners, derived each render: one per row whose derived breach
  // is the underlying stop or the structural stop. breachPct is
  // (underlying - level) / underlying, the OPPOSITE sign of positionRange.stopPct.
  const breachBanners = positions.flatMap((p) => {
    const { breach } = derivePositionStatus(p, { premiumStopPct });
    if (breach !== 'stop' && breach !== 'structural') return [];
    const underlying = p.contract.endsWith('|STOCK') ? p.currentPrice : (p.currentStockPrice ?? 0);
    const level = breach === 'stop' ? p.stop : p.structuralStop;
    if (level == null || !(underlying > 0)) return [];
    const pct = ((underlying - level) / underlying) * 100;
    const label = breach === 'stop' ? 'stop' : 'structural stop';
    const text =
      `${p.symbol} ${readableContract(p.contract)}: ${label} breached. ` +
      `Underlying ${formatMoney(underlying, { decimals: 2 })} is ${p.direction === 'Bearish' ? 'above' : 'below'} ` +
      `your ${label} ${formatMoney(level, { decimals: 2 })} (${formatBreachPct(pct)}).` +
      (p.quoteUnavailable === true && !p.contract.endsWith('|STOCK')
        ? ' The option has had no quote since the last sync, so its P&L and risk are unknown.'
        : '');
    return [{ contract: p.contract, symbol: p.symbol, text }];
  });

  // Clock-derived labels come from effect-set state only: on the server pass
  // and the first client render `now` is null and no period text is rendered,
  // so server HTML and the first hydrated render agree (React #418).
  const fmtDay = (d: Date) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
  let todayLabel: string | undefined;
  let weekLabel: string | undefined;
  let monthLabel: string | undefined;
  let yearLabel: string | undefined;
  if (now) {
    todayLabel = fmtDay(now);
    // Calendar week (Mon–Sun) containing today — matches the backend's week bucket.
    const mondayOffset = (now.getDay() + 6) % 7;
    const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset);
    const weekEnd = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + 6);
    weekLabel = `${fmtDay(weekStart)} – ${fmtDay(weekEnd)}`;
    monthLabel = now.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    yearLabel = String(now.getFullYear());
  }

  const TABS = ['open', 'history'] as const;
  const tabRefs = useRef<Record<'open' | 'history', HTMLButtonElement | null>>({ open: null, history: null });
  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = TABS.indexOf(tab);
    let next: 'open' | 'history' | null = null;
    if (e.key === 'ArrowRight') next = TABS[(i + 1) % TABS.length];
    else if (e.key === 'ArrowLeft') next = TABS[(i + TABS.length - 1) % TABS.length];
    else if (e.key === 'Home') next = TABS[0];
    else if (e.key === 'End') next = TABS[TABS.length - 1];
    if (next === null) return;
    e.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  };

  const confirmClose = async (p: PortfolioPosition, opts: { qtyToClose: number; exitPrice: number; exitDate: string; exitReason: ExitReason }) => {
    setCloseError(null);
    const { ok, detail } = await closeRemote(p.recId, opts);
    if (ok) {
      setClosing(null);
      fetchHistory();
      fetchPerformance();
    } else {
      setCloseError(detail ?? 'Failed to close position.');
    }
  };

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Portfolio</Title>
        <Text size={13} tone="secondary">{positions.length} open positions</Text>
      </div>
      {syncStatus.kind === 'failed-with-prior' || syncStatus.kind === 'failed-no-prior' ? (
        <div role="status" className={styles.syncStatus}>
          <Text size={11} tone="caution">{syncStatus.text}</Text>
        </div>
      ) : (
        <div className={styles.syncStatus}>
          <Text size={11} tone={syncStatus.kind === 'syncing' ? 'dim' : 'secondary'}>{syncStatus.text}</Text>
        </div>
      )}

      <BrokerAttemptPanel />

      {lastSyncError && (
        <div role="alert" className={styles.syncErrorBanner}>
          <Text size={13} tone="reject">
            {isPartialSave(lastSyncError.detail)
              ? `${lastSyncError.symbol}: some changes were not saved:`
              : `${lastSyncError.symbol} was not saved:`}{' '}
            {rejectionMessage(lastSyncError.detail)}
          </Text>
          <button type="button" className={styles.syncErrorDismiss} onClick={clearSyncError} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      {lastPremiumStopDropped && (
        <div role="alert" className={styles.syncErrorBanner}>
          <Text size={13} tone="caution">
            {`${lastPremiumStopDropped.symbol}: ${premiumStopDropText(
              lastPremiumStopDropped.requestedDollar, lastPremiumStopDropped.reason,
              lastPremiumStopDropped.keptPct)}`}
          </Text>
          <button type="button" className={styles.syncErrorDismiss} onClick={clearPremiumStopDropped} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      {breachBanners.map((b) => (
        <div key={b.contract} role="alert" className={styles.breachBanner}>
          <Text size={13} tone="reject">{b.text}</Text>
          <div className={styles.breachActions}>
            <button
              type="button"
              className={styles.breachBtn}
              onClick={() => { setTab('open'); setEditing(b.contract); setSelectedSymbol(b.symbol); }}
            >
              {`Review ${b.symbol}`}
            </button>
            <button type="button" className={styles.breachBtn} onClick={() => setClosing(b.contract)}>
              Close position…
            </button>
          </div>
        </div>
      ))}

      <div className={styles.tabs} role="tablist" aria-label="Portfolio views">
        <button
          type="button" role="tab" id="portfolio-tab-open" aria-controls="portfolio-panel-open"
          aria-selected={tab === 'open'} tabIndex={tab === 'open' ? 0 : -1}
          ref={(el) => { tabRefs.current.open = el; }}
          className={tab === 'open' ? styles.tabActive : styles.tab}
          onClick={() => setTab('open')} onKeyDown={onTabKeyDown}
        >
          Open ({positions.length})
        </button>
        <button
          type="button" role="tab" id="portfolio-tab-history" aria-controls="portfolio-panel-history"
          aria-selected={tab === 'history'} tabIndex={tab === 'history' ? 0 : -1}
          ref={(el) => { tabRefs.current.history = el; }}
          className={tab === 'history' ? styles.tabActive : styles.tab}
          onClick={() => setTab('history')} onKeyDown={onTabKeyDown}
        >
          History ({history.length})
        </button>
      </div>

      <div className={styles.perfStrip}>
        <PerfStat label="Realized today"      value={performance.realizedToday} period={todayLabel} />
        <PerfStat label="Realized this week"  value={performance.realizedWeek}  period={weekLabel} />
        <PerfStat label="Realized this month" value={performance.realizedMonth} period={monthLabel} />
        <PerfStat label="Realized this year"  value={performance.realizedYear}  period={yearLabel} />
      </div>

      {tab === 'history' && (
        <div role="tabpanel" id="portfolio-panel-history" aria-labelledby="portfolio-tab-history" className={styles.panel}>
        {/* 1. Trade statistics, then the equity curve — both sit above the trade list */}
        <TradeStatsStrip stats={historyStats} stopPct={premiumStopPct} />
        <div className={styles.perfViews}>
          <PnlChart
            equityCurve={performance.equityCurve}
            realizedCurve={performance.realizedCurve}
            defaultKind="realized"
            staleNotices={staleNotices}
          />
        </div>

        {/* 2. Toolbar + closed-trade list */}
        <div className={styles.historyToolbar}>
          <Text size={12} tone="secondary">{history.length} closed trades</Text>
          <div className={styles.toolbarActions}>
            {clearConfirm ? (
              <>
                <Text size={12} tone="reject">Delete all {history.length} records?</Text>
                <button
                  type="button"
                  className={styles.clearConfirmBtn}
                  onClick={async () => {
                    await clearAllHistory();
                    fetchPerformance();
                    setClearConfirm(false);
                  }}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  className={styles.downloadBtn}
                  onClick={() => setClearConfirm(false)}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                className={styles.clearBtn}
                onClick={() => setClearConfirm(true)}
                disabled={history.length === 0}
                aria-label="Clear all trade history"
              >
                Clear all
              </button>
            )}
            <button
              type="button"
              className={styles.downloadBtn}
              onClick={() => downloadCsv('trade-history.csv', toHistoryCsv(history))}
              disabled={history.length === 0}
              aria-label="Download closed trade history as CSV"
            >
              Download CSV
            </button>
          </div>
        </div>
        {history.length > 0 && (
          <div className={styles.historyFilterBar}>
            <div role="group" aria-label="Filter trades" className={styles.filterGroup}>
              {(['all', 'wins', 'losses'] as const).map((f) => (
                <button
                  key={f} type="button" aria-pressed={histFilter === f}
                  className={histFilter === f ? styles.filterBtnActive : styles.filterBtn}
                  onClick={() => setHistFilter(f)}
                >
                  {f === 'all' ? 'All' : f === 'wins' ? 'Wins' : 'Losses'}
                </button>
              ))}
            </div>
            <input
              type="text" className={styles.filterSearch} placeholder="Symbol"
              aria-label="Search symbol" value={histQuery}
              onChange={(e) => setHistQuery(e.target.value)}
            />
            <Text size={12} tone="secondary">{`Showing ${filteredHistory.length} of ${history.length}`}</Text>
          </div>
        )}
        {pendingRow && (
          <div role="alertdialog" aria-label="Confirm remove trade" className={styles.removeConfirm} data-testid="history-remove-confirm">
            <Text size={12} tone="reject">{`Remove ${tradeLabel(pendingRow)} from history? This changes realized totals.`}</Text>
            <button type="button" className={styles.clearConfirmBtn} disabled={removeBusy} onClick={() => confirmRemove(pendingRow.id)}>Confirm</button>
            <button type="button" className={styles.downloadBtn} disabled={removeBusy} onClick={() => { setRemovePending(null); setRemoveFailed(false); }}>Cancel</button>
            {removeFailed && <Text size={12} tone="reject">Could not remove the trade — it is still in your history.</Text>}
          </div>
        )}
        <div className={styles.historyWrap}>
          {history.length === 0 ? (
            <Text size={13} tone="secondary">No closed trades yet.</Text>
          ) : (
          <>
          <div className={styles.historyHeader} role="row" data-testid="history-header" style={{ gridTemplateColumns: HISTORY_COLUMNS }}>
            <div role="columnheader" aria-sort={ariaSort('symbol')}>{sortBtn('symbol', 'SYMBOL')}</div>
            <Text size={11} tone="dim">CONTRACT</Text>
            <Text size={11} tone="dim">QTY · ENTRY → EXIT</Text>
            <div role="columnheader" aria-sort={ariaSort('entry', 'exit')} className={styles.datesHeader}>
              {sortBtn('entry', 'ENTRY')}
              {sortBtn('exit', 'EXIT')}
            </div>
            <div role="columnheader" aria-sort={ariaSort('pnl')}>{sortBtn('pnl', 'P&L')}</div>
            <div role="columnheader" aria-sort={ariaSort('return')}>{sortBtn('return', 'RETURN')}</div>
            <div role="columnheader" aria-sort={ariaSort('hold')}>{sortBtn('hold', 'HOLD')}</div>
            <span title={stopTooltip(premiumStopPct)} data-testid="history-exitcheck-header">
              <Text size={11} tone="dim">EXIT CHECK</Text>
            </span>
            <Text size={11} tone="dim">EXIT REASON</Text>
            <span aria-hidden />
          </div>
          {sortedHistory.length === 0 && (
            <Text size={13} tone="secondary">No trades match this filter.</Text>
          )}
          {sortedHistory.map((h) => {
            const ret = returnPct(h);
            const hd = holdDays(h);
            const stop = stopPctFor(h, premiumStopPct);
            const ec = exitCheck(h, stop.pct);
            return (
            <div key={h.id} className={styles.historyRow} data-testid="history-row">
              <span data-testid="history-symbol"><Data size={13} weight={500}>{h.symbol}</Data></span>
              <span title={h.contract}><Text size={12} tone="secondary">{readableContract(h.contract)}</Text></span>
              <Text size={11} tone="dim">{h.qtyClosed}x · {h.entryPrice.toFixed(2)} → {h.exitPrice.toFixed(2)}</Text>
              <Text size={11} tone="secondary">{h.entryDate ? `${h.entryDate} → ${h.exitDate}` : h.exitDate}</Text>
              <Data size={13} weight={500} tone={h.realizedPnlDollar > 0 ? 'pass' : h.realizedPnlDollar < 0 ? 'reject' : undefined}>
                {formatMoney(h.realizedPnlDollar, { plus: true })}
              </Data>
              <span data-testid="history-return">
                <Data size={12} tone={ret === null ? undefined : moneyTone(ret, 2)}>{ret === null ? '—' : formatSignedPct(ret, 1)}</Data>
              </span>
              <span data-testid="history-hold">
                <Data size={12}>{hd === null ? '—' : `${hd}d`}</Data>
              </span>
              <span data-testid="history-exitcheck" title={rowStopTooltip(stop)}>
                <Text size={11} tone={ec.kind === 'past-stop' ? 'reject' : ec.kind === 'within-stop' ? 'caution' : 'secondary'}>{ec.label}</Text>
              </span>
              <span data-testid="history-exitreason">
                <Text size={11} tone="secondary">{exitReasonLabel(h.exitReason)}</Text>
              </span>
              <span className={styles.historyActions}>
                <Link href={`/journal?symbol=${encodeURIComponent(h.symbol)}`} className={styles.historyRemove} aria-label={`Open journal for ${h.symbol}`} title="Open journal for this symbol">↗</Link>
                <button type="button" className={styles.historyRemove} onClick={() => { setRemovePending(h.id); setRemoveFailed(false); }} aria-label={`Remove ${h.symbol} from history`} title="Remove from history">×</button>
              </span>
            </div>
            );
          })}
          </>
          )}
        </div>

        {/* 3. Realized P&L heatmap — below the list */}
        <PnlHeatmap history={history} />
        </div>
      )}

      {tab === 'open' && (<div role="tabpanel" id="portfolio-panel-open" aria-labelledby="portfolio-tab-open" className={styles.panel}>
        {loadState === 'loading' ? (
        <div className={styles.empty} role="status">
          <Text size={14} tone="secondary">Syncing positions…</Text>
        </div>
      ) : loadState === 'failed' ? (
        <div className={styles.empty}>
          <Text size={14} tone="caution">
            {`Could not load positions. Last sync failed ${hhmmss(lastSyncFailedAt ?? 0)}.`}
          </Text>
        </div>
      ) : loadState === 'empty' ? (
        <div className={styles.empty}>
          <Text size={14} tone="secondary">No open positions.</Text>
          <Text size={12} tone="dim">
            Send a trade from the Screener → Step 7 or add manually.
          </Text>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <div className={`${styles.tableHeader} ${styles.minW}`} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">DIR</Text>
            <Text size={11} tone="dim">DTE</Text>
            <Text size={11} tone="dim" className={styles.right}>ENTRY → NOW</Text>
            <Text size={11} tone="dim" className={styles.right}>P&L</Text>
            <Text size={11} tone="dim" className={styles.right}>{ivColumnLabel(ivBasesOf(positions))}</Text>
            <Text size={11} tone="dim" className={styles.right}>Δ · Θ $/DAY</Text>
            <Text size={11} tone="dim">UNDERLYING vs STOP / T1</Text>
            <Text size={11} tone="dim" className={styles.right}>RISK @ STOP</Text>
            <Text size={11} tone="dim">STATUS</Text>
            <span aria-hidden />
          </div>

          <div className={`${styles.tableBody} ${styles.minW}`}>
            {positions.map((p) => {
              // Status is derived at render from the alert engine's own rules
              // (the stored p.status is only the creation-time value).
              const derived = derivePositionStatus(p, { premiumStopPct });
              const risk = riskAtStopOf(p);
              return (
              <div key={p.recId} className={styles.rowWrap}>
                {/* The row itself stays role="row" (TableRow's onClick would make it
                    a button holding buttons), so selection lives on this wrapper. */}
                <div
                  className={styles.rowSelect}
                  tabIndex={0}
                  onClick={() => setSelectedSymbol(p.symbol)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target === e.currentTarget) setSelectedSymbol(p.symbol);
                  }}
                >
                <TableRow status={derived.status} columns={COLUMNS}>
                  <OpenChartButton symbol={p.symbol} />
                  <div className={styles.symbolCell}>
                    <Data size={13} weight={500}>{p.symbol}</Data>
                    <span className={styles.contractCell}>
                      <span title={p.contract}><Text size={11} tone="secondary">{readableContract(p.contract)}</Text></span>
                      {p.source === 'manual'     && <span className={styles.srcManual}>MANUAL</span>}
                      {p.source === 'paper'      && <span className={styles.srcPaper} title={p.sourceLabel ?? 'Paper broker execution'}>PAPER</span>}
                      {p.source === 'auto-trade' && <span className={styles.srcAuto}  title={p.sourceLabel ?? 'Auto-trade execution'}>AUTO</span>}
                    </span>
                  </div>
                  <span className={p.direction === 'Bullish' ? styles.dirBull : styles.dirBear}>
                    {p.direction === 'Bullish' ? 'Bull' : 'Bear'}
                  </span>
                  <DTEProgressBar daysRemaining={p.dteRemaining} totalDays={p.dteTotal} />
                  <div
                    className={styles.priceCell}
                    title={
                      p.contract.endsWith('|STOCK')
                        ? `Stock at entry: $${p.entryPrice.toFixed(2)}`
                        : `Stock at entry: ${p.entryStockPrice != null ? `$${p.entryStockPrice.toFixed(2)}` : '— (not recorded)'}\nOption at entry: $${p.entryPrice.toFixed(2)} per share`
                    }
                  >
                    <div className={styles.pricePair}>
                      <Data size={12}>${p.entryPrice.toFixed(2)}</Data>
                      <Text size={11} tone="dim">→</Text>
                      {p.quoteUnavailable ? (
                        <Data size={12} weight={500} title="Quote unavailable">—</Data>
                      ) : (
                        <Data size={12} weight={500}>${p.currentPrice.toFixed(2)}</Data>
                      )}
                    </div>
                    {!p.contract.endsWith('|STOCK') && (
                      <div className={styles.stockEntrySub}>
                        <Text size={10} tone="dim">Stock: </Text>
                        <Data size={10} tone="secondary">
                          {p.entryStockPrice != null ? `$${p.entryStockPrice.toFixed(2)}` : '—'}
                        </Data>
                      </div>
                    )}
                  </div>
                  {p.quoteUnavailable ? (
                    <div className={styles.pnlCell} title="Quote unavailable">
                      <Data size={13} weight={500}>—</Data>
                      <Data size={11}>—</Data>
                    </div>
                  ) : (
                    <div className={styles.pnlCell}>
                      <Data size={13} weight={500} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                        {formatMoney(p.pnlDollar, { plus: true })}
                      </Data>
                      <Data size={11} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                        {formatSignedPct(p.pnlPct, 1)}
                      </Data>
                    </div>
                  )}
                  <IvPositionCell position={p} />
                  {(() => {
                    const th = positionThetaDollars(p);
                    return (
                      <span className={styles.right}>
                        <Data size={12}>{p.delta !== undefined ? p.delta.toFixed(2) : '—'}</Data>
                        <Text size={12} tone="dim">{' · '}</Text>
                        {th == null ? (
                          <Data size={12}>—</Data>
                        ) : (
                          <Data size={12} tone={moneyTone(th, 2)}>
                            {formatMoney(th, { decimals: 2, plus: true })}
                          </Data>
                        )}
                      </span>
                    );
                  })()}
                  <RangeCell position={p} />
                  {risk != null ? (
                    <Data size={12} className={styles.right}>{formatMoney(risk)}</Data>
                  ) : (
                    <Data size={12} className={styles.right} title={p.contract.endsWith('|STOCK') ? RISK_STOCK : RISK_NEEDS_PLAN}>—</Data>
                  )}
                  <div className={styles.statusCell}>
                    <StatusBadge status={derived.status} tooltip={positionStatusTooltip(derived.status)} />
                    <Text size={10} tone="secondary">{derived.reason}</Text>
                  </div>
                  <button
                    type="button"
                    className={styles.editBtn}
                    onClick={(e) => {
                      e.stopPropagation();
                      const opening = editing !== p.contract;
                      setEditing(opening ? p.contract : null);
                      setSelectedSymbol(opening ? p.symbol : null);
                    }}
                    aria-label={`Edit ${p.contract}`}
                    aria-expanded={editing === p.contract}
                    title="Edit position"
                  >
                    <PencilIcon />
                  </button>
                </TableRow>
                </div>

                {editing === p.contract && (
                  <EditDrawer
                    position={p}
                    onClose={() => { setEditing(null); setSelectedSymbol(null); }}
                    onChange={(patch) => updatePosition(p.contract, patch)}
                    onRemove={() => { setEditing(null); setSelectedSymbol(null); setClosing(p.contract); }}
                  />
                )}
              </div>
              );
            })}
          </div>

          {/* Sticky totals footer */}
          <div className={`${styles.footer} ${styles.minW}`}>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Deployed</Text>
              <Data size={14} weight={500}>{formatMoney(deployed)}</Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Open P&L</Text>
              <Data size={14} weight={500} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
                {formatMoney(openPnL, { plus: true })}
              </Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Return on cost</Text>
              <Data size={14} weight={500} tone={openPnLPct > 0 ? 'pass' : openPnLPct < 0 ? 'reject' : undefined}>
                {formatSignedPct(openPnLPct, 1)}
              </Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Θ per day</Text>
              <Data size={14} weight={500} tone={thetaDollars != null ? moneyTone(thetaDollars, 2) : undefined}>
                {thetaDollars != null ? formatMoney(thetaDollars, { decimals: 2, plus: true }) : '—'}
              </Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">W / L</Text>
              <Data size={14} weight={500}>
                <span className={styles.win}>{winners}</span>
                {' / '}
                <span className={styles.loss}>{losers}</span>
              </Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Risk at stops</Text>
              <Data size={14} weight={500}>{formatMoney(riskTotal.total)}</Data>
              {riskTotal.unpriced > 0 && <Text size={10} tone="caution">{`+${riskTotal.unpriced} unpriced`}</Text>}
            </div>
            {unquoted > 0 && (
              <div className={styles.footerGroup}>
                <Text size={11} tone="caution">{unquotedNote(unquoted)}</Text>
              </div>
            )}
          </div>
        </div>
      )}

        <div className={styles.perfViews}>
          <PnlChart
            equityCurve={performance.equityCurve}
            realizedCurve={performance.realizedCurve}
            openPnlCurve={performance.openPnlCurve}
            defaultKind="open"
            staleNotices={staleNotices}
          />
        </div>
      </div>)}

      {tab === 'open' && closing && (() => {
        const p = positions.find((x) => x.contract === closing);
        const dismiss = () => { setClosing(null); setCloseError(null); };

        // A failed close can remove the position from `positions` (e.g. the
        // "genuinely gone" case in closePositionRemote drops the phantom row
        // before returning its error). If the drawer only rendered when `p`
        // still exists, that exact removal made the whole modal — including
        // the error explaining WHY — vanish along with it. Show a standalone
        // error card in that case instead of silently closing.
        if (!p) {
          if (!closeError) return null;
          return (
            <div className={styles.closeOverlay} role="dialog" aria-modal="true" aria-label="Close position error" onClick={(e) => { if (e.target === e.currentTarget) dismiss(); }}>
              <div className={styles.closeModal}>
                <Text size={12} tone="reject">{closeError}</Text>
                <button type="button" className={styles.clearConfirmBtn} onClick={dismiss}>OK</button>
              </div>
            </div>
          );
        }

        return (
          <div
            className={styles.closeOverlay}
            role="dialog"
            aria-modal="true"
            onClick={(e) => { if (e.target === e.currentTarget) dismiss(); }}
          >
            <div className={styles.closeModal}>
              {closeError && <Text size={12} tone="reject">{closeError}</Text>}
              <ClosePositionDrawer
                position={p}
                premiumStopPct={premiumStopPct}
                onCancel={dismiss}
                onConfirm={(opts) => confirmClose(p, opts)}
              />
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function PerfStat({ label, value, period }: { label: string; value: number; period?: string }) {
  const tone = value > 0 ? 'pass' : value < 0 ? 'reject' : undefined;
  return (
    <div className={styles.perfStat}>
      <Text size={11} tone="secondary">{label}</Text>
      <Data size={16} weight={500} tone={tone}>{formatMoney(value, { plus: true })}</Data>
      {period && <Text size={10} tone="dim">{period}</Text>}
    </div>
  );
}

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
      <path
        d="M9.5 1.8 L12.2 4.5 L4.5 12.2 L1.5 12.5 L1.8 9.5 Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}
