/*
 * Settings' IV edit is a session OVERRIDE on top of the fetched record
 * (decision DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29): it never quotes a
 * hardcoded number, it survives a re-fetch, and what each input shows is what
 * is applied -- or it is marked as not applied.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { IvThresholdsSection } from '../IvThresholdsSection';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { api } from '@/lib/api';
import { IV_SHIPPED } from '@/lib/testFixtures/thresholds';

jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn() } }));
const get = api.getIvThresholds as jest.Mock;

const input = (h: 'Swing' | 'Position') => screen.getByLabelText(`${h} pass max`) as HTMLInputElement;
const apply = () => screen.getByRole('button', { name: 'Apply thresholds' }) as HTMLButtonElement;
const reset = () => screen.getByRole('button', { name: 'Reset to scoring_rules.yaml' });
const type  = (h: 'Swing' | 'Position', v: string) => fireEvent.change(input(h), { target: { value: v } });
const defaultTags = () => [...document.querySelectorAll('span')]
  .map((s) => s.textContent ?? '').filter((t) => t.startsWith('Default:'));

/** Mount with the fetch answering `answer`, and let that fetch settle. */
async function mount(answer: () => Promise<unknown>) {
  get.mockImplementation(answer);
  await act(async () => { render(<IvThresholdsSection />); });
}
/** A re-fetch (another page mounting), settled. */
async function refetch(answer: () => Promise<unknown>) {
  get.mockImplementation(answer);
  await act(async () => { await useIvThresholdsStore.getState().fetch(); });
}

beforeEach(() => {
  get.mockReset();
  useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
});
afterEach(cleanup);

describe('IvThresholdsSection', () => {
  it('G1: with no record no input shows 34 or 44, Apply is disabled, and a failure is named', async () => {
    await mount(async () => { throw new Error('GET /api/config/iv-thresholds → 500'); });
    expect([input('Swing').value, input('Position').value]).toEqual(['', '']);
    expect(apply().disabled).toBe(true);
    const status = document.querySelector('[data-part="iv-thresholds-status"]');
    expect(status?.getAttribute('data-status')).toBe('failed');
    expect(status?.textContent).toContain('GET /api/config/iv-thresholds → 500');
    expect(document.body.textContent).not.toMatch(/\b(34|44)\b/);
  });

  it('G2: Apply writes overrides and leaves the fetched record untouched', async () => {
    await mount(async () => IV_SHIPPED);
    expect([input('Swing').value, input('Position').value]).toEqual(['34', '44']);
    type('Swing', '50');
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides).toEqual({ Swing: { abs_pass_max: 50 } });
    expect(useIvThresholdsStore.getState().thresholds).toEqual(IV_SHIPPED);
  });

  it('G3: a re-fetch after Apply keeps the input value and the override', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', '50');
    fireEvent.click(apply());
    await refetch(async () => IV_SHIPPED);
    expect(input('Swing').value).toBe('50');
    expect(useIvThresholdsStore.getState().overrides).toEqual({ Swing: { abs_pass_max: 50 } });
  });

  it('G3b: an accepted field shows the value written, not its raw text', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', ' 050 ');
    fireEvent.click(apply());
    expect(input('Swing').value).toBe('50');
  });

  it('G4: Reset clears the override and shows the YAML value again', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', '50');
    fireEvent.click(apply());
    fireEvent.click(reset());
    expect(useIvThresholdsStore.getState().overrides).toEqual({});
    expect(input('Swing').value).toBe('34');
  });

  it('G4b: Reset of a typed, never-applied value shows the YAML value (the seed did not change)', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', '60');
    fireEvent.click(reset());
    expect(input('Swing').value).toBe('34');
    // ...and a later Apply writes nothing: the field is no longer dirty.
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides).toEqual({});
  });

  it('G5: an out-of-range value is refused, stays refused, and a valid field beside it is applied', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', '150');
    type('Position', '60');
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides).toEqual({ Position: { abs_pass_max: 60 } });
    expect(document.querySelector('[data-refused="Swing"]')).not.toBeNull();
    expect(document.querySelector('[data-refused="Position"]')).toBeNull();
    expect(input('Swing').value).toBe('150');
    // A second Apply still refuses it and still says so.
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides).toEqual({ Position: { abs_pass_max: 60 } });
    expect(document.querySelector('[data-refused="Swing"]')).not.toBeNull();
    expect(input('Swing').value).toBe('150');
  });

  it.each([['0'], ['101'], ['abc'], ['']])('G5b: refuses %j', async (v) => {
    await mount(async () => IV_SHIPPED);
    type('Swing', v);
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides).toEqual({});
    expect(document.querySelector('[data-refused="Swing"]')).not.toBeNull();
  });

  it('G6: editing only Swing never freezes Position; a later YAML change reaches Position', async () => {
    await mount(async () => IV_SHIPPED);
    type('Swing', '50');
    fireEvent.click(apply());
    expect(useIvThresholdsStore.getState().overrides.Position).toBeUndefined();
    const moved = { ...IV_SHIPPED, Position: { ...IV_SHIPPED.Position, abs_pass_max: 48 } };
    await refetch(async () => moved);
    expect(input('Position').value).toBe('48');
    expect(input('Swing').value).toBe('50');
  });

  it('G7: no Default tag quotes 34/44 without a record; with one, each tag is the fetched value', async () => {
    await mount(() => new Promise(() => {}));   // still loading
    expect(defaultTags()).toEqual([]);
    cleanup();
    const other = {
      ...IV_SHIPPED,
      Swing:    { ...IV_SHIPPED.Swing,    abs_pass_max: 31 },
      Position: { ...IV_SHIPPED.Position, abs_pass_max: 41 },
    };
    await mount(async () => other);
    expect(defaultTags()).toEqual(['Default: 31', 'Default: 41']);
  });
});
