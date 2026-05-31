# CONTEXT_FIX_STARTUP_AND_PERFORMANCE.md
# Project: Options Screener / Trading Assistant
# Purpose: Fix startup scripts, desktop shortcuts, async performance + full E2E validation
# Project Root: F:\Git\GitHub\Trading assistant
# Date: 2026-05-11
# LLM Toolset Available: Superpowers Skill, Sub-Agent Spawning, Playwright

---

## ⚠️ CRITICAL OPERATING RULES — READ FIRST, CONFIRM BEFORE ACTING

These rules apply to YOU and to every sub-agent you spawn.

1. You CANNOT declare any task DONE unless you have runtime proof.
   Runtime proof = actual terminal output, test result, or Playwright report, pasted inline.
2. You CANNOT chain steps. Complete and confirm each step individually before proceeding.
3. You CANNOT use PowerShell health checks against already-running processes as proof of a fix.
4. You CANNOT simulate, mock, or assume a test passed. If you did not run it, it is not passed.
5. If a sub-agent you spawned declares a task done without attached proof, reject its result and re-run.
6. Every bug fix must be followed by the exact acceptance test defined under that bug.
7. E2E tests must always start from a COLD STATE — no servers running before the test begins.
8. Before taking any action, list back to the user: (a) the 5 bugs you will fix, (b) the 7 execution steps, (c) the Done Definition. Wait for user confirmation before proceeding.

---

## PROJECT STRUCTURE

```
F:\Git\GitHub\Trading assistant\          ← PROJECT ROOT
├── backend\
│   ├── .venv\                            ← correct virtual environment (contains pyvenv.cfg)
│   ├── main.py                           ← FastAPI app, uvicorn entrypoint
│   └── ...
├── frontend\
│   ├── package.json
│   ├── package-lock.json                 ← KEEP THIS
│   └── ...
├── start-backend.bat                     ← EXISTS — needs repair (BUG 2)
├── start-frontend.bat                    ← MISSING or broken — needs creation (BUG 1)
├── package-lock.json                     ← ROOT LEVEL — must be deleted (BUG 4)
├── package.json                          ← root level
├── playwright.integration.config.ts
├── test-results\
│   └── .last-run.json
├── playwright-integration-report\
│   └── index.html
└── llm-contexts\
    └── FIX_STARTUP_PERFORMANCE_E2E.md    ← THIS FILE
```

---

## BUG 1 — CREATE start-frontend.bat (MISSING)

### Root Cause
The file does not exist in the project root. When a .bat file launches a child process
(npm run dev) without the `call` keyword, CMD.EXE exits immediately after spawning the
child, closing the window in under 1 second with no visible error.

### Required Action
Create the file `F:\Git\GitHub\Trading assistant\start-frontend.bat` with this exact content:

```bat
@echo off
cd /d "F:\Git\GitHub\Trading assistant\frontend"
call npm run dev
pause
```

### Acceptance Test — Step 1
- Open a FRESH CMD window (not an already-open one)
- Double-click the new start-frontend.bat OR run it from CMD
- PASS criteria:
  - Window stays open
  - Next.js compilation output is visible
  - http://localhost:3001 returns HTTP 200
  - http://localhost:3001/dashboard loads without white screen
- FAIL criteria: window closes before compilation, any compile error
- PROOF REQUIRED: paste full terminal output + confirm URL is reachable

---

## BUG 2 — REPAIR start-backend.bat (EXISTS BUT BROKEN)

### Root Cause
Two confirmed issues:
1. Script references `venv\Scripts\activate.bat` but the correct folder is `.venv\`
   (the virtual environment was recreated and the dot-prefix was dropped in the bat file)
2. The `call` keyword may be missing before uvicorn, which causes CMD.EXE to exit
   immediately after launching uvicorn, closing the window

### Required Action
Replace the full content of `F:\Git\GitHub\Trading assistant\start-backend.bat` with:

```bat
@echo off
cd /d "F:\Git\GitHub\Trading assistant\backend"
call .venv\Scripts\activate.bat
call uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
```

### Acceptance Test — Step 2
- Open a FRESH CMD window
- Run start-backend.bat
- PASS criteria:
  - Window stays open
  - Uvicorn startup log is visible ("Application startup complete")
  - GET http://127.0.0.1:8000/health returns {"status":"ok"}
- PROOF REQUIRED: paste full terminal output + paste the health endpoint response

---

## BUG 3 — DELETE OLD DESKTOP SHORTCUTS, CREATE NEW ONES FOR BOTH BAT FILES

### Root Cause
Old shortcuts point to the broken bat files or have an incorrect "Start in" path.
An incorrect "Start in" causes relative path resolution to fail even if the bat file
itself is correct, because CMD.EXE resolves relative paths from the working directory
set in the shortcut, not from the bat file's own location.

### Required Action
Use the Superpowers Skill to:

1. DELETE any existing desktop shortcuts named:
   - "start-backend" or "Start Backend" or any variant pointing to start-backend.bat
   - "start-frontend" or "Start Frontend" or any variant pointing to start-frontend.bat

2. CREATE two new .lnk shortcuts on the Desktop with these exact properties:

   Shortcut 1 — Backend:
   - Name: "Start Backend - Trading Assistant"
   - Target: F:\Git\GitHub\Trading assistant\start-backend.bat
   - Start in: F:\Git\GitHub\Trading assistant
   - Run: Normal window (NOT minimized, NOT maximized)

   Shortcut 2 — Frontend:
   - Name: "Start Frontend - Trading Assistant"
   - Target: F:\Git\GitHub\Trading assistant\start-frontend.bat
   - Start in: F:\Git\GitHub\Trading assistant
   - Run: Normal window (NOT minimized, NOT maximized)

### Acceptance Test — Step 3
- Double-click EACH new desktop shortcut (separately, not simultaneously)
- PASS criteria for each:
  - Window opens and stays open
  - Server starts successfully (same pass criteria as Step 1 and Step 2)
- PROOF REQUIRED: screenshot of both shortcuts on desktop + terminal output of each launch

---

## BUG 4 — REMOVE ROOT-LEVEL package-lock.json

### Root Cause
Two package-lock.json files exist simultaneously:
- F:\Git\GitHub\Trading assistant\package-lock.json  ← WRONG — should not exist at root
- F:\Git\GitHub\Trading assistant\frontend\package-lock.json  ← CORRECT — keep this

Next.js detects both and incorrectly guesses the workspace root, producing a warning
on every frontend startup. This is noise that obscures real errors.

### Required Action
Delete ONLY: `F:\Git\GitHub\Trading assistant\package-lock.json`
Do NOT delete: `F:\Git\GitHub\Trading assistant\frontend\package-lock.json`

### Acceptance Test — Step 4
- From a fresh terminal, run: cd "F:\Git\GitHub\Trading assistant\frontend" && npm run dev
- PASS criteria: No "two lockfiles detected" or "wrong workspace root" warning in output
- PROOF REQUIRED: paste the first 30 lines of npm run dev output

---

## BUG 5 — PERFORMANCE: Synchronous Tradier API Blocking the Uvicorn Event Loop

### Root Cause (confirmed from codebase analysis)

Two compounding issues:

**Issue A — Synchronous blocking calls:**
The scanner calls the Tradier API using synchronous `requests.get()`, one symbol at a time.
For 500 symbols × ~1.4 seconds each = ~700 seconds of blocking the single uvicorn worker.
During this time, every other incoming HTTP request (health checks, UI calls) is queued
and cannot be served. The FastAPI endpoint uses `def` instead of `async def`.

**Issue B — Duplicate API calls per symbol:**
`fetch_earnings_date()` and `fetch_dividend_date()` are each called TWICE per symbol
in the scan loop. This doubles the API round-trips for these two calls unnecessarily.

### Required Action — Spawn a sub-agent for this task

The sub-agent must:

1. Locate the scan loop (likely in a service or scanner file under backend\)
2. Replace all synchronous `requests.get()` Tradier calls with `httpx.AsyncClient`
3. Convert the scan endpoint from `def` to `async def`
4. Wrap the scan in `asyncio.gather()` with a semaphore for controlled concurrency:
   - Use `asyncio.Semaphore(10)` — maximum 10 parallel Tradier calls at once
   - This respects Tradier rate limits while maximising throughput
5. Deduplicate `fetch_earnings_date` and `fetch_dividend_date`:
   - Call each ONCE per symbol
   - Cache the result in a local dict within the scan function scope
   - Reuse the cached value wherever it was previously called a second time
6. Do NOT change the API contract — same endpoints, same request/response shape
7. Do NOT modify any frontend files

Target architecture:
```python
import asyncio
import httpx

async def scan_universe(symbols: list[str]) -> list[dict]:
    semaphore = asyncio.Semaphore(10)
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [fetch_symbol_data(client, semaphore, symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if r is not None and not isinstance(r, Exception)]

async def fetch_symbol_data(client: httpx.AsyncClient, sem: asyncio.Semaphore, symbol: str) -> dict | None:
    async with sem:
        earnings = await fetch_earnings_date(client, symbol)   # called ONCE
        dividend = await fetch_dividend_date(client, symbol)   # called ONCE
        # ... rest of per-symbol logic using earnings and dividend from above
```

### Acceptance Test — Step 5
The sub-agent MUST provide ALL of the following as proof:

- [ ] Run a timed scan with 10 symbols — attach full output including elapsed time
- [ ] Run a timed scan with 50 symbols — attach full output including elapsed time
      PASS: 50-symbol scan completes in under 30 seconds
- [ ] While a scan is running, hit GET http://127.0.0.1:8000/health
      PASS: health endpoint responds immediately (under 1 second), proving non-blocking
- [ ] Run the full backend test suite: `pytest backend/ -v`
      PASS: test_first_calibration_under_500ms must now PASS (was failing at 722ms)
      Attach full pytest output

---

## E2E TEST SUITE (Playwright)

### Purpose
Verify that the frontend and backend start correctly from cold state, the UI loads and
navigates, the Scan button triggers a real backend call and returns results, errors are
documented and fixed, and both servers shut down cleanly.

Use config: `playwright.integration.config.ts`
Save report to: `playwright-integration-report/index.html`
Save screenshots on failure to: `test-results/`

### Pre-conditions
- All 5 bugs above are fixed and their individual acceptance tests are passed
- NO servers are running before E2E begins (cold start)
- Both new desktop shortcuts exist and point to the correct bat files

---

### E2E-01: Cold-Start Startup

```
GIVEN  no servers are running (verify ports 8000 and 3001 are free)
WHEN   start-backend.bat is launched programmatically via Playwright or a helper script
AND    start-frontend.bat is launched programmatically
THEN   GET http://127.0.0.1:8000/health returns {"status":"ok"} within 15 seconds
AND    GET http://localhost:3001 returns HTTP 200 within 30 seconds
AND    no errors in backend terminal output during startup
PROOF  terminal output of both servers during startup, HTTP responses documented
```

---

### E2E-02: Dashboard Loads and Navigation Works

```
GIVEN  both servers are running (from E2E-01)
WHEN   Playwright navigates to http://localhost:3001
THEN   the page title is present and non-empty
AND    the left sidebar navigation is visible
AND    clicking each nav item (Workflow, Stocks, Contracts, Trade Cards) does not produce:
       - HTTP 404
       - White/blank screen
       - JavaScript console error
PROOF  Playwright screenshot of each navigated page, console error log (must be empty)
```

---

### E2E-03: Scan Button — Trigger, Response, and Documentation

```
GIVEN  both servers are running and the dashboard/stocks page is loaded
WHEN   Playwright locates and clicks the Scan button
THEN   a loading indicator or in-progress state appears within 3 seconds
AND    the scan API endpoint returns HTTP 200
AND    results are rendered in the UI within 60 seconds:
       - At minimum 1 result row is visible, OR
       - An explicit "no results" message is shown (both are acceptable PASS states)
AND    the total scan response time is logged in the test report
IF     any of the following occur, they must be DOCUMENTED IN FULL and FIXED before PASS:
       - HTTP 4xx or 5xx from the scan endpoint
       - JavaScript exception in the browser console
       - Timeout (scan takes over 60 seconds for a small universe)
       - UI does not update after scan completes
PROOF  Playwright screenshot before click, during loading, and after results render
       Network log showing scan endpoint request and response
       Elapsed time from click to results render
```

---

### E2E-04: Server Shutdown

```
GIVEN  both servers are running after E2E-01 through E2E-03
WHEN   both bat processes are terminated (Playwright teardown or helper script)
THEN   port 8000 is no longer listening within 10 seconds
AND    port 3001 is no longer listening within 10 seconds
PROOF  netstat or equivalent output confirming both ports are free
```

---

### E2E Error Documentation Template
If any E2E scenario fails, the sub-agent or LLM must document:
```
SCENARIO: [E2E-0X name]
STEP THAT FAILED: [exact step]
ERROR MESSAGE: [full error text]
SCREENSHOT: [attached]
NETWORK LOG: [attached if relevant]
ROOT CAUSE HYPOTHESIS: [LLM analysis]
FIX APPLIED: [exact code or config change]
RE-TEST RESULT: [PASS / FAIL — with new proof attached]
```

---

## EXECUTION ORDER

Execute strictly in this sequence. Do not skip steps. Do not combine steps.
Each step requires runtime proof before the next step begins.

| Step | Task                                          | Proof Required                                          |
|------|-----------------------------------------------|---------------------------------------------------------|
| 1    | Create start-frontend.bat                     | Window stays open, localhost:3001 reachable             |
| 2    | Repair start-backend.bat                      | Uvicorn running, /health returns {"status":"ok"}        |
| 3    | Delete old shortcuts, create 2 new shortcuts  | Both shortcuts launch servers from desktop click        |
| 4    | Delete root-level package-lock.json           | No lockfile warning on npm run dev                      |
| 5    | Async scan refactor (spawn sub-agent)         | 50-symbol scan < 30s + calibration test passes          |
| 6    | Run Playwright E2E suite (E2E-01 to E2E-04)   | HTML report + all 4 scenarios PASS with proof attached  |
| 7    | Commit all changes                            | git log showing commit on feature/fix-scan-and-startup  |

---

## SUB-AGENT INSTRUCTIONS (for Step 5)

When spawning a sub-agent for the async refactor:
- Pass this full context document to the sub-agent
- Add this instruction: "Do not mark this task done unless you attach:
  (1) pytest output showing test_first_calibration_under_500ms PASSED,
  (2) timed scan output for 50 symbols completing under 30 seconds,
  (3) health endpoint response captured DURING an active scan."
- Sub-agent must not modify any frontend files
- Sub-agent must not change the external API contract (endpoints, request/response shape)
- Sub-agent must run `pytest backend/ -v` after changes and attach full output

---

## DONE DEFINITION

This entire task is DONE only when ALL of the following checkboxes can be ticked
with attached runtime proof for each:

- [ ] start-frontend.bat exists in project root, stays open, serves localhost:3001
- [ ] start-backend.bat activates .venv correctly and serves :8000/health
- [ ] Both desktop shortcuts launch the correct bat files with correct Start-in path
- [ ] No lockfile warning appears on frontend npm run dev startup
- [ ] 50-symbol scan completes in under 30 seconds (async refactor confirmed)
- [ ] fetch_earnings_date and fetch_dividend_date are called only once per symbol
- [ ] test_first_calibration_under_500ms PASSES in pytest
- [ ] E2E-01: Cold start — both servers up, health confirmed
- [ ] E2E-02: Dashboard loads, all nav items work, zero console errors
- [ ] E2E-03: Scan button triggers, results render, response time logged
- [ ] E2E-04: Both servers shut down cleanly, ports released
- [ ] All changes committed to feature/fix-scan-and-startup
