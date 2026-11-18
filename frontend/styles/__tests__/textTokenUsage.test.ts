/**
 * TEXT-CONTRAST-AA usage guard (plan docs/superpowers/plans/2026-11-17-text-contrast-aa-plan.md §3.4, §5, §6).
 *
 * Grey rule: --text-secondary / --text-dim are text colours (raised to WCAG AA). A non-text use — fill,
 * border, outline, meter bar, chart series — must read --graphic-secondary / --graphic-dim instead, which
 * keep the old grey values, so raising the text greys never changes a fill, line or bar.
 *  - CSS: no declaration whose property is not exactly `color` references var(--text-secondary) or
 *    var(--text-dim). Each line is split on `;` / `{`; the property is the text before the last `:` of
 *    the declaration (as scripts/text_contrast.py `usages` does).
 *  - TS/TSX: no token('--text-secondary') / token('--text-dim') read except the chart axis-label colours
 *    (lightweight-charts `layout.textColor`), which are text and follow the new grey on purpose (§5.3).
 *    They are allowlisted by file path + the identifier the read is assigned to.
 *
 * Walks frontend/ (.css, .ts, .tsx), skipping node_modules, .next, coverage, __tests__, __mocks__ and
 * styles/tokens.css, and comment lines (starting with `*`, `//` or `/*`).
 */
import fs from 'fs';
import path from 'path';

const FRONTEND = path.resolve(__dirname, '../..');
const SKIP_DIRS = new Set(['node_modules', '.next', 'coverage', '__tests__', '__mocks__']);
const TOKENS_REL = 'styles/tokens.css';

interface SourceLine {
  rel: string;
  lineNo: number;
  text: string;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.isDirectory()) {
      if (!SKIP_DIRS.has(ent.name)) walk(path.join(dir, ent.name), out);
    } else if (/\.(css|tsx?)$/.test(ent.name) && !ent.name.endsWith('.d.ts')) {
      out.push(path.join(dir, ent.name));
    }
  }
  return out;
}

function sourceLines(ext: RegExp): SourceLine[] {
  const lines: SourceLine[] = [];
  for (const file of walk(FRONTEND)) {
    const rel = path.relative(FRONTEND, file).split(path.sep).join('/');
    if (rel === TOKENS_REL || !ext.test(rel)) continue;
    fs.readFileSync(file, 'utf8')
      .split(/\r?\n/)
      .forEach((text, i) => {
        const t = text.trimStart();
        if (t.startsWith('*') || t.startsWith('//') || t.startsWith('/*')) return;
        lines.push({ rel, lineNo: i + 1, text });
      });
  }
  return lines;
}

/** Property of the CSS declaration that contains the text before a match, or '?' if none. */
function cssProperty(before: string): string {
  const decl = before.split(';').pop()!.split('{').pop()!;
  const m = /([-\w]+)\s*:[^:]*$/.exec(decl);
  return m ? m[1].trim().toLowerCase() : '?';
}

// Chart axis-label colours (lightweight-charts `layout.textColor`, plan §5.3): text, keep --text-secondary.
const TSX_GREY_TEXT_ALLOW = new Set([
  'components/organisms/CandlestickChart/index.tsx|textDim|--text-secondary',
  'components/organisms/ChartPane/index.tsx|textDim|--text-secondary',
  'components/organisms/PnlChart/index.tsx|textDim|--text-secondary',
  'components/organisms/EarningsChart/index.tsx|textColor|--text-secondary',
  'components/organisms/CandidateBacktestWorkspace/index.tsx|text|--text-secondary',
]);

describe('text token usage guard', () => {
  it('grey rule (CSS): var(--text-secondary|--text-dim) only in `color:` declarations', () => {
    const offenders: string[] = [];
    const re = /var\(\s*(--text-(?:secondary|dim))\s*\)/g;
    for (const { rel, lineNo, text } of sourceLines(/\.css$/)) {
      for (const m of text.matchAll(re)) {
        const prop = cssProperty(text.slice(0, m.index));
        if (prop !== 'color') offenders.push(`${rel}:${lineNo} ${prop}: ${m[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("grey rule (TS/TSX): token('--text-secondary|--text-dim') only for chart axis-label text", () => {
    const offenders: string[] = [];
    const re = /token\(\s*['"](--text-(?:secondary|dim))['"]\s*\)/g;
    for (const { rel, lineNo, text } of sourceLines(/\.tsx?$/)) {
      for (const m of text.matchAll(re)) {
        const km = /([A-Za-z]+)\s*[:=]\s*[^:=,{]*$/.exec(text.slice(0, m.index));
        const name = km ? km[1] : '?';
        if (!TSX_GREY_TEXT_ALLOW.has(`${rel}|${name}|${m[1]}`)) offenders.push(`${rel}:${lineNo} ${name} = ${m[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('the TSX allowlist has no stale entries', () => {
    const seen = new Set<string>();
    const re = /token\(\s*['"](--text-(?:secondary|dim))['"]\s*\)/g;
    for (const { rel, text } of sourceLines(/\.tsx?$/)) {
      for (const m of text.matchAll(re)) {
        const km = /([A-Za-z]+)\s*[:=]\s*[^:=,{]*$/.exec(text.slice(0, m.index));
        seen.add(`${rel}|${km ? km[1] : '?'}|${m[1]}`);
      }
    }
    expect([...TSX_GREY_TEXT_ALLOW].filter((k) => !seen.has(k))).toEqual([]);
  });
});
