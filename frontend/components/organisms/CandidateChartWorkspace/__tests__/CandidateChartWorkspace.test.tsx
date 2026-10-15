import { act, render, screen } from '@testing-library/react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import CandidateChartWorkspace from '..';

jest.mock('next/navigation', () => ({useSearchParams: jest.fn()}));
jest.mock('@/lib/api', () => ({BacktestArtifactError: jest.requireActual('@/lib/api').BacktestArtifactError, api: {getOriginalBacktest:jest.fn()}}));
jest.mock('@/components/organisms/ChartWorkspace', () => ({__esModule:true, default: function Probe() {
  const {useCandidateBacktest} = jest.requireActual('..');
  const {context,state} = useCandidateBacktest();
  return <div data-testid="scope">{JSON.stringify({context,state})}</div>;
}}));
jest.mock('@/components/organisms/CandidateBacktestWorkspace', () => ({__esModule:true, default: function HistoricalProbe() {
  const {useCandidateBacktest} = jest.requireActual('..');
  return <div data-testid="scope">{JSON.stringify(useCandidateBacktest())}</div>;
}}));
const id = '0f15f060-4602-4254-a113-2076894eb97c';
beforeEach(() => jest.clearAllMocks());

test('ordinary chart remains live with no original fetch', () => {
  (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('symbol=AAA'));
  render(<CandidateChartWorkspace/>);
  expect(screen.getByTestId('scope')).toHaveTextContent('"context":null,"state":{"status":"idle"}');
  expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});

test('new-tab route reconstructs original identity without scan stores and exposes unavailable legacy scope', async () => {
  const storageBefore = JSON.stringify(localStorage);
  (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams(`symbol=AAA&source=pullback&backtest_artifact_status=available&backtest_artifact_id=${id}`));
  (api.getOriginalBacktest as jest.Mock).mockResolvedValue({schema_version:1,artifact_id:id,provenance:'original',identity:{symbol:'AAA'},detail:{status:'success'}});
  const view = render(<CandidateChartWorkspace/>);
  await act(async () => {});
  expect(screen.getByTestId('scope')).toHaveTextContent('"status":"ready"');
  expect(api.getOriginalBacktest).toHaveBeenCalledTimes(1);
  (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('symbol=AAA&source=stocks&backtest_artifact_status=original_unavailable'));
  view.rerender(<CandidateChartWorkspace/>);
  expect(screen.getByTestId('scope')).toHaveTextContent('"status":"unavailable","reason":"original_unavailable"');
  expect(screen.getByTestId('scope')).not.toHaveTextContent('"artifact":');
  expect(api.getOriginalBacktest).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(localStorage)).toBe(storageBefore);
});

test.each(['failed','unsupported','insufficient_history'])( 'unavailable %s is distinct from successful zero trades', (reason) => {
  (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams(`symbol=AAA&source=stocks&backtest_artifact_status=${reason}`));
  render(<CandidateChartWorkspace/>);
  expect(screen.getByRole('status')).toHaveTextContent(`Original backtest unavailable: ${reason}`);
  expect(screen.queryByText(/Successful result: zero closed trades/)).not.toBeInTheDocument();
  expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});
