import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { PositionCardData } from '@/types/stockDomain';
const mockPush = jest.fn();
const mockCard = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: (props: unknown) => { mockCard(props); return <div>Full shared card</div>; } }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => <div>Basket dialog</div> }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => <div>Durable send notes</div> }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => <div>Original funnel</div> }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: ({ symbol }: { symbol: string }) => <button>Watch {symbol}</button> }));
jest.mock('@/components/atoms/StatusBadge', () => ({ StatusBadge: ({ status, tooltip }: { status: string; tooltip: string }) => <span title={tooltip}>{status}</span> }));
function candidate(symbol: string, days: number, score: number): PositionCardData {
 return { symbol, company: symbol, price: 100, direction: 'Bullish', strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {} }, backtest: { n_trades: 20, win_rate: .46, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'historical summary · data' }, stock_score: score, stock_status: 'CAUTION', shares: 10, dollar_risk: 50, dollar_size: 1000, confidence: null, confidence_text: null, next_event_days: days, sector_rs_pct: 2 };
}
beforeEach(() => {
 mockPush.mockClear(); mockCard.mockClear();
 useScanParamsStore.setState({ eventFilter: 'include', btMinWinRate: .9 });
 useScanStore.setState({ stockScanResult: { scan_id: 'scan', timestamp: 't', candidates: [candidate('AAPL', 2, 80), candidate('MSFT', 30, 70)], rejected: [{ symbol: 'BAD', reason: 'backtest gate: insufficient trades' }, { symbol: 'CAP', reason: 'Shortlist cap: rank below limit' }] }, stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 20, bt_min_win_rate: .4 } as never, stockScanFeedback: { error: null, notice: 'After-scan save failed' }, selectedSymbol: null, stockBasket: [] });
});
it('keeps one union table and separates expand/watch controls from Position navigation', () => {
 render(<Page />);
 for (const label of ['SUMMARY','SCORE','STATUS','Δ','WIN %','TRADES','RETURN','MAX DD','VS SPX','EVENT','CONF','GATE']) expect(screen.getByText(label)).toBeInTheDocument();
 expect(screen.getByText('After-scan save failed')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Watch AAPL' }));
 expect(mockPush).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' }));
 expect(screen.getByText('Full shared card')).toBeInTheDocument();
 expect(mockCard).toHaveBeenLastCalledWith(expect.objectContaining({ strategyKey: 'pullback_ema' }));
 expect(mockPush).not.toHaveBeenCalled();
 fireEvent.click(screen.getAllByRole('button', { name: 'Open Position' })[1]);
 expect(useScanStore.getState().selectedSymbol).toBe('MSFT');
 expect(mockPush).toHaveBeenCalledWith('/screener/step-7-position-card');
});
it('uses paired scan thresholds and reports unavailable provenance for legacy evidence', () => {
 render(<Page />);
 expect(screen.getAllByTitle(/≥40%/).length).toBeGreaterThan(0);
 act(() => useScanStore.setState({ stockScanRequest: null }));
 expect(screen.getAllByTitle('Threshold provenance unavailable for this scan').length).toBeGreaterThan(0);
});
it('filters events with an explicit hidden count without removing rejection explanations', () => {
 render(<Page />);
 act(() => useScanParamsStore.setState({ eventFilter: 'avoid' }));
 expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
 expect(screen.getByText('1 of 2 hidden by the event filter.')).toBeInTheDocument();
 expect(screen.getByText('BAD: backtest gate: insufficient trades')).toBeInTheDocument();
 act(() => useScanParamsStore.setState({ eventFilter: 'only_pre_event' }));
 expect(screen.getByText('AAPL')).toBeInTheDocument();
 expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
 act(() => useScanStore.setState({ stockScanResult: { scan_id: 'empty', timestamp: 't', candidates: [], rejected: [] } }));
 expect(screen.getByText(/No candidates to display/)).toBeInTheDocument();
});

it('cycles health sorting descending, ascending, then original order', () => {
 const state = useScanStore.getState();
 useScanStore.setState({ stockScanResult: { ...state.stockScanResult!, candidates: state.stockScanResult!.candidates.map((c, i) => ({ ...c, fundamentals: { score: i ? 90 : 40 } as never })) } });
 render(<Page />);
 const symbols = () => screen.getAllByRole('button', { name: /^Watch / }).map(b => b.textContent);
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
 fireEvent.click(screen.getByRole('button', { name: /HEALTH/ }));
 expect(symbols()).toEqual(['Watch MSFT', 'Watch AAPL']);
 fireEvent.click(screen.getByRole('button', { name: /HEALTH/ }));
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
 fireEvent.click(screen.getByRole('button', { name: /HEALTH/ }));
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
});
