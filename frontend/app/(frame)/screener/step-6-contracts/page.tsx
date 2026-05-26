'use client';

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { statusForScore } from '@/lib/status';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { contractLabel, type OptionContract } from '@/types/domain';
import styles from '../screener.module.css';
import tbl from './contracts.module.css';

const COLUMNS = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 96px 44px';

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
  rows.sort((a, b) => {
    switch (key) {
      case 'contract':
        return contractLabel(a).localeCompare(contractLabel(b)) * mul;
      default:
        return ((a[key] as number) - (b[key] as number)) * mul;
    }
  });
  return rows;
}

export default function Step6Page() {
  const [contractsBySymbol, setContractsBySymbol] = useState<Record<string, OptionContract[]>>({});
  const [expanded, setExpanded] = useState<string>('');
  const [pick, setPick]         = useState<string>('');
  const [sortKey, setSortKey]   = useState<SortKey>('score');
  const [sortDir, setSortDir]   = useState<SortDir>('desc');
  const [offline, setOffline]   = useState(false);

  const { maxContractsPerChain, maxContractPrice } = useSettingsStore();
  const scanResult = useScanStore((s) => s.scanResult);
  const context    = useScanStore((s) => s.context);
  const candidates = useScanStore((s) => s.scanResult?.candidates ?? []);

  const stockScoreBySymbol = Object.fromEntries(
    (scanResult?.candidates ?? []).map((c) => [c.symbol, c.stockScore ?? 70]),
  );

  useEffect(() => {
    if (candidates.length === 0) return;
    setOffline(false);
    Promise.all(candidates.map((c) => api.getContracts(c.symbol, 'C', {
      stock_score: stockScoreBySymbol[c.symbol] ?? 70,
      direction:   context?.direction ?? 'Bullish',
      horizon:     context?.horizon ?? 'swing',
      limit:       maxContractsPerChain,
      max_price:   maxContractPrice,
    })))
      .then((results) => {
        const bySymbol: Record<string, OptionContract[]> = {};
        candidates.forEach((c, i) => { bySymbol[c.symbol] = results[i] ?? []; });
        setContractsBySymbol(bySymbol);
        const first = results[0]?.[0];
        if (first) setPick(first.id);
        if (candidates[0]) setExpanded(candidates[0].symbol);
      })
      .catch(() => setOffline(true));
  }, [candidates]);

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
      </div>

      {offline && (
        <Text size={13} tone="dim">Backend not running — start start-backend.bat to load live data.</Text>
      )}

      {candidates.length === 0 && (
        <Text size={13} tone="secondary">Run a scan to see contracts.</Text>
      )}

      {candidates.length > 0 && (
        <>
          <div className={tbl.headerRow} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <SortBtn label="CONTRACT" k="contract"     sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
            <SortBtn label="DTE"      k="dte"          sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
            <SortBtn label="DELTA"    k="delta"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="PRICE"    k="price"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="IV RANK"  k="ivRank"       sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="IV PCTL"  k="ivPercentile" sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="Θ/DAY"    k="theta"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="SPREAD"   k="spread"       sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="VOL"      k="volume"       sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <SortBtn label="SCORE"    k="score"        sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
            <Text size={11} tone="dim">PICK</Text>
          </div>

          {candidates.map((candidate) => {
            const contracts = contractsBySymbol[candidate.symbol] ?? [];
            const isOpen = expanded === candidate.symbol;
            // Recommended is always the highest-score contract regardless of active sort column.
            const byScore      = sortContracts(contracts, 'score', 'desc');
            const recommended  = byScore[0];
            // User sort applies to the remaining (chain) contracts.
            const sorted = sortContracts(contracts, sortKey, sortDir);
            const chain  = sorted.filter((c) => c.id !== recommended?.id);
            return (
              <div key={candidate.symbol} className={tbl.group}>
                <button
                  type="button"
                  className={tbl.groupHeader}
                  onClick={() => setExpanded(isOpen ? '' : candidate.symbol)}
                  aria-expanded={isOpen}
                >
                  <Text size={13} weight={500}>{candidate.symbol}</Text>
                  <Text size={11} tone="secondary">{contracts.length} contracts</Text>
                  <span className={`${tbl.chevron} ${isOpen ? tbl.chevronOpen : ''}`} aria-hidden>&#x203A;</span>
                </button>

                {isOpen && (
                  <div className={tbl.groupBody}>
                    {recommended && (
                      <>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>A — RECOMMENDED</Text>
                        </div>
                        {(() => {
                          const c = recommended;
                          const status = statusForScore(c.score);
                          return (
                            <TableRow
                              key={c.id}
                              status={status}
                              columns={COLUMNS}
                              selected={c.id === pick}
                              onClick={() => setPick(c.id)}
                              className={tbl.recommendedRow}
                            >
                              <ContractStar contractId={c.id} size="sm" />
                              <Data size={13} weight={500}>{contractLabel(c)}</Data>
                              <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
                              <Data size={12} className={tbl.right}>{c.delta.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>${c.price.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>{c.ivRank}</Data>
                              <Data size={12} className={tbl.right}>{c.ivPercentile}</Data>
                              <Data size={12} className={tbl.right}>{c.theta.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>${c.spread.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>{c.volume.toLocaleString()}</Data>
                              <div className={tbl.scoreCell}>
                                <Data size={13} weight={500}>{c.score}</Data>
                                <StatusBadge status={status} />
                              </div>
                              <span
                                aria-label={c.id === pick ? 'Selected' : 'Select'}
                                className={tbl.pickDot}
                                data-selected={c.id === pick ? 'true' : 'false'}
                              />
                            </TableRow>
                          );
                        })()}
                      </>
                    )}

                    {chain.length > 0 && (
                      <>
                        <div className={tbl.sectionLabel}>
                          <Text size={10} tone="dim" weight={500}>B — TOP {chain.length}</Text>
                        </div>
                        {chain.map((c) => {
                          const status = statusForScore(c.score);
                          return (
                            <TableRow
                              key={c.id}
                              status={status}
                              columns={COLUMNS}
                              selected={c.id === pick}
                              onClick={() => setPick(c.id)}
                            >
                              <ContractStar contractId={c.id} size="sm" />
                              <Data size={13} weight={500}>{contractLabel(c)}</Data>
                              <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
                              <Data size={12} className={tbl.right}>{c.delta.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>${c.price.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>{c.ivRank}</Data>
                              <Data size={12} className={tbl.right}>{c.ivPercentile}</Data>
                              <Data size={12} className={tbl.right}>{c.theta.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>${c.spread.toFixed(2)}</Data>
                              <Data size={12} className={tbl.right}>{c.volume.toLocaleString()}</Data>
                              <div className={tbl.scoreCell}>
                                <Data size={13} weight={500}>{c.score}</Data>
                                <StatusBadge status={status} />
                              </div>
                              <span
                                aria-label={c.id === pick ? 'Selected' : 'Select'}
                                className={tbl.pickDot}
                                data-selected={c.id === pick ? 'true' : 'false'}
                              />
                            </TableRow>
                          );
                        })}
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
