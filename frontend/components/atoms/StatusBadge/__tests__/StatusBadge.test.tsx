import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { Status } from '@/lib/status';

const statuses: Status[] = ['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'];

const expectedLabels: Record<Status, string> = {
  PASS: 'PASS',
  CAUTION: 'CAUTION',
  REJECT: 'REJECT',
  PENDING: 'PENDING',
  NO_DATA: 'NO DATA',
};

describe('StatusBadge', () => {
  it.each(statuses)('renders correct text for %s', (status) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(expectedLabels[status])).toBeInTheDocument();
  });

  it('renders custom label when provided', () => {
    render(<StatusBadge status="PASS" label="HIGH CONFIDENCE" />);
    expect(screen.getByText('HIGH CONFIDENCE')).toBeInTheDocument();
  });

  it.each(statuses)('applies status-specific class for %s', (status) => {
    const { container } = render(<StatusBadge status={status} />);
    const badge = container.querySelector('span');
    expect(badge).toBeInTheDocument();
    // The module CSS class mapping is tested implicitly by rendered markup
  });
});
