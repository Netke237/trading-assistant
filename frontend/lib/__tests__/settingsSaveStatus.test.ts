import {
  useSettingsSaveStatus, trackSave, settleAll, setDraft, discardDraft,
  clearDiscarded, outstanding, retryLocalWrites, isSaving,
} from '../settingsSaveStatus';

function deferred<T = number>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const kinds = () => outstanding().map((item) => item.kind);
beforeEach(() => useSettingsSaveStatus.setState({ channels: {}, localFailures: {} }));

test('registers before calling run, passes through result and rejection identities including synchronous throws', async () => {
  const value = { portfolioValue: 234567 };
  await expect(trackSave('risk', 'Risk limits', () => {
    expect(isSaving('risk')).toBe(true);
    return Promise.resolve(value);
  })).resolves.toBe(value);
  const error = new Error('synthetic request failure');
  await expect(trackSave('risk', 'Risk limits', () => Promise.reject(error))).rejects.toBe(error);
  expect(kinds()).toEqual(['failed']);
  setDraft('risk', 'Risk limits', false);
  discardDraft('risk');
  retryLocalWrites();
  expect(kinds()).toEqual(['failed']);
  await expect(trackSave('risk', 'Risk limits', () => { throw error; })).rejects.toBe(error);
  await trackSave('risk', 'Risk limits', () => Promise.resolve(value));
  expect(outstanding()).toEqual([]);
});

test.each(['old-first', 'latest-first'])('overlap is synchronously sticky and requires fresh safe user save: %s', async (order) => {
  const old = deferred();
  const latest = deferred();
  const p1 = trackSave('retention', 'Retention', () => old.promise);
  const p2 = trackSave('retention', 'Retention', () => latest.promise);
  expect(kinds()).toEqual(['unconfirmed']);
  if (order === 'old-first') { old.resolve(120); await p1; latest.resolve(90); await p2; }
  else { latest.resolve(90); await p2; old.resolve(120); await p1; }
  await settleAll();
  setDraft('retention', 'Retention', false); // remount/readback
  setDraft('retention', 'Retention', true);
  discardDraft('retention');
  clearDiscarded('retention');
  retryLocalWrites();
  expect(kinds()).toEqual(['unconfirmed']);
  await trackSave('retention', 'Retention', () => Promise.resolve(90));
  expect(outstanding()).toEqual([]);
});

test.each(['old-first', 'latest-first'])('only latest outcomes apply, even when a superseded attempt fails: %s', async (order) => {
  const old = deferred(); const latest = deferred();
  const p1 = trackSave('risk', 'Risk limits', () => old.promise);
  const caught = p1.catch((error) => error);
  const p2 = trackSave('risk', 'Risk limits', () => latest.promise);
  if (order === 'old-first') { old.reject('old error'); await caught; latest.resolve(17); await p2; }
  else { latest.resolve(17); await p2; old.reject('old error'); await caught; }
  expect(kinds()).toEqual(['unconfirmed']);
});

test('latest failure cannot be cleared by older success or another channel', async () => {
  const old = deferred(); const latest = deferred();
  const p1 = trackSave('risk', 'Risk limits', () => old.promise);
  const p2 = trackSave('risk', 'Risk limits', () => latest.promise).catch(() => {});
  latest.reject(new Error('latest failed')); await p2;
  old.resolve(18); await p1;
  await trackSave('timezone', 'Timezone', () => Promise.resolve(19));
  expect(kinds()).toEqual(['failed', 'unconfirmed']);
  await trackSave('risk', 'Risk limits', () => Promise.resolve(20));
  expect(outstanding()).toEqual([]);
});

test('settleAll retains superseded attempts and includes attempts started while waiting', async () => {
  const old = deferred(); const latest = deferred(); const added = deferred();
  const p1 = trackSave('risk', 'Risk limits', () => old.promise);
  const p2 = trackSave('risk', 'Risk limits', () => latest.promise);
  let settled = false;
  const waiting = settleAll().then(() => { settled = true; });
  latest.resolve(31); await p2;
  expect(settled).toBe(false);
  const p3 = trackSave('timezone', 'Timezone', () => added.promise);
  old.resolve(32); await p1;
  await Promise.resolve(); expect(settled).toBe(false);
  added.reject(new Error('added failure')); await p3.catch(() => {});
  await waiting;
  expect(isSaving()).toBe(false);
  expect(outstanding().find((item) => item.channel === 'timezone')?.kind).toBe('failed');
});

test('draft lifecycle and local explicit commit clear discarded without erasing failures', async () => {
  setDraft('strategy:lookback', 'Lookback', true, 'invalid value not applied');
  expect(outstanding()[0]).toMatchObject({ channel: 'strategy:lookback', kind: 'draft', message: 'invalid value not applied' });
  setDraft('strategy:lookback', 'Lookback', false); expect(outstanding()).toEqual([]);
  discardDraft('strategy:lookback'); expect(outstanding()).toEqual([]);
  setDraft('strategy:lookback', 'Lookback', true); discardDraft('strategy:lookback');
  expect(kinds()).toEqual(['discarded']);
  setDraft('strategy:lookback', 'Lookback', false); expect(kinds()).toEqual(['discarded']);
  setDraft('strategy:lookback', 'Lookback', true); expect(kinds()).toEqual(['draft']);
  discardDraft('strategy:lookback'); clearDiscarded('strategy:lookback');
  expect(outstanding()).toEqual([]);
});

test('a save already in flight at discard cannot clear discarded; a later safe save can', async () => {
  const save = deferred();
  const p = trackSave('timezone', 'Timezone', () => save.promise);
  setDraft('timezone', 'Timezone', true); discardDraft('timezone');
  save.resolve(41); await p;
  expect(kinds()).toEqual(['discarded']);
  await trackSave('timezone', 'Timezone', () => Promise.resolve(42));
  expect(outstanding()).toEqual([]);
});

test('a newer overlapping attempt cannot clear a discard stamped before it', async () => {
  const old = deferred(); const latest = deferred();
  const p1 = trackSave('timezone', 'Timezone', () => old.promise);
  setDraft('timezone', 'Timezone', true); discardDraft('timezone');
  const p2 = trackSave('timezone', 'Timezone', () => latest.promise);
  old.resolve(51); await p1; latest.resolve(52); await p2;
  expect(kinds()).toEqual(['unconfirmed', 'discarded']);
  await trackSave('timezone', 'Timezone', () => Promise.resolve(53));
  expect(outstanding()).toEqual([]);
});

test('Zustand subscribers observe pending, failures and recovery without persisting the ledger', async () => {
  localStorage.clear();
  const listener = jest.fn(); const unsubscribe = useSettingsSaveStatus.subscribe(listener);
  await trackSave('risk', 'Risk limits', () => Promise.reject(61)).catch(() => {});
  expect(listener).toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
  unsubscribe();
});

test('an overlapping latest success cannot erase a previously failed save', async () => {
  await trackSave('risk', 'Risk limits', () => Promise.reject(81)).catch(() => {});
  const old = deferred(); const latest = deferred();
  const p1 = trackSave('risk', 'Risk limits', () => old.promise);
  const p2 = trackSave('risk', 'Risk limits', () => latest.promise);
  latest.resolve(82); await p2; old.resolve(83); await p1;
  expect(kinds()).toEqual(['failed', 'unconfirmed']);
  await trackSave('risk', 'Risk limits', () => Promise.resolve(84));
  expect(outstanding()).toEqual([]);
});
