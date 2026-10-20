/**
 * @smoke
 * The IV basis split, rendered (PHASE-A-NULL-IVRANK-2026-09-06).
 *
 * `ivRank` (a TRUE PERCENTILE, present only when IBKR or tastytrade answered)
 * and `iv` (an ABSOLUTE 0-100 level for one strike) are two different
 * quantities, and printing one under the other's label is the defect Phase A
 * exists to remove. Nothing else in the suite watches that: the mocked chain
 * is consumed only by ws-g-happy-path-mocked.spec.ts, whose tests are
 * `test.fixme` and therefore never run, so before this file the fixtures could
 * have gone on feeding the pre-split shape unnoticed — and did.
 *
 * These tests reach the two pages that show the figure without going through
 * Steps 1-3 (which is what ws-g is fixme'd over) by seeding the persisted scan
 * store directly, and they assert the RENDERED FORM rather than merely that
 * some IV text is present. A regression that read the wrong field, or labelled
 * an absolute level as a percentile, changes that form and fails here.
 */

import { test, expect, type Page } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';
import { MOCK_SCAN_CANDIDATE, MOCK_OPTION_CHAIN } from '../fixtures/api-mocks';

// Seeded at the store's CURRENT version so `migrate` is skipped. Seeding at an
// older version would run the v12→v13 legacy strip over this blob and drop the
// very fields under test.
const SCAN_STORE_KEY = 'bamendjou-scan-store';
const SCAN_STORE_VERSION = 13;

/** Puts one COMPLETED scan in localStorage before the app boots, so a deep step
 *  URL renders with candidates instead of its empty state. `context` is left
 *  null on purpose: every read of it on these pages is optional-chained with a
 *  default, and seeding one would assert coupling that does not exist. */
async function seedCompletedScan(page: Page, candidate: unknown = MOCK_SCAN_CANDIDATE): Promise<void> {
  await page.addInitScript(
    ([key, version, c]) => {
      window.localStorage.setItem(key as string, JSON.stringify({
        version,
        state: {
          scanResult: {
            scan_id: 'iv-basis-e2e',
            timestamp: new Date().toISOString(),
            candidates: [c],
            rejected: [],
          },
          scanState: 'COMPLETED',
          scanAt: new Date().toISOString(),
        },
      }));
    },
    [SCAN_STORE_KEY, SCAN_STORE_VERSION, candidate] as const,
  );
}

test.describe('IV basis rendering (mocked) @smoke', () => {
  test('Step 5 shows an absolute IV as absolute, and gates it on the absolute set', async ({ page }) => {
    await seedCompletedScan(page);
    await new ScreenerPage(page).goto(5);

    // The seeded candidate carries `iv: 42` with `ivRank: null` — no rank source
    // answered, which is the common production case. Asserted through the cell's
    // `title`, because that is where formatIv() states the BASIS outright; the
    // rendered "42.0%" alone would also be produced by a percentile printed with
    // the wrong unit, which is precisely the confusion under test.
    const ivCell = page.locator('[title^="Implied volatility"]');
    await expect(ivCell).toHaveCount(1);
    await expect(ivCell).toContainText('42.0%');

    // ...and nothing may dress it as a percentile. `rank` is the suffix
    // formatIv() appends on the rank basis only.
    await expect(page.locator('[title^="IV rank"]')).toHaveCount(0);
    await expect(page.getByText('rank', { exact: true })).toHaveCount(0);

    // The gate sentence must quote the ABSOLUTE threshold set (Swing: 34/55),
    // not the rank set that happens to be seeded with the same numbers today.
    // The noun is what separates them.
    await expect(page.getByText(/IV ≤ 34 → PASS/)).toBeVisible();
    await expect(page.getByText(/IV rank ≤/)).toHaveCount(0);
  });

  test('Step 6 shows per-strike absolute IV, and no reading as no reading', async ({ page }) => {
    await seedCompletedScan(page);
    await new ScreenerPage(page).goto(6);

    // Two of the three mocked strikes carry their own absolute IV, and they
    // DIFFER: `iv` is per strike, whereas a rank is one symbol-level number
    // broadcast over the whole chain. Distinct values are what makes a
    // wrong-field read visible at all — under the pre-split fixture every strike
    // held the same 42 and either field read identically.
    const absoluteCells = page.locator('[title^="Implied volatility"]');
    await expect(absoluteCells).toHaveCount(2);
    await expect(absoluteCells.filter({ hasText: '42.0%' })).toHaveCount(1);
    await expect(absoluteCells.filter({ hasText: '43.1%' })).toHaveCount(1);
    await expect(page.locator('[title^="IV rank"]')).toHaveCount(0);
    await expect(page.getByText('rank', { exact: true })).toHaveCount(0);

    // The third strike has no reading at all — a state the pre-split shape could
    // not express, since one field then had to stand for both. It must read as
    // absent rather than as a floor: `iv ?? 0` would print 0.0% here and would
    // also sort a contract with no volatility data to the top of an ascending
    // "cheapest IV" sort.
    await expect(page.locator('[title="No implied-volatility data for this contract."]')).toHaveCount(1);
    await expect(page.getByText('0.0%')).toHaveCount(0);
  });

  test('Step 5 and Step 6 show an IV rank on the rank basis, and gate on the rank set', async ({ page }) => {
    // Seed candidate carrying a true IV rank percentile (PHASE-A-NULL-IVRANK-2026-09-06 / #176)
    const rankCandidate = {
      ...MOCK_SCAN_CANDIDATE,
      contractDetails: {
        ...MOCK_SCAN_CANDIDATE.contractDetails,
        ivRank: 20,
        iv: 42,
      },
    };
    await seedCompletedScan(page, rankCandidate);

    // Override /api/contracts to provide contracts carrying ivRank
    const rankChain = MOCK_OPTION_CHAIN.map((c) => ({
      ...c,
      ivRank: c.iv != null ? 20 : null,
    }));
    await page.route('**/api/contracts**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(rankChain),
      });
    });

    // ── Step 5: Vol / Events ────────────────────────────────────────────────
    await new ScreenerPage(page).goto(5);

    // Cell title states the basis outright: "IV rank 20 — where today's implied volatility sits..."
    const ivCell = page.locator('[title^="IV rank"]');
    await expect(ivCell).toHaveCount(1);
    await expect(ivCell).toContainText('20');
    await expect(page.getByText('rank', { exact: true })).toBeVisible();

    // Absolute basis label must NOT be present on this row
    await expect(page.locator('[title^="Implied volatility"]')).toHaveCount(0);

    // Gate sentence must quote the RANK threshold set (Swing: 34/55)
    await expect(page.getByText(/IV rank ≤ 34 → PASS/)).toBeVisible();
    await expect(page.getByText(/^IV ≤ \d+ → PASS/)).toHaveCount(0);

    // ── Step 6: Contracts ───────────────────────────────────────────────────
    await new ScreenerPage(page).goto(6);

    // Column header derived via ivColumnLabel(ivBasesOf(contracts)) must read "IV RANK"
    await expect(page.getByRole('button', { name: 'IV RANK', exact: true })).toBeVisible();

    // The two strikes with volatility must render their IV rank with "rank" suffix
    const rankContractCells = page.locator('[title^="IV rank"]');
    await expect(rankContractCells).toHaveCount(2);
    await expect(rankContractCells.first()).toContainText('20');

    // The strike without reading remains as no data
    await expect(page.locator('[title="No implied-volatility data for this contract."]')).toHaveCount(1);
  });
});
