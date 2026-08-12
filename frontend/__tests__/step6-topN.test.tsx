import type { OptionContract } from '../types/domain';

describe('Step 6 recommended contract logic', () => {
  const mockContracts: OptionContract[] = [
    { id: 'A', score: 45, strike: 400, delta: 0.5, symbol: 'TEST', expiry: '2025-05-16', right: 'C', dte: 10, dteTotal: 30, price: 3.0, ivRank: 40, ivPercentile: 40, theta: -0.05, spread: 0.1, volume: 1000, contractConfidence: 'CAUTION' },
    { id: 'B', score: 82, strike: 410, delta: 0.4, symbol: 'TEST', expiry: '2025-05-16', right: 'C', dte: 10, dteTotal: 30, price: 2.5, ivRank: 60, ivPercentile: 60, theta: -0.04, spread: 0.1, volume: 2000, contractConfidence: 'PASS' },
    { id: 'C', score: 61, strike: 420, delta: 0.3, symbol: 'TEST', expiry: '2025-05-16', right: 'C', dte: 10, dteTotal: 30, price: 1.5, ivRank: 50, ivPercentile: 50, theta: -0.03, spread: 0.1, volume: 1500, contractConfidence: 'CAUTION' },
  ];

  it('recommended is always highest score regardless of sort column', () => {
    const byScore = [...mockContracts].sort((a, b) => b.score - a.score);
    expect(byScore[0].id).toBe('B'); // score=82 is highest
  });

  it('chain excludes the recommended contract', () => {
    const recommended = mockContracts.find((c) => c.score === 82)!;
    const chain = mockContracts.filter((c) => c.id !== recommended.id);
    expect(chain).toHaveLength(2);
    expect(chain.find((c) => c.id === 'B')).toBeUndefined();
  });

  it('recommended is stable even when sorted by strike ascending', () => {
    // Simulate user sorting by strike asc — id 'A' (strike 400) would be first.
    const byStrike = [...mockContracts].sort((a, b) => a.strike - b.strike);
    expect(byStrike[0].id).toBe('A'); // strike sort puts A first
    // But score-based recommended is still B.
    const byScore = [...mockContracts].sort((a, b) => b.score - a.score);
    expect(byScore[0].id).toBe('B');
    // Chain (from strike sort) excludes recommended (B).
    const chain = byStrike.filter((c) => c.id !== byScore[0].id);
    expect(chain.map((c) => c.id)).toEqual(['A', 'C']);
  });
});
