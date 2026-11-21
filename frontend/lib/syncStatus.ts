// frontend/lib/syncStatus.ts
import { hhmmss } from './configHealth';

export type SyncStatusKind = 'syncing' | 'ok' | 'failed-with-prior' | 'failed-no-prior';
export interface SyncStatusView { kind: SyncStatusKind; text: string }

export interface SyncStamps {
  lastSyncAt: number | null;
  lastSyncFailedAt: number | null;
  firstSyncAt: number | null;
}

/** A failure counts only while it is newer than the last success. */
export function syncStatusView(s: SyncStamps): SyncStatusView {
  const { lastSyncAt, lastSyncFailedAt } = s;
  if (lastSyncFailedAt !== null && lastSyncFailedAt > (lastSyncAt ?? 0)) {
    if (lastSyncAt !== null) {
      return {
        kind: 'failed-with-prior',
        text: `Last sync failed ${hhmmss(lastSyncFailedAt)}, showing ${hhmmss(lastSyncAt)}`,
      };
    }
    return {
      kind: 'failed-no-prior',
      text: `Last sync failed ${hhmmss(lastSyncFailedAt)}, showing positions saved in this browser`,
    };
  }
  if (lastSyncAt !== null) {
    return {
      kind: 'ok',
      text: `Synced ${hhmmss(lastSyncAt)} · refreshes every 30 s, paused while this tab is hidden`,
    };
  }
  return { kind: 'syncing', text: 'Syncing…' };
}

export type PositionsLoadState = 'loading' | 'failed' | 'empty' | 'ready';

export function positionsLoadState(
  count: number,
  lastSyncAt: number | null,
  lastSyncFailedAt: number | null,
): PositionsLoadState {
  if (count > 0) return 'ready';
  if (lastSyncAt === null && lastSyncFailedAt === null) return 'loading';
  if (lastSyncAt === null) return 'failed';
  return 'empty';
}
