'use client';

/*
 * Portfolio — Phase 5.
 * Open positions table with DTE progress bars, sticky totals footer, and
 * inline in-memory edit. Click the pencil to change stop / target / size
 * or close the position (removed from local state — mock only).
 */

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { BrokerAttemptPanel } from '@/components/organisms/BrokerAttemptPanel';
import { ClosePositionDrawer } from '@/components/organisms/ClosePositionDrawer';
import { PnlChart } from '@/components/organisms/PnlChart';
import { PnlHeatmap } from '@/components/organisms/PnlHeatmap';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAlertStore } from '@/lib/alertStore';
import { scanPortfolio } from '@/lib/alertEngine';
import { toHistoryCsv } from '@/lib/portfolioHistory';
import { positionStatusTooltip } from '@/lib/statusTooltips';
import type { PortfolioPosition } from '@/types/domain';
import { resolveIv, formatIv, ivColumnLabel, ivBasesOf, type IvBasis } from '@/lib/ivBasis';
import styles from './page.module.css';
import { EditDrawer } from './EditDrawer';
import { isPartialSave, rejectionMessage } from '@/lib/portfolioRejection';
import { premiumStopDropText } from '@/lib/premiumStop';
import { openTotals, unquotedNote } from '@/lib/portfolioTotals';

const HISTORY_COLUMNS = '64px 1.6fr 1fr 168px 80px 28px';

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

const COLUMNS = '28px 72px 1.6fr 72px 1fr 110px 104px 60px 56px 60px 90px 40px';

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
  const syncFromBackend = usePortfolioStore((s) => s.syncFromBackend);
  const updatePosition = usePortfolioStore((s) => s.updatePosition);
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
  const removeHistory = usePerformanceStore((s) => s.removeHistory);
  const clearAllHistory = usePerformanceStore((s) => s.clearAllHistory);
  const [clearConfirm, setClearConfirm] = useState(false);

  useEffect(() => {
    // Sync open positions FIRST — GET /api/portfolio writes today's equity
    // snapshot (including open P&L) when every position got a quote; when any
    // did not, it skips the write and today's point stays as last written
    // (NO-LIVE-QUOTE NLQ-1). Only then read performance, otherwise the curve
    // races ahead of a write and shows a stale value.
    (async () => {
      await syncFromBackend();
      fetchPerformance();
    })();
    fetchHistory();

    // Every 30 s: refresh live quotes → run alert engine → refresh equity curve.
    // Chained so alerts always fire on freshly-fetched prices, not a parallel clock.
    const runCycle = () => {
      usePortfolioStore.getState().syncFromBackend?.()
        .then(() => {
          const positions = usePortfolioStore.getState().positions;
          const pct = useSettingsStore.getState().premiumStopPct;
          const addToast = useAlertStore.getState().addToast;
          // enabledTypes is read here (not captured in the effect's closure) so
          // a Settings change takes effect on the very next 30s cycle without
          // this interval having to be torn down and re-created.
          const enabledTypes = useAlertStore.getState().config.enabledTypes;
          for (const r of scanPortfolio(positions, { premiumStopPct: pct, enabledTypes })) addToast(r);
          usePerformanceStore.getState().fetchPerformance();
        })
        .catch(() => {});
    };
    const id = setInterval(runCycle, 30_000);
    return () => clearInterval(id);
  }, [syncFromBackend, fetchHistory, fetchPerformance]);

  // Clear the sidebar's selected-symbol note when leaving this page, so a
  // stale selection doesn't linger for the next visit.
  useEffect(() => {
    return () => setSelectedSymbol(null);
  }, [setSelectedSymbol]);

  // A row with no quote carries 0 defaults, not a price: the totals leave it
  // out and say so, rather than adding a silent 0 (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, openPnLPct, winners, losers, unquoted } = openTotals(positions);

  const now = new Date();
  const fmtDay = (d: Date) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
  const todayLabel = fmtDay(now);
  // Calendar week (Mon–Sun) containing today — matches the backend's week bucket.
  const mondayOffset = (now.getDay() + 6) % 7;
  const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset);
  const weekEnd = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + 6);
  const weekLabel = `${fmtDay(weekStart)} – ${fmtDay(weekEnd)}`;
  const monthLabel = now.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
  const yearLabel = String(now.getFullYear());

  const confirmClose = async (p: PortfolioPosition, opts: { qtyToClose: number; exitPrice: number; exitDate: string }) => {
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

      <div className={styles.tabs}>
        <button type="button" className={tab === 'open' ? styles.tabActive : styles.tab} onClick={() => setTab('open')}>
          Open ({positions.length})
        </button>
        <button type="button" className={tab === 'history' ? styles.tabActive : styles.tab} onClick={() => setTab('history')}>
          History ({history.length})
        </button>
      </div>

      <div className={styles.perfStrip}>
        <PerfStat label="Today"  value={performance.realizedToday} period={todayLabel} />
        <PerfStat label="Week"   value={performance.realizedWeek}  period={weekLabel} />
        <PerfStat label="Month"  value={performance.realizedMonth} period={monthLabel} />
        <PerfStat label="Year"   value={performance.realizedYear}  period={yearLabel} />
      </div>

      {tab === 'history' && (
        <>
        {/* 1. Equity curve — sits above the trade list */}
        <div className={styles.perfViews}>
          <PnlChart
            equityCurve={performance.equityCurve}
            realizedCurve={performance.realizedCurve}
            defaultKind="realized"
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
        <div className={styles.historyWrap}>
          {history.length === 0 ? (
            <Text size={13} tone="secondary">No closed trades yet.</Text>
          ) : (
          <>
          <div className={styles.historyHeader} style={{ gridTemplateColumns: HISTORY_COLUMNS }}>
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">CONTRACT</Text>
            <Text size={11} tone="dim">QTY · ENTRY → EXIT</Text>
            <Text size={11} tone="dim">DATES</Text>
            <Text size={11} tone="dim">P&L</Text>
            <span aria-hidden />
          </div>
          {history.map((h) => (
            <div key={h.id} className={styles.historyRow}>
              <Data size={13} weight={500}>{h.symbol}</Data>
              <Text size={12} tone="secondary">{h.contract}</Text>
              <Text size={11} tone="dim">{h.qtyClosed}x · {h.entryPrice.toFixed(2)} → {h.exitPrice.toFixed(2)}</Text>
              <Text size={11} tone="secondary">{h.entryDate ? `${h.entryDate} → ${h.exitDate}` : h.exitDate}</Text>
              <Data size={13} weight={500} tone={h.realizedPnlDollar > 0 ? 'pass' : h.realizedPnlDollar < 0 ? 'reject' : undefined}>
                {h.realizedPnlDollar > 0 ? '+' : ''}${Math.round(h.realizedPnlDollar)}
              </Data>
              <button type="button" className={styles.historyRemove} onClick={() => removeHistory(h.id)} aria-label={`Remove ${h.symbol} from history`} title="Remove from history">×</button>
            </div>
          ))}
          </>
          )}
        </div>

        {/* 3. Realized P&L heatmap — below the list */}
        <PnlHeatmap history={history} />
        </>
      )}

      {tab === 'open' && (<>
        {positions.length === 0 ? (
        <div className={styles.empty}>
          <Text size={14} tone="secondary">No open positions.</Text>
          <Text size={12} tone="dim">
            Send a trade from the Screener → Step 7 or add manually.
          </Text>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">CONTRACT</Text>
            <Text size={11} tone="dim">DIR</Text>
            <Text size={11} tone="dim">DTE</Text>
            <Text size={11} tone="dim" className={styles.right}>ENTRY → NOW</Text>
            <Text size={11} tone="dim" className={styles.right}>P&L</Text>
            <Text size={11} tone="dim" className={styles.right}>{ivColumnLabel(ivBasesOf(positions))}</Text>
            <Text size={11} tone="dim" className={styles.right}>Δ</Text>
            <Text size={11} tone="dim" className={styles.right}>Θ/DAY</Text>
            <Text size={11} tone="dim">STATUS</Text>
            <span aria-hidden />
          </div>

          <div className={styles.tableBody}>
            {positions.map((p) => (
              <div key={p.recId} className={styles.rowWrap}>
                <TableRow status={p.status} columns={COLUMNS}>
                  <OpenChartButton symbol={p.symbol} />
                  <Data size={13} weight={500}>{p.symbol}</Data>
                  <span className={styles.contractCell}>
                    <Text size={12} tone="secondary">{p.contract}</Text>
                    {p.source === 'manual'     && <span className={styles.srcManual}>MANUAL</span>}
                    {p.source === 'paper'      && <span className={styles.srcPaper} title={p.sourceLabel ?? 'Paper broker execution'}>PAPER</span>}
                    {p.source === 'auto-trade' && <span className={styles.srcAuto}  title={p.sourceLabel ?? 'Auto-trade execution'}>AUTO</span>}
                  </span>
                  <span className={p.direction === 'Bullish' ? styles.dirBull : styles.dirBear}>
                    {p.direction === 'Bullish' ? 'Bull' : 'Bear'}
                  </span>
                  <DTEProgressBar daysRemaining={p.dteRemaining} totalDays={p.dteTotal} />
                  <div className={styles.priceCell}>
                    <Data size={12}>${p.entryPrice.toFixed(2)}</Data>
                    <Text size={11} tone="dim">→</Text>
                    {p.quoteUnavailable ? (
                      <Data size={12} weight={500} title="Quote unavailable">—</Data>
                    ) : (
                      <Data size={12} weight={500}>${p.currentPrice.toFixed(2)}</Data>
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
                        {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                      </Data>
                      <Data size={11} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                        {p.pnlPct > 0 ? '+' : ''}{p.pnlPct.toFixed(1)}%
                      </Data>
                    </div>
                  )}
                  <IvPositionCell position={p} />
                  <Data size={12} className={styles.right}>
                    {p.delta !== undefined ? p.delta.toFixed(2) : '—'}
                  </Data>
                  <Data size={12} className={styles.right} tone="reject">
                    {p.theta !== undefined ? p.theta.toFixed(2) : '—'}
                  </Data>
                  <StatusBadge status={p.status} tooltip={positionStatusTooltip(p.status)} />
                  <button
                    type="button"
                    className={styles.editBtn}
                    onClick={() => {
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

                {editing === p.contract && (
                  <EditDrawer
                    position={p}
                    onClose={() => { setEditing(null); setSelectedSymbol(null); }}
                    onChange={(patch) => updatePosition(p.contract, patch)}
                    onRemove={() => { setEditing(null); setSelectedSymbol(null); setClosing(p.contract); }}
                  />
                )}
              </div>
            ))}
          </div>

          {/* Sticky totals footer */}
          <div className={styles.footer}>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Deployed</Text>
              <Data size={14} weight={500}>${Math.round(deployed).toLocaleString()}</Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Open P&L</Text>
              <Data size={14} weight={500} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
                {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
              </Data>
            </div>
            <div className={styles.footerGroup}>
              <Text size={11} tone="secondary">Return</Text>
              <Data size={14} weight={500} tone={openPnLPct > 0 ? 'pass' : openPnLPct < 0 ? 'reject' : undefined}>
                {openPnLPct > 0 ? '+' : ''}{openPnLPct.toFixed(2)}%
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
          />
        </div>
      </>)}

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
      <Data size={16} weight={500} tone={tone}>{value > 0 ? '+' : ''}${Math.round(value)}</Data>
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
