# Adversarial Plan Audit: UNRESOLVED-SAVE-UX (#171)

- **Plan reviewed:** `docs/superpowers/plans/2026-10-21-unresolved-save-ux-plan.md`
- **Auditor Conversation:** `aff0d187-ee17-4057-b17b-ca49cb43c425`
- **Standard applied:** `bmad-review-adversarial-general` with numeric/persistence gate (AUDIT-RULE-V2)
- **Status:** CLEAN (0 gate findings)

---

### Scope & Checked Artifacts

Cross-checked the plan against the real codebase across all direct-send paths, stores, and test suites:
1. `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` (lines 102–111, 1220–1232, 1327–1348)
2. `frontend/lib/stockDirectSend.ts` (lines 60–98, 120–139, 160–175)
3. `frontend/lib/stockExecutionSession.ts` (lines 115–142, `useStockOrderOwnershipStore`)
4. `frontend/lib/directSendNotesStore.ts` (lines 15–50, `useDirectSendNotesStore`)
5. `frontend/lib/directOrder.ts` (lines 48–58, `whyOf`, `isNotFound`)
6. `frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-save-first.test.tsx` (lines 569–582, Test 18)
7. `frontend/lib/__tests__/stockDirectSend.test.tsx` (lines 220–244, `DirectSendNotesPanel` / `removeNoteRow`)
8. `docs/superpowers/PROJECT_STATE.json` (`UNRESOLVED-SAVE-UX` phase and regex verify probe)

---

### Verification Against Gate Standards

#### 1. Broker Order Safety & Order Absence Verification
- In Options Step 7 (`step-7-trade-card/page.tsx:1224-1231`), when a save is unconfirmed (`saved.offline || bare5xx || unparsed2xx`), the function registers the note via `addDirectNote({ recId, kind: 'save-unconfirmed', ... })`, drops the local row via `dropLocal(recId)`, attempts a best-effort delete, and immediately returns (`return;`). The broker order dispatch call (`api.postOptionOrder`) is strictly downstream of this early exit.
- In Stocks Direct Send (`stockDirectSend.ts:165-175`), when a save is unconfirmed, the function registers the note via `addNote({ recId, kind: 'save-unconfirmed', ... })`, drops local state, and immediately returns (`return { kind: 'unknown', qty: null, ... }`). The broker order call (`api.postStockOrder`) is never reached.
- In both paths, `orderId` is explicitly set to `null` on the note, and the rendered text is explicitly `"NO order was sent, but Portfolio may still have saved this send"`.
- Furthermore, for the other note kinds (`order-unknown` and `not-removed`), `removeNoteRow` in both files was already executing `await removeTrackedRow(note.recId, note.kind !== 'save-unconfirmed')`, which already evaluated to `notFoundIsFinal: true`.
- **Conclusion:** Deleting an unconfirmed save and treating a 404 response as final success carries zero risk of deleting or stranding an active broker order. No broker order ever existed or was attempted.

#### 2. Store Cleanliness & UI Unblocking
- `useDirectSendNotesStore`: When `removeTrackedRow(note.recId, true)` swallows 404, execution proceeds cleanly to `removeNote(note.recId)`, removing the note from the in-memory store and dismissing the persistent warning banner.
- `portfolioStore`: Inside `removeTrackedRow`, `dropLocal(recId)` removes the position from client state immediately, and `syncFromBackend(true).then(() => dropLocal(recId))` forces a fresh sync and drops it again to eliminate race conditions from any in-flight background GETs.
- `useStockOrderOwnershipStore`:
  - In `stockDirectSend.ts:130-134`, an unconfirmed save locks the symbol in `bySymbol[symbol]` with `status: 'unknown'`.
  - The plan requires releasing `useStockOrderOwnershipStore` when `removeNoteRow` removes the note. Matching by `record.recId === note.recId` and calling `ownership.finish(symbol, note.recId, null, '')` deletes `bySymbol[symbol]` and unblocks subsequent order attempts for that symbol.
- **Conclusion:** The UI is cleanly unblocked across all three stores.

#### 3. Test Coverage Sufficiency
- Options Step 7: The plan explicitly targets Test 18 in `direct-send-save-first.test.tsx:569-582`. Updating Test 18 to assert that 404 immediately removes the note and clears the list directly exercises the change.
- Stocks Direct Send: The plan specifies adding a dedicated unit test in `stockDirectSend.test.tsx` verifying that `removeNoteRow` removes the `save-unconfirmed` note when `deletePortfolioPosition` rejects with 404.
- **Conclusion:** Test coverage requirements are sufficient and cover both options and stock execution contexts.

#### 4. Error Handling & Edge Cases
- Non-404 errors (network outage / HTTP 5xx) are rethrown by `removeTrackedRow` and caught by `removeNoteRow`, setting `removing: false` and surfacing `"Remove failed: <why>. Try again."`.
- Concurrent clicks are guarded by `if (note.removing) return;`.
- User cancellation is guarded by `if (!confirm(removeConfirmText(note))) return;`.

---

### GATE FINDINGS: 0
**Status:** CLEAN
