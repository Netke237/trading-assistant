import React from 'react';
import '@testing-library/jest-dom';
import { render, act } from '@testing-library/react';
import { ThemeProvider } from '../index';
import { useThemeStore, THEME_STORAGE_KEY } from '@/lib/theme';

describe('ThemeProvider cross-tab synchronization (#399)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = 'dark';
    useThemeStore.setState({ theme: 'dark' });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('synchronizes initial theme to document.documentElement.dataset.theme', () => {
    useThemeStore.setState({ theme: 'dark' });
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('updates DOM and store when receiving cross-tab storage event (dark -> light)', () => {
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );
    expect(document.documentElement.dataset.theme).toBe('dark');

    const newThemePayload = JSON.stringify({ state: { theme: 'light' }, version: 0 });
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: newThemePayload,
        })
      );
    });

    expect(useThemeStore.getState().theme).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('updates DOM and store when receiving cross-tab storage event (light -> dark)', () => {
    useThemeStore.setState({ theme: 'light' });
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );
    expect(document.documentElement.dataset.theme).toBe('light');

    const newThemePayload = JSON.stringify({ state: { theme: 'dark' }, version: 0 });
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: newThemePayload,
        })
      );
    });

    expect(useThemeStore.getState().theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('resets theme to default dark when storage is cleared (key is null)', () => {
    useThemeStore.setState({ theme: 'light' });
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );
    expect(document.documentElement.dataset.theme).toBe('light');

    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: null,
          newValue: null,
        })
      );
    });

    expect(useThemeStore.getState().theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('ignores storage events for unrelated keys', () => {
    useThemeStore.setState({ theme: 'dark' });
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );

    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'bamendjou:other-store',
          newValue: JSON.stringify({ state: { theme: 'light' } }),
        })
      );
    });

    expect(useThemeStore.getState().theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('ignores corrupted JSON in storage event without altering state or throwing', () => {
    useThemeStore.setState({ theme: 'dark' });
    render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );

    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: '{malformed:json:',
        })
      );
    });

    expect(useThemeStore.getState().theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('removes storage listener on unmount', () => {
    const { unmount } = render(
      <ThemeProvider>
        <div>Content</div>
      </ThemeProvider>
    );

    unmount();

    // After unmount, dispatching storage event should not mutate DOM theme
    const payload = JSON.stringify({ state: { theme: 'light' }, version: 0 });
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: payload,
        })
      );
    });

    // ThemeProvider is unmounted, so DOM dataset.theme should not have been updated to light
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
