import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import SettingsPage from '../page';
import { getTuningJob, type WfoOosMetrics, type WfoProposal } from '@/lib/api';

// Phase C hygiene T5 (item 3). The backend's oos_metrics carries `n_trades`
// (pooled across the basket, gated by `min_trades`) plus `n_symbols` (gated by
// `min_symbols`). The Strategy Tuning proposal card's "OOS trades" cell shows
// the symbol count beside the pooled trade count, only when it is present
// (proposals persisted before Phase C T5 lack it).
//
// ProposalCard is private to page.tsx (a Next 15 page may not add named
// exports), so the whole page is rendered and navigated to Strategy Tuning,
// with a stored job id whose completed job carries one proposal. Every api
// call reached while that section mounts is mocked:
//   - ScheduleSection:    getTuningSchedule
//   - StrategyTuningForm: getTuningJobCount, getTuningJob

jest.mock('@/lib/api', () => ({
  api: {},
  getRiskSettings: jest.fn().mockResolvedValue(undefined),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
  getTuningSchedule: jest.fn(),
  saveTuningSchedule: jest.fn(),
  startTuningJob: jest.fn(),
  getTuningJob: jest.fn(),
  getTuningJobCount: jest.fn(),
  clearTuningJobs: jest.fn(),
  adoptStrategyParams: jest.fn(),
}));

const mocked = jest.requireMock('@/lib/api') as Record<string, jest.Mock>;

function proposal(oos: WfoOosMetrics): WfoProposal {
  return {
    strategy: 'pullback_ema',
    direction: 'Bullish',
    proposed: { ema_period: 21 },
    consistency: 0.8,
    eligible: true,
    oos_metrics: oos,
    fold_winners: [],
    verdict: { in_sample_return: 10, walk_forward_return: 6, degradation_pct: 0.4 },
    recommendation: 'Adopt',
  };
}

const BASE_OOS: WfoOosMetrics = {
  sharpe: 0.9, expectancy: 0.4, win_rate: 0.55, total_return: 6, max_drawdown: -3, n_trades: 42,
};

async function renderTuning(oos: WfoOosMetrics): Promise<HTMLElement> {
  (getTuningJob as jest.Mock).mockResolvedValue({
    status: 'completed', done: 1, total: 1, proposals: { pullback_ema: proposal(oos) },
  });
  sessionStorage.setItem('bamendjou:wfo:jobId', 'job-1');
  render(<SettingsPage />);
  fireEvent.click(screen.getByText('Strategy Tuning', { selector: 'span, div, p' }));
  const label = await screen.findByText('OOS trades');
  // The value is the label's next sibling in the same cell.
  return label.nextElementSibling as HTMLElement;
}

describe('Settings → Strategy Tuning — OOS trades cell', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();
    mocked.getTuningSchedule.mockResolvedValue({ enabled: false, time: '05:00', next_run: null, days_of_week: [5] });
    mocked.getTuningJobCount.mockResolvedValue({ count: 1, completed: 1, failed: 0, running: 0 });
  });

  it('shows the contributing symbol count beside the pooled trade count', async () => {
    const value = await renderTuning({ ...BASE_OOS, n_trades_per_symbol: 8, n_symbols: 5 });
    expect(value).toHaveTextContent(/^42 · 5 symbols$/);
  });

  it('shows only the trade count for a proposal without n_symbols', async () => {
    const value = await renderTuning(BASE_OOS);
    expect(value).toHaveTextContent(/^42$/);
  });
});
