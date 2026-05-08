/**
 * Minimal audit logger — console + localStorage.
 */

export type AuditEvent = 'APPROVE' | 'REJECT' | 'SUBMIT' | 'CLOSE';

interface AuditEntry {
  timestamp: string;
  event: AuditEvent;
  recId: string;
  details?: Record<string, unknown>;
}

const AUDIT_STORAGE_KEY = 'bamendjou-audit-log';

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
    localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(log));
  } catch {
    // ignore storage errors
  }
}
