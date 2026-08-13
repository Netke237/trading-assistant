'use client';

/*
 * /dev/components — dev-only visual gallery of every atom + molecule.
 * Serves as a smoke test for token application, font enforcement, theme
 * switching, and status variants. Not linked from production nav.
 *
 * Client component so TableRow onClick handlers work — this is a dev tool,
 * no SEO concern.
 */

import { notFound } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ScoreBar } from '@/components/atoms/ScoreBar';
import { EventFlag } from '@/components/atoms/EventFlag';
import { RankDelta } from '@/components/atoms/RankDelta';
import { StatusDot } from '@/components/atoms/StatusDot';
import { IconButton } from '@/components/atoms/IconButton';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { TableRow } from '@/components/molecules/TableRow';
import { SectionCard } from '@/components/molecules/SectionCard';
import { StepIndicator } from '@/components/molecules/StepIndicator';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { AlertRow } from '@/components/molecules/AlertRow';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import type { Status } from '@/lib/status';
import styles from './page.module.css';

const ALL_STATUSES: Status[] = ['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'];

export default function ComponentsGallery() {
  if (process.env.NODE_ENV !== 'development') notFound();
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Title as="h1" size={24}>
          Component Gallery
        </Title>
        <ModeToggle />
      </header>

      {/* ---------------- Typography ---------------- */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <Text size={10} tone="secondary">
            Primitives
          </Text>
        </div>

        <div className={styles.stack}>
          <Title as="h2" size={32}>
            Sora 32 bold
          </Title>
          <Title as="h2" size={24}>
            Sora 24 bold
          </Title>
          <Title as="h2" size={20}>
            Sora 20 bold
          </Title>
          <Text size={16} weight={600}>
            DM Sans 16 / 600
          </Text>
          <Text size={14} weight={500}>
            DM Sans 14 / 500 — nav item
          </Text>
          <Text size={13}>DM Sans 13 / 400 — body</Text>
          <Text size={12} tone="secondary">
            DM Sans 12 / 400 secondary
          </Text>
          <Text size={10} tone="secondary">
            DM Sans 10 uppercase
          </Text>
          <Data size={24} weight={500}>
            185.20 · AAPL · 87/100
          </Data>
          <Data size={14}>14px mono · 09:42 · 2.4:1</Data>
          <Data size={11} tone="dim">
            11px mono dim
          </Data>
        </div>
      </section>

      {/* ---------------- Atoms ---------------- */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <Text size={10} tone="secondary">
            Atoms
          </Text>
        </div>

        <Text size={12} tone="secondary" as="p">
          StatusBadge — all statuses
        </Text>
        <div className={styles.group}>
          {ALL_STATUSES.map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>

        <Text size={12} tone="secondary" as="p">
          ScoreBar — fill color driven by value
        </Text>
        <div className={styles.stack}>
          <ScoreBar label="Trend" value={85} />
          <ScoreBar label="Pullback" value={64} />
          <ScoreBar label="Trigger" value={41} />
          <ScoreBar label="Event" value={22} max={30} displayValue="22/30" />
        </div>

        <Text size={12} tone="secondary" as="p">
          EventFlag — proximity ranges
        </Text>
        <div className={styles.group}>
          <EventFlag days={14} title="Earnings" />
          <EventFlag days={7} title="FOMC" />
          <EventFlag days={5} title="Earnings" />
          <EventFlag days={3} title="Earnings" />
          <EventFlag days={1} title="Earnings" />
        </div>

        <Text size={12} tone="secondary" as="p">
          RankDelta
        </Text>
        <div className={styles.group}>
          <RankDelta value={3} />
          <RankDelta value={1} />
          <RankDelta value={0} />
          <RankDelta value={-2} />
          <RankDelta value={-5} />
        </div>

        <Text size={12} tone="secondary" as="p">
          StatusDot
        </Text>
        <div className={styles.group}>
          <StatusDot tone="PASS" />
          <StatusDot tone="CAUTION" />
          <StatusDot tone="REJECT" />
          <StatusDot tone="PENDING" />
          <StatusDot tone="ACCENT" />
          <StatusDot tone="PASS" size="sm" />
        </div>

        <Text size={12} tone="secondary" as="p">
          IconButton
        </Text>
        <div className={styles.group}>
          <IconButton aria-label="Close" bordered>
            <XIcon />
          </IconButton>
          <IconButton aria-label="Filter">
            <FilterIcon />
          </IconButton>
          <IconButton aria-label="Close" size="sm">
            <XIcon />
          </IconButton>
          <IconButton aria-label="Close" size="lg" bordered>
            <XIcon />
          </IconButton>
        </div>
      </section>

      {/* ---------------- Molecules ---------------- */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <Text size={10} tone="secondary">
            Molecules
          </Text>
        </div>

        <Text size={12} tone="secondary" as="p">
          TableRow — all status tints
        </Text>
        <div className={styles.rowsContainer}>
          <div
            className={styles.columnHeader}
            style={{ gridTemplateColumns: '60px 1fr 60px 80px 60px' }}
          >
            <Text size={10} tone="secondary">Sym</Text>
            <Text size={10} tone="secondary">Company</Text>
            <Text size={10} tone="secondary">Score</Text>
            <Text size={10} tone="secondary">Status</Text>
            <Text size={10} tone="secondary">Event</Text>
          </div>
          {([
            { status: 'PASS',    sym: 'AAPL', co: 'Apple Inc',       score: 87, days: 14 },
            { status: 'PASS',    sym: 'MSFT', co: 'Microsoft Corp',  score: 82, days: 9 },
            { status: 'CAUTION', sym: 'NVDA', co: 'NVIDIA Corp',     score: 64, days: 5 },
            { status: 'REJECT',  sym: 'META', co: 'Meta Platforms',  score: 41, days: 21 },
            { status: 'PENDING', sym: 'AMD',  co: 'Adv. Micro Dev.', score: 0,  days: 3 },
          ] as const).map((r) => (
            <TableRow
              key={r.sym}
              status={r.status}
              columns="60px 1fr 60px 80px 60px"
            >
              <Data size={13} weight={500}>{r.sym}</Data>
              <Text size={13} tone="secondary">{r.co}</Text>
              <Data size={12}>{r.score || '—'}</Data>
              <StatusBadge status={r.status} />
              <EventFlag days={r.days} />
            </TableRow>
          ))}
        </div>

        <Text size={12} tone="secondary" as="p">
          SectionCard
        </Text>
        <div className={styles.grid2}>
          <SectionCard title="Watchlist" count={8} action={{ label: 'View all' }}>
            <Text size={13} tone="secondary">
              Rows go here. This is just the card chrome.
            </Text>
          </SectionCard>
          <SectionCard title="Alerts" count={3}>
            <div className={styles.alertsList}>
              <AlertRow kind="Critical" symbol="AAPL" reason="Stop-loss approaching" timestamp="09:42" />
              <AlertRow kind="Action" symbol="MSFT" reason="Entry trigger fired" timestamp="09:38" />
              <AlertRow kind="Info" symbol="NVDA" reason="Earnings in 3 days" timestamp="09:15" />
            </div>
          </SectionCard>
        </div>

        <Text size={12} tone="secondary" as="p">
          StepIndicator — all 3 states
        </Text>
        <div className={styles.stack}>
          <StepIndicator index={1} label="Universe" state="completed" />
          <StepIndicator index={2} label="Direction + Horizon" state="completed" />
          <StepIndicator index={3} label="Market Regime" state="completed" />
          <StepIndicator index={4} label="Stock Ranking" state="current" />
          <StepIndicator index={5} label="Vol + Events" state="future" />
          <StepIndicator index={6} label="Contracts" state="future" />
          <StepIndicator index={7} label="Trade Card" state="future" />
        </div>

        <Text size={12} tone="secondary" as="p">
          ScoreCardPanel
        </Text>
        <div className={styles.stack}>
          <ScoreCardPanel
            title="Stock Score"
            bars={[
              { label: 'Trend',      value: 26, max: 30, displayValue: '26/30' },
              { label: 'Pullback',   value: 18, max: 20, displayValue: '18/20' },
              { label: 'Trigger',    value: 14, max: 20, displayValue: '14/20' },
              { label: 'Event',      value: 15, max: 15, displayValue: '15/15' },
              { label: 'Volatility', value: 14, max: 15, displayValue: '14/15' },
            ]}
            total={87}
            confidence="PASS"
          />
        </div>

        <Text size={12} tone="secondary" as="p">
          DTEProgressBar
        </Text>
        <div className={styles.stack}>
          <DTEProgressBar daysRemaining={38} totalDays={45} />
          <DTEProgressBar daysRemaining={22} totalDays={45} />
          <DTEProgressBar daysRemaining={6}  totalDays={45} />
        </div>

        <Text size={12} tone="secondary" as="p">
          SymbolHeader
        </Text>
        <div className={styles.stack}>
          <SymbolHeader
            ticker="AAPL"
            company="Apple Inc"
            price={185.2}
            direction="Bullish"
            status="PASS"
            size={24}
          />
          <SymbolHeader
            ticker="META"
            company="Meta Platforms"
            price={512.07}
            direction="Bearish"
            status="CAUTION"
            size={18}
          />
        </div>
      </section>
    </div>
  );
}

function XIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}
