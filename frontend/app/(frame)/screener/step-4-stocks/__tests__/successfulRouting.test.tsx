import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { runStockScanWithContinuation } from '@/lib/stockScan';
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@/lib/stockScan', () => ({ ...jest.requireActual('@/lib/stockScan'), runStockScanWithContinuation: jest.fn() }));
jest.mock('../HistoryPrefetchRow', () => ({ HistoryPrefetchRow: () => null }));
jest.mock('@/components/organisms/StrategyParamsPanel', () => ({ StrategyParamsPanel: () => null }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => null }));
beforeEach(() => {
 mockPush.mockClear();
 useScanStore.setState({ activeStrategy: 'pullback_ema', stockManualRunToken: 10, scanState: 'IDLE', stockScanResult: null, stockScanFeedback: { error: null, notice: null } });
});
it('routes a current successful zero-candidate scan to Backtest', async () => {
 (runStockScanWithContinuation as jest.Mock).mockResolvedValue({ kind: 'success', token: 10, result: { candidates: [], rejected: [] } });
 render(<Page />); fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' }));
 await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/screener/step-6-backtest'));
 expect(mockPush).toHaveBeenCalledTimes(1);
});
it.each(['failure','obsolete'])('does not route a %s outcome', async kind => {
 (runStockScanWithContinuation as jest.Mock).mockResolvedValue({ kind, token: 10, reason: 'original failure reason' });
 render(<Page />);
 await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' })));
 expect(mockPush).not.toHaveBeenCalled();
});
it('does not route a superseded success', async () => {
 let resolve!: (v: unknown) => void;
 (runStockScanWithContinuation as jest.Mock).mockReturnValue(new Promise(r => { resolve = r; }));
 render(<Page />); fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' }));
 await act(async () => { useScanStore.setState({ stockManualRunToken: 11 }); resolve({ kind: 'success', token: 10, result: { candidates: [] } }); });
 expect(mockPush).not.toHaveBeenCalled();
});
