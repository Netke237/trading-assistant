import { buildActionItems, type EpisodesInput } from '@/lib/actionNeeded';
import { episodeKey } from '@/lib/alertEpisodes';
import type { AlertEpisode } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../test-utils/portfolioFixture20261117';

// PORTFOLIO-ALERT-ACTION T4 (#672) — the pure builder behind "Action needed".

const NOW = new Date('2026-11-27T12:00:00Z');
const OPTS = { premiumStopPct: 0.6, now: NOW };

const BMY_SENTENCE =
  'BMY 67C · 19 Mar 27: stop breached. Underlying $60.95 is below your stop $64.13 (−5.2%). ' +
  'The option has had no quote since the last sync, so its P&L and risk are unknown.';

function bmy(over: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return { ...portfolio20261117()[2], stop: 64.13, structuralStop: null, targets: [{ stockPrice: 70 } as never], ...over };
}

function ep(recId: string, alertType: string, startedAt: string, truncated = false, lastFiredAt = '2026-11-27T08:00:00+00:00'): AlertEpisode {
  return { recId, symbol: recId, alertType, startedAt, lastFiredAt, fireCount: 3, startTruncated: truncated };
}

function loaded(...eps: AlertEpisode[]): EpisodesInput {
  return {
    status: 'loaded',
    gapHours: 72,
    byKey: Object.fromEntries(eps.map((e) => [episodeKey(e.recId, e.alertType), e])),
  };
}

function stock(symbol: string, over: Partial<PortfolioPosition>): PortfolioPosition {
  return {
    symbol, contract: `${symbol}|STOCK`, direction: 'Bullish',
    entryDate: '2026-11-10', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 100, currentPrice: 100, currentStockPrice: 100,
    pnlDollar: 0, pnlPct: 0, stop: null, targets: [], status: 'PENDING', contracts: 1,
    recId: `REC-${symbol}`, ...over,
  } as PortfolioPosition;
}

function option(symbol: string, over: Partial<PortfolioPosition>): PortfolioPosition {
  return {
    symbol, contract: `${symbol}|50|2027-06-17|C`, direction: 'Bullish',
    entryDate: '2026-11-10', expiry: '2027-06-17', dteRemaining: 200, dteTotal: 219,
    entryPrice: 5, currentPrice: 5, currentStockPrice: 55,
    pnlDollar: 0, pnlPct: 0, stop: null, targets: [], status: 'PENDING', contracts: 1,
    recId: `REC-${symbol}`, ...over,
  } as PortfolioPosition;
}

describe('buildActionItems', () => {
  it('BMY stop: 9 days since 18 Nov from a non-truncated episode, banner sentence kept', () => {
    const items = buildActionItems([bmy()], loaded(ep('REC-BMY', 'STOP_REACHED', '2026-11-18T12:00:00+00:00')), OPTS);
    expect(items).toHaveLength(1);
    expect(items[0].symbol).toBe('BMY');
    expect(items[0].contract).toBe('BMY|67|2027-03-19|C');
    expect(items[0].breachSentence).toBe(BMY_SENTENCE);
    expect(items[0].entries).toEqual([
      expect.objectContaining({ alertType: 'STOP_REACHED', label: 'Stop hit', detail: '9 days, since 18 Nov' }),
    ]);
  });

  it('BMY since 18 Oct under 30-day retention: "30+ days, since before 28 Oct", never an exact date', () => {
    const items = buildActionItems([bmy()], loaded(ep('REC-BMY', 'STOP_REACHED', '2026-10-28T12:00:00+00:00', true)), OPTS);
    expect(items[0].entries[0].detail).toBe('30+ days, since before 28 Oct');
    expect(items[0].entries[0].detail).not.toMatch(/since 2?8 Oct/);
  });

  it('structural breach: structural sentence and label', () => {
    const [cmg] = portfolio20261117();
    const items = buildActionItems([{ ...cmg, structuralStop: 37 }], loaded(), OPTS);
    expect(items[0].breachSentence).toBe(
      'CMG 40C · 17 Jun 27: structural stop breached. Underlying $36.06 is below your structural stop $37.00 (−2.6%).',
    );
    expect(items[0].entries.map((e) => e.label)).toEqual(['Structural level hit']);
  });

  it('TP_HIT + TIME_STOP on one option: two entries, no sentence', () => {
    const p = option('XYZ', { dteRemaining: 2, targets: [{ stockPrice: 50 } as never] });
    const items = buildActionItems([p], loaded(ep('REC-XYZ', 'TP_HIT', '2026-11-25T12:00:00+00:00')), OPTS);
    expect(items).toHaveLength(1);
    expect(items[0].breachSentence).toBeNull();
    const byType = Object.fromEntries(items[0].entries.map((e) => [e.alertType, e]));
    expect(byType.TP_HIT).toEqual(expect.objectContaining({ label: 'Target reached', detail: '2 days, since 25 Nov' }));
    expect(byType.TIME_STOP).toEqual(expect.objectContaining({ label: 'Time stop hit', detail: 'new — not yet logged' }));
  });

  it('premium-stop label by side', () => {
    const items = buildActionItems([
      stock('LNG', { entryPrice: 100, currentPrice: 30, currentStockPrice: 30 }),
      stock('SHT', { direction: 'Bearish', entryPrice: 100, currentPrice: 170, currentStockPrice: 170 }),
      option('OPT', { entryPrice: 5, currentPrice: 1 }),
    ], loaded(), OPTS);
    const label = (s: string) => items.find((i) => i.symbol === s)!.entries.find((e) => e.alertType === 'PREMIUM_STOP')!.label;
    expect(label('LNG')).toBe('Stock stop hit');
    expect(label('SHT')).toBe('Stock stop hit (short)');
    expect(label('OPT')).toBe('Premium stop hit');
    // A premium stop alone is not a stop/structural breach: no banner sentence.
    expect(items.find((i) => i.symbol === 'OPT')!.breachSentence).toBeNull();
  });

  it('no current episode → "new — not yet logged"; an episode past the gap is not current', () => {
    const stale = ep('REC-BMY', 'STOP_REACHED', '2026-11-01T12:00:00+00:00', false, '2026-11-20T12:00:00+00:00');
    expect(buildActionItems([bmy()], loaded(), OPTS)[0].entries[0].detail).toBe('new — not yet logged');
    expect(buildActionItems([bmy()], loaded(stale), OPTS)[0].entries[0].detail).toBe('new — not yet logged');
  });

  it('episodes fetch failed → "duration unavailable" (no number, no date)', () => {
    const items = buildActionItems([bmy()], { status: 'failed' }, OPTS);
    expect(items[0].entries[0].detail).toBe('duration unavailable');
    expect(items[0].breachSentence).toBe(BMY_SENTENCE);
  });

  it('episodes not loaded yet → no duration claimed', () => {
    const items = buildActionItems([bmy()], { status: 'pending' }, OPTS);
    expect(items[0].entries[0].detail).toBe('duration loading…');
  });

  it('sorting: stop-type first, then longest active, then symbol', () => {
    const positions = [
      option('EEE', { dteRemaining: 2 }),                                   // TIME_STOP, no episode
      option('DDD', { targets: [{ stockPrice: 50 } as never] }),            // TP 20 d
      option('AAA', { targets: [{ stockPrice: 50 } as never] }),            // TP 20 d
      option('BBB', { stop: 60 }),                                           // stop 2 d
      option('CCC', { stop: 60 }),                                           // stop 9 d
    ];
    const items = buildActionItems(positions, loaded(
      ep('REC-DDD', 'TP_HIT', '2026-11-07T12:00:00+00:00'),
      ep('REC-AAA', 'TP_HIT', '2026-11-07T12:00:00+00:00'),
      ep('REC-BBB', 'STOP_REACHED', '2026-11-25T12:00:00+00:00'),
      ep('REC-CCC', 'STOP_REACHED', '2026-11-18T12:00:00+00:00'),
    ), OPTS);
    expect(items.map((i) => i.symbol)).toEqual(['CCC', 'BBB', 'AAA', 'DDD', 'EEE']);
  });

  it('per-position mute is ignored: a muted stop still needs action', () => {
    const items = buildActionItems([bmy({ alertOverrides: { STOP_REACHED: false } })], loaded(), OPTS);
    expect(items).toHaveLength(1);
    expect(items[0].breachSentence).toBe(BMY_SENTENCE);
  });

  it('EVENT_RISK alone and a quiet position produce no item', () => {
    const [cmg, nclh] = portfolio20261117();
    expect(buildActionItems([cmg, { ...nclh, nextEventDays: 1, nextEventLabel: 'Earnings' } as PortfolioPosition], loaded(), OPTS)).toEqual([]);
  });
});
