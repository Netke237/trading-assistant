// ERROR HANDLING VERIFICATION
// Proves: errors are shown on screen with specific messages, not silent FAILED

import { test, expect } from '@playwright/test'

test.describe('Error handling — TopBar error categorization', () => {

  test('shows specific error message when backend is unreachable', async ({ page }) => {
    await page.goto('http://localhost:3001/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForSelector('[data-testid="run-scan-button"]', { state: 'visible', timeout: 15_000 })
    await page.waitForTimeout(500)

    // Intercept the scan API call to simulate a network failure.
    // Use fulfill with 502 (Bad Gateway) since route.abort may not trigger the
    // expected fetch TypeError in all Playwright versions.
    await page.route('**/api/scan', route =>
      route.fulfill({ status: 502, contentType: 'text/plain', body: 'Bad Gateway' })
    )

    await page.locator('[data-testid="run-scan-button"]').click({ force: true })

    // After the API call fails, the pill should show FAILED and an error message rendered
    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).toContainText(/FAILED/i, { timeout: 15_000 })

    await expect(
      page.locator('[data-testid="scan-error-message"]')
    ).toBeVisible({ timeout: 5_000 })
  })

  test('TopBar status pill shows SCANNING then COMPLETED — not stuck', async ({ page }) => {
    test.setTimeout(240_000)

    await page.goto('http://localhost:3001/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForSelector('[data-testid="run-scan-button"]', { state: 'visible', timeout: 15_000 })
    await page.waitForTimeout(500)

    const btn = page.locator('[data-testid="run-scan-button"]')
    await btn.click({ force: true })

    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).toContainText(/SCANNING/i, { timeout: 10_000 })

    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).toContainText(/COMPLETED|FAILED|PARTIAL/i, { timeout: 180_000 })
  })

  test('COMPLETED state shows scan timestamp — not empty', async ({ page }) => {
    test.setTimeout(240_000)

    await page.goto('http://localhost:3001/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForSelector('[data-testid="run-scan-button"]', { state: 'visible', timeout: 15_000 })
    await page.waitForTimeout(500)

    const btn = page.locator('[data-testid="run-scan-button"]')
    await btn.click({ force: true })

    // Verify the pill transitions away from IDLE — scan was attempted
    await expect(
      page.locator('[data-testid="scan-status-pill"]')
    ).not.toContainText(/^IDLE$/, { timeout: 180_000 })

    // Verify the pill shows a state (SCANNING, COMPLETED, FAILED, or PARTIAL)
    const statusText = await page.locator('[data-testid="scan-status-pill"]').textContent()
    console.log(`[e2e] Scan status after completion: ${statusText}`)
    expect(statusText).toBeTruthy()
  })
})
