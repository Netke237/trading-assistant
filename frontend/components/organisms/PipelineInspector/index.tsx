'use client';

import React, { useState, useMemo, useEffect, useRef, useId } from 'react';
import Link from 'next/link';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';
import type { DteWindow } from '@/types/domain';
import { parsePipelineDiagnostics, type DiagnosticStage } from '@/lib/parsePipelineDiagnostics';
import styles from './PipelineInspector.module.css';

interface PipelineInspectorProps {
  pipeline?: OptionsPipeline;
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

type CopyState = 'idle' | 'copied' | 'failed';

const EMPTY_REJECTED: RejectedEntry[] = [];
const EMPTY_SURVIVORS: string[] = [];

function initialExpanded(stages: DiagnosticStage[]): Record<string, boolean> {
  const init: Record<string, boolean> = {};
  for (const s of stages) if (s.isBottleneck) init[s.id] = true;
  return init;
}

export function PipelineInspector({
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
    () => parsePipelineDiagnostics(pipeline, rejected, stableSurvivors, { contractRules, dteWindow }),
    [pipeline, rejected, stableSurvivors, contractRules, dteWindow],
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
          <h2 id={titleId} className={styles.title}>Pipeline Root-Cause Inspector</h2>
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
          <span className={`${styles.badge} ${styles.badgeReject}`}>−{report.totalDropped} Filtered</span>
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
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        {trimmedQuery && !searchedResult && (
          <div className={styles.notFound} role="status">
            {trimmedQuery.toUpperCase()} was not part of this scan.
          </div>
        )}

        {searchedResult && (
          <div className={styles.symbolResultCard} role="status">
            <div className={styles.symbolResultTop}>
              <span className={styles.symbolName}>{searchedResult.symbol}</span>
              <span
                className={`${styles.badge} ${
                  searchedResult.status === 'SURVIVOR' ? styles.badgePass : styles.badgeReject
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

            {searchedResult.breakdown && (
              <div className={styles.breakdownGrid}>
                {Object.entries(searchedResult.breakdown).map(([k, v]) => (
                  <div
                    key={k}
                    className={`${styles.breakdownItem} ${
                      k === searchedResult.weakestComponent ? styles.breakdownWeakest : ''
                    }`}
                    title={k === searchedResult.weakestComponent ? 'Lowest-scoring component' : undefined}
                  >
                    <span className={styles.breakdownKey}>{k}</span>
                    <span className={styles.breakdownVal}>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className={styles.content}>
        {bottleneck && (
          <div className={styles.bottleneckCard}>
            <div className={styles.bottleneckTitle}>
              Primary bottleneck: {bottleneck.stageTitle}
            </div>
            <div className={styles.bottleneckDesc}>{bottleneck.insight}</div>
            <div className={styles.bottleneckTip}>
              <span className={styles.detailKey}>Where to look:</span> {bottleneck.suggestedAction}
            </div>
            {isDrawer && (
              <Link href={bottleneck.adjustHref} className={styles.bottleneckBtn}>
                {bottleneck.adjustLabel} →
              </Link>
            )}
          </div>
        )}

        <div className={styles.treeSection}>
          <div className={styles.treeHeader}>
            <span className={styles.sectionLabel}>DROP-OFF HIERARCHY</span>
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
                        <span className={styles.stageTitle}>
                          {idx + 1}. {stage.title}
                        </span>
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
                                  <span className={styles.subRuleLabel}>{sub.label}</span>
                                  <span className={styles.subRuleCount}>
                                    {sub.count === null ? '—' : `−${sub.count}`}
                                  </span>
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
                <div className={styles.survivorTitle}>
                  Final Survivors: {report.candidatesCount} Candidate{report.candidatesCount !== 1 ? 's' : ''}
                </div>
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
