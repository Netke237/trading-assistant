'use client';

/*
 * Portfolio — Phase 5.
 * Open positions table with DTE progress bars, sticky totals footer, and
 * inline in-memory edit. Click the pencil to change stop / target / size
 * or close the position (removed from local state — mock only).
 */

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PortfolioPosition } from '@/types/domain';
import styles from './page.module.css';

function ivRankTone(rk: number | undefined): 'pass' | 'caution' | 'reject' | undefined {
  if (rk === undefined) return undefined;
  if (rk >= 70) return 'reject';      // very rich
  if (rk >= 40) return 'caution';     // moderate
  return 'pass';                      // cheap
}

const COLUMNS = '72px 1.6fr 72px 1fr 110px 104px 60px 56px 60px 90px 40px';

export default function PortfolioPage() {
  const positions      = usePortfolioStore((s) => s.positions);
  const updatePosition = usePortfolioStore((s) => s.updatePosition);
  const closeInStore   = usePortfolioStore((s) => s.closePosition);
  const [editing, setEditing] = useState<string | null>(null);

  const deployed = positions.reduce((s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1), 0);
  const openPnL  = positions.reduce((s, p) => s + p.pnlDollar, 0);
  const openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0;
  const winners = positions.filter((p) => p.pnlDollar > 0).length;
  const losers  = positions.filter((p) => p.pnlDollar < 0).length;

  const closePosition = (contract: string) => {
    closeInStore(contract);
    setEditing(null);
  };

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Portfolio</Title>
        <Text size={13} tone="secondary">{positions.length} open positions</Text>
      </div>

      <div className={styles.tableWrap}>
        <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <Text size={11} tone="dim">SYMBOL</Text>
          <Text size={11} tone="dim">CONTRACT</Text>
          <Text size={11} tone="dim">DIR</Text>
          <Text size={11} tone="dim">DTE</Text>
          <Text size={11} tone="dim" className={styles.right}>ENTRY → NOW</Text>
          <Text size={11} tone="dim" className={styles.right}>P&amp;L</Text>
          <Text size={11} tone="dim" className={styles.right}>IV RK</Text>
          <Text size={11} tone="dim" className={styles.right}>Δ</Text>
          <Text size={11} tone="dim" className={styles.right}>Θ/DAY</Text>
          <Text size={11} tone="dim">STATUS</Text>
          <span aria-hidden />
        </div>

        <div className={styles.tableBody}>
          {positions.map((p) => (
            <div key={p.contract} className={styles.rowWrap}>
              <TableRow status={p.status} columns={COLUMNS}>
                <Data size={13} weight={500}>{p.symbol}</Data>
                <span className={styles.contractCell}>
                  <Text size={12} tone="secondary">{p.contract}</Text>
                  {p.source === 'manual' && <span className={styles.srcManual}>MANUAL</span>}
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
                <StatusBadge status={p.status} />
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
                  onRemove={() => closePosition(p.contract)}
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
            <Text size={11} tone="secondary">Open P&amp;L</Text>
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
    </div>
  );
}

/* ---------- Edit drawer ---------- */

function EditDrawer({
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
  return (
    <div className={styles.editDrawer}>
      <div className={styles.editHeader}>
        <Text size={12} weight={400}>Edit {position.contract}</Text>
        <button type="button" className={styles.editClose} onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <div className={styles.editGrid}>
        <EditField
          label="Stop"
          hint="Exit if position drops below this option price."
          value={position.stop}
          onChange={(n) => onChange({ stop: n })}
        />
        <EditField
          label="Target"
          hint="First take-profit level."
          value={position.target}
          onChange={(n) => onChange({ target: n })}
        />
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
            const pnlDollar = (n - position.entryPrice) * 100 * (position.contracts ?? 1);
            const pnlPct    = ((n - position.entryPrice) / position.entryPrice) * 100;
            onChange({ currentPrice: n, pnlDollar, pnlPct });
          }}
        />
      </div>

      <div className={styles.editFooter}>
        <Text size={11} tone="secondary">
          Changes stay local to this session. Hooking broker write APIs is a Phase 7 task.
        </Text>
        <button type="button" className={styles.editRemove} onClick={onRemove}>
          Close position
        </button>
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
