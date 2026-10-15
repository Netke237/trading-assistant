import { buildCandidateChartHref, parseCandidateChartContext } from '@/lib/candidateChart';

const id = '0f15f060-4602-4254-a113-2076894eb97c';
const parse = (url: string) => parseCandidateChartContext(new URL(url, 'http://localhost').searchParams);

test.each(['stocks', 'pullback'] as const)('%s carries clicked candidate original ID independent of direction', source => {
  for (const direction of ['Bullish', 'Bearish']) {
    const url = buildCandidateChartHref({symbol: 'BRK.B', direction, backtest_artifact_id: id, backtest_artifact_status: 'available'}, source);
    expect(parse(url)).toEqual({source, symbol: 'BRK.B', artifactId: id, status: 'available'});
    expect(url).not.toContain('direction=');
  }
});
test.each(['prebreakout', 'fib'] as const)('%s cannot manufacture strategy evidence from setup confidence', source => {
  expect(parse(buildCandidateChartHref({symbol:'AAA',backtest_artifact_id:id,backtest_artifact_status:'available'}, source)))
    .toEqual({source,symbol:'AAA',artifactId:null,status:'unsupported'});
});
test('legacy candidate has explicit missing original, ordinary chart has no original scope', () => {
  expect(parse(buildCandidateChartHref({symbol:'AAA'}, 'stocks'))?.status).toBe('original_unavailable');
  expect(parse('/chart?symbol=AAA')).toBeNull();
  expect(parse('/chart')).toBeNull();
});
test.each(['failed','insufficient_history','invalid_evidence','storage_unavailable','capture_unavailable'] as const)('preserves %s without fetching an ID', status => {
  expect(parse(buildCandidateChartHref({symbol:'AAA',backtest_artifact_status:status},'pullback'))?.status).toBe(status);
});
test.each([
  'source=stocks&symbol=AAA&backtest_artifact_status=available&backtest_artifact_id=bad',
  `source=stocks&symbol=AAA&backtest_artifact_status=available&backtest_artifact_id=${id}&backtest_artifact_id=${id}`,
  'source=other&symbol=AAA', 'source=stocks', 'source=stocks&symbol=AAA&symbol=BBB',
])('malformed context never falls through to a normal live chart: %s', query => {
  expect(parse(`/chart?${query}`)?.status).toBe('invalid_input');
});
