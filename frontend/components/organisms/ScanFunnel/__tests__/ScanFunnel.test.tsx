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
    other_rejected: 0,
    failed_direction: 0,
    failed_shortlist: 0,
    candidates: 5,
    ...over,
  };
}

/**
 * The counts, not just the labels. Asserting only the "−N label" chips let the
 * arithmetic be wrong in any way that preserved them: flipping a minus to a
 * plus, or dropping a term from a running total, passed the whole file.
 */
describe('ScanFunnel — the funnel reconciles', () => {
  it('walks down to exactly the Candidates figure, options mode', () => {
    // 518 − 10 − 237 − 15 − (200+51) − 5 direction = 0.
    render(<ScanFunnel mode="options" pipeline={pipeline({ failed_direction: 5, candidates: 0 })} />);
    const shown = screen.getAllByText(/^\d+$/).map((el) => Number(el.textContent));

    expect(shown[0]).toBe(518);              // Universe
    expect(shown[shown.length - 1]).toBe(0); // Candidates
    // Each stage's count is strictly the previous minus what it dropped.
    expect(shown).toEqual([518, 508, 271, 256, 5, 0, 0]);
  });

  it('walks down to exactly the Candidates figure with a cap trim', () => {
    render(<ScanFunnel mode="options" pipeline={pipeline({
      failed_score: 200, failed_contracts: 51, failed_shortlist: 3, candidates: 2,
    })} />);
    const shown = screen.getAllByText(/^\d+$/).map((el) => Number(el.textContent));

    // ... 5 survive scoring, cap trims 3, 2 returned.
    expect(shown).toEqual([518, 508, 271, 256, 5, 2, 2]);
  });

  it('takes errors off the top rather than mid-chain, options mode', () => {
    // An errored symbol never produced an outcome at any gate, so no stage may
    // claim it survived. 7+10+237+15+200+44+5 = 518, a coherent funnel.
    render(<ScanFunnel mode="options" pipeline={pipeline({
      other_rejected: 7, failed_contracts: 44, candidates: 5,
    })} />);
    const shown = screen.getAllByText(/^\d+$/).map((el) => Number(el.textContent));

    // 518 −7 errored =511, −10 =501, −237 =264, −15 =249, −244 =5.
    expect(shown).toEqual([518, 501, 264, 249, 5, 5]);
  });

  it('walks down to exactly the Candidates figure, stock mode', () => {
    render(<ScanFunnel mode="stock" pipeline={{
      scanned: 100, failed_history: 10, failed_score: 30, failed_signal: 20,
      failed_backtest: 15, failed_regime: 8, failed_direction: 9,
      failed_shortlist: 3, other_rejected: 4, candidates: 1,
    }} />);
    const shown = screen.getAllByText(/^\d+$/).map((el) => Number(el.textContent));

    // 100 −4 errored =96, −10 hist =86, −30 score =56, −9 dir =47,
    // −8 regime =39, −20 signal =19, −15 backtest =4, −3 cap =1.
    expect(shown).toEqual([100, 86, 56, 47, 39, 19, 4, 1, 1]);
  });
});

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

  it('hides the gate for a persisted result predating the new counters', () => {
    // failed_direction / failed_shortlist absent — an older stored blob, whose
    // `candidates` was counted BEFORE the gate ran. Rendering the stage with a
    // zero would positively assert nothing was gated, which the blob cannot
    // support. Absent must read as "unknown", not as "none".
    const legacy = {
      scanned: 100, failed_data: 5, failed_pre_screen: 40, no_chain: 5,
      failed_score: 30, failed_contracts: 15, candidates: 5,
    } as OptionsPipeline;

    expect(() => render(<ScanFunnel mode="options" pipeline={legacy} />)).not.toThrow();
    expect(screen.queryByText('Direction conviction')).not.toBeInTheDocument();
    expect(screen.queryByText('Shortlist cap')).not.toBeInTheDocument();

    // Hiding the stages is not enough on its own: the chain still ends on 5
    // above "Candidates 5" only because this blob happens to reconcile. When it
    // does not, nothing in the arithmetic can say so — hence the explicit note.
    expect(screen.getByText(/Stored before per-gate counts were recorded/))
      .toBeInTheDocument();
  });

  it('hides the gate on a horizon where it never ran', () => {
    // The gate is defined for four direction/horizon pairs only. On Intraday no
    // gate runs at all, so a stage would imply a screen that did not happen.
    render(<ScanFunnel mode="options" pipeline={pipeline({ failed_direction: 0 })} />);
    expect(screen.queryByText('Direction conviction')).not.toBeInTheDocument();
  });

  it('surfaces exceptions and unclassified rejections instead of losing them', () => {
    render(<ScanFunnel mode="options" pipeline={pipeline({ other_rejected: 7 })} />);
    expect(screen.getByText('Unattributed / errored')).toBeInTheDocument();
    expect(screen.getByText('−7')).toBeInTheDocument();
  });
});

describe('ScanFunnel — stock mode', () => {
  const stock = {
    scanned: 100, failed_history: 10, failed_score: 30, failed_signal: 20,
    failed_backtest: 15, failed_regime: 8, failed_direction: 9,
    failed_shortlist: 3, other_rejected: 4, candidates: 1,
  };

  it('renders the drops the stock funnel used to swallow', () => {
    // failed_regime and other_rejected were counted by the backend and never
    // displayed — and stock-mode direction_conviction rejections landed inside
    // other_rejected, so the stock funnel had the same bug as the options one.
    render(<ScanFunnel mode="stock" pipeline={stock} />);

    expect(screen.getByText('Regime')).toBeInTheDocument();
    expect(screen.getByText('−8 headwind')).toBeInTheDocument();
    expect(screen.getByText('Direction')).toBeInTheDocument();
    expect(screen.getByText('−9 no conviction')).toBeInTheDocument();
    expect(screen.getByText('Unattributed / errored')).toBeInTheDocument();
    expect(screen.getByText('−4')).toBeInTheDocument();
    expect(screen.getByText('Shortlist cap')).toBeInTheDocument();
  });

  it('hides each conditional stage that dropped nothing', () => {
    render(<ScanFunnel mode="stock" pipeline={{
      ...stock, failed_regime: 0, failed_direction: 0, failed_shortlist: 0, other_rejected: 0,
    }} />);

    expect(screen.queryByText('Regime')).not.toBeInTheDocument();
    expect(screen.queryByText('Direction')).not.toBeInTheDocument();
    expect(screen.queryByText('Unattributed / errored')).not.toBeInTheDocument();
    expect(screen.queryByText('Shortlist cap')).not.toBeInTheDocument();
  });
});
