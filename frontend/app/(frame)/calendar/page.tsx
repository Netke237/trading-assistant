'use client';

/*
 * Calendar — month-grid view.
 * Shows 2 months side-by-side (responsive: wraps on narrow screens).
 * Event dots on days that have events, colored by gate status.
 * Click a day → detail panel below lists that day's events.
 * Prev / Next cycles months; Today jumps back to current.
 */

import { useEffect, useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { EventFlag } from '@/components/atoms/EventFlag';
import { eventProximityGateTooltip } from '@/lib/statusTooltips';
import { api } from '@/lib/api';
import type { UpcomingEvent } from '@/types/domain';
import type { Status } from '@/lib/status';
import styles from './page.module.css';

const TODAY = new Date();

const WEEK_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

interface DayCell {
  iso:        string;        // YYYY-MM-DD
  dayNum:     number;
  inMonth:    boolean;
  isToday:    boolean;
  events:     UpcomingEvent[];
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function isoForUTC(d: Date): string {
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

/**
 * Build a 6-week grid (42 cells) for the month containing `anchor`.
 * Week starts Monday. Leading/trailing days from adjacent months are
 * included but flagged with `inMonth: false`.
 */
function buildMonthGrid(anchor: Date, eventsByDate: Map<string, UpcomingEvent[]>): DayCell[] {
  const year  = anchor.getUTCFullYear();
  const month = anchor.getUTCMonth();
  const firstOfMonth = new Date(Date.UTC(year, month, 1));
  // JS weekday: 0=Sun..6=Sat. Shift so Monday=0.
  const firstWeekday = (firstOfMonth.getUTCDay() + 6) % 7;
  // Start grid on the Monday on or before the 1st.
  const gridStart = new Date(Date.UTC(year, month, 1 - firstWeekday));
  const todayIso  = isoForUTC(TODAY);

  const cells: DayCell[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setUTCDate(gridStart.getUTCDate() + i);
    const iso = isoForUTC(d);
    cells.push({
      iso,
      dayNum:  d.getUTCDate(),
      inMonth: d.getUTCMonth() === month,
      isToday: iso === todayIso,
      events:  eventsByDate.get(iso) ?? [],
    });
  }
  return cells;
}

/** Highest-severity status among events on a day (for dot colour). */
function dayPrimaryStatus(events: UpcomingEvent[]): Status | null {
  if (events.length === 0) return null;
  if (events.some((e) => e.status === 'REJECT'))  return 'REJECT';
  if (events.some((e) => e.status === 'CAUTION')) return 'CAUTION';
  return 'PASS';
}

function addMonths(d: Date, n: number): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1));
}

function monthLabel(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
}

export default function CalendarPage() {
  const [anchor, setAnchor] = useState<Date>(new Date(Date.UTC(TODAY.getUTCFullYear(), TODAY.getUTCMonth(), 1)));
  const [selected, setSelected] = useState<string | null>(isoForUTC(TODAY));
  const [events, setEvents] = useState<UpcomingEvent[]>([]);

  useEffect(() => { api.getEvents().then(setEvents).catch(() => {}); }, []);

  const eventsByDate = useMemo(() => {
    const map = new Map<string, UpcomingEvent[]>();
    for (const ev of events) {
      const list = map.get(ev.date) ?? [];
      list.push(ev);
      map.set(ev.date, list);
    }
    return map;
  }, [events]);

  // Six months side-by-side (responsive: wraps to 2–3 cols on narrower screens).
  const monthViews = useMemo(() => {
    const out: { date: Date; cells: DayCell[] }[] = [];
    for (let i = 0; i < 6; i++) {
      const date = addMonths(anchor, i);
      out.push({ date, cells: buildMonthGrid(date, eventsByDate) });
    }
    return out;
  }, [anchor, eventsByDate]);

  const selectedEvents = selected ? (eventsByDate.get(selected) ?? []) : [];
  const selectedDate   = selected ? new Date(`${selected}T00:00:00Z`) : null;

  const totalEventsInView = monthViews
    .flatMap((m) => m.cells)
    .filter((c) => c.inMonth && c.events.length > 0)
    .reduce((n, c) => n + c.events.length, 0);

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Calendar</Title>
        <Text size={13} tone="secondary">
          {totalEventsInView} event{totalEventsInView === 1 ? '' : 's'} · earnings, FOMC, expirations
        </Text>
      </div>

      <div className={styles.navBar}>
        <button
          type="button"
          className={styles.navBtn}
          onClick={() => setAnchor((a) => addMonths(a, -1))}
          aria-label="Previous month"
        >
          ←
        </button>
        <div className={styles.navTitle}>
          <Data size={14} weight={500}>{monthLabel(monthViews[0]!.date)}</Data>
          <Text size={11} tone="dim">–</Text>
          <Data size={14} weight={500}>{monthLabel(monthViews[5]!.date)}</Data>
        </div>
        <div className={styles.navBtnGroup}>
          <button
            type="button"
            className={styles.navBtn}
            onClick={() => setAnchor(new Date(Date.UTC(TODAY.getUTCFullYear(), TODAY.getUTCMonth(), 1)))}
          >
            Today
          </button>
          <button
            type="button"
            className={styles.navBtn}
            onClick={() => setAnchor((a) => addMonths(a, 1))}
            aria-label="Next month"
          >
            →
          </button>
        </div>
      </div>

      <div className={styles.months}>
        {monthViews.map((m) => (
          <MonthCard
            key={isoForUTC(m.date)}
            label={monthLabel(m.date)}
            cells={m.cells}
            selected={selected}
            onSelect={setSelected}
          />
        ))}
      </div>

      {/* Selected day detail */}
      <section className={styles.detail} aria-live="polite">
        <header className={styles.detailHeader}>
          <Data size={14} weight={500}>
            {selectedDate
              ? selectedDate.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
              : 'Select a day'}
          </Data>
          {selectedDate && selectedEvents.length > 0 && (
            <EventFlag
              days={Math.round((selectedDate.getTime() - TODAY.getTime()) / 86_400_000)}
              title={`${selectedEvents.length} event${selectedEvents.length !== 1 ? 's' : ''} on this day`}
            />
          )}
        </header>
        {selectedEvents.length > 0 ? (
          <ul className={styles.items}>
            {selectedEvents.map((ev) => (
              <li key={`${ev.date}-${ev.symbol}-${ev.label}`} className={styles.item}>
                <StatusDot tone={ev.status} size="sm" title={eventProximityGateTooltip(ev.status)} />
                <Data size={12} weight={500} className={styles.sym}>{ev.symbol}</Data>
                <Text size={12} tone="secondary">{ev.label}</Text>
              </li>
            ))}
          </ul>
        ) : (
          <div className={styles.detailEmpty}>
            <Text size={13} tone="dim">
              {selected ? 'No events on this day.' : 'Pick a day to see its events.'}
            </Text>
          </div>
        )}
      </section>
    </div>
  );
}

function MonthCard({
  label,
  cells,
  selected,
  onSelect,
}: {
  label:    string;
  cells:    DayCell[];
  selected: string | null;
  onSelect: (iso: string) => void;
}) {
  const inMonthEvents = cells.filter((c) => c.inMonth && c.events.length > 0).length;
  return (
    <div className={styles.monthCard}>
      <header className={styles.monthHeader}>
        <Data size={14} weight={500}>{label}</Data>
        <Text size={11} tone="secondary">
          {inMonthEvents} day{inMonthEvents === 1 ? '' : 's'} with events
        </Text>
      </header>

      <div className={styles.weekRow} aria-hidden>
        {WEEK_LABELS.map((w) => (
          <Text key={w} size={11} tone="dim" className={styles.weekLabel}>{w}</Text>
        ))}
      </div>

      <div className={styles.grid}>
        {cells.map((c) => {
          const isSel = selected === c.iso;
          const primary = dayPrimaryStatus(c.events);
          const cls = [
            styles.dayCell,
            !c.inMonth        ? styles.dayOut        : '',
            c.isToday         ? styles.dayToday     : '',
            isSel             ? styles.daySelected  : '',
            c.events.length   ? styles.dayHasEvents : '',
          ].filter(Boolean).join(' ');
          return (
            <button
              key={c.iso}
              type="button"
              className={cls}
              onClick={() => onSelect(c.iso)}
              disabled={!c.inMonth}
              aria-label={`${c.iso}${c.events.length ? `, ${c.events.length} event${c.events.length === 1 ? '' : 's'}` : ''}`}
              aria-pressed={isSel}
            >
              <Data size={12} weight={c.events.length ? 500 : 400}>{c.dayNum}</Data>
              <span className={styles.dotRow} aria-hidden>
                {primary && (
                  <span className={`${styles.eventDot} ${styles[`eventDot_${primary}`]}`} />
                )}
                {c.events.length > 1 && (
                  <span className={`${styles.eventDot} ${styles[`eventDot_${primary}`]}`} style={{ opacity: 0.5 }} />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
