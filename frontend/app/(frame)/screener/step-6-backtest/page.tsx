'use client';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { SavedScanReportInspector } from '@/components/organisms/SavedScanReportInspector';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import { WatchStar } from '@/components/atoms/WatchStar';
import { Tooltip } from '@/components/atoms/Tooltip';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { DirectSendNotesPanel } from '@/components/organisms/DirectSendNotesPanel';
import { stockPositionCardKey } from '@/lib/stockScan';
import { splitStockRejected } from '@/lib/stockShortlist';
import { computeStockDeltas } from '@/lib/stockDelta';
import { stockScanGateTooltip, fundamentalScoreTooltip, winRateTooltip } from '@/lib/statusTooltips';
import { toneForScore, FUNDAMENTAL_BAND } from '@/lib/status';
import styles from './page.module.css';

const TIME_EXIT_TOOLTIP = "trades closed at the next open after being held the horizon's hold, neither stop nor target reached";

function _startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}
function _labelWithDate(iso: string): string {
  const scan = new Date(iso);
  const now  = new Date();
  const diffDays = Math.round((_startOfDay(now) - _startOfDay(scan)) / 86_400_000);
  const timeStr = scan.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const mon = scan.toLocaleString(undefined, { month: 'short' });
  const day = scan.getDate();
  if (diffDays === 1) return `Yesterday · ${timeStr}`;
  const sameYear = scan.getFullYear() === now.getFullYear();
  return sameYear ? `${mon} ${day} · ${timeStr}` : `${mon} ${day} ${scan.getFullYear()} · ${timeStr}`;
}

export default function Step6BacktestPage() {
  const result = useScanStore(s => s.stockScanResult);
  const previous = useScanStore(s => s.previousStockScanResult);
  const request = useScanStore(s => s.stockScanRequest);
  const stockScanAt = useScanStore(s => s.stockScanAt);
  const feedback = useScanStore(s => s.stockScanFeedback);
  const stockBasket = useScanStore(s => s.stockBasket);
  const afterScanIntent = useScanStore(s => s.stockAfterScanIntent);
  const selected = useScanStore(s => s.selectedSymbol);
  const setSelectedSymbol = useScanStore(s => s.setSelectedSymbol);
  const eventFilter = useScanParamsStore(s => s.eventFilter);
  const portfolioPositions = usePortfolioStore(s => s.positions);
  const portfolioSymbols = new Set(portfolioPositions.map(p => p.symbol));
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [healthSort, setHealthSort] = useState<'asc' | 'desc' | null>(null);
  const [showSendDialog, setShowSendDialog] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const router = useRouter();
  const minTrades = request?.bt_min_trades;
  const minWinRate = request?.bt_min_win_rate;
  const scannedRequestStrategy = request?.strategy;
  const deltas = result ? computeStockDeltas(result, previous) : new Map();
  const candidates = result?.candidates ?? [];
  const filteredCandidates = candidates.filter(c => eventFilter === 'avoid' ? c.next_event_days == null || c.next_event_days > 7 : eventFilter === 'only_pre_event' ? c.next_event_days != null && c.next_event_days <= 21 : true);
  const { rejected: gateRejected, overCap } = splitStockRejected(result?.rejected);
  const candidateSymbols = candidates.map(c => c.symbol);
  const notRanked = Math.max(0, (result?.pipeline?.scanned ?? (result?.rejected.length ?? 0) + candidates.length) - candidates.length);
  const gateThisScan = typeof minTrades === 'number' && typeof minWinRate === 'number'
    ? `win ≥${(minWinRate * 100).toFixed(0)}% · trades ≥${minTrades} · expectancy ≥ 0`
    : 'Threshold provenance unavailable for this scan';
  const eventFilterLabel = eventFilter === 'include' ? 'Include' : eventFilter === 'avoid' ? 'Avoid' : eventFilter === 'only_pre_event' ? 'Events only' : eventFilter;
  function onAfterScanToggle(symbol: string, armed: boolean) { useScanStore.getState().setStockAfterScanIntent(symbol, armed); }
  function proceedWith(symbol: string) { setSelectedSymbol(symbol); router.push('/screener/step-7-position-card'); }
  return <div className={styles.main}>
    <div className={styles.header}>
      <Text size={11} tone="dim">STEP 5 OF 6</Text><Title as="h1" size={24}>Backtest Results</Title>
      <Text size={13} tone="secondary">{filteredCandidates.length} candidates · {gateRejected.length} rejected{overCap.length > 0 && ` · ${overCap.length} over cap`}</Text>
      <Text size={12} tone="caution">Unvalidated · Research only. Strategy validation is unavailable; automatic arming and broker sending are blocked. Score is a filter. The backtest gate below is historical per-symbol scan evidence, not strategy validation approval.</Text>
      {stockBasket.length > 0 && <button type="button" className={styles.actionBtn} onClick={() => setShowSendDialog(true)}>Send basket ({stockBasket.length})</button>}
    </div>
    {/* react-jsx drops whitespace between elements; the label keeps the space so the region reads "Candidates 2". */}
    <section className={styles.summaryStrip} aria-label="Scan summary">
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Candidates </Text>
        <Data size={13}>{filteredCandidates.length}{' '}</Data>
      </div>
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Rejected </Text>
        <Data size={13}>{gateRejected.length}{' '}</Data>
      </div>
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Over cap </Text>
        <Data size={13}>{overCap.length}{' '}</Data>
      </div>
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Gate this scan used </Text>
        <Text size={12}>{gateThisScan}{' '}</Text>
      </div>
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Event filter </Text>
        <Text size={12}>{eventFilterLabel}{' '}</Text>
      </div>
      <div className={styles.summaryItem}>
        <Text size={11} tone="dim">Hidden </Text>
        <Data size={13}>{candidates.length - filteredCandidates.length}{' '}</Data>
      </div>
      {stockScanAt && mounted && (
        <div className={styles.summaryItem}>
          <Text size={11} tone="dim">Last stock scan: {_labelWithDate(stockScanAt)}</Text>
        </div>
      )}
    </section>
    {feedback.error && <Text size={12} tone="reject">{feedback.error}</Text>}
    {feedback.notice && <Text size={12} tone="caution">{feedback.notice}</Text>}
    <DirectSendNotesPanel />
    {!result && <Text size={13} tone="dim">No stock scan result. Go back to Step 4 (Strategy) and run a scan.</Text>}
    {<button type="button" className={styles.inspectBtn} onClick={() => setInspectorOpen(true)}>Filter Breakdown{result ? ` (${notRanked} Not Ranked)` : ' · saved report'}</button>}
    {result?.direction_banner && <div className={styles.directionBanner}><Text size={12} tone="caution">{result.direction_banner}</Text></div>}
    {candidates.length > filteredCandidates.length && <Text size={11} tone="caution">{candidates.length - filteredCandidates.length} of {candidates.length} hidden by the event filter.</Text>}
    {result && filteredCandidates.length === 0 && <Text size={13} tone="dim">No candidates to display. Adjust the filter or return to Strategy and run another scan.</Text>}
    {result && <div className={styles.results}>
      <div className={styles.tableHeader}>
        <span aria-hidden />
        {['SYMBOL','SUMMARY','SCORE','STATUS','Δ','WIN %','TRADES','RETURN','MAX DD'].map(label => <Text key={label} size={11} tone="dim">{label}</Text>)}
        <button type="button" className={styles.sortableHeader} onClick={() => setHealthSort(s => s === null ? 'desc' : s === 'desc' ? 'asc' : null)} title="Sort by fundamental health score">HEALTH {healthSort === 'desc' ? '↓' : healthSort === 'asc' ? '↑' : '↕'}</button>
        {['VS SPX','EVENT','CONF','GATE','DETAILS','POSITION'].map(label => <Text key={label} size={11} tone="dim">{label}</Text>)}
      </div>
      <div className={styles.tableBody}>
            {[...filteredCandidates].sort((a, b) => {
              if (healthSort === null) return 0;
              const aScore = a.fundamentals?.score ?? -1;
              const bScore = b.fundamentals?.score ?? -1;
              return healthSort === 'desc' ? bScore - aScore : aScore - bScore;
            }).map((c) => {
              const d = deltas.get(c.symbol);
              const bt = c.backtest;
              const open = openSymbol === c.symbol;
              const gateStatus = bt.passes_gate ? 'PASS' : 'REJECT';
              return (
                <div key={c.symbol}>
                  <div
                    className={`${styles.row} ${open || selected === c.symbol ? styles.rowOpen : ''}`}
                  >
                    <span>
                      <WatchStar symbol={c.symbol} size="sm" />
                    </span>
                    <span className={styles.symbolCell}>
                      <Data size={12} weight={500}>{c.symbol}</Data>
                      {portfolioSymbols.has(c.symbol) && (
                        <span className={styles.inPortfolioDot} title="Already in portfolio" />
                      )}
                    </span>
                    <Text size={11}>{bt.summary_text.split('·')[0]?.trim()}</Text>
                    <Data size={12} title="Score is a filter, not evidence of profitable edge">{c.stock_score}</Data>
                    <StatusBadge status={c.stock_status} />
                    <Data size={11} tone={!d ? 'dim' : d.scoreDelta > 0 ? 'pass' : d.scoreDelta < 0 ? 'reject' : 'secondary'}>
                      {!d ? '—' : `${d.scoreDelta > 0 ? '+' : ''}${d.scoreDelta}${d.rankDelta !== 0 ? ` (${d.rankDelta > 0 ? '↑' : '↓'}${Math.abs(d.rankDelta)})` : ''}`}
                    </Data>
                    <Data
                      size={12}
                      tone={bt.win_rate >= 0.5 ? 'pass' : minWinRate != null && bt.win_rate >= minWinRate ? 'caution' : 'reject'}
                      title={minWinRate == null ? 'Threshold provenance unavailable for this scan' : winRateTooltip(bt.win_rate, 0.5, minWinRate)}
                    >
                      {(bt.win_rate * 100).toFixed(0)}%
                    </Data>
                    <span className={styles.tradesCell} data-testid={`trades-${c.symbol}`}>
                      <Data size={12}>{bt.n_trades}</Data>
                      {/* n_time_exits null/absent = unknown (saved before the field): never "0", no hold label. */}
                      {bt.n_time_exits == null ? (
                        <Text size={10} tone="dim">—</Text>
                      ) : bt.hold_max_days == null ? (
                        <Text size={10} tone="dim">no hold</Text>
                      ) : (
                        <Tooltip text={TIME_EXIT_TOOLTIP}>
                          <Text size={10} tone="secondary">{`${bt.n_time_exits} of ${bt.n_trades} on time (hold ${bt.hold_max_days}d)`}</Text>
                        </Tooltip>
                      )}
                    </span>
                    <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>{bt.total_return_pct.toFixed(1)}%</Data>
                    <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
                    {c.fundamentals ? (
                      <Tooltip text={fundamentalScoreTooltip('overall', c.fundamentals.score)}>
                        <Data size={12} tone={toneForScore(c.fundamentals.score, FUNDAMENTAL_BAND)}>
                          {c.fundamentals.score}
                        </Data>
                      </Tooltip>
                    ) : (
                      <Data size={12} tone="dim">—</Data>
                    )}
                    <Data size={12} tone={c.sector_rs_pct == null ? 'secondary' : c.sector_rs_pct > 1 ? 'pass' : c.sector_rs_pct < -1 ? 'reject' : 'secondary'}>{c.sector_rs_pct == null ? '—' : `${c.sector_rs_pct > 0 ? '+' : ''}${c.sector_rs_pct.toFixed(1)}%`}</Data>
                    <Text size={11} tone={c.next_event_days == null ? 'dim' : c.next_event_days <= 3 ? 'reject' : c.next_event_days <= 14 ? 'caution' : 'secondary'}>
                      {c.next_event_days == null ? '—' : `${(c.next_event_label ?? 'E')[0].toUpperCase()} ${c.next_event_days}d`}
                    </Text>
                    <ConfidenceBadge confidence={c.confidence} title={c.confidence_text ?? undefined} />
                    <StatusBadge
                      status={gateStatus}
                      tooltip={minTrades == null || minWinRate == null ? 'Threshold provenance unavailable for this scan' : stockScanGateTooltip({
                        passes: bt.passes_gate,
                        winRate: bt.win_rate,
                        nTrades: bt.n_trades,
                        expectancy: bt.expectancy,
                        minWinRate,
                        minTrades,
                      })}
                    />
                    <button type="button" className={styles.actionBtn} aria-expanded={open} aria-label={`Expand ${c.symbol}`} onClick={() => setOpenSymbol(open ? null : c.symbol)}>{open ? 'Collapse' : 'Expand'}</button>
                    <button type="button" className={styles.actionBtn} onClick={() => proceedWith(c.symbol)}>Open Position</button>
                  </div>
                  {open && (
                    <StockPositionCard
                      // See stockPositionCardKey's doc comment: an adversarial audit
                      // round caught a stale entry/stop/target overlay from a
                      // PREVIOUS scan silently surviving a same-symbol Run Scan and
                      // reaching order placement / Add to Portfolio, because
                      // `openSymbol` isn't reset by onRun() and StockPositionCard's
                      // own overlay-reset effect only fires on a symbol change.
                      key={stockPositionCardKey(c)}
                      card={c}
                      // The strategy this row was scanned with: NOT the current selection, which
                      // can change after the scan, and NOT lastStockScanStrategy, which can name
                      // another tab's or device's scan (plan audit P1-F1). StockAutoTradeArm
                      // persists a strategy watch with this key.
                      strategyKey={scannedRequestStrategy ?? c.strategy.strategy}
                      afterScanArmed={!!afterScanIntent[c.symbol]}
                      onAfterScanToggle={onAfterScanToggle}
                    />
                  )}
                </div>
              );
            })}
      </div>
    </div>}
    {showSendDialog && <StockSendDialog cards={stockBasket} onClose={() => setShowSendDialog(false)} onSubmit={() => setShowSendDialog(false)} />}
    <SavedScanReportInspector category="stocks" tableRunId={result?.report_run_id} isDrawer isOpen={inspectorOpen} onClose={() => setInspectorOpen(false)} />
  </div>;
}
