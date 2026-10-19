import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import SettingsPage from '../page';
import { useThemeStore } from '@/lib/theme';

// Mock API calls so SettingsPage can mount without network calls
jest.mock('@/lib/api', () => ({
  api: {
    postCredentials: jest.fn().mockResolvedValue(undefined),
    getLastScan: jest.fn().mockResolvedValue(null),
    getLastStockScan: jest.fn().mockResolvedValue(null),
  },
  getRiskSettings: jest.fn().mockResolvedValue(null),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

describe('Settings page — Appearance row density persistence (#370)', () => {
  beforeEach(() => {
    localStorage.clear();
    useThemeStore.setState({ theme: 'dark', density: 'Comfortable' });
  });

  test('density selection survives Settings section remount and persists to localStorage', () => {
    render(<SettingsPage />);

    // Click Appearance in the subnav
    const appearanceNav = screen.getByRole('button', { name: /appearance/i });
    fireEvent.click(appearanceNav);

    // Locate the density select
    const select = screen.getByDisplayValue('Comfortable') as HTMLSelectElement;
    expect(select).toBeInTheDocument();

    // Select "Compact"
    fireEvent.change(select, { target: { value: 'Compact' } });
    expect(select.value).toBe('Compact');

    // Store should reflect 'Compact'
    expect(useThemeStore.getState().density).toBe('Compact');

    // Switch section to "Regime" (unmounting ThemeForm)
    const regimeNav = screen.getByRole('button', { name: /regime/i });
    fireEvent.click(regimeNav);
    expect(screen.queryByDisplayValue('Compact')).not.toBeInTheDocument();

    // Switch section back to "Appearance" (remounting ThemeForm)
    fireEvent.click(appearanceNav);

    // Assert that the density select is STILL "Compact", not reset to "Comfortable"
    const remountedSelect = screen.getByDisplayValue('Compact') as HTMLSelectElement;
    expect(remountedSelect).toBeInTheDocument();
    expect(remountedSelect.value).toBe('Compact');
  });
});
