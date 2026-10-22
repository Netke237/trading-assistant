# APP-AUDIT-B-RUN-GATE — Shared Run Scan confirmation bypassed in Stocks and Pre-Breakout (#387)

Independent remediation phase from #350 (programme #348), addressing defect B3-2 from `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/regime/findings.md`.

## Goal

Ensure the direction-aligned `combinedRegime === 'REJECT'` confirmation dialog in `RunScanButton` (`frontend/components/organisms/RunScanButton/index.tsx`) gates scan execution and navigation across all three screener modes (`options`, `stocks`, and `prebreakout`), rather than being bypassed in Stocks and Pre-Breakout modes.

## Root Cause

In `frontend/components/organisms/RunScanButton/index.tsx`:
- Lines 74–77 handle `prebreakout` mode with an early return:
  ```tsx
  if (screenerMode === 'prebreakout') {
    router.push('/screener/step-4-prebreakout');
    return;
  }
  ```
- Lines 79–130 handle `stocks` mode with an early return:
  ```tsx
  if (screenerMode === 'stocks') {
    ...
    return;
  }
  ```
- Lines 161–165 check the market regime:
  ```tsx
  const currentRegime = useScanStore.getState().combinedRegime;
  if (currentRegime === 'REJECT' && !regimeConfirmedRef.current) {
    setShowRegimeConfirm(true);
    return;
  }
  ```

Because the mode-specific handlers for `prebreakout` and `stocks` return before line 161 is ever evaluated:
1. In `stocks` mode, clicking "Run Stock Scan" fires `runStockScanWithContinuation(activeStrategy)` immediately without prompting the user, even when the direction opposes market regime (`combinedRegime === 'REJECT'`).
2. In `prebreakout` mode, clicking "Go to Setup Scanner" navigates immediately to `/screener/step-4-prebreakout` without prompting the user.
3. Only `options` mode reaches line 161 to present the confirmation dialog.

## Implementation Details

### 1. Component Refactor: `frontend/components/organisms/RunScanButton/index.tsx`

Hoist the confirmation check to the top of `onClick`, immediately following the `if (scanning) return;` guard:

```tsx
  const onClick = useCallback(() => {
    if (scanning) return;

    const isRegimeOpposed = useScanStore.getState().combinedRegime === 'REJECT';
    if (isRegimeOpposed && !regimeConfirmedRef.current) {
      setShowRegimeConfirm(true);
      return;
    }

    if (screenerMode === 'prebreakout') {
      router.push('/screener/step-4-prebreakout');
      return;
    }

    if (screenerMode === 'stocks') {
      ...
```

- Remove the redundant check at lines 161–165 in the `options` path.
- The state variable `isRegimeOpposed` satisfies the presence probe declared in `docs/superpowers/PROJECT_STATE.json` (`verify.pattern: "isRegimeOpposed"`).
- Dialog actions in JSX remain:
  - **Cancel**: `setShowRegimeConfirm(false);` — closes the dialog; no scan is triggered, and no navigation occurs.
  - **Proceed anyway**:
    ```tsx
    setShowRegimeConfirm(false);
    regimeConfirmedRef.current = true;
    onClick();
    regimeConfirmedRef.current = false;
    ```
    When `onClick()` is invoked re-entrantly with `regimeConfirmedRef.current = true`, `isRegimeOpposed && !regimeConfirmedRef.current` evaluates to `false`, allowing execution to proceed into the respective mode's branch (`prebreakout`, `stocks`, or `options`). Resetting `regimeConfirmedRef.current = false` immediately after ensures any subsequent scan run requires confirmation anew.

### 2. Regression Testing: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`

Add an exhaustive test suite under `describe('RunScanButton — cross-mode regime REJECT gate (#387)', ...)`:
1. **Stocks mode with REJECT**:
   - `screenerMode: 'stocks'`, `activeStrategy: 'pullback_ema'`, `combinedRegime: 'REJECT'`.
   - Click button -> Dialog appears ("Market regime is REJECT"). `runStockScanWithContinuation` is NOT called; router does NOT navigate.
   - Click "Cancel" -> Dialog disappears; `runStockScanWithContinuation` is NOT called.
   - Click button again -> Click "Proceed anyway" -> `runStockScanWithContinuation` IS called and execution proceeds normally.
2. **Pre-Breakout mode with REJECT**:
   - `screenerMode: 'prebreakout'`, `combinedRegime: 'REJECT'`.
   - Click button -> Dialog appears ("Market regime is REJECT"). `mockPush` is NOT called.
   - Click "Cancel" -> Dialog disappears; `mockPush` is NOT called.
   - Click button again -> Click "Proceed anyway" -> `mockPush` IS called with `'/screener/step-4-prebreakout'`.
3. **Options mode with REJECT**:
   - `screenerMode: 'options'`, `combinedRegime: 'REJECT'`.
   - Click button -> Dialog appears ("Market regime is REJECT"). `api.postScanBody` is NOT called.
   - Click "Cancel" -> Dialog disappears; `api.postScanBody` is NOT called.
   - Click button again -> Click "Proceed anyway" -> `api.postScanBody` IS called.
4. **PASS regime (all modes)**:
   - When `combinedRegime === 'PASS'`, clicking the button bypasses the dialog in all three modes and executes directly.
5. **Subsequent click re-prompts**:
   - After confirming once via "Proceed anyway", a subsequent click while `combinedRegime === 'REJECT'` re-prompts the dialog (verifying `regimeConfirmedRef.current` was properly reset to `false`).

## Verification Commands

1. `npm test -- RunScanButton.test.tsx`
2. `npm run typecheck`
3. `npm test` (full frontend suite)
4. `python scripts/state.py`

## Audit and Delivery Workflow

1. Spawn independent subagent for **Plan Audit** applying `.agents/skills/bmad-review-adversarial-general/SKILL.md` under the repository numeric/persistence gate. Record findings and clean status in `docs/superpowers/audits/APP-AUDIT-B-RUN-GATE/plan-r1.md` and `PROJECT_STATE.json`.
2. Apply code and test changes.
3. Run verification commands. Commit implementation changes.
4. Sync latest `origin/main` if moved.
5. Spawn independent subagent for **Code Audit** applying `.agents/skills/bmad-review-adversarial-general/SKILL.md` against the integrated diff. Record findings and clean status in `docs/superpowers/audits/APP-AUDIT-B-RUN-GATE/code-r1.md` and `PROJECT_STATE.json`.
6. Push branch `board/app-audit-b-run-gate-ee5e0b18` and open PR targeting `main` with title `fix(screener): enforce shared reject confirmation in Stocks and Pre-Breakout (#387)`.
7. Once CI checks pass and all `board.md` requirements are satisfied, execute self-merge via `gh pr merge --merge --match-head-commit <sha>`.
8. Reconcile merge record to `status: shipped`, update GitHub issue #387, post Telegram notification, and release the claim.
