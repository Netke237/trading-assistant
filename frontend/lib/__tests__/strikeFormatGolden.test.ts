/**
 * EXACT-STRIKE invariant I2 — Python/JS parity of the strike text in a
 * contract id. The backend's `format_strike(wire)` and the frontend's
 * `contractId(sym, wire, …)` must put the same text in the strike slot for
 * every wire value the backend emits. The table is the shared golden file the
 * backend pytest also reads; it is read here with `fs`, never copied.
 */
import fs from 'fs';
import path from 'path';
import { contractId } from '@/types/domain';

const GOLDEN = path.resolve(__dirname, '../../../backend/tests/fixtures/strike_format_golden.json');

describe('strike_format_golden.json — contractId strike slot', () => {
  const table = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as { wire: number; text: string }[];

  it('is a non-empty table of {wire: number, text: string}', () => {
    expect(table.length).toBeGreaterThan(0);
    for (const e of table) {
      expect(typeof e.wire).toBe('number');
      expect(typeof e.text).toBe('string');
    }
  });

  it.each(table.map((e) => [e.text, e.wire] as const))('wire for %s puts exactly that text in the id', (text, wire) => {
    const id = contractId('XYZ', wire, '2025-05-16', 'C');
    expect(id.split('|')[1]).toBe(text);
    expect(id).toBe(`XYZ|${text}|2025-05-16|C`);
  });
});
