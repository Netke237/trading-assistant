'use client';

import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { NoLiveQuoteTag } from '@/components/atoms/NoLiveQuoteTag';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { ContractExplanationToggle } from '@/components/atoms/ContractExplanationToggle';
import { ContractScoreExplanation } from '@/components/molecules/ContractScoreExplanation';
import { validateExplanation, getExplanationSummaryLine } from '@/lib/contractExplanation';
import { api } from '@/lib/api';
import { sanitizeHoldDays } from '@/lib/horizonPresets';
import { buildGrading, gradingToCtx } from '@/lib/contractGrading';
import { missingCardContracts, withCardContract } from '@/lib/step6CardContract';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { contractLabel, type ContractGrading, type OptionContract, type TradeCardData } from '@/types/domain';
import { resolveIv, formatIv, ivSortValue, ivColumnLabel, ivBasesOf } from '@/lib/ivBasis';
import styles from '../screener.module.css';
import tbl from './contracts.module.css';

// Compact column template (10 cols) — fits comfortably at 1280px without horizontal scroll
const COLUMNS = '24px minmax(0, 1fr) 80px 44px 60px 52px 50px 80px 64px 20px';

type SortKey =
  | 'contract' | 'dte' | 'delta' | 'price'
  | 'ivRank' | 'ivPercentile' | 'theta'
  | 'spread' | 'volume' | 'score';

type SortDir = 'asc' | 'desc';

function sortContracts(
  contracts: OptionContract[],
  key: SortKey,
  dir: SortDir,
): OptionContract[] {
  const rows = [...contracts];
  const mul = dir === 'asc' ? 1 : -1;
  // "No data" must never masquerade as a number. `ivRank` and `ivPercentile`
  // are nullable since the Phase A split, and arithmetic on null silently
  // coerces it to 0 — which would sort a contract with NO volatility reading
  // to the top of an ascending "cheapest IV" sort
  // (PHASE-A-NULL-IVRANK-2026-09-06). Nulls sort last in BOTH directions.
  const byNullable = (av: number | null, bv: number | null): number => {
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (av - bv) * mul;
  };
  rows.sort((a, b) => {
    switch (key) {
      case 'contract':
        return contractLabel(a).localeCompare(contractLabel(b)) * mul;
      case 'ivRank':
        // Sort on the figure actually displayed — a percentile when one
        // exists, otherwise the absolute IV.
        return byNullable(ivSortValue(a), ivSortValue(b));
      case 'ivPercentile':
        return byNullable(a.ivPercentile, b.ivPercentile);
      default:
        return ((a[key] as number) - (b[key] as number)) * mul;
    }
  });
  return rows;
}

/** The IV cell. Shows an IV RANK when one exists and an ABSOLUTE
 *  implied volatility otherwise, and says which — the two are different
 *  quantities and printing one under the other's name is the defect Phase A
 *  exists to fix (PHASE-A-NULL-IVRANK-2026-09-06). Most chains have no rank
 *  source, so the absolute form is the common case. */
function IvCell({ contract }: { contract: OptionContract }) {
  const shown = formatIv(resolveIv(contract), contract.symbol);
  return (
    <Data size={12} className={tbl.right} title={shown.title}>
      {shown.text}
      {shown.suffix !== '' && <Text size={10} tone="dim">{` ${shown.suffix}`}</Text>}
    </Data>
  );
}

/** Returns the spread badge label for a candidate, or null if single-leg. */
function spreadBadge(candidate: TradeCardData): string | null {
  if (candidate.spreadType === 'bear_put')  return 'BPS';
  if (candidate.spreadType === 'bear_call') return 'BCS';
  return null;
}

/** Derives global rules applied summary from returned contract evaluation snapshots. */
function getGlobalRulesBanner(contractsBySymbol: Record<string, OptionContract[]>): string | null {
  const allContracts = Object.values(contractsBySymbol).flat();
  const withExp = allContracts.filter((c) => validateExplanation(c.explanation, c.id));
  if (withExp.length === 0) return null;
  if (withExp.length !== allContracts.length) return 'Rules applied: Evaluation snapshot unavailable for some contracts; see available per-contract explanations.';

  const firstExp = withExp[0].explanation!;
  const firstWeights = JSON.stringify(firstExp.weights);
  const firstPass = firstExp.pass_threshold;
  const firstCaution = firstExp.caution_threshold;

  const allAgree = withExp.every(
    (c) =>
      JSON.stringify(c.explanation?.weights) === firstWeights &&
      c.explanation?.pass_threshold === firstPass &&
      c.explanation?.caution_threshold === firstCaution,
  );

  if (!allAgree) {
    return 'Rules applied: Evaluation rules vary per contract (see individual contract explanations for effective weights and thresholds).';
  }

  const w = firstExp.weights;
  const wLiq = w.liquidity * 100;
  const wSpr = w.spread * 100;
  const wDel = w.delta * 100;
  const wDte = w.dte * 100;
  const wIv = w.iv_rank * 100;

  return `Rules applied: Liquidity ${wLiq}% · Spread ${wSpr}% · Delta ${wDel}% · DTE ${wDte}% · IV ${wIv}% | Status: Pass ≥ ${firstPass} · Caution ≥ ${firstCaution} · Reject < ${firstCaution}`;
}

export default function Step6Page() {
  const router = useRouter();
  const [localContractsBySymbol, setLocalContractsBySymbol] = useState<Record<string, OptionContract[]>>({});
  // The grading each symbol's rows were fetched with, set together with them,
  // so a star records exactly the inputs that graded the row on screen even if
  // scanResult is replaced while Step 6 is mounted.
  const [gradingBySymbol, setGradingBySymbol] = useState<Record<string, ContractGrading>>({});
  // Per symbol, the trade card's own contract when Step 6 had to fetch it
  // past max price / limit (lib/step6CardContract.ts). Marked in the table,
  // never Recommended, never auto-picked.
  const [rescuedBySymbol, setRescuedBySymbol] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<string>('');
  const [pick, setPick]         = useState<string>('');
  const [sortKey, setSortKey]   = useState<SortKey>('score');
  const [sortDir, setSortDir]   = useState<SortDir>('desc');
  const [offline, setOffline]   = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [expandedExplanations, setExpandedExplanations] = useState<Record<string, boolean>>({});
  // Shared ref for both mount-triggered and manual-refresh fetch so they cancel each other.
  const fetchControllerRef = useRef<AbortController | null>(null);

  const { maxContractsPerChain, maxContractPrice } = useSettingsStore();
  const scanResult              = useScanStore((s) => s.scanResult);
  const context                 = useScanStore((s) => s.context);
  const rawCandidates           = useScanStore((s) => s.scanResult?.candidates);
  const candidates              = rawCandidates ?? [];
  const pickedContracts         = useScanStore((s) => s.pickedContracts);
  const setPickedContract       = useScanStore((s) => s.setPickedContract);
  const setContractsBySymbol    = useScanStore((s) => s.setContractsBySymbol);

  // The contract rules the scan graded its trade cards with (Step-3 liquidity,
  // spread, delta, IV overrides), from the RESULT -- not live scanOverrides,
  // which can be edited after the scan. Without them /api/contracts grades on
  // contract_rules.yaml, so a Loose-profile scan's own contract showed here as
  // REJECT, score 0. Missing (absent, or null from the backend) on results from
  // before the scan recorded them, or when recording failed.
  const contractRules = scanResult?.contract_rules ?? undefined;

  const stockScoreBySymbol = Object.fromEntries(
    (scanResult?.candidates ?? []).map((c) => [c.symbol, c.stockScore ?? 70]),
  );

  const toggleExplanation = (id: string) => {
    setExpandedExplanations((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const loadContracts = useCallback(async (signal?: AbortSignal) => {
    if ((rawCandidates ?? []).length === 0) return;
    setRefreshing(true);
    setOffline(false);
    const right = (context?.direction ?? 'Bullish') === 'Bullish' ? 'C' : 'P';
    const hold = context?.holdMin != null && context?.holdMax != null
      ? sanitizeHoldDays(context.holdMin, context.holdMax)
      : undefined;
    // The request is derived FROM the grading the stars will store, so the
    // two cannot drift (WATCHLIST-SCAN-CONTRACT-RULES).
    const gradings = candidates.map((c) =>
      buildGrading(contractRules, hold, stockScoreBySymbol[c.symbol] ?? 70));
    try {
      const results = await Promise.all(
        candidates.map((c, i) => api.getContracts(c.symbol, right, {
          ...gradingToCtx(gradings[i]),
          direction:     context?.direction ?? 'Bullish',
          horizon:       context?.horizon ?? 'swing',
          limit:         maxContractsPerChain,
          max_price:     maxContractPrice,
        }, signal))
      );
      if (signal?.aborted) return;
      const rows = results.map((r) => r ?? []);
      const bySymbol: Record<string, OptionContract[]> = {};
      const gradingMap: Record<string, ContractGrading> = {};
      candidates.forEach((c, i) => { bySymbol[c.symbol] = rows[i] ?? []; gradingMap[c.symbol] = gradings[i]!; });
      setLocalContractsBySymbol(bySymbol);
      setGradingBySymbol(gradingMap);
      setContractsBySymbol(bySymbol);
      setRescuedBySymbol({});
      setExpandedExplanations((prev) => {
        const allIds = new Set<string>();
        rows.forEach((list) => list.forEach((c) => allIds.add(c.id)));
        const next: Record<string, boolean> = {};
        for (const [id, open] of Object.entries(prev)) {
          if (open && allIds.has(id)) next[id] = true;
        }
        return next;
      });
      // The selection shown is the user's OWN stored pick whenever there is
      // one -- it is what Step 7 sends -- even while its row is not (yet) in
      // the table: a rescued card contract arrives below, and until then (or
      // if the rescue fails) no row is shown selected rather than a row Step
      // 7 will not trade. With no stored pick, the auto-pick is from the
      // FILTERED rows only: a rescued card contract is outside the user's max
      // price / limit and is never chosen for them. No row: no stale id.
      const firstSymbol = candidates[0]?.symbol ?? '';
      const storedPick = pickedContracts[firstSymbol];
      setPick(storedPick ?? rows[0]?.[0]?.id ?? '');
      if (candidates[0]) setExpanded(candidates[0].symbol);
      setRefreshing(false);

      // The card's own contract, when max_price or limit cut it: asked for by
      // expiry + strike, which the backend exempts from both, with the SAME
      // grading as its table, and appended once the table is already on
      // screen. A failure leaves the table as fetched -- it is never what
      // makes Step 6 read as offline.
      const missing = missingCardContracts(candidates, rows, right);
      if (missing.length === 0) return;
      const rescued = await Promise.all(missing.map((m) =>
        api.getContracts(candidates[m.index]!.symbol, right, {
          ...gradingToCtx(gradings[m.index]),
          direction:     context?.direction ?? 'Bullish',
          horizon:       context?.horizon ?? 'swing',
          expiry:        m.expiry,
          strikes:       [m.strike],
        }, signal).catch(() => [] as OptionContract[])));
      if (signal?.aborted) return;
      const merged: Record<string, OptionContract[]> = { ...bySymbol };
      const rescuedIds: Record<string, string[]> = {};
      missing.forEach((m, k) => {
        const sym = candidates[m.index]!.symbol;
        const next = withCardContract(merged[sym] ?? [], rescued[k] ?? [], m.id);
        if (next.length > (merged[sym] ?? []).length) rescuedIds[sym] = [m.id];
        merged[sym] = next;
      });
      if (Object.keys(rescuedIds).length === 0) return;
      setLocalContractsBySymbol(merged);
      setContractsBySymbol(merged);
      setRescuedBySymbol(rescuedIds);
    } catch {
      if (!signal?.aborted) setOffline(true);
    } finally {
      if (!signal?.aborted) setRefreshing(false);
    }
  }, [rawCandidates, candidates, context, contractRules, stockScoreBySymbol, maxContractsPerChain, maxContractPrice, pickedContracts]);

  // Trigger on new scan results; abort any in-flight fetch (manual or auto) first.
  useEffect(() => {
    fetchControllerRef.current?.abort();
    const controller = new AbortController();
    fetchControllerRef.current = controller;
    loadContracts(controller.signal);
    return () => { controller.abort(); };
  }, [rawCandidates]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = () => {
    fetchControllerRef.current?.abort();
    const controller = new AbortController();
    fetchControllerRef.current = controller;
    loadContracts(controller.signal);
  };

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir(k === 'contract' ? 'asc' : 'desc');
    }
  };

  return (
    <div className={`${styles.main} ${tbl.mainOverride}`}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 7</Text>
        <Title as="h1" size={24}>Contracts</Title>
        <Text size={13} tone="secondary">
          Scored by DTE fit, delta, IV attractiveness, liquidity and spread. Click a stock to
          expand its chain. Click a column header to sort. Star a contract to track it.
        </Text>
        <div className={styles.stepHeaderActions}>
          <button
            type="button"
            className={styles.backLink}
            onClick={() => router.push('/screener/step-4-ranking')}
          >
            &larr; Back to Ranking
          </button>
          <button
            type="button"
            className={styles.refreshBtn}
            onClick={handleRefresh}
            disabled={refreshing || candidates.length === 0}
          >
            {refreshing ? 'Refreshing…' : 'Refresh prices'}
          </button>
        </div>
      </div>

      {offline && (
        <Text size={13} tone="dim">Backend not running — start it (uvicorn app.main:app --port 8000) to load live data.</Text>
      )}

      {candidates.length > 0 && contractRules === undefined && (
        <Text size={13} tone="caution">
          This scan has no recorded contract rules, so contracts below are graded on the
          default rules and may differ from the trade cards. Re-run the scan to grade them
          with the scan&apos;s own rules.
        </Text>
      )}

      {(() => {
        const banner = getGlobalRulesBanner(localContractsBySymbol);
        return banner ? (
          <div className={tbl.rulesAppliedBanner}>
            <Text size={12} tone="secondary">{banner}</Text>
          </div>
        ) : null;
      })()}

      {candidates.length === 0 && (
        <Text size={13} tone="secondary">Run a scan to see contracts.</Text>
      )}

      {candidates.length > 0 && (
        <>
          {candidates.map((candidate) => {
            const contracts  = localContractsBySymbol[candidate.symbol] ?? [];
            const isOpen     = expanded === candidate.symbol;
            const badge      = spreadBadge(candidate);
            const isSpread   = badge !== null;
            const netDC      = candidate.netDebitCredit;
            const sign       = netDC != null ? (netDC >= 0 ? '+' : '−') : null;

            // Recommended is always the highest-score contract regardless of active sort column.
            const rescuedIds  = rescuedBySymbol[candidate.symbol] ?? [];
            const byScore     = sortContracts(contracts, 'score', 'desc');
            const recommended = byScore.find((c) => !rescuedIds.includes(c.id) && !c.noLiveQuote)
              ?? byScore.find((c) => !rescuedIds.includes(c.id));
            // User sort applies to the remaining (chain) contracts.
            const sorted = sortContracts(contracts, sortKey, sortDir);
            const chain  = sorted.filter((c) => c.id !== recommended?.id);

            /** Renders a single contract row, reused for recommended + chain. */
            const renderRow = (c: OptionContract, extra?: { className?: string }) => {
              const status = c.contractConfidence;
              return (
                <TableRow
                  key={c.id}
                  status={status}
                  columns={COLUMNS}
                  selected={c.id === pick}
                  onClick={() => {
                    setPick(c.id);
                    setPickedContract(candidate.symbol, c.id);
                  }}
                  className={`${tbl.contractRow} ${extra?.className ?? ''}`}
                >
                  <ContractStar contractId={c.id} grading={gradingBySymbol[candidate.symbol]} size="sm" />
                  <Data size={13} weight={500}>
                    {contractLabel(c)}
                    {rescuedIds.includes(c.id) && (
                      <span title="The trade card's own contract. It was not in the filtered table -- above your max contract price, past the contracts-per-chain limit, or on a different expiry from the one this table lists -- and is shown so you can still see and pick it.">
                        <Text size={10} tone="caution">{' card · not in filtered table'}</Text>
                      </span>
                    )}
                  </Data>
                  <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
                  <Data size={12} className={tbl.right}>{c.delta.toFixed(2)}</Data>
                  <Data size={12} className={tbl.right}>${c.price.toFixed(2)}</Data>
                  <IvCell contract={c} />
                  <Data size={12} className={tbl.right}>${c.spread.toFixed(2)}</Data>
                  <div className={tbl.scoreCell}>
                    <Data size={13} weight={500}>{c.score}</Data>
                    <StatusBadge status={status} tooltip={getExplanationSummaryLine(c)} tooltipAlign="right" />
                    <NoLiveQuoteTag noLiveQuote={c.noLiveQuote} quoteState={c.quoteState} />
                  </div>
                  <ContractExplanationToggle
                    isOpen={!!expandedExplanations[c.id]}
                    onToggle={() => toggleExplanation(c.id)}
                    controlsId={`explanation-${c.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                    contractLabel={contractLabel(c)}
                  />
                  <span
                    aria-label={c.id === pick ? 'Selected' : 'Select'}
                    className={tbl.pickDot}
                    data-selected={c.id === pick ? 'true' : 'false'}
                  />
                </TableRow>
              );
            };

            return (
              <div key={candidate.symbol} className={tbl.group}>
                {/* Group header — symbol + contract count */}
                <div className={tbl.groupHeaderRow}>
                  <button
                    type="button"
                    className={tbl.groupHeader}
                    onClick={() => setExpanded(isOpen ? '' : candidate.symbol)}
                    aria-expanded={isOpen}
                  >
                    <Text size={13} weight={500}>{candidate.symbol}</Text>
                    {badge && (
                      <span className={tbl.spreadBadgeInline}>
                        <Text size={10} weight={500}>{badge}</Text>
                      </span>
                    )}
                    <Text size={11} tone="secondary">
                      {contracts.length - rescuedIds.length} contracts{rescuedIds.length > 0 ? ' + card' : ''}
                    </Text>
                    <span className={`${tbl.chevron} ${isOpen ? tbl.chevronOpen : ''}`} aria-hidden>&#x203A;</span>
                  </button>
                  <button
                    className={tbl.chartBtn}
                    title="Open in Chart"
                    onClick={(e) => { e.stopPropagation(); window.open(`/chart?symbol=${candidate.symbol}`, '_blank'); }}
                  >
                    📈
                  </button>
                </div>

                {isOpen && (
                  // role="table" marks this as the per-symbol contracts table for screen
                  // readers and for any future e2e test that seeds scan data and asserts on it
                  // via getByRole('table').
                  <div role="table" className={tbl.groupBody}>
                    {/* Candidate spread snapshot banner */}
                    {isSpread && (
                      <div className={tbl.spreadSnapshot}>
                        <Text size={11} weight={600} tone="primary">
                          Candidate spread snapshot ({candidate.spreadType === 'bear_put' ? 'Bear Put Spread' : candidate.spreadType === 'bear_call' ? 'Bear Call Spread' : candidate.spreadType}):
                        </Text>
                        <Text size={11} tone="secondary">
                          Net D/C: <Data size={11}>{netDC != null ? `${sign}$${Math.abs(netDC).toFixed(2)}` : '—'}</Data>
                        </Text>
                        <Text size={11} tone="secondary">
                          Max Gain: <Data size={11}>{candidate.maxProfit != null ? `$${candidate.maxProfit.toFixed(2)}` : '—'}</Data>
                        </Text>
                        <Text size={11} tone="secondary">
                          Max Loss: <Data size={11}>{candidate.maxLoss != null ? `$${candidate.maxLoss.toFixed(2)}` : '—'}</Data>
                        </Text>
                        <Text size={11} tone="secondary">
                          Breakeven: <Data size={11}>{candidate.breakeven != null ? `$${candidate.breakeven.toFixed(2)}` : '—'}</Data>
                        </Text>
                      </div>
                    )}

                    {/* Sort toolbar allowing sort by any of 10 metrics */}
                    <div className={tbl.sortToolbar}>
                      <label className={tbl.sortLabel} htmlFor={`sort-${candidate.symbol}`}>
                        Sort chain by:
                        <select
                          id={`sort-${candidate.symbol}`}
                          className={tbl.sortSelect}
                          value={sortKey}
                          onChange={(e) => setSortKey(e.target.value as SortKey)}
                        >
                          <option value="score">Score</option>
                          <option value="contract">Contract</option>
                          <option value="dte">DTE</option>
                          <option value="delta">Delta</option>
                          <option value="price">Price</option>
                          <option value="ivRank">{ivColumnLabel(ivBasesOf(contracts))}</option>
                          <option value="ivPercentile">IV Percentile</option>
                          <option value="theta">Theta (Θ/day)</option>
                          <option value="spread">Spread</option>
                          <option value="volume">Volume</option>
                        </select>
                      </label>
                      <button
                        type="button"
                        className={tbl.sortDirBtn}
                        onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                        title={`Current: ${sortDir.toUpperCase()}. Click to switch to ${sortDir === 'asc' ? 'DESC' : 'ASC'}`}
                        aria-label={`Sort direction: ${sortDir}`}
                      >
                        <Text size={11} weight={500}>{sortDir === 'asc' ? 'Asc ↑' : 'Desc ↓'}</Text>
                      </button>
                    </div>

                    {/* Compact sticky header */}
                    <div className={tbl.headerRow} style={{ gridTemplateColumns: COLUMNS, position: 'relative', top: 0 }}>
                      <span aria-hidden />
                      <SortBtn label="CONTRACT" k="contract" sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
                      <SortBtn label="DTE"      k="dte"      sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
                      <SortBtn label="DELTA"    k="delta"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="PRICE"    k="price"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label={ivColumnLabel(ivBasesOf(contracts))} k="ivRank" sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="SPREAD"   k="spread"   sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="SCORE"    k="score"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <Text size={11} tone="dim">EXPLAIN</Text>
                      <Text size={11} tone="dim">PICK</Text>
                    </div>

                    {recommended && (
                      <Fragment key={recommended.id}>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>A — RECOMMENDED</Text>
                        </div>
                        {renderRow(recommended, { className: tbl.recommendedRow })}
                        {expandedExplanations[recommended.id] && (
                          <ContractScoreExplanation
                            id={`explanation-${recommended.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                            contract={recommended}
                          />
                        )}
                      </Fragment>
                    )}

                    {chain.length > 0 && (
                      <>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>B — FULL CHAIN</Text>
                        </div>
                        {chain.map((c) => (
                          <Fragment key={c.id}>
                            {renderRow(c)}
                            {expandedExplanations[c.id] && (
                              <ContractScoreExplanation
                                id={`explanation-${c.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                                contract={c}
                              />
                            )}
                          </Fragment>
                        ))}
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function SortBtn({
  label,
  k,
  sortKey,
  dir,
  onClick,
  align,
}: {
  label:   string;
  k:       SortKey;
  sortKey: SortKey;
  dir:     SortDir;
  onClick: (k: SortKey) => void;
  align?:  'left' | 'right';
}) {
  const active = sortKey === k;
  return (
    <button
      type="button"
      onClick={() => onClick(k)}
      className={`${tbl.sortBtn} ${align === 'right' ? tbl.sortRight : ''} ${active ? tbl.sortActive : ''}`}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  );
}
