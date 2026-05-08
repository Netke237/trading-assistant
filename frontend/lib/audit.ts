/**
 * Minimal audit logger — console + localStorage.
 * Capped at MAX_ENTRIES to prevent QuotaExceededError.
 */

export type AuditEvent = 'APPROVE' | 'REJECT' | 'SUBMIT' | 'CLOSE';

interface AuditEntry {
  timestamp: string;
  event: AuditEvent;
  recId: string;
  details?: Record<string, unknown>;
}

const AUDIT_STORAGE_KEY = 'bamendjou-audit-log';
const MAX_ENTRIES = 500;
const EVICT_COUNT = 100; // how many to drop when over limit

export function logAudit(
  event: AuditEvent,
  recId: string,
  details?: Record<string, unknown>
): void {
  const entry: AuditEntry = {
    timestamp: new Date().toISOString(),
    event,
    recId,
    details,
  };
  // eslint-disable-next-line no-console
  console.log('[AUDIT]', entry);
  try {
    const raw = localStorage.getItem(AUDIT_STORAGE_KEY);
    const log: AuditEntry[] = raw ? (JSON.parse(raw) as AuditEntry[]) : [];
    log.push(entry);

    // FIFO eviction: keep newest MAX_ENTRIES
    if (log.length > MAX_ENTRIES) {
      log.splice(0, log.length - MAX_ENTRIES);
    }

    _setWithFallback(log);
  } catch {
    // ignore storage read errors
  }
}

function _setWithFallback(log: AuditEntry[]): void {
  try {
    localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(log));
  } catch {
    // QuotaExceededError: evict oldest EVICT_COUNT entries and retry once
    try {
      log.splice(0, EVICT_COUNT);
      localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(log));
    } catch {
      // If it still fails (e.g. single entry too large), silently drop
    }
  }
}
