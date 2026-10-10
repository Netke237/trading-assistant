import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '../index';

// CSS modules map to an empty object under Jest, so give Data's tone classes
// readable names here to assert which tone the badge renders.
jest.mock('@/components/primitives/Data.module.css', () => ({
  toneDim: 'toneDim',
  toneCaution: 'toneCaution',
  tonePass: 'tonePass',
  toneReject: 'toneReject',
}));

const UNVALIDATED_TOOLTIP =
  'Fewer than 20 non-overlapping past setups. Not enough history to validate this pattern, so it cannot reach PASS.';

test('renders a measured confidence as a percent', () => {
  render(<ConfidenceBadge confidence={62} />);
  expect(screen.getByText('62%')).toBeInTheDocument();
});

test.each([null, undefined])('missing confidence (%p) reads Unvalidated in caution tone', (value) => {
  const { container } = render(<ConfidenceBadge confidence={value} />);
  const label = screen.getByText('Unvalidated');
  expect(label).toBeInTheDocument();
  expect(label).toHaveClass('toneCaution');
  expect(label).not.toHaveClass('toneDim');
  expect(screen.queryByText('—')).not.toBeInTheDocument();
  expect(screen.getByRole('tooltip')).toHaveTextContent(UNVALIDATED_TOOLTIP);
  expect(container.querySelector('[data-tier="unknown"]')).toBeInTheDocument();
});

test('a caller-supplied title still overrides the Unvalidated tooltip', () => {
  render(<ConfidenceBadge confidence={null} title="custom tip" />);
  expect(screen.getByRole('tooltip')).toHaveTextContent('custom tip');
  expect(screen.getByText('Unvalidated')).toBeInTheDocument();
});

test('applies tier data attribute', () => {
  const { container } = render(<ConfidenceBadge confidence={80} />);
  expect(container.querySelector('[data-tier="high"]')).toBeInTheDocument();
});
