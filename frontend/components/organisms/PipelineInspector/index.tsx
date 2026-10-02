'use client';

import React, { useState, useMemo, useEffect } from 'react';
import Link from 'next/link';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';
import { parsePipelineDiagnostics } from '@/lib/parsePipelineDiagnostics';
import styles from './PipelineInspector.module.css';

interface PipelineInspectorProps {
  pipeline?: OptionsPipeline;
  rejected?: RejectedEntry[];
  survivors?: string[];
  isOpen?: boolean;
  onClose?: () => void;
  isDrawer?: boolean;
  defaultSearch?: string;
}

export function PipelineInspector({
  pipeline,
  rejected = [],
  survivors = [],
  isOpen = true,
  onClose,
  isDrawer = true,
  defaultSearch = '',
}: PipelineInspectorProps) {
  const [searchQuery, setSearchQuery] = useState(defaultSearch);
  const [viewMode, setViewMode] = useState<'tree' | 'ascii'>('tree');
  const [copied, setCopied] = useState(false);

  // Close drawer on Escape key press
  useEffect(() => {
    if (!isDrawer || !isOpen || !onClose) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose?.();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDrawer, isOpen, onClose]);

  // Compute diagnostics
  const report = useMemo(
    () => parsePipelineDiagnostics(pipeline, rejected, survivors),
    [pipeline, rejected, survivors],
  );

  // Expanded stages state: default open the bottleneck and pre-screen
  const [expandedStages, setExpandedStages] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const s of report.stages) {
      if (s.isBottleneck || s.droppedCount > 0) {
        init[s.id] = true;
      }
    }
    return init;
  });

  // Expanded ticker chips state
  const [expandedChips, setExpandedChips] = useState<Record<string, boolean>>({});

  function toggleStage(id: string) {
    setExpandedStages((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function toggleChips(subId: string) {
    setExpandedChips((prev) => ({ ...prev, [subId]: !prev[subId] }));
  }

  function handleCopyTree() {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(report.asciiTree);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  // Active searched symbol
  const searchedResult = useMemo(
    () => (searchQuery ? report.lookupSymbol(searchQuery) : null),
    [searchQuery, report],
  );

  if (!isOpen) return null;

  const content = (
    <div className={isDrawer ? styles.drawer : styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleArea}>
            <span style={{ fontSize: '15px' }}>🔍</span>
            <span style={{ fontSize: '13px', fontWeight: 600 }}>Pipeline Root-Cause Inspector</span>
          </div>
          <div className={styles.headerActions}>
            <button
              type="button"
              className={styles.iconBtn}
              onClick={handleCopyTree}
              title="Copy formatted ASCII tree"
            >
              {copied ? '✓ Copied' : '📋 Copy Tree'}
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

      {/* Symbol Search */}
      <div className={styles.searchSection}>
        <div className={styles.searchInputWrapper}>
          <span className={styles.searchIcon}>🔍</span>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Search symbol (e.g. NVDA, AAPL)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              style={{
                position: 'absolute',
                right: '8px',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Live Symbol Lookup Result Card */}
        {searchedResult && (
          <div className={styles.symbolResultCard}>
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
                <strong>Stage:</strong> {searchedResult.stageName}
              </div>
              <div>
                <strong>Reason:</strong> {searchedResult.primaryReason}
              </div>
              {searchedResult.detailedReason !== searchedResult.primaryReason && (
                <div style={{ marginTop: '3px', color: 'var(--text-dim)' }}>
                  <em>{searchedResult.detailedReason}</em>
                </div>
              )}
            </div>

            {searchedResult.breakdown && (
              <div className={styles.breakdownGrid}>
                {Object.entries(searchedResult.breakdown).map(([k, v]) => (
                  <div key={k} className={styles.breakdownItem}>
                    <span style={{ color: 'var(--text-dim)', textTransform: 'uppercase' }}>{k}</span>
                    <span
                      className={styles.breakdownVal}
                      style={{ color: v >= 55 ? 'var(--pass)' : v >= 35 ? 'var(--caution)' : 'var(--reject)' }}
                    >
                      {v}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className={styles.content}>
        {/* Primary Bottleneck Card */}
        {report.primaryBottleneck && (
          <div className={styles.bottleneckCard}>
            <div className={styles.bottleneckTitle}>
              <span>⚠️</span>
              <span>PRIMARY BOTTLENECK: {report.primaryBottleneck.stageTitle}</span>
            </div>
            <div className={styles.bottleneckDesc}>{report.primaryBottleneck.insight}</div>
            <div className={styles.bottleneckTip}>
              <strong>Remedy:</strong> {report.primaryBottleneck.suggestedAction}
            </div>
            {isDrawer && (
              <Link href="/screener/step-3-direction" className={styles.bottleneckBtn}>
                Adjust in Step 3 →
              </Link>
            )}
          </div>
        )}

        {/* Tree Section */}
        <div className={styles.treeSection}>
          <div className={styles.treeHeader}>
            <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
              DROP-OFF HIERARCHY
            </span>
            <div className={styles.treeViewToggle}>
              <button
                type="button"
                className={`${styles.viewModeBtn} ${viewMode === 'tree' ? styles.viewModeActive : ''}`}
                onClick={() => setViewMode('tree')}
              >
                Interactive
              </button>
              <button
                type="button"
                className={`${styles.viewModeBtn} ${viewMode === 'ascii' ? styles.viewModeActive : ''}`}
                onClick={() => setViewMode('ascii')}
              >
                Plaintext Tree
              </button>
            </div>
          </div>

          {viewMode === 'ascii' ? (
            <pre className={styles.asciiTreeBox}>{report.asciiTree}</pre>
          ) : (
            <div className={styles.treeContainer}>
              {/* Root node */}
              <div className={styles.rootNode}>
                <span>🌐</span>
                <span>Universe ({report.scanned} Total)</span>
              </div>

              {/* Stages */}
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
                      <div className={styles.stageTitleArea}>
                        <span className={`${styles.stageChevron} ${isExpanded ? styles.stageChevronOpen : ''}`}>
                          ▶
                        </span>
                        <span className={styles.stageTitle}>
                          {idx + 1}. {stage.title}
                        </span>
                      </div>
                      <div className={styles.stageBadges}>
                        <span className={`${styles.badge} ${styles.badgeReject}`}>−{stage.droppedCount}</span>
                        <span className={styles.badge}>{stage.pctOfTotal}%</span>
                        {stage.isBottleneck && (
                          <span className={`${styles.badge} ${styles.badgeBottleneck}`}>Bottleneck</span>
                        )}
                      </div>
                    </button>

                    {isExpanded && (
                      <div className={styles.stageBody}>
                        <div className={styles.stageRuleSummary}>{stage.ruleSummary}</div>

                        <div className={styles.subRuleList}>
                          {stage.subRules.map((sub) => {
                            const showChips = !!expandedChips[sub.id];
                            return (
                              <div key={sub.id} className={styles.subRuleItem}>
                                <div className={styles.subRuleHeader}>
                                  <span className={styles.subRuleLabel}>{sub.label}</span>
                                  <div className={styles.subRuleCountArea}>
                                    <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--reject)' }}>
                                      −{sub.count}
                                    </span>
                                  </div>
                                </div>
                                <div className={styles.subRuleExplanation}>{sub.ruleExplanation}</div>

                                {sub.symbols.length > 0 && (
                                  <>
                                    <button
                                      type="button"
                                      className={styles.tickerChipsToggle}
                                      onClick={() => toggleChips(sub.id)}
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

              {/* Survivor Final Node */}
              <div className={styles.survivorCard}>
                <div className={styles.survivorTitle}>
                  <span>✓</span>
                  <span>
                    Final Survivors: {report.candidatesCount} Candidate{report.candidatesCount !== 1 ? 's' : ''}
                  </span>
                </div>
                {survivors.length > 0 && (
                  <div style={{ display: 'flex', gap: '4px' }}>
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
