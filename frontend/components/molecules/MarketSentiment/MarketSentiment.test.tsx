import { render, screen } from '@testing-library/react';
import type { SentimentData } from '@/types/domain';
import { MarketSentiment } from './index';

jest.mock('./MarketSentiment.module.css', () => ({
  __esModule: true,
  default: new Proxy({}, { get: (_, key) => String(key) }),
}));

const sentiment: SentimentData = {
  horizon: 'Position', timeframe: 'daily', state: 'Bull', p_stay: 0.876,
  stability: 'Stable', regime_age_days: 12, avg_regime_duration: 31.5,
  conviction_pct: 27.4, conviction_label: 'Strong conviction',
  interpretation: 'The regime favours this trade.', alignment: 'Aligned',
};

test('compact preserves the complete default content and default false preserves markup', () => {
  const { container, rerender } = render(<MarketSentiment s={sentiment} />);
  const baseline = container.innerHTML;
  rerender(<MarketSentiment s={sentiment} compact={false} />);
  expect(container.innerHTML).toBe(baseline);
  rerender(<MarketSentiment s={sentiment} compact />);
  expect(container.innerHTML.replace('card compact', 'card')).toBe(baseline);
  expect(screen.getByText('Position · daily')).toBeVisible();
  expect(screen.getByText('+27.4%')).toHaveClass('tonePass');
  expect(screen.getByText('Strong conviction — The regime favours this trade.')).toBeVisible();
  expect(screen.getByText('State Bull · sticky 88% · ≈31.5 strides')).toBeVisible();
  expect(screen.getByText('OMM/HMM Aligned')).toHaveClass('aligned');
});

test('a carried stride size is shown beside the average', () => {
  const withStride = { ...sentiment, duration_stride_bars: 20 };
  render(<MarketSentiment s={withStride} />);
  expect(screen.getByText('State Bull · sticky 88% · ≈31.5 strides of 20 bars')).toBeVisible();
});

test.each([
  [15, '+15%', 'tonePass'], [14.9, '+14.9%', 'toneCaution'],
  [0, '0%', 'toneCaution'], [-14.9, '-14.9%', 'toneCaution'],
  [-15, '-15%', 'toneReject'],
])('compact keeps the conviction band for %s', (conviction_pct, value, colour) => {
  render(<MarketSentiment s={{ ...sentiment, conviction_pct }} compact />);
  expect(screen.getByText(value)).toHaveClass(colour);
});

test.each([
  ['Aligned', 'OMM/HMM Aligned', 'aligned'],
  ['Diverging', 'OMM/HMM Diverging', 'diverging'],
  ['Unavailable', 'OMM only', 'unavail'],
] as const)('compact retains the %s alignment state', (alignment, label, colour) => {
  render(<MarketSentiment s={{ ...sentiment, alignment }} compact />);
  expect(screen.getByText(label)).toBeVisible();
  expect(screen.getByText(label)).toHaveClass(colour);
});

test.each([null, undefined, { ...sentiment, insufficient_data: true }])(
  'compact never exposes stale values with missing or insufficient history (%s)', s => {
    const { container, rerender } = render(<MarketSentiment s={s} />);
    const baseline = container.innerHTML;
    rerender(<MarketSentiment s={s} compact />);
    expect(container.innerHTML).toBe(baseline);
    expect(screen.getByText('Regime: Unmeasured')).toBeVisible();
    expect(screen.getByText('Regime: Unmeasured')).toHaveClass('toneCaution');
    expect(screen.getByText('Insufficient history or unavailable data.')).toBeVisible();
    expect(screen.queryByText(/State Bull|sticky|OMM\/HMM|Strong conviction/)).not.toBeInTheDocument();
    expect(screen.queryByText('+27.4%')).not.toBeInTheDocument();
  },
);

test('candidate data changes replace all compact sentiment values', () => {
  const { rerender } = render(<MarketSentiment s={sentiment} compact />);
  rerender(<MarketSentiment compact s={{
    ...sentiment, state: 'Bear', conviction_pct: -30, p_stay: 0,
    avg_regime_duration: 0, conviction_label: 'Opposed', interpretation: 'Against this trade.',
    alignment: 'Diverging',
  }} />);
  expect(screen.queryByText('+27.4%')).not.toBeInTheDocument();
  expect(screen.getByText('-30%')).toHaveClass('toneReject');
  expect(screen.getByText('Opposed — Against this trade.')).toBeVisible();
  expect(screen.getByText('State Bear · sticky 0% · ≈0 strides')).toBeVisible();
});

test('compact context names conviction, state and alignment independently without a new qualification verdict', () => {
  render(<MarketSentiment s={{ ...sentiment, state: 'Bull', conviction_pct: -30, alignment: 'Diverging' }} compact />);
  expect(screen.getByText('Conviction')).toBeVisible();
  expect(screen.getByText('-30%')).toHaveClass('toneReject');
  expect(screen.getByText('State Bull · sticky 88% · ≈31.5 strides')).toBeVisible();
  expect(screen.getByText('Alignment')).toBeVisible();
  expect(screen.getByText('OMM/HMM Diverging')).toHaveClass('diverging');
  expect(screen.queryByText('PASS')).not.toBeInTheDocument();
});

test.each([false, true])('candidate changes clear stale values and restore measured zero (compact=%s)', compact => {
  const { rerender } = render(<MarketSentiment s={sentiment} compact={compact} />);
  expect(screen.getByText('+27.4%')).toBeVisible();
  rerender(<MarketSentiment s={{ ...sentiment, insufficient_data: true }} compact={compact} />);
  expect(screen.getByText('Regime: Unmeasured')).toBeVisible();
  expect(screen.queryByText(/State Bull|27.4%|Strong conviction|OMM\/HMM/)).not.toBeInTheDocument();
  rerender(<MarketSentiment s={{ ...sentiment, conviction_pct: 0 }} compact={compact} />);
  expect(screen.queryByText('Regime: Unmeasured')).not.toBeInTheDocument();
  expect(screen.getByText('0%')).toHaveClass('toneCaution');
  expect(screen.getByText('State Bull · sticky 88% · ≈31.5 strides')).toBeVisible();
});
