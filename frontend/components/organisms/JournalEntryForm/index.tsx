'use client';

/*
 * JournalEntryForm — create/edit form with the Trade/Note entry_type toggle.
 *
 * The toggle RESETS (not just hides) all 14 trade-only fields when switching
 * to Note — JOURNAL_TRADE_ONLY_FIELDS (types/journal.ts) is the single source
 * of truth for that list, shared with the backend's forbidden-field rule.
 * Merely conditionally rendering the trade inputs while leaving their values
 * in form state would guarantee a 422 on submit the moment a user toggles
 * Trade->Note on a form that had any trade field filled in.
 *
 * A brand-new trade entry's `status` defaults to 'open' — nothing else in the
 * schema enforces this (it's nullable at the DB level, necessarily, since
 * `note` entries forbid it).
 *
 * `strategy_tag` is free text (the 7 step-4-stocks strategy names are offered only
 * as <datalist> suggestions, not a closed <select>) — options trades and
 * off-strategy stock trades need to write something else in.
 *
 * `mistake_tags` is a comma-separated free-text input, split/trimmed to
 * string[] on submit — no fixed vocabulary exists in the schema.
 *
 * The symbol picker distinguishes a watchlistStore pick (sets only `symbol`)
 * from a portfolioStore position pick (sets BOTH `symbol` and `position_id`
 * from that position's `recId` — camelCase; `rec_id` is only the backend
 * column name this is ultimately compared against).
 */

import { useMemo, useState } from 'react';
import { Text } from '@/components/primitives';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { localDateInputToStartOfDayIso, isoToLocalDateInputValue } from '@/lib/journalDate';
import {
  JOURNAL_TRADE_ONLY_FIELDS,
  type JournalEntry,
  type JournalEntryInput,
  type JournalEntryType,
  type JournalDirection,
  type JournalInstrumentType,
  type JournalStatus,
} from '@/types/journal';
import styles from './JournalEntryForm.module.css';

const STRATEGY_SUGGESTIONS = [
  'pullback_ema',
  'breakout_base',
  'ma_crossover',
  'mean_reversion_rsi',
  'mean_reversion_bb',
  'mean_reversion_vwap',
  'mean_reversion_multi',
] as const;

function todayLocalDateInput(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

interface FormState {
  entry_type: JournalEntryType;
  entry_date: string; // yyyy-mm-dd
  symbol: string;
  instrument_type: JournalInstrumentType | '';
  direction: JournalDirection | '';
  entry_price: string;
  exit_price: string;
  position_size: string;
  stop_loss: string;
  risk_dollars: string;
  net_pnl: string;
  thesis: string;
  strategy_tag: string;
  mistake_tags: string;
  execution_grade: string;
  status: JournalStatus | '';
  lessons_learned: string;
  notes: string;
  position_id: string | null;
}

function blankForm(): FormState {
  return {
    entry_type: 'trade',
    entry_date: todayLocalDateInput(),
    symbol: '',
    instrument_type: '',
    direction: '',
    entry_price: '',
    exit_price: '',
    position_size: '',
    stop_loss: '',
    risk_dollars: '',
    net_pnl: '',
    thesis: '',
    strategy_tag: '',
    mistake_tags: '',
    execution_grade: '',
    status: 'open',
    lessons_learned: '',
    notes: '',
    position_id: null,
  };
}

function formFromEntry(entry: JournalEntry): FormState {
  return {
    entry_type: entry.entry_type,
    entry_date: isoToLocalDateInputValue(entry.entry_date) || todayLocalDateInput(),
    symbol: entry.symbol ?? '',
    instrument_type: entry.instrument_type ?? '',
    direction: entry.direction ?? '',
    entry_price: entry.entry_price != null ? String(entry.entry_price) : '',
    exit_price: entry.exit_price != null ? String(entry.exit_price) : '',
    position_size: entry.position_size != null ? String(entry.position_size) : '',
    stop_loss: entry.stop_loss != null ? String(entry.stop_loss) : '',
    risk_dollars: entry.risk_dollars != null ? String(entry.risk_dollars) : '',
    net_pnl: entry.net_pnl != null ? String(entry.net_pnl) : '',
    thesis: entry.thesis ?? '',
    strategy_tag: entry.strategy_tag ?? '',
    mistake_tags: (entry.mistake_tags ?? []).join(', '),
    execution_grade: entry.execution_grade != null ? String(entry.execution_grade) : '',
    status: entry.status ?? '',
    lessons_learned: entry.lessons_learned ?? '',
    notes: entry.notes ?? '',
    position_id: entry.position_id ?? null,
  };
}

/** Resets exactly the 14 trade-only fields — the backend's forbidden-field
 *  list — to their empty/null form-state equivalents. */
function resetTradeOnlyFields(f: FormState): FormState {
  const cleared = { ...f };
  for (const field of JOURNAL_TRADE_ONLY_FIELDS) {
    switch (field) {
      case 'symbol':          cleared.symbol = ''; break;
      case 'direction':       cleared.direction = ''; break;
      case 'entry_price':     cleared.entry_price = ''; break;
      case 'exit_price':      cleared.exit_price = ''; break;
      case 'position_size':   cleared.position_size = ''; break;
      case 'stop_loss':       cleared.stop_loss = ''; break;
      case 'risk_dollars':    cleared.risk_dollars = ''; break;
      case 'net_pnl':         cleared.net_pnl = ''; break;
      case 'status':          cleared.status = ''; break;
      case 'instrument_type': cleared.instrument_type = ''; break;
      case 'position_id':     cleared.position_id = null; break;
      case 'strategy_tag':    cleared.strategy_tag = ''; break;
      case 'execution_grade': cleared.execution_grade = ''; break;
      case 'thesis':          cleared.thesis = ''; break;
    }
  }
  return cleared;
}

function numOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function strOrNull(raw: string): string | null {
  const trimmed = raw.trim();
  return trimmed === '' ? null : trimmed;
}

function buildPayload(f: FormState): JournalEntryInput | null {
  const entryDateIso = localDateInputToStartOfDayIso(f.entry_date);
  if (!entryDateIso) return null;

  const mistakeTags = f.mistake_tags.trim()
    ? f.mistake_tags.split(',').map((t) => t.trim()).filter(Boolean)
    : null;

  if (f.entry_type === 'note') {
    return {
      entry_type: 'note',
      entry_date: entryDateIso,
      symbol: null,
      instrument_type: null,
      direction: null,
      entry_price: null,
      exit_price: null,
      position_size: null,
      stop_loss: null,
      risk_dollars: null,
      net_pnl: null,
      thesis: null,
      strategy_tag: null,
      mistake_tags: mistakeTags,
      execution_grade: null,
      status: null,
      lessons_learned: strOrNull(f.lessons_learned),
      notes: strOrNull(f.notes),
      position_id: null,
    };
  }

  return {
    entry_type: 'trade',
    entry_date: entryDateIso,
    symbol: strOrNull(f.symbol.toUpperCase()),
    instrument_type: f.instrument_type || null,
    direction: f.direction || null,
    entry_price: numOrNull(f.entry_price),
    exit_price: numOrNull(f.exit_price),
    position_size: numOrNull(f.position_size),
    stop_loss: numOrNull(f.stop_loss),
    risk_dollars: numOrNull(f.risk_dollars),
    net_pnl: numOrNull(f.net_pnl),
    thesis: strOrNull(f.thesis),
    strategy_tag: strOrNull(f.strategy_tag),
    mistake_tags: mistakeTags,
    execution_grade: f.execution_grade ? Number(f.execution_grade) : null,
    status: f.status || null,
    lessons_learned: strOrNull(f.lessons_learned),
    notes: null,
    position_id: f.position_id,
  };
}

interface JournalEntryFormProps {
  /** null = creating a new entry; otherwise editing this entry (pre-filled). */
  entry: JournalEntry | null;
  onSubmit: (input: JournalEntryInput) => void;
  onCancel: () => void;
}

export function JournalEntryForm({ entry, onSubmit, onCancel }: JournalEntryFormProps) {
  const [form, setForm] = useState<FormState>(() => (entry ? formFromEntry(entry) : blankForm()));
  const [error, setError] = useState<string | null>(null);

  const watchlistSymbols = useWatchlistStore((s) => s.added);
  const positions = usePortfolioStore((s) => s.positions);

  const openPositions = useMemo(
    () => [...positions].sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [positions],
  );

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function handleTypeChange(next: JournalEntryType) {
    setForm((f) => {
      if (next === 'note') {
        return { ...resetTradeOnlyFields(f), entry_type: 'note' };
      }
      // Trade (fresh, or switching back from Note) — default status to
      // 'open' when it isn't already set, so a trade never silently persists
      // with status=None (invisible to the status filter / table column).
      return { ...f, entry_type: 'trade', status: f.status || 'open' };
    });
  }

  function handlePickWatchlistSymbol(symbol: string) {
    if (!symbol) return;
    // Sets only `symbol` (per the plan) — but a previously-picked position_id
    // pointing at a different symbol is now stale and must not linger.
    setForm((f) => ({ ...f, symbol, position_id: null }));
  }

  function handlePickPosition(recId: string) {
    if (!recId) return;
    const pos = positions.find((p) => p.recId === recId);
    if (!pos) return;
    setForm((f) => ({ ...f, symbol: pos.symbol, position_id: pos.recId }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (form.entry_type === 'trade' && !form.symbol.trim()) {
      setError('Symbol is required for a trade entry.');
      return;
    }
    const payload = buildPayload(form);
    if (!payload) {
      setError('Entry date is required.');
      return;
    }
    setError(null);
    onSubmit(payload);
  }

  const isTrade = form.entry_type === 'trade';

  return (
    <div className={styles.overlay} role="dialog" aria-modal aria-labelledby="journal-form-title">
      <form className={styles.panel} onSubmit={handleSubmit}>
        <div className={styles.header}>
          <Text as="div" size={14} weight={600}>
            <span id="journal-form-title">{entry ? 'Edit entry' : 'New entry'}</span>
          </Text>
          <div className={styles.toggle} role="tablist" aria-label="Entry type">
            <button
              type="button"
              role="tab"
              aria-selected={isTrade}
              className={`${styles.toggleBtn} ${isTrade ? styles.toggleActive : ''}`}
              onClick={() => handleTypeChange('trade')}
            >
              Trade
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!isTrade}
              className={`${styles.toggleBtn} ${!isTrade ? styles.toggleActive : ''}`}
              onClick={() => handleTypeChange('note')}
            >
              Note
            </button>
          </div>
        </div>

        <div className={styles.body}>
          <div className={styles.field}>
            <Text as="label" size={11} tone="secondary" weight={400}>Entry date</Text>
            <input
              type="date"
              className={styles.input}
              aria-label="Entry date"
              value={form.entry_date}
              onChange={(e) => set('entry_date', e.target.value)}
              required
            />
          </div>

          {isTrade && (
            <>
              <div className={styles.field}>
                <Text as="label" size={11} tone="secondary" weight={400}>Symbol *</Text>
                <input
                  type="text"
                  className={styles.input}
                  aria-label="Symbol, required"
                  value={form.symbol}
                  onChange={(e) => {
                    const next = e.target.value.toUpperCase();
                    // A manual edit invalidates a prior position pick — a
                    // stale position_id pointing at a now-mismatched symbol
                    // would silently mislink the entry.
                    setForm((f) => ({ ...f, symbol: next, position_id: null }));
                  }}
                  placeholder="AAPL"
                />
                <div className={styles.pickerRow}>
                  <select
                    className={styles.pickerSelect}
                    value=""
                    aria-label="Pick from watchlist"
                    onChange={(e) => handlePickWatchlistSymbol(e.target.value)}
                  >
                    <option value="">From watchlist…</option>
                    {watchlistSymbols.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                  <select
                    className={styles.pickerSelect}
                    value=""
                    aria-label="Pick from portfolio position"
                    onChange={(e) => handlePickPosition(e.target.value)}
                  >
                    <option value="">From portfolio position…</option>
                    {openPositions.map((p) => (
                      <option key={p.recId} value={p.recId}>
                        {p.symbol} — {p.contract}
                      </option>
                    ))}
                  </select>
                </div>
                {form.position_id && (
                  <Text size={10} tone="dim">Linked to position {form.position_id}</Text>
                )}
              </div>

              <div className={styles.row3}>
                <div className={styles.field}>
                  <Text as="label" size={11} tone="secondary" weight={400}>Direction</Text>
                  <select className={styles.input} aria-label="Direction" value={form.direction} onChange={(e) => set('direction', e.target.value as JournalDirection | '')}>
                    <option value="">—</option>
                    <option value="long">Long</option>
                    <option value="short">Short</option>
                  </select>
                </div>
                <div className={styles.field}>
                  <Text as="label" size={11} tone="secondary" weight={400}>Instrument</Text>
                  <select className={styles.input} aria-label="Instrument" value={form.instrument_type} onChange={(e) => set('instrument_type', e.target.value as JournalInstrumentType | '')}>
                    <option value="">—</option>
                    <option value="stock">Stock</option>
                    <option value="option">Option</option>
                  </select>
                </div>
                <div className={styles.field}>
                  <Text as="label" size={11} tone="secondary" weight={400}>Status</Text>
                  <select className={styles.input} aria-label="Status" value={form.status} onChange={(e) => set('status', e.target.value as JournalStatus | '')}>
                    <option value="">—</option>
                    <option value="open">Open</option>
                    <option value="closed">Closed</option>
                  </select>
                </div>
              </div>

              <div className={styles.row3}>
                <NumField label="Entry price" value={form.entry_price} onChange={(v) => set('entry_price', v)} />
                <NumField label="Exit price" value={form.exit_price} onChange={(v) => set('exit_price', v)} />
                <NumField label="Position size" value={form.position_size} onChange={(v) => set('position_size', v)} />
              </div>
              <div className={styles.row3}>
                <NumField label="Stop loss" value={form.stop_loss} onChange={(v) => set('stop_loss', v)} />
                <NumField label="Risk $" value={form.risk_dollars} onChange={(v) => set('risk_dollars', v)} />
                <NumField label="Net P&L" value={form.net_pnl} onChange={(v) => set('net_pnl', v)} />
              </div>

              <div className={styles.row2}>
                <div className={styles.field}>
                  <Text as="label" size={11} tone="secondary" weight={400}>Strategy tag</Text>
                  <input
                    type="text"
                    className={styles.input}
                    aria-label="Strategy tag"
                    list="journal-strategy-tags"
                    value={form.strategy_tag}
                    onChange={(e) => set('strategy_tag', e.target.value)}
                    placeholder="pullback_ema, or your own…"
                  />
                  <datalist id="journal-strategy-tags">
                    {STRATEGY_SUGGESTIONS.map((s) => <option key={s} value={s} />)}
                  </datalist>
                </div>
                <div className={styles.field}>
                  <Text as="label" size={11} tone="secondary" weight={400}>Execution grade</Text>
                  <select className={styles.input} aria-label="Execution grade" value={form.execution_grade} onChange={(e) => set('execution_grade', e.target.value)}>
                    <option value="">—</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              </div>

              <div className={styles.field}>
                <Text as="label" size={11} tone="secondary" weight={400}>Thesis</Text>
                <textarea className={styles.textarea} aria-label="Thesis" rows={2} value={form.thesis} onChange={(e) => set('thesis', e.target.value)} placeholder="One-liner: why this trade" />
              </div>
            </>
          )}

          {!isTrade && (
            <div className={styles.field}>
              <Text as="label" size={11} tone="secondary" weight={400}>Notes</Text>
              <textarea className={styles.textarea} aria-label="Notes" rows={5} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Daily note / reflection…" />
            </div>
          )}

          <div className={styles.field}>
            <Text as="label" size={11} tone="secondary" weight={400}>Mistake tags</Text>
            <input
              type="text"
              className={styles.input}
              aria-label="Mistake tags"
              value={form.mistake_tags}
              onChange={(e) => set('mistake_tags', e.target.value)}
              placeholder="revenge traded, sized too big, …"
            />
            <Text size={10} tone="dim">Comma-separated</Text>
          </div>

          <div className={styles.field}>
            <Text as="label" size={11} tone="secondary" weight={400}>Lessons learned</Text>
            <textarea className={styles.textarea} aria-label="Lessons learned" rows={2} value={form.lessons_learned} onChange={(e) => set('lessons_learned', e.target.value)} />
          </div>

          {error && <Text size={12} tone="reject">{error}</Text>}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
          <button type="submit" className={styles.submitBtn}>{entry ? 'Save changes' : 'Create entry'}</button>
        </div>
      </form>
    </div>
  );
}

function NumField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className={styles.field}>
      <Text as="label" size={11} tone="secondary" weight={400}>{label}</Text>
      <input
        type="number"
        step="any"
        className={`${styles.input} ${styles.inputMono}`}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
