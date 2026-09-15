import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { MethodPickSelector } from '@/components/molecules/MethodPickSelector';
import type { MethodPickOption } from '@/components/molecules/MethodPickSelector';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 3 — the control's own rules (spec §6.1, §7.4,
// §9.2). The card-level wiring is pinned in TradeCard.methodPick.test.tsx and
// StockPositionCard.methodPick.test.tsx.

const NOW = '2026-09-14T12:00:00.000Z';
const now = () => NOW;

/** The four options with ONE row each, using the §6.1 table's per-method split
 *  verbatim — a ladder/arithmetic row is stock-only, a Monte Carlo row carries
 *  both (and RENDERS the premium), a race row is option-only. */
function options(over: Partial<Record<string, unknown>> = {}): MethodPickOption[] {
  void over;
  return [
    {
      method: 'ladder', label: 'Ladder', unavailable: null,
      rows: [{ key: 'tp1', label: 'TP1', displayPrice: 200.02, rowStockPrice: 200.02, rowOptionPrice: null }],
    },
    {
      method: 'arithmetic', label: 'Arithmetic', unavailable: null,
      rows: [{ key: 'a2', label: '2:1', displayPrice: 210.5, rowStockPrice: 210.5, rowOptionPrice: null }],
    },
    {
      method: 'monte_carlo', label: 'Monte Carlo', unavailable: null,
      rows: [{ key: 'mc20', label: 'T20%', displayPrice: 6.24, rowStockPrice: 197.5, rowOptionPrice: 6.24 }],
    },
    {
      method: 'barrier_race', label: 'Barrier Race', unavailable: null,
      rows: [{ key: 'r20', label: 'T20%', displayPrice: 6.24, rowStockPrice: null, rowOptionPrice: 6.24 }],
    },
  ];
}

const radio = (name: string) => screen.getByRole('radio', { name });

describe('MethodPickSelector — the method radiogroup', () => {
  it('pre-selects nothing (§6.1: a pre-selected radio is a default nobody looked at)', () => {
    render(<MethodPickSelector options={options()} pick={null} onChange={jest.fn()} now={now} />);
    for (const label of ['Ladder', 'Arithmetic', 'Monte Carlo', 'Barrier Race']) {
      expect(radio(label)).toHaveAttribute('aria-checked', 'false');
    }
  });

  it('disables an unavailable method WITH ITS REASON rather than hiding it', () => {
    const opts = options();
    opts[2] = { ...opts[2], unavailable: 'Run Estimate first', rows: [] };
    render(<MethodPickSelector options={opts} pick={null} onChange={jest.fn()} now={now} />);
    // Present, not hidden — the absence of a run must not read as "this card
    // does not have Monte Carlo".
    expect(radio('Monte Carlo')).toBeDisabled();
    expect(screen.getByText('Run Estimate first')).toBeInTheDocument();
  });

  it('a disabled method cannot be picked', () => {
    const opts = options();
    opts[3] = { ...opts[3], unavailable: 'Run Estimate first', rows: [] };
    const onChange = jest.fn();
    render(<MethodPickSelector options={opts} pick={null} onChange={onChange} now={now} />);
    fireEvent.click(radio('Barrier Race'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('picking a method emits a complete pick with NO row and the default basis', () => {
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={null} onChange={onChange} now={now} />);
    fireEvent.click(radio('Barrier Race'));
    // §7.4 — "neither price field blocks". A method alone is a complete
    // decision; Barrier Race in particular can never carry a stock price, so a
    // pick that required one would make the race unpickable.
    expect(onChange).toHaveBeenCalledWith({
      method: 'barrier_race',
      rowStockPrice: null,
      rowOptionPrice: null,
      stopBasis: 'stock',
      pickedAt: NOW,
    });
  });

  it('re-clicking the live method is a no-op, so it cannot drop a chosen row', () => {
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'premium', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(radio('Monte Carlo'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('switching method DROPS the previous row rather than carrying its prices across', () => {
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'premium', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(radio('Barrier Race'));
    // Carrying 197.5 across would leave a Monte Carlo UNDERLYING level stamped
    // on a Barrier Race pick — and a race pick must seed ('ladder', NULL).
    expect(onChange).toHaveBeenCalledWith({
      method: 'barrier_race',
      rowStockPrice: null,
      rowOptionPrice: null,
      stopBasis: 'premium',   // the basis is a separate decision and survives
      pickedAt: NOW,
    });
  });

  it('Clear removes the pick entirely', () => {
    const pick: MethodPick = {
      method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null,
      stopBasis: 'stock', pickedAt: NOW,
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

describe('MethodPickSelector — the row radiogroup and the §6.1 price split', () => {
  it('shows no row group until a method is picked', () => {
    render(<MethodPickSelector options={options()} pick={null} onChange={jest.fn()} now={now} />);
    expect(screen.queryByRole('radiogroup', { name: 'Target row' })).not.toBeInTheDocument();
  });

  it('offers NO rows for a method that has gone unavailable, even while it is still the pick', () => {
    // A pick survives its method going away for as long as it takes the card's
    // clear effect to fire. On that commit the control must not render the
    // method as disabled-with-a-reason AND offer its rows as clickable — which
    // is what happens when `active` is chosen by the pick's method alone.
    const opts = options();
    opts[2] = { ...opts[2], unavailable: 'Estimate not re-run this session' };
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={opts} pick={pick} onChange={jest.fn()} now={now} />);
    expect(radio('Monte Carlo')).toBeDisabled();
    expect(screen.queryByRole('radiogroup', { name: 'Target row' })).not.toBeInTheDocument();
  });

  it('a Monte Carlo row stores the UNDERLYING in rowStockPrice and the PREMIUM in rowOptionPrice', () => {
    // THE UNITS TEST, at the control. The row RENDERS 6.24 (the premium — what
    // the trader is reading), while the field that may seed resolved_tp_price
    // is the 197.50 beside it. A control that stored "the price on the row"
    // once would put a $6.24 premium in a stock-price column, making
    // `price >= 6.24` true on the first tick and firing TP_HIT instantly on
    // every bullish position.
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: null, rowOptionPrice: null,
      stopBasis: 'stock', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    const group = screen.getByRole('radiogroup', { name: 'Target row' });
    expect(group).toHaveTextContent('$6.24');
    fireEvent.click(screen.getByRole('radio', { name: 'T20%' }));
    expect(onChange).toHaveBeenCalledWith({
      method: 'monte_carlo',
      rowStockPrice: 197.5,
      rowOptionPrice: 6.24,
      stopBasis: 'stock',
      pickedAt: NOW,
    });
  });

  it('a Barrier Race row stores a NULL stock price, never the option price', () => {
    const pick: MethodPick = {
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: null,
      stopBasis: 'stock', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(screen.getByRole('radio', { name: 'T20%' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      rowStockPrice: null, rowOptionPrice: 6.24,
    }));
  });

  it('a ladder row stores a NULL option price', () => {
    const pick: MethodPick = {
      method: 'ladder', rowStockPrice: null, rowOptionPrice: null,
      stopBasis: 'stock', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(screen.getByRole('radio', { name: 'TP1' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      rowStockPrice: 200.02, rowOptionPrice: null,
    }));
  });

  it('highlights the stored row by its PRICE PAIR, which is all a pick records', () => {
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={options()} pick={pick} onChange={jest.fn()} now={now} />);
    expect(screen.getByRole('radio', { name: 'T20%' })).toHaveAttribute('aria-checked', 'true');
  });

  it('highlights NO row when the stored prices no longer match one', () => {
    // A recompute moved the row. Showing a different row lit up would be a
    // screen naming a level the pick does not carry.
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 111.11, rowOptionPrice: 2.22,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={options()} pick={pick} onChange={jest.fn()} now={now} />);
    expect(screen.getByRole('radio', { name: 'T20%' })).toHaveAttribute('aria-checked', 'false');
  });

  it('needs BOTH fields to agree — the stock term', () => {
    // Two Monte Carlo rows whose premiums coincide (the same % target priced
    // off two different underlying levels is not exotic once a plan is
    // recomputed). Matching on `rowOptionPrice` alone lights the FIRST row for
    // a pick that names the second — a screen showing a level the pick does
    // not carry.
    const opts = options();
    opts[2] = {
      ...opts[2],
      rows: [
        { key: 'a', label: 'A', displayPrice: 6.24, rowStockPrice: 197.5, rowOptionPrice: 6.24 },
        { key: 'b', label: 'B', displayPrice: 6.24, rowStockPrice: 204.1, rowOptionPrice: 6.24 },
      ],
    };
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 204.1, rowOptionPrice: 6.24,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={opts} pick={pick} onChange={jest.fn()} now={now} />);
    expect(screen.getByRole('radio', { name: 'A' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'B' })).toHaveAttribute('aria-checked', 'true');
  });

  it('needs BOTH fields to agree — the option term', () => {
    // `FirstPassageTarget.stockPrice` is "null if unreachable", so a plan can
    // carry several rows with no stock level at all. Matching on
    // `rowStockPrice` alone lights the first of them for every pick.
    const opts = options();
    opts[2] = {
      ...opts[2],
      rows: [
        { key: 'a', label: 'A', displayPrice: 6.24, rowStockPrice: null, rowOptionPrice: 6.24 },
        { key: 'b', label: 'B', displayPrice: 7.8, rowStockPrice: null, rowOptionPrice: 7.8 },
      ],
    };
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: null, rowOptionPrice: 7.8,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={opts} pick={pick} onChange={jest.fn()} now={now} />);
    expect(screen.getByRole('radio', { name: 'A' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'B' })).toHaveAttribute('aria-checked', 'true');
  });

  it('does not match a null-stock-price row to a pick that merely has no row', () => {
    // Both fields must agree. Matching on "the non-null one" alone would light
    // up the race row for every method-only pick, since both carry nulls.
    const pick: MethodPick = {
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: null,
      stopBasis: 'stock', pickedAt: NOW,
    };
    render(<MethodPickSelector options={options()} pick={pick} onChange={jest.fn()} now={now} />);
    expect(screen.getByRole('radio', { name: 'T20%' })).toHaveAttribute('aria-checked', 'false');
  });
});

describe('MethodPickSelector — the stop basis (§9.2)', () => {
  it('says "Judged on", never "armed"', () => {
    render(<MethodPickSelector options={options()} pick={null} onChange={jest.fn()} now={now} />);
    // G records which stop the trade was judged on and re-points NO alert. A
    // control captioned "armed" beside a STOP_REACHED that still fires on the
    // stock stop would name one basis while a different one fires.
    expect(screen.getByRole('radiogroup', { name: 'Judged on' })).toBeInTheDocument();
    expect(screen.queryByText(/armed/i)).not.toBeInTheDocument();
  });

  it('is inert until a method is picked', () => {
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={null} onChange={onChange} now={now} />);
    expect(radio('Premium stop')).toBeDisabled();
    fireEvent.click(radio('Premium stop'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('changes the basis on an existing pick without touching its row', () => {
    const pick: MethodPick = {
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'stock', pickedAt: '2026-09-13T00:00:00.000Z',
    };
    const onChange = jest.fn();
    render(<MethodPickSelector options={options()} pick={pick} onChange={onChange} now={now} />);
    fireEvent.click(radio('Premium stop'));
    expect(onChange).toHaveBeenCalledWith({
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
      stopBasis: 'premium', pickedAt: NOW,
    });
  });
});
