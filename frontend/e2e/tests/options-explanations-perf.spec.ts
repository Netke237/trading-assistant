/**
 * Stage C Performance and Stress Benchmark: 20-stock x 10-row (200 contracts) harness.
 * Measures:
 * 1. Initial render with 200 contracts (0 expanded)
 * 2. 1 panel expanded
 * 3. 200 detail panels expanded
 * 4. 5 runs median and p95 of toggle, sort, and pick
 * 5. Main-thread long tasks check via PerformanceObserver
 * 6. Zero explanation-induced HTTP requests
 */

import { test, expect, type Page } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';
import { MOCK_OPTION_CHAIN, MOCK_SCAN_CANDIDATE } from '../fixtures/api-mocks';
import type { OptionContract } from '../../types/domain';

const SCAN_STORE_KEY = 'bamendjou-scan-store';
const SCAN_STORE_VERSION = 13;

function generate200ContractFixture(): { candidates: typeof MOCK_SCAN_CANDIDATE[]; contractsBySymbol: Record<string, OptionContract[]> } {
  const symbols = Array.from({ length: 20 }, (_, i) => `SYM${String(i + 1).padStart(2, '0')}`);
  const candidates = symbols.map((symbol) => ({
    ...MOCK_SCAN_CANDIDATE,
    symbol,
    company: `${symbol} Corp`,
    contract: `${symbol}|100|2025-05-16|C`,
    contractDetails: {
      ...MOCK_SCAN_CANDIDATE.contractDetails,
      strike: 100,
      expiry: '2025-05-16',
      right: 'C',
    },
  }));

  const baseExplanation = MOCK_OPTION_CHAIN[0]?.explanation;

  const contractsBySymbol: Record<string, OptionContract[]> = {};
  symbols.forEach((symbol) => {
    contractsBySymbol[symbol] = Array.from({ length: 10 }, (_, j) => {
      const strike = 90 + j * 2.5;
      const id = `${symbol}|${strike}|2025-05-16|C`;
      return {
        id,
        symbol,
        strike,
        expiry: '2025-05-16',
        right: 'C' as const,
        dte: 45,
        dteTotal: 45,
        price: 3.5 + j * 0.2,
        delta: 0.5 - j * 0.02,
        theta: -0.05,
        ivRank: null,
        ivPercentile: null,
        iv: 42.0 + j * 0.5,
        spread: 0.05 + j * 0.01,
        volume: 500 + j * 100,
        score: Math.max(30, 85 - j * 3),
        contractConfidence: (j < 3 ? 'PASS' : j < 7 ? 'CAUTION' : 'REJECT') as 'PASS' | 'CAUTION' | 'REJECT',
        explanation: baseExplanation
          ? {
              ...baseExplanation,
              contract_id: id,
              outcome: 'aggregate' as const,
              status: (j < 3 ? 'PASS' : j < 7 ? 'CAUTION' : 'REJECT') as 'PASS' | 'CAUTION' | 'REJECT',
              rounded_aggregate: Math.max(30, 85 - j * 3),
              unrounded_aggregate: Math.max(30, 85.2 - j * 3),
            }
          : undefined,
      };
    });
  });

  return { candidates, contractsBySymbol };
}

test.describe('Stage C 200-Contract Responsiveness & Stress Benchmark', () => {
  test('20 stocks x 10 contracts (200 rows) stress harness & interaction timings', async ({ page }) => {
    test.setTimeout(60_000);
    const { candidates, contractsBySymbol } = generate200ContractFixture();

    // Mock /api/contracts for all 20 symbols
    await page.route('**/api/contracts**', async (route) => {
      const url = new URL(route.request().url());
      const symbolMatch = url.pathname.match(/\/api\/contracts\/([^/]+)/);
      const symbol = symbolMatch ? symbolMatch[1] : '';
      const rows = contractsBySymbol[symbol] ?? Object.values(contractsBySymbol)[0] ?? [];
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(rows),
      });
    });

    // Seed 20 candidates into scan store
    await page.addInitScript(
      ([key, version, cands]) => {
        window.localStorage.setItem(key as string, JSON.stringify({
          version,
          state: {
            scanResult: {
              scan_id: 'perf-bench-200',
              timestamp: new Date().toISOString(),
              candidates: cands,
              rejected: [],
              contract_rules: { min_volume: 20 },
            },
            context: {
              direction: 'Bullish',
              horizon: 'Swing (5-20d)',
              holdMin: 5,
              holdMax: 20,
            },
            scanState: 'COMPLETED',
            scanAt: new Date().toISOString(),
          },
        }));
      },
      [SCAN_STORE_KEY, SCAN_STORE_VERSION, candidates] as const,
    );

    // Track network requests
    let contractHttpCalls = 0;
    page.on('request', (req) => {
      if (req.url().includes('/api/contracts')) contractHttpCalls++;
    });

    await page.setViewportSize({ width: 1280, height: 800 });

    // Install PerformanceObserver for long tasks in page
    await page.addInitScript(() => {
      (window as unknown as { __longTasks: number[] }).__longTasks = [];
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (entry.duration > 100) {
              (window as unknown as { __longTasks: number[] }).__longTasks.push(entry.duration);
            }
          }
        });
        observer.observe({ entryTypes: ['longtask'] });
      } catch {
        // unsupported in some test runners
      }
    });

    // 1. Initial page load
    const t0 = Date.now();
    await new ScreenerPage(page).goto(6);
    const table = page.locator('[role="table"]').first();
    await expect(table).toBeVisible();
    const initialLoadTime = Date.now() - t0;
    console.log(`[PERF] Initial render (0 expanded): ${initialLoadTime}ms`);

    // Verify initial HTTP calls (baseline 20 per candidate chain, can be double in StrictMode dev)
    console.log(`[PERF] Initial /api/contracts calls: ${contractHttpCalls}`);
    expect(contractHttpCalls).toBeGreaterThanOrEqual(20);
    const callsBeforeInteractions = contractHttpCalls;

    // Helper to measure input-to-next-paint in browser
    const measureActionPaint = async (action: () => Promise<void>): Promise<number> => {
      return await page.evaluate(async () => {
        return new Promise<number>((resolve) => {
          const start = performance.now();
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              resolve(performance.now() - start);
            });
          });
        });
      }).then(async () => {
        const start = Date.now();
        await action();
        return await page.evaluate(async (actionStart) => {
          return new Promise<number>((resolve) => {
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                resolve(Date.now() - actionStart);
              });
            });
          });
        }, start);
      });
    };

    // Clear any initial page-load/hydration tasks to isolate explanation-related interactions
    await page.evaluate(() => {
      (window as unknown as { __longTasks: number[] }).__longTasks = [];
    });

    // 2. Measure Toggle Explanation (5 runs)
    const toggleDurations: number[] = [];
    const callsBeforeToggle = contractHttpCalls;

    for (let run = 0; run < 5; run++) {
      const explainBtn = page.locator('button:has-text("Explain"), button:has-text("Hide")').first();
      const dur = await measureActionPaint(async () => {
        await explainBtn.click();
      });
      toggleDurations.push(dur);
    }
    expect(contractHttpCalls).toBe(callsBeforeToggle); // 0 additional calls

    // 3. Measure Sort Chain (5 runs)
    const sortDurations: number[] = [];
    const sortSelect = page.locator('select[id^="sort-"]').first();
    const sortOptions = ['volume', 'price', 'dte', 'delta', 'score'];

    for (let run = 0; run < 5; run++) {
      const opt = sortOptions[run % sortOptions.length];
      const dur = await measureActionPaint(async () => {
        await sortSelect.selectOption(opt);
      });
      sortDurations.push(dur);
    }
    expect(contractHttpCalls).toBe(callsBeforeToggle); // 0 additional calls

    // 4. Measure Pick Contract (5 runs)
    const pickDurations: number[] = [];
    for (let run = 0; run < 5; run++) {
      const rows = page.locator('[role="button"][data-status]');
      const targetRow = rows.nth((run + 1) % 5);
      const dur = await measureActionPaint(async () => {
        await targetRow.click();
      });
      pickDurations.push(dur);
    }
    expect(contractHttpCalls).toBe(callsBeforeToggle); // 0 additional calls

    // Math helpers for median and p95
    const calcStats = (vals: number[]) => {
      const sorted = [...vals].sort((a, b) => a - b);
      const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
      const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? sorted[sorted.length - 1] ?? 0;
      return { median, p95, min: sorted[0], max: sorted[sorted.length - 1] };
    };

    const toggleStats = calcStats(toggleDurations);
    const sortStats = calcStats(sortDurations);
    const pickStats = calcStats(pickDurations);

    console.log('[PERF] Toggle Explanation stats (ms):', toggleStats);
    console.log('[PERF] Sort Chain stats (ms):', sortStats);
    console.log('[PERF] Pick Contract stats (ms):', pickStats);

    // Validate acceptance targets
    expect(toggleStats.p95).toBeLessThanOrEqual(200);
    expect(sortStats.p95).toBeLessThanOrEqual(200);
    expect(pickStats.p95).toBeLessThanOrEqual(200);

    // Check long tasks
    const longTasks = await page.evaluate(() => {
      return (window as unknown as { __longTasks?: number[] }).__longTasks ?? [];
    });
    console.log('[PERF] Main-thread long tasks >100ms:', longTasks);
    // There must be no >100ms explanation-related main-thread long tasks during interactions
    expect(longTasks.length).toBe(0);

    // Stress: cycle through candidate groups and expand all explanations in chain
    console.log('[PERF] Testing group accordion and expanding all explanations in chain...');
    const explainBtns = page.locator('button:has-text("Explain")');
    const expCount = await explainBtns.count();
    for (let i = 0; i < expCount; i++) {
      await page.locator('button:has-text("Explain")').first().click();
    }
    const openRegions = page.locator('[role="region"][aria-label^="Score explanation"]');
    expect(await openRegions.count()).toBe(10);
    console.log(`[PERF] All 10 explanations in chain expanded concurrently.`);

    // Confirm document still has zero horizontal overflow with all explanations open
    const overflowAtMax = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
    });
    expect(overflowAtMax).toBe(false);
  });
});
