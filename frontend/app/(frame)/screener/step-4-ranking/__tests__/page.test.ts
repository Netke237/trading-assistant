import { cardToRow } from '../cardToRow';
import type { ScanResult } from '@/lib/scanStore';

const mockPreviousRun: ScanResult = {
  scan_id: 'REC-20260504-A1B2C3D4',
  timestamp: '2026-05-04T09:30:00',
  rejected: [],
  candidates: [
    {
      symbol: 'AAPL', company: 'Apple Inc.', price: 185.20, direction: 'Bullish', status: 'PASS',
      stockScore: 82, stockConfidence: 'PASS',
      stockBreakdown: { trend: 85, pullback: 80, trigger: 78, event: 90, volatility: 75 },
      contract: 'AAPL|190|2026-06-20|C', contractScore: 76, contractConfidence: 'PASS',
      contractBreakdown: { dteFit: 80, delta: 75, ivAttractiveness: 70, liquidity: 85, spread: 70 },
      contractDetails: { strike: 190, expiry: '2026-06-20', right: 'C', mid: 2.50, delta: 0.45, theta: -0.05, ivRank: 55, dte: 47 },
      entry: { limit: 2.45, maxFill: 2.55, orderType: 'Limit' },
      exit: { invalidation: 179.60, premiumStop: 1.50, timeStopDays: 18, target: 200.00, targets: [{ id: 'tp1', stockPrice: 200.00, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 2.4, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
    },
    {
      symbol: 'MSFT', company: 'Microsoft Corp.', price: 410.50, direction: 'Bullish', status: 'PASS',
      stockScore: 78, stockConfidence: 'PASS',
      stockBreakdown: { trend: 80, pullback: 75, trigger: 82, event: 70, volatility: 80 },
      contract: 'MSFT|420|2026-06-20|C', contractScore: 74, contractConfidence: 'PASS',
      contractBreakdown: { dteFit: 78, delta: 72, ivAttractiveness: 68, liquidity: 82, spread: 68 },
      contractDetails: { strike: 420, expiry: '2026-06-20', right: 'C', mid: 5.20, delta: 0.42, theta: -0.08, ivRank: 48, dte: 47 },
      entry: { limit: 5.10, maxFill: 5.30, orderType: 'Limit' },
      exit: { invalidation: 398.20, premiumStop: 3.12, timeStopDays: 18, target: 443.30, targets: [{ id: 'tp1', stockPrice: 443.30, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 2.1, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
    },
    {
      symbol: 'NVDA', company: 'NVIDIA Corp.', price: 120.30, direction: 'Bullish', status: 'CAUTION',
      stockScore: 65, stockConfidence: 'CAUTION',
      stockBreakdown: { trend: 70, pullback: 60, trigger: 65, event: 55, volatility: 70 },
      contract: 'NVDA|125|2026-06-20|C', contractScore: 62, contractConfidence: 'CAUTION',
      contractBreakdown: { dteFit: 65, delta: 60, ivAttractiveness: 58, liquidity: 70, spread: 55 },
      contractDetails: { strike: 125, expiry: '2026-06-20', right: 'C', mid: 3.80, delta: 0.40, theta: -0.06, ivRank: 62, dte: 47 },
      entry: { limit: 3.70, maxFill: 3.90, orderType: 'Limit' },
      exit: { invalidation: 116.70, premiumStop: 2.28, timeStopDays: 18, target: 129.90, targets: [{ id: 'tp1', stockPrice: 129.90, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 1.8, rrModel: 'BS repriced (IV-derived)', finalStatus: 'CAUTION',
    },
  ],
};

const mockCurrentRun: ScanResult = {
  scan_id: 'REC-20260504-10111213',
  timestamp: '2026-05-04T10:30:00',
  rejected: [],
  candidates: [
    {
      symbol: 'MSFT', company: 'Microsoft Corp.', price: 412.00, direction: 'Bullish', status: 'PASS',
      stockScore: 81, stockConfidence: 'PASS',
      stockBreakdown: { trend: 82, pullback: 78, trigger: 85, event: 72, volatility: 82 },
      contract: 'MSFT|420|2026-06-20|C', contractScore: 78, contractConfidence: 'PASS',
      contractBreakdown: { dteFit: 80, delta: 76, ivAttractiveness: 72, liquidity: 85, spread: 72 },
      contractDetails: { strike: 420, expiry: '2026-06-20', right: 'C', mid: 5.40, delta: 0.43, theta: -0.08, ivRank: 50, dte: 47 },
      entry: { limit: 5.30, maxFill: 5.50, orderType: 'Limit' },
      exit: { invalidation: 399.60, premiumStop: 3.24, timeStopDays: 18, target: 444.90, targets: [{ id: 'tp1', stockPrice: 444.90, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 2.2, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
    },
    {
      symbol: 'AAPL', company: 'Apple Inc.', price: 186.50, direction: 'Bullish', status: 'PASS',
      stockScore: 79, stockConfidence: 'PASS',
      stockBreakdown: { trend: 80, pullback: 78, trigger: 75, event: 88, volatility: 72 },
      contract: 'AAPL|190|2026-06-20|C', contractScore: 74, contractConfidence: 'PASS',
      contractBreakdown: { dteFit: 78, delta: 73, ivAttractiveness: 68, liquidity: 82, spread: 68 },
      contractDetails: { strike: 190, expiry: '2026-06-20', right: 'C', mid: 2.60, delta: 0.46, theta: -0.05, ivRank: 53, dte: 47 },
      entry: { limit: 2.55, maxFill: 2.65, orderType: 'Limit' },
      exit: { invalidation: 180.90, premiumStop: 1.56, timeStopDays: 18, target: 201.40, targets: [{ id: 'tp1', stockPrice: 201.40, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 2.3, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
    },
    {
      symbol: 'AMD', company: 'Advanced Micro Devices', price: 98.40, direction: 'Bullish', status: 'PASS',
      stockScore: 72, stockConfidence: 'PASS',
      stockBreakdown: { trend: 75, pullback: 70, trigger: 72, event: 65, volatility: 78 },
      contract: 'AMD|100|2026-06-20|C', contractScore: 70, contractConfidence: 'PASS',
      contractBreakdown: { dteFit: 72, delta: 68, ivAttractiveness: 65, liquidity: 78, spread: 65 },
      contractDetails: { strike: 100, expiry: '2026-06-20', right: 'C', mid: 2.90, delta: 0.44, theta: -0.05, ivRank: 58, dte: 47 },
      entry: { limit: 2.85, maxFill: 2.95, orderType: 'Limit' },
      exit: { invalidation: 95.40, premiumStop: 1.74, timeStopDays: 18, target: 106.20, targets: [{ id: 'tp1', stockPrice: 106.20, contractsToSell: 1, status: 'PENDING' }] },
      rrRatio: 2.0, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
    },
  ],
};

describe('cardToRow', () => {
  it('computes rankDelta and scoreDelta against previous run', () => {
    const previous = mockPreviousRun;
    const current = mockCurrentRun;

    // Previous run order: AAPL (rank 1, score 82), MSFT (rank 2, score 78), NVDA (rank 3, score 65)
    // Current run order: MSFT (rank 1, score 81), AAPL (rank 2, score 79), AMD (rank 3, score 72)
    const msftCurrent = current.candidates[0];

    const row = cardToRow(msftCurrent, 1, previous, 'Swing (5–15d)');

    // MSFT moved from rank 2 to rank 1 => rankDelta = +1 (improved)
    expect(row.rankDelta).toBe(1);
    // MSFT score changed from 78 to 81 => scoreDelta = +3
    expect(row.scoreDelta).toBe(3);
  });

  it('carries the scan position as rank, the Step 4 default sort key', () => {
    // The table sorts by `rank` by default, so a row without it would sort last
    // and the backend's order (PASS before CAUTION, then score) would be lost.
    const rows = mockCurrentRun.candidates.map((c, i) => cardToRow(c, i + 1, null, 'Swing (5–15d)'));
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3]);
  });

  it('returns zero deltas when no previous run exists', () => {
    const current = mockCurrentRun;
    const row = cardToRow(current.candidates[0], 1, null, 'Swing (5–15d)');

    expect(row.rankDelta).toBe(0);
    expect(row.scoreDelta).toBe(0);
  });

  it('returns zero deltas for a new symbol not in previous run', () => {
    const previous = mockPreviousRun;
    const current = mockCurrentRun;

    // AMD is not in previous run (index 2 => rank 3)
    const amdCurrent = current.candidates[2];
    const row = cardToRow(amdCurrent, 3, previous, 'Swing (5–15d)');

    expect(row.rankDelta).toBe(0);
    expect(row.scoreDelta).toBe(0);
  });

  it('derives horizon from context string', () => {
    const current = mockCurrentRun;

    const swing = cardToRow(current.candidates[0], 1, null, 'Swing (5–15d)');
    expect(swing.horizon).toBe('Swing');

    const position = cardToRow(current.candidates[0], 1, null, 'Position (15–45d)');
    expect(position.horizon).toBe('Position');

    const intraday = cardToRow(current.candidates[0], 1, null, 'Intraday (0–2d)');
    expect(intraday.horizon).toBe('Intraday');

    const custom = cardToRow(current.candidates[0], 1, null, 'Custom (20–30d)');
    expect(custom.horizon).toBe('Custom');
  });

  it('falls back to Swing when context horizon is missing', () => {
    const current = mockCurrentRun;
    const row = cardToRow(current.candidates[0], 1, null, undefined);
    expect(row.horizon).toBe('Swing');
  });

  it('carries confidence and interpretation text into the row', () => {
    const card = { ...mockCurrentRun.candidates[0], confidence: 62, confidenceText: 'Mixed history' };
    const row = cardToRow(card, 1, null, 'Swing (5–15d)');
    expect(row.confidence).toBe(62);
    expect(row.confidenceText).toContain('Mixed');
  });

  it('defaults confidence to null when absent', () => {
    const row = cardToRow(mockCurrentRun.candidates[0], 1, null, 'Swing (5–15d)');
    expect(row.confidence).toBeNull();
  });
});

it('retains the bearish Unvalidated CAUTION verdict for ranking', () => {
  const card = { ...mockCurrentRun.candidates[0], direction: 'Bearish' as const,
    status: 'CAUTION' as const, finalStatus: 'CAUTION' as const };
  const row = cardToRow(card, 1);
  expect(row.direction).toBe('Bearish');
  expect(row.status).toBe('CAUTION');
  expect(row.score).toBe(card.stockScore);
});
