import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import type { OptionsPipeline } from '@/lib/scanStore';
import { ScanFunnel } from '../index';

/**
 * The options funnel must not end on a number the ranking table never shows.
 * The reported bug: "Candidates 5" rendered above an empty Step-4 table,
 * because the backend snapshotted the count before the direction-conviction
 * gate stripped all five. The backend now counts after every filter; these
 * tests pin the display half — every symbol lost between one stage and the
 * next is attributed to a visible stage.
 */

function pipeline(over: Partial<OptionsPipeline> = {}): OptionsPipeline {
  return {
    scanned: 518,
    failed_data: 10,
    failed_pre_screen: 237,
    no_chain: 15,
    failed_score: 200,
    failed_contracts: 51,
    failed_direction: 0,
    failed_shortlist: 0,
    candidates: 5,
    ...over,
  };
}

describe('ScanFunnel — options mode', () => {
  it('names the direction-conviction gate as the stage that took the candidates', () => {
    render(<ScanFunnel mode="options" pipeline={pipeline({ failed_direction: 5, candidates: 0 })} />);

    expect(screen.getByText('Direction conviction')).toBeInTheDocument();
    expect(screen.getByText('−5 no conviction')).toBeInTheDocument();
  });

  it('shows the shortlist cap only when it actually trimmed something', () => {
    const { rerender } = render(<ScanFunnel mode="options" pipeline={pipeline()} />);
    expect(screen.queryByText('Shortlist cap')).not.toBeInTheDocument();

    rerender(<ScanFunnel mode="options" pipeline={pipeline({ failed_shortlist: 13, candidates: 5 })} />);
    expect(screen.getByText('Shortlist cap')).toBeInTheDocument();
    expect(screen.getByText('−13 over cap')).toBeInTheDocument();
  });

  it('tolerates a persisted result predating the new counters', () => {
    // failed_direction / failed_shortlist absent — an older stored blob.
    const legacy = {
      scanned: 100, failed_data: 5, failed_pre_screen: 40, no_chain: 5,
      failed_score: 30, failed_contracts: 15, candidates: 5,
    } as OptionsPipeline;

    expect(() => render(<ScanFunnel mode="options" pipeline={legacy} />)).not.toThrow();
    expect(screen.getByText('Direction conviction')).toBeInTheDocument();
  });
});
