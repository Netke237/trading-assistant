import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import { TableRow } from '../index';
import { useThemeStore } from '@/lib/theme';

describe('TableRow — row density rendering (#370)', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'dark', density: 'Comfortable' });
  });

  test('renders with data-density="comfortable" by default', () => {
    render(
      <TableRow status="PASS" columns="100px 1fr">
        <div>Cell 1</div>
        <div>Cell 2</div>
      </TableRow>
    );

    const row = screen.getByRole('row');
    expect(row).toHaveAttribute('data-density', 'comfortable');
    expect(row).toHaveAttribute('data-status', 'PASS');
  });

  test('renders with data-density="compact" when store density is Compact', () => {
    act(() => {
      useThemeStore.getState().setDensity('Compact');
    });

    render(
      <TableRow status="CAUTION" columns="100px 1fr">
        <div>Cell 1</div>
        <div>Cell 2</div>
      </TableRow>
    );

    const row = screen.getByRole('row');
    expect(row).toHaveAttribute('data-density', 'compact');
    expect(row).toHaveAttribute('data-status', 'CAUTION');
  });

  test('updates data-density dynamically when density changes in store', () => {
    const { rerender } = render(
      <TableRow status="PASS" columns="100px 1fr">
        <div>Cell 1</div>
        <div>Cell 2</div>
      </TableRow>
    );

    const row = screen.getByRole('row');
    expect(row).toHaveAttribute('data-density', 'comfortable');

    act(() => {
      useThemeStore.getState().setDensity('Compact');
    });

    expect(row).toHaveAttribute('data-density', 'compact');
  });
});
