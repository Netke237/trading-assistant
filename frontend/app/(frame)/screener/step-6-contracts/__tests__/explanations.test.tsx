import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Step6Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import type { OptionContract, TradeCardData } from '@/types/domain';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-6-contracts',
}));

jest.mock('@/lib/api', () => ({
  api: {
    getContracts: jest.fn(),
    addWatchedContract: jest.fn().mockResolvedValue({ contract_id: 'x' }),
  },
}));

const getContracts = api.getContracts as jest.Mock;

const MOCK_EXPLANATION = {
  contract_id: 'XOM|190|2026-12-18|C',
  version: 1,
  evaluated_at: '2026-10-03T12:00:00Z',
  outcome: 'aggregate' as const,
  score: 72,
  status: 'PASS' as const,
  weights: { liquidity: 0.25, spread: 0.25, delta: 0.2, dte: 0.15, iv_rank: 0.15 },
  pass_threshold: 65,
  caution_threshold: 45,
  unrounded_score: 72.4,
  rounded_score: 72,
  components: {
    liquidity: { name: 'liquidity', wire_name: 'liquidity', raw_score: 80, weight: 0.25, contribution: 20, lost_points: 5, flags: [] },
    spread: { name: 'spread', wire_name: 'spread', raw_score: 80, weight: 0.25, contribution: 20, lost_points: 5, flags: [] },
    delta: { name: 'delta', wire_name: 'delta', raw_score: 70, weight: 0.2, contribution: 14, lost_points: 6, flags: [] },
    dte: { name: 'dte', wire_name: 'dte', raw_score: 70, weight: 0.15, contribution: 10.5, lost_points: 4.5, flags: [] },
    iv_rank: { name: 'iv_rank', wire_name: 'iv', raw_score: 52.67, weight: 0.15, contribution: 7.9, lost_points: 7.1, flags: [] },
  },
  largest_losses: [
    { name: 'iv_rank', wire_name: 'iv', raw_score: 52.67, weight: 0.15, contribution: 7.9, lost_points: 7.1, flags: [] },
    { name: 'delta', wire_name: 'delta', raw_score: 70, weight: 0.2, contribution: 14, lost_points: 6.0, flags: [] },
    { name: 'liquidity', wire_name: 'liquidity', raw_score: 80, weight: 0.25, contribution: 20, lost_points: 5.0, flags: [] },
  ],
  blockers: [],
  reject_reasons: [],
  reasons: [],
  soft_flags: [],
  soft_fail_count: 0,
  max_soft_fail_count: 3,
};

const CONTRACT_A: OptionContract = {
  id: 'XOM|190|2026-12-18|C',
  symbol: 'XOM',
  strike: 190,
  expiry: '2026-12-18',
  right: 'C',
  dte: 40,
  dteTotal: 40,
  price: 2.5,
  delta: 0.45,
  theta: -0.05,
  ivRank: 40,
  iv: 30,
  ivPercentile: 40,
  spread: 0.1,
  volume: 100,
  score: 72,
  contractConfidence: 'PASS',
  explanation: MOCK_EXPLANATION,
};

const CONTRACT_B: OptionContract = {
  id: 'XOM|185|2026-12-18|C',
  symbol: 'XOM',
  strike: 185,
  expiry: '2026-12-18',
  right: 'C',
  dte: 40,
  dteTotal: 40,
  price: 3.2,
  delta: 0.55,
  theta: -0.06,
  ivRank: 42,
  iv: 31,
  ivPercentile: 42,
  spread: 0.12,
  volume: 150,
  score: 78,
  contractConfidence: 'PASS',
  explanation: {
    ...MOCK_EXPLANATION,
    contract_id: 'XOM|185|2026-12-18|C',
    score: 78,
    rounded_score: 78,
  },
};

function setupStore(candidateOverrides: Partial<TradeCardData> = {}) {
  useScanStore.setState({
    scanResult: {
      candidates: [
        {
          symbol: 'XOM',
          stockScore: 80,
          direction: 'Bullish',
          contract: 'XOM|185|2026-12-18|C',
          contractDetails: { strike: 185, expiry: '2026-12-18', right: 'C' },
          ...candidateOverrides,
        } as TradeCardData,
      ],
      rejected: [],
      scan_id: 'scan-1',
      timestamp: '2026-10-03T12:00:00Z',
      contract_rules: { min_volume: 20 },
    } as any,
    context: { direction: 'Bullish', horizon: 'Swing (5-20d)', holdMin: 5, holdMax: 20 } as any,
    scanOverrides: {},
    pickedContracts: {},
    contractsBySymbol: {},
  } as any);
}

describe('Step 6 contract score explanations & compact layout', () => {
  beforeEach(() => {
    getContracts.mockReset();
  });

  it('renders the global rules applied banner when returned evaluation snapshots agree', async () => {
    getContracts.mockResolvedValue([CONTRACT_A, CONTRACT_B]);
    setupStore();
    render(<Step6Page />);

    expect(await screen.findByText(/Rules applied: Liquidity 25% · Spread 25% · Delta 20% · DTE 15% · IV 15%/)).toBeInTheDocument();
    expect(screen.getByText(/Pass ≥ 65 · Caution ≥ 45 · Reject < 45/)).toBeInTheDocument();
  });

  it('indicates rules vary per contract if snapshots disagree on weights or thresholds', async () => {
    const CONTRACT_C = {
      ...CONTRACT_B,
      explanation: {
        ...MOCK_EXPLANATION,
        contract_id: 'XOM|185|2026-12-18|C',
        pass_threshold: 70,
      },
    };
    getContracts.mockResolvedValue([CONTRACT_A, CONTRACT_C]);
    setupStore();
    render(<Step6Page />);

    expect(
      await screen.findByText(/Rules applied: Evaluation rules vary per contract/),
    ).toBeInTheDocument();
  });

  it('does not fabricate zero weights for incomplete or future snapshots', async () => {
    getContracts.mockResolvedValue([{ ...CONTRACT_A, explanation: { ...MOCK_EXPLANATION, weights: {} } }]);
    setupStore();
    render(<Step6Page />);
    await screen.findByText(/XOM/);
    fireEvent.click(await screen.findByRole('button', { name: /^Explain score/ }));
    expect(await screen.findByText('Explanation unavailable for this result')).toBeInTheDocument();
    expect(screen.queryByText(/Liquidity 0%/)).not.toBeInTheDocument();
  });

  it('preserves fractional weights from the backend wire keys', async () => {
    getContracts.mockResolvedValue([{ ...CONTRACT_A, explanation: {
      ...MOCK_EXPLANATION,
      weights: { ...MOCK_EXPLANATION.weights, iv_rank: 0.1525, liquidity: 0.2475 },
    } }]);
    setupStore();
    render(<Step6Page />);
    expect(await screen.findByText(/Liquidity 24.75%.*IV 15.25%/)).toBeInTheDocument();
  });

  it('renders candidate spread snapshot banner for spread candidates', async () => {
    getContracts.mockResolvedValue([CONTRACT_A]);
    setupStore({
      spreadType: 'bear_put',
      netDebitCredit: -2.45,
      maxProfit: 255,
      maxLoss: 245,
      breakeven: 182.55,
    });
    render(<Step6Page />);

    expect(await screen.findByText(/Candidate spread snapshot \(Bear Put Spread\):/)).toBeInTheDocument();
    expect(screen.getByText(/−\$2.45/)).toBeInTheDocument();
    expect(screen.getByText(/\$255.00/)).toBeInTheDocument();
    expect(screen.getByText(/\$245.00/)).toBeInTheDocument();
    expect(screen.getByText(/\$182.55/)).toBeInTheDocument();
  });

  it('clicking Explain expands score explanation without selecting or starring the contract', async () => {
    getContracts.mockResolvedValue([CONTRACT_A, CONTRACT_B]);
    setupStore();
    render(<Step6Page />);

    await waitFor(() => expect(getContracts).toHaveBeenCalled());

    // CONTRACT_B (score 78) is Recommended, CONTRACT_A (score 72) is in Full Chain.
    // By default pick is auto-selected to first row (CONTRACT_B).
    const stateBefore = useScanStore.getState().pickedContracts.XOM;

    const explainButtons = await screen.findAllByRole('button', { name: /Explain score for/ });
    expect(explainButtons.length).toBeGreaterThanOrEqual(1);

    // Click explain on CONTRACT_A (in full chain)
    fireEvent.click(explainButtons[1]);

    // Explanation should now be visible
    const region = await screen.findByRole('region', { name: /Score explanation for XOM\|190\|2026-12-18\|C/ });
    expect(region).toBeInTheDocument();
    expect(within(region).getByText('Composite Score:')).toBeInTheDocument();
    expect(within(region).getByText('72')).toBeInTheDocument();
    expect(within(region).getByText('IV Attractiveness')).toBeInTheDocument();

    // Verify pick did NOT change to CONTRACT_A
    expect(useScanStore.getState().pickedContracts.XOM).toBe(stateBefore);

    // Verify star was NOT added
    expect(api.addWatchedContract).not.toHaveBeenCalled();

    // Click Hide to collapse
    const hideBtn = screen.getByRole('button', { name: /Hide score explanation for XOM 190C/ });
    fireEvent.click(hideBtn);

    await waitFor(() => {
      expect(screen.queryByRole('region', { name: /Score explanation for XOM\|190\|2026-12-18\|C/ })).not.toBeInTheDocument();
    });
  });

  it('keyboard Enter on Explain toggle does not select the row', async () => {
    getContracts.mockResolvedValue([CONTRACT_A, CONTRACT_B]);
    setupStore();
    render(<Step6Page />);

    const explainButtons = await screen.findAllByRole('button', { name: /Explain score for/ });
    const btn = explainButtons[1]; // CONTRACT_A

    fireEvent.keyDown(btn, { key: 'Enter', code: 'Enter' });
    fireEvent.click(btn);

    expect(await screen.findByRole('region', { name: /Score explanation for XOM\|190\|2026-12-18\|C/ })).toBeInTheDocument();
    // Pick contract is not updated to CONTRACT_A
    expect(useScanStore.getState().pickedContracts.XOM).not.toBe('XOM|190|2026-12-18|C');
  });

  it('allows sorting by any of the 10 metrics via the sort toolbar', async () => {
    getContracts.mockResolvedValue([CONTRACT_A, CONTRACT_B]);
    setupStore();
    render(<Step6Page />);

    const sortSelect = await screen.findByLabelText(/Sort chain by:/);
    expect(sortSelect).toBeInTheDocument();

    // Change sort to volume
    fireEvent.change(sortSelect, { target: { value: 'volume' } });
    expect(sortSelect).toHaveValue('volume');

    // Toggle sort direction
    const sortDirBtn = screen.getByRole('button', { name: /Sort direction:/ });
    fireEvent.click(sortDirBtn);
    expect(screen.getByText('Asc ↑')).toBeInTheDocument();
  });
});
