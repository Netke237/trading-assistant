# Context Doc 41 — FR-HIST: Scan History, Portfolio History, and Decision Trail

**Feature:** History and logging UI — browse past scan propositions, portfolio changes, and audit decisions
**PRD refs:** FR-43 (Monitoring & observability), FR-46 (Auditability and state recovery)
**Status:** New requirement — backend audit infrastructure exists; frontend and DB schema gaps remain

---

## 1. What the PRD already specified

From PRD-02:

> **FR-43:** "The system SHALL maintain structured logs for recommendations, approvals, alerts, and portfolio state. Each recommendation can be traced end-to-end from scan rule to final approval or rejection."

> **FR-46:** "The system SHALL preserve portfolio and watchlist state across restarts and provide an auditable decision trail. Every decision SHALL include a unique recommendation ID. The audit trail supports tracing a recommendation from scan input through final portfolio or rejection state."

---

## 2. What is already built

| Component | Location | Status |
|---|---|---|
| JSONL audit log | `backend/audit.log` | Writing on every scan — events: `scan_started`, `trade_card_created`, `candidate_rejected` |
| Unique `rec_id` per scan | `backend/app/services/audit.py` | `new_rec_id()` generates `REC-YYYYMMDD-XXXXXXXX` |
| Current scan session | `scan_sessions` DB table, `id="current"` | Persists the last scan result only — overwritten on each new scan |
| Portfolio positions | `portfolio_positions` DB table | Current state persists across restarts — no history of changes |

---

## 3. What is missing (the gaps)

### Gap A — Scan history: only "current" scan survives

The `scan_sessions` table has a single row (`id="current"`). Every new scan overwrites it. There is no record of what the scanner proposed yesterday or last week.

**Fix needed:** Change the persistence model to retain one row per scan. Add a `GET /api/scans` endpoint returning the history list.

### Gap B — Portfolio history: no timeline

The portfolio table stores current open positions. There is no record of:
- When a position was opened
- What the scanner's proposition was that led to it
- P&L over time
- Closed/expired positions

**Fix needed:** Add a `portfolio_history` table and log every position change (add, close, expire).

### Gap C — No frontend to view any of this

The audit.log and DB data exist but there is no page in the app to browse them.

**Fix needed:** A "History" page (new nav item) with three tabs: Scans | Portfolio | Decisions.

---

## 4. Scope of this workstream

This workstream is split into two sub-tasks that can be dispatched in parallel:

### WT-A: Backend history (database + endpoints)

**Owned files:**
- `backend/app/models/scan_session.py` — modify to support multiple rows
- `backend/migrations/` — add Alembic migration for new schema
- `backend/app/routers/history.py` — new router: `GET /api/scans`, `GET /api/scans/{scan_id}`, `GET /api/portfolio/history`
- `backend/app/schemas/__init__.py` — add `ScanSummary`, `PortfolioEvent` models
- `backend/app/main.py` — register history router

**Schema changes:**

```sql
-- scan_sessions: add index, keep all rows (remove the single id="current" constraint)
ALTER TABLE scan_sessions ADD COLUMN display_id TEXT;  -- human-friendly: "Scan #4 — 2024-06-15 14:32"
CREATE INDEX idx_scan_sessions_timestamp ON scan_sessions(timestamp DESC);

-- portfolio_history: new table
CREATE TABLE portfolio_history (
    id          TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    contract    TEXT NOT NULL,
    event_type  TEXT NOT NULL,  -- 'opened' | 'closed' | 'expired' | 'stop_hit'
    rec_id      TEXT,           -- links to scan that generated the proposition
    price       REAL,
    pnl_dollar  REAL,
    pnl_pct     REAL,
    timestamp   TEXT NOT NULL
);
```

**Endpoints:**

```
GET /api/scans                    → list[ScanSummary]   (latest 50, desc)
GET /api/scans/{scan_id}          → ScanResult          (full candidates)
GET /api/portfolio/history        → list[PortfolioEvent] (latest 200, desc)
```

**Wiring:** In `POST /api/scan`, instead of upsert with `id="current"`, insert a new row with a generated `scan_id`. Also keep a `id="current"` pointer row (or just always query by latest timestamp) so `GET /api/tradecards` still works.

### WT-B: Frontend history page

**New route:** `frontend/app/(frame)/history/page.tsx`

**Nav:** Add `History` entry to `NavItems` between Validation and Settings.

**Three tabs:**

#### Tab 1 — Scans
Table showing past scans:

| Date | Universe size | Candidates | Direction | Horizon | Regime |
|---|---|---|---|---|---|
| 2024-06-15 14:32 | 12 | 4 PASS, 2 CAUTION | Bullish | Swing | PASS |

Clicking a row opens a drawer or navigates to `/history/scans/{scan_id}` showing the full candidate list (reuses `ValidationTable` component).

#### Tab 2 — Portfolio
Timeline of position events:

| Date | Symbol | Contract | Event | Price | P&L |
|---|---|---|---|---|---|
| 2024-06-18 | AAPL | 190C 06/21 | Opened | $4.15 | — |
| 2024-06-21 | AAPL | 190C 06/21 | Expired | $0.00 | −$415 |

#### Tab 3 — Decisions
Raw audit trail from `GET /api/audit` (paginated):

| Time | Event | Symbol | rec_id | Detail |
|---|---|---|---|---|
| 14:32:05 | trade_card_created | AAPL | REC-20240615-A3F1 | score: 82 |
| 14:32:05 | candidate_rejected | META | REC-20240615-A3F1 | stock REJECT (score 38) |

---

## 5. Link between scan proposition and portfolio

When the user sends a trade card to broker/portfolio (Step 7), the `rec_id` from the trade card should be stored with the portfolio position. This creates the trace:

```
Scan run (scan_id: REC-20240615-A3F1)
  └── Candidate AAPL (rec_id: REC-20240615-A3F1)
        └── Portfolio position opened (rec_id: REC-20240615-A3F1)
              └── Position closed 2024-06-21 — P&L: −$415
```

**Required change in `POST /api/portfolio`:** Accept and store the `rec_id` field from the trade card.

---

## 6. Costs

- No external services needed.
- Storage: JSONL audit log grows at ~1 KB per scan candidate. At 10 scans/day × 10 candidates = 100 KB/day = ~35 MB/year. Negligible.
- DB: scan history rows are ~2 KB each. 1000 scans = 2 MB. Negligible.

---

## 7. Acceptance criteria

- `GET /api/scans` returns the 50 most recent scans with candidate counts.
- Running two consecutive scans produces two separate rows — not an overwrite.
- `GET /api/tradecards` still returns the most recent scan's candidates (unchanged behaviour).
- Portfolio History tab shows position open/close events in reverse chronological order.
- Scan History tab: clicking a past scan shows its candidates (read-only, no step navigation).
- Every new portfolio position carries the `rec_id` of the scan proposition that generated it.
- `pytest backend/tests/ -v` — all existing tests pass.
- `npm run typecheck` — zero errors.

---

## 8. What this is NOT

- Not a charting/P&L dashboard (that would be a separate FR).
- Not real-time streaming (the history table is polled on page load, no WebSocket needed).
- Not backtesting (covered by FR-BT, context doc 40).
