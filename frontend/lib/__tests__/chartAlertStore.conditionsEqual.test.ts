import { conditionsEqual } from '../chartAlertStore';
import type { Condition } from '@/types/alerts';

describe('conditionsEqual deep id stripping', () => {
  it('treats two conditions differing only by top-level id as equal', () => {
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10 }] as Condition[];
    const b = [{ kind: 'price', id: 'x2', operator: '>', value: 10 }] as Condition[];
    expect(conditionsEqual(a, b)).toBe(true);
  });

  it('ignores an id nested inside a condition sub-object', () => {
    // Guards the recursive strip: a future nested-id condition type must still
    // compare equal when only the nested id differs.
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10, meta: { id: 'n1', tag: 't' } }] as unknown as Condition[];
    const b = [{ kind: 'price', id: 'x2', operator: '>', value: 10, meta: { id: 'n2', tag: 't' } }] as unknown as Condition[];
    expect(conditionsEqual(a, b)).toBe(true);
  });

  it('still distinguishes conditions that differ on a real field', () => {
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10 }] as Condition[];
    const b = [{ kind: 'price', id: 'x1', operator: '>', value: 11 }] as Condition[];
    expect(conditionsEqual(a, b)).toBe(false);
  });
});
