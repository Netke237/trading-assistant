import React, { useEffect, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CollapsibleSection } from '..';

beforeEach(() => localStorage.clear());

it('keeps legacy children unmounted while collapsed by default', () => {
  render(<CollapsibleSection title="Legacy" storageKey="test:legacy" defaultCollapsed>
    <input aria-label="Legacy child" />
  </CollapsibleSection>);
  expect(screen.queryByLabelText('Legacy child')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button'));
  expect(screen.getByLabelText('Legacy child')).toBeVisible();
  fireEvent.click(screen.getByRole('button'));
  expect(screen.queryByLabelText('Legacy child')).not.toBeInTheDocument();
});

it('retains child state without rerunning mount work when keepMounted is enabled', () => {
  const mounted = jest.fn();
  const unmounted = jest.fn();
  function EvidenceFixture() {
    const [value, setValue] = useState('captured');
    useEffect(() => { mounted(); return unmounted; }, []);
    return <input aria-label="Evidence note" value={value} onChange={event => setValue(event.target.value)} />;
  }
  render(<CollapsibleSection title="Evidence" storageKey="test:evidence" defaultCollapsed keepMounted>
    <EvidenceFixture />
  </CollapsibleSection>);
  const toggle = screen.getByRole('button');
  const input = screen.getByLabelText('Evidence note');
  expect(input).not.toBeVisible();
  fireEvent.click(toggle);
  fireEvent.change(input, { target: { value: 'retained note' } });
  fireEvent.click(toggle);
  expect(input).not.toBeVisible();
  fireEvent.click(toggle);
  expect(screen.getByLabelText('Evidence note')).toBe(input);
  expect(input).toHaveValue('retained note');
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(unmounted).not.toHaveBeenCalled();
});
