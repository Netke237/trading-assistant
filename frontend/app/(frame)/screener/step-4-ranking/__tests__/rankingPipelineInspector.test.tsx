import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import Step4Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/screener/step-4-ranking',
}));

jest.mock('@/lib/api', () => ({
  api: {
    getLatestScanReport: jest.fn().mockImplementation(() => { const result = useScanStore.getState().scanResult; return Promise.resolve({category:'options',latest_attempt:{category:'options',run_id:'durable-options',generation:1,status:'complete',trigger:'manual',persistence:'saved',started_at:'2026-10-13',ended_at:'2026-10-13',inputs:{},diagnostics_available:true,diagnostics:{pipeline:result?.pipeline,rejected:result?.rejected,accepted_symbols:result?.candidates.map(c=>c.symbol)},result},previous_report:null}); }),
    getCandles: jest.fn().mockResolvedValue([]),
  },
}));

describe('Step 4 Ranking Page — PipelineInspector Drawer Integration', () => {
  it('opens inspector drawer when Filter Breakdown button is clicked with survivors', async () => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'test-scan-1',
        timestamp: '2026-10-02T12:00:00Z',
        candidates: [
          {
            symbol: 'MSFT',
            company: 'Microsoft Corporation',
            price: 450.00,
            direction: 'Bullish',
            score: 88,
            rank: 1,
            finalStatus: 'PASS',
            status: 'PASS',
            contractStatus: 'PASS',
            stockScore: 88,
            stockBreakdown: { trend: 80, pullback: 85, trigger: 90, event: 95, volatility: 70 },
          } as any,
        ],
        pipeline: {
          scanned: 500,
          failed_data: 10,
          failed_pre_screen: 200,
          no_chain: 100,
          failed_score: 50,
          failed_contracts: 139,
          candidates: 1,
        },
        rejected: [
          { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14)' },
        ],
      } as any,
    });

    render(<Step4Page />);

    const breakdownBtn = screen.getByText(/Filter Breakdown/i);
    expect(breakdownBtn).toBeInTheDocument();
    fireEvent.click(breakdownBtn);

    expect(await screen.findByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...')).toBeInTheDocument();
  });

  it('opens inspector drawer from empty state when 0 candidates matched', async () => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'test-scan-2',
        timestamp: '2026-10-02T12:00:00Z',
        candidates: [],
        pipeline: {
          scanned: 500,
          failed_data: 20,
          failed_pre_screen: 280,
          no_chain: 120,
          failed_score: 50,
          failed_contracts: 30,
          candidates: 0,
        },
        rejected: [
          { symbol: 'AAPL', reason: 'Pre-screen: score 30 rejected' },
        ],
      } as any,
    });

    render(<Step4Page />);

    expect(screen.getByText('No candidates matched the current scan criteria.')).toBeInTheDocument();
    const breakdownBtn = screen.getByText(/Filter Breakdown/i);
    fireEvent.click(breakdownBtn);

    expect(await screen.findByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByText('500 Scanned')).toBeInTheDocument();
  });
});
