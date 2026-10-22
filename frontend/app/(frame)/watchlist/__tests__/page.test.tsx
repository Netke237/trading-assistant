import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import WatchlistPage from '../page';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { useWatchlistUiStore } from '@/lib/watchlistUiStore';
import { useChartStore } from '@/lib/chartStore';
import { contractLabel, type ContractGrading, type OptionContract, type WatchlistRow } from '@/types/domain';
import { localTodayIso } from '@/lib/contractGrading';

const row: WatchlistRow = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 190, direction: 'Bullish', horizon: 'Swing',
  score: 80, rankDelta: 0, status: 'PASS',
  breakdown: { trend: 0, pullback: 0, trigger: 0, event: 0, volatility: 0 },
  nextEventDays: null, nextEventLabel: null,
};

jest.mock('@/lib/api', () => ({
  api: {
    getWatchlist: jest.fn().mockResolvedValue([]),
    listCompositeWatches: jest.fn().mockResolvedValue([]),
    getContracts: jest.fn().mockResolvedValue([]),
    getWatchedContractsDetail: jest.fn().mockResolvedValue([]),
    getWatchedContracts: jest.fn().mockResolvedValue([]),
    removeWatchedContract: jest.fn().mockResolvedValue(undefined),
    addWatchedContract: jest.fn().mockResolvedValue({ contract_id: 'x' }),
  },
}));
import { api } from '@/lib/api';

// Selecting a row opens InlineChartPanel, which renders the real
// CandlestickChart/IndicatorPanel — not under test here. Stub it out; row
// selection is exercised via the store, not the chart it happens to open.
jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: () => null,
}));

describe('WatchlistPage — row selection drives the shared UI stores end to end', () => {
  beforeEach(() => {
    useWatchlistStore.setState({ added: [] } as any);
    useWatchedContractsStore.setState({ ids: [], grading: {} });
    useWatchlistUiStore.setState({ selectedSymbol: null });
    useChartStore.setState({ symbol: '', symbolName: '' } as any);
    (api.getWatchlist as jest.Mock).mockResolvedValue([row]);
  });

  it('clicking a row sets watchlistUiStore.selectedSymbol, and clicking it again clears it', async () => {
    render(<WatchlistPage />);
    const symbolCell = await screen.findByText('AAPL');
    const rowEl = symbolCell.closest('[role="button"]') as HTMLElement;
    expect(rowEl).toBeTruthy();

    await act(async () => { rowEl.click(); });
    expect(useWatchlistUiStore.getState().selectedSymbol).toBe('AAPL');

    await act(async () => { rowEl.click(); });
    expect(useWatchlistUiStore.getState().selectedSymbol).toBeNull();
  });

  it('never logs React\'s cross-component update warning on click (regression: setState-in-updater side effect)', async () => {
    // The warning only fires when another mounted component actually
    // subscribes to watchlistUiStore — verified empirically: rendering
    // WatchlistPage alone (even under StrictMode) never triggers it,
    // because nothing re-renders in response to the store update. In the
    // real app, @contextRail/watchlist/page.tsx is that subscriber, mounted
    // alongside this page via a parallel route. This minimal stand-in
    // mirrors just its subscription, not its full implementation.
    //
    // Also requires StrictMode — verified empirically: reverting onSelect to
    // the old setState-in-updater form still passed this test without it.
    // Next actually runs with reactStrictMode: true in dev (see
    // next.config), so wrapping here is what makes this test able to catch
    // that regression.
    function RailSubscriberStandIn() {
      const symbol = useWatchlistUiStore((s) => s.selectedSymbol);
      return <div data-testid="rail-stand-in">{symbol ?? 'none'}</div>;
    }

    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <React.StrictMode>
        <WatchlistPage />
        <RailSubscriberStandIn />
      </React.StrictMode>,
    );
    const symbolCell = await screen.findByText('AAPL');
    const rowEl = symbolCell.closest('[role="button"]') as HTMLElement;
    expect(rowEl).toBeTruthy();

    await act(async () => { rowEl.click(); });
    expect(screen.getByTestId('rail-stand-in')).toHaveTextContent('AAPL');

    const badWarning = errorSpy.mock.calls.some((c) =>
      String(c[0]).includes('Cannot update a component')
    );
    expect(badWarning).toBe(false);
    errorSpy.mockRestore();
  });
});

// ── Contracts tab: stars graded as the scan did (WATCHLIST-SCAN-CONTRACT-RULES) ──

// Dates relative to now: no test may start failing when a literal date passes.
const isoIn = (days: number) => localTodayIso(new Date(Date.now() + days * 86_400_000));
const E    = isoIn(40);
const E2   = isoIn(47);
const PAST = isoIn(-3);

const G:  ContractGrading = { contract_rules: { min_volume: 20 }, hold_min_days: 20, hold_max_days: 25, stock_score: 72 };
const G2: ContractGrading = { ...G, stock_score: 55 };

const getContracts = api.getContracts as jest.Mock;

function oc(id: string, score = 50, over: Partial<OptionContract> = {}): OptionContract {
  const [symbol, strike, expiry, right] = id.split('|');
  return {
    id, symbol: symbol!, strike: Math.trunc(Number(strike)), expiry: expiry!, right: right as 'C' | 'P',
    dte: 40, dteTotal: 40, price: 2.5, delta: 0.45, theta: -0.05, ivRank: 40, spread: 0.1,
    volume: 100, score, contractConfidence: 'PASS', ...over,
  } as OptionContract;
}

/** Answers every group with a row per asked strike, scored `score`. */
const answer = (score = 50) => (sym: string, right: string, ctx: { expiry: string; strikes: number[] }) =>
  Promise.resolve(ctx.strikes.map((k) => oc(`${sym}|${k}|${ctx.expiry}|${right}`, score)));

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/** Local state AND what the mount-time /detail sync serves agree. */
function seed(ids: string[], grading: Record<string, ContractGrading> = {}) {
  useWatchedContractsStore.setState({ ids, grading });
  (api.getWatchedContractsDetail as jest.Mock).mockResolvedValue(
    ids.map((id) => ({ contract_id: id, grading: grading[id] ?? null })));
}

async function openContracts() {
  render(<WatchlistPage />);
  await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Contracts/ })); });
}

const labelOf = (id: string) => {
  const [symbol, strike, expiry, right] = id.split('|');
  return contractLabel({ symbol: symbol!, strike: parseFloat(strike!), expiry: expiry!, right: right as 'C' | 'P' });
};
const rowOf = (id: string) => screen.getByText(labelOf(id)).closest('[data-status]') as HTMLElement;
const rowText = (id: string) => rowOf(id).textContent ?? '';
const BANNER = 'Could not load option chains — retry';

describe('WatchlistPage — Contracts tab grades each star with its own grading', () => {
  const A  = `AAPL|187|${E}|C`;
  const B  = `AAPL|190|${E}|C`;

  beforeEach(() => {
    jest.clearAllMocks();
    useWatchlistStore.setState({ added: [] } as any);
    (api.getWatchlist as jest.Mock).mockResolvedValue([row]);
    (api.removeWatchedContract as jest.Mock).mockResolvedValue(undefined);
    getContracts.mockReset();
    getContracts.mockImplementation(answer());
    seed([]);
  });

  // a
  it('calls getContracts with the star\'s expiry, strikes and grading', async () => {
    seed([A], { [A]: G });
    await openContracts();
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(getContracts).toHaveBeenCalledTimes(1);
    const [sym, right, ctx] = getContracts.mock.calls[0];
    expect([sym, right]).toEqual(['AAPL', 'C']);
    expect(ctx).toEqual({
      expiry: E, strikes: [187], contract_rules: { min_volume: 20 },
      hold_min_days: 20, hold_max_days: 25, stock_score: 72,
    });
  });

  // b
  it('two gradings on one symbol/right are two requests, each row graded by its own', async () => {
    seed([A, B], { [A]: G, [B]: G2 });
    getContracts.mockImplementation((sym: string, right: string, ctx: { expiry: string; stock_score: number }) =>
      // Both groups return BOTH contracts: flat matching would mix them up.
      Promise.resolve([oc(A, ctx.stock_score === 72 ? 11 : 22), oc(B, ctx.stock_score === 72 ? 11 : 22)]));
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('11')).toBeInTheDocument());
    expect(getContracts).toHaveBeenCalledTimes(2);
    expect(within(rowOf(B)).getByText('22')).toBeInTheDocument();
  });

  // c
  it('a star with no grading sends only expiry and strikes and shows the YAML marker', async () => {
    seed([A, B], { [B]: G });
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    const calls = getContracts.mock.calls.map((c) => c[2]);
    expect(calls).toContainEqual({ expiry: E, strikes: [187] });
    expect(within(rowOf(A)).getByText('Graded on contract_rules.yaml', { exact: false })).toBeInTheDocument();
    expect(within(rowOf(B)).queryByText('Graded on contract_rules.yaml', { exact: false })).toBeNull();
  });

  it('a legacy 187.0 star matched by trunc renders starred and unstars on click', async () => {
    const legacy = `AAPL|187.0|${E}|C`;
    seed([legacy]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(legacy)).getByText('50')).toBeInTheDocument());
    const star = within(rowOf(legacy)).getByRole('button', { name: 'Remove contract from watchlist' });
    expect(star).toHaveAttribute('aria-pressed', 'true');
    await act(async () => { fireEvent.click(star); });
    expect(api.removeWatchedContract).toHaveBeenCalledWith(legacy);
  });

  // d
  it('two expiries of one symbol/right/grading are two requests, both rows shown', async () => {
    const A2 = `AAPL|187|${E2}|C`;
    seed([A, A2]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A2)).getByText('50')).toBeInTheDocument());
    expect(within(rowOf(A)).getByText('50')).toBeInTheDocument();
    expect(getContracts.mock.calls.map((c) => c[2].expiry).sort()).toEqual([E, E2].sort());
  });

  // e
  it('shows Loading… (PENDING) until its group settles, then Not in the current chain (NO_DATA)', async () => {
    seed([A]);
    const d = deferred<OptionContract[]>();
    getContracts.mockReturnValueOnce(d.promise);
    await openContracts();
    expect(rowText(A)).toContain('Loading…');
    expect(rowText(A)).not.toContain('Not in the current chain');
    expect(rowOf(A)).toHaveAttribute('data-status', 'PENDING');
    await act(async () => { d.resolve([]); });
    expect(rowText(A)).toContain('Not in the current chain');
    expect(rowOf(A)).toHaveAttribute('data-status', 'NO_DATA');
    expect(within(rowOf(A)).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('a strike joining a group is Loading… while the first row keeps its score', async () => {
    seed([A], { [A]: G });
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    const d = deferred<OptionContract[]>();
    getContracts.mockReturnValueOnce(d.promise);
    await act(async () => { useWatchedContractsStore.getState().add(B, G); });
    expect(rowText(B)).toContain('Loading…');
    expect(within(rowOf(A)).getByText('50')).toBeInTheDocument();
    await act(async () => { d.resolve([oc(A, 60), oc(B, 61)]); });
    expect(within(rowOf(B)).getByText('61')).toBeInTheDocument();
  });

  it('Refresh in flight keeps every live score', async () => {
    seed([A, B]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    getContracts.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeInTheDocument();
    expect(within(rowOf(A)).getByText('50')).toBeInTheDocument();
    expect(within(rowOf(B)).getByText('50')).toBeInTheDocument();
    expect(screen.queryByText('Loading…')).toBeNull();
  });

  it('unstarring a sibling keeps the other row\'s score (superset match)', async () => {
    seed([A, B]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(B)).getByText('50')).toBeInTheDocument());
    getContracts.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => {
      fireEvent.click(within(rowOf(B)).getByRole('button', { name: 'Remove contract from watchlist' }));
    });
    expect(within(rowOf(A)).getByText('50')).toBeInTheDocument();
    expect(screen.queryByText('Loading…')).toBeNull();
  });

  it('a failed group stays "Could not load the chain" while a Refresh is pending', async () => {
    seed([A]);
    getContracts.mockRejectedValueOnce(new Error('API /api/contracts → 503: x'));
    await openContracts();
    await waitFor(() => expect(rowText(A)).toContain('Could not load the chain — retry'));
    getContracts.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(rowText(A)).toContain('Could not load the chain — retry');
    expect(rowText(A)).not.toContain('Loading…');
  });

  it('an aborted refresh settling late cannot overwrite the newer one', async () => {
    seed([A, B]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    const r1 = deferred<OptionContract[]>();
    getContracts.mockReturnValueOnce(r1.promise);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    getContracts.mockImplementationOnce(answer(60));  // R2
    await act(async () => {
      fireEvent.click(within(rowOf(B)).getByRole('button', { name: 'Remove contract from watchlist' }));
    });
    await waitFor(() => expect(within(rowOf(A)).getByText('60')).toBeInTheDocument());
    await act(async () => { r1.resolve([oc(A, 99), oc(B, 99)]); });
    expect(within(rowOf(A)).getByText('60')).toBeInTheDocument();
  });

  it('a past expiry is Expired with no request; a rejected group does not hide another', async () => {
    const X = `AAPL|200|${PAST}|C`;
    const M = `MSFT|400|${E}|P`;
    seed([X, A, M]);
    getContracts.mockImplementation((sym: string, right: string, ctx: { expiry: string; strikes: number[] }) =>
      sym === 'MSFT' ? Promise.reject(new Error('API /api/contracts → 503: x')) : answer()(sym, right, ctx));
    await openContracts();
    await waitFor(() => expect(rowText(M)).toContain('Could not load the chain — retry'));
    expect(rowText(X)).toContain('Expired');
    expect(within(rowOf(A)).getByText('50')).toBeInTheDocument();
    expect(getContracts.mock.calls.map((c) => c[2].expiry)).not.toContain(PAST);
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('missing rows sort last under score, price and dte in both directions', async () => {
    const X = `AAPL|200|${PAST}|C`;
    const L2 = `AAPL|195|${E}|C`;
    seed([X, A, L2]);
    getContracts.mockImplementation((sym: string, right: string, ctx: { expiry: string; strikes: number[] }) =>
      Promise.resolve(ctx.strikes.map((k) => oc(`${sym}|${k}|${ctx.expiry}|${right}`, k, { price: k / 10, dte: k }))));
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('187')).toBeInTheDocument());
    for (const label of ['SCORE', 'PRICE', 'DTE']) {
      for (let i = 0; i < 2; i++) {
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${label}`) })); });
        const order = Array.from(document.querySelectorAll('[data-status]')).map((el) => el.textContent ?? '');
        const contractRows = order.filter((t) => t.includes('AAPL 1') || t.includes('AAPL 2'));
        expect(contractRows[contractRows.length - 1]).toContain('Expired');
      }
    }
  });

  // f
  it('an unreadable id is its own row, never sent, and can be unstarred', async () => {
    const bad = `AAPL|abc|${E}|C`;
    seed([bad, A]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    expect(getContracts).toHaveBeenCalledTimes(1);
    expect(getContracts.mock.calls[0][2].strikes).toEqual([187]);
    const badRow = screen.getByText(bad).closest('[data-status]') as HTMLElement;
    expect(badRow.textContent).toContain('Unreadable contract id');
    expect(badRow).toHaveAttribute('data-status', 'NO_DATA');
    await act(async () => {
      fireEvent.click(within(badRow).getByRole('button', { name: 'Remove contract from watchlist' }));
    });
    expect(api.removeWatchedContract).toHaveBeenCalledWith(bad);
  });

  // g
  it('every star expired or unreadable: no request and no banner', async () => {
    seed([`AAPL|200|${PAST}|C`, 'junk']);
    await openContracts();
    await act(async () => {});
    expect(getContracts).not.toHaveBeenCalled();
    expect(screen.queryByText(BANNER)).toBeNull();
    expect(screen.getByText('junk')).toBeInTheDocument();
  });

  it('a raised banner clears when every remaining star is expired or unreadable', async () => {
    // Starts with the banner ON, so the zero-groups early return's reset is
    // what turns it off (the test above starts with it off).
    seed([A]);
    getContracts.mockRejectedValue(new Error('API /api/contracts → 503: x'));
    await openContracts();
    await waitFor(() => expect(screen.getByText(BANNER)).toBeInTheDocument());
    await act(async () => { useWatchedContractsStore.setState({ ids: [`AAPL|200|${PAST}|C`, 'junk'], grading: {} }); });
    expect(screen.queryByText(BANNER)).toBeNull();
    expect(getContracts).toHaveBeenCalledTimes(1);
  });

  it('a grading-only change (same ids) refetches with the new grading', async () => {
    seed([A], { [A]: G });
    getContracts.mockImplementation((sym: string, right: string, ctx: { expiry: string; stock_score: number }) =>
      Promise.resolve([oc(A, ctx.stock_score === 72 ? 11 : 22)]));
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('11')).toBeInTheDocument());
    const ids = useWatchedContractsStore.getState().ids;
    await act(async () => { useWatchedContractsStore.setState({ grading: { [A]: G2 } }); });
    expect(useWatchedContractsStore.getState().ids).toBe(ids);   // ids untouched: only `grading` can trigger it
    await waitFor(() => expect(within(rowOf(A)).getByText('22')).toBeInTheDocument());
    expect(getContracts).toHaveBeenLastCalledWith('AAPL', 'C', expect.objectContaining({ stock_score: 55 }), expect.anything());
  });

  it('the chain banner shows on the Contracts tab only', async () => {
    seed([A]);
    getContracts.mockRejectedValue(new Error('API /api/contracts → 503: x'));
    await openContracts();
    await waitFor(() => expect(screen.getByText(BANNER)).toBeInTheDocument());
    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Stocks/ })); });
    expect(screen.queryByText(BANNER)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Composite/ })); });
    expect(screen.queryByText(BANNER)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Contracts/ })); });
    expect(screen.getByText(BANNER)).toBeInTheDocument();
  });

  it('the banner shows only when every fetched group failed', async () => {
    seed([A, `MSFT|400|${E}|P`]);
    getContracts.mockRejectedValue(new Error('API /api/contracts → 503: x'));
    await openContracts();
    await waitFor(() => expect(screen.getByText(BANNER)).toBeInTheDocument());
    expect(screen.queryByText(/Backend not running/)).toBeNull();
  });

  it('a slow fetch rejecting after the last unstar raises no banner', async () => {
    seed([A]);
    const d = deferred<OptionContract[]>();
    getContracts.mockReturnValueOnce(d.promise);
    await openContracts();
    await act(async () => { useWatchedContractsStore.setState({ ids: [], grading: {} }); });
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
    await act(async () => { d.reject(new Error('API /api/contracts → 503: x')); });
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('unstarring the last valid star beside an expired one resets Refreshing… and raises no banner', async () => {
    const X = `AAPL|200|${PAST}|C`;
    seed([X, A]);
    const d = deferred<OptionContract[]>();
    getContracts.mockReturnValueOnce(d.promise);
    await openContracts();
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(within(rowOf(A)).getByRole('button', { name: 'Remove contract from watchlist' }));
    });
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
    await act(async () => { d.reject(new Error('API /api/contracts → 503: x')); });
    expect(screen.queryByText(BANNER)).toBeNull();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('a contracts success does not clear a stocks failure', async () => {
    (api.getWatchlist as jest.Mock).mockRejectedValue(new Error('down'));
    seed([A]);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Stocks/ })); });
    expect(screen.getByText(/Backend not running/)).toBeInTheDocument();
  });

  it('stocks offline banner shows only on the Stocks tab', async () => {
    (api.getWatchlist as jest.Mock).mockRejectedValue(new Error('down'));
    render(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/Backend not running/)).toBeInTheDocument());

    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Contracts/ })); });
    expect(screen.queryByText(/Backend not running/)).toBeNull();

    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Composite/ })); });
    expect(screen.queryByText(/Backend not running/)).toBeNull();

    await act(async () => { fireEvent.click(screen.getByRole('tab', { name: /Stocks/ })); });
    expect(screen.getByText(/Backend not running/)).toBeInTheDocument();
  });

  it('aborts in-flight contracts fetch on unmount', async () => {
    seed([A]);
    let signal: AbortSignal | undefined;
    getContracts.mockImplementation((_sym: string, _right: string, _ctx: any, sig?: AbortSignal) => {
      signal = sig;
      return new Promise(() => {});
    });
    const { unmount } = render(<WatchlistPage />);
    await waitFor(() => expect(getContracts).toHaveBeenCalled());
    expect(signal).toBeDefined();
    expect(signal?.aborted).toBe(false);

    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it('counts every star, missing rows included', async () => {
    seed([A, `AAPL|200|${PAST}|C`, 'junk']);
    await openContracts();
    await waitFor(() => expect(within(rowOf(A)).getByText('50')).toBeInTheDocument());
    expect(screen.getByText(/^3 starred contracts/)).toBeInTheDocument();
  });
});
