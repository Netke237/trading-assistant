'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { contractScoreTooltip } from '@/lib/statusTooltips';
import { api } from '@/lib/api';
import { sanitizeHoldDays } from '@/lib/horizonPresets';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { contractLabel, type OptionContract, type TradeCardData } from '@/types/domain';
import { resolveIv, formatIv, ivSortValue, ivColumnLabel, ivBasesOf } from '@/lib/ivBasis';
import styles from '../screener.module.css';
import tbl from './contracts.module.css';

// Single-leg column template (12 cols)
const COLUMNS_SINGLE = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 96px 44px';
// Spread column template — adds 5 spread cols before PICK
const COLUMNS_SPREAD  = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 96px 52px 80px 80px 80px 80px 44px';

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

/** The IV cell. Shows a TRUE PERCENTILE when one exists and an ABSOLUTE
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

export default function Step6Page() {
  const router = useRouter();
  const [localContractsBySymbol, setLocalContractsBySymbol] = useState<Record<string, OptionContract[]>>({});
  const [expanded, setExpanded] = useState<string>('');
  const [pick, setPick]         = useState<string>('');
  const [sortKey, setSortKey]   = useState<SortKey>('score');
  const [sortDir, setSortDir]   = useState<SortDir>('desc');
  const [offline, setOffline]   = useState(false);
  const [refreshing, setRefreshing] = useState(false);
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

  const stockScoreBySymbol = Object.fromEntries(
    (scanResult?.candidates ?? []).map((c) => [c.symbol, c.stockScore ?? 70]),
  );

  const loadContracts = useCallback(async (signal?: AbortSignal) => {
    if ((rawCandidates ?? []).length === 0) return;
    setRefreshing(true);
    setOffline(false);
    const right = (context?.direction ?? 'Bullish') === 'Bullish' ? 'C' : 'P';
    const hold = context?.holdMin != null && context?.holdMax != null
      ? sanitizeHoldDays(context.holdMin, context.holdMax)
      : undefined;
    try {
      const results = await Promise.all(
        candidates.map((c) => api.getContracts(c.symbol, right, {
          stock_score:   stockScoreBySymbol[c.symbol] ?? 70,
          direction:     context?.direction ?? 'Bullish',
          horizon:       context?.horizon ?? 'swing',
          limit:         maxContractsPerChain,
          max_price:     maxContractPrice,
          hold_min_days: hold?.hold_min_days,
          hold_max_days: hold?.hold_max_days,
        }, signal))
      );
      if (signal?.aborted) return;
      const bySymbol: Record<string, OptionContract[]> = {};
      candidates.forEach((c, i) => { bySymbol[c.symbol] = results[i] ?? []; });
      setLocalContractsBySymbol(bySymbol);
      setContractsBySymbol(bySymbol);
      const firstSymbol = candidates[0]?.symbol ?? '';
      const storedPick = pickedContracts[firstSymbol];
      const first = storedPick
        ? bySymbol[firstSymbol]?.find((c) => c.id === storedPick) ?? results[0]?.[0]
        : results[0]?.[0];
      if (first) setPick(first.id);
      if (candidates[0]) setExpanded(candidates[0].symbol);
    } catch {
      if (!signal?.aborted) setOffline(true);
    } finally {
      if (!signal?.aborted) setRefreshing(false);
    }
  }, [rawCandidates, candidates, context, stockScoreBySymbol, maxContractsPerChain, maxContractPrice, pickedContracts]);

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
    <div className={styles.main}>
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
            const COLUMNS    = isSpread ? COLUMNS_SPREAD : COLUMNS_SINGLE;

            // Recommended is always the highest-score contract regardless of active sort column.
            const byScore     = sortContracts(contracts, 'score', 'desc');
            const recommended = byScore[0];
            // User sort applies to the remaining (chain) contracts.
            const sorted = sortContracts(contracts, sortKey, sortDir);
            const chain  = sorted.filter((c) => c.id !== recommended?.id);

            /** Renders a single contract row, reused for recommended + chain. */
            const renderRow = (c: OptionContract, extra?: { className?: string }) => {
              const status = c.contractConfidence;
              const netDC = candidate.netDebitCredit;
              const sign  = netDC != null ? (netDC >= 0 ? '+' : '−') : null;
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
                  className={extra?.className}
                >
                  <ContractStar contractId={c.id} size="sm" />
                  <Data size={13} weight={500}>{contractLabel(c)}</Data>
                  <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
                  <Data size={12} className={tbl.right}>{c.delta.toFixed(2)}</Data>
                  <Data size={12} className={tbl.right}>${c.price.toFixed(2)}</Data>
                  <IvCell contract={c} />
                  <Data size={12} className={tbl.right}>{c.ivPercentile != null ? c.ivPercentile : '—'}</Data>
                  <Data size={12} className={tbl.right}>{c.theta.toFixed(2)}</Data>
                  <Data size={12} className={tbl.right}>${c.spread.toFixed(2)}</Data>
                  <Data size={12} className={tbl.right}>{c.volume.toLocaleString()}</Data>
                  <div className={tbl.scoreCell}>
                    <Data size={13} weight={500}>{c.score}</Data>
                    <StatusBadge status={status} tooltip={contractScoreTooltip(c)} />
                  </div>
                  {isSpread && (
                    <>
                      <span className={tbl.spreadBadge}>
                        <Text size={10} weight={500}>{badge}</Text>
                      </span>
                      <Data size={12} className={`${tbl.right} ${tbl.spreadCell}`}>
                        {netDC != null ? `${sign}$${Math.abs(netDC).toFixed(2)}` : '—'}
                      </Data>
                      <Data size={12} className={`${tbl.right} ${tbl.spreadCell}`}>
                        {candidate.maxProfit != null ? `$${candidate.maxProfit.toFixed(2)}` : '—'}
                      </Data>
                      <Data size={12} className={`${tbl.right} ${tbl.spreadCell}`}>
                        {candidate.maxLoss != null ? `$${candidate.maxLoss.toFixed(2)}` : '—'}
                      </Data>
                      <Data size={12} className={`${tbl.right} ${tbl.spreadCell}`}>
                        {candidate.breakeven != null ? `$${candidate.breakeven.toFixed(2)}` : '—'}
                      </Data>
                    </>
                  )}
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
                    <Text size={11} tone="secondary">{contracts.length} contracts</Text>
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
                    {/* Sticky sub-header per group so spread columns have labels */}
                    <div className={tbl.headerRow} style={{ gridTemplateColumns: COLUMNS, position: 'relative', top: 0 }}>
                      <span aria-hidden />
                      <SortBtn label="CONTRACT" k="contract"     sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
                      <SortBtn label="DTE"      k="dte"          sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
                      <SortBtn label="DELTA"    k="delta"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="PRICE"    k="price"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label={ivColumnLabel(ivBasesOf(contracts))} k="ivRank" sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="IV PCTL"  k="ivPercentile" sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="Θ/DAY"    k="theta"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="SPREAD"   k="spread"       sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="VOL"      k="volume"       sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      <SortBtn label="SCORE"    k="score"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                      {isSpread && (
                        <>
                          <Text size={11} tone="dim" className={tbl.sortBtn}>TYPE</Text>
                          <Text size={11} tone="dim" className={`${tbl.sortBtn} ${tbl.sortRight}`}>NET D/C</Text>
                          <Text size={11} tone="dim" className={`${tbl.sortBtn} ${tbl.sortRight}`}>MAX GAIN</Text>
                          <Text size={11} tone="dim" className={`${tbl.sortBtn} ${tbl.sortRight}`}>MAX LOSS</Text>
                          <Text size={11} tone="dim" className={`${tbl.sortBtn} ${tbl.sortRight}`}>B/E</Text>
                        </>
                      )}
                      <Text size={11} tone="dim">PICK</Text>
                    </div>

                    {recommended && (
                      <>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>A — RECOMMENDED</Text>
                        </div>
                        {renderRow(recommended, { className: tbl.recommendedRow })}
                      </>
                    )}

                    {chain.length > 0 && (
                      <>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>B — FULL CHAIN</Text>
                        </div>
                        {chain.map((c) => renderRow(c))}
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
