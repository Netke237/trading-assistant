import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { PipelineInspector } from '../index';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';

const mockPipeline: OptionsPipeline = {
  scanned: 518,
  failed_data: 11,
  failed_pre_screen: 277,
  no_chain: 138,
  failed_score: 50,
  failed_contracts: 41,
  candidates: 1,
};

const mockRejected: RejectedEntry[] = [
  { symbol: 'PLUG', reason: 'price filter ($2.10 < $15.00 min)' },
  { symbol: 'AEP', reason: 'Pre-screen: score 29 rejected', breakdown: { trend: 30, pullback: 10, trigger: 10, event: 55, vol: 50 } },
  { symbol: 'ABT', reason: 'no option chain' },
  { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(15), volume_too_low(10)' },
];

describe('PipelineInspector Component', () => {
  it('renders in drawer mode with backdrop, close button, and step 3 adjustment link', () => {
    const handleClose = jest.fn();
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={true}
        onClose={handleClose}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Pipeline Root-Cause Inspector' })).toBeInTheDocument();
    expect(screen.getByText('Review in Step 3 →')).toBeInTheDocument();

    const closeBtn = screen.getByLabelText('Close inspector');
    expect(closeBtn).toBeInTheDocument();
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape key in drawer mode', () => {
    const handleClose = jest.fn();
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={true}
        onClose={handleClose}
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('renders in inline mode without backdrop, close button, or step 3 adjustment link', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    expect(screen.queryByLabelText('Close inspector')).not.toBeInTheDocument();
    expect(screen.queryByText('Review in Step 3 →')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('518 Scanned')).toBeInTheDocument();
  });

  it('performs live symbol lookup and shows diagnosis', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    const input = screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...');
    fireEvent.change(input, { target: { value: 'NVDA' } });

    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText('REJECTED')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Stage: Score Gate & Contract Rules');
    expect(screen.getByText(/Spread Too Wide, Low Liquidity/)).toBeInTheDocument();
  });

  it('says a symbol was not part of the scan instead of showing nothing', () => {
    render(<PipelineInspector pipeline={mockPipeline} rejected={mockRejected} survivors={['MSFT']} isDrawer={false} />);
    fireEvent.change(screen.getByPlaceholderText('Search symbol (e.g. NVDA, AAPL)...'), { target: { value: 'zzzz' } });
    expect(screen.getByText('ZZZZ was not part of this scan.')).toBeInTheDocument();
  });

  it('shows no bottleneck card when nothing was dropped', () => {
    render(
      <PipelineInspector
        pipeline={{ scanned: 1, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 1 }}
        rejected={[]}
        survivors={['MSFT']}
        isDrawer={false}
      />
    );
    expect(screen.queryByText(/Primary bottleneck/i)).not.toBeInTheDocument();
  });

  it('shows a dash, not an estimate, when a stage has no per-symbol reasons', () => {
    render(<PipelineInspector pipeline={mockPipeline} rejected={[]} survivors={['MSFT']} isDrawer={false} />);
    // pre-screen (277) is the bottleneck and opens by default
    expect(screen.getByText(/Per-rule breakdown unavailable/)).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('identifies primary bottleneck stage', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    expect(screen.getByText(/Primary bottleneck: Pre-Screen Setup Score/i)).toBeInTheDocument();
  });

  it('toggles plaintext ASCII tree view and copies to clipboard', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: jest.fn().mockImplementation(() => Promise.resolve()),
      },
    });

    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    const toggleBtn = screen.getByText('Plaintext Tree');
    fireEvent.click(toggleBtn);
    expect(screen.getByText(/Universe \(518\)/i)).toBeInTheDocument();

    const copyBtn = screen.getByTitle('Copy formatted ASCII tree');
    await act(async () => { fireEvent.click(copyBtn); });
    expect(navigator.clipboard.writeText).toHaveBeenCalled();
    expect(copyBtn).toHaveTextContent('Copied');
  });

  it('reports a failed copy instead of claiming success', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: jest.fn().mockImplementation(() => Promise.reject(new Error('denied'))) },
    });
    render(<PipelineInspector pipeline={mockPipeline} rejected={mockRejected} survivors={['MSFT']} isDrawer={false} />);
    const copyBtn = screen.getByTitle('Copy formatted ASCII tree');
    await act(async () => { fireEvent.click(copyBtn); });
    expect(copyBtn).toHaveTextContent('Copy failed');
  });

  it('expands ticker chips and searches ticker on chip click', () => {
    render(
      <PipelineInspector
        pipeline={mockPipeline}
        rejected={mockRejected}
        survivors={['MSFT']}
        isOpen={true}
        isDrawer={false}
      />
    );

    fireEvent.click(screen.getByText('1. Data & Universe Filters'));
    const viewChipsBtns = screen.getAllByText(/View 1 Tickers/i);
    fireEvent.click(viewChipsBtns[0]);

    const chip = screen.getByTitle('Click to inspect PLUG');
    expect(chip).toBeInTheDocument();
    fireEvent.click(chip);

    // After clicking chip, PLUG should be searched and diagnosed in the card
    expect(screen.getAllByText('PLUG').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/Data & Universe Filters/i).length).toBeGreaterThanOrEqual(2);
  });
});
