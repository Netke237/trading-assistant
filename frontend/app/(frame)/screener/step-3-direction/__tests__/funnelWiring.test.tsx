import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step3Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import type { ScanResult } from '@/lib/scanStore';

/** Live table counts stay gated while durable previous evidence remains separately selectable. */

jest.mock('@/lib/api', () => ({
  api: {
    getLatestScanReport: jest.fn().mockImplementation(()=>{
      const state=useScanStore.getState();const saved={category:'options',run_id:'saved-previous',generation:1,status:'complete',trigger:'manual',persistence:'saved',started_at:'t',ended_at:'t',inputs:{},diagnostics_available:true,diagnostics:{pipeline:previousRun.pipeline,rejected:previousRun.rejected,accepted_symbols:['AAA']},result:previousRun};
      return Promise.resolve({category:'options',latest_attempt:state.scanState==='COMPLETED'?saved:{...saved,run_id:'current-attempt',generation:2,status:state.scanState==='SCANNING'?'running':'failed',diagnostics_available:false,diagnostics:null,result:null},previous_report:state.scanState==='COMPLETED'?null:saved});
    }),
    getRegime: jest.fn().mockResolvedValue(null),
    getScanStatus: jest.fn().mockResolvedValue(null),
    getLastScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    getEventThresholds: jest.fn().mockResolvedValue(null),
  },
}));

// Not under test: it fires a scan and owns its own store writes.
jest.mock('@/components/organisms/RunScanButton', () => ({
  RunScanButton: () => null,
}));
jest.mock('@/components/organisms/SearchProfileBar', () => ({
  SearchProfileBar: () => null,
}));

const previousRun: ScanResult = {
  scan_id: 'REC-PREV', timestamp: '2026-09-15T21:33:00+00:00',
  candidates: [{ symbol: 'AAA' } as never],
  rejected: [{ symbol: 'R1', reason: 'no market data' }],
  pipeline: {
    scanned: 518, failed_data: 10, failed_pre_screen: 237, no_chain: 15,
    failed_score: 200, failed_contracts: 51, other_rejected: 0,
    failed_direction: 4, failed_shortlist: 0, candidates: 1,
  },
};

function seed(scanState: string) {
  useScanStore.setState({
    scanResult: previousRun,
    rejectedLog: [],          // RunScanButton clears this on scan start
    scanState: scanState as never,
    screenerMode: 'options',
  });
}

describe('Step 3 — durable evidence is separate from gated live table counts', () => {
  afterEach(() => {
    act(()=>useScanStore.setState({ scanResult: undefined, rejectedLog: [], scanState: 'IDLE' as never }));
  });

  it('renders the funnel for a completed scan', async () => {
    seed('COMPLETED');
    render(<Step3Page />);

    expect(await screen.findByText('Pipeline Root-Cause Inspector')).toBeInTheDocument();
  });

  it('hides the previous run\'s funnel while a new scan is running', async () => {
    // The regression this guards: the header fell back to passed + rejected
    // while the funnel still rendered the stale pipeline's "Universe 518".
    seed('SCANNING');
    render(<Step3Page />);

    expect(screen.queryByText('Pipeline Root-Cause Inspector')).not.toBeInTheDocument();
    expect(screen.queryByText('518')).not.toBeInTheDocument();
    await screen.findByText('Run current-attempt');
    fireEvent.click(screen.getByText('Previous saved report'));
    await screen.findByText('Run saved-previous');
    expect(screen.getByText('518 Scanned')).toBeInTheDocument();
  });

  it('hides the previous run\'s funnel after a failed scan', async () => {
    // FAILED is a persisted terminal state, so this survives a reload.
    seed('FAILED');
    render(<Step3Page />);

    expect(screen.queryByText('Pipeline Root-Cause Inspector')).not.toBeInTheDocument();
    expect(screen.queryByText('518')).not.toBeInTheDocument();
    await screen.findByText('Run current-attempt');
    fireEvent.click(screen.getByText('Previous saved report'));
    await screen.findByText('Run saved-previous');
    expect(screen.getByText('518 Scanned')).toBeInTheDocument();
  });
});
