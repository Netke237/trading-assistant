import { useThemeStore, THEME_STORAGE_KEY, type Density, type Theme } from '@/lib/theme';

describe('theme store (useThemeStore) — persistence and density (#370)', () => {
  beforeEach(() => {
    localStorage.clear();
    useThemeStore.setState({ theme: 'dark', density: 'Comfortable' });
  });

  test('default initial state has dark theme and Comfortable density', () => {
    const state = useThemeStore.getState();
    expect(state.theme).toBe('dark');
    expect(state.density).toBe('Comfortable');
  });

  test('setDensity updates density state and persists to localStorage', () => {
    useThemeStore.getState().setDensity('Compact');
    expect(useThemeStore.getState().density).toBe('Compact');

    // Verify localStorage persistence
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.state.density).toBe('Compact');
    expect(parsed.version).toBe(1);
  });

  test('setTheme and toggle work as expected alongside density', () => {
    useThemeStore.getState().setTheme('light');
    expect(useThemeStore.getState().theme).toBe('light');
    expect(useThemeStore.getState().density).toBe('Comfortable');

    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().theme).toBe('dark');

    useThemeStore.getState().setDensity('Compact');
    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().theme).toBe('light');
    expect(useThemeStore.getState().density).toBe('Compact');
  });

  test('migrate handler upgrades v0 legacy state without density to v1', () => {
    const migrate = (useThemeStore as any).persist.getOptions().migrate;
    expect(migrate).toBeDefined();

    // Legacy payload with theme 'light' and no version (or version 0)
    const legacyState = { theme: 'light' };
    const migrated = migrate(legacyState, 0);

    expect(migrated.theme).toBe('light');
    expect(migrated.density).toBe('Comfortable');
  });

  test('migrate handler preserves valid existing density in v0 or corrupted payload', () => {
    const migrate = (useThemeStore as any).persist.getOptions().migrate;

    // Legacy payload that somehow has density 'Compact'
    const legacyWithDensity = { theme: 'dark', density: 'Compact' };
    const migrated = migrate(legacyWithDensity, 0);

    expect(migrated.theme).toBe('dark');
    expect(migrated.density).toBe('Compact');

    // Null or invalid state safely falls back
    const migratedNull = migrate(null, 0);
    expect(migratedNull.theme).toBe('dark');
    expect(migratedNull.density).toBe('Comfortable');
  });
});
