/*
 * Candle fixtures — Phase 5. Procedurally generated OHLCV series per symbol
 * using a seeded RNG so values are stable across hot reloads and server renders.
 */

import type { Candle } from '@/types/chart';

/** Mulberry32 — tiny deterministic PRNG. */
function rng(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6D2B79F5) >>> 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function isoDaysAgo(days: number): string {
  const d = new Date('2026-04-18T00:00:00Z');
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Generate N daily candles ending at the anchor date. Drifts up or down. */
export function makeCandles(seed: number, base: number, bars = 120, drift = 0.0005): Candle[] {
  const rand = rng(seed);
  const out: Candle[] = [];
  let close = base;
  for (let i = bars - 1; i >= 0; i--) {
    const open = close;
    const vol = base * (0.012 + rand() * 0.018);             // 1.2%–3% daily range
    const dir = rand() < 0.53 + drift * 40 ? 1 : -1;         // slight directional bias
    const range = vol * (0.6 + rand() * 0.8);
    const nextClose = Math.max(1, open + dir * range + (rand() - 0.5) * vol * 0.5);
    const high = Math.max(open, nextClose) + rand() * range * 0.4;
    const low  = Math.min(open, nextClose) - rand() * range * 0.4;
    const volume = Math.round(4_000_000 + rand() * 12_000_000);
    out.push({
      time:  isoDaysAgo(i),
      open:  +open.toFixed(2),
      high:  +high.toFixed(2),
      low:   +low.toFixed(2),
      close: +nextClose.toFixed(2),
      volume,
    });
    close = nextClose;
  }
  return out;
}

/** Deterministic seed lookup per symbol. */
const SEEDS: Record<string, { seed: number; base: number; drift: number }> = {
  AAPL: { seed: 11, base: 172, drift:  0.0008 },
  NVDA: { seed: 22, base: 820, drift:  0.0015 },
  MSFT: { seed: 33, base: 395, drift:  0.0006 },
  META: { seed: 44, base: 495, drift:  0.0005 },
  GOOGL:{ seed: 55, base: 148, drift:  0.0004 },
  AMZN: { seed: 66, base: 178, drift:  0.0004 },
  AMD:  { seed: 77, base: 148, drift:  0.0007 },
  TSLA: { seed: 88, base: 190, drift: -0.0010 },
  NFLX: { seed: 99, base: 598, drift:  0.0003 },
  INTC: { seed: 111, base: 40, drift: -0.0006 },
  // Market indices — used on Step 3 Market Regime mini charts.
  SPX:  { seed: 201, base: 5180, drift:  0.0006 },
  NDX:  { seed: 202, base: 18020, drift: 0.0009 },
};

export function candlesFor(symbol: string): Candle[] {
  const cfg = SEEDS[symbol] ?? { seed: 1, base: 100, drift: 0 };
  return makeCandles(cfg.seed, cfg.base, 120, cfg.drift);
}
