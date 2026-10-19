import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { SavedScanResultsTable } from '../index';

test('options rows keep the saved stock score and capped status, with the full record collapsed', () => {
  const row = {
    symbol: 'MKC', direction: 'Bearish', price: 46.17, stockScore: 62,
    stockConfidence: 'CAUTION', finalStatus: 'REJECT',
    stockExplanation: { score: 62, raw_status: 'PASS', unrounded_score: 62.1 },
  };
  render(<SavedScanResultsTable category="options" rows={[row]} />);
  const table = screen.getByRole('table', { name: 'Saved accepted results' });
  const result = within(table).getByRole('row', { name: /MKC/ });
  expect(within(result).getByText('$46.17')).toBeInTheDocument();
  expect(within(result).getByText('Bearish')).toBeInTheDocument();
  expect(within(result).getByText('62')).toBeInTheDocument();
  expect(within(result).getByText('CAUTION')).toBeInTheDocument();
  const details = within(result).getByText('Raw record').closest('details')!;
  expect(details.open).toBe(false);
  expect(within(details).getByText(/unrounded_score/)).not.toBeVisible();
  fireEvent.click(within(details).getByText('Raw record'));
  expect(details.open).toBe(true);
  expect(JSON.parse(details.querySelector('pre')!.textContent!)).toEqual(row);
});

test.each(['stocks', 'pullback'] as const)('%s uses the saved stock fields rather than historical confidence or explanation status', category => {
  render(<SavedScanResultsTable category={category} rows={[{
    symbol: 'ZERO', direction: 'Bullish', price: 0, stock_score: 0,
    stock_status: 'REJECT', confidence: 91, stock_explanation: { score: 80, status: 'PASS' },
  }]} />);
  const row = screen.getByRole('row', { name: /ZERO/ });
  expect(within(row).getByText('$0')).toBeInTheDocument();
  expect(within(row).getByText('0')).toBeInTheDocument();
  expect(within(row).getByText('REJECT')).toBeInTheDocument();
});

test.each(['prebreakout', 'fib'] as const)('%s labels setup confidence without inventing a stock status or price', category => {
  render(<SavedScanResultsTable category={category} rows={[{ symbol: 'SETUP', direction: 'Bullish', confidence: 0 }]} />);
  expect(screen.getByRole('columnheader', { name: 'Confidence' })).toBeInTheDocument();
  expect(screen.queryByRole('columnheader', { name: 'Stock score' })).not.toBeInTheDocument();
  expect(screen.queryByRole('columnheader', { name: 'Stock status' })).not.toBeInTheDocument();
  expect(screen.queryByRole('columnheader', { name: 'Price' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('row', { name: /SETUP/ })).getByText('0')).toBeInTheDocument();
});

test('absent, unavailable and nonnumeric values are not displayed as measured zero', () => {
  render(<SavedScanResultsTable category="options" rows={[
    { symbol: 'ABSENT', price: null },
    { symbol: 'REDACTED', direction: 'Bearish', direction_unavailable: true, price: 0, price_unavailable: true, stockScore: 0, stockScore_unavailable: true, stockConfidence: 'PASS', stockConfidence_unavailable: true },
    { symbol: 'INVALID', price: Infinity, stockScore: '0', stockConfidence: 'Unknown' },
  ]} />);
  for (const symbol of ['ABSENT', 'REDACTED', 'INVALID']) {
    const row = screen.getByRole('row', { name: new RegExp(symbol) });
    expect(within(row).getAllByText('Unavailable')).toHaveLength(4);
    expect(within(row).queryByText('$0')).not.toBeInTheDocument();
  }
});

test('an empty saved result stays empty', () => {
  render(<SavedScanResultsTable category="stocks" rows={[]} />);
  expect(screen.getByText('No accepted results recorded.')).toBeInTheDocument();
  expect(screen.getAllByRole('row')).toHaveLength(1);
});
