import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { ConfidenceBadge } from '../index';

test('renders percent and dash for null', () => {
  const { rerender } = render(<ConfidenceBadge confidence={62} />);
  expect(screen.getByText('62%')).toBeInTheDocument();
  rerender(<ConfidenceBadge confidence={null} />);
  expect(screen.getByText('—')).toBeInTheDocument();
});

test('applies tier data attribute', () => {
  const { container } = render(<ConfidenceBadge confidence={80} />);
  expect(container.querySelector('[data-tier="high"]')).toBeInTheDocument();
});
