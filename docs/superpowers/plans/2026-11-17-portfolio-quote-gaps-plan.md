# PORTFOLIO-QUOTE-GAPS — plan (board item #658)

Date: 2026-11-17 · Branch: `board/portfolio-quote-gaps-8c0ac135` · Umbrella: #656 (findings 1 and 2)
Frontend consumer: #661 `PORTFOLIO-SYNC-STATE` (reads the fields this plan adds; not built here).

## 1. Findings that drive this plan

### 1.1 BMY `quoteUnavailable` — root cause (no code defect)

Investigated read-only on 2026-11-17 (Tradier GETs, `GET /api/portfolio`, and the
read-only `backend/scripts/check_contract_strikes.py --chain` against the live DB).

- Tradier answers normally for BMY. `expirations` lists `2027-03-19`; the call chain for
  that expiry is two-sided and lists strikes 65 and **67.5**; it lists **no 67 strike**.
- The open position (`REC-1787064154702-Z4U9`, booked 2026-08-18) is stored as
  `BMY|67|2027-03-19|C`. Before EXACT-STRIKE every chain-built id was
  `f"{symbol}|{int(strike)}|…"`, so the 67.5 call was saved as `67`, and the old matcher
  (`int(float(strike_str))` vs `int(strike)`) kept pricing it from the 67.5 row.
- EXACT-STRIKE (PR #512, merged 2026-10-22, `34b00b37`) made the match exact by design
  (`parse_strike_text("67") == 67` vs row strike `67.5` → `None`). The live backend picked
  it up after the 2026-10-23 snapshot → `quoteUnavailable` → NLQ-1 skips every later
  snapshot → `openPnlCurve` frozen at 2026-10-23.
- EXACT-STRIKE's checker reports this row as `AMBIGUOUS`; its plan (ES-4, Q-1) makes any
  persisted-id correction Kenneth's per-row call, never automatic.

Conclusion: `fetch_contract_quote_async` is correct; quoting a different strike than the
id names would reintroduce the EXACT-STRIKE defect. **No change to `market.py`.** The fix
is a one-row data correction, asked as Q1 on #658 (needs Kenneth). Not built here.

### 1.2 Snapshot policy (needs Kenneth — not built here)

`GET /api/portfolio` skips `_upsert_equity_snapshot` whenever any row is
`quoteUnavailable` (NLQ-1). Options (a) keep skipping, (b) write from quoted rows + an
`unquoted_count` column, (c) last known mark + flag. Recommendation (a). Asked as Q2 on
#658. This plan changes **nothing** about which snapshots are written or what they hold;
(b)/(c) are out of scope until Kenneth answers.

## 2. What this phase builds (independent of Q1/Q2)

`GET /api/portfolio/performance` gains three fields so the Portfolio page can say *since
when* the curves are stale and *which contracts* blocked the write, instead of guessing:

| Field | Type | Meaning |
|---|---|---|
| `lastSnapshotDate` | `str \| null` (`YYYY-MM-DD`) | `snapshot_date` of the newest `equity_snapshots` row — the last point of `equityCurve` / `openPnlCurve`. `null` when there is no row. Read from the DB. |
| `snapshotSkippedOn` | `str \| null` (`YYYY-MM-DD`) | The server-local date of the most recent `GET /api/portfolio` **in this backend process** that skipped the snapshot write because of unquoted rows, **only while that read is the latest snapshot outcome** (cleared by a later successful write or a read with no open positions). `null` = no skip recorded by this process (none happened since the last write/empty read, or the process restarted since). |
| `snapshotSkippedContracts` | `list[str]` | The `contract` ids of the rows that were `quoteUnavailable` in that skipping read, de-duplicated, in the order `GET /api/portfolio` returned them. `[]` whenever `snapshotSkippedOn` is `null`. |

Rules:
- R1. The fields describe; they never alter the curves. `realized*`, `realizedCurve`,
  `equityCurve`, `openPnlCurve` are byte-identical to today for every DB state.
- R2. No new table, column or migration; no write to `equity_snapshots` added or removed.
  The skip record is a module-level value in `app/routers/portfolio.py`, not persisted
  (Q3 on #658 tells Kenneth; persistence would need his go).
- R3. Record transitions, all inside `get_portfolio`, using the same `today =
  date.today()` the handler already computes:
  - unquoted rows present → record = `(today.isoformat(), deduped unquoted contracts)`,
    set **before** the existing early `return schemas` (the skip path is otherwise
    unchanged, including its log line);
  - snapshot written → record = `None`, set **after** `await _upsert_equity_snapshot(...)`
    returns (a write that raises leaves the record as it was; the request is a 500 as
    today);
  - no open positions (`if not schemas: return schemas`) → record = `None` (nothing can
    be unquoted; a stale BMY entry must not survive the position being closed);
  - the schema-drift `except (OperationalError, ProgrammingError)` path → record untouched.
- R4. `lastSnapshotDate` is the max `snapshot_date` (the query already orders ascending;
  ISO `YYYY-MM-DD` strings sort chronologically) — take `snaps[-1].snapshot_date`.
- R5. Single uvicorn worker (`start-backend.bat`/Docker run one process), so one module
  value is the process truth. Concurrent reads: last completed transition wins — each read
  reflects a real outcome, so either value is true for some moment.

## 3. Files (Touches)

- `backend/app/routers/portfolio.py` — record + three fields in `get_performance`.
- `backend/app/schemas/__init__.py` — three optional fields on `PerformanceResponse`
  (defaults `None`, `None`, `[]`, so every existing constructor call stays valid). This
  file is outside #658's literal Touches line; it is the response model of the endpoint the
  item names, and #657 (frontend) does not touch it.
- `backend/tests/test_portfolio_close_history.py` — new tests (reuse its `client` /
  `client_with_session` fixtures and `_seed_two` / `_quotes` helpers).
- `docs/superpowers/PROJECT_STATE.json`, this plan.
- **Not touched:** `backend/app/data/market.py` (§1.1), any model, any migration, `frontend/`.

## 4. Tasks

### Task 1 — snapshot status on `/api/portfolio/performance` (ticket T1)

Tests first, appended to `backend/tests/test_portfolio_close_history.py`. Every test
resets the record first (autouse fixture in the new section:
`monkeypatch.setattr(portfolio_module, "_last_snapshot_skip", None)`, where
`portfolio_module` is `app.routers.portfolio`), because the value is module-level.

1. `test_performance_snapshot_status_empty` — no snapshot rows, no portfolio read →
   `lastSnapshotDate is None`, `snapshotSkippedOn is None`, `snapshotSkippedContracts == []`.
2. `test_performance_snapshot_status_after_a_write_day` — `_seed_two`, every quote present,
   `GET /api/portfolio` then `/performance` → `lastSnapshotDate == today`,
   `snapshotSkippedOn is None`, `[]`.
3. `test_performance_snapshot_status_after_a_skip_day` — seed a snapshot row dated
   `2026-10-23` (open_pnl 1530.0) and `_seed_two`; the option leg unquoted →
   `lastSnapshotDate == "2026-10-23"`, `snapshotSkippedOn == today`,
   `snapshotSkippedContracts == ["AAPL|185|2027-01-15|C"]`, and `openPnlCurve` is exactly
   `[{"date": "2026-10-23", "value": 1530.0}]` (R1).
4. `test_performance_snapshot_skip_cleared_by_a_later_write` — skip read, then an
   all-quoted read → `snapshotSkippedOn is None`, `[]`, `lastSnapshotDate == today`.
5. `test_performance_snapshot_skip_after_a_write_same_day` — all-quoted read, then a skip
   read → `lastSnapshotDate == today` and `snapshotSkippedOn == today` with the contract.
6. `test_performance_snapshot_skip_lists_every_unquoted_contract` — both legs of
   `_seed_two` unquoted → the list is exactly the two ids, in `GET /api/portfolio` order
   (`portfolio_positions.contract` is unique, so a duplicate cannot be seeded; the
   `dict.fromkeys` dedupe stays as a guard and needs no test of its own).
   *(Amended after plan round 1, test-only: the round noted the unique constraint.)*
7. `test_performance_snapshot_skip_cleared_when_no_positions_remain` — skip read, delete
   the positions (via the session), `GET /api/portfolio` returns `[]` → record cleared.
8. `test_performance_existing_fields_unchanged` — for the skip-day DB state of test 3,
   the response minus the three new keys equals the pre-change shape (assert the key set
   is exactly the old seven plus the three new ones, and the old values as computed).

Expected RED: tests 1–8 fail with `KeyError`/missing key (`lastSnapshotDate` absent) and
`AttributeError` on `_last_snapshot_skip` for the fixture — run once and confirm, then
implement:

- `app/schemas/__init__.py` `PerformanceResponse`: add
  `lastSnapshotDate: Optional[str] = None`, `snapshotSkippedOn: Optional[str] = None`,
  `snapshotSkippedContracts: list[str] = []`, each with a one-line comment stating §2's
  meaning (process-local for the two skip fields).
- `app/routers/portfolio.py`: module-level
  `_last_snapshot_skip: tuple[str, list[str]] | None = None` with a comment (R2, R5);
  transitions per R3 (`global` statement in `get_portfolio`); dedupe with
  `list(dict.fromkeys(unquoted))`; in `get_performance` set the three fields per R4 and
  the record.

Green: `cd backend && python -m pytest tests/test_portfolio_close_history.py -q`, then the
full backend suite `python -m pytest -q` (Python 3.11). Frontend untouched; still run
`cd frontend && npm run typecheck` once at the end as the repo requires before commit.

Commit: `feat(portfolio): snapshot status on /api/portfolio/performance (PORTFOLIO-QUOTE-GAPS T1)`.

## 5. Acceptance mapping (#658)

| #658 acceptance | Where |
|---|---|
| Root cause recorded; fixed with a test if a defect | §1.1, comment on #658; not a code defect → no code fix; data fix = Q1 |
| `/performance` returns last snapshot date + skipped-contract list; tests cover skip and write days | Task 1, tests 2–5 |
| Snapshot policy decided by Kenneth (or kept) and recorded in `PROJECT_STATE.json` | Q2 pending → `needs-kenneth`; recorded in the phase entry when answered |
| Python 3.11; backend tests green; plan + code audit clean | §4 Green; audits per `audit_rule` |

## 6. Audit gate (paste into every auditor brief)

A finding blocks only if it can put a **wrong number in front of a user or on a broker
order**, or **corrupt persisted data**. A comment blocks only if it misstates mechanism.
Here that means: any path where the new fields claim a skip that did not happen or hide
one that did (the frontend will show them as the reason the curve is stale); any change
to the existing curve/bucket numbers; any new or removed write to `equity_snapshots` or
any other table.

## 7. Completion milestones (task-ratings.md)

0% → 10% this plan drafted → 20% plan audit clean → 50% T1 built → 70% full backend
suite + typecheck green → 85% code audit clean → 95% PR head CI green and pre-merge
conditions (blocked while `needs-kenneth` is on #658) → 100% merged + verified.
