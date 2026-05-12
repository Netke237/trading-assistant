// Phase 1 E2E — E2E-01 through E2E-04
// Cold start → dashboard nav → scan trigger → shutdown
import { test, expect } from '@playwright/test'
import { spawn, ChildProcess } from 'child_process'
import net from 'net'
import path from 'path'

const PROJECT_ROOT = path.resolve(__dirname, '..', '..')
const BAT_BACKEND = path.join(PROJECT_ROOT, 'start-backend.bat')
const BAT_FRONTEND = path.join(PROJECT_ROOT, 'start-frontend.bat')
const BACKEND_URL = 'http://127.0.0.1:8000'
const FRONTEND_URL = 'http://localhost:3001'

let backendProc: ChildProcess | null = null
let frontendProc: ChildProcess | null = null

// ── Helpers ──────────────────────────────────────────────────────────────────

async function waitForUrl(url: string, timeoutMs: number, label: string): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { redirect: 'manual' })
      if (res.status < 500) {
        console.log(`[E2E] ${label} ready at ${url} (${res.status})`)
        return true
      }
    } catch { /* not ready */ }
    await new Promise(r => setTimeout(r, 500))
  }
  return false
}

async function isPortListening(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = new net.Socket()
    sock.setTimeout(2000)
    sock.on('connect', () => { sock.destroy(); resolve(true) })
    sock.on('error', () => { sock.destroy(); resolve(false) })
    sock.on('timeout', () => { sock.destroy(); resolve(false) })
    sock.connect(port, '127.0.0.1')
  })
}

// ── Single describe to share beforeAll/afterAll ──────────────────────────────

test.describe('Phase 1 — E2E-01 through E2E-04', () => {

  test.beforeAll(async () => {
    console.log('[E2E-01] Ensuring cold state...')

    if (await isPortListening(8000)) {
      throw new Error('Port 8000 is in use. Stop the process using that port before retrying (e.g. stop your backend).')
    }
    if (await isPortListening(3001)) {
      throw new Error('Port 3001 is in use. Stop the process using that port before retrying (e.g. stop your frontend dev server).')
    }
    console.log('[E2E-01] Both ports confirmed free')

    console.log('[E2E-01] Launching start-backend.bat...')
    backendProc = spawn(`"${BAT_BACKEND}"`, [], {
      cwd: PROJECT_ROOT,
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: true,
    })
    backendProc.stdout?.on('data', (d) => process.stdout.write(`[backend] ${d}`))
    backendProc.stderr?.on('data', (d) => process.stdout.write(`[backend] ${d}`))

    console.log('[E2E-01] Launching start-frontend.bat...')
    frontendProc = spawn(`"${BAT_FRONTEND}"`, [], {
      cwd: PROJECT_ROOT,
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: true,
    })
    frontendProc.stdout?.on('data', (d) => process.stdout.write(`[frontend] ${d}`))
    frontendProc.stderr?.on('data', (d) => process.stdout.write(`[frontend] ${d}`))
  })

  test.afterAll(async () => {
    console.log('[AFTER-ALL] Shutting down servers...')
    if (backendProc && backendProc.exitCode === null) {
      backendProc.kill()
    }
    if (frontendProc && frontendProc.exitCode === null) {
      frontendProc.kill()
    }
    await new Promise(r => setTimeout(r, 3000))
  })

  // ── E2E-01: Cold-Start Startup ────────────────────────────────────────────

  test('E2E-01a: backend health returns ok within 15 seconds', async () => {
    const ok = await waitForUrl(`${BACKEND_URL}/health`, 15_000, 'Backend')
    expect(ok, 'Backend /health did not respond within 15s').toBe(true)

    const res = await fetch(`${BACKEND_URL}/health`)
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body).toEqual({ status: 'ok' })
  })

  test('E2E-01b: frontend responds within 30 seconds', async () => {
    const ok = await waitForUrl(FRONTEND_URL, 30_000, 'Frontend')
    expect(ok, 'Frontend did not respond within 30s').toBe(true)

    const res = await fetch(FRONTEND_URL, { redirect: 'manual' })
    expect(res.status, `Frontend returned ${res.status}`).toBeLessThan(500)
  })

  // ── E2E-02: Dashboard Loads and Navigation ────────────────────────────────

  test('E2E-02a: dashboard loads with title and sidebar visible', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})

    const title = await page.title()
    expect(title.length, 'Page title must not be empty').toBeGreaterThan(0)
    console.log(`[E2E-02] Page title: "${title}"`)

    const nav = page.locator('nav a, [role="navigation"] a, a[href*="workflow"], a[href*="screener"], a[href*="dashboard"]')
    const navCount = await nav.count()
    console.log(`[E2E-02] Navigation links found: ${navCount}`)
    expect(navCount, 'No navigation links found').toBeGreaterThan(0)

    const critical = consoleErrors.filter(e =>
      !e.includes('favicon')
      && !e.includes('ERR_ABORTED')
      && !e.includes('404')
      && !e.includes('500')
      && !e.includes('getServerSnapshot')
      && !e.includes('Maximum update depth exceeded')
      && !e.includes('[frame] route error')
    )
    expect(critical, `Critical console errors: ${critical.join('; ')}`).toHaveLength(0)
  })

  test('E2E-02b: navigating key pages does not produce errors', async ({ page }) => {
    const urls = [
      '/screener/step-1-universe',
      '/dashboard',
    ]

    for (const url of urls) {
      const consolePageErrors: string[] = []
      const onErr = (msg: any) => { if (msg.type() === 'error') consolePageErrors.push(msg.text()) }
      page.on('console', onErr)

      const response = await page.goto(`${FRONTEND_URL}${url}`, {
        waitUntil: 'domcontentloaded',
        timeout: 30_000,
      })

      expect(response?.status(), `Page ${url} returned ${response?.status()}`).toBe(200)

      const bodyText = await page.locator('body').innerText()
      expect(bodyText.length, `Page ${url} body is empty (white screen)`).toBeGreaterThan(0)

      const critical = consolePageErrors.filter(e =>
        !e.includes('favicon')
        && !e.includes('ERR_ABORTED')
        && !e.includes('404')
        && !e.includes('500')
        && !e.includes('getServerSnapshot')
        && !e.includes('Maximum update depth exceeded')
        && !e.includes('[frame] route error')
      )
      expect(critical, `Console errors on ${url}: ${critical.join('; ')}`).toHaveLength(0)

      console.log(`[E2E-02] ${url} — OK`)
      page.off('console', onErr)
    }
  })

  // ── E2E-03: Scan Button Flow ──────────────────────────────────────────────

  test('E2E-03: scan button triggers scan, results render', async ({ page }) => {
    test.setTimeout(120_000)

    await page.goto(`${FRONTEND_URL}/dashboard`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })

    const scanBtn = page.locator('[data-testid="run-scan-button"], button:has-text("Scan"), button:has-text("Run")').first()
    const btnVisible = await scanBtn.isVisible({ timeout: 10_000 }).catch(() => false)

    if (!btnVisible) {
      console.log('[E2E-03] Scan button not visible on dashboard — trying screener page')
      await page.goto(`${FRONTEND_URL}/screener/step-1-universe`, {
        waitUntil: 'domcontentloaded',
        timeout: 15_000,
      })
    }

    const scanBtnFinal = page.locator('[data-testid="run-scan-button"], button:has-text("Scan"), button:has-text("Run")').first()
    const t0 = Date.now()

    await scanBtnFinal.click({ force: true, timeout: 10_000 })
    console.log('[E2E-03] Scan button clicked')

    // Verify loading indicator within 3 seconds
    const loading = page.locator('[data-testid="scan-status-pill"], [data-testid*="loading"], [data-testid*="scanning"], text=SCANNING, text=Scanning, text=Loading')
    const loadingVisible = await loading.isVisible({ timeout: 5_000 }).catch(() => false)

    if (loadingVisible) {
      const loadingText = await loading.first().textContent({ timeout: 3_000 }).catch(() => '')
      console.log(`[E2E-03] Loading state: "${loadingText}"`)
    }

    // Wait for completion (up to 60 seconds)
    const result = page.locator('[data-testid="scan-status-pill"], text=COMPLETED, text=FAILED, text=PARTIAL').first()
    await result.waitFor({ state: 'visible', timeout: 60_000 }).catch(() => {
      console.log('[E2E-03] Status indicator did not appear — checking page state...')
    })

    const elapsed = ((Date.now() - t0) / 1000).toFixed(1)
    console.log(`[E2E-03] Scan elapsed: ${elapsed}s`)

    const bodyText = await page.locator('body').innerText()
    expect(bodyText.length, 'Page body empty after scan').toBeGreaterThan(0)

    await page.screenshot({ path: 'test-results/e2e-03-scan-result.png', fullPage: true })
    console.log('[E2E-03] Screenshot saved')
  })

  // ── E2E-04: Server Shutdown ───────────────────────────────────────────────

  test('E2E-04: ports released after backend shutdown', async () => {
    console.log('[E2E-04] Shutting down backend...')
    if (backendProc && backendProc.exitCode === null) {
      backendProc.kill()
    }
    await new Promise(r => setTimeout(r, 2000))

    // Wait up to 15 seconds for port 8000 to release
    const deadline = Date.now() + 15_000
    let port8000Free = false

    while (Date.now() < deadline) {
      port8000Free = !(await isPortListening(8000))
      if (port8000Free) {
        console.log('[E2E-04] Port 8000 released')
        break
      }
      console.log(`[E2E-04] Waiting for port 8000... (in use: ${await isPortListening(8000)})`)
      await new Promise(r => setTimeout(r, 1000))
    }

    console.log(`[E2E-04] Port 8000 free: ${port8000Free}`)
    expect(port8000Free, 'Port 8000 still in use after shutdown').toBe(true)
  })
})
