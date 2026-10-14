import React from 'react';
import { render, screen } from '@testing-library/react';
import Step3Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/screener/step-3-direction',
}));

jest.mock('@/lib/api', () => ({
  api: {
    getLatestScanReport: jest.fn().mockImplementation(() => { const result = useScanStore.getState().scanResult; return Promise.resolve({category:'options',latest_attempt:{category:'options',run_id:'durable-options',generation:1,status:'complete',trigger:'manual',persistence:'saved',started_at:'2026-10-13',ended_at:'2026-10-13',inputs:{},diagnostics_available:true,diagnostics:{pipeline:result?.pipeline,rejected:result?.rejected,accepted_symbols:result?.candidates.map(c=>c.symbol)},result},previous_report:null}); }),
    getScanResult: jest.fn().mockResolvedValue(null),
    getConfig: jest.fn().mockResolvedValue({}),
    getRegime: jest.fn().mockResolvedValue({ overall: 'PASS', omm: { state: 'BULL' } }),
  },
}));

describe('Step 3 Direction Page — PipelineInspector Integration', () => {
  beforeEach(() => {
    useScanStore.setState({
      screenerMode: 'options',
      scanState: 'COMPLETED',
      scanResult: {
        scan_id: 'test-scan-123',
        timestamp: '2026-10-02T12:00:00Z',
        candidates: [{ symbol: 'MSFT', score: 85, rank: 1 } as any],
        pipeline: {
          scanned: 500,
          failed_data: 20,
          failed_pre_screen: 250,
          no_chain: 150,
          failed_score: 50,
          failed_contracts: 29,
          candidates: 1,
        },
        rejected: [
          { symbol: 'PLUG', reason: 'price filter ($2.10 < $15.00 min)' },
          { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14)' },
        ],
      } as any,
    });
  });

  it('renders PipelineInspector inline when scan results are completed', async () => {
    render(<Step3Page />);

    expect(await screen.findByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
    expect(screen.getByText('500 Scanned')).toBeInTheDocument();
    expect(screen.getByText('−499 Not Ranked')).toBeInTheDocument();
    expect(screen.getByText('1 Survivor')).toBeInTheDocument();
    expect(api.getLatestScanReport).toHaveBeenCalledWith('options', expect.any(AbortSignal));
    expect(screen.getByText('Run durable-options')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...')).toBeInTheDocument();
  });
});
