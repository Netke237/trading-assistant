// ISSUE 2 VERIFICATION
// Proves: scan is fast, non-blocking, returns correct shape, DB uses UUID not singleton

import { test, expect, request as playwrightRequest } from '@playwright/test'

const BACKEND = 'http://localhost:8001'
const SMALL_UNIVERSE = ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMZN']

const MEDIUM_UNIVERSE = [
  'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','BRK.B','LLY','V',
  'JPM','UNH','XOM','MA','AVGO','PG','HD','COST','JNJ','WMT',
  'ABBV','MRK','CVX','BAC','CRM','KO','PEP','ACN','MCD','TMO',
  'NFLX','AMD','CSCO','ABT','DHR','LIN','ADBE','NKE','DIS','PM',
  'ORCL','TXN','INTC','HON','INTU','QCOM','RTX','CAT','AMGN','IBM'
]

test.describe('Issue 2 — Scan pipeline performance', () => {

  test('POST /api/scan returns 200 with correct response shape', async () => {
    const ctx = await playwrightRequest.newContext()
    const res = await ctx.post(`${BACKEND}/api/scan`, {
      data: { universe: SMALL_UNIVERSE, direction: 'Bullish', horizon: 'Swing' },
    })

    expect(res.status()).toBe(200)
    const body = await res.json()

    expect(body).toHaveProperty('scan_id')
    expect(body).toHaveProperty('candidates')
    expect(body).toHaveProperty('rejected')

    expect(body.scan_id).toMatch(
      /^REC-\d{8}-[A-F0-9]{8}$/,
      'scan_id must be a REC-YYYYMMDD-XXXXXXXX format — the singleton "current" row was a bug'
    )

    await ctx.dispose()
  })

  test('Scan completes in under 60 seconds for 50-symbol universe', async () => {
    test.setTimeout(90_000)

    const ctx = await playwrightRequest.newContext()
    const t0 = Date.now()

    const res = await ctx.post(`${BACKEND}/api/scan`, {
      data: { universe: MEDIUM_UNIVERSE, direction: 'Bullish', horizon: 'Swing' },
    })

    const elapsed = (Date.now() - t0) / 1000
    console.log(`[benchmark] 50-symbol scan completed in ${elapsed.toFixed(1)}s`)

    expect(res.status()).toBe(200)
    expect(elapsed, `Scan took ${elapsed.toFixed(1)}s — batching fix may not be applied`).toBeLessThan(60)

    await ctx.dispose()
  })

  test('Scan does NOT block the uvicorn worker — /health responds during scan', async () => {
    test.setTimeout(120_000)

    const ctx = await playwrightRequest.newContext()

    const scanPromise = ctx.post(`${BACKEND}/api/scan`, {
      data: { universe: MEDIUM_UNIVERSE, direction: 'Bullish', horizon: 'Swing' },
    })

    await new Promise(r => setTimeout(r, 2000))

    const t0 = Date.now()
    const health = await ctx.get(`${BACKEND}/health`)
    const latency = Date.now() - t0

    expect(health.status()).toBe(200)
    expect(
      latency,
      `/health took ${latency}ms — worker appears blocked. Async refactor may not be working.`
    ).toBeLessThan(1000)

    console.log(`[non-blocking] /health responded in ${latency}ms while scan ran`)

    await scanPromise
    await ctx.dispose()
  })

  test('fetch_events returns both earnings and dividend data (merged endpoint fix)', async () => {
    const ctx = await playwrightRequest.newContext()

    const res = await ctx.get(`${BACKEND}/api/events/AAPL`)
    expect(res.status()).not.toBe(500)

    const body = await res.json()
    expect(body).toHaveProperty('earnings_date')
    expect(body).toHaveProperty('dividend_date')

    await ctx.dispose()
  })

  test('Consecutive scans use different scan_ids — no singleton DB corruption', async () => {
    const ctx = await playwrightRequest.newContext()

    const r1 = await ctx.post(`${BACKEND}/api/scan`, { data: { universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing' } })
    const r2 = await ctx.post(`${BACKEND}/api/scan`, { data: { universe: ['MSFT'], direction: 'Bullish', horizon: 'Swing' } })

    const b1 = await r1.json()
    const b2 = await r2.json()

    expect(b1.scan_id).not.toEqual(b2.scan_id)
    console.log(`[db] scan_id 1: ${b1.scan_id}`)
    console.log(`[db] scan_id 2: ${b2.scan_id}`)

    await ctx.dispose()
  })
})
