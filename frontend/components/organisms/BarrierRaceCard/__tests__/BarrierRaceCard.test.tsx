import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import BarrierRaceCard from '@/components/organisms/BarrierRaceCard';
import type { BarrierRace, BarrierRaceOutcome } from '@/types/domain';

// Genuine `estimate_first_passage` output for the reference contract (185/190C,
// 30 DTE, $5.20 premium, stop $176, 60% premium stop, seed 42) — not a
// hand-written approximation. The old fixture carried an `edgePerContract` of
// -193.28 when every edge is a whole number of dollars by construction, and
// four shares that were all exact two-decimal values, which are exactly the
// ones on which a rounding disagreement cannot show up.
function outcome(over: Partial<BarrierRaceOutcome> = {}): BarrierRaceOutcome {
  return {
    targetPct: 0.20,
    targetOptionPrice: 6.24,
    pTargetFirst: 0.2685,
    pStockStopFirst: 0.0,
    pPremiumStopFirst: 0.6865,
    pNeither: 0.045,
    daysTarget: 7,
    daysStockStop: null,
    daysPremiumStop: 20,
    daysAnyPathReachedStop: 26,
    weightTargetFirst: 0.27,
    weightStockStopFirst: 0.0,
    weightPremiumStopFirst: 0.69,
    weightNeither: 0.04,
    terminalMean: 3.64,
    rewardDollar: 1.04,
    repriceDaysStockStop: 26,
    stopRepricedValue: 0.03,
    riskStockStop: 5.17,
    riskPremiumStop: 3.12,
    rrStockStop: 0.20116054158607352,
    rrPremiumStop: 0.33333333333333337,
    edgePerContract: -193.0,
    ...over,
  };
}

const RACE: BarrierRace = {
  outcomes: [
    outcome(),
    outcome({
      targetPct: 0.35, targetOptionPrice: 7.02, pTargetFirst: 0.138, pPremiumStopFirst: 0.785,
      pNeither: 0.077, daysTarget: 12, daysPremiumStop: 21,
      weightTargetFirst: 0.14, weightPremiumStopFirst: 0.78, weightNeither: 0.08,
      terminalMean: 3.98, rewardDollar: 1.82, rrStockStop: 0.35203094777562866,
      rrPremiumStop: 0.5833333333333334, edgePerContract: -228.0,
    }),
    outcome({
      targetPct: 0.50, targetOptionPrice: 7.80, pTargetFirst: 0.0825, pPremiumStopFirst: 0.81,
      pNeither: 0.1075, daysTarget: 16, daysPremiumStop: 21,
      weightTargetFirst: 0.08, weightPremiumStopFirst: 0.81, weightNeither: 0.11,
      terminalMean: 4.20, rewardDollar: 2.60, rrStockStop: 0.5029013539651838,
      rrPremiumStop: 0.8333333333333334, edgePerContract: -243.0,
    }),
  ],
  premiumStopPrice: 2.08,
  premiumStopPct: 0.60,
  stockStopPrice: 176.00,
  // The premium every printed chain subtracts, quantized to cents by the
  // backend. The card must print this rather than re-round its own copy.
  premiumUsed: 5.20,
  ivSolved: true,
  nPaths: 2000,
};

// The card's editable "Premium stop" field, in DOLLARS. 60% of the $5.20
// premium, i.e. the value that genuinely did set the barrier.
const PREMIUM_STOP_FIELD = 3.12;

function renderCard(props: Partial<React.ComponentProps<typeof BarrierRaceCard>> = {}) {
  return render(
    <BarrierRaceCard
      race={RACE}
      premiumStopFromField
      premiumStopField={PREMIUM_STOP_FIELD}
      isFresh
      {...props}
    />,
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
    // Raw shares, not the allocated weights: the bar is continuous and these
    // sum to 100% exactly on their own.
    expect(targetSegments[0]).toHaveStyle({ width: '26.8500%' });
    expect(targetSegments[1]).toHaveStyle({ width: '13.8000%' });
    expect(targetSegments[2]).toHaveStyle({ width: '8.2500%' });
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
    expect(label).toContain('Premium stop first 69%');
    expect(label).toContain('Neither 4%');

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
      screen.getAllByText(
        '$5.20 premium - $0.03 at the stop '
        + '(repriced at 26d — the median day any path reaches the stop) = $5.17',
      ),
    ).toHaveLength(3);
    expect(screen.getByText('$1.04 / $5.17 = 0.20x')).toBeInTheDocument();
    expect(screen.getByText('$1.82 / $5.17 = 0.35x')).toBeInTheDocument();
    expect(screen.getByText('$2.60 / $5.17 = 0.50x')).toBeInTheDocument();
  });

  it('prints the edge chain with all four signed contributions', () => {
    renderCard();
    expect(
      screen.getByText(/0\.27 x \$1\.04 - 0\.00 x \$5\.17 - 0\.69 x \$3\.12 \+ 0\.04 x -\$1\.56/),
    ).toBeInTheDocument();
  });

  it('marks the premium-stop ratio as a constant, not a measurement', () => {
    renderCard();
    expect(
      screen.getByText(/0\.33x, which is your target % over your stop %/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Only the first ratio is a measurement/)).toBeInTheDocument();
  });

  it('does not claim the premium stop came from the field when it did not', () => {
    // The field holds a DOLLAR amount fixed at scan time. A contract that has
    // since fallen below it makes the fraction >= 1, so nothing is sent and the
    // backend applies its own default — while the card stated unconditionally
    // that the level came "from the editable field above".
    renderCard({ premiumStopFromField: false, premiumStopField: 9.99 });
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
    render(<BarrierRaceCard race={null} premiumStopFromField premiumStopField={PREMIUM_STOP_FIELD} isFresh />);
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
      <BarrierRaceCard race={RACE} premiumStopFromField premiumStopField={PREMIUM_STOP_FIELD} isFresh={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('still renders the refusal copy, which depends on no live barrier', () => {
    render(<BarrierRaceCard race={null} premiumStopFromField premiumStopField={PREMIUM_STOP_FIELD} isFresh={false} />);
    expect(screen.getByText(/Not simulated — contract expires today/)).toBeInTheDocument();
  });
});

describe('when nothing has been run yet', () => {
  it('renders nothing', () => {
    const { container } = render(
      <BarrierRaceCard race={undefined} premiumStopFromField premiumStopField={PREMIUM_STOP_FIELD} isFresh />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// -- Round 2: what the card claims vs what it renders -------------------------

describe('the numbers the card promises', () => {
  it('renders four whole percentages that sum to 100 on a REAL share set', () => {
    // The default fixture (0.27 / 0.00 / 0.68 / 0.05) is four values that are
    // already exact whole percents, so the "sum to 100%" assertion above cannot
    // fail — it asserted a property it did not test. This is the reference
    // contract's actual T35% row: rounded independently it renders
    // 14 + 0 + 79 + 8 = 101%, printed directly under "Every row sums to 100%"
    // and beside a bar that does sum to 100 because it uses the raw values.
    render(
      <BarrierRaceCard
        race={{
          ...RACE,
          outcomes: [outcome({
            pTargetFirst: 0.138, pStockStopFirst: 0.0, pPremiumStopFirst: 0.785, pNeither: 0.077,
          })],
        }}
        premiumStopFromField
        premiumStopField={PREMIUM_STOP_FIELD}
        isFresh
      />,
    );
    const label = screen.getAllByRole('img')[0].getAttribute('aria-label') ?? '';
    // Skip the leading "20% target:" and read the four share percentages.
    const spoken = [...label.matchAll(/(\d+)%/g)].slice(1).map((m) => Number(m[1]));
    expect(spoken).toHaveLength(4);
    expect(spoken.reduce((a, b) => a + b, 0)).toBe(100);
  });

  it('keeps the stock-stop probability on screen when only the PREMIUM stop moved', () => {
    // The standalone invalidation probability moved onto this card (spec 3.4),
    // and the barriersChanged short-circuit sat above it — so editing the
    // premium stop deleted a number the premium stop cannot affect.
    renderCard({ barriersChanged: true, invalidation: { probability: 0.30, expectedDays: 4 } });
    expect(screen.getByText(/Barriers changed/)).toBeInTheDocument();
    expect(screen.getByText(/30% of paths touch the stock stop/)).toBeInTheDocument();
  });

  it('caveats every number when the contract IV could not be solved', () => {
    renderCard({ race: { ...RACE, ivSolved: false } });
    expect(
      screen.getByText(/implied volatility could not be backed out of its quote/),
    ).toBeInTheDocument();
  });

  it('warns when the bolded R:R describes an outcome the simulation never reached', () => {
    // Every row of the default fixture has pStockStopFirst == 0, which is the
    // reference contract's real behaviour: the premium stop fires first on
    // every losing path, so the stock-stop R:R contributes nothing to the edge.
    renderCard();
    expect(
      screen.getByText(/describes an outcome the simulation never reached/),
    ).toBeInTheDocument();
  });

  it('renders the conditional medians to both stops, not only to the target', () => {
    // daysStockStop and daysPremiumStop were computed, mapped onto the wire and
    // typed, and then never rendered.
    renderCard();
    // Real conditional medians: 20/21/21 to the premium stop, 7/12/16 to the
    // target, and "—" to the stock stop, which no path reached first.
    expect(screen.getAllByText('~21d').length).toBe(2);
    expect(screen.getByText('~20d')).toBeInTheDocument();
    expect(screen.getByText('~7d')).toBeInTheDocument();
    expect(screen.getByText('~12d')).toBeInTheDocument();
    expect(screen.getByText('~16d')).toBeInTheDocument();
  });

  it('prints an edge chain whose terms sum to the total it prints', () => {
    renderCard();
    expect(
      screen.getAllByText(
        // Testing Library normalises runs of whitespace, so the chain's double
        // spaces around the arrow are matched loosely. The point of the
        // assertion is the TOTAL: 0.27x1.04 - 0 - 0.68x3.12 + 0.05x-1.56 is
        // -1.9188, and the card must print that, not the -193.28 this fixture
        // used to carry while the assertion only checked the four terms.
        /0\.27 x \$1\.04 - 0\.00 x \$5\.17 - 0\.69 x \$3\.12 \+ 0\.04 x -\$1\.56 = -\$1\.93\s+->\s+-\$193\.00 per contract/,
      ).length,
    ).toBeGreaterThan(0);
  });
});
