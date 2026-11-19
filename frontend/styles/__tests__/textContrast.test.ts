/**
 * TEXT-CONTRAST-AA (plan docs/superpowers/plans/2026-11-17-text-contrast-aa-plan.md §3.3, §6 T1).
 *
 * Pins styles/tokens.css:
 *  - every text token is a 6-digit hex with WCAG 2.x contrast >= 4.5:1 against --bg-base and
 *    --bg-surface of its own theme block (same luminance formula as scripts/text_contrast.py);
 *  - the exact §3.3 text-token values, so a later edit cannot drift silently;
 *  - every other token keeps its pre-phase (main 8268d4c7) value, and the two --graphic-* greys equal
 *    the old --text-secondary / --text-dim values, so no fill, border or chart series changes colour.
 *
 * Blocks are parsed with the same regex as the script: dark = `[data-theme="dark"] {…}` (the block that
 * `:root,` also selects), light = `[data-theme="light"] {…}`.
 */
import fs from 'fs';
import path from 'path';

const TOKENS_CSS = fs.readFileSync(path.resolve(__dirname, '../tokens.css'), 'utf8');

type Theme = 'dark' | 'light';

function block(selector: string): Record<string, string> {
  const esc = selector.replace(/[[\]"=]/g, (c) => `\\${c}`);
  const m = new RegExp(`${esc}\\s*\\{([\\s\\S]*?)\\}`).exec(TOKENS_CSS);
  if (!m) throw new Error(`block ${selector} not found in tokens.css`);
  const out: Record<string, string> = {};
  for (const d of m[1].matchAll(/(--[\w-]+):\s*([^;]+);/g)) out[d[1]] = d[2].trim();
  return out;
}

const BLOCKS: Record<Theme, Record<string, string>> = {
  dark: block('[data-theme="dark"]'),
  light: block('[data-theme="light"]'),
};

function lin(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}
function luminance(hex: string): number {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const HEX6 = /^#[0-9A-Fa-f]{6}$/;

// §3.3 "Values (after)" — text-only colours.
const TEXT_TOKENS: Record<string, Record<Theme, string>> = {
  '--text-primary': { dark: '#D1D4DC', light: '#131722' },
  '--text-secondary': { dark: '#A3A6B4', light: '#5A6070' },
  '--text-dim': { dark: '#8B8FA1', light: '#626D8B' },
  '--text-pass': { dark: '#26A69A', light: '#167A73' },
  '--text-caution': { dark: '#F59F00', light: '#986207' },
  '--text-reject': { dark: '#FF6B68', light: '#D12C2C' },
  '--text-accent': { dark: '#5885FF', light: '#235DFF' },
  '--text-accent-hover': { dark: '#7A9DFF', light: '#1E53E5' },
  '--text-neutral': { dark: '#7F8DA4', light: '#606F85' },
};

// Old text-grey values (main 8268d4c7), now carried by the non-text grey tokens.
const GRAPHIC_TOKENS: Record<string, Record<Theme, string>> = {
  '--graphic-secondary': { dark: '#787B86', light: '#5A6070' },
  '--graphic-dim': { dark: '#434651', light: '#9BA3B8' },
};

// §3.3 "Unchanged": every other token, copied from tokens.css at main 8268d4c7.
const UNCHANGED: Record<Theme, Record<string, string>> = {
  dark: {
    '--bg-base': '#131722',
    '--bg-surface': '#1E2335',
    '--bg-surface-2': '#252B43',
    '--bg-surface-3': '#2A3152',
    '--border-subtle': '#2A2E42',
    '--border-strong': '#363B54',
    '--pass': '#26A69A',
    '--pass-bg': '#0D201F',
    '--pass-border': '#1A3533',
    '--caution': '#F59F00',
    '--caution-bg': '#1F1A0D',
    '--caution-border': '#352E1A',
    '--reject': '#EF5350',
    '--reject-bg': '#1F0E0D',
    '--reject-border': '#352020',
    '--neutral': '#4A5568',
    '--neutral-bg': '#1A202C',
    '--accent': '#2962FF',
    '--accent-hover': '#1E53E5',
    '--accent-dim': '#142B7A',
    '--accent-text': '#FFFFFF',
    '--space-1': '4px',
    '--space-2': '8px',
    '--space-3': '12px',
    '--space-4': '16px',
    '--space-5': '20px',
    '--space-6': '24px',
    '--space-8': '32px',
    '--space-12': '48px',
    '--radius-sm': '4px',
    '--radius-md': '6px',
    '--radius-lg': '10px',
    '--shadow-elevated': '0 4px 16px rgba(0, 0, 0, 0.5)',
    '--shadow-overlay': '0 4px 16px rgba(0, 0, 0, 0.35)',
    '--shadow-popover': '0 8px 24px rgba(0, 0, 0, 0.35)',
    '--frame-topbar-h': '48px',
    '--frame-navrail-w': '64px',
    '--frame-navrail-w-expanded': '200px',
    '--frame-contextrail-w': '300px',
    '--frame-stepnav-h': '52px',
  },
  light: {
    '--bg-base': '#F0F3FA',
    '--bg-surface': '#FFFFFF',
    '--bg-surface-2': '#F5F7FF',
    '--bg-surface-3': '#EBF0FF',
    '--border-subtle': '#DDE1F0',
    '--border-strong': '#C5CCE6',
    '--pass': '#1A9188',
    '--pass-bg': '#EDF7F6',
    '--pass-border': '#B3E0DC',
    '--caution': '#D4890A',
    '--caution-bg': '#FEF6E6',
    '--caution-border': '#F5D38A',
    '--reject': '#D32F2F',
    '--reject-bg': '#FEECEC',
    '--reject-border': '#F5BCBC',
    '--neutral': '#64748B',
    '--neutral-bg': '#F1F5F9',
    '--accent': '#2962FF',
    '--accent-hover': '#1E53E5',
    '--accent-dim': '#EEF2FF',
    '--accent-text': '#FFFFFF',
    '--shadow-elevated': '0 4px 16px rgba(19, 23, 34, 0.12)',
    '--shadow-overlay': '0 4px 16px rgba(0, 0, 0, 0.12)',
    '--shadow-popover': '0 8px 24px rgba(19, 23, 34, 0.13)',
  },
};

const THEMES: Theme[] = ['dark', 'light'];

describe('tokens.css text contrast (WCAG AA)', () => {
  describe.each(THEMES)('%s theme', (theme) => {
    const v = BLOCKS[theme];

    it.each(Object.keys(TEXT_TOKENS))('%s is a hex with >= 4.5:1 on --bg-base and --bg-surface', (tok) => {
      expect(v[tok]).toMatch(HEX6);
      expect(contrast(v[tok], v['--bg-base'])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(v[tok], v['--bg-surface'])).toBeGreaterThanOrEqual(4.5);
    });

    it.each(Object.keys(TEXT_TOKENS))('%s has its plan §3.3 value', (tok) => {
      expect(v[tok]?.toUpperCase()).toBe(TEXT_TOKENS[tok][theme]);
    });

    it.each(Object.keys(GRAPHIC_TOKENS))('%s keeps the old text-grey value', (tok) => {
      expect(v[tok]?.toUpperCase()).toBe(GRAPHIC_TOKENS[tok][theme]);
    });

    it('every other token keeps its pre-phase value', () => {
      const actual: Record<string, string> = {};
      for (const k of Object.keys(UNCHANGED[theme])) actual[k] = v[k];
      expect(actual).toEqual(UNCHANGED[theme]);
    });

    it('defines no token beyond the pinned, text and graphic sets', () => {
      const expected = [
        ...Object.keys(UNCHANGED[theme]),
        ...Object.keys(TEXT_TOKENS),
        ...Object.keys(GRAPHIC_TOKENS),
      ].sort();
      expect(Object.keys(v).sort()).toEqual(expected);
    });
  });

  it('row-density tokens are unchanged', () => {
    expect(block('[data-density="comfortable"]')).toEqual({ '--table-row-min-height': '44px' });
    expect(block('[data-density="compact"]')).toEqual({ '--table-row-min-height': '32px' });
  });
});
