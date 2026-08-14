import { worstStatus } from '@/lib/status';

describe('worstStatus', () => {
  it('ranks REJECT > CAUTION > PENDING > PASS > NO_DATA', () => {
    expect(worstStatus('PASS', 'REJECT')).toBe('REJECT');
    expect(worstStatus('PASS', 'CAUTION')).toBe('CAUTION');
    expect(worstStatus('PENDING', 'PASS')).toBe('PENDING');
    expect(worstStatus('NO_DATA', 'PASS')).toBe('PASS');
  });

  it('ranks NO_DATA below PASS (fallback-only) — intentional, do not "fix" here; see M8 local fix in step-5-vol-events', () => {
    // NO_DATA is only ever returned when none of REJECT/CAUTION/PENDING/PASS
    // are present. riskStore.ts and risk.ts (the only other two callers)
    // never pass NO_DATA, so this ordering is safe for them — a caller that
    // wants "unknown" to be treated as CAUTION-or-worse must map it locally
    // before calling worstStatus, not rely on this function reordering NO_DATA.
    expect(worstStatus('NO_DATA', 'PASS')).toBe('PASS');
  });

  it('falls back to NO_DATA only when no other status is present', () => {
    expect(worstStatus('NO_DATA')).toBe('NO_DATA');
    expect(worstStatus()).toBe('NO_DATA');
  });
});
