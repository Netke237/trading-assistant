/*
 * Trading Journal — types.
 *
 * Mirrors backend/app/routers/journal.py's JournalEntryCreate/JournalEntryOut
 * schemas field-for-field. Deliberately snake_case (not translated to
 * camelCase) — matches the backend column/field spelling directly, the same
 * choice frontend/types/alerts.ts makes for chart alerts. Also mirrors
 * alerts.ts's per-field-union convention: every enum-ish field gets its own
 * exported literal union instead of a plain `string`, giving the frontend
 * compile-time protection the backend's plain `str` columns don't have.
 */

export type JournalEntryType = 'trade' | 'note';
export type JournalDirection = 'long' | 'short';
export type JournalStatus = 'open' | 'closed';
export type JournalInstrumentType = 'stock' | 'option';

/**
 * A journal entry as returned by the backend (`JournalEntryOut`).
 *
 * Trade-only fields (everything except `id`, `user_id`, `entry_type`,
 * `entry_date`, `mistake_tags`, `lessons_learned`, `notes`, `created_at`,
 * `updated_at`) are nullable — a `note` entry carries `null` for all 14 of
 * them (see JOURNAL_TRADE_ONLY_FIELDS below; the backend's model_validator
 * rejects a `note` payload that sets any of them).
 */
export interface JournalEntry {
  id: string;
  user_id: string;
  entry_type: JournalEntryType;
  /** ISO datetime, UTC-normalized. Always present — 'note' entries carry it too. */
  entry_date: string;
  symbol: string | null;
  instrument_type: JournalInstrumentType | null;
  direction: JournalDirection | null;
  entry_price: number | null;
  exit_price: number | null;
  position_size: number | null;
  stop_loss: number | null;
  /** Stored input (position_size × |entry−stop| convention) — user-editable, not force-derived. */
  risk_dollars: number | null;
  net_pnl: number | null;
  thesis: string | null;
  strategy_tag: string | null;
  mistake_tags: string[] | null;
  /** 1–5. */
  execution_grade: number | null;
  status: JournalStatus | null;
  lessons_learned: string | null;
  /** Free body text — used by 'note' entries. */
  notes: string | null;
  /** Soft reference to a portfolioStore position's `recId` (backend column: `rec_id`). No FK. */
  position_id: string | null;
  /** Derived at read time (net_pnl / risk_dollars) — never sent by the client. */
  r_multiple: number | null;
  created_at: string;
  updated_at: string;
}

/**
 * The 14 trade-only fields the backend forbids on a `note` entry. Kept as a
 * single source of truth on the frontend so the create/edit form's
 * entry-type toggle can reset exactly this set (and only this set) when
 * switching to Note — must stay field-for-field in sync with the backend's
 * `model_validator` list (see plan's Router section: this list was
 * incomplete for three audit rounds running).
 */
export const JOURNAL_TRADE_ONLY_FIELDS = [
  'symbol',
  'direction',
  'entry_price',
  'exit_price',
  'position_size',
  'stop_loss',
  'risk_dollars',
  'net_pnl',
  'status',
  'instrument_type',
  'position_id',
  'strategy_tag',
  'execution_grade',
  'thesis',
] as const;

/**
 * The body sent to POST/PUT /journal/entries. Excludes server-assigned
 * (`id`, `user_id`, `created_at`, `updated_at`) and server-derived
 * (`r_multiple`) fields — the backend computes `r_multiple`, it is never
 * accepted from the client.
 */
export type JournalEntryInput = Omit<
  JournalEntry,
  'id' | 'user_id' | 'r_multiple' | 'created_at' | 'updated_at'
>;

/** Query params for GET /journal/entries — maps directly to the router's filters. */
export interface JournalEntryFilters {
  symbol?: string;
  strategy_tag?: string;
  status?: JournalStatus;
  entry_type?: JournalEntryType;
  /** ISO datetime — UTC start-of-local-day boundary. */
  date_from?: string;
  /** ISO datetime — UTC end-of-local-day boundary. */
  date_to?: string;
}
