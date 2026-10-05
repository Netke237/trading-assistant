import { render, screen, within } from '@testing-library/react';
import { fundamentalScoreTooltip, safetyFlagTooltip } from '@/lib/statusTooltips';
import type { FundamentalsOut } from '@/types/domain';
import { FundamentalHealthCard } from './index';

jest.mock('./FundamentalHealthCard.module.css', () => ({
  __esModule: true,
  default: new Proxy({}, { get: (_, key) => String(key) }),
}));

const fundamentals: FundamentalsOut = {
  score: 64, quality_label: 'Strong', risk_label: 'High',
  growth_score: 65, quality_score: 40, risk_score: 39,
  safety_flags: ['negative_equity', 'extreme_leverage', 'unknown_flag'], detail: {},
};

test('default false keeps original markup; compact keeps original values and tooltips', () => {
  const { container, rerender } = render(<FundamentalHealthCard f={fundamentals} />);
  const baseline = container.innerHTML;
  rerender(<FundamentalHealthCard f={fundamentals} compact={false} />);
  expect(container.innerHTML).toBe(baseline);
  rerender(<FundamentalHealthCard f={fundamentals} compact />);
  const copy = container.cloneNode(true) as HTMLElement;
  copy.querySelector('details')?.remove();
  expect(copy.innerHTML.replace('card compact', 'card')).toBe(baseline);
  expect(screen.getByText('Strong quality · High risk')).toBeVisible();
  const tooltips = screen.getAllByRole('tooltip').map(t => t.textContent);
  expect(tooltips).toEqual([
    fundamentalScoreTooltip('overall', 64), fundamentalScoreTooltip('growth', 65),
    fundamentalScoreTooltip('quality', 40), fundamentalScoreTooltip('risk', 39),
    ...fundamentals.safety_flags.map(safetyFlagTooltip),
  ]);
});

test('compact preserves each independent score colour and keeps active flags outside details', () => {
  render(<FundamentalHealthCard f={fundamentals} compact />);
  expect(screen.getByText('64')).toHaveClass('toneCaution');
  expect(screen.getByText('65')).toHaveClass('tonePass');
  expect(screen.getByText('40')).toHaveClass('toneCaution');
  expect(screen.getByText('39')).toHaveClass('toneReject');
  for (const flag of fundamentals.safety_flags) {
    const chip = screen.getByText(flag.replace(/_/g, ' '));
    expect(chip).toBeVisible();
    expect(chip).toHaveClass('flag');
    expect(chip.closest('details')).toBeNull();
  }
});

test('compact definitions remain mounted and use the existing score and flag explanations', () => {
  const { container } = render(<FundamentalHealthCard f={fundamentals} compact />);
  const details = container.querySelector('details')!;
  expect(details).not.toHaveAttribute('open');
  expect(within(details).getByText('Score definitions & safety flags')).toBeVisible();
  for (const text of [
    fundamentalScoreTooltip('overall', 64), fundamentalScoreTooltip('growth', 65),
    fundamentalScoreTooltip('quality', 40), fundamentalScoreTooltip('risk', 39),
    ...fundamentals.safety_flags.map(safetyFlagTooltip),
  ]) {
    expect(within(details).getByText(text)).toBeInTheDocument();
  }
});

test.each([null, undefined])('compact preserves no-data state (%s)', f => {
  const { container, rerender } = render(<FundamentalHealthCard f={f} />);
  const baseline = container.innerHTML;
  rerender(<FundamentalHealthCard f={f} compact />);
  expect(container.innerHTML).toBe(baseline);
  expect(screen.getByText('Fundamental Health — no data')).toBeVisible();
  expect(container.querySelector('details')).toBeNull();
});

test.each([[], undefined])('compact tolerates empty or legacy absent safety flags (%s)', safety_flags => {
  render(<FundamentalHealthCard compact f={{ ...fundamentals, safety_flags } as FundamentalsOut} />);
  expect(screen.getByText('64')).toBeVisible();
  expect(screen.queryByText('negative equity')).not.toBeInTheDocument();
  expect(screen.getAllByRole('tooltip')).toHaveLength(4);
});

test('changing candidate data replaces compact scores, definitions and safety flags', () => {
  const { container, rerender } = render(<FundamentalHealthCard f={fundamentals} compact />);
  rerender(<FundamentalHealthCard compact f={{
    ...fundamentals, score: 0, growth_score: 10, quality_score: 20, risk_score: 30,
    quality_label: 'Weak', risk_label: 'Low', safety_flags: [],
  }} />);
  expect(screen.getByText('0')).toHaveClass('toneReject');
  expect(screen.queryByText('64')).not.toBeInTheDocument();
  expect(screen.queryByText('negative equity')).not.toBeInTheDocument();
  expect(screen.getByText('Weak quality · Low risk')).toBeVisible();
  expect(within(container.querySelector('details')!).getByText(fundamentalScoreTooltip('overall', 0)))
    .toBeInTheDocument();
});
