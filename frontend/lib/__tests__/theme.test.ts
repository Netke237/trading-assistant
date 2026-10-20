import {
  useThemeStore,
  parseTheme,
  syncThemeFromStorage,
  THEME_STORAGE_KEY,
  type Density,
  type Theme,
} from '@/lib/theme';

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

describe('theme.ts unit tests (#399)', () => {
  beforeEach(() => {
    localStorage.clear();
    useThemeStore.setState({ theme: 'dark', density: 'Comfortable' });
  });

  describe('parseTheme', () => {
    it('parses valid light theme state', () => {
      const raw = JSON.stringify({ state: { theme: 'light' }, version: 0 });
      expect(parseTheme(raw)).toBe('light');
    });

    it('parses valid dark theme state', () => {
      const raw = JSON.stringify({ state: { theme: 'dark' }, version: 0 });
      expect(parseTheme(raw)).toBe('dark');
    });

    it('returns null on invalid JSON', () => {
      expect(parseTheme('{broken-json')).toBeNull();
    });

    it('returns null on null, undefined, or empty string', () => {
      expect(parseTheme(null)).toBeNull();
      expect(parseTheme(undefined)).toBeNull();
      expect(parseTheme('')).toBeNull();
    });

    it('returns null on unsupported or unexpected theme strings', () => {
      const raw = JSON.stringify({ state: { theme: 'solarized' } });
      expect(parseTheme(raw)).toBeNull();
    });

    it('returns null when state or theme property is missing', () => {
      expect(parseTheme(JSON.stringify({}))).toBeNull();
      expect(parseTheme(JSON.stringify({ state: {} }))).toBeNull();
      expect(parseTheme(JSON.stringify({ state: { theme: 123 } }))).toBeNull();
    });
  });

  describe('syncThemeFromStorage', () => {
    it('updates store to light when raw serialized light state is provided', () => {
      useThemeStore.setState({ theme: 'dark' });
      const raw = JSON.stringify({ state: { theme: 'light' }, version: 0 });
      syncThemeFromStorage(raw);
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('updates store to dark when raw serialized dark state is provided', () => {
      useThemeStore.setState({ theme: 'light' });
      const raw = JSON.stringify({ state: { theme: 'dark' }, version: 0 });
      syncThemeFromStorage(raw);
      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('reads from localStorage when raw argument is omitted', () => {
      useThemeStore.setState({ theme: 'dark' });
      localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ state: { theme: 'light' }, version: 0 }));
      syncThemeFromStorage();
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('resets to default dark when raw is null (storage cleared or key deleted)', () => {
      useThemeStore.setState({ theme: 'light' });
      syncThemeFromStorage(null);
      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('preserves current state when raw is corrupted JSON (does not alter or throw)', () => {
      useThemeStore.setState({ theme: 'light' });
      syncThemeFromStorage('{bad-json-payload');
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('preserves current state when raw contains invalid theme value', () => {
      useThemeStore.setState({ theme: 'light' });
      syncThemeFromStorage(JSON.stringify({ state: { theme: 'unknown' } }));
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('is a no-op when target theme already matches current store theme', () => {
      useThemeStore.setState({ theme: 'dark' });
      syncThemeFromStorage(JSON.stringify({ state: { theme: 'dark' }, version: 0 }));
      expect(useThemeStore.getState().theme).toBe('dark');
    });
  });
});
