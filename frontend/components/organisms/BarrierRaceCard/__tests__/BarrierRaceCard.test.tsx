import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import BarrierRaceCard from '@/components/organisms/BarrierRaceCard';
import type { BarrierRace, BarrierRaceOutcome } from '@/types/domain';

function outcome(over: Partial<BarrierRaceOutcome> = {}): BarrierRaceOutcome {
  return {
    targetPct: 0.20,
    targetOptionPrice: 6.24,
    pTargetFirst: 0.27,
    pStockStopFirst: 0.00,
    pPremiumStopFirst: 0.68,
    pNeither: 0.05,
    daysTarget: 7,
    daysStockStop: null,
    daysPremiumStop: 20,
    terminalMean: 3.64,
    rewardDollar: 1.04,
    repriceDaysStockStop: 7,
    stopRepricedValue: 0.18,
    riskStockStop: 5.02,
    riskPremiumStop: 3.12,
    rrStockStop: 0.2072,
    rrPremiumStop: 0.3333,
    edgePerContract: -193.28,
    ...over,
  };
}

const RACE: BarrierRace = {
  outcomes: [
    outcome(),
    outcome({ targetPct: 0.35, targetOptionPrice: 7.02, pTargetFirst: 0.14, pPremiumStopFirst: 0.78, pNeither: 0.08, rewardDollar: 1.82, rrStockStop: 0.3625, rrPremiumStop: 0.5833 }),
    outcome({ targetPct: 0.50, targetOptionPrice: 7.80, pTargetFirst: 0.08, pPremiumStopFirst: 0.81, pNeither: 0.11, rewardDollar: 2.60, rrStockStop: 0.5178, rrPremiumStop: 0.8333 }),
  ],
  premiumStopPrice: 2.08,
  premiumStopPct: 0.60,
  stockStopPrice: 176.00,
  // The premium every printed chain subtracts, quantized to cents by the
  // backend. The card must print this rather than re-round its own copy.
  premiumUsed: 5.20,
  nPaths: 2000,
};

// The card's editable "Premium stop" field, in DOLLARS. 60% of the $5.20
// premium, i.e. the value that genuinely did set the barrier.
const PREMIUM_STOP_FIELD = 3.12;

function renderCard(props: Partial<React.ComponentProps<typeof BarrierRaceCard>> = {}) {
  return render(
    <BarrierRaceCard race={RACE} premiumStopField={PREMIUM_STOP_FIELD} isFresh {...props} />,
  );
}

// -- 10. The bars and the shares ---------------------------------------------

describe('the race outcome', () => {
  it('renders one bar per target, at the returned widths', () => {
    renderCard();
    const targetSegments = screen.getAllByTestId('segment-Target first');
    expect(targetSegments).toHaveLength(3);
    // Exact strings: a binary-float tail (0.14 * 100 = 14.000000000000002)
    // would otherwise land in the style attribute verbatim.
    expect(targetSegments[0]).toHaveStyle({ width: '27.0000%' });
    expect(targetSegments[1]).toHaveStyle({ width: '14.0000%' });
    expect(targetSegments[2]).toHaveStyle({ width: '8.0000%' });
  });

  it('omits a zero-width segment rather than rendering an invisible one', () => {
    renderCard();
    // pStockStopFirst is 0 on all three rows of this fixture — the reference
    // contract's actual behaviour, since the premium stop is far tighter. The
    // other three segments still render, so this is not an empty-DOM pass.
    expect(screen.queryAllByTestId('segment-Stock stop first')).toHaveLength(0);
    expect(screen.getAllByTestId('segment-Premium stop first')).toHaveLength(3);
  });

  it('labels all four shares and they sum to 100%', () => {
    renderCard();
    const bar = screen.getAllByRole('img')[0];
    const label = bar.getAttribute('aria-label') ?? '';
    expect(label).toContain('Target first 27%');
    expect(label).toContain('Stock stop first 0%');
    expect(label).toContain('Premium stop first 68%');
    expect(label).toContain('Neither 5%');

    const shares = [...label.matchAll(/(\d+)%/g)]
      .map((m) => Number(m[1]))
      .slice(1);   // the first match is the target's own "20%"
    expect(shares.reduce((a, b) => a + b, 0)).toBe(100);
  });

  it('says why the rows sum to 100% and the Monte Carlo card above does not', () => {
    renderCard();
    expect(screen.getByText(/counted once, for whichever barrier it reached first/)).toBeInTheDocument();
    expect(screen.getByText(/can sum past 100%/)).toBeInTheDocument();
  });

  it('says the medians are conditional, not over all paths', () => {
    renderCard();
    expect(screen.getByText(/median over the paths that got there first, not over all paths/)).toBeInTheDocument();
  });
});

// -- The barriers, each with its unit ----------------------------------------

describe('the three barriers', () => {
  it('never shows a bare number for a level', () => {
    renderCard();
    expect(screen.getByText('$176.00 stock')).toBeInTheDocument();
    expect(screen.getByText('$2.08 option')).toBeInTheDocument();
  });
});

// -- The printed arithmetic ---------------------------------------------------

describe('the printed arithmetic', () => {
  it('prints the risk chain, and it adds up', () => {
    renderCard();
    // One per target row, and identical across all three by construction: the
    // stop leg depends on the stop, not on which target you are aiming at.
    // Only the reward leg differs per row.
    expect(
      screen.getAllByText('$5.20 premium - $0.18 at the stop (repriced at 7d) = $5.02'),
    ).toHaveLength(3);
    expect(screen.getByText('$1.04 / $5.02 = 0.21x')).toBeInTheDocument();
    expect(screen.getByText('$1.82 / $5.02 = 0.36x')).toBeInTheDocument();
    expect(screen.getByText('$2.60 / $5.02 = 0.52x')).toBeInTheDocument();
  });

  it('prints the edge chain with all four signed contributions', () => {
    renderCard();
    expect(
      screen.getByText(/0\.27 x \$1\.04 - 0\.00 x \$5\.02 - 0\.68 x \$3\.12 \+ 0\.05 x -\$1\.56/),
    ).toBeInTheDocument();
  });

  it('marks the premium-stop ratio as a constant, not a measurement', () => {
    renderCard();
    expect(
      screen.getByText(/20% \/ 60% = 0\.33x on every contract/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Only the first ratio is a measurement/)).toBeInTheDocument();
  });

  it('does not claim the premium stop came from the field when it did not', () => {
    // The field holds a DOLLAR amount fixed at scan time. A contract that has
    // since fallen below it makes the fraction >= 1, so nothing is sent and the
    // backend applies its own default — while the card stated unconditionally
    // that the level came "from the editable field above".
    renderCard({ premiumStopField: 9.99 });
    expect(screen.getByText(/the default/)).toBeInTheDocument();
    expect(screen.queryByText(/from the editable field above/)).not.toBeInTheDocument();
  });

  it('shows both stops as armed, since the armed stop is whichever fires first', () => {
    renderCard();
    expect(screen.getAllByText(/whichever fires first/)).toHaveLength(2);
  });

  it('carries the IV-frozen caveat verbatim', () => {
    renderCard();
    expect(
      screen.getByText(/a real fear bid would leave more premium than shown/),
    ).toBeInTheDocument();
  });
});

// -- 11. The refusal branch ---------------------------------------------------

describe('when the simulation was refused', () => {
  it('renders the "not simulated" copy, not an empty card and not four zeroes', () => {
    render(<BarrierRaceCard race={null} premiumStopField={PREMIUM_STOP_FIELD} isFresh />);
    expect(screen.getByText(/Not simulated — contract expires today/)).toBeInTheDocument();
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });
});

// -- 12. A moved barrier clears the race --------------------------------------

describe('when a barrier moved after the race was computed', () => {
  it('clears the bars and asks for a re-run rather than showing stale ones', () => {
    renderCard({ barriersChanged: true });
    expect(screen.getByText(/Barriers changed — re-run the estimate/)).toBeInTheDocument();
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect(screen.queryByText('$5.20 premium - $0.18 at the stop (repriced at 7d) = $5.02'))
      .not.toBeInTheDocument();
  });
});

// -- 13. A restored, not-fresh-this-mount estimate ----------------------------

describe('when the estimate was restored from cache rather than fetched this mount', () => {
  it('renders nothing at all', () => {
    // Its two barrier inputs are live and the estimate can be arbitrarily old.
    // Pairing them is the mixed-vintage hazard structuralRR's freshness
    // machinery exists to prevent.
    const { container } = render(
      <BarrierRaceCard race={RACE} premiumStopField={PREMIUM_STOP_FIELD} isFresh={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('still renders the refusal copy, which depends on no live barrier', () => {
    render(<BarrierRaceCard race={null} premiumStopField={PREMIUM_STOP_FIELD} isFresh={false} />);
    expect(screen.getByText(/Not simulated — contract expires today/)).toBeInTheDocument();
  });
});

describe('when nothing has been run yet', () => {
  it('renders nothing', () => {
    const { container } = render(
      <BarrierRaceCard race={undefined} premiumStopField={PREMIUM_STOP_FIELD} isFresh />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
