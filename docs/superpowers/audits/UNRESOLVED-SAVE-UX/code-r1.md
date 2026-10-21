# Independent Adversarial Audit Report: Code Round 1

**Target:** `UNRESOLVED-SAVE-UX` (#171)  
**Auditor Conversation:** `7d869b06-38e3-4706-8ab6-b00bd2873088`  
**Reviewed Diff:** `origin/main..HEAD` on branch `board/unresolved-save-ux-aed7bdd5` (worktree `.worktrees/unresolved-save-ux`)  
**Plan:** `docs/superpowers/plans/2026-10-21-unresolved-save-ux-plan.md`  
**Skill Applied:** `bmad-review-adversarial-general`  
**The Gate:** Blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment blocks only if a competent reader acting on it would write a wrong change (misstates mechanism). Wording, test hygiene, dead code, style, illustrative figures, latent defects with no reachable path are not reported.  
**Status:** **CLEAN** (0 gate findings)

---

### What Was Checked

#### 1. Treating 404 as Final on Remove (`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1335-1337`, `frontend/lib/stockDirectSend.ts:86-88`)
- In `step-7-trade-card/page.tsx`:
  - `removeNoteRow` calls `await removeTrackedRow(note.recId, true)`.
  - When `api.deletePortfolioPosition(recId)` returns 404, `isNotFound(e)` is `true`.
  - With `notFoundIsFinal: true`, `removeTrackedRow` swallows the 404 error (`if (!(notFoundIsFinal && isNotFound(e))) throw e`).
  - `dropLocal(recId)` removes the position from the local `usePortfolioStore` state immediately, and `void usePortfolioStore.getState().syncFromBackend(true).then(() => dropLocal(recId))` initiates a forced backend resync to ensure no stale in-flight GET can re-populate the row.
  - `removeTrackedRow` completes normally and returns control to `removeNoteRow`, which calls `removeNote(note.recId)`.
  - The `catch (e)` block in `removeNoteRow` is bypassed completely; no error banner or status text is set, and the note is removed from `useDirectSendNotesStore`.
- In `frontend/lib/stockDirectSend.ts`:
  - `removeNoteRow` calls `await removeTrackedRow(note.recId, true)` with identical swallowing of 404.
  - `removeNote(note.recId)` removes the note cleanly from `useDirectSendNotesStore`.
  - The stale message (`"Not found yet — the save may still be finishing. Press Remove again in a few seconds."`) was completely removed from both files, aligning with Kenneth's 2026-10-15 decision: 404 is final because the row never landed on the server.

#### 2. Local Portfolio Cleanup, Ownership Release & Broker Order Safety
- **Order Safety:**
  - For `save-unconfirmed` notes, both in Options (`step-7-trade-card/page.tsx:1224-1231`) and Stocks (`stockDirectSend.ts:168-178`), the functions register the note and immediately exit when `saved.offline || bare5xx || unparsed2xx`. Downstream broker dispatch (`api.postOptionOrder` / `api.postStockOrder`) is never called. No broker order ever existed or was attempted.
  - For `order-unknown` notes where a broker order was sent, `removeConfirmText` explicitly prompts the user: `"Delete the tracked ... position? Do this ONLY if [broker] shows no order for it."`
- **Ownership Release (`frontend/lib/stockDirectSend.ts:89-94`):**
  - After `removeNote(note.recId)`, `removeNoteRow` inspects `useStockOrderOwnershipStore.getState().bySymbol`.
  - For any entry where `record.recId === note.recId && record.status === 'unknown'`, it calls `ownership.finish(sym, note.recId, null, '')`.
  - In `useStockOrderOwnershipStore`, `finish(..., status = null)` deletes `next[symbol]`, clearing the lock.
  - This cleanly unblocks subsequent stock order actions for that symbol without allowing order collisions while an order is actively `'in-flight'` or confirmed `'placed'`.

#### 3. Error Handling for Non-404 Failures
- In both `step-7-trade-card/page.tsx` and `stockDirectSend.ts`:
  - When `api.deletePortfolioPosition(recId)` fails due to a network error (`TypeError: Failed to fetch`) or server error (`500 Internal Server Error`), `isNotFound(e)` returns `false`.
  - In `removeTrackedRow`, `!(notFoundIsFinal && isNotFound(e))` evaluates to `true`, and the error is rethrown.
  - The `catch (e)` block in `removeNoteRow` catches the rethrown error and executes:
    ```ts
    patchNote(note.recId, {
      removing: false,
      status: `Remove failed: ${whyOf(e)}. Try again.`,
    });
    ```
  - `removing: false` re-enables the Remove button.
  - The note remains in `useDirectSendNotesStore`.
  - In stock mode, `ownership.finish` is not reached, so the ownership lock remains intact until successful deletion.
  - The user can retry Remove.

#### 4. Consistency Across Options and Stocks Modes
- Both execution paths use the same `removeTrackedRow(note.recId, true)` contract.
- Both call `removeNote(note.recId)` on success / 404.
- Both surface identical `Remove failed: ${whyOf(e)}. Try again.` error reporting on non-404 failure.
- Both guard re-entrancy via `if (note.removing) return;` and user intent via `confirm(removeConfirmText(note))`.
- Stocks mode additionally manages `useStockOrderOwnershipStore`, which is specific to stock execution and not used in the options path.

#### 5. Test Coverage & Verification
- `frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-save-first.test.tsx`:
  - Test 18 updated to verify that a 404 on Remove immediately dismisses a `save-unconfirmed` note and leaves 0 notes and no `"Not found yet"` text.
  - Test 20 and Test 21b continue to verify non-404 errors (`Remove failed: x. Try again.`) and per-recId targeting.
- `frontend/lib/__tests__/stockDirectSend.test.tsx`:
  - Added dedicated unit test `'SAVE-UNCONFIRMED: a 404 on Remove is final, deletes note and clears ownership (#171)'` verifying note deletion and ownership store release for `NVDA`.
- Static & runtime checks run in `.worktrees/unresolved-save-ux`:
  - `npm run typecheck`: clean (0 errors).
  - Jest: 2 suites, 86 tests passed (14.36s `stockDirectSend.test.tsx`, 93.08s `direct-send-save-first.test.tsx`).
  - `python scripts/state.py`: verified presence probe `removeTrackedRow\(note\.recId, true\)`, 0 drift.

---

### Findings

None. All checks passed the numeric, persistence, and broker order safety gate.

---

### Gate Findings: 0
**Status:** **CLEAN**
