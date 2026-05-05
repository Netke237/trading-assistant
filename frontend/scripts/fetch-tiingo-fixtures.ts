/**
 * Fetch Tiingo historical fixtures helper.
 * Run with: npx tsx scripts/fetch-tiingo-fixtures.ts
 * Requires TIINGO_API_TOKEN environment variable.
 */

import * as fs from 'fs';
import * as path from 'path';

const TIINGO_API_TOKEN = process.env.TIINGO_API_TOKEN;
const SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'SPY', 'SPX', 'NDX'];
const FIXTURES_DIR = path.join(__dirname, '..', 'backend', 'tests', 'fixtures');

// Date range: last 365 days
const endDate = new Date();
const startDate = new Date();
startDate.setDate(startDate.getDate() - 365);

function formatDate(d: Date): string {
  return d.toISOString().split('T')[0];
}

interface TiingoBar {
  date: string;
  adjOpen: number;
  adjHigh: number;
  adjLow: number;
  adjClose: number;
  adjVolume: number;
}

interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

async function fetchTiingo(symbol: string): Promise<Candle[]> {
  const url = new URL(`https://api.tiingo.com/tiingo/daily/${symbol}/prices`);
  url.searchParams.set('startDate', formatDate(startDate));
  url.searchParams.set('endDate', formatDate(endDate));
  url.searchParams.set('resampleFreq', 'daily');

  const response = await fetch(url.toString(), {
    headers: {
      Authorization: `Token ${TIINGO_API_TOKEN}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Tiingo API error for ${symbol}: ${response.status} ${response.statusText}`);
  }

  const data = (await response.json()) as TiingoBar[];

  return data.map((bar) => ({
    time: bar.date.slice(0, 10),
    open: Math.round(bar.adjOpen * 100) / 100,
    high: Math.round(bar.adjHigh * 100) / 100,
    low: Math.round(bar.adjLow * 100) / 100,
    close: Math.round(bar.adjClose * 100) / 100,
    volume: Math.round(bar.adjVolume),
  }));
}

async function main(): Promise<void> {
  if (!TIINGO_API_TOKEN) {
    console.error('Error: TIINGO_API_TOKEN environment variable is required');
    process.exit(1);
  }

  // Ensure fixtures directory exists
  if (!fs.existsSync(FIXTURES_DIR)) {
    fs.mkdirSync(FIXTURES_DIR, { recursive: true });
  }

  console.log(`Fetching Tiingo data for ${SYMBOLS.join(', ')}...`);
  console.log(`Date range: ${formatDate(startDate)} to ${formatDate(endDate)}`);

  for (const symbol of SYMBOLS) {
    try {
      console.log(`Fetching ${symbol}...`);
      const candles = await fetchTiingo(symbol);
      const outputPath = path.join(FIXTURES_DIR, `${symbol}_candles.json`);
      fs.writeFileSync(outputPath, JSON.stringify(candles, null, 2));
      console.log(`  ✓ ${candles.length} bars written to ${outputPath}`);
    } catch (error) {
      console.error(`  ✗ Failed to fetch ${symbol}:`, error instanceof Error ? error.message : error);
    }
  }

  console.log('\nDone!');
}

main();
