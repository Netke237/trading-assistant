import '@testing-library/jest-dom';
import { render, act } from '@testing-library/react';
import { ThemeProvider } from '../index';
import { useThemeStore } from '@/lib/theme';

describe('ThemeProvider — dataset.density synchronization (#370)', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-density');
    useThemeStore.setState({ theme: 'dark', density: 'Comfortable' });
  });

  test('synchronizes density to documentElement dataset on mount', () => {
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.dataset.density).toBe('comfortable');
  });

  test('updates documentElement dataset.density when store density changes', () => {
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );

    expect(document.documentElement.dataset.density).toBe('comfortable');

    act(() => {
      useThemeStore.getState().setDensity('Compact');
    });

    expect(document.documentElement.dataset.density).toBe('compact');

    act(() => {
      useThemeStore.getState().setDensity('Comfortable');
    });

    expect(document.documentElement.dataset.density).toBe('comfortable');
  });
});
