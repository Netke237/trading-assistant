# Plan: Portfolio: show stock and option price at entry, and each stop's distance from them (#630)

## Problem & Context
On the Portfolio page (`frontend/app/(frame)/portfolio/page.tsx` and `EditDrawer.tsx`), users cannot see what the underlying stock was worth when a contract was bought:
1. The table row's "ENTRY → NOW" column displays the option premium only (e.g. `$3.00 → $2.80`).
2. The underlying stock price at entry has been recorded in the database (`portfolio_positions.entry_stock_price`) for option positions created since the column was added, but `PortfolioPositionSchema` in `backend/app/schemas/__init__.py` does not include `entryStockPrice`. As a result, `GET /api/portfolio` strips it, and neither the frontend store nor the UI ever receives it. For stock positions (`contract.endsWith('|STOCK')`), `entry_price` is already the stock entry price.
3. The invalidation Stop (`stop`) and Structural stop (`structuralStop`) are stock price levels, while the Premium stop is an option price (for options) or stock price (for short stock). Because no entry reference is shown next to each stop, users cannot see how far each stop level sits from entry.
4. Legacy option rows opened before `entry_stock_price` existed have `NULL` in the database. Per issue #630: **Never backfill or estimate it.** A NULL stock entry must be displayed as `—` and labeled "not recorded".

Issue #630 tracks this enhancement.

## Core Requirements & Acceptance Criteria
- **Criterion 1 (API Schema Read):** `GET /api/portfolio` returns `entryStockPrice: float | None` for every open position schema.
  - For stock positions (`contract.endsWith('|STOCK')`), `entryStockPrice` is populated directly from `entry_price`.
  - For option positions, `entryStockPrice` is populated from `entry_stock_price` (which is a float or `None`).
  - Writes and position creation (`create_position` / `services/position_writer.py`) remain completely unchanged.
- **Criterion 2 (Backend Coverage):** Backend pytest tests verify that `GET /api/portfolio` returns `entryStockPrice` as a valid float when populated on the model and as `null` when `entry_stock_price` is `None` (legacy option row), and returns `entryPrice` as `entryStockPrice` for stock legs.
- **Criterion 3 (Frontend Type & Store Deserialization):**
  - `PortfolioPosition` in `frontend/types/domain.ts` and `BackendPosition` in `frontend/lib/portfolioStore.ts` include `entryStockPrice?: number | null`.
  - `fromBackend` in `frontend/lib/portfolioStore.ts` maps `entryStockPrice: isStock ? p.entryPrice : (p.entryStockPrice ?? null)` without default substitution.
  - Store version bumped to `8` in `portfolioStore.ts` with migration for existing stored positions.
  - Optimistic creation (`persistPosition`, `applyPersistedPosition`, `buildPaperPosition`) preserves `entryStockPrice` so newly added positions do not flash "not recorded".
- **Criterion 4 (Visible Entry Reference Display):** Portfolio UI (`EditDrawer` and row) displays:
  - "Stock at entry": `$50.00` (or `— (not recorded)` for legacy option rows).
  - "Option at entry": `$3.00 per share` (with contract cost = `entryPrice × 100 × (contracts ?? 1)`).
  - For stock positions (`contract.endsWith('|STOCK')`), only "Stock at entry" is shown once (since option at entry is inapplicable).
- **Criterion 5 (Direction-Aware Stop Distances):** Each stop displays its distance from its respective entry reference:
  - `stop` and `structuralStop` against `entryStockPrice`: formatted as `$46.60 · −$3.40 / −6.8% from entry`. Direction-aware for Bearish positions: an adverse move toward the stop sits above entry, which represents negative return/risk distance (`−$X.XX / −Y.Y% from entry`), while a trailed stop locking in profit sits below entry and represents a positive distance (`+$X.XX / +Y.Y% from entry`).
  - `premiumStop` against option entry `entryPrice`: formatted as `$1.20 · −$1.80 / −60% from entry` (or `$1.20 · −60% of $3.00`). For short stock: stop fires on a rise (e.g. at $55.00 on $50.00 entry with 10% stop), which represents an adverse loss of `−$5.00 / −10.0% from entry`.
  - When `entryStockPrice` is null (legacy rows), stock stop distances render `— (not recorded)`.
  - Finite number validation (`Number.isFinite`) guards against `NaN` on all numeric inputs.
- **Criterion 6 (No Alert or Order Impact):** No change to how positions are saved, how orders are submitted, or how alerts evaluate in `alertEngine.ts` or `alert_generator.py`.
- **Criterion 7 (Test & Typecheck Cleanliness):** Jest test suites and TypeScript `tsc --noEmit` remain 100% clean.

---

## Detailed Implementation Steps

### Step 1: Backend Schema & Router Update
- In `backend/app/schemas/__init__.py`:
  - Add `entryStockPrice: Optional[float] = None` to `PortfolioPositionSchema`.
  - In `PortfolioPositionSchema.from_orm_model(cls, obj)`:
    ```python
    is_stock = bool(obj.contract and obj.contract.endswith("|STOCK"))
    entry_stock_price = obj.entry_price if is_stock else getattr(obj, "entry_stock_price", None)
    ```
    Map `entryStockPrice=entry_stock_price`.
- In `backend/tests/test_portfolio_entry_stock_price.py`:
  - Create dedicated tests verifying `GET /api/portfolio` returns:
    1. `entryStockPrice` as a float when `entry_stock_price` is set on an option position.
    2. `entryStockPrice` as `None`/`null` when `entry_stock_price` is `None` on a legacy option position.
    3. `entryStockPrice == entryPrice` for a stock position (`|STOCK`).

### Step 2: Frontend Types & Store Update
- In `frontend/types/domain.ts`:
  - In `interface PortfolioPosition`: add `entryStockPrice?: number | null;`.
- In `frontend/lib/portfolioStore.ts`:
  - In `type BackendPosition`: add `entryStockPrice?: number | null;`.
  - In `fromBackend(p: BackendPosition)`:
    ```typescript
    const isStock = p.contract.endsWith('|STOCK');
    entryStockPrice: isStock ? p.entryPrice : (p.entryStockPrice ?? null),
    ```
  - In `persistPosition`: capture `entryStockPrice` from server response body and return in `SaveOutcome`.
  - In `applyPersistedPosition`: retain `saved.entryStockPrice ?? pos.entryStockPrice`.
  - In `buildPaperPosition` (and wherever optimistic positions are built): populate `entryStockPrice`.
  - In `usePortfolioStore` persist configuration: bump version to `8`.
  - In `migratePortfolioPersist`: add migration for v7 -> v8 populating `entryStockPrice: isStock ? entryPrice : null`.

### Step 3: Pure Stop Distance Helper & Tests
- Create `frontend/lib/stopDistance.ts`:
  - `formatStockStopDistance(stopPrice: number | null | undefined, entryStockPrice: number | null | undefined, direction: Direction): string | null`
    - Returns `null` if `stopPrice == null || !Number.isFinite(stopPrice) || stopPrice <= 0`.
    - Returns `"— (not recorded)"` if `entryStockPrice == null || !Number.isFinite(entryStockPrice) || entryStockPrice <= 0`.
    - If `direction === 'Bearish'`:
      `dollarDelta = entryStockPrice - stopPrice` (adverse move where stop > entry yields negative dollarDelta)
    - If `direction === 'Bullish'`:
      `dollarDelta = stopPrice - entryStockPrice` (adverse move where stop < entry yields negative dollarDelta)
    - `pctDelta = (dollarDelta / entryStockPrice) * 100`
    - Formats string: e.g. `$46.60 · −$3.40 / −6.8% from entry` (using unicode minus `−` for negative, `+` for positive).
  - `formatPremiumStopDistance(entryPrice: number, premiumStopPct: number | null | undefined, globalPremiumStopPct: number, contract: string, direction: Direction): string | null`
    - Returns `null` if `!Number.isFinite(entryPrice) || entryPrice <= 0`.
    - Resolves `effectivePct = resolvePremiumStopPct(premiumStopPct, globalPremiumStopPct)`.
    - Resolves `shortStock = isShortStockPosition(contract, direction)`.
    - Resolves `firingPrice = percentStopFiringPrice(entryPrice, effectivePct, shortStock)`.
    - For `shortStock`:
      `dollarDelta = entryPrice - firingPrice` (fires above entry, e.g. 50 - 55 = -5.00)
      `pctDelta = (dollarDelta / entryPrice) * 100` (-10%)
      Formats: `$55.00 · −$5.00 / −10.0% from entry`
    - For options/long-stock:
      `dollarDelta = firingPrice - entryPrice` (fires below entry, e.g. 1.20 - 3.00 = -1.80)
      `pctDelta = (dollarDelta / entryPrice) * 100` (-60%)
      Formats: `$1.20 · −60% of $3.00` (or `$1.20 · −$1.80 / −60.0% from entry`).
- Create `frontend/lib/__tests__/stopDistance.test.ts`:
  - Unit tests covering all cases:
    - Bullish stock stop below entry (adverse, negative).
    - Bullish stock stop above entry (trailed profit, positive).
    - Bearish stock stop above entry (adverse, negative).
    - Bearish stock stop below entry (trailed profit, positive).
    - NULL entryStockPrice -> "— (not recorded)".
    - NaN or non-finite inputs guarded.
    - Unset/zero stop -> null.
    - Premium stop distance on option (60% of $3.00 -> $1.20).
    - Premium stop with inherited global stop resolved.
    - Premium stop on short stock.

### Step 4: UI Updates in Portfolio Page & EditDrawer
- In `frontend/app/(frame)/portfolio/EditDrawer.tsx`:
  - Add an Entry Reference header section between `editHeader` and `editGrid`:
    - Shows "Stock at entry": `$50.00` or `— (not recorded)` if null.
    - If not a stock position: shows "Option at entry": `$3.00 per share` (contract cost = `$300.00` via `position.entryPrice * 100 * (position.contracts ?? 1)`).
    - If a stock position: shows "Stock at entry" only once.
  - In `EditField` component:
    - Add `distance?: string | null` prop.
    - Render distance hint in label row:
      `<span className={styles.distanceText}>{distance}</span>`
  - Pass distance to `EditField label="Stop"`:
    `distance={formatStockStopDistance(position.stop, isStock ? position.entryPrice : position.entryStockPrice, position.direction)}`
  - Pass distance to `EditField label="Structural stop"`:
    `distance={formatStockStopDistance(position.structuralStop, isStock ? position.entryPrice : position.entryStockPrice, position.direction)}`
  - In `PremiumStopEditor`:
    - Display `formatPremiumStopDistance(position.entryPrice, position.premiumStopPct, globalPremiumStopPct, position.contract, position.direction)`.
- In `frontend/app/(frame)/portfolio/page.tsx`:
  - In `priceCell` for table rows:
    - Add tooltip `title` with "Stock at entry: ..." and "Option at entry: ...".
    - For option positions, add secondary subtext line showing `Stock: $XX.XX` (or `Stock: —` if null).
- In `frontend/app/(frame)/portfolio/page.module.css`:
  - Add styles for `.entryRefCard`, `.entryRefItem`, `.entryRefValue`, `.notRecorded`, `.distanceText`, `.stockEntrySub`.

### Step 5: Verification & Audit
- Run backend pytest tests (`backend/.venv/Scripts/pytest backend/tests/test_portfolio_entry_stock_price.py`): 2 passed.
- Run backend portfolio suite (`pytest -k portfolio`): 378 passed.
- Run frontend typecheck (`npm run typecheck`): 0 errors.
- Run frontend Jest tests (`npm run test`): clean.

## Audit History

### Plan Stage
- **Round 1 (2026-11-12):** Subagent `a2462ae4-28ab-4094-8f44-60b65f105651` reported 7 findings. Plan updated.
- **Round 2 (2026-11-12):** Subagent `54125aec-ffe7-495e-a3b0-11256486e37e` confirmed **0 gate findings**. Plan stage closed clean.

### Code Stage
- **Round 1 (2026-11-13):** Subagent `a8edd7f2-520a-4757-b6d5-91a1634907b1` reported 1 gate finding:
  - Finding 1: `formatPremiumStopDistance` used `Math.round(effectivePct * 100)`, causing lossy percentage displays for non-integer stops (e.g. 12.5%, 48.43%, 0.19%).
  - Advisory: `stockTimeStop.test.ts` store version expectation needed update to 8.
- **Fix:**
  - Replaced `Math.round` with `premiumStopPctLabel(effectivePct)` from `frontend/lib/premiumStop.ts`.
  - Added test cases in `frontend/lib/__tests__/stopDistance.test.ts` for non-integer percentages.
  - Updated store version expectation in `frontend/lib/__tests__/stockTimeStop.test.ts` to 8.
- **Round 2 (2026-11-13):** Subagent `f3694f4f-ce80-4cc6-9a88-59445e24dcba` confirmed **0 gate findings**. Code stage closed clean (`audit_clean: true`).
