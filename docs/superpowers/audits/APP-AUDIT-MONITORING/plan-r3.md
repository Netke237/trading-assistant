# Adversarial Plan Audit (Round 3): APP-AUDIT-MONITORING (#355)

**Review Target:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md`  
**Phase ID:** `APP-AUDIT-MONITORING`  
**Branch:** `board/app-audit-monitoring-7fb31a2c`  
**Worktree:** `.worktrees/app-audit-monitoring`  
**Diff Reviewed:** `git -C .worktrees/app-audit-monitoring diff d6b7bf15..HEAD -- docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` (commit `efac8b27`)  
**Reviewer:** Independent Adversarial Subagent (`bmad-review-adversarial-general`)  
**Standard:** Project Numeric & Persistence Gate (finding blocks if it puts a wrong number in front of user or on a broker order, corrupts persisted data, or misstates mechanism such that a competent reader acting on it writes a wrong change).  
**Status:** **CLEAN (0 Gate-Level Findings)**

---

### Audit Evaluation of Round 2 Fixes

1. **Finding 1 (`useWatchedContractsStore` persisted state shape corrected to `ids: string[]`, `grading: Record<string, ContractGrading>`)**:
   - **Verification**: Line 50 of `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` was updated from `contracts: string[]` to `ids: string[], grading: Record<string, ContractGrading>`.
   - **Cross-Check with Codebase**: In `frontend/lib/watchedContractsStore.ts`:
     - Line 21: `ids: string[];`
     - Line 23: `grading: Record<string, ContractGrading>;`
     - Line 34: `type Persisted = Pick<WatchedContractsState, 'ids' | 'grading'>;`
     - Line 48: `sanitizePersisted(persisted)` returns `{ ids, grading }`.
     - Line 52: `migrateWatchedContracts` returns `{ ids, grading: version < 3 ? {} : grading }`.
     - Line 134: `partialize: (state) => ({ ids: state.ids, grading: state.grading })`.
   - **Assessment**: **VERIFIED CLEAN**. The plan now accurately reflects the actual state shape and `partialize` configuration in `watchedContractsStore.ts`. It eliminates the risk of an implementer asserting on `state.contracts` or corrupting existing persisted contracts in `localStorage`.

2. **Finding 2 (Strategy Watch endpoints corrected to `GET /api/strategy-watch/schedule` & `PUT /api/strategy-watch/schedule`, and `POST /api/strategy-watch/evaluate`)**:
   - **Verification**: Lines 95-96 of `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` were updated from `POST /api/strategy-watch/schedule` and `POST /api/strategy-watch/evaluate-now` to:
     - `GET /api/strategy-watch/schedule` & `PUT /api/strategy-watch/schedule` (polling vs EOD schedule).
     - `POST /api/strategy-watch/evaluate` (triggers immediate evaluation).
   - **Cross-Check with Codebase**:
     - `backend/app/routers/strategy_watch.py`:
       - Line 18: `router = APIRouter(prefix="/api/strategy-watch", ...)`
       - Line 96: `@router.get("/schedule")`
       - Line 101: `@router.put("/schedule")`
       - Line 106: `@router.post("/evaluate")`
     - `frontend/lib/api.ts`:
       - Line 897: `getStrategyWatchSchedule: () => get<StrategyWatchSchedule>('/api/strategy-watch/schedule')`
       - Line 899: `setStrategyWatchSchedule: (cfg: StrategyWatchSchedule) => put<StrategyWatchSchedule>('/api/strategy-watch/schedule', cfg)`
       - Line 901: `evaluateStrategyWatches: () => post<{ fired: number; events: unknown[] }>('/api/strategy-watch/evaluate', {})`
   - **Assessment**: **VERIFIED CLEAN**. The plan now strictly matches both the backend router definitions and the frontend API client methods. Tests following this plan will not encounter HTTP 405 or HTTP 404 errors.

---

### Step 4 Re-Check & Interaction Analysis

- **Re-check for adjacent or secondary regressions**:
  - Verified that updating `contracts` to `ids` in Section 2.A does not contradict Section 3 Task 2, which already verifies migration for `ids` and `grading`.
  - Verified that all other references to `contracts` refer strictly to the domain entity/tab (`Contracts Tab (tab === 'contracts')`).
  - Verified that all 7 Strategy Watch endpoints listed in Section 2.C (`GET /`, `POST /`, `POST /bulk`, `PATCH /{watch_id}`, `DELETE /{id}`, `GET /schedule`, `PUT /schedule`, `POST /evaluate`) match the routes implemented in `backend/app/routers/strategy_watch.py` and `frontend/lib/api.ts`.
  - Verified that no changes to the plan introduce false claims, invalid types, or mechanism misstatements.

---

### Conclusion

The plan is **CLEAN** (0 gate findings). Both Round 2 findings have been accurately addressed without introducing new defects or regressions. The plan is ready for implementation.
