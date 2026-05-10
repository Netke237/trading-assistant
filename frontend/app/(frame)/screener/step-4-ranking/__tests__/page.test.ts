import { cardToRow } from '../cardToRow';
import { mockPreviousRun, mockCurrentRun } from '@/mocks/scan';

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
});
