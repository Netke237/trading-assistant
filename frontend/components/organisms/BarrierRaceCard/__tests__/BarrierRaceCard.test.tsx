import '@testing-library/jest-dom';
import { render, screen, within, fireEvent } from '@testing-library/react';
import BarrierRaceCard from '@/components/organisms/BarrierRaceCard';
import type { BarrierRace, BarrierRaceOutcome } from '@/types/domain';
import { formatRaceRR, formatRaceEdge } from '@/lib/barrierRace';

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
      screen.getByText(
        /0\.27 x \$1\.04 - 0\.00 x \$5\.17 - 0\.69 x \$3\.12 \+ 0\.04 x \(\$3\.64 at expiry - \$5\.20\)/,
      ),
    ).toBeInTheDocument();
  });

  it('marks the premium-stop ratio as a constant, not a measurement', () => {
    renderCard();
    expect(
      screen.getByText(/0\.33x, the same on every contract/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Only the first ratio is a measurement/)).toBeInTheDocument();
  });

  it('says the premium-stop percentage is a loss, not the level beside it', () => {
    // The barriers table puts the level ($2.08 option) next to this note.
    // "~60% of premium" beside it cannot be reconciled — 60% of the $5.20
    // premium is $3.12, and $2.08 is the complement.
    renderCard();
    expect(screen.getByText(/stops out after losing ~60% of premium/)).toBeInTheDocument();
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
            // BOTH the raw shares and the weights the backend allocated from
            // them. Overriding only the shares left the assertion below reading
            // the base fixture's weights, so the test could not fail on the
            // case it was written for.
            pTargetFirst: 0.138, pStockStopFirst: 0.0, pPremiumStopFirst: 0.785, pNeither: 0.077,
            weightTargetFirst: 0.14, weightStockStopFirst: 0.0,
            weightPremiumStopFirst: 0.78, weightNeither: 0.08,
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
    // And the fixture is genuinely capable of failing: rounding those shares
    // one by one gives 14 + 0 + 79 + 8 = 101.
    const naive = [0.138, 0.0, 0.785, 0.077].map((v) => Math.round(v * 100));
    expect(naive.reduce((a, b) => a + b, 0)).toBe(101);
  });

  it('renders nothing at all for a stale race, even when its barriers moved', () => {
    // The freshness check must outrank the barriers-changed branch. The other
    // way round, the frame after a contract switch — isFresh already false,
    // barriersChanged computed from the PREVIOUS contract's snapshot against
    // the new contract's stop — painted "Barriers changed — re-run the
    // estimate" plus the previous contract's invalidation probability under the
    // new contract's header.
    const { container } = renderCard({
      isFresh: false,
      barriersChanged: true,
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the stock-stop probability on screen, naming the stop it belongs to, when the STOCK stop moved', () => {
    // Spec 3.4 moves the invalidation row onto this card, "not a deletion".
    // Suppressing it whenever the stock stop moved deleted it: the three
    // per-target probabilities that can sum past 100% stay on screen above with
    // nothing left to explain why. It is printed with the level it was measured
    // against, which is the fact that makes it stale.
    renderCard({
      barriersChanged: true,
      stockStopMoved: true,
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    expect(screen.getByText(/30% of paths touched the stock stop/)).toBeInTheDocument();
    expect(screen.getByText(/\$176\.00 stop this estimate used/)).toBeInTheDocument();
    // ...and it does NOT claim the premium stop is what changed.
    expect(screen.queryByText(/unaffected by the premium stop/)).not.toBeInTheDocument();
  });

  it('prints a half-integer median the same way the risk chain does', () => {
    // Math.round printed "~3d" for a 2.5 median that the risk chain, three
    // inches below, calls "2.5d — the median day any path reaches the stop".
    renderCard({ invalidation: { probability: 0.30, expectedDays: 2.5 } });
    expect(screen.getByText(/median ~2\.5d/)).toBeInTheDocument();
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

  it('warns when the bolded R:R describes an outcome the simulation barely reached', () => {
    // Every row of the default fixture has weightStockStopFirst == 0, which is
    // the reference contract's real behaviour: the premium stop fires first on
    // essentially every losing path, so the stock-stop R:R contributes nothing
    // to the edge. The copy says "almost never", not "never" — largest-
    // remainder can allocate 0 to a genuinely non-zero share, so the absolute
    // claim would be false on about half a percent of real rows, while
    // "contributes nothing to the edge" stays exact because the edge is
    // weighted with that same allocated zero.
    renderCard();
    expect(
      screen.getByText(/describes an outcome the simulation almost never reached/),
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
        // assertion is the TOTAL: with the backend's own allocated weights,
        // 0.27x1.04 - 0.00x5.17 - 0.69x3.12 + 0.04x-1.56 is -1.9296, printed as
        // -$1.93. The fixture used to carry -193.28 while the assertion checked
        // only the four terms, so the total went unchecked.
        /0\.27 x \$1\.04 - 0\.00 x \$5\.17 - 0\.69 x \$3\.12 \+ 0\.04 x \(\$3\.64 at expiry - \$5\.20\) = -\$1\.93\s+->\s+-\$193\.00 per contract/,
      ).length,
    ).toBeGreaterThan(0);
  });
});

// ── The cross-reference to the trade card's stop-cost readout ───────────────

describe('stopCostShown — never name a readout that is not on screen', () => {
  // The prop exists for exactly one reason: TradeCard hides the stop-cost gate
  // while the structural stop is loading or errored, and a paragraph telling
  // the reader to go and compare against a row that is nowhere on the page is
  // worse than saying nothing. Neither direction was pinned, so the prop could
  // have been dropped, inverted, or defaulted the other way in silence.
  const CROSS_REF = /see “Max loss if the stop is hit” in Structure & Stops/;

  it('points at the trade card readout when it is shown', () => {
    renderCard({ stopCostShown: true });
    expect(screen.getByText(CROSS_REF)).toBeInTheDocument();
    // The reason the two figures differ is what makes the comparison usable —
    // naming only decay sent a hand-checker looking for a difference decay
    // alone cannot account for.
    expect(screen.getByText(/time decay AND by pricing model/)).toBeInTheDocument();
  });

  it('says nothing about it when that readout is not rendered', () => {
    renderCard({ stopCostShown: false });
    expect(screen.queryByText(CROSS_REF)).not.toBeInTheDocument();
    // The line the paragraph always carries is still there — only the
    // cross-reference is conditional.
    expect(
      screen.getByText(/Priced at each barrier's own median day/),
    ).toBeInTheDocument();
  });

  it('defaults to saying nothing, since the caller opts in', () => {
    renderCard();
    expect(screen.queryByText(CROSS_REF)).not.toBeInTheDocument();
  });
});

// ── TRADE-CARD-BARRIER-PRESENTATION: one comparison row per target ──────────

describe('the comparison row', () => {
  // The rows of the outcome table, in target order. The barriers table is the
  // first table on the card; the outcome table is the second.
  const outcomeRows = () => {
    const tables = screen.getAllByRole('table');
    return within(tables[1]).getAllByRole('row').slice(1);   // drop the header row
  };

  it('puts the four shares, the target median, the stock R:R and the edge in the same row', () => {
    renderCard();
    const rows = outcomeRows();
    expect(rows).toHaveLength(3);
    const cells = within(rows[0]).getAllByRole('cell').map((c) => c.textContent);
    expect(cells).toEqual([
      '20%$6.24Estimated dollar outcomeUnavailable', '', '27%', '0%', '69%', '4%', '~7d', '0.20x', '-$193.00',
    ]);
    // The bar is in the second cell, and it is still the raw-share bar.
    expect(within(rows[0]).getByRole('img')).toBeInTheDocument();
    expect(within(rows[1]).getAllByRole('cell').map((c) => c.textContent).slice(2))
      .toEqual(['14%', '0%', '78%', '8%', '~12d', '0.35x', '-$228.00']);
    expect(within(rows[2]).getAllByRole('cell').map((c) => c.textContent).slice(2))
      .toEqual(['8%', '0%', '81%', '11%', '~16d', '0.50x', '-$243.00']);
  });

  it('names its columns', () => {
    renderCard();
    const headers = within(screen.getAllByRole('table')[1])
      .getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual([
      'Target / option', 'Split', 'Target first', 'Stock stop', 'Premium stop', 'Neither',
      'Median to target', 'R:R vs stock stop', 'Edge / contract',
    ]);
  });

  it('keeps the row R:R and edge equal to the tails of the full chains, in every branch', () => {
    // The row cells are cut from the formatters' own strings. Pin that against
    // each branch the formatters have, so the row can never print a number
    // beside a chain that ends in an em dash, or the reverse.
    const cases: Array<[string, Partial<BarrierRaceOutcome>, string, string]> = [
      ['measured', {}, '0.20x', '-$193.00'],
      ['stop could not be repriced', { stopRepricedValue: null, riskStockStop: null }, '—', '—'],
      ['no risk at the stop', { riskStockStop: 0, rrStockStop: null }, '—', '-$193.00'],
      ['negative risk leg', { riskStockStop: -1.5, rrStockStop: null }, '—', '-$193.00'],
      ['no edge', { edgePerContract: null }, '0.20x', '—'],
      ['positive edge', { edgePerContract: 298 }, '0.20x', '$298.00'],
    ];
    for (const [name, over, rr, edge] of cases) {
      const o = outcome(over);
      const { unmount } = render(
        <BarrierRaceCard
          race={{ ...RACE, outcomes: [o] }}
          premiumStopFromField
          premiumStopField={PREMIUM_STOP_FIELD}
          isFresh
        />,
      );
      const cells = within(outcomeRows()[0]).getAllByRole('cell').map((c) => c.textContent);
      expect([name, cells[7], cells[8]]).toEqual([name, rr, edge]);
      // And the full chain the disclosure prints ends in exactly those values.
      const rrChain = formatRaceRR(o);
      expect([name, rr === '—' ? rrChain.endsWith('= —') : rrChain.endsWith(`= ${rr}`)])
        .toEqual([name, true]);
      const edgeChain = formatRaceEdge(o, RACE.premiumUsed);
      expect([name, edge === '—' ? edgeChain === '—' : edgeChain.endsWith(`${edge} per contract`)])
        .toEqual([name, true]);
      expect(screen.getByText(rrChain)).toBeInTheDocument();
      unmount();
    }
  });

  it('does not colour the edge: the card adds no gate', () => {
    renderCard({ race: { ...RACE, outcomes: [outcome({ edgePerContract: 298 })] } });
    const edgeCell = within(outcomeRows()[0]).getAllByRole('cell')[8];
    expect(edgeCell.innerHTML).not.toMatch(/tone(Pass|Reject|Caution)/);
  });
});

describe('the inline disclosure', () => {
  const details = (container: HTMLElement) => container.querySelector('details') as HTMLElement;

  it('is closed by default and holds the stop medians, the full chains and the prose', () => {
    const { container } = renderCard({ stopCostShown: true });
    const d = details(container);
    expect(d).not.toBeNull();
    expect(d).not.toHaveAttribute('open');
    const inside = within(d);
    // The two stop medians, per target.
    expect(inside.getAllByText('Median to stock stop')).toHaveLength(3);
    expect(inside.getAllByText('Median to premium stop')).toHaveLength(3);
    expect(inside.getByText('~20d')).toBeInTheDocument();
    expect(inside.getAllByText('~21d')).toHaveLength(2);
    // Every chain, still printed in full by the original formatters.
    expect(inside.getAllByText(/= \$5\.17$/)).toHaveLength(3);
    expect(inside.getByText('$1.04 / $5.17 = 0.20x')).toBeInTheDocument();
    expect(inside.getByText(/0\.33x, the same on every contract/)).toBeInTheDocument();
    expect(inside.getAllByText(/per contract$/)).toHaveLength(3);
    // The explanations.
    expect(inside.getByText(/counted once, for whichever barrier it reached first/)).toBeInTheDocument();
    expect(inside.getByText(/median over the paths that got there first/)).toBeInTheDocument();
    expect(inside.getByText(/see “Max loss if the stop is hit”/)).toBeInTheDocument();
    expect(inside.getByText(/Only the first ratio is a measurement/)).toBeInTheDocument();
    expect(inside.getByText(/It is signed, not a loss/)).toBeInTheDocument();
    expect(inside.getByText(/a real fear bid would leave more premium than shown/)).toBeInTheDocument();
  });

  it('never holds a warning: both stay visible outside it', () => {
    const { container } = renderCard({ race: { ...RACE, ivSolved: false } });
    const d = details(container);
    const iv = screen.getByText(/implied volatility could not be backed out of its quote/);
    const weak = screen.getByText(/describes an outcome the simulation almost never reached/);
    expect(d.contains(iv)).toBe(false);
    expect(d.contains(weak)).toBe(false);
  });

  it('keeps the barriers and the standalone stock-stop touch outside it', () => {
    const { container } = renderCard({ invalidation: { probability: 0.81, expectedDays: 14 } });
    const d = details(container);
    expect(d.contains(screen.getByText('$176.00 stock'))).toBe(false);
    expect(d.contains(screen.getByText('$2.08 option'))).toBe(false);
    const standalone = screen.getByText(/81% of paths touch the/);
    expect(standalone).toHaveTextContent('(median ~14d)');
    expect(d.contains(standalone)).toBe(false);
  });

  it('shows the assumptions strip outside it', () => {
    const { container } = renderCard();
    const strip = screen.getByText('2,000 paths · each row sums to 100%');
    expect(details(container).contains(strip)).toBe(false);
    expect(screen.getByText('Edge before commissions')).toBeInTheDocument();
  });

  it('is absent from the changed-barrier and refusal branches', () => {
    const changed = renderCard({ barriersChanged: true });
    expect(changed.container.querySelector('details')).toBeNull();
    expect(changed.container.querySelector('table')).toBeNull();
    changed.unmount();
    const refused = render(
      <BarrierRaceCard race={null} premiumStopFromField premiumStopField={PREMIUM_STOP_FIELD} isFresh />,
    );
    expect(refused.container.querySelector('details')).toBeNull();
  });
});


describe('controlled race shortcut', () => {
  it('has no action for shared callers unless explicitly supplied', () => {
    renderCard();
    expect(screen.queryByRole('button', { name: /Use Barrier Race/ })).not.toBeInTheDocument();
  });

  it('emits only the target identity and renders the controlled selection', () => {
    const onSelectTarget = jest.fn();
    renderCard({ onSelectTarget, selectedTargetPct: 0.35 });
    expect(screen.getByRole('button', { name: 'Use Barrier Race T35%' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Use Barrier Race T20%' }));
    expect(onSelectTarget).toHaveBeenCalledWith(0.2);
  });

  it.each([
    { race: null }, { race: undefined }, { isFresh: false },
    { barriersChanged: true }, { barriersChanged: true, stockStopMoved: true },
  ])('retains refusal/freshness early returns with a callback: %p', (props) => {
    renderCard({ ...props, onSelectTarget: jest.fn() });
    expect(screen.queryByRole('button', { name: /Use Barrier Race/ })).not.toBeInTheDocument();
  });
});

// OPT-PRES-07: the target reward is already returned in the backend's cents.
describe('selected-contract dollar outcomes', () => {
  const rows = () => within(screen.getAllByRole('table')[1]).getAllByRole('row').slice(1);

  it('scales every returned reward by entered quantity, retaining selection and per-contract edge', () => {
    const onSelectTarget = jest.fn();
    renderCard({ quantity: 2, onSelectTarget });
    expect(screen.getByText(/2 entered contracts × 100 shares.*selected-contract full exit/)).toBeVisible();
    ['$208.00', '$364.00', '$520.00'].forEach((amount, i) => {
      expect(within(rows()[i]).getByText(amount)).toBeVisible();
      fireEvent.click(within(rows()[i]).getByRole('button'));
      expect(onSelectTarget).toHaveBeenLastCalledWith(RACE.outcomes[i].targetPct);
    });
    expect(within(rows()[0]).getByText('-$193.00')).toBeVisible();
  });

  it('uses rewardDollar rather than rebuilding it from a percentage or a differently rounded premium', () => {
    renderCard({ quantity: 3, race: { ...RACE, premiumUsed: 1.03,
      outcomes: [outcome({ targetPct: 0.2, targetOptionPrice: 1.235, rewardDollar: 0.21 })] } });
    expect(within(rows()[0]).getByText('$63.00')).toBeVisible();
    expect(within(rows()[0]).queryByText('$61.50')).not.toBeInTheDocument();
  });

  it('matches existing formatter precision for a legacy half-cent reward before quantity scaling', () => {
    renderCard({ quantity: 3, race: { ...RACE, outcomes: [outcome({ rewardDollar: 0.215 })] } });
    expect(within(rows()[0]).getByText('$63.00')).toBeVisible();
    expect(screen.getByText(/\$0\.21 \/ \$5\.17/)).toBeInTheDocument();
  });

  it.each([0, 0.29, -0.29])('preserves a zero or signed reward %s without binary-float tails', (rewardDollar) => {
    renderCard({ quantity: 3, race: { ...RACE, outcomes: [outcome({ rewardDollar })] } });
    const amount = rewardDollar === 0 ? '$0.00' : rewardDollar > 0 ? '$87.00' : '-$87.00';
    expect(within(rows()[0]).getByText(amount)).toBeVisible();
  });

  it('shows zero quantity as zero and limits spread amounts to the selected contract', () => {
    renderCard({ quantity: 0, isSpread: true });
    rows().forEach((row) => expect(within(row).getByText('$0.00')).toBeVisible());
    expect(screen.getByText(/not a whole-spread outcome/)).toBeVisible();
  });

  it.each([undefined, NaN, Infinity, -1])('does not invent an amount for unavailable quantity %s', (quantity) => {
    renderCard({ quantity });
    rows().forEach((row) => expect(within(row).getByText('Unavailable')).toBeVisible());
  });

  it.each([NaN, Infinity, undefined])('does not invent an amount for unavailable returned reward %s', (rewardDollar) => {
    renderCard({ quantity: 2, race: { ...RACE, outcomes: [outcome({ rewardDollar })] } });
    expect(within(rows()[0]).getByText('Unavailable')).toBeVisible();
  });

  it('retains availability gates for dollar outcomes when barriers change', () => {
    renderCard({ quantity: 2, barriersChanged: true });
    expect(screen.queryByText('$208.00')).not.toBeInTheDocument();
    expect(screen.queryByText('Estimated dollar outcome')).not.toBeInTheDocument();
  });
});
