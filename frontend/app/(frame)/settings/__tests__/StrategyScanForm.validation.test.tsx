import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import SettingsPage from '../page';
import { useScanParamsStore } from '@/lib/scanParamsStore';

// Mock Next.js navigation if needed
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/settings',
}));

describe('StrategyScanForm — validation and draft error handling (#373)', () => {
  beforeEach(() => {
    useScanParamsStore.getState().resetToDefaults();
  });

  it('rejects typing 0 into pullback tolerance, displays accessible alert, and preserves store', () => {
    render(<SettingsPage />);

    // Switch to Strategy scan tab
    const strategyTab = screen.getByRole('button', { name: /Strategy scan/i });
    fireEvent.click(strategyTab);

    const pullbackInput = screen.getByLabelText('Pullback tolerance') as HTMLInputElement;

    // Type 0 into pullback tolerance
    fireEvent.change(pullbackInput, { target: { value: '0' } });

    // Draft reflects what user typed
    expect(pullbackInput.value).toBe('0');

    // Accessible error is visible
    expect(pullbackInput).toHaveAttribute('aria-invalid', 'true');
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('between 0.5% and 15%');

    // Store is NOT updated to 0 (remains null / follow profile)
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBeNull();
  });

  it('rejects typing 0 into MA crossover lookback, displays accessible alert, and preserves store', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const crossoverInput = screen.getByLabelText('MA crossover lookback') as HTMLInputElement;
    fireEvent.change(crossoverInput, { target: { value: '0' } });

    expect(crossoverInput.value).toBe('0');
    expect(crossoverInput).toHaveAttribute('aria-invalid', 'true');
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('between 1 and 30 bars');
    expect(useScanParamsStore.getState().maCrossoverLookback).toBeNull();
  });

  it('rejects typing 1.0 into breakout multiplier (strict lower bound > 1.0)', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const breakoutInput = screen.getByLabelText('Breakout volume multiplier') as HTMLInputElement;
    fireEvent.change(breakoutInput, { target: { value: '1.0' } });

    expect(breakoutInput.value).toBe('1.0');
    expect(breakoutInput).toHaveAttribute('aria-invalid', 'true');
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('greater than 1.0× and at most 3.0×');
    expect(useScanParamsStore.getState().breakoutVolumeMult).toBeNull();
  });

  it('accepts valid inputs, clears error, and commits exact fractional value immediately', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const pullbackInput = screen.getByLabelText('Pullback tolerance') as HTMLInputElement;
    fireEvent.change(pullbackInput, { target: { value: '8.25' } });

    expect(pullbackInput).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByRole('alert')).toBeNull();
    // 8.25% committed as exact fraction 0.0825
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.0825);
  });

  it('clicking clear writes null to store and removes draft error', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const pullbackInput = screen.getByLabelText('Pullback tolerance') as HTMLInputElement;
    fireEvent.change(pullbackInput, { target: { value: '0' } });
    expect(screen.getByRole('alert')).toBeInTheDocument();

    const clearBtn = screen.getByRole('button', { name: 'Clear Pullback tolerance' });
    fireEvent.click(clearBtn);

    expect(pullbackInput.value).toBe('');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBeNull();
  });

  it('displays initial field error for hydrated schema-invalid legacy value (pullback = 0)', () => {
    useScanParamsStore.setState({ pullbackTolerancePct: 0 });
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('Invalid stored pullback tolerance');
  });

  it('does NOT reject schema-valid legacy value exceeding UI max (e.g. breakout 4.0)', () => {
    useScanParamsStore.setState({ breakoutVolumeMult: 4.0 });
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Strategy scan/i }));

    const breakoutInput = screen.getByLabelText('Breakout volume multiplier') as HTMLInputElement;
    expect(breakoutInput.value).toBe('4');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(useScanParamsStore.getState().breakoutVolumeMult).toBe(4.0);
  });
});
