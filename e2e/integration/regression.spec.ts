// REGRESSION SUITE
// The async refactor of market.py broke 6 routers with ImportError.
// These tests ensure they never silently break again.

import { test, expect, request as playwrightRequest } from '@playwright/test'

const BACKEND = 'http://localhost:8001'

const ROUTERS = [
  { name: 'candles',   path: '/api/candles/AAPL',    method: 'get'  as const },
  { name: 'contracts', path: '/api/contracts?symbol=AAPL', method: 'get'  as const },
  { name: 'news',      path: '/api/news?symbols=AAPL',    method: 'get'  as const },
  { name: 'sectors',   path: '/api/sectors',          method: 'get'  as const },
  { name: 'alerts',    path: '/api/alerts',           method: 'get'  as const },
  { name: 'regime',    path: '/api/regime',           method: 'get'  as const },
  { name: 'events',    path: '/api/events/AAPL',     method: 'get'  as const },
]

test.describe('Regression — routers after async refactor', () => {
  for (const router of ROUTERS) {
    test(`${router.name} router responds (not 500 ImportError)`, async () => {
      const ctx = await playwrightRequest.newContext()
      const res = await ctx[router.method](`${BACKEND}${router.path}`)

      expect(
        res.status(),
        `${router.name} returned ${res.status()} — possible ImportError from async refactor`
      ).not.toBe(500)

      expect(
        res.status(),
        `${router.name} returned 404 — router may not be registered in main.py`
      ).not.toBe(404)

      await ctx.dispose()
    })
  }
})
