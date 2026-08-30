'use client';

/*
 * Trading Journal — entry list + filter bar + Trade/Note create/edit form.
 *
 * Backend-persisted (not localStorage) — replaces an external Excel trading
 * journal. See the plan (journal-plan.md) for the full field/business-rule
 * spec this page mirrors.
 *
 * The filter bar calls journalStore.syncEntries(filters) SERVER-SIDE on every
 * change (not a client-side filter over the loaded array); the `symbol` text
 * filter is debounced ~300ms so typing doesn't fire a request per keystroke.
 * Table sorting, by contrast, is client-side (see JournalEntryTable) — the
 * backend has no sort query param.
 */

import { useEffect, useMemo, useState } from 'react';
import { Title, Text } from '@/components/primitives';
import { ConfirmDialog } from '@/components/molecules/ConfirmDialog';
import { JournalEntryForm } from '@/components/organisms/JournalEntryForm';
import { JournalEntryTable } from '@/components/organisms/JournalEntryTable';
import { useJournalStore } from '@/lib/journalStore';
import { localDateInputToStartOfDayIso, localDateInputToEndOfDayIso } from '@/lib/journalDate';
import type { JournalEntry, JournalEntryFilters, JournalEntryInput, JournalEntryType, JournalStatus } from '@/types/journal';
import styles from './page.module.css';

const SYMBOL_DEBOUNCE_MS = 300;

export default function JournalPage() {
  const entries      = useJournalStore((s) => s.entries);
  const loading       = useJournalStore((s) => s.loading);
  const error          = useJournalStore((s) => s.error);
  const syncEntries    = useJournalStore((s) => s.syncEntries);
  const createEntry    = useJournalStore((s) => s.createEntry);
  const updateEntry    = useJournalStore((s) => s.updateEntry);
  const deleteEntry    = useJournalStore((s) => s.deleteEntry);
  const clearError     = useJournalStore((s) => s.clearError);

  // Filter bar state — raw controls.
  const [symbolInput, setSymbolInput]   = useState('');
  const [debouncedSymbol, setDebouncedSymbol] = useState('');
  const [strategyTagInput, setStrategyTagInput] = useState('');
  const [debouncedStrategyTag, setDebouncedStrategyTag] = useState('');
  const [status, setStatus]             = useState<JournalStatus | ''>('');
  const [entryType, setEntryType]       = useState<JournalEntryType | ''>('');
  const [dateFrom, setDateFrom]         = useState('');
  const [dateTo, setDateTo]             = useState('');

  const [showForm, setShowForm]         = useState(false);
  const [editingEntry, setEditingEntry] = useState<JournalEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<JournalEntry | null>(null);

  // Debounce both free-text filters (~300ms) — `symbol` and `strategy_tag`
  // are both typed inputs that would otherwise fire a request per keystroke;
  // the other controls (selects, date pickers) don't, so they sync
  // immediately on change.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSymbol(symbolInput.trim()), SYMBOL_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [symbolInput]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedStrategyTag(strategyTagInput.trim()), SYMBOL_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [strategyTagInput]);

  const filters = useMemo<JournalEntryFilters>(() => {
    const f: JournalEntryFilters = {};
    if (debouncedSymbol) f.symbol = debouncedSymbol;
    if (debouncedStrategyTag) f.strategy_tag = debouncedStrategyTag;
    if (status) f.status = status;
    if (entryType) f.entry_type = entryType;
    const from = localDateInputToStartOfDayIso(dateFrom);
    if (from) f.date_from = from;
    const to = localDateInputToEndOfDayIso(dateTo);
    if (to) f.date_to = to;
    return f;
  }, [debouncedSymbol, debouncedStrategyTag, status, entryType, dateFrom, dateTo]);

  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    syncEntries(filters);
    // filtersKey is the stable dep — filters itself is a fresh object each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey]);

  function openCreate() {
    setEditingEntry(null);
    setShowForm(true);
  }

  function openEdit(entry: JournalEntry) {
    setEditingEntry(entry);
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingEntry(null);
  }

  async function handleSubmit(input: JournalEntryInput) {
    if (editingEntry) {
      await updateEntry(editingEntry.id, input);
    } else {
      await createEntry(input);
    }
    closeForm();
  }

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <div className={styles.headingTop}>
          <Title as="h1" size={24}>Trading Journal</Title>
          <button type="button" className={styles.newBtn} onClick={openCreate}>
            New entry
          </button>
        </div>
        <Text size={13} tone="secondary">
          {loading ? 'Loading…' : `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`}
        </Text>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          <Text size={12} tone="reject">{error}</Text>
          <button type="button" className={styles.errorDismiss} onClick={clearError}>Dismiss</button>
        </div>
      )}

      <div className={styles.filterBar}>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">Symbol</Text>
          <input
            type="text"
            className={styles.filterInput}
            aria-label="Filter by symbol"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            placeholder="e.g. AAPL"
          />
        </div>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">Strategy tag</Text>
          <input
            type="text"
            className={styles.filterInput}
            aria-label="Filter by strategy tag"
            value={strategyTagInput}
            onChange={(e) => setStrategyTagInput(e.target.value)}
            placeholder="e.g. pullback_ema"
          />
        </div>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">Status</Text>
          <select className={styles.filterInput} aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value as JournalStatus | '')}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </div>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">Entry type</Text>
          <select className={styles.filterInput} aria-label="Filter by entry type" value={entryType} onChange={(e) => setEntryType(e.target.value as JournalEntryType | '')}>
            <option value="">All</option>
            <option value="trade">Trade</option>
            <option value="note">Note</option>
          </select>
        </div>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">From</Text>
          <input type="date" className={styles.filterInput} aria-label="Filter from date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <Text as="label" size={11} tone="dim">To</Text>
          <input type="date" className={styles.filterInput} aria-label="Filter to date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      <JournalEntryTable
        entries={entries}
        onRowClick={openEdit}
        onDeleteClick={(entry) => setDeleteTarget(entry)}
      />

      {showForm && (
        <JournalEntryForm
          entry={editingEntry}
          onSubmit={handleSubmit}
          onCancel={closeForm}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={`Delete this ${deleteTarget.entry_type === 'trade' ? 'trade' : 'note'} entry?`}
          body={deleteTarget.symbol ? `${deleteTarget.symbol} — ${new Date(deleteTarget.entry_date).toLocaleDateString()}` : undefined}
          confirmLabel="Delete"
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => {
            deleteEntry(deleteTarget.id);
            setDeleteTarget(null);
          }}
        />
      )}
    </div>
  );
}
