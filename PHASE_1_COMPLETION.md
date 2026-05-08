# Trading Assistant — Phase 2 Continuation Prompt

## Where we are

This is the **Bamendjou Options Screener and Recommendation Assistant** (repo: `F:\Git\GitHub\Trading assistant`). We just completed **Phase 1** of a production-readiness push against PRD-02 (`PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md`).

### Phase 1 completed (all merged to `main`)

| Workstream | Branch | PRD Requirement | Status |
|---|---|---|---|
| State Persistence | `feature/state-persistence` | FR-46 | `recId` on all positions, Zustand `persist` middleware (portfolio/watchlist/contracts), audit logger (`lib/audit.ts`), duplicate-merge on rehydrate |
| Trade Card Enhancements | `feature/trade-card-enhancements` | FR-15, FR-40 | `TargetLevel[]` array replacing single `target`, scale-out logic, pricing method badges, sell-to-close plan section |
| Continuous Scan | `feature/continuous-scan` | FR-32, FR-33 | `ScanScheduler` backend service, `/api/scan/continuous` endpoints, `PARTIAL`/`CANCELLED` scan states, scan-to-scan delta computation |
| Testing + Pagination | `feature/testing-pagination` | FR-44, FR-12 | 48 frontend unit tests (stores + components), 24 backend tests (data-leakage + reproducibility + portfolio rules), Pagination molecule in Step 4 |
| Chart Indicators | `feature/chart-indicators` | FR-35 | RSI, MACD, Volume indicator panes on `CandlestickChart`, toggle bar, pure client-side calculations |

### Current verification status

- **Frontend typecheck**: Clean (0 errors)
- **Frontend tests**: 48 passed, 7 suites, 0 failures
- **Backend tests**: 90 passed (11 pre-existing failures in `test_routes.py` due to empty fixture data — not caused by Phase 1)

### Architecture context

- **Frontend**: Next.js 15, TypeScript strict, CSS Modules, Zustand v5, lightweight-charts v5, no Tailwind
- **Backend**: FastAPI, SQLAlchemy async, pytest, Heston + Black-Scholes models
- **Key types** (`types/domain.ts`): `PortfolioPosition` now has `recId: string` and `targets: TargetLevel[]`; `ScanState` includes `'PARTIAL' | 'CANCELLED'`
- **Worktrees directory**: `.worktrees/` (gitignored) — contains isolated branches for completed workstreams

---

## What remains: Phase 2

Phase 2 has 2 workstreams that depend on Phase 1 outputs. These are **not yet started**.

### F. Risk Management (FR-42)

**Dependencies**: State Persistence (A) + Trade Card Enhancements (B)

**What to build**:
- Enforce max exposure per trade and max total portfolio exposure
- Enforce max concurrent approved trade count and max daily trade recommendation count
- Every trade card must include explicit invalidation level and capital-at-risk estimate
- Correlation and event-risk checks before adding recommendation to portfolio
- Risk rules operate independently of scoring confidence and may veto a recommendation
- Portfolio-level risk state visible in dashboard

**Key acceptance criteria**:
- Portfolio manager rejects/flags recommendations exceeding configured exposure limits
- Approved trades show invalidation level, estimated risk, position sizing rationale
- Correlated-symbol risk visible in recommendation summary, may reduce position size
- System prevents approval without defined invalidation stop

### G. Alerting & Monitoring (FR-37, FR-43)

**Dependencies**: State Persistence (A) + Trade Card Enhancements (B)

**What to build**:
- Rate limiting + deduplication windows for alerts
- Exit-aware alerts: TP hit, stop reached, premium stop, time stop approaching
- Event-risk alerts for earnings/expirations
- Alert delivery: in-app toast + badge (sound optional)
- Structured logs for recommendations, approvals, alerts, portfolio state
- Dashboard shows watchlist status, approved positions, unrealized P&L, risk status, recent alerts

**Key acceptance criteria**:
- Alerts limited to one per event type per configured window
- Each recommendation traceable end-to-end from scan rule to final approval/rejection
- Event-risk alerts for earnings, expirations, user-configured review dates

---

## How to continue

1. **Read the PRD**: `F:\Git\GitHub\Trading assistant\PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md`
2. **Read LLM_CONTEXT.md**: `F:\Git\GitHub\Trading assistant\frontend\LLM_CONTEXT.md` (master conventions)
3. **Create worktrees** for Phase 2:
   - `.worktrees/feature-risk-management`
   - `.worktrees/feature-alerting-monitoring`
4. **Implement workstreams F and G** in parallel (they are independent of each other)
5. **Merge to main** after verification
6. **Update this file** with Phase 2 results

## Critical rules

- Use the `using-git-worktrees` skill to create isolated workspaces
- Use the `worktree-context-doc` skill to generate scoped LLM context documents for each subagent
- Run `npm run typecheck` after every frontend edit — must be clean
- Run `pytest` after every backend edit — must pass (except pre-existing `test_routes.py` failures)
- Do not modify files outside the owned files list for each workstream
- Commit after each file is complete

## Pre-existing test failures to ignore

`backend/tests/test_routes.py` has 11 failures due to empty fixture data — this is a pre-existing issue unrelated to any work. All other tests must pass.

---

*Generated after Phase 1 completion. Next: Phase 2 (Risk Management + Alerting).*