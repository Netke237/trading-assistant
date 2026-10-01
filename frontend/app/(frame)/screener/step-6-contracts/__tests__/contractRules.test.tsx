import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Step6Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import type { TradeCardData } from '@/types/domain';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-6-contracts',
}));

jest.mock('@/lib/api', () => ({
  // ContractStar calls `.catch` on addWatchedContract.
  api: { getContracts: jest.fn(), addWatchedContract: jest.fn().mockResolvedValue({ contract_id: 'x' }) },
}));

const getContracts = api.getContracts as jest.Mock;

const LOOSE = { min_volume: 20, min_open_interest: 75, max_bid_ask_spread_pct: 0.3 };

function setup(contractRules: Record<string, number> | null | undefined, scanOverrides: Record<string, unknown> = {}) {
  useScanStore.setState({
    scanResult: {
      candidates: [{ symbol: 'XOM', stockScore: 80, direction: 'Bullish' } as TradeCardData],
      rejected: [], scan_id: 'x', timestamp: '',
      ...(contractRules !== undefined ? { contract_rules: contractRules } : {}),
    } as any,
    context: { direction: 'Bullish', horizon: 'Swing (5-20d)', holdMin: 5, holdMax: 20 } as any,
    // Always set, so state from one test cannot leak into the next.
    scanOverrides,
    pickedContracts: {},
  } as any);
}

describe('Step 6 grades contracts with the rules the scan applied', () => {
  beforeEach(() => {
    getContracts.mockReset();
    getContracts.mockResolvedValue([]);
  });

  it('sends the scan result\'s contract rules to /api/contracts', async () => {
    setup(LOOSE);
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts.mock.calls[0][2]).toMatchObject({ contract_rules: LOOSE });
    expect(screen.queryByText(/has no recorded contract rules/)).not.toBeInTheDocument();
  });

  it('uses the result, not live Step-3 overrides edited after the scan', async () => {
    setup(LOOSE, { min_volume: 500, min_open_interest: 5000 });
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts.mock.calls[0][2].contract_rules).toEqual(LOOSE);
  });

  it('a scan that overrode nothing sends an empty rule set and shows no notice', async () => {
    setup({});
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts.mock.calls[0][2].contract_rules).toEqual({});
    expect(screen.queryByText(/has no recorded contract rules/)).not.toBeInTheDocument();
  });

  it('a result from before the rules were recorded says so', async () => {
    setup(undefined);
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts.mock.calls[0][2].contract_rules).toBeUndefined();
    expect(screen.getByText(/has no recorded contract rules/)).toBeInTheDocument();
  });

  // The backend serialises a missing ScanResult.contract_rules as null
  // (/api/scan/last restoring an older blob, or a scan that could not record them).
  it('a null rule set from the backend says so too', async () => {
    setup(null);
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts.mock.calls[0][2].contract_rules).toBeUndefined();
    expect(screen.getByText(/has no recorded contract rules/)).toBeInTheDocument();
  });
});

describe('a star records the grading its row was fetched with (WATCHLIST-SCAN-CONTRACT-RULES)', () => {
  const ROW = {
    id: 'XOM|190|2026-12-18|C', symbol: 'XOM', strike: 190, expiry: '2026-12-18', right: 'C',
    dte: 40, dteTotal: 40, price: 2.5, delta: 0.45, theta: -0.05, ivRank: 40, iv: 30, ivPercentile: 40,
    spread: 0.1, volume: 100, score: 72, contractConfidence: 'PASS',
  };

  beforeEach(() => {
    getContracts.mockReset();
    getContracts.mockResolvedValue([ROW]);
    (api.addWatchedContract as jest.Mock).mockClear();
    useWatchedContractsStore.setState({ ids: [], grading: {} });
  });

  const clickStar = async () => {
    const star = await screen.findByRole('button', { name: 'Add contract to watchlist' });
    fireEvent.click(star);
  };

  it('stores exactly the grading getContracts was called with', async () => {
    setup(LOOSE);
    render(<Step6Page />);
    await clickStar();
    const ctx = getContracts.mock.calls[0][2];
    const want = {
      contract_rules: ctx.contract_rules, hold_min_days: ctx.hold_min_days,
      hold_max_days: ctx.hold_max_days, stock_score: ctx.stock_score,
    };
    expect(want).toEqual({ contract_rules: LOOSE, hold_min_days: 5, hold_max_days: 20, stock_score: 80 });
    expect(useWatchedContractsStore.getState().grading[ROW.id]).toEqual(want);
    expect(api.addWatchedContract).toHaveBeenCalledWith(ROW.id, want);
  });

  it('records unknown rules as null (the request omitted them)', async () => {
    setup(undefined);
    render(<Step6Page />);
    await clickStar();
    expect(getContracts.mock.calls[0][2].contract_rules).toBeUndefined();
    expect(useWatchedContractsStore.getState().grading[ROW.id]?.contract_rules).toBeNull();
  });

  it('keeps the fetch-time grading after scanResult is replaced without a refetch', async () => {
    setup(LOOSE);
    render(<Step6Page />);
    await screen.findByRole('button', { name: 'Add contract to watchlist' });
    const prev = useScanStore.getState().scanResult!;
    // Same `candidates` reference: the load effect keyed on rawCandidates does not refetch.
    act(() => { useScanStore.setState({ scanResult: { ...prev, contract_rules: { min_volume: 999 } } as any }); });
    await clickStar();
    expect(getContracts).toHaveBeenCalledTimes(1);
    expect(useWatchedContractsStore.getState().grading[ROW.id]?.contract_rules).toEqual(LOOSE);
  });
});
