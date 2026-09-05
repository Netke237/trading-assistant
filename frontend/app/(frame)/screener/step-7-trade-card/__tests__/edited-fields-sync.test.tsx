import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';

/*
 * The card's edits have to REACH the order. Piece 4 threaded the Premium stop
 * through `handleEditsChange`; Invalidation and Entry limit were left behind,
 * and every send path read the card's ORIGINAL values instead:
 *
 *   - `stop: card.exit.invalidation` in both position builders, so editing
 *     Invalidation from 140 to 132 stored a position whose stop was still 140
 *     and STOP_REACHED fired 8 points early, at a level nothing on screen
 *     still showed. `stop` is an UNDERLYING price compared against the live
 *     stock price (alertEngine.ts), which is what makes this a wrong-trade
 *     defect rather than a cosmetic one.
 *   - `limit_price: card.entry.limit` on the quick Place Limit path and in
 *     AutoTradeArm, and the same value in the button's own label — so an
 *     edited limit was shown, promised, and then not sent.
 *
 * The edits were never wired; the schematic removals deleted `isDirty()`,
 * which was the last code reading them, and that is what made it invisible.
 *
 * Max fill and Time stop are deliberately NOT covered: nothing consumes
 * either one anywhere (TIME_STOP fires on a hardcoded `dteRemaining <= 3`),
 * so there is no send path for a test to pin. Threading those is a build.
 */

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
    getContractQuote: jest.fn().mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-AUTO' }),
  },
}));

const CARD_INVALIDATION = 140;
const CARD_LIMIT = 2.5;

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
    entry: { limit: CARD_LIMIT, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: CARD_INVALIDATION, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
  };
}

const originalFetch = global.fetch;

describe('step-7-trade-card — edited card fields reach the order', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        scanResult: { candidates: [makeCard('AAA')] } as any,
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
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    (api.armAutoTrade as jest.Mock).mockResolvedValue({ armed: true });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  /** The Invalidation / Premium stop / Time stop fields live inside the
   *  collapsed ladder section. */
  function expandLadder() {
    fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
  }

  /** Type a new value into one of the card's EditableKV fields and commit it. */
  function editField(label: string, from: string, to: string) {
    fireEvent.click(screen.getByLabelText(`Edit ${label}`));
    const input = screen.getByDisplayValue(from);
    fireEvent.change(input, { target: { value: to } });
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  async function placeLimit() {
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
  }

  it('sends the EDITED invalidation as the position stop, not the card\'s original', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    await placeLimit();

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const [pos] = usePortfolioStore.getState().positions;
    expect(pos.stop).toBe(132);
    expect(pos.stop).not.toBe(CARD_INVALIDATION);
  });

  it('leaves an UNTOUCHED invalidation on the card\'s own value', async () => {
    // The control. An untouched field caches null rather than a snapshot of the
    // seed, precisely so `mergePlan` moving `exit.invalidation` underneath it
    // still wins.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    await placeLimit();

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(CARD_INVALIDATION);
  });

  it('posts the EDITED entry limit as the order\'s limit_price, and says so on the button', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    // The label is a promise about what the click will do; it has to move too.
    const limitBtn = await screen.findByRole('button', { name: /place limit @ \$2\.71/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: 2.71, order_type: 'LMT' }),
    ));
  });

  it('arms auto-trade at the EDITED entry limit', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));
    fireEvent.click(await screen.findByRole('button', { name: /^Arm —/ }));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: 2.71 }),
    ));
  });
});
