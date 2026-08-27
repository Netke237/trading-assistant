'use client';

/*
 * Portfolio — Phase 5.
 * Open positions table with DTE progress bars, sticky totals footer, and
 * inline in-memory edit. Click the pencil to change stop / target / size
 * or close the position (removed from local state — mock only).
 */

import { useEffect, useRef, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { usePortfolioStore, flushPendingPositionPatches } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { maxLossAtStop, resolveMaxLossLimitDollar, recommendedContractSize, formatRecommendedContractSizeRaw } from '@/lib/risk';
import { ClosePositionDrawer } from '@/components/organisms/ClosePositionDrawer';
import { PnlChart } from '@/components/organisms/PnlChart';
import { PnlHeatmap } from '@/components/organisms/PnlHeatmap';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { _horizonEnum } from '@/lib/analysisStore';
import { useAlertStore } from '@/lib/alertStore';
import { scanPortfolio } from '@/lib/alertEngine';
import { toHistoryCsv } from '@/lib/portfolioHistory';
import { positionStatusTooltip } from '@/lib/statusTooltips';
import { api } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';
import styles from './page.module.css';

const HISTORY_COLUMNS = '64px 1.6fr 1fr 168px 80px 28px';

const REJECTION_LABELS: Record<string, string> = {
  single_trade_exposure_too_high: 'This trade is too large for your account size (over the single-trade limit). Raise your account value in Settings or reduce size.',
  size_reduced_to_fit_exposure_limit: 'This trade is too large for your account size (over the single-trade limit). Raise your account value in Settings or reduce size.',
  total_exposure_limit_reached: 'Adding this would exceed your total portfolio exposure limit.',
  max_concurrent_positions_reached: 'You are at your maximum number of open positions.',
  daily_recommendation_limit_reached: 'You have reached the maximum number of new positions for today.',
  duplicate_symbol_already_open: 'You already have an open position on this symbol.',
  portfolio_too_small: 'Your configured account value is below the minimum required.',
};

/** The backend returns risk reasons space-joined (portfolio.py); map each code
 *  to friendly text, falling back to the raw string when unmapped. */
function rejectionMessage(detail: string): string {
  const mapped = detail
    .split(' ')
    .map((code) => REJECTION_LABELS[code])
    .filter(Boolean);
  return mapped.length ? mapped.join(' ') : detail;
}

function ivRankTone(rk: number | undefined): 'pass' | 'caution' | 'reject' | undefined {
  if (rk === undefined) return undefined;
  if (rk >= 70) return 'reject';      // very rich
  if (rk >= 40) return 'caution';     // moderate
  return 'pass';                      // cheap
}

/** `position.contract` for an option position is a backend-generated,
 *  pipe-delimited machine ID — "SYMBOL|STRIKE|EXPIRY|C/P" (see
 *  backend/app/routers/scan.py's `contract=f"{symbol}|{int(strike)}|..."`
 *  and backend/app/schemas/__init__.py's persistence-schema comment). Note
 *  the `int(strike)` truncation — this id is INTEGER-only, so it silently
 *  rounds down any fractional strike (e.g. 187.5 -> "187"). Every option
 *  position, old or new, has this format, unlike `tradeCardSnapshot.strike`,
 *  which is only populated for positions opened after this Monte Carlo
 *  feature shipped — so this is used strictly as the FALLBACK for
 *  pre-existing positions that predate the snapshot, never preferred over
 *  it. Callers must try `tradeCardSnapshot.strike` first. */
function optionStrikeFromContract(contract: string): number | null {
  const parts = contract.split('|');
  if (parts.length !== 4) return null;
  const strike = Number(parts[1]);
  return Number.isFinite(strike) && strike > 0 ? strike : null;
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
  const clearSyncError = usePortfolioStore((s) => s.clearSyncError);
  const syncFromBackend = usePortfolioStore((s) => s.syncFromBackend);
  const updatePosition = usePortfolioStore((s) => s.updatePosition);
  const [editing, setEditing] = useState<string | null>(null);
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
    // snapshot (including open P&L). Only then read performance, otherwise the
    // curve races ahead of the write and shows a stale value.
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
          for (const r of scanPortfolio(positions, { premiumStopPct: pct })) addToast(r);
          usePerformanceStore.getState().fetchPerformance();
        })
        .catch(() => {});
    };
    const id = setInterval(runCycle, 30_000);
    return () => clearInterval(id);
  }, [syncFromBackend, fetchHistory, fetchPerformance]);

  const deployed = positions.reduce((s, p) => s + p.currentPrice * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1), 0);
  const openPnL  = positions.reduce((s, p) => s + p.pnlDollar, 0);
  const openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0;
  const winners = positions.filter((p) => p.pnlDollar > 0).length;
  const losers  = positions.filter((p) => p.pnlDollar < 0).length;

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

      {lastSyncError && (
        <div role="alert" className={styles.syncErrorBanner}>
          <Text size={13} tone="reject">
            {lastSyncError.symbol} was not saved: {rejectionMessage(lastSyncError.detail)}
          </Text>
          <button type="button" className={styles.syncErrorDismiss} onClick={clearSyncError} aria-label="Dismiss">
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
            <Text size={11} tone="dim" className={styles.right}>IV RK</Text>
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
                    <Data size={12} weight={500}>${p.currentPrice.toFixed(2)}</Data>
                  </div>
                  <div className={styles.pnlCell}>
                    <Data size={13} weight={500} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                      {p.pnlDollar > 0 ? '+' : ''}${Math.round(p.pnlDollar)}
                    </Data>
                    <Data size={11} tone={p.pnlDollar > 0 ? 'pass' : p.pnlDollar < 0 ? 'reject' : undefined}>
                      {p.pnlPct > 0 ? '+' : ''}{p.pnlPct.toFixed(1)}%
                    </Data>
                  </div>
                  <Data size={12} className={styles.right} tone={ivRankTone(p.ivRank)}>
                    {p.ivRank !== undefined ? p.ivRank : '—'}
                  </Data>
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
                    onClick={() => setEditing((cur) => (cur === p.contract ? null : p.contract))}
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
                    onClose={() => setEditing(null)}
                    onChange={(patch) => updatePosition(p.contract, patch)}
                    onRemove={() => { setEditing(null); setClosing(p.contract); }}
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

/* ---------- Edit drawer ---------- */

export function EditDrawer({
  position,
  onClose,
  onChange,
  onRemove,
}: {
  position: PortfolioPosition;
  onClose: () => void;
  onChange: (patch: Partial<PortfolioPosition>) => void;
  onRemove: () => void;
}) {
  // Send any debounced-but-not-yet-fired edit immediately when this drawer
  // instance goes away — covers both its own close button and the parent
  // swapping `editing` to a different row (which unmounts this instance
  // without ever calling `onClose`).
  useEffect(() => {
    return () => { flushPendingPositionPatches(position.recId); };
  }, [position.recId]);

  const isStock = position.contract.endsWith('|STOCK');
  const snapshot = position.tradeCardSnapshot ?? {};
  const stockTargetPrices = position.targets.map((t) => t.targetPrice ?? t.stockPrice).filter((p): p is number => typeof p === 'number' && p > 0);
  const optionStrike = (typeof snapshot.strike === 'number' ? snapshot.strike : null) ?? optionStrikeFromContract(position.contract);
  const optionTrend = (snapshot.stockBreakdown as { trend?: number } | undefined)?.trend;
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);

  // Mirrors backend/app/routers/stock_scan.py's own directional validation for
  // /api/stocks/first-passage (stop and every target must be on the correct
  // side of the current price for the trade's direction) — without this, a
  // normal winning position (current price has already run past a target that
  // hasn't had its `targets[].status` synced to HIT yet) hits a 422 that the
  // single catch{} below collapses into "try again," which can never succeed
  // no matter how many times the user clicks it.
  const stockDirectionValid = isStock && position.stop
    ? position.direction === 'Bullish'
      ? position.stop < position.currentPrice && stockTargetPrices.every((p) => p > position.currentPrice)
      : position.stop > position.currentPrice && stockTargetPrices.every((p) => p < position.currentPrice)
    : true;

  const estimateDisabled = isStock
    ? stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid
    : optionStrike == null || position.currentStockPrice == null || !position.stop;

  // Same AbortController pattern as StockPositionCard's onEstimate/estimateReq
  // (the template this section mirrors): abort a still-in-flight request when
  // the button is re-fired or this drawer instance goes away (closing the
  // drawer, or the parent switching `editing` to a different row), so a late
  // response for a request the user has already moved on from can never land.
  const estimateReq = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => { estimateReq.current?.abort(); };
  }, [position.recId]);

  const [mcLoading, setMcLoading] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);
  const [mcResult, setMcResult] = useState<{
    targets: { label: string; price: number; probability: number; expectedDays: number | null }[];
    invalidation: { probability: number; expectedDays: number | null };
    horizonNote?: string;
    modelCaveat?: string | null;
  } | null>(null);

  // True once the user has explicitly edited the "Current price" EditField
  // in this drawer session since the last estimate — set ONLY by that
  // field's own onChange below, never derived by comparing mcResult's
  // captured price against position.currentPrice/currentStockPrice on every
  // render. A value-comparison approach was tried first and had to be
  // reverted: portfolioStore's syncFromBackend() re-enriches currentPrice/
  // currentStockPrice from the broker every 30s (see the "clear entirely"
  // effect's own comment on this same tick, which excludes these fields for
  // exactly this reason) while this drawer stays mounted in place — a
  // comparison-based flag would have relabeled that routine price refresh as
  // "the user changed something," firing a false "stale" caution roughly
  // every poll cycle during market hours even when nobody touched anything.
  const [priceEditedSinceEstimate, setPriceEditedSinceEstimate] = useState(false);

  // Clear a stale Monte Carlo result — and abort an in-flight request — when
  // the user edits stop/targets in this same open drawer (EditDrawer doesn't
  // unmount on those edits; the parent just re-renders it with new props).
  // Without this, the panel keeps showing probabilities computed against the
  // OLD stop/targets after the user changes them. Keyed by VALUE (not the
  // `position.targets` array reference, which gets a new identity on
  // unrelated store updates like a routine price-sync tick) so this doesn't
  // spuriously wipe a fresh estimate on every sync poll — only on a genuine
  // stop/target edit. Deliberately excludes currentPrice/currentStockPrice,
  // which tick frequently and would defeat the point of showing a result.
  const targetPricesKey = position.targets.map((t) => t.targetPrice ?? t.stockPrice).join(',');
  useEffect(() => {
    estimateReq.current?.abort();
    estimateReq.current = null;
    // Aborting means this drawer no longer cares about the in-flight
    // request's outcome — reset mcLoading here too, unconditionally.
    // runEstimate's own `finally` only clears mcLoading when
    // estimateReq.current still === its own controller, which is no longer
    // true once this effect has nulled the ref: without this line the
    // button would be stuck on "Estimating…" until the drawer remounts.
    setMcLoading(false);
    setMcResult(null);
    setMcError(null);
    setPriceEditedSinceEstimate(false);
  }, [position.stop, targetPricesKey]);

  const runEstimate = async () => {
    estimateReq.current?.abort();
    const ctrl = new AbortController();
    estimateReq.current = ctrl;
    setMcLoading(true);
    setMcError(null);
    setMcResult(null);
    setPriceEditedSinceEstimate(false);
    try {
      if (isStock) {
        if (stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid) throw new Error('missing target/stop');
        // A position minted with no snapshot (the after-scan auto-execute path
        // deliberately omits one — see paperTrade.ts/step-4-stocks's own
        // comment) has no real strategy name to send. An empty string just
        // never matches the backend's mean-reversion caveat check, which is a
        // safe under-trigger — a wrong HARDCODED guess here would misrepresent
        // which strategy this trade actually came from.
        const strategy = (snapshot.strategy as { strategy?: string } | undefined)?.strategy ?? '';
        const horizonLabel = typeof snapshot.horizon === 'string' ? snapshot.horizon : undefined;
        const res = await api.getStockFirstPassage({
          symbol: position.symbol,
          direction: position.direction,
          horizon: _horizonEnum(horizonLabel),
          strategy,
          stock_price: position.currentPrice,
          stop_price: position.stop,
          targets: stockTargetPrices,
          trend_score: typeof snapshot.stock_score === 'number' ? snapshot.stock_score : 50,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setMcResult({
          targets: res.targets.map((t, i) => ({ label: `T${i + 1}`, price: t.price, probability: t.probability, expectedDays: t.expectedDays })),
          invalidation: res.invalidation,
          horizonNote: `${res.horizonDays} trading days`,
          modelCaveat: res.modelCaveat,
        });
      } else {
        if (optionStrike == null || position.currentStockPrice == null || !position.stop) {
          throw new Error('missing option context');
        }
        const res = await api.getFirstPassageEstimate({
          symbol: position.symbol,
          direction: position.direction,
          stock_price: position.currentStockPrice,
          strike: optionStrike,
          dte: position.dteRemaining,
          premium: position.currentPrice,
          delta: position.delta ?? 0.45,
          trend_score: optionTrend ?? 50,
          invalidation_price: position.stop,
          t1_pct: defaultTargetPct.t1,
          t2_pct: defaultTargetPct.t2,
          t3_pct: defaultTargetPct.t3,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setMcResult({
          targets: res.targets.map((t) => ({ label: `T${Math.round(t.pct * 100)}%`, price: t.stockPrice ?? 0, probability: t.probability, expectedDays: t.expectedDays })),
          invalidation: res.invalidation,
        });
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      // Mirrors StockPositionCard's onEstimate, which captures the real
      // error (setEstimateErr(String(e))) rather than a single static
      // message — a genuine backend rejection (bad symbol, missing candle
      // data, a 500) reads very differently from "try again" being useless
      // forever after the directional-guard case above.
      setMcError(String(e));
    } finally {
      if (estimateReq.current === ctrl) {
        estimateReq.current = null;
        setMcLoading(false);
      }
    }
  };

  // True when the user has explicitly edited Current Price in this drawer
  // session since the estimate was fetched, so the displayed probabilities
  // were computed against a now-stale price. Deliberately a flag set only by
  // the EditField's own onChange (see priceEditedSinceEstimate's declaration
  // above), not a comparison against the live position price — the live
  // price ticks on its own via the 30s portfolio sync regardless of whether
  // the user touched anything.
  const mcPriceStale = mcResult != null && priceEditedSinceEstimate;

  return (
    <div className={styles.editDrawer}>
      <div className={styles.editHeader}>
        <Text size={12} weight={400}>Edit {position.contract}</Text>
        <button type="button" className={styles.editClose} onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <div className={styles.editGrid}>
        <EditField
          label="Stop"
          hint="Exit if the underlying stock drops below this price (invalidates the trade thesis)."
          value={position.stop ?? 0}
          onChange={(n) => onChange({ stop: n > 0 ? n : null })}
        />
        <EditField
          label="Structural stop"
          hint="Tighter, chart-based stop (order block / swing level) from Check structure. Optional — 0 means none was captured."
          value={position.structuralStop ?? 0}
          onChange={(n) => onChange({ structuralStop: n > 0 ? n : null })}
        />
        <TargetEditor
          targets={position.targets}
          onChange={(targets) => onChange({ targets })}
        />
        {!position.contract.endsWith('|STOCK') && (
          <ExitPlanEditor position={position} onChange={onChange} />
        )}
        {!position.contract.endsWith('|STOCK') && (
          <MaxLossBanner position={position} onChange={onChange} />
        )}
        <EditField
          label="Contracts"
          hint="Number of option contracts held."
          value={position.contracts ?? 1}
          step={1}
          onChange={(n) => onChange({ contracts: Math.max(1, Math.round(n)) })}
        />
        <EditField
          label="Current price"
          hint="Manual override — will refresh from broker in live mode."
          value={position.currentPrice}
          onChange={(n) => {
            const mult = position.contract.endsWith('|STOCK') ? 1 : 100;
            const pnlDollar = (n - position.entryPrice) * mult * (position.contracts ?? 1);
            const pnlPct    = ((n - position.entryPrice) / position.entryPrice) * 100;
            onChange({ currentPrice: n, pnlDollar, pnlPct });
            setPriceEditedSinceEstimate(true);
          }}
        />
      </div>

      <div className={styles.mcSection}>
        <Text size={12} weight={500}>Monte Carlo estimate</Text>
        <div className={styles.mcRow}>
          <button type="button" className={styles.mcBtn} onClick={runEstimate} disabled={mcLoading || estimateDisabled}>
            <Text size={12} weight={500}>{mcLoading ? 'Estimating…' : 'Estimate'}</Text>
          </button>
          {mcError && <Text size={11} tone="reject">{mcError}</Text>}
        </div>
        {isStock && !stockDirectionValid && (
          <Text size={11} tone="dim">
            Stop or a target is already on the wrong side of the current price — sync the position&apos;s targets before estimating.
          </Text>
        )}
        {mcResult?.horizonNote && (
          <Text size={10} tone="dim">Chance of reaching each target within {mcResult.horizonNote}</Text>
        )}
        {mcResult && (
          <div className={styles.mcResultRow}>
            {mcResult.targets.map((t, i) => (
              <div key={`${t.label}-${i}`}>
                <Text size={10} tone="dim">{t.label.toUpperCase()}</Text>
                <Data size={14} weight={500} tone="pass">{`${Math.round(t.probability * 100)}%`}</Data>
                <Text size={10} tone="dim">{t.expectedDays != null ? `~${Math.round(t.expectedDays)}d` : 'unlikely'}</Text>
              </div>
            ))}
            <div>
              <Text size={10} tone="dim">STOP HIT</Text>
              <Data size={14} weight={500} tone="reject">{`${Math.round(mcResult.invalidation.probability * 100)}%`}</Data>
              <Text size={10} tone="dim">{mcResult.invalidation.expectedDays != null ? `~${Math.round(mcResult.invalidation.expectedDays)}d` : 'unlikely'}</Text>
            </div>
          </div>
        )}
        {mcResult?.modelCaveat && (
          <Text size={11} tone="caution">{mcResult.modelCaveat}</Text>
        )}
        {mcPriceStale && (
          <Text size={11} tone="caution">Price has changed since this estimate was computed.</Text>
        )}
      </div>

      <div className={styles.editFooter}>
        <Text size={11} tone="secondary">
          Stop, structural stop, targets, and contract count save to your account automatically.
        </Text>
        <button type="button" className={styles.editRemove} onClick={onRemove}>
          Close position
        </button>
      </div>
    </div>
  );
}

function TargetEditor({
  targets,
  onChange,
}: {
  targets: import('@/types/domain').TargetLevel[];
  onChange: (targets: import('@/types/domain').TargetLevel[]) => void;
}) {
  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Targets</Text>
      <div className={styles.targetList}>
        {targets.map((t, i) => (
          <div key={t.id ?? i} className={styles.targetItem}>
            <div className={styles.targetHeader}>
              <Text size={12} weight={600}>{t.id?.toUpperCase()}</Text>
              <span className={styles.targetStatus}>{t.status}</span>
            </div>
            <div className={styles.targetGrid}>
              <div>
                <Text size={10} tone="dim">Stock</Text>
                <Data size={12} weight={500}>${t.stockPrice.toFixed(2)}</Data>
              </div>
              {t.estimatedOptionPrice !== undefined && (
                <div>
                  <Text size={10} tone="dim">Est. option</Text>
                  <Data size={12} weight={500}>${t.estimatedOptionPrice.toFixed(2)}</Data>
                </div>
              )}
              <div>
                <Text size={10} tone="dim">Sell</Text>
                <input
                  type="number"
                  min={1}
                  step={1}
                  className={styles.targetInput}
                  value={t.contractsToSell ?? 0}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (!Number.isFinite(n) || n < 1) return;
                    onChange(
                      targets.map((x) => (x.id === t.id ? { ...x, contractsToSell: n } : x)),
                    );
                  }}
                />
              </div>
            </div>
            {t.pricingMethod && (
              <Text size={10} tone="dim">Method: {t.pricingMethod}</Text>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** "Compute Exit Plan" for an OPEN option position — post-trade counterpart
 *  to TradeCard's pre-trade button. Persists the result verbatim via the
 *  same `onChange` -> updatePosition -> PATCH /api/portfolio/{recId} path
 *  every other drawer field already uses; refreshed only on manual re-click,
 *  never automatically. Options-only (the repricing chain needs strike/dte/
 *  premium, which a stock position doesn't have) — the caller only renders
 *  this for non-'|STOCK' contracts. */
function ExitPlanEditor({
  position,
  onChange,
}: {
  position: PortfolioPosition;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const exitPlan = position.exitPlan;

  const compute = async () => {
    setLoading(true);
    setError(false);
    try {
      const parts = position.contract.split('|');
      const strike = Number(parts[1]);
      // trend_score isn't available for an already-open position (the scan-time
      // score isn't carried on PortfolioPosition) — neutral 50 means zero
      // directional drift bias in the Monte Carlo leg, an honest default
      // rather than fabricating a score from partial data.
      const res = await api.getExitPlan({
        symbol: position.symbol,
        direction: position.direction,
        entry_price: position.currentStockPrice ?? position.entryPrice,
        strike,
        dte: position.dteRemaining,
        premium: position.currentPrice,
        trend_score: 50,
      });
      onChange({ exitPlan: { ...res, computedAt: new Date().toISOString() } });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Exit Plan</Text>
      <button type="button" className={styles.exitPlanBtn} onClick={compute} disabled={loading}>
        {loading ? 'Computing exit plan…' : 'Compute Exit Plan'}
      </button>
      {error && <Text size={10} tone="reject">Couldn&apos;t compute an exit plan — try again.</Text>}
      {exitPlan && (
        <div className={styles.targetList}>
          <div className={styles.targetItem}>
            <div className={styles.targetHeader}>
              <Text size={12} weight={600}>
                Stop {exitPlan.stop.source === 'structural' ? '(structural)' : '(ATR-widened)'}
              </Text>
            </div>
            <div className={styles.targetGrid}>
              <div>
                <Text size={10} tone="dim">Stock</Text>
                <Data size={12} weight={500}>${exitPlan.stop.price.toFixed(2)}</Data>
              </div>
              <div>
                <Text size={10} tone="dim">Contract</Text>
                <Data size={12} weight={500}>${exitPlan.stop.contractPrice.toFixed(2)}</Data>
              </div>
            </div>
            <Text size={10} tone="dim">Method: {exitPlan.stop.rrModel}</Text>
          </div>
          {exitPlan.targets.map((t) => (
            <div key={t.rrRatio} className={styles.targetItem}>
              <div className={styles.targetHeader}>
                <Text size={12} weight={600}>{t.rrRatio}R {t.qualityGood ? '✓' : '⚠'}</Text>
                <span className={styles.targetStatus}>{t.tpSource === 'structural_snap' ? 'snapped' : 'arithmetic'}</span>
              </div>
              <div className={styles.targetGrid}>
                <div>
                  <Text size={10} tone="dim">Stock</Text>
                  <Data size={12} weight={500}>${t.price.toFixed(2)}</Data>
                </div>
                <div>
                  <Text size={10} tone="dim">Contract</Text>
                  <Data size={12} weight={500}>${t.contractPrice.toFixed(2)}</Data>
                </div>
                <div>
                  <Text size={10} tone="dim">Probability</Text>
                  <Data size={12} weight={500}>{(t.probability * 100).toFixed(0)}%</Data>
                </div>
              </div>
              <Text size={10} tone="dim">Method: {t.rrModel}</Text>
              {!t.qualityGood && (
                <Text size={10} tone="caution">
                  {t.qualityReasons.includes('stop_widened') ? 'Stop ATR-widened. ' : ''}
                  {t.qualityReasons.includes('target_beyond_structural') ? 'Target overshoots structural level.' : ''}
                </Text>
              )}
            </div>
          ))}
          <Text size={10} tone="dim">as of {new Date(exitPlan.computedAt).toLocaleTimeString()}</Text>
        </div>
      )}
    </div>
  );
}

/** Feature C (exit-plan pipeline plan) — inline max-loss-at-stop badge for an
 *  OPEN option position. Warning-only, never blocks any action here (nothing
 *  is being submitted from the Portfolio editor). Basis is strictly the
 *  exit-plan pipeline's final stop, repriced to a contract price — same rule
 *  TradeCard-time's checkTradeRisk() uses — so it only renders once an exit
 *  plan has been computed; options-only like ExitPlanEditor above it. */
function MaxLossBanner({
  position,
  onChange,
}: {
  position: PortfolioPosition;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const limits = useRiskStore((s) => s.limits);
  const exitPlan = position.exitPlan;
  const contracts = position.contracts ?? 1;
  const override = position.maxLossOverride ?? null;

  // The loss figure is a pure client computation — exitPlan.stop.contractPrice
  // is already repriced, no network round trip needed — so this debounce is
  // purely to stop the number/badge flashing on every keystroke while the
  // user is still typing a new contracts count or override value, not to
  // throttle a live backend call (that already happens 600ms-debounced,
  // separately, in portfolioStore's scheduleRemotePositionPatch).
  const [debounced, setDebounced] = useState({ contracts, override });
  useEffect(() => {
    const t = setTimeout(() => setDebounced({ contracts, override }), 400);
    return () => clearTimeout(t);
  }, [contracts, override]);

  const [editingOverride, setEditingOverride] = useState(false);
  const [draftMode, setDraftMode] = useState<'dollar' | 'percent'>(override?.mode ?? 'percent');
  const [draftValue, setDraftValue] = useState(() =>
    override
      ? (override.mode === 'percent' ? override.value * 100 : override.value)
      : Math.round(limits.maxLossPerTradePct * 100 * 100) / 100
  );

  // entryPrice <= 0 is a data-integrity glitch, not a real 0-loss trade
  // (mirrors the "never a real premium" convention `floorStop` applies to
  // stock prices elsewhere in this store) — without this guard the formula
  // below reports a reassuring "PASS — $0 max loss" for a position whose
  // loss genuinely can't be computed.
  if (!exitPlan || position.contract.endsWith('|STOCK') || position.entryPrice <= 0) return null;

  const lossAtStop = maxLossAtStop(position.entryPrice, exitPlan.stop.contractPrice, debounced.contracts);
  const limitDollar = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, debounced.override);
  const exceeded = lossAtStop > limitDollar;
  const riskPerContract = maxLossAtStop(position.entryPrice, exitPlan.stop.contractPrice, 1);
  const sizing = recommendedContractSize(limitDollar, riskPerContract);

  const applyOverride = () => {
    const value = draftMode === 'percent' ? draftValue / 100 : draftValue;
    onChange({ maxLossOverride: { mode: draftMode, value } });
    setEditingOverride(false);
  };
  const clearOverride = () => {
    onChange({ maxLossOverride: null });
    setEditingOverride(false);
  };

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Max loss at stop</Text>
      <div className={styles.targetItem}>
        <div className={styles.targetHeader}>
          <Data size={13} weight={500} tone={exceeded ? 'reject' : 'pass'}>
            ${Math.round(lossAtStop).toLocaleString()}
          </Data>
          <StatusBadge status={exceeded ? 'REJECT' : 'PASS'} />
        </div>
        <Text size={10} tone="dim">
          Limit ${Math.round(limitDollar).toLocaleString()}
          {override
            ? ` (override: ${override.mode === 'percent' ? `${(override.value * 100).toFixed(2)}%` : `$${override.value.toLocaleString()}`})`
            : ' (account default)'}
        </Text>
        {sizing && (
          <Text size={10} tone="dim">
            Risk-derived size: {sizing.recommended} contract{sizing.recommended === 1 ? '' : 's'} ({formatRecommendedContractSizeRaw(sizing.raw)} exact)
          </Text>
        )}
        {!editingOverride ? (
          <button type="button" className={styles.exitPlanBtn} onClick={() => setEditingOverride(true)}>
            {override ? 'Edit override' : 'Set override'}
          </button>
        ) : (
          <div className={styles.targetGrid}>
            <div className={styles.maxLossModeToggle}>
              <button
                type="button"
                className={draftMode === 'percent' ? styles.maxLossModeBtnActive : styles.maxLossModeBtn}
                onClick={() => setDraftMode('percent')}
              >
                %
              </button>
              <button
                type="button"
                className={draftMode === 'dollar' ? styles.maxLossModeBtnActive : styles.maxLossModeBtn}
                onClick={() => setDraftMode('dollar')}
              >
                $
              </button>
            </div>
            <input
              type="number"
              className={styles.targetInput}
              value={draftValue}
              min={0}
              step={draftMode === 'percent' ? 0.25 : 10}
              onChange={(e) => setDraftValue(Math.max(0, Number(e.target.value) || 0))}
              aria-label="Max loss override value"
            />
            <button type="button" className={styles.exitPlanBtn} onClick={applyOverride}>Apply</button>
            {override && (
              <button type="button" className={styles.editRemove} onClick={clearOverride}>Use default</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EditField({
  label,
  hint,
  value,
  step = 0.05,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  step?: number;
  onChange: (n: number) => void;
}) {
  return (
    <label className={styles.editField}>
      <Text size={11} tone="secondary">{label}</Text>
      <input
        type="number"
        className={styles.editInput}
        step={step}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
      />
      {hint && <Text size={10} tone="dim">{hint}</Text>}
    </label>
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
