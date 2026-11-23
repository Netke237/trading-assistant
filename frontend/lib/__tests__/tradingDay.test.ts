import { etDateIso, lastTradingDayEt } from '../tradingDay';

const d = (iso: string) => new Date(iso);

describe('etDateIso', () => {
  it('derives the ET calendar date, not the UTC one', () => {
    // 2026-11-21 02:00Z is still the evening of 20 Nov in New York (EST, UTC-5).
    expect(etDateIso(d('2026-11-21T02:00:00Z'))).toBe('2026-11-20');
  });
  it('gives the same ET date for the same instant regardless of host zone', () => {
    // 23:30 UTC and 00:30 CET next day are the same instant.
    expect(etDateIso(d('2026-11-20T23:30:00Z'))).toBe(etDateIso(d('2026-11-21T00:30:00+01:00')));
  });
});

describe('lastTradingDayEt', () => {
  it('Friday 16:00 ET stays Friday', () => {
    expect(lastTradingDayEt(d('2026-11-20T21:00:00Z'))).toBe('2026-11-20');
  });
  it('Saturday steps back to Friday', () => {
    expect(lastTradingDayEt(d('2026-11-21T17:00:00Z'))).toBe('2026-11-20');
  });
  it('Sunday steps back to Friday', () => {
    expect(lastTradingDayEt(d('2026-11-22T17:00:00Z'))).toBe('2026-11-20');
  });
  it('Monday 09:29 ET steps back to Friday', () => {
    expect(lastTradingDayEt(d('2026-11-23T14:29:00Z'))).toBe('2026-11-20');
  });
  it('Monday 09:30 ET is Monday', () => {
    expect(lastTradingDayEt(d('2026-11-23T14:30:00Z'))).toBe('2026-11-23');
  });
  it('Tuesday 09:29 ET steps back one weekday to Monday', () => {
    expect(lastTradingDayEt(d('2026-11-24T14:29:00Z'))).toBe('2026-11-23');
  });
  it('DST start day 2026-03-08 (Sunday) steps back to Friday 2026-03-06', () => {
    expect(lastTradingDayEt(d('2026-03-08T12:00:00Z'))).toBe('2026-03-06');
  });
  it('Monday after DST start: 09:30 EDT is 13:30Z', () => {
    expect(lastTradingDayEt(d('2026-03-09T13:29:00Z'))).toBe('2026-03-06');
    expect(lastTradingDayEt(d('2026-03-09T13:30:00Z'))).toBe('2026-03-09');
  });
  it('DST end day 2026-11-01 (Sunday) steps back to Friday 2026-10-30', () => {
    expect(lastTradingDayEt(d('2026-11-01T12:00:00Z'))).toBe('2026-10-30');
  });
  it('Monday after DST end: 09:30 EST is 14:30Z', () => {
    expect(lastTradingDayEt(d('2026-11-02T14:29:00Z'))).toBe('2026-10-30');
    expect(lastTradingDayEt(d('2026-11-02T14:30:00Z'))).toBe('2026-11-02');
  });
  it('UTC and CET representations of one instant give the same answer', () => {
    expect(lastTradingDayEt(d('2026-11-23T14:30:00Z'))).toBe(lastTradingDayEt(d('2026-11-23T15:30:00+01:00')));
  });
});
