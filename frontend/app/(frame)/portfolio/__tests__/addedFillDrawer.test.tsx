/**
 * BROKER-PATH T6 — an increase is an added fill. Blurring a larger quantity
 * must not PATCH. The saved average and P&L change only when the server
 * confirms the total, the fill price, and the authoritative base together.
 */
import { useState } from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { EditDrawer } from '../EditDrawer';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { rejectionMessage } from '@/lib/portfolioRejection';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
    getExitPlan: jest.fn(),
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: '2026-08-27T00:00:00Z' }),
  },
}));

const noop = () => {};

function fillPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|220|2026-09-16|C', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
    entryPrice: 10, currentPrice: 18, currentStockPrice: 30,
    // (18 - 10) * 100 * 2. Must stay this until the server confirms a fill.
    pnlDollar: 1600, pnlPct: 80, stop: 12, targets: [
      { id: 'T1', stockPrice: 220, contractsToSell: 1, status: 'PENDING' },
    ],
    status: 'PASS', contracts: 2, recId: 'REC-FILL',
    tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
    ...overrides,
  };
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as unknown as Response;
}

function patchBodies(): Record<string, unknown>[] {
  return (global.fetch as jest.Mock).mock.calls
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String(init.body)) as Record<string, unknown>);
}

function LiveDrawer({ initial, onPatch }: {
  initial: PortfolioPosition;
  onPatch: (p: Partial<PortfolioPosition>) => void;
}) {
  const [pos, setPos] = useState(initial);
  return (
    <EditDrawer
      position={pos}
      onClose={noop}
      onRemove={noop}
      onChange={(patch) => { onPatch(patch); setPos((c) => ({ ...c, ...patch })); }}
    />
  );
}

function StoreDrawer() {
  const position = usePortfolioStore((s) => s.positions.find((p) => p.recId === 'REC-FILL'));
  const updatePosition = usePortfolioStore((s) => s.updatePosition);
  if (!position) return null;
  return (
    <EditDrawer
      position={position}
      onClose={noop}
      onRemove={noop}
      onChange={(patch) => updatePosition(position.contract, patch)}
    />
  );
}

function typeQty(value: string) {
  const contracts = screen.getByLabelText(/Contracts/) as HTMLInputElement;
  fireEvent.change(contracts, { target: { value } });
  fireEvent.blur(contracts);
  return contracts;
}

describe('added-fill drawer', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue(jsonResponse({}));
    act(() => {
      useRiskStore.setState({
        limits: {
          maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
          maxConcurrentPositions: 10, maxDailyRecommendations: 5, portfolioValue: 50000,
          maxLossPerTradePct: 0.0375,
        },
      } as never);
      usePortfolioStore.setState({
        positions: [fillPosition()], lastSyncError: null,
      });
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('increasing quantity alone never PATCHes and does not change the saved size or entry', async () => {
    jest.useFakeTimers();
    const onPatch = jest.fn();
    render(<LiveDrawer initial={fillPosition()} onPatch={onPatch} />);

    const contracts = typeQty('5');

    expect(onPatch).not.toHaveBeenCalled();
    expect(contracts.value).toBe('5');
    expect(usePortfolioStore.getState().positions[0]!.contracts).toBe(2);
    expect(usePortfolioStore.getState().positions[0]!.entryPrice).toBe(10);

    await act(async () => { await jest.advanceTimersByTimeAsync(700); });
    expect(patchBodies()).toHaveLength(0);
    expect(screen.getByLabelText(/Added fill price/i)).toBeInTheDocument();
    jest.useRealTimers();
  });

  it('a decrease still saves on blur, with no fill price', async () => {
    jest.useFakeTimers();
    render(<StoreDrawer />);
    const contracts = typeQty('1');
    expect(contracts.value).toBe('1');
    expect(screen.queryByLabelText(/Added fill price/i)).not.toBeInTheDocument();

    await act(async () => { await jest.advanceTimersByTimeAsync(700); });
    expect(patchBodies()).toEqual([
      expect.objectContaining({ qty: 1 }),
    ]);
    expect(patchBodies()[0]!.addedFillPrice).toBeUndefined();
    expect(patchBodies()[0]!.expectedQty).toBeUndefined();
    jest.useRealTimers();
  });

  it('requires a positive finite fill price and does not send without one', () => {
    const onPatch = jest.fn();
    const { rerender } = render(<LiveDrawer initial={fillPosition()} onPatch={onPatch} />);
    typeQty('5');
    const price = screen.getByLabelText(/Added fill price/i) as HTMLInputElement;
    const confirm = screen.getByRole('button', { name: /Confirm added fill/i });

    for (const bad of ['', '0', '-2', '20.', 'abc']) {
      fireEvent.change(price, { target: { value: bad } });
      fireEvent.click(confirm);
    }

    expect(onPatch).not.toHaveBeenCalled();
    expect(patchBodies()).toHaveLength(0);
    expect(screen.getByText(/positive number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Contracts/)).toHaveValue('5');
    rerender(<LiveDrawer initial={fillPosition()} onPatch={onPatch} />);
    expect(screen.getByText(/positive number/i)).toBeInTheDocument();
  });

  it('focus or blur of an untouched quantity or fill price sends nothing', () => {
    const onPatch = jest.fn();
    render(<LiveDrawer initial={fillPosition()} onPatch={onPatch} />);
    const contracts = screen.getByLabelText(/Contracts/);
    fireEvent.focus(contracts);
    fireEvent.blur(contracts);
    expect(onPatch).not.toHaveBeenCalled();
    expect(patchBodies()).toHaveLength(0);

    typeQty('5');
    const price = screen.getByLabelText(/Added fill price/i);
    fireEvent.focus(price);
    fireEvent.blur(price);
    fireEvent.change(price, { target: { value: '20' } });
    fireEvent.blur(price);
    expect(onPatch).not.toHaveBeenCalled();
    expect(patchBodies()).toHaveLength(0);
  });

  it('confirmation sends the total, the fill price, and the saved base once', async () => {
    render(<StoreDrawer />);
    typeQty('5');
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.blur(screen.getByLabelText(/Added fill price/i));
    expect(patchBodies()).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));
    await act(async () => { await Promise.resolve(); });

    expect(patchBodies()).toHaveLength(1);
    expect(patchBodies()[0]).toMatchObject({
      qty: 5, addedFillPrice: 20, expectedQty: 2,
    });
    // The typed total is not the base, and the average is still the saved one.
    expect(patchBodies()[0]!.expectedQty).not.toBe(5);
    expect(usePortfolioStore.getState().positions[0]!.entryPrice).toBe(10);
    expect(screen.getByText(/Average entry \$10\.00/)).toBeInTheDocument();
  });

  it('keeps an unsent quantity draft across a refresh and confirms against the new base', async () => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue(jsonResponse([{
        id: 'p1', recId: 'REC-FILL', symbol: 'AAPL', contract: 'AAPL|220|2026-09-16|C',
        direction: 'Bullish', entryPrice: 10, qty: 3, entryDate: '2026-08-01',
        stop: 12, targets: [], dteTotal: 30, createdAt: '2026-08-01T00:00:00Z',
        currentPrice: 18, pnlDollar: 2400, pnlPct: 80,
      }]));
    render(<StoreDrawer />);
    const contracts = typeQty('6');

    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });

    expect(contracts.value).toBe('6');
    expect(usePortfolioStore.getState().positions[0]!.contracts).toBe(3);
    expect(usePortfolioStore.getState().positions[0]!.entryPrice).toBe(10);
    expect(patchBodies()).toHaveLength(0);

    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse({ qty: 6, entryPrice: 15 }));
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(patchBodies()).toEqual([
      expect.objectContaining({ qty: 6, addedFillPrice: 20, expectedQty: 3 }),
    ]);
  });

  it('a weighted response updates the average and P&L and ignores a partial size', async () => {
    let resolvePatch: ((value: Response) => void) | null = null;
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn((_url: string, init?: { method?: string }) => {
      if (init?.method === 'PATCH') {
        return new Promise<Response>((resolve) => { resolvePatch = resolve; });
      }
      return Promise.resolve(jsonResponse([]));
    });
    render(<StoreDrawer />);
    typeQty('5');
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));
    await act(async () => { await Promise.resolve(); });

    const row = () => usePortfolioStore.getState().positions[0]!;
    expect(row().entryPrice).toBe(10);
    expect(row().pnlDollar).toBe(1600);
    expect(screen.getByText(/Average entry \$10\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/Average entry \$16\.00/)).not.toBeInTheDocument();

    await act(async () => {
      resolvePatch?.(jsonResponse({ qty: 5, entryPrice: 16, adjustedQty: 2 }));
      await Promise.resolve();
      await Promise.resolve();
    });

    // 2 @ 10 plus 3 @ 20 is 5 @ 16. Mark stays 18. (18 - 16) * 100 * 5 = 1000.
    expect(row().contracts).toBe(5);
    expect(row().entryPrice).toBe(16);
    expect(row().pnlDollar).toBeCloseTo(1000, 6);
    expect(row().pnlPct).toBeCloseTo(12.5, 6);
    expect(screen.getByLabelText(/Contracts/)).toHaveValue('5');
    expect(screen.getByText(/Average entry \$16\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/Size reduced to 2/)).not.toBeInTheDocument();
  });

  it('a stale-base rejection shows the server quantity and entry and keeps the saved stop', async () => {
    jest.useFakeTimers();
    let savedStop = 12;
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn((_url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        if ('stop' in body) savedStop = body.stop as number;
        if ('addedFillPrice' in body || 'expectedQty' in body) {
          return Promise.resolve(jsonResponse({ detail: 'stale_expected_qty' }, false, 422));
        }
        return Promise.resolve(jsonResponse({ stop: body.stop ?? null }));
      }
      return Promise.resolve(jsonResponse([{
        id: 'p1', recId: 'REC-FILL', symbol: 'AAPL', contract: 'AAPL|220|2026-09-16|C',
        direction: 'Bullish', entryPrice: 11, qty: 4, entryDate: '2026-08-01',
        stop: savedStop, targets: [], dteTotal: 30, createdAt: '2026-08-01T00:00:00Z',
        currentPrice: 18,
      }]));
    });
    render(<StoreDrawer />);

    const stop = screen.getByDisplayValue('12');
    fireEvent.change(stop, { target: { value: '9' } });
    fireEvent.blur(stop);
    typeQty('5');
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));

    await act(async () => {
      await jest.advanceTimersByTimeAsync(700);
      await Promise.resolve();
      await Promise.resolve();
    });

    const row = usePortfolioStore.getState().positions[0]!;
    expect(patchBodies().some((b) => b.stop === 9)).toBe(true);
    expect(patchBodies().some((b) => b.qty === 5 && b.addedFillPrice === 20 && b.expectedQty === 2)).toBe(true);
    expect(row.contracts).toBe(4);
    expect(row.entryPrice).toBe(11);
    expect(row.stop).toBe(9);
    expect(screen.getByLabelText(/Contracts/)).toHaveValue('4');
    expect(screen.getByText(/Average entry \$11\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/Average entry \$16\.00/)).not.toBeInTheDocument();
    jest.useRealTimers();
  });

  it('a cap breach displays the full fill and the warning, never a partial added fill', async () => {
    const breach = 'exposure_breach: single_trade_exposure_too_high; combined exposure 8000.00';
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue(jsonResponse({
        qty: 5, entryPrice: 16, adjustedQty: 2, exposureBreach: breach,
      }));
    render(<StoreDrawer />);
    typeQty('5');
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    const row = usePortfolioStore.getState().positions[0]!;
    expect(row.contracts).toBe(5);
    expect(row.entryPrice).toBe(16);
    expect(screen.getByLabelText(/Contracts/)).toHaveValue('5');
    expect(screen.getByText(rejectionMessage(breach))).toBeInTheDocument();
    expect(screen.queryByText(/Size reduced to 2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Quantity saved as 2/)).not.toBeInTheDocument();
  });

  it('an in-flight older response cannot replace a newer quantity draft', async () => {
    let resolvePatch: ((value: Response) => void) | null = null;
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn((_url: string, init?: { method?: string }) => {
      if (init?.method === 'PATCH') {
        return new Promise<Response>((resolve) => { resolvePatch = resolve; });
      }
      return Promise.resolve(jsonResponse([]));
    });
    render(<StoreDrawer />);
    const contracts = typeQty('5');
    fireEvent.change(screen.getByLabelText(/Added fill price/i), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm added fill/i }));
    await act(async () => { await Promise.resolve(); });
    expect(patchBodies()).toHaveLength(1);

    fireEvent.change(contracts, { target: { value: '8' } });
    await act(async () => {
      resolvePatch?.(jsonResponse({ qty: 5, entryPrice: 16 }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(contracts.value).toBe('8');
    expect(patchBodies()).toHaveLength(1);
    expect(usePortfolioStore.getState().positions[0]!.contracts).toBe(5);
    expect(usePortfolioStore.getState().positions[0]!.entryPrice).toBe(16);
  });
});
