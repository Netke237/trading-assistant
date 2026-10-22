import { create } from 'zustand';

export interface SaveChannel {
  label: string;
  sequence: number;
  pending: Record<number, Promise<void>>;
  failed: boolean;
  unconfirmed: boolean;
  draft: string | null;
  discardedAt: number | null;
}

interface LocalFailure {
  label: string;
  pendingValue: string;
}

interface SettingsSaveStatus {
  channels: Record<string, SaveChannel>;
  localFailures: Record<string, LocalFailure>;
}

export interface OutstandingSave {
  channel: string;
  label: string;
  kind: 'failed' | 'draft' | 'discarded' | 'unconfirmed' | 'local';
  message: string;
}

// Deliberately not persisted. No imports from persisted stores: their storage
// adapters report here, so importing them would also create a dependency cycle.
// Subscribe to this store (or select channels/localFailures) for footer updates;
// outstanding() is a fresh derived list, not a stable React selector snapshot.
export const useSettingsSaveStatus = create<SettingsSaveStatus>(() => ({
  channels: {},
  localFailures: {},
}));

function updateChannel(channel: string, label: string, update: (current: SaveChannel) => SaveChannel): void {
  useSettingsSaveStatus.setState((state) => ({
    channels: {
      ...state.channels,
      [channel]: update(state.channels[channel] ?? {
        label, sequence: 0, pending: {}, failed: false,
        unconfirmed: false, draft: null, discardedAt: null,
      }),
    },
  }));
}

export function isSaving(channel?: string): boolean {
  const { channels } = useSettingsSaveStatus.getState();
  return channel === undefined
    ? Object.values(channels).some((entry) => Object.keys(entry.pending).length > 0)
    : Object.keys(channels[channel]?.pending ?? {}).length > 0;
}

export function trackSave<T>(channel: string, label: string, run: () => Promise<T>): Promise<T> {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let sequence = 0;
  let beganWithoutOlderPending = false;
  // Register before run(), including synchronous throws and reentrant saves.
  updateChannel(channel, label, (current) => {
    sequence = current.sequence + 1;
    beganWithoutOlderPending = Object.keys(current.pending).length === 0;
    return {
      ...current, label, sequence,
      pending: { ...current.pending, [sequence]: pending },
      unconfirmed: current.unconfirmed || !beganWithoutOlderPending,
    };
  });

  const finish = (success: boolean) => {
    updateChannel(channel, label, (current) => {
      const remaining = { ...current.pending };
      delete remaining[sequence];
      const next = { ...current, pending: remaining };
      if (current.sequence === sequence) {
        if (!success) next.failed = true;
        else if (beganWithoutOlderPending) {
          next.failed = false;
          next.unconfirmed = false;
          if (current.discardedAt !== null && sequence > current.discardedAt) next.discardedAt = null;
        }
      }
      return next;
    });
    release();
  };

  let result: Promise<T>;
  try { result = run(); }
  catch (error) { result = Promise.reject(error); }
  return Promise.resolve(result).then(
    (value) => { finish(true); return value; },
    (error: unknown) => { finish(false); throw error; },
  );
}

export async function settleAll(): Promise<void> {
  // These settlement promises never reject and include superseded attempts.
  // Read again after waiting to catch saves begun during the previous wait.
  for (;;) {
    const pending = Object.values(useSettingsSaveStatus.getState().channels)
      .flatMap((entry) => Object.values(entry.pending));
    if (pending.length === 0) return;
    await Promise.all(pending);
  }
}

export function setDraft(channel: string, label: string, dirty: boolean, message = 'unsaved edit — use its Save button'): void {
  updateChannel(channel, label, (current) => ({
    ...current, label, draft: dirty ? message : null,
    discardedAt: dirty ? null : current.discardedAt,
  }));
}

export function discardDraft(channel: string): void {
  const current = useSettingsSaveStatus.getState().channels[channel];
  if (!current?.draft) return;
  updateChannel(channel, current.label, (entry) => ({
    ...entry, draft: null, discardedAt: entry.sequence,
  }));
}

/** For explicit successful local-only commits (strategy overrides / IV Apply). */
export function clearDiscarded(channel: string): void {
  const current = useSettingsSaveStatus.getState().channels[channel];
  if (!current || current.discardedAt === null) return;
  updateChannel(channel, current.label, (entry) => ({ ...entry, discardedAt: null }));
}

export function reportLocalWriteFailure(key: string, label: string, pendingValue: string): void {
  useSettingsSaveStatus.setState((state) => ({
    localFailures: { ...state.localFailures, [key]: { label, pendingValue } },
  }));
}

export function reportLocalWriteSuccess(key: string): void {
  if (!(key in useSettingsSaveStatus.getState().localFailures)) return;
  useSettingsSaveStatus.setState((state) => {
    const localFailures = { ...state.localFailures };
    delete localFailures[key];
    return { localFailures };
  });
}

export function retryLocalWrites(): void {
  for (const [key, failure] of Object.entries(useSettingsSaveStatus.getState().localFailures)) {
    try {
      localStorage.setItem(key, failure.pendingValue);
      reportLocalWriteSuccess(key);
    } catch {
      // Keep the last failed serialized bytes for the next explicit retry.
    }
  }
}

export function outstanding(): OutstandingSave[] {
  const { channels, localFailures } = useSettingsSaveStatus.getState();
  const items: OutstandingSave[] = [];
  for (const [channel, entry] of Object.entries(channels)) {
    const add = (kind: OutstandingSave['kind'], message: string) => items.push({ channel, label: entry.label, kind, message });
    if (entry.failed) add('failed', 'save failed — not confirmed by the server');
    if (entry.unconfirmed) add('unconfirmed', 'latest save not confirmed — save or re-enter this setting again');
    if (entry.draft !== null) add('draft', entry.draft);
    if (entry.discardedAt !== null) add('discarded', 'edit discarded when you left the section — not saved');
  }
  for (const [channel, failure] of Object.entries(localFailures)) {
    items.push({ channel, label: failure.label, kind: 'local', message: 'could not be stored in this browser (storage full or blocked) — the previous value returns on reload' });
  }
  return items;
}
