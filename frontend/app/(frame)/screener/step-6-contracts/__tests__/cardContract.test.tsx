/**
 * STEP3-PARAM-REACH (STEP6-SCAN-CONTRACT-RULES deferred item 3): Step 6 lists
 * the trade card's own contract even when /api/contracts' max_price or limit
 * cut it from the table.
 */
import '@testing-library/jest-dom';
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
  api: { getContracts: jest.fn(), addWatchedContract: jest.fn().mockResolvedValue({ contract_id: 'x' }) },
}));

const getContracts = api.getContracts as jest.Mock;

const CARD_ID = 'XOM|190|2026-12-18|C';
const row = (id: string, strike: number, score: number) => ({
  id, symbol: 'XOM', strike, expiry: '2026-12-18', right: 'C',
  dte: 40, dteTotal: 40, price: 2.5, delta: 0.45, theta: -0.05, ivRank: 40, iv: 30, ivPercentile: 40,
  spread: 0.1, volume: 100, score, contractConfidence: 'PASS',
});
const OTHER = row('XOM|185|2026-12-18|C', 185, 80);
const CARD_ROW = row(CARD_ID, 190, 70);
const RULES = { min_volume: 20 };

function setup() {
  useScanStore.setState({
    scanResult: {
      candidates: [{
        symbol: 'XOM', stockScore: 80, direction: 'Bullish', contract: CARD_ID,
        contractDetails: { strike: 190, expiry: '2026-12-18', right: 'C' },
      } as TradeCardData],
      rejected: [], scan_id: 'x', timestamp: '', contract_rules: RULES,
    } as never,
    context: { direction: 'Bullish', horizon: 'Swing (5–20d)', holdMin: 5, holdMax: 20 } as never,
    scanOverrides: {},
    pickedContracts: {},
    contractsBySymbol: {},
  } as never);
}

describe('Step 6 always lists the card\'s own contract', () => {
  beforeEach(() => getContracts.mockReset());

  it('cut from the table → fetched by expiry + strike with the same grading, and listed', async () => {
    getContracts.mockImplementation((_s: string, _r: string, ctx: { strikes?: number[] }) =>
      Promise.resolve(ctx.strikes ? [CARD_ROW] : [OTHER]));
    setup();
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalledTimes(2));
    const [base, rescue] = getContracts.mock.calls.map((c) => c[2]);
    expect(rescue).toMatchObject({ expiry: '2026-12-18', strikes: [190] });
    expect(rescue.limit).toBeUndefined();
    expect(rescue.max_price).toBeUndefined();
    for (const k of ['contract_rules', 'hold_min_days', 'hold_max_days', 'stock_score', 'direction', 'horizon']) {
      expect(rescue[k]).toEqual(base[k]);
    }
    expect(await screen.findByText(/190C/)).toBeInTheDocument();
    expect(useScanStore.getState().contractsBySymbol.XOM?.map((c) => c.id)).toEqual([OTHER.id, CARD_ID]);
  });

  it('already in the table → no second request', async () => {
    getContracts.mockResolvedValue([OTHER, CARD_ROW]);
    setup();
    render(<Step6Page />);
    await waitFor(() => expect(useScanStore.getState().contractsBySymbol.XOM).toHaveLength(2));
    // The rescue would run before contractsBySymbol is written, so by now it
    // would already have been called.
    expect(getContracts).toHaveBeenCalledTimes(1);
  });

  it('a failed rescue leaves the table as fetched and does not read as offline', async () => {
    getContracts.mockImplementation((_s: string, _r: string, ctx: { strikes?: number[] }) =>
      ctx.strikes ? Promise.reject(new Error('503')) : Promise.resolve([OTHER]));
    setup();
    render(<Step6Page />);
    await waitFor(() => expect(getContracts).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(useScanStore.getState().contractsBySymbol.XOM).toHaveLength(1));
    expect(screen.queryByText(/Backend not running/)).not.toBeInTheDocument();
    expect(screen.queryByText(/outside filters/)).not.toBeInTheDocument();
  });

  /** The contract label in the row right after the "A — RECOMMENDED" label. */
  const recommendedLabel = () => {
    const label = screen.queryByText('A — RECOMMENDED');
    return label?.parentElement?.nextElementSibling?.textContent ?? null;
  };

  it('the rescued row is marked and never Recommended, even when it scores highest', async () => {
    const CARD_TOP = { ...CARD_ROW, score: 95 };
    getContracts.mockImplementation((_s: string, _r: string, ctx: { strikes?: number[] }) =>
      Promise.resolve(ctx.strikes ? [CARD_TOP] : [OTHER]));
    setup();
    render(<Step6Page />);
    expect(await screen.findByText(/outside filters/)).toBeInTheDocument();
    expect(recommendedLabel()).toMatch(/185C/);
    expect(recommendedLabel()).not.toMatch(/190C/);
  });

  it('every row over the cap → no Recommended row, the card contract listed in the chain', async () => {
    getContracts.mockImplementation((_s: string, _r: string, ctx: { strikes?: number[] }) =>
      Promise.resolve(ctx.strikes ? [CARD_ROW] : []));
    setup();
    render(<Step6Page />);
    expect(await screen.findByText(/outside filters/)).toBeInTheDocument();
    expect(screen.queryByText('A — RECOMMENDED')).not.toBeInTheDocument();
    expect(screen.getByText('B — FULL CHAIN')).toBeInTheDocument();
  });

  it('the table is on screen before the rescue answers', async () => {
    let release: (v: unknown) => void = () => {};
    getContracts.mockImplementation((_s: string, _r: string, ctx: { strikes?: number[] }) =>
      ctx.strikes ? new Promise((r) => { release = r; }) : Promise.resolve([OTHER]));
    setup();
    render(<Step6Page />);
    expect(await screen.findByText(/185C/)).toBeInTheDocument();
    expect(getContracts).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/190C/)).not.toBeInTheDocument();
    release([CARD_ROW]);
    expect(await screen.findByText(/190C/)).toBeInTheDocument();
  });
});
