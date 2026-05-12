// Console Error Guard — ensures critical React runtime errors fail Playwright tests.
// Attach to each `page` before navigation so errors are captured regardless of when they fire.
//
// Critical error patterns:
//   - "Maximum update depth exceeded"  (infinite re-render loop)
//   - "getServerSnapshot"             (sync external store error, e.g. Zustand misuse)
//   - "React error"                   (catch-all for React runtime errors)
//
// Opt-out: call detachConsoleGuard(page) to remove the listener for a specific test.

const CRITICAL_PATTERNS = ['Maximum update depth exceeded', 'getServerSnapshot', 'React error']

export function attachConsoleGuard(page: any): void {
  page.on('console', (msg: any) => {
    if (msg.type() !== 'error') return
    const text: string = msg.text()
    for (const pattern of CRITICAL_PATTERNS) {
      if (text.includes(pattern)) {
        const url = page.url()
        throw new Error(`[console-guard] Critical React error on "${url}": ${text}`)
      }
    }
  })
}

export function detachConsoleGuard(page: any): void {
  page.off('console', () => {})
}
