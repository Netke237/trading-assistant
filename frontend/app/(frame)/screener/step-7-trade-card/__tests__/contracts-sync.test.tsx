import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is about the shared Contracts
// map, not the method-pick gate, so every fixture stamps a satisfied pick
// for both basket symbols or the new `pickMissing` check leaves every send
// path disabled regardless of what these tests exercise.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

/*
 * Feature 7 regression coverage — the real, pre-existing bug: TradeCard's
 * `overlay.contracts` and every order-placement path (SendToBrokerDialog's
 * own row state, the quick "Place Limit"/"Right Now" buttons, and auto-trade
 * arm) each defaulted to a hardcoded 1 independently, so editing Contracts on
 * the card never changed what actually got sent. These tests exercise a
 * BASKET of 2+ pinned symbols — not just a single-symbol happy path — to
 * prove each symbol's own edited Contracts value reaches every downstream
 * path via the shared per-symbol map, not just the active card.
 */

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
    getContractQuote: jest.fn().mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-AUTO' }),
  },
}));

/* P1b-i -- the direct sends now SAVE FIRST, and a 2xx whose body carries no
 * positive `entryPrice` is treated as unconfirmed (no order is sent). So the
 * persist POST ECHOES its request body back, which carries the `entryPrice`
 * and `recId` the page sent; every other request keeps the old `{}` reply. */
function echoFetch(): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

function makeCard(symbol: string): TradeCardData {
  return {
    symbol,
    company: `${symbol} Inc.`,
    price: 150,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} 150C 05/15`,
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
    // Every card a current scan produces carries its resolved regime-gate
    // rule; AutoTradeArm refuses one that does not.
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

const originalFetch = global.fetch;

describe('step-7-trade-card — shared per-symbol Contracts map (Feature 7)', () => {
  it('keeps one exit selector inline in Final Recommendation, outside broker execution', async () => {
    render(<Step7TradeCardPage />);
    const summary = await screen.findByRole('region', { name: 'Final Recommendation' });
    expect(within(summary).getByRole('radio', { name: 'Ladder' })).toBeVisible();
    expect(screen.getAllByRole('radio', { name: 'Ladder' })).toHaveLength(1);
    const execution = screen.getByText('Decision and execution').parentElement!;
    expect(within(execution).queryByRole('radio', { name: 'Ladder' })).not.toBeInTheDocument();
  });

  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        scanResult: { scan_id: 'test-scan', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        optionsCardEdits: {
          ...emptyCardEdits(),
          scanId: 'test-scan',
          picks: {
            'AAA|150|2026-05-15|C': pick(),
            'BBB|150|2026-05-15|C': pick(),
          },
        },
        pickedContracts: {},
        contractsBySymbol: {},
        scanOverrides: {},
      } as any);
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
      useSettingsStore.setState((s) => ({
        ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      }) as any);
      useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    });
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    (api.armAutoTrade as jest.Mock).mockResolvedValue({ armed: true });
    global.fetch = echoFetch();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  function editContracts(value: string) {
    const trigger = screen.getByLabelText('Edit Contracts');
    fireEvent.click(trigger);
    const input = screen.getByDisplayValue('1');
    fireEvent.change(input, { target: { value } });
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  it('carries each pinned symbol\'s own edited Contracts value into the broker dialog', async () => {
    render(<Step7TradeCardPage />);

    // AAA is active first — edit its Contracts to 3, then pin it.
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument());
    editContracts('3');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('3'));
    fireEvent.click(screen.getByTitle('Pin to basket'));

    // Move to BBB, edit its Contracts to 5, pin it too.
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('1'));
    editContracts('5');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('5'));
    fireEvent.click(screen.getByTitle('Pin to basket'));

    // Open the basket dialog.
    fireEvent.click(screen.getByRole('button', { name: /track basket \(2\)/i }));

    await waitFor(() => expect(screen.getByLabelText('Contracts for AAA')).toBeInTheDocument());
    expect(screen.getByLabelText('Contracts for AAA')).toHaveValue(3);
    expect(screen.getByLabelText('Contracts for BBB')).toHaveValue(5);
  });

  it('resets the contract count when a new scan result lands (A8, open_questions[68])', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument());
    editContracts('3');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('3'));

    // A new run of the same symbols, landing while the page is mounted (the
    // StoreHydration-after-mount path). A size typed against the old run must
    // not ride into the new run's order.
    act(() => {
      useScanStore.setState({
        scanResult: { scan_id: 'test-scan-2', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        optionsCardEdits: {
          ...emptyCardEdits(), scanId: 'test-scan-2',
          picks: { 'AAA|150|2026-05-15|C': pick(), 'BBB|150|2026-05-15|C': pick() },
        },
      } as any);
    });
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('1'));
  });

  it('uses the shared map\'s edited value — not a hardcoded 1 — on the quick "Place Limit" and "Right Now — Market" paths', async () => {
    render(<Step7TradeCardPage />);

    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument());
    editContracts('4');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('4'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));

    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ quantity: 4, order_type: 'LMT' }),
    ));
    // Wait for the whole async placeLimitPaper chain (persistPosition's fetch,
    // addPosition, then the `finally` setLimitPlacing(false)) to settle — the
    // Market button is also gated on `limitPlacing`, so clicking it too early
    // (right after postOptionOrder was merely CALLED, not yet resolved end to
    // end) would silently no-op on a still-disabled button.
    const marketBtn = screen.getByRole('button', { name: /right now/i });
    await waitFor(() => expect(marketBtn).toBeEnabled());

    (api.postOptionOrder as jest.Mock).mockClear();
    // P1b-i: a direct send refuses a contract this browser already tracks
    // (the local duplicate check), and the Limit send above just saved one.
    // This test is about the quantity, so start the Market send from an empty
    // portfolio.
    act(() => { usePortfolioStore.setState({ positions: [] }); });
    fireEvent.click(marketBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ quantity: 4, order_type: 'MKT' }),
    ));
  });

  it('uses the shared map\'s edited value — not a hardcoded 1 — when arming auto-trade', async () => {
    render(<Step7TradeCardPage />);

    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument());
    editContracts('7');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('7'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));

    const armBtn = await screen.findByRole('button', { name: /^Arm —/ });
    fireEvent.click(armBtn);

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledWith(
      expect.objectContaining({ quantity: 7 }),
    ));
  });
});
