import '@testing-library/jest-dom';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { PositionCardData } from '@/types/stockDomain';
jest.mock('@/lib/api',()=>({api:{getLatestScanReport:jest.fn().mockImplementation(()=>{const result=useScanStore.getState().stockScanResult;return Promise.resolve({category:'stocks',latest_attempt:{category:'stocks',run_id:'durable-stock',generation:1,status:'complete',trigger:'manual',started_at:'t',ended_at:'t',persistence:'saved',inputs:{},diagnostics_available:true,diagnostics:{pipeline:result?.pipeline,rejected:result?.rejected,accepted_symbols:result?.candidates.map(c=>c.symbol)},result},previous_report:null});})}}));
const mockPush = jest.fn();
const mockCard = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: (props: unknown) => { mockCard(props); return <div>Full shared card</div>; } }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => <div>Basket dialog</div> }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => <div>Durable send notes</div> }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: ({ symbol }: { symbol: string }) => <button>Watch {symbol}</button> }));
jest.mock('@/components/atoms/StatusBadge', () => ({ StatusBadge: ({ status, tooltip }: { status: string; tooltip: string }) => <span title={tooltip}>{status}</span> }));
function candidate(symbol: string, days: number, score: number): PositionCardData {
 return { symbol, company: symbol, price: 100, direction: 'Bullish', strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {} }, backtest: { n_trades: 20, win_rate: .46, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'historical summary · data' }, stock_score: score, stock_status: 'CAUTION', shares: 10, dollar_risk: 50, dollar_size: 1000, confidence: null, confidence_text: null, next_event_days: days, sector_rs_pct: 2 };
}
beforeEach(() => {
 mockPush.mockClear(); mockCard.mockClear();
 useScanParamsStore.setState({ eventFilter: 'include', btMinWinRate: .9 });
 useScanStore.setState({ stockScanResult: { scan_id: 'scan', timestamp: 't', pipeline:{scanned:4,failed_history:0,failed_score:0,failed_direction:0,failed_regime:0,failed_signal:0,failed_backtest:1,failed_shortlist:1,candidates:2}, candidates: [candidate('AAPL', 2, 80), candidate('MSFT', 30, 70)], rejected: [{ symbol: 'BAD', reason: 'backtest gate: insufficient trades' }, { symbol: 'CAP', reason: 'Shortlist cap: rank below limit' }] }, stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 20, bt_min_win_rate: .4 } as never, stockScanFeedback: { error: null, notice: 'After-scan save failed' }, selectedSymbol: null, stockBasket: [] });
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
it('filters events with an explicit hidden count without removing rejection explanations', async () => {
 render(<Page />);
 act(() => useScanParamsStore.setState({ eventFilter: 'avoid' }));
 expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
 expect(screen.getByText('1 of 2 hidden by the event filter.')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Filter Breakdown (2 Not Ranked)' }));
 const inspector = screen.getByRole('dialog', { name: 'Saved scan report' });
 await within(inspector).findByText('Pipeline Root-Cause Inspector');
 expect(within(inspector).getByText('2 Survivors')).toBeInTheDocument();
 fireEvent.change(within(inspector).getByRole('textbox'), { target: { value: 'BAD' } });
 expect(within(within(inspector).getByRole('region',{name:'Pipeline Root-Cause Inspector'})).getByRole('status')).toHaveTextContent('backtest gate: insufficient trades');
 fireEvent.change(within(inspector).getByRole('textbox'), { target: { value: 'AAPL' } });
 expect(within(inspector).getByText('SURVIVOR')).toBeInTheDocument();
 fireEvent.click(within(inspector).getByRole('button', { name: 'Close inspector' }));
 act(() => useScanParamsStore.setState({ eventFilter: 'only_pre_event' }));
 expect(screen.getByText('AAPL')).toBeInTheDocument();
 expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
 act(() => useScanStore.setState({ stockScanResult: { scan_id: 'empty', timestamp: 't', candidates: [], rejected: [] } }));
 expect(screen.getByText(/No candidates to display/)).toBeInTheDocument();
});

it('inspects shortlist trims separately and restores focus when dismissed', async () => {
 render(<Page />);
 const opener = screen.getByRole('button', { name: 'Filter Breakdown (2 Not Ranked)' });
 opener.focus();
 fireEvent.click(opener);
 const inspector = screen.getByRole('dialog', { name: 'Saved scan report' });
 await within(inspector).findByText('Pipeline Root-Cause Inspector');
 const search = within(inspector).getByRole('textbox');
 expect(within(inspector).getByRole('button',{name:'Close inspector'})).toHaveFocus();
 fireEvent.change(search, { target: { value: 'CAP' } });
 expect(within(inspector).getByText('TRIMMED')).toBeInTheDocument();
 expect(within(inspector).getByText('Shortlist cap: rank below limit')).toBeInTheDocument();
 fireEvent.keyDown(window, { key: 'Escape' });
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
 expect(opener).toHaveFocus();
});

it('shows the screenshot scan as a stock hierarchy even when no candidates survive', async () => {
 useScanStore.setState({ stockScanResult: {
   scan_id: 'zero', timestamp: 't', candidates: [],
   rejected: [{ symbol: 'DAY', reason: 'backtest gate: Only 1 trades — need 5' }],
   pipeline: { scanned: 518, failed_history: 16, failed_score: 195, failed_direction: 26, failed_direction_unmeasured: 0, direction_min_trend: 30, failed_regime: 0, failed_signal: 280, failed_backtest: 1, failed_shortlist: 0, other_rejected: 0, candidates: 0 },
 } });
 render(<Page />);
 expect(screen.queryByText('Pipeline log')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Filter Breakdown (518 Not Ranked)' }));
 const inspector = screen.getByRole('dialog', { name: 'Saved scan report' });
 await within(inspector).findByText('Pipeline Root-Cause Inspector');
 expect(within(inspector).getByText('518 Scanned')).toBeInTheDocument();
 expect(within(inspector).getByText('0 Survivors')).toBeInTheDocument();
 expect(within(inspector).queryByText(/Option chain/)).not.toBeInTheDocument();
 fireEvent.change(within(inspector).getByRole('textbox'), { target: { value: 'DAY' } });
 expect(within(inspector).getByText('backtest gate: Only 1 trades — need 5')).toBeInTheDocument();
 fireEvent.click(within(inspector).getByRole('button', { name: 'Plaintext Tree' }));
 expect(Array.from(inspector.querySelectorAll('pre')).find(p=>p.textContent?.includes('Left:'))).toHaveTextContent('Left: 502');
 expect(Array.from(inspector.querySelectorAll('pre')).find(p=>p.textContent?.includes('Left:'))).toHaveTextContent('Left: 307');
 expect(Array.from(inspector.querySelectorAll('pre')).find(p=>p.textContent?.includes('Left:'))).toHaveTextContent('Left: 281');
 expect(Array.from(inspector.querySelectorAll('pre')).find(p=>p.textContent?.includes('Left:'))).toHaveTextContent('Left: 1');
});

it('cycles health sorting descending, ascending, then original order', () => {
 const state = useScanStore.getState();
 useScanStore.setState({ stockScanResult: { ...state.stockScanResult!, candidates: state.stockScanResult!.candidates.map((c, i) => ({ ...c, fundamentals: { score: i ? 90 : 40 } as never })) } });
 render(<Page />);
 const symbols = () => screen.getAllByRole('button', { name: /^Watch / }).map(b => b.textContent);
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
 fireEvent.click(screen.getByRole('button', { name: 'Sort by fundamental health score' }));
 expect(symbols()).toEqual(['Watch MSFT', 'Watch AAPL']);
 fireEvent.click(screen.getByRole('button', { name: 'Sort by fundamental health score' }));
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
 fireEvent.click(screen.getByRole('button', { name: 'Sort by fundamental health score' }));
 expect(symbols()).toEqual(['Watch AAPL', 'Watch MSFT']);
});
