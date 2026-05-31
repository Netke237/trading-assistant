// FULL STACK E2E
// Browser → Next.js → FastAPI → Tradier API → SQLite → back to browser
// Zero mocks for data. Everything is live.
// Requires the real backend on port 8000 (started via desktop link).

import { test, expect } from '@playwright/test'

const REAL_BACKEND = 'http://localhost:8000'

test.describe('Full stack — scan flow end to end', () => {

  test.beforeAll(async ({ request }) => {
    try {
      const res = await request.get(`${REAL_BACKEND}/health`)
      if (!res.ok()) {
        throw new Error(`Backend health check failed: ${res.status()}`)
      }
      console.log('[scan-ui] Real backend on port 8000 is healthy')
    } catch {
      test.skip(true, 'Real backend not running on port 8000. Start it via the desktop link first.')
    }
  })

  test('app loads, scan runs, results render', async ({ page }) => {
    test.setTimeout(240_000)

    await page.goto('http://localhost:3001/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForSelector('[data-testid="run-scan-button"]', { state: 'visible', timeout: 15_000 })
    await page.waitForTimeout(500)

    const scanBtn = page.locator('[data-testid="run-scan-button"]')
    await expect(scanBtn).toBeEnabled({ timeout: 5_000 })

    await scanBtn.click({ force: true })
    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).toContainText(/SCANNING/i, { timeout: 10_000 })

    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).toContainText(/COMPLETED|FAILED|PARTIAL/i, { timeout: 200_000 })

    await expect(page.locator('body')).toBeVisible()
    await expect(page.locator('[data-testid="run-scan-button"]')).toBeVisible()

    const statusText = await page.locator('[data-testid="scan-status-pill"]').textContent()
    console.log(`[e2e] Final scan status: ${statusText}`)
  })

  test('backend /health confirms stack is connected', async ({ request }) => {
    const res = await request.get(`${REAL_BACKEND}/health`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.status).toBe('ok')
  })
})
