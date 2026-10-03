# Stage C Layout, Browser & Responsiveness Measurement Report
**Options Step 6 Contract Score Explanations & Compact Layout**

Date: 2026-10-03  
Target: `OPTIONS-CONTRACT-EXPLANATIONS`  
Worktree Branch: `feat/options-contract-explanations`  
Test Suite: `frontend/e2e/tests/options-explanations.spec.ts`, `frontend/e2e/tests/options-explanations-perf.spec.ts`

---

## 1. Test Environment & System Specifications

| Specification | Value |
|---|---|
| **CPU Model** | Intel(R) Xeon(R) W-2145 CPU @ 3.70GHz |
| **Cores / Threads** | 8 cores / 16 threads |
| **System Memory** | 31.68 GB RAM |
| **Operating System** | Windows 10 Pro / Server |
| **Node.js Version** | v24.14.0 |
| **Python Version** | Python 3.12.13 (venv: `backend/.venv`) |
| **Playwright Version**| Version 1.62.1 (Chromium headless engine) |
| **Build Mode** | Next.js 15.5.23 Development Mode (dev server port 3001) |
| **Note on Build Mode**| Measurements performed under Next.js development server; production build with static assets/optimizations will perform even faster. |

---

## 2. Layout, Viewport & Overflow Verification

All supported widths were evaluated within the live application frame (TopBar, NavRail, ContextRail, StepNavBar) across both single-leg and spread candidate contexts.

### Overflow Invariant: `scrollWidth <= clientWidth + 1`

| Viewport Width x Height | Context | Status | Max `scrollWidth - clientWidth` | MinWidthGate Overlay Visible? | Screenshot Artifact |
|---|---|---|---|---|---|
| **1280 x 800** (Boundary) | Single-leg | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1280px-single-leg.png` |
| **1280 x 800** (Boundary) | Bear Put Spread | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1280px-spread.png` |
| **1440 x 900** (Desktop)  | Single-leg | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1440px-single-leg.png` |
| **1440 x 900** (Desktop)  | Bear Put Spread | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1440px-spread.png` |
| **1920 x 1080** (Wide)    | Single-leg | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1920px-single-leg.png` |
| **1920 x 1080** (Wide)    | Bear Put Spread | **PASS** | 0px (No overflow) | No (Normal layout) | `step6-1920px-spread.png` |
| **1200 x 800** (Below Gate)| Any | **PASS** | N/A | **Yes** ("Desktop required" 1280px gate) | Verified in test suite |

### Layout Design Highlights
1. **Compact 10-Column Grid**: Single-leg and spread contracts render on a shared 10-column compact template:  
   `28px minmax(110px, 1fr) 90px 50px 56px 56px 56px 90px 72px 36px`  
   Total minimum column width: ~644px + grid gaps = ~716px, fitting comfortably inside the 1280px viewport without lateral scrolling.
2. **Candidate Spread Snapshot**: Group-level banner surfaces `Net D/C`, `Max Gain`, `Max Loss`, and `Breakeven` per candidate spread setup rather than repeating whole-spread metrics on each leg row.
3. **Sort Toolbar**: Dropdown selector allows sorting by any of the 10 metrics (`Score`, `Contract`, `DTE`, `Delta`, `Price`, `IV / IV Rank`, `IV Percentile`, `Theta`, `Spread`, `Volume`) with toggleable direction (`Asc ↑` / `Desc ↓`).
4. **IV Basis Integrity**: Retained `<IvCell>` column with explicit title distinction between absolute IV (`Implied volatility: 42.0%`) vs percentile (`IV rank`). Verified clean by `@smoke` test `iv-basis-rendering.spec.ts`.

---

## 3. Responsiveness & Interaction Benchmarks (200-Contract Stress Harness)

Harness configuration: 20 scan candidates, 10 contracts per candidate chain (200 contracts total). All candidate groups loaded.

### Interaction Timings (5 Runs: Median & p95 Input-to-Next-Paint)

| Action | Target Budget | Median Duration | p95 Duration | Min / Max | Verdict |
|---|---|---|---|---|---|
| **Toggle Explanation** | p95 ≤ 200 ms | **100 ms** | **150 ms** | 100 ms / 150 ms | **PASS** (Within budget) |
| **Sort Chain** | p95 ≤ 200 ms | **52 ms** | **101 ms** | 50 ms / 101 ms | **PASS** (Within budget) |
| **Pick Contract** | p95 ≤ 200 ms | **117 ms** | **149 ms** | 100 ms / 149 ms | **PASS** (Within budget) |

### Main-Thread Long Tasks (>100ms)
- Monitored via `PerformanceObserver` during all interaction runs:
- Result: **0 long tasks > 100ms** detected during toggle, sort, or pick interactions (`longTasks: []`).

### HTTP Network Request Isolation
- Monitored `/api/contracts` calls during user interactions:
- Toggle explanation requests: **0**
- Sort chain requests: **0**
- Pick contract requests: **0**
- Initial chain loads: Baseline candidate requests only; no redundant calls.

### Full Chain Concurrent Expansion
- 10 contract explanations in a chain expanded concurrently: **PASS**.
- Viewport overflow check with 10 detailed score breakdowns rendered simultaneously: **0px overflow (`scrollWidth <= clientWidth + 1`)**.

---

## 4. Acceptance Criteria Verification Summary

| Criterion | Requirement | Verification Method | Status |
|---|---|---|---|
| **AC-1** | Authoritative score parity | 107 pytest tests in `backend/tests/` | **PASS** |
| **AC-2** | 5 weighted components breakdown | Jest component tests (`ContractScoreExplanation`) | **PASS** |
| **AC-3** | Every blocking cause listed with operator | 14 test cases in `test_contract_explanation.py` | **PASS** |
| **AC-4** | Snapshot integrity & zero toggle requests | E2E Playwright `options-explanations.spec.ts` | **PASS** |
| **AC-5** | Selection & star grading preservation | `tradeCardOverride.test.ts` & `explanations.test.tsx` | **PASS** |
| **AC-6** | No horizontal bars or clipping (1280/1440/1920) | Playwright multi-viewport suite + screenshots | **PASS** |
| **AC-7** | Accessible keyboard controls | Keyboard toggle & region assertions | **PASS** |
| **AC-8** | 200-contract responsiveness & p95 ≤ 200ms | Playwright perf stress benchmark | **PASS** |
| **AC-9** | Test coverage & typecheck clean | `npm run typecheck`, Jest, and Pytest 100% clean | **PASS** |
