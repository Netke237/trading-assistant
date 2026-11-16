import '@testing-library/jest-dom';
import * as React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { CandidateNav } from '..';

// #610 G2 — the candidate navigation is a thin inline row
// ("‹ Previous · AAPL 1 / 2 · Next ›", Pin to basket, "Basket — empty"),
// keeping every control, chip, disabled reason and handler.
jest.mock('@/components/primitives/Text.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));

const handlers = () => ({
  onPrev: jest.fn(), onNext: jest.fn(), onSelect: jest.fn(), onTogglePin: jest.fn(), onRemovePin: jest.fn(),
});

describe('CandidateNav inline row', () => {
  it('reads as one inline row with sentence-case basket text and keeps the controls', () => {
    const h = handlers();
    render(<CandidateNav symbols={['AAPL', 'MSFT']} activeSymbol="AAPL" basket={[]} {...h} />);
    const prev = screen.getByRole('button', { name: 'Previous candidate' });
    const next = screen.getByRole('button', { name: 'Next candidate' });
    expect(prev).toHaveTextContent('‹ Previous');
    expect(next).toHaveTextContent('Next ›');
    expect(prev).toBeDisabled();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    // Sentence case, readable tone — not the dim uppercase "BASKET — empty".
    const basket = screen.getByText('Basket — empty');
    expect(basket).toHaveClass('s12', 'toneSecondary');
    expect(basket).not.toHaveClass('toneDim');
    // Navigation, pin and basket share a single row.
    const pin = screen.getByRole('button', { name: /Pin to basket/ });
    expect(prev.closest('[data-candidate-nav-row]')).toContainElement(pin);
    expect(prev.closest('[data-candidate-nav-row]')).toContainElement(basket);
    fireEvent.click(next);
    fireEvent.click(pin);
    expect(h.onNext).toHaveBeenCalledTimes(1);
    expect(h.onTogglePin).toHaveBeenCalledTimes(1);
  });

  it('keeps basket chips, their select/remove handlers, the count and the pin disabled reason', () => {
    const h = handlers();
    render(<CandidateNav symbols={['AAPL', 'MSFT']} activeSymbol="MSFT" basket={['AAPL']} {...h}
      pinDisabled pinDisabledReason="Earnings inside the window" />);
    const basket = screen.getByLabelText('Basket');
    expect(within(basket).getByText('Basket (1)')).toBeInTheDocument();
    fireEvent.click(within(basket).getByRole('button', { name: 'AAPL' }));
    fireEvent.click(within(basket).getByRole('button', { name: 'Remove AAPL from basket' }));
    expect(h.onSelect).toHaveBeenCalledWith('AAPL');
    expect(h.onRemovePin).toHaveBeenCalledWith('AAPL');
    const pin = screen.getByTitle('Earnings inside the window');
    expect(pin).toBeDisabled();
  });
});
