# Plan: UNRESOLVED-SAVE-UX (#171)

## Problem
When a position save fails ambiguously (e.g. offline network, bare HTTP 5xx, or unparseable 2xx response), the client records a `DirectSendNote` with `kind: 'save-unconfirmed'` and sends no broker order.
The user is shown a persistent warning banner with a **Remove** button.
When the user clicks **Remove**, `removeNoteRow` calls `removeTrackedRow(note.recId, note.kind !== 'save-unconfirmed')`.
Because `note.kind === 'save-unconfirmed'`, `notFoundIsFinal` is `false`. When the backend returns HTTP 404 (`Position with rec_id '...' not found.`), the 404 is re-thrown as an error instead of being treated as success, trapping the note indefinitely on screen with:
`"Not found yet — the save may still be finishing. Press Remove again in a few seconds."`

Kenneth decided on 2026-10-15:
> **Dismiss after 'not found'**: When a position deletion returns 404 for an unconfirmed save, treat 404 as final (the row never landed on the server), dismiss the note, and unblock subsequent actions.

## Scope
- In scope:
  1. `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`:
     - In `removeNoteRow`: Pass `true` for `notFoundIsFinal` so 404 is swallowed as final success.
     - Remove the stale "the save may still be finishing" error message.
  2. `frontend/lib/stockDirectSend.ts`:
     - In `removeNoteRow`: Pass `true` for `notFoundIsFinal`.
     - In `removeNoteRow`: Release `useStockOrderOwnershipStore` if `note.recId` or its symbol was locked in `unknown` state.
  3. Tests:
     - Update Test 18 in `frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-save-first.test.tsx` to verify that 404 immediately removes the note and clears the list.
     - Add a unit test in `frontend/lib/__tests__/stockDirectSend.test.tsx` verifying that `removeNoteRow` removes the `save-unconfirmed` note when `deletePortfolioPosition` returns 404.
- Out of scope:
  - Changing broker order execution, portfolio schemas, or other note kinds (`order-unknown`).

## Acceptance Criteria
- Clicking "Remove" on a `save-unconfirmed` note whose backend position delete returns 404 deletes the note from `useDirectSendNotesStore`.
- No error message or "Not found yet" text remains displayed.
- Test 18 in `direct-send-save-first.test.tsx` passes.
- `npm run typecheck` and Jest tests pass.
- Independent plan and code audits clean under `audit_rule`.
