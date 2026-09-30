import { render, screen, waitFor } from '@testing-library/react';
import Step6Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import type { TradeCardData } from '@/types/domain';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-6-contracts',
}));

jest.mock('@/lib/api', () => ({
  api: { getContracts: jest.fn() },
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
