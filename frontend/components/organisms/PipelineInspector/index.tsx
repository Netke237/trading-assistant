'use client';

import React, { useState, useMemo, useEffect, useRef, useId } from 'react';
import Link from 'next/link';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';
import type { StockPipeline } from '@/types/stockDomain';
import type { DteWindow } from '@/types/domain';
import { parsePipelineDiagnostics, type DiagnosticStage } from '@/lib/parsePipelineDiagnostics';
import { parseStockPipelineDiagnostics } from '@/lib/parseStockPipelineDiagnostics';
import { Text, Data } from '@/components/primitives';
import styles from './PipelineInspector.module.css';

interface PipelineInspectorCommonProps {
  rejected?: RejectedEntry[];
  survivors?: string[];
  /** `ScanResult.contract_rules` — labels show a threshold only when the scan recorded it. */
  contractRules?: Record<string, number> | null;
  dteWindow?: DteWindow;
  isOpen?: boolean;
  onClose?: () => void;
  isDrawer?: boolean;
  defaultSearch?: string;
}

type PipelineInspectorProps = PipelineInspectorCommonProps & (
  | { mode?: 'options'; pipeline?: OptionsPipeline }
  | { mode: 'stock'; pipeline?: StockPipeline }
);

type CopyState = 'idle' | 'copied' | 'failed';

const EMPTY_REJECTED: RejectedEntry[] = [];
const EMPTY_SURVIVORS: string[] = [];

function initialExpanded(stages: DiagnosticStage[]): Record<string, boolean> {
  const init: Record<string, boolean> = {};
  for (const s of stages) if (s.isBottleneck) init[s.id] = true;
  return init;
}

export function PipelineInspector({
  mode = 'options',
  pipeline,
  rejected = EMPTY_REJECTED,
  survivors = EMPTY_SURVIVORS,
  contractRules,
  dteWindow,
  isOpen = true,
  onClose,
  isDrawer = true,
  defaultSearch = '',
}: PipelineInspectorProps) {
  const [searchQuery, setSearchQuery] = useState(defaultSearch);
  const [viewMode, setViewMode] = useState<'tree' | 'ascii'>('tree');
  const [copyState, setCopyState] = useState<CopyState>('idle');
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Parents build `survivors` with a fresh `.map()` each render; keying on its
  // contents keeps the report (and the expansion reset below) stable until the
  // scan actually changes.
  const survivorsKey = survivors.join(',');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableSurvivors = useMemo(() => survivors, [survivorsKey]);
  const report = useMemo(
    () => mode === 'stock'
      ? parseStockPipelineDiagnostics(pipeline as StockPipeline | undefined, rejected, stableSurvivors)
      : parsePipelineDiagnostics(pipeline as OptionsPipeline | undefined, rejected, stableSurvivors, { contractRules, dteWindow }),
    [mode, pipeline, rejected, stableSurvivors, contractRules, dteWindow],
  );

  // Re-derived whenever a new report arrives, so a re-run scan does not keep
  // the previous run's expansion.
  const [expandedStages, setExpandedStages] = useState<Record<string, boolean>>(() => initialExpanded(report.stages));
  const [expandedChips, setExpandedChips] = useState<Record<string, boolean>>({});
  const firstReport = useRef(report);
  useEffect(() => {
    if (firstReport.current === report) return;
    firstReport.current = report;
    setExpandedStages(initialExpanded(report.stages));
    setExpandedChips({});
  }, [report]);

  // Held in a ref so a parent passing an inline arrow does not re-run the
  // focus effect below on every render (which would yank focus to the search).
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  // Drawer: Escape closes, Tab stays inside, focus moves in on open and back
  // to the opener on close.
  useEffect(() => {
    if (!isDrawer || !isOpen) return;
    const opener = document.activeElement as HTMLElement | null;
    searchRef.current?.focus();
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (e.defaultPrevented) return;
        onCloseRef.current?.();
        return;
      }
      if (e.key !== 'Tab' || !dialogRef.current) return;
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      // Focus can fall out of the dialog when the focused control unmounts
      // (e.g. "Clear search"); pull it back in rather than let Tab reach the page.
      if (!dialogRef.current.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
        return;
      }
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      opener?.focus?.();
    };
  }, [isDrawer, isOpen]);

  useEffect(() => {
    if (copyState === 'idle') return;
    const t = setTimeout(() => setCopyState('idle'), 2000);
    return () => clearTimeout(t);
  }, [copyState]);

  function toggleStage(id: string) {
    setExpandedStages((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function toggleChips(key: string) {
    setExpandedChips((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleCopyTree() {
    try {
      if (!navigator?.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(report.asciiTree);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  const trimmedQuery = searchQuery.trim();
  const searchedResult = useMemo(
    () => (trimmedQuery ? report.lookupSymbol(trimmedQuery) : null),
    [trimmedQuery, report],
  );

  if (!isOpen) return null;

  const copyLabel = copyState === 'copied' ? 'Copied' : copyState === 'failed' ? 'Copy failed' : 'Copy Tree';
  const bottleneck = report.primaryBottleneck;

  const content = (
    <div
      ref={dialogRef}
      className={isDrawer ? styles.drawer : styles.container}
      role={isDrawer ? 'dialog' : 'region'}
      aria-modal={isDrawer ? true : undefined}
      aria-labelledby={titleId}
    >
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <h2 id={titleId} className={styles.title}>
            <Text size={13} weight={600}>Pipeline Root-Cause Inspector</Text>
          </h2>
          <div className={styles.headerActions}>
            <button
              type="button"
              className={styles.iconBtn}
              onClick={handleCopyTree}
              title="Copy formatted ASCII tree"
            >
              {copyLabel}
            </button>
            {isDrawer && onClose && (
              <button
                type="button"
                className={styles.closeBtn}
                onClick={onClose}
                aria-label="Close inspector"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        <div className={styles.metaRow}>
          <span className={styles.badge}>{report.scanned} Scanned</span>
          <span
            className={`${styles.badge} ${styles.badgeReject}`}
            title="Scanned minus survivors: every rejected symbol plus any trimmed by the shortlist cap"
          >
            −{report.totalDropped} Not Ranked
          </span>
          <span className={`${styles.badge} ${styles.badgePass}`}>
            {report.candidatesCount} Survivor{report.candidatesCount !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      <div className={styles.searchSection}>
        <div className={styles.searchInputWrapper}>
          <input
            ref={searchRef}
            type="text"
            className={styles.searchInput}
            placeholder="Search symbol (e.g. NVDA, AAPL)..."
            aria-label="Look up a symbol in this scan"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className={styles.clearBtn}
              onClick={() => {
                setSearchQuery('');
                searchRef.current?.focus();
              }}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        {/* Always mounted so screen readers announce each new lookup result. */}
        <div role="status" aria-live="polite">
        {trimmedQuery && !searchedResult && (
          <div className={styles.notFound}>
            {trimmedQuery.toUpperCase()} is not among this scan&apos;s survivors or recorded rejects.
          </div>
        )}

        {searchedResult && (
          <div className={styles.symbolResultCard}>
            <div className={styles.symbolResultTop}>
              <span className={styles.symbolName}>{searchedResult.symbol}</span>
              <span
                className={`${styles.badge} ${
                  searchedResult.status === 'SURVIVOR' ? styles.badgePass
                    : searchedResult.status === 'TRIMMED' ? styles.badgeBottleneck : styles.badgeReject
                }`}
              >
                {searchedResult.status}
              </span>
            </div>
            <div className={styles.symbolDetails}>
              <div>
                <span className={styles.detailKey}>Stage:</span> {searchedResult.stageName}
              </div>
              <div>
                <span className={styles.detailKey}>Rule:</span> {searchedResult.primaryReason}
              </div>
              {searchedResult.detailedReason !== searchedResult.primaryReason && (
                <div className={styles.detailRaw}>{searchedResult.detailedReason}</div>
              )}
            </div>

            {searchedResult.components && searchedResult.components.length > 0 && (
              <div className={styles.breakdownGrid}>
                {searchedResult.components.map((c) => (
                  <div
                    key={c.key}
                    className={`${styles.breakdownItem} ${
                      c.key === searchedResult.weakestComponent ? styles.breakdownWeakest : ''
                    }`}
                    title={c.placeholder
                      ? 'Placeholder value — the scorer also returns this when it cannot measure the component'
                      : c.key === searchedResult.weakestComponent ? 'Lowest weighted component' : undefined}
                  >
                    <Text size={10} tone="dim">{c.label.toUpperCase()}</Text>
                    <Data size={11} weight={500} tone={c.placeholder ? 'dim' : 'primary'}>
                      {c.placeholder ? `${c.score}?` : c.score}
                    </Data>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        </div>
      </div>

      <div className={styles.content}>
        {report.reconciliationNote && (
          <div className={styles.stageNote}>{report.reconciliationNote}</div>
        )}
        {bottleneck && (
          <div className={styles.bottleneckCard}>
            <div className={styles.bottleneckTitle}>
              Primary bottleneck: {bottleneck.stageTitle}
            </div>
            <div className={styles.bottleneckDesc}>{bottleneck.insight}</div>
            <div className={styles.bottleneckTip}>
              <span className={styles.detailKey}>Where to look:</span> {bottleneck.suggestedAction}
            </div>
            {isDrawer && bottleneck.adjustHref && (
              <Link href={bottleneck.adjustHref} className={styles.bottleneckBtn}>
                {bottleneck.adjustLabel} →
              </Link>
            )}
          </div>
        )}

        <div className={styles.treeSection}>
          <div className={styles.treeHeader}>
            <Text size={11} weight={500} tone="secondary">DROP-OFF HIERARCHY</Text>
            <div className={styles.treeViewToggle}>
              <button
                type="button"
                className={`${styles.viewModeBtn} ${viewMode === 'tree' ? styles.viewModeActive : ''}`}
                onClick={() => setViewMode('tree')}
                aria-pressed={viewMode === 'tree'}
              >
                Interactive
              </button>
              <button
                type="button"
                className={`${styles.viewModeBtn} ${viewMode === 'ascii' ? styles.viewModeActive : ''}`}
                onClick={() => setViewMode('ascii')}
                aria-pressed={viewMode === 'ascii'}
              >
                Plaintext Tree
              </button>
            </div>
          </div>

          {viewMode === 'ascii' ? (
            <pre className={styles.asciiTreeBox}>{report.asciiTree}</pre>
          ) : (
            <div className={styles.treeContainer}>
              <div className={styles.rootNode}>Universe ({report.scanned} Total)</div>

              {report.stages.map((stage, idx) => {
                const isExpanded = !!expandedStages[stage.id];
                return (
                  <div
                    key={stage.id}
                    className={`${styles.stageCard} ${stage.isBottleneck ? styles.stageCardBottleneck : ''}`}
                  >
                    <button
                      type="button"
                      className={styles.stageHeader}
                      onClick={() => toggleStage(stage.id)}
                      aria-expanded={isExpanded}
                    >
                      <span className={styles.stageTitleArea}>
                        <span className={`${styles.stageChevron} ${isExpanded ? styles.stageChevronOpen : ''}`} aria-hidden>
                          ▶
                        </span>
                        <Text size={12} weight={500}>
                          {idx + 1}. {stage.title}
                        </Text>
                      </span>
                      <span className={styles.stageBadges}>
                        <span className={`${styles.badge} ${styles.badgeReject}`}>−{stage.droppedCount}</span>
                        <span className={styles.badge}>{stage.pctOfTotal}%</span>
                        <span className={styles.badge}>Left {stage.remainingCount}</span>
                        {stage.isBottleneck && (
                          <span className={`${styles.badge} ${styles.badgeBottleneck}`}>Bottleneck</span>
                        )}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className={styles.stageBody}>
                        <div className={styles.stageRuleSummary}>{stage.ruleSummary}</div>
                        {stage.note && <div className={styles.stageNote}>{stage.note}</div>}

                        {stage.subRules.length === 0 && stage.droppedCount === 0 && (
                          <div className={styles.subRuleExplanation}>Nothing dropped at this stage.</div>
                        )}

                        <div className={styles.subRuleList}>
                          {stage.subRules.map((sub) => {
                            const chipKey = `${stage.id}/${sub.id}`;
                            const showChips = !!expandedChips[chipKey];
                            return (
                              <div key={sub.id} className={styles.subRuleItem}>
                                <div className={styles.subRuleHeader}>
                                  <Text size={11} weight={500}>{sub.label}</Text>
                                  <Data size={11} weight={500} tone="reject">
                                    {sub.count === null ? '—' : `−${sub.count}`}
                                  </Data>
                                </div>
                                <div className={styles.subRuleExplanation}>{sub.ruleExplanation}</div>

                                {sub.symbols.length > 0 && (
                                  <>
                                    <button
                                      type="button"
                                      className={styles.tickerChipsToggle}
                                      onClick={() => toggleChips(chipKey)}
                                      aria-expanded={showChips}
                                    >
                                      {showChips ? 'Hide Tickers ▲' : `View ${sub.symbols.length} Tickers ▼`}
                                    </button>
                                    {showChips && (
                                      <div className={styles.tickerChipsGrid}>
                                        {sub.symbols.map((sym) => (
                                          <button
                                            key={sym}
                                            type="button"
                                            className={styles.tickerChip}
                                            onClick={() => setSearchQuery(sym)}
                                            title={`Click to inspect ${sym}`}
                                          >
                                            {sym}
                                          </button>
                                        ))}
                                      </div>
                                    )}
                                  </>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              <div className={styles.survivorCard}>
                <Text size={12} weight={600} tone="pass">
                  Final Survivors: {report.candidatesCount} Candidate{report.candidatesCount !== 1 ? 's' : ''}
                </Text>
                {survivors.length > 0 && (
                  <div className={styles.survivorChips}>
                    {survivors.slice(0, 5).map((s) => (
                      <span key={s} className={`${styles.badge} ${styles.badgePass}`}>
                        {s}
                      </span>
                    ))}
                    {survivors.length > 5 && (
                      <span className={styles.badge}>+{survivors.length - 5}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  if (isDrawer) {
    return (
      <>
        <div className={styles.drawerBackdrop} onClick={onClose} aria-hidden />
        {content}
      </>
    );
  }

  return content;
}
