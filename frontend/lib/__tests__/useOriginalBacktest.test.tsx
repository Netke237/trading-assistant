import { act, renderHook } from '@testing-library/react';
import { api, BacktestArtifactError } from '@/lib/api';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { CandidateChartContext } from '@/types/backtest';

jest.mock('@/lib/api', () => ({BacktestArtifactError:jest.requireActual('@/lib/api').BacktestArtifactError,api:{getOriginalBacktest:jest.fn()}}));
const id = '0f15f060-4602-4254-a113-2076894eb97c';
const id2 = '1f15f060-4602-4254-a113-2076894eb97c';
const context: CandidateChartContext = {source:'stocks',symbol:'AAA',artifactId:id,status:'available'};
const artifact = (artifactId=id, symbol='AAA') => ({schema_version:1,artifact_id:artifactId,provenance:'original',identity:{symbol},detail:{status:'success',summary:{n_trades:0},trades:[]}});
beforeEach(() => jest.clearAllMocks());
test('loads only opaque identity and exact candidate symbol, zero trades remains ready', async () => {
  (api.getOriginalBacktest as jest.Mock).mockResolvedValue(artifact());
  const {result} = renderHook(() => useOriginalBacktest(context));
  await act(async () => {});
  expect(api.getOriginalBacktest).toHaveBeenCalledWith(id,'AAA',expect.any(AbortSignal));
  expect(result.current.status).toBe('ready');
});
test.each(['prebreakout','fib'] as const)('unsupported %s never fetches forged IDs', async source => {
  const {result} = renderHook(() => useOriginalBacktest({...context,source}));
  await act(async () => {});
  expect(result.current).toEqual({status:'unavailable',reason:'unsupported'});
  expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});
test.each([
  {...artifact(),artifact_id:id2}, {...artifact(),identity:{symbol:'BBB'}},
  {...artifact(),provenance:'fresh'}, {...artifact(),schema_version:2}, {...artifact(),detail:{status:'failed'}},
])('rejects mismatched reply %#', async reply => {
  (api.getOriginalBacktest as jest.Mock).mockResolvedValue(reply);
  const {result} = renderHook(() => useOriginalBacktest(context));
  await act(async () => {});
  expect(result.current).toEqual({status:'unavailable',reason:'invalid_evidence'});
});
test('late success/error and immediate render cannot expose evidence for another context or active symbol', async () => {
  const pending: {resolve:(value:unknown)=>void;reject:(error:Error)=>void}[] = [];
  (api.getOriginalBacktest as jest.Mock).mockImplementation(() => new Promise((resolve,reject) => pending.push({resolve,reject})));
  const snapshots: string[]=[];
  const {result,rerender} = renderHook(({ctx,symbol}) => {
    const value = useOriginalBacktest(ctx,symbol); snapshots.push(value.status); return value;
  }, {initialProps:{ctx:context,symbol:'AAA'}});
  await act(async () => pending[0].resolve(artifact()));
  expect(result.current.status).toBe('ready');
  snapshots.length=0;
  rerender({ctx:{...context,artifactId:id2},symbol:'AAA'});
  expect(snapshots).not.toContain('ready');
  await act(async () => pending[1].resolve(artifact(id2)));
  expect(result.current.status).toBe('ready');
  snapshots.length=0;
  rerender({ctx:{...context,artifactId:id2},symbol:'BBB'});
  expect(snapshots).not.toContain('ready');
  expect(result.current).toEqual({status:'unavailable',reason:'context_mismatch'});
  snapshots.length=0;
  rerender({ctx:{...context,artifactId:id2},symbol:'AAA'});
  expect(snapshots).not.toContain('ready');
  await act(async () => pending[2].resolve(artifact(id2)));
  rerender({ctx:context,symbol:'AAA'});
  rerender({ctx:{...context,source:'pullback'},symbol:'AAA'});
  await act(async () => pending[3].reject(new Error('old request')));
  expect(result.current.status).toBe('loading');
  await act(async () => pending[4].resolve(artifact()));
  expect(result.current.status).toBe('ready');
});
test('unmount aborts request and generic charts perform no original fetch', () => {
  (api.getOriginalBacktest as jest.Mock).mockReturnValue(new Promise(() => {}));
  const view = renderHook(() => useOriginalBacktest(context));
  const signal = (api.getOriginalBacktest as jest.Mock).mock.calls[0][2] as AbortSignal;
  view.unmount(); expect(signal.aborted).toBe(true);
  jest.clearAllMocks();
  const {result} = renderHook(() => useOriginalBacktest(null));
  expect(result.current).toEqual({status:'idle'});
  expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});


test.each(['unsupported','insufficient_history','invalid_input','failed','invalid_evidence','storage_unavailable','capture_unavailable','original_unavailable'] as const)('candidate status %s never triggers a fresh run or fetch', status => {
  const {result} = renderHook(() => useOriginalBacktest({...context,artifactId:null,status}));
  expect(result.current).toEqual({status:'unavailable',reason:status});
  expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});
test.each(['missing','expired','invalid_input','storage_unavailable'] as const)('server %s remains distinct from successful zero trades', async reason => {
  (api.getOriginalBacktest as jest.Mock).mockRejectedValue(new BacktestArtifactError(reason,404));
  const {result} = renderHook(() => useOriginalBacktest(context));
  await act(async () => {});
  expect(result.current).toEqual({status:'unavailable',reason});
});

test('late success from previous same-symbol scan cannot replace the selected original', async () => {
  const pending: ((value:unknown)=>void)[] = [];
  (api.getOriginalBacktest as jest.Mock).mockImplementation(() => new Promise(resolve => pending.push(resolve)));
  const {result,rerender} = renderHook(({ctx}) => useOriginalBacktest(ctx), {initialProps:{ctx:context}});
  rerender({ctx:{...context,artifactId:id2}});
  await act(async () => pending[1](artifact(id2)));
  expect(result.current.status === 'ready' && result.current.artifact.artifact_id).toBe(id2);
  await act(async () => pending[0](artifact()));
  expect(result.current.status === 'ready' && result.current.artifact.artifact_id).toBe(id2);
});
