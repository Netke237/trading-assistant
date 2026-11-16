/** Every original-evidence state keeps its meaning under the review header, with the labelled live fallback. */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { useSearchParams } from 'next/navigation';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { OriginalBacktestState, OriginalBacktestUnavailableReason } from '@/types/backtest';
import CandidateChartWorkspace, { formatUnavailableReason } from '..';

jest.mock('next/navigation', () => ({useSearchParams: jest.fn()}));
jest.mock('@/lib/useOriginalBacktest', () => ({useOriginalBacktest: jest.fn()}));
jest.mock('@/lib/api', () => ({api: {getOriginalBacktest: jest.fn(), getFreshBacktestConfiguration: jest.fn(() => new Promise(() => {})), runFreshBacktest: jest.fn()}}));
jest.mock('@/components/organisms/ChartWorkspace', () => ({__esModule: true, default: () => <div data-testid="live-chart">Live chart</div>}));
jest.mock('@/components/organisms/CandidateBacktestWorkspace', () => ({__esModule: true, default: ({artifact}: any) => <div data-testid="report">{artifact.artifact_id}</div>}));

const setState = (state: OriginalBacktestState) => (useOriginalBacktest as jest.Mock).mockReturnValue(state);
const header = () => screen.getByRole('region', {name: 'Backtest review'});
beforeEach(() => {
 jest.clearAllMocks();
 (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('symbol=AAA&source=fib&backtest_artifact_status=available&backtest_artifact_id=0f15f060-4602-4254-a113-2076894eb97c'));
});

const reasons: OriginalBacktestUnavailableReason[] = ['unsupported', 'insufficient_history', 'storage_unavailable', 'capture_unavailable', 'original_unavailable', 'invalid_evidence', 'invalid_input', 'failed', 'missing', 'expired', 'context_mismatch'];
test.each(reasons)('unavailable %s keeps its reason, the labelled live chart and an explicit fresh configuration', reason => {
 setState({status: 'unavailable', reason});
 render(<CandidateChartWorkspace/>);
 expect(screen.getByRole('status')).toHaveTextContent(`Original backtest unavailable: ${formatUnavailableReason(reason)}. Live chart below; no historical result has been substituted.`);
 expect(screen.getByTestId('live-chart')).toBeInTheDocument();
 expect(screen.queryByTestId('report')).not.toBeInTheDocument();
 expect(within(header()).getByRole('heading', {level: 1, name: 'AAA / Backtest review'})).toBeInTheDocument();
 expect(within(header()).getByText('No original result')).toBeInTheDocument();
 expect(header()).toHaveTextContent('Pre-Breakout screener · fib / Backtest review / AAA');
 expect(header()).toHaveTextContent('No recorded backtest result is displayed.');
 const toggle = screen.getByRole('button', {name: 'Separate fresh run'});
 expect(toggle).toHaveAttribute('aria-expanded', 'false');
 fireEvent.click(toggle);
 expect(screen.getByLabelText('Fresh strategy')).toHaveValue('');
 expect(screen.getByLabelText('Fresh direction')).toHaveValue('');
});

test('loading keeps its meaning and the live chart; no report is shown yet', () => {
 setState({status: 'loading'});
 render(<CandidateChartWorkspace/>);
 expect(screen.getByRole('status')).toHaveTextContent('Loading original backtest evidence…');
 expect(screen.getByTestId('live-chart')).toBeInTheDocument();
 expect(screen.queryByTestId('report')).not.toBeInTheDocument();
 expect(within(header()).getByText('Loading original scan')).toBeInTheDocument();
 expect(header()).toHaveTextContent('Loading the recorded run identity…');
});

test('the standalone live chart has no review header, disclosure or status', () => {
 (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('symbol=AAA'));
 setState({status: 'idle'});
 render(<CandidateChartWorkspace/>);
 expect(screen.getByTestId('live-chart')).toBeInTheDocument();
 expect(screen.queryByRole('region', {name: 'Backtest review'})).not.toBeInTheDocument();
 expect(screen.queryByRole('button', {name: 'Separate fresh run'})).not.toBeInTheDocument();
 expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
