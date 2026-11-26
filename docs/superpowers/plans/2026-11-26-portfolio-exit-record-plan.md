# PORTFOLIO-EXIT-RECORD — implementation plan (#664)

Board item / tracking issue: #664 · Branch: `board/portfolio-exit-record-878aec62` · Umbrella: #656
Ratings: size L · complexity 4 (persistence change: new columns + Alembic migration, close flow, History tab).

## Goal

Record **why** each trade was closed and **what stop it had** at that moment, so the History tab judges
stop discipline against the real plan instead of today's global setting.

## Out of scope

Auto-closing positions; broker-side close routing (the disabled "Also send to broker" stub stays as is);
back-filling old rows (old rows stay NULL — never guessed).

## Facts this plan relies on (checked against `origin/main` @ 88b157ed)

- `backend/app/models/closed_position.py` — `ClosedPositionModel`, one row per sell event (a partial
  close writes one row and reduces the open position's `qty`).
- `backend/app/routers/portfolio.py:564-642` `close_position` — the only writer of `closed_positions`
  rows from a close. It re-reads `position` under `lock_exposure` before building the row; the snapshot
  must be read from **that** locked `position`, not the pre-lock `preview`.
- `backend/app/schemas/__init__.py:1549` `ClosePositionRequest`, `:1560` `ClosedPositionSchema`
  (+ `from_orm_model`). The only caller of `POST /api/portfolio/{rec_id}/close` is
  `frontend/lib/portfolioStore.ts` `closePositionRemote` (~line 1639).
- Per-position premium stop: `PortfolioPositionModel.premium_stop_pct` (NULL = inherit global),
  resolved only through `backend/app/services/premium_stop.py` `resolve_premium_stop_pct(position_pct,
  global_pct)`; threshold price `premium_stop_threshold_price(entry, pct)`. The backend global comes
  from `services/position_writer.py:_global_premium_stop_pct()` (risk_rules.yaml →
  `reward_risk.premium_stop_pct`, which `routers/risk_settings.py` writes from the Settings page), and
  returns `None` when it cannot be loaded.
- `stop` / `structural_stop` on the open position are already floored (non-positive → NULL) by every
  write path (`_floor_stop`).
- Alembic: `backend/migrations/` (config `migrations/alembic.ini`), single head `d6a2f9c4e017`
  (`tests/test_alembic_heads.py` enforces exactly one head). Migration tests run Alembic against a
  temp sqlite file (`tests/test_broker_attempts_migration.py` pattern); Postgres cases are gated on an
  explicit env URL and skip otherwise (`tests/test_history_large_writes.py` pattern).
- Frontend: `ClosedPosition` type in `frontend/lib/performanceStore.ts:4`; CSV in
  `frontend/lib/portfolioHistory.ts` `toHistoryCsv`; exit check / stats in `frontend/lib/tradeStats.ts`
  (`exitCheck(h, stopPct)`, `computeTradeStats(rows, stopPct)` — the file header names #664 as the
  extension point); History tab + close dialog wiring in `frontend/app/(frame)/portfolio/page.tsx`
  (`premiumStopPct` from `settingsStore`, `exitCheck` at ~536, `computeTradeStats` at ~184,
  `ClosePositionDrawer` at ~826); derived status in `frontend/lib/positionStatus.ts`
  `derivePositionStatus` (breach `stop | structural | premium`), alert types from
  `frontend/lib/alertEngine.ts` `scanPortfolio` (`TP_HIT`, `TIME_STOP`, …).

## Design

### Stored fields (all nullable; old rows stay NULL)

| Column (`closed_positions`) | API field | Value written at close |
|---|---|---|
| `exit_reason` String(20) | `exitReason` | one of `stop`, `structural_stop`, `premium_stop`, `target`, `time_stop`, `expiry`, `manual`, `unknown`; NULL when the request omits it |
| `stop_at_close` Float | `stopAtClose` | locked `position.stop` (already floored; NULL stays NULL) |
| `structural_stop_at_close` Float | `structuralStopAtClose` | locked `position.structural_stop` |
| `premium_stop_pct_at_close` Float | `premiumStopPctAtClose` | **option rows only**: `resolve_premium_stop_pct(position.premium_stop_pct, _global_premium_stop_pct())`, **except** NULL when the position inherits (`premium_stop_pct is None`) and the global could not be loaded (`None`) — the 0.60 last-resort fallback is a guess and is never persisted. Stock rows (`contract` ends `\|STOCK`): NULL (no premium stop applies). |
| `premium_stop_price_at_close` Float | `premiumStopPriceAtClose` | option rows with a stored pct: `premium_stop_threshold_price(position.entry_price, pct)` (per-share option price at which the stop fires); otherwise NULL |

Partial closes: each close row carries its own snapshot taken from the locked position at that close.
No other table changes. `record_realized_loss`, P&L math and the position reduce/delete are untouched.

### API

- `ClosePositionRequest.exitReason: Optional[Literal[...the 8 values...]] = None`. Anything else → 422
  (Pydantic). Omitted / null → stored NULL ("not recorded"), so an older client cannot break closes.
- `ClosedPositionSchema` gains the five fields (all `Optional`, default None) and `from_orm_model`
  maps them. `GET /api/portfolio/history` and the close response return them.

### Migration

New revision `down_revision = 'd6a2f9c4e017'`. `upgrade`: five `op.add_column(..., nullable=True)` with
no server default (existing rows read NULL). `downgrade`: drop the five columns inside
`op.batch_alter_table('closed_positions')` (sqlite needs batch for drop). Exactly one head afterwards.

### Close dialog (frontend)

- New pure helper `frontend/lib/exitReason.ts`:
  - `EXIT_REASONS` (ordered list) + `ExitReason` type + `exitReasonLabel(r | null | undefined)` →
    `Stop`, `Structural stop`, `Premium stop`, `Target`, `Time stop`, `Expiry`, `Manual`, `Unknown`,
    and `Not recorded` for null/undefined.
  - `defaultExitReason(p: PortfolioPosition, opts: { premiumStopPct: number; exitDate: string })`,
    first match wins: `derivePositionStatus(p, {premiumStopPct}).breach` `stop`→`stop`,
    `structural`→`structural_stop`, `premium`→`premium_stop`; option whose expiry (from
    `parseContractId(p.contract)`) is on/before `exitDate` → `expiry`; `scanPortfolio` reports
    `TIME_STOP` → `time_stop`; reports `TP_HIT` → `target`; otherwise `manual`.
- `ClosePositionDrawer` gets a "Reason" `<select>` (all 8 values, labels from `exitReasonLabel`),
  required, pre-selected from `defaultExitReason` (computed once on open; the page passes
  `premiumStopPct`), always editable; `onConfirm` opts gain `exitReason`. Label weight 400, CSS Module,
  tokens only (repo conventions).
- `closePositionRemote` opts and request body gain `exitReason` (sent as given; `?? null`).
  `page.tsx` `confirmClose` passes it through.

### History tab + CSV (frontend)

- `ClosedPosition` type gains the five optional fields (`?: T | null`).
- `toHistoryCsv` appends, **after** the existing last column `P&L %`, in this order:
  `Exit Reason` (`exitReasonLabel`), `Stop at Close`, `Structural Stop at Close`,
  `Premium Stop % at Close` (fraction × 100, 2 dp), `Premium Stop Price at Close` (2 dp); empty cell
  when null. Existing columns and their order are unchanged.
- History table: new "Exit reason" column showing `exitReasonLabel(h.exitReason)`.
- Exit check uses the stop in force for that trade: `stopPctFor(h, globalPct) =
  h.premiumStopPctAtClose ?? globalPct`, returning also `source: 'stored' | 'global'`.
  - `exitCheck(h, stopPctFor(h, g).pct)` per row; the cell tooltip says which: stored →
    "Premium stop at close: N%"; global → "Stop not recorded for this trade — using today's
    N% premium stop".
  - `computeTradeStats(rows, globalPct)` keeps its signature but evaluates each row's exit check with
    that row's `stopPctFor` (so `pastStop` counts use the stored stop when present). `exitCheck`
    itself is unchanged.
  - The column header tooltip / stats strip wording that today says "global premium stop" is updated
    to say stored-when-recorded, else today's global.

## Tickets (sequential; each ends green on its own)

| # | Ticket | Files | Blocked by |
|---|---|---|---|
| T1 | Backend: columns, migration, schemas, close snapshot | `backend/app/models/closed_position.py`, new `backend/migrations/versions/<rev>_closed_position_exit_record.py`, `backend/app/schemas/__init__.py`, `backend/app/routers/portfolio.py`, new `backend/tests/test_exit_record.py` (+ migration test) | — |
| T2 | Frontend: close dialog reason + API plumbing + CSV | `frontend/lib/exitReason.ts` (new), `frontend/lib/performanceStore.ts` (type), `frontend/lib/portfolioStore.ts` (`closePositionRemote`), `frontend/components/organisms/ClosePositionDrawer/*`, `frontend/app/(frame)/portfolio/page.tsx` (confirmClose + drawer prop), `frontend/lib/portfolioHistory.ts`, tests | T1 |
| T3 | Frontend: History exit-reason column + stored-stop exit check | `frontend/lib/tradeStats.ts`, `frontend/app/(frame)/portfolio/page.tsx`, `TradeStatsStrip` if its wording names the global stop, tests | T2 (same page file) |
| T4 | Coordinator: acceptance, `git merge origin/main`, code audit, PR | — | T1–T3 |

### Tests required (test-first)

T1:
- Close an option with an explicit `premium_stop_pct` → row stores that pct, price = entry×(1−pct),
  `stop`/`structural_stop` copied, `exitReason` stored.
- Close an option inheriting the global (monkeypatch `_global_premium_stop_pct` → 0.5) → pct 0.5.
- Inheriting with global `None` → pct and price NULL (never 0.60).
- Stock close → premium fields NULL, stops copied.
- Partial close then full close of the same position → two rows, each with its own snapshot (change
  the position's stop between the two closes; each row holds the value at its close).
- Omitted `exitReason` → NULL; invalid value → 422 and **no** row written, position unchanged.
- `GET /api/portfolio/history` returns the five fields.
- Migration on a temp sqlite DB created at `d6a2f9c4e017` with an existing `closed_positions` row:
  upgrade → columns exist, row unchanged with NULLs; downgrade → columns gone, row intact.
  Postgres variant gated on `EXIT_RECORD_TEST_POSTGRES_URL` (skips without it). Single head test
  still passes.

T2: `defaultExitReason` for each branch (stop / structural / premium breach, expiry, time stop,
target, manual, breach beats target); drawer renders the select pre-selected and sends the edited
value in `onConfirm`; `closePositionRemote` body includes `exitReason`; CSV appends the five columns
after `P&L %` with empty cells for nulls and unchanged earlier columns.

T3: exit check uses stored pct when present (a 45% loss with stored 0.40 → past stop while global
0.60 says within) and the global when absent, with the source in the tooltip; `computeTradeStats`
`pastStop` counts follow per-row stops; Exit reason column shows labels and "Not recorded".

## Acceptance (from #664)

- [ ] Alembic upgrade/downgrade tested on sqlite and Postgres; existing closed rows unchanged (NULLs).
      Postgres: coordinator runs the gated test against a throwaway database on the local Postgres if
      reachable; otherwise listed under "Needs Kenneth".
- [ ] Close flow stores reason and stop snapshot; partial closes store them per close row.
- [ ] History shows the reason; exit check uses the stored stop when present (tests for both).
- [ ] Python 3.11; backend + frontend tests and typecheck green; plan audit and code audit clean.

## Gate (paste into every auditor brief)

A finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or
**corrupt persisted data**. A comment blocks only if it misstates mechanism. Nothing else is reported.
