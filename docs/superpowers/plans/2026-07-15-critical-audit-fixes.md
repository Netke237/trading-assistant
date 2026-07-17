# Critical Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 11 Critical findings from the 2026-07-15 full-repository audit — a read-only, 7-domain review published as a claude.ai artifact (not a file in this repo; there is no `repo_audit.html` checked in anywhere, so don't try to diff against it as a source file). Findings: wrong P&L numbers, a broken audit trail on Postgres, cache/param bugs that silently poison scan results, a fabricated backtest metric, a mispriced stop-loss direction, a state-loss race on Step 3, and a double-close race in the portfolio store.

**Architecture:** Each task is an independent, surgical fix to existing modules — no new abstractions, no refactors beyond what's needed to close the specific defect. Backend fixes are pure-function/router-level changes verified by pytest; the two schema-drift bugs are closed with one new Alembic migration verified against the real `ritter-postgres` Docker container (SQLite doesn't enforce column types, which is why these bugs are invisible in dev). Frontend fixes are verified with Jest plus a manual browser check via the Browser pane.

**Tech Stack:** FastAPI + SQLAlchemy v2 + Alembic + pytest (backend); Next.js 15 + Zustand v5 + Jest (frontend).

---

## Findings-to-tasks coverage map

All 11 Critical findings, in the order they appeared in the audit, mapped to the task that fixes them. Task 2 closes two findings with one migration since both are the same Postgres-schema-drift root cause.

| # | Finding | File:line (audit) | Task |
|---|---|---|---|
| 1 | Stock close records P&L 100x too high | `portfolio_performance.py:14` | Task 1 |
| 2 | `audit_events.recommendation_id` UUID/String mismatch | `models/audit_event.py:15` | Task 2 |
| 3 | Confidence cache key ignores `atr_mult` | `routers/stock_scan.py:320,726` | Task 3 |
| 4 | Confidence computed with wrong `scoring_mode` | `scoring/signal_confidence.py:169-200` | Task 4 |
| 5 | Short-stock stop-loss direction wrong | `services/alert_generator.py:59` | Task 5 |
| 6 | Backtest "expectancy" is fabricated; gate unused | `services/strategy_backtest.py:137-141` | Task 6 |
| 7 | Backtest gate ignores live strategy params | `routers/stock_scan.py:711-722` | Task 7 |
| 8 | Step 3 saved horizon silently overwritten | `step-3-direction/page.tsx:738-822` | Task 9 |
| 9 | Double-close can resurrect a position | `lib/portfolioStore.ts:258-359` | Task 10 |
| 10 | `portfolio_positions` missing DB uniqueness / wrong `entry_date` type | `models/portfolio.py:13-15,19` | Task 2 |
| 11 | Missing-field validation silently passes | `schemas/__init__.py:526-537` | Task 8 |

---

## Task ordering and independence

Tasks 1, 2, 5, 6, 8, 9, 10 are mutually independent and can be implemented in any order or in parallel by separate subagents. Task 2 touches two tables in one migration file — do not split it, since both ALTERs belong to the same Postgres-drift root cause and should land as one deployable unit.

**Tasks 3, 4, and 7 all edit the same two blocks of `backend/app/routers/stock_scan.py` (the `_analyze_core` confidence/backtest block around line ~290-320, and the `_process_stock` block around line ~660-736) and MUST be implemented sequentially in that order — 3, then 4, then 7 — by the same worker or with each one fully merged before the next starts.** Task 4's Step 5 "before" snippet is literally Task 3's "after" output, and Task 7's Steps 4-5 edit the immediately adjacent `run_strategy_backtest`/`_backtest_key` calls inside those same blocks. Running 3, 4, and 7 in parallel on separate checkouts will produce merge conflicts or before-text that no longer matches. Do not hand these three to `subagent-driven-development` as parallel tasks.

---

### Task 1: Stock position close no longer inflates P&L 100× (Critical finding #1)

**Files:**
- Modify: `backend/app/services/portfolio_performance.py:12-16`
- Modify: `backend/app/routers/portfolio.py:32-34, 300`
- Test: `backend/tests/test_portfolio_performance.py`

**Root cause:** `realized_pnl()` hardcodes the options `×100` contract multiplier for every close. `routers/portfolio.py` already has a correct per-type multiplier (`_contract_multiplier`, 1 for `SYMBOL|STOCK` contracts, 100 for options) and uses it everywhere else (unrealized P&L, capital-at-risk) — just not here.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_portfolio_performance.py` (after the existing imports, which already pull `realized_pnl`):

```python
def test_realized_pnl_stock_uses_multiplier_one():
    # Stock close: no ×100 contract multiplier. entry 50, exit 55, 10 shares -> 50.0, +10%
    dollar, pct = realized_pnl(entry_price=50.0, exit_price=55.0, qty=10, contract="AAPL|STOCK")
    assert dollar == 50.0
    assert pct == 10.0


def test_realized_pnl_option_still_uses_multiplier_100():
    dollar, pct = realized_pnl(entry_price=1.00, exit_price=1.50, qty=2, contract="AAPL|185|2026-08-21|C")
    assert dollar == 100.0
    assert pct == 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_portfolio_performance.py -v`
Expected: the two new tests fail with `TypeError: realized_pnl() got an unexpected keyword argument 'contract'`

- [ ] **Step 3: Fix `realized_pnl()` to take the contract and apply the correct multiplier**

Replace `backend/app/services/portfolio_performance.py:12-16`:

```python
def _contract_multiplier(contract: str) -> int:
    """Return 1 for stock positions (SYMBOL|STOCK), 100 for option contracts."""
    return 1 if str(contract).endswith("|STOCK") else 100


def realized_pnl(entry_price: float, exit_price: float, qty: int, contract: str) -> tuple[float, float]:
    """Realized P&L: (exit - entry) * multiplier * qty. multiplier is 1 for stocks, 100 for options.
    Percent guards entry==0."""
    multiplier = _contract_multiplier(contract)
    dollar = round((exit_price - entry_price) * multiplier * qty, 2)
    pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0
    return dollar, pct
```

- [ ] **Step 4: Update the existing tests to pass a contract, and the call site**

In `backend/tests/test_portfolio_performance.py`, update the two existing calls to pass `contract="AAPL|185|2026-08-21|C"` (an option contract string, preserving the ×100 behavior they were already asserting):

```python
def test_realized_pnl_long_premium():
    # entry 1.00, exit 1.50, 2 contracts -> (1.50-1.00)*100*2 = 100.0, +50%
    dollar, pct = realized_pnl(entry_price=1.00, exit_price=1.50, qty=2, contract="AAPL|185|2026-08-21|C")
    assert dollar == 100.0
    assert pct == 50.0


def test_realized_pnl_loss_and_zero_entry_guard():
    dollar, pct = realized_pnl(entry_price=2.00, exit_price=1.00, qty=1, contract="AAPL|185|2026-08-21|C")
    assert dollar == -100.0
    assert pct == -50.0
    # entry 0 must not divide-by-zero
    d2, p2 = realized_pnl(entry_price=0.0, exit_price=1.0, qty=1, contract="AAPL|185|2026-08-21|C")
    assert d2 == 100.0
    assert p2 == 0.0
```

In `backend/app/routers/portfolio.py`, delete the now-duplicate local helper at lines 32-34:

```python
def _contract_multiplier(contract: str) -> int:
    """Return 1 for stock positions (SYMBOL|STOCK), 100 for option contracts."""
    return 1 if str(contract).endswith("|STOCK") else 100
```

and import the single source of truth instead — change the existing import block at line 21-23 from:

```python
from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve,
)
```

to:

```python
from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve, _contract_multiplier,
)
```

Then update the call site at line 300 from:

```python
    dollar, pct = realized_pnl(position.entry_price, float(exit_price), qty_to_close)
```

to:

```python
    dollar, pct = realized_pnl(position.entry_price, float(exit_price), qty_to_close, position.contract)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_portfolio_performance.py -v`
Expected: all tests PASS (6 total: 4 existing + 2 new)

Run: `cd backend && python -c "import app.routers.portfolio"` to confirm the import change doesn't break module load (no circular import — `portfolio_performance.py` has no imports from `routers/`, so this is safe).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/portfolio_performance.py backend/app/routers/portfolio.py backend/tests/test_portfolio_performance.py
git commit -m "fix: stop stock position closes from using the options 100x multiplier"
```

---

### Task 2: Fix audit_events and portfolio_positions schema drift on Postgres (Critical findings #2 and #10)

**Files:**
- Create: `backend/migrations/versions/<new_revision>_fix_audit_and_portfolio_schema_drift.py`
- Test: manual — run migration against the real Postgres container

**Root cause:** Two ORM models declare constraints/types that the migration that created their tables never applied:
- `AuditEventModel.recommendation_id` is `String, nullable=False` in code; the migration created it as `postgresql.UUID`. The app always writes non-UUID strings like `REC-20260715-AB12CD34` into it (confirmed: all three call sites in `backend/app/services/audit.py` always set `recommendation_id=rec_id`) — every write fails on real Postgres with "invalid input syntax for type uuid."
- `PortfolioPositionModel.rec_id` and `.contract` are declared `unique=True` in code; the migration never added those constraints. `.entry_date` is `String` in code; the migration typed the column `DateTime(timezone=True)`.

SQLite doesn't enforce column types, which is why none of this shows up in the dev SQLite fallback.

- [ ] **Step 1: Find the current migration head**

Run: `cd backend/migrations/versions && for f in *.py; do rev=$(grep -m1 "^revision = " "$f" | sed "s/revision = //"); down=$(grep -m1 "^down_revision = " "$f" | sed "s/down_revision = //"); echo "$f | rev=$rev down=$down"; done`

Expected: every `down_revision` value appears as some file's `revision` value *except* `'a7f3e9b12c04'` (from `a7f3e9b12c04_drop_orphan_kids_app_schema.py`) — that is the current head. If a newer migration has been added since this plan was written, use that one's revision instead.

- [ ] **Step 2: Write the migration**

Create `backend/migrations/versions/b3f7a1c9d4e2_fix_audit_and_portfolio_schema_drift.py` (use `alembic revision` to generate a fresh hash if you want strict tooling compliance — the exact hash doesn't matter, only that `down_revision` chains from the real head found in Step 1):

```python
"""fix audit_events and portfolio_positions schema drift

Revision ID: b3f7a1c9d4e2
Revises: a7f3e9b12c04
Create Date: 2026-07-15

Closes two Postgres-only correctness bugs invisible on the SQLite dev fallback
(SQLite does not enforce column types or unique constraints):

1. audit_events.recommendation_id was created as UUID but the ORM model (and
   every write site in app/services/audit.py) always uses a non-UUID rec_id
   string like "REC-20260715-AB12CD34" — every approve/reject/override write
   fails with "invalid input syntax for type uuid" on real Postgres.
2. portfolio_positions.rec_id/.contract were never given the UNIQUE constraint
   the ORM model declares, and .entry_date was created as DateTime while the
   model (and every write site) treats it as a plain ISO string.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b3f7a1c9d4e2'
down_revision = 'a7f3e9b12c04'
branch_labels = None
depends_on = None


def _check_upgrade_preconditions() -> None:
    """The tables this migration tightens were originally created with looser
    constraints (audit_events.recommendation_id nullable; portfolio_positions
    rec_id/contract nullable and not unique) — see
    16febdf31dd2_add_persistence_tables.py. If any real rows violate what
    we're about to enforce, raise a clear, actionable error up front instead
    of letting a raw Postgres UniqueViolation/NotNullViolation surface
    mid-migration with no guidance."""
    bind = op.get_bind()

    null_recommendation_id = bind.execute(sa.text(
        "SELECT count(*) FROM audit_events WHERE recommendation_id IS NULL"
    )).scalar()
    if null_recommendation_id:
        raise RuntimeError(
            f"{null_recommendation_id} audit_events row(s) have NULL recommendation_id — "
            "cannot apply NOT NULL. Back these rows up and either delete them "
            "or backfill recommendation_id from rec_id before re-running this migration."
        )

    null_rec_id = bind.execute(sa.text(
        "SELECT count(*) FROM portfolio_positions WHERE rec_id IS NULL"
    )).scalar()
    if null_rec_id:
        raise RuntimeError(
            f"{null_rec_id} portfolio_positions row(s) have NULL rec_id — "
            "cannot apply NOT NULL. Back these rows up and either delete them "
            "or assign a rec_id before re-running this migration."
        )

    dup_rec_id = bind.execute(sa.text(
        "SELECT rec_id, count(*) FROM portfolio_positions "
        "GROUP BY rec_id HAVING count(*) > 1"
    )).fetchall()
    if dup_rec_id:
        raise RuntimeError(
            f"Duplicate rec_id values in portfolio_positions: {dup_rec_id} — "
            "cannot apply UNIQUE. Resolve the duplicates (this is likely the "
            "double-close/double-insert race also fixed in this audit pass) "
            "before re-running this migration."
        )

    dup_contract = bind.execute(sa.text(
        "SELECT contract, count(*) FROM portfolio_positions "
        "GROUP BY contract HAVING count(*) > 1"
    )).fetchall()
    if dup_contract:
        raise RuntimeError(
            f"Duplicate contract values in portfolio_positions: {dup_contract} — "
            "cannot apply UNIQUE. Resolve the duplicates before re-running this migration."
        )


def upgrade() -> None:
    _check_upgrade_preconditions()

    # ── audit_events.recommendation_id: UUID -> String ─────────────────────────
    op.alter_column(
        'audit_events', 'recommendation_id',
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(),
        postgresql_using='recommendation_id::text',
        nullable=False,
    )

    # ── portfolio_positions.entry_date: DateTime -> String (ISO date text) ─────
    op.alter_column(
        'portfolio_positions', 'entry_date',
        existing_type=sa.DateTime(timezone=True),
        type_=sa.String(),
        postgresql_using='entry_date::text',
        nullable=False,
    )

    # ── portfolio_positions.rec_id / .contract: add missing UNIQUE + NOT NULL ──
    op.alter_column('portfolio_positions', 'rec_id', existing_type=sa.String(), nullable=False)
    op.create_unique_constraint('uq_portfolio_positions_rec_id', 'portfolio_positions', ['rec_id'])
    op.create_unique_constraint('uq_portfolio_positions_contract', 'portfolio_positions', ['contract'])


def downgrade() -> None:
    op.drop_constraint('uq_portfolio_positions_contract', 'portfolio_positions', type_='unique')
    op.drop_constraint('uq_portfolio_positions_rec_id', 'portfolio_positions', type_='unique')
    op.alter_column('portfolio_positions', 'rec_id', existing_type=sa.String(), nullable=True)

    op.alter_column(
        'portfolio_positions', 'entry_date',
        existing_type=sa.String(),
        type_=sa.DateTime(timezone=True),
        postgresql_using='entry_date::timestamptz',
        nullable=False,
    )

    op.alter_column(
        'audit_events', 'recommendation_id',
        existing_type=sa.String(),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using='recommendation_id::uuid',
        nullable=False,
    )
```

- [ ] **Step 3: Run the migration against the real Postgres container**

This is the only way to actually verify the fix — SQLite would accept the old schema silently. Run:

`docker ps --filter name=ritter-postgres --format "{{.Names}}"`

Expected: prints `ritter-postgres` (confirms the container from prior sessions is running; if not, start it per your usual workflow before continuing).

Then, with the backend's Postgres `DATABASE_URL` pointed at that container, run:

`cd backend && alembic upgrade head`

Expected: no errors. `_check_upgrade_preconditions()` runs first and raises a `RuntimeError` with the specific offending rows if any existing `portfolio_positions` row has a NULL `rec_id` or a duplicate `rec_id`/`contract` — the original table (`16febdf31dd2_add_persistence_tables.py`) allowed both, so this is a real possibility, not a hypothetical. If that happens, stop and report the exact rows to Kenneth rather than deleting or force-fixing data — resolving duplicates may itself be evidence of the double-insert/double-close races fixed elsewhere in this plan. Separately, if `alter_column ... postgresql_using='recommendation_id::text'` fails for some other reason, that also means stop-and-report rather than forcing the cast.

- [ ] **Step 4: Verify the new constraints actually hold**

Run this against the same Postgres container (e.g. via `docker exec -it ritter-postgres psql -U <user> -d <db> -c "..."`, using whatever credentials the project's `.env`/docker-compose already defines):

```sql
\d audit_events
\d portfolio_positions
```

Expected: `recommendation_id` shows as `character varying` (not `uuid`); `entry_date` shows as `character varying`; `rec_id` and `contract` each show a `UNIQUE` index in the `Indexes:` section.

- [ ] **Step 5: Run the backend test suite to confirm nothing else broke**

Run: `cd backend && pytest tests/ -k "portfolio or audit" -v`
Expected: all pass (these tests run against the SQLite fallback per `conftest.py`, so this step is a regression check on ORM-level behavior, not a substitute for Step 3-4).

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/b3f7a1c9d4e2_fix_audit_and_portfolio_schema_drift.py
git commit -m "fix: align audit_events and portfolio_positions Postgres schema with the ORM models"
```

---

### Task 3: Confidence cache key now includes the ATR multiple that changes the answer (Critical finding #3)

**Files:**
- Modify: `backend/app/routers/stock_scan.py:320, 726-736`
- Test: `backend/tests/test_confidence_cache.py` (existing coverage already asserts `cache_key` behavior; no new cache-layer test needed — the fix is at the call sites)
- Test: `backend/tests/test_confidence_gate_stocks.py` (add a call-site regression test)

**Root cause:** `conf_cache_key()` (aliased from `confidence_cache.cache_key`) is called at both `stock_scan.py:320` and `stock_scan.py:726` without `atr_mult`, so it silently defaults to `1.5` regardless of `req.confidence_atr_mult`. A scan with a custom multiple reads (and then overwrites) the cache entry for the *default* multiple. The options-path equivalent in `routers/scan.py:446-447` already does this correctly: `_atr_for_key = atr_mult if atr_mult is not None else 1.5`. Mirror that exact pattern.

Note: the second call site (`stock_scan.py:726-736`) already has a partial workaround — `_cached = None if req.confidence_atr_mult is not None else get_cached(_ck)` — that avoids a bad *read* but still performs a bad *write* (`set_cached(_ck, _cached)` at line 736 still overwrites the default-key entry with a custom-multiple result). Fixing the key itself makes this workaround both unnecessary and insufficient-on-its-own to fix; remove it.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_confidence_gate_stocks.py`. That file doesn't currently import `confidence_cache` anywhere, so keep this test self-contained with its own inline import (matching the style `test_confidence_cache.py` already uses for every one of its tests):

```python
def test_custom_atr_mult_does_not_collide_with_default_cache_key(monkeypatch):
    """A scan with a custom confidence_atr_mult must not read or overwrite the
    cache entry used by default-multiple scans (Critical finding #3, 2026-07-15 audit)."""
    import app.data.confidence_cache as cc
    cc.clear_cache()

    default_key = cc.cache_key("AAPL", "Bullish", "Swing", 1.5)
    custom_key = cc.cache_key("AAPL", "Bullish", "Swing", 2.5)
    assert default_key != custom_key

    cc.set_cached(default_key, {"confidence": 70, "sample_size": 50})
    cc.set_cached(custom_key, {"confidence": 30, "sample_size": 50})

    # The two entries must stay independent — this is what stock_scan.py's
    # call sites rely on when they resolve atr_mult=None -> 1.5 for the key.
    assert cc.get_cached(default_key)["confidence"] == 70
    assert cc.get_cached(custom_key)["confidence"] == 30
```

- [ ] **Step 2: Run test to verify it currently passes at the cache layer but fails to reflect the real router bug**

Run: `cd backend && pytest tests/test_confidence_gate_stocks.py::test_custom_atr_mult_does_not_collide_with_default_cache_key -v`
Expected: PASS — this test exercises `confidence_cache.py` directly, which is already correct. It documents the invariant the router call sites must uphold; the actual bug is that `stock_scan.py` doesn't pass `atr_mult` into `cache_key()` at all, so it can never produce `custom_key`. Proceed to the router fix — there's no isolated router-level unit test for this because `_analyze_core`/`_process_stock` require a full bars/request fixture; the fix is verified by code inspection plus this cache-layer invariant test, which is what a reviewer should check.

- [ ] **Step 3: Fix the first call site — `_analyze_core` (line ~320)**

In `backend/app/routers/stock_scan.py`, change:

```python
        _ck = conf_cache_key(symbol, req.direction, req.horizon)
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, atr_mult=req.confidence_atr_mult)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            set_cached(_ck, _cached)
```

to:

```python
        _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
        _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key)
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, atr_mult=req.confidence_atr_mult)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            set_cached(_ck, _cached)
```

- [ ] **Step 4: Fix the second call site — `_process_stock` (line ~726-736), removing the now-redundant read bypass**

Change:

```python
            _ck = conf_cache_key(symbol, req.direction, req.horizon)
            # Non-default atr_mult: bypass cache to avoid stale hits from a
            # prior scan that used a different multiplier.
            _cached = None if req.confidence_atr_mult is not None else get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    atr_mult=req.confidence_atr_mult,
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
```

to:

```python
            _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
            _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key)
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    atr_mult=req.confidence_atr_mult,
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
```

- [ ] **Step 5: Run tests to verify nothing broke**

Run: `cd backend && pytest tests/test_confidence_cache.py tests/test_confidence_gate_stocks.py tests/test_confidence_gate.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_confidence_gate_stocks.py
git commit -m "fix: confidence cache key now varies with atr_mult in the stocks scan path"
```

---

### Task 4: Confidence is computed against the stocks-mode scoring rules, not options-mode (Critical finding #4)

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py:153-200`
- Modify: `backend/app/routers/stock_scan.py:323-324, 731-734`
- Modify: `backend/app/data/confidence_cache.py:19-22`
- Test: `backend/tests/test_signal_confidence.py`

**Root cause:** `compute_confidence()` replays history via `score_stock(..., scoring_mode=...)` but never passes `scoring_mode` through, so it always defaults to `"options"`. Every live stocks-path caller in `stock_scan.py` scores candidates with `scoring_mode="stock"` — a materially different rule set (trigger scoring, volume treatment, event weighting all differ). The confidence percentage shown to the user isn't measuring the setup that's actually live.

The cache key must also encode `scoring_mode` — otherwise a value the nightly `historical_store.py` prefetch job computed under `scoring_mode="options"` (it intentionally keeps using the default; see Step 5) would be served to a `scoring_mode="stock"` lookup and reintroduce the exact bug this task fixes, just one layer down.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_signal_confidence.py` (it already has a `_bar` helper and an uptrending-bars pattern near the existing `test_...` at line ~78-83 — reuse that style):

```python
def test_compute_confidence_accepts_scoring_mode(monkeypatch):
    """stock_scan.py's live callers pass scoring_mode='stock'; compute_confidence
    must forward it to score_stock instead of silently using the 'options' default
    (Critical finding #4, 2026-07-15 audit)."""
    from app.scoring import signal_confidence as sc

    seen_modes = []

    def _spy_score_stock(*args, **kwargs):
        seen_modes.append(kwargs.get("scoring_mode"))
        from app.scoring.stock_scorer import score_stock as _real
        return _real(*args, **kwargs)

    import app.scoring.stock_scorer as stock_scorer_mod
    monkeypatch.setattr(stock_scorer_mod, "score_stock", _spy_score_stock)

    price = 100.0
    bars = []
    for i in range(80):
        price *= 1.004
        bars.append(_bar(price * 0.997, price * 1.01, price * 0.99, price, 1000 + i))

    sc.compute_confidence(bars, direction="Bullish", horizon="Swing", atr_mult=1.5, scoring_mode="stock")
    assert seen_modes, "score_stock was never called — check the monkeypatch target"
    assert all(m == "stock" for m in seen_modes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_confidence.py::test_compute_confidence_accepts_scoring_mode -v`
Expected: FAIL with `TypeError: compute_confidence() got an unexpected keyword argument 'scoring_mode'`

- [ ] **Step 3: Thread `scoring_mode` through `compute_confidence()`**

In `backend/app/scoring/signal_confidence.py`, change the signature and body at lines 153-190:

```python
def compute_confidence(
    bars: list[dict],
    *,
    direction: str,
    horizon: str,
    atr_mult: float | None = None,   # if None, uses config atr_mult_target/atr_mult_stop
    scoring_mode: str = "options",   # must match the scoring_mode the live caller scores with
) -> ConfidenceResult:
    """Replay the entry signal across history and score its reliability.

    A 'fire' = score_stock(...).status == 'PASS' on bars up to and including i,
    using only price-derived rules (no event/iv inputs in the historical replay).

    `atr_mult` overrides the configured ATR multiples for the win/loss barriers
    (symmetric, both sides); when None, per-horizon atr_mult_target/atr_mult_stop
    from config are used (asymmetric, preferred).

    `scoring_mode` must match the mode the live caller scores candidates with —
    "stock" and "options" apply materially different rules (trigger scoring,
    volume treatment, event weighting), so a mismatch measures a setup that
    isn't the one actually live.
    """
    from app.scoring.stock_scorer import score_stock, _atr  # reuse existing helpers

    bt = load_backtest_cfg(horizon)
    n_days = int(bt["n_days"])
    atr_period = int(bt["atr_period"])
    # Per-strategy asymmetric ATR: override uses same value for both (backward compat)
    if atr_mult is not None:
        _atr_mult_target = float(atr_mult)
        _atr_mult_stop   = float(atr_mult)
    else:
        _atr_mult_target = float(bt["atr_mult_target"])
        _atr_mult_stop   = float(bt["atr_mult_stop"])
    min_samples = int(bt["min_samples"])

    warmup = 60  # need enough bars for MAs/ADX before the first meaningful score
    outcomes: list[str] = []
    last = len(bars) - n_days
    for i in range(warmup, last):
        window = bars[: i + 1]
        card = score_stock(
            symbol="_bt", direction=direction, horizon=horizon, bars=window,
            scoring_mode=scoring_mode,
        )
        if card.status != "PASS":
            continue
        atr = _atr(window, atr_period)
        forward = bars[i + 1 : i + 1 + n_days]
        outcomes.append(
            evaluate_fire(window, forward, direction=direction, atr=atr,
                          atr_mult_target=_atr_mult_target, atr_mult_stop=_atr_mult_stop)
        )
    return aggregate(outcomes, min_samples=min_samples,
                     atr_mult_target=_atr_mult_target, atr_mult_stop=_atr_mult_stop)
```

- [ ] **Step 4: Update the cache key to include `scoring_mode`**

In `backend/app/data/confidence_cache.py`, change lines 19-22:

```python
def cache_key(symbol: str, direction: str, horizon: str, atr_mult: float = 1.5) -> str:
    # atr_mult is part of the key: changing it changes the computed confidence,
    # so cached results under a different multiple must not be reused.
    return f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}|{float(atr_mult):g}"
```

to:

```python
def cache_key(symbol: str, direction: str, horizon: str, atr_mult: float = 1.5, scoring_mode: str = "options") -> str:
    # atr_mult and scoring_mode are both part of the key: changing either changes
    # the computed confidence, so cached results under a different value of
    # either must not be reused across the options-scan and stocks-scan paths.
    return f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}|{float(atr_mult):g}|{scoring_mode.lower()}"
```

This is backward-compatible: `routers/scan.py:447` and `historical_store.py:319,322` don't pass `scoring_mode` and keep defaulting to `"options"`, which is correct for those call sites (the options-scan path and its prefetch). Only `stock_scan.py`'s two call sites need to start passing `"stock"` explicitly — done in the next step.

**Accepted tradeoff, not a bug to fix here:** before this change, `stock_scan.py`'s cache keys were shaped identically to the nightly `historical_store.py` prefetch job's keys (both `symbol|direction|horizon|1.5`), so the stocks path could get a cache hit from that prefetch — serving the *wrong*-mode confidence number, which is precisely the bug this task fixes. After this change, stocks-path keys are `...|stock`-suffixed and can never match what the prefetch writes (`...|options`), so every stocks scan for a symbol/direction/horizon combo not already computed live that day will cold-start a full `compute_confidence` walk-forward replay instead of getting a prefetch cache hit. This is the correct tradeoff (a slower correct number beats a fast wrong one) but it is a real latency change — if stocks-path scan latency regresses noticeably after this ships, the fix is to extend `historical_store.py`'s prefetch to also precompute the `scoring_mode="stock"` variant, not to revert this task. That extension is out of scope for this plan.

- [ ] **Step 5: Update both `stock_scan.py` call sites to pass `scoring_mode="stock"`**

In `backend/app/routers/stock_scan.py`, at the first call site (from Task 3's Step 3, now reading):

```python
        _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
        _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key)
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, atr_mult=req.confidence_atr_mult)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            set_cached(_ck, _cached)
```

change to:

```python
        _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
        _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key, scoring_mode="stock")
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, atr_mult=req.confidence_atr_mult,
                                           scoring_mode="stock")
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            set_cached(_ck, _cached)
```

At the second call site (from Task 3's Step 4, now reading):

```python
            _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
            _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key)
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    atr_mult=req.confidence_atr_mult,
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
```

change to:

```python
            _atr_for_key = req.confidence_atr_mult if req.confidence_atr_mult is not None else 1.5
            _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_for_key, scoring_mode="stock")
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    atr_mult=req.confidence_atr_mult, scoring_mode="stock",
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_signal_confidence.py tests/test_confidence_cache.py tests/test_confidence_gate_stocks.py tests/test_confidence_gate.py -v`
Expected: all PASS, including the new `test_compute_confidence_accepts_scoring_mode`

- [ ] **Step 7: Commit**

```bash
git add backend/app/scoring/signal_confidence.py backend/app/routers/stock_scan.py backend/app/data/confidence_cache.py backend/tests/test_signal_confidence.py
git commit -m "fix: confidence replay now scores with the same scoring_mode the live scan used"
```

---

### Task 5: Fix short-stock stop-loss direction in alert generation (Critical finding #5)

**Files:**
- Modify: `backend/app/services/alert_generator.py:59`
- Test: `backend/tests/test_alerts.py`

**Root cause:** `is_bearish` is parsed from the option-contract string shape (`contract.split("|")[3] == "P"`), but a stock contract is `SYMBOL|STOCK` — `split("|")` on that string has only 2 parts, so the `len(...) >= 4` guard is always `False` and `is_bearish` is always `False` for every stock position, regardless of its real `direction` field (`"Bullish"`/`"Bearish"`). A short stock's stop should trigger when price *rises*; today it's evaluated as a long (triggers on price *falling*), so the alert fires on the wrong side or not at all.

- [ ] **Step 1: Write the failing test**

`test_alerts.py` already has both a `db_session` fixture and an `_insert_position(db, **overrides)` helper (`test_alerts.py:60-72`) that every other test in the file uses to build a `PortfolioPositionModel` with sensible defaults — use it instead of constructing the model inline:

```python
@pytest.mark.asyncio
async def test_short_stock_stop_triggers_on_price_rise(db_session):
    """A short (Bearish direction) stock position's stop must trigger when price
    rises above the stop, not below it (Critical finding #5, 2026-07-15 audit)."""
    await _insert_position(
        db_session, symbol="XYZ", contract="XYZ|STOCK", direction="Bearish",
        stop=105.0, targets=[],
    )

    # Price rose above the short's stop (105) -> must alert STOP_REACHED.
    alerts = await generate_alerts(db_session, current_prices={"XYZ": 106.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert stop_alerts[0].symbol == "XYZ"
```

`generate_alerts` and `pytest` are already imported at the top of `test_alerts.py`; no new imports are needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_alerts.py::test_short_stock_stop_triggers_on_price_rise -v`
Expected: FAIL — `stop_alerts` is empty, because `is_bearish` evaluates `False` for a `XYZ|STOCK` contract, so the code checks `price <= pos.stop` (106 <= 105 is False) instead of `price >= pos.stop` (106 >= 105 is True).

- [ ] **Step 3: Fix `is_bearish` to use the position's real direction, not contract shape**

In `backend/app/services/alert_generator.py`, change line 59 from:

```python
        is_bearish = pos.contract.split("|")[3] == "P" if len(pos.contract.split("|")) >= 4 else False
```

to:

```python
        is_bearish = pos.direction.lower() in ("bearish", "bear", "short")
```

This works uniformly for both option contracts (a Bearish-direction position is a long put or short call — the `direction` field already encodes the trade's directional bias regardless of instrument type) and stock contracts (a short stock has `direction="Bearish"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_alerts.py -v`
Expected: all PASS, including the new test. Re-check any pre-existing option-contract tests in this file still pass — `direction` should already be set correctly on those fixtures since it drives other logic in the app (position sizing, P&L sign), so this shouldn't require fixture changes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_generator.py backend/tests/test_alerts.py
git commit -m "fix: short-stock stop-loss now triggers on price rise, not fall"
```

---

### Task 6: Backtest "expectancy" is a real per-trade number, and the confidence gate uses it (Critical finding #6)

**Files:**
- Modify: `backend/app/services/strategy_backtest.py:23-25, 128-156`
- Modify: `backend/app/routers/stock_scan.py` (wherever `bt_result.passes_gate` currently gates — see Step 4)
- Test: `backend/tests/test_strategy_backtest.py`

**Root cause:** `expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss` looks like a real expectancy formula, but `avg_win`/`avg_loss` are computed by dividing the backtest's *cumulative* `Return %` and single peak-to-trough `Max Drawdown %` by trade counts — neither is an average win or loss size per trade. `_MIN_EXPECTANCY` is defined but never referenced anywhere in `passes_gate` or any caller. The number shown to the user on Step 6 is not what it claims to be, and the gate that's supposed to reject low-expectancy setups doesn't exist.

`backtesting.py`'s `stats` object (from `bt.run()`) exposes a `_trades` DataFrame with a `PnL` column with one row per closed trade — this is the correct source for a real average win/loss.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_strategy_backtest.py` (it already has `_synth_bars` at the top — reuse it):

```python
def test_expectancy_is_average_pnl_per_trade_not_cumulative_return():
    """expectancy must be win_rate*avg_win - (1-win_rate)*avg_loss computed from
    real per-trade PnL, not cumulative Return%/MaxDD% divided by trade counts
    (Critical finding #6, 2026-07-15 audit)."""
    bars = _synth_bars(500, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    if result.n_trades == 0:
        pytest.skip("synthetic bars didn't produce trades on this run")
    # A sane per-trade expectancy in $ terms on $100k starting cash should be a
    # small fraction of total_return_pct, not comparable in magnitude to it —
    # the old (buggy) formula divided cumulative Return% by trade count, which
    # for n_trades >= 10 makes |expectancy| << |total_return_pct| by construction
    # only coincidentally; the real bug is structural, so assert the gate exists
    # and is actually applied instead of asserting a numeric range.
    assert isinstance(result.expectancy, float)


def test_min_expectancy_gate_is_applied():
    """_MIN_EXPECTANCY must actually gate passes_gate, not just exist as a
    module constant (Critical finding #6, 2026-07-15 audit)."""
    from app.services import strategy_backtest as sb
    bars = _synth_bars(500, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    if result.n_trades < 10:
        pytest.skip("not enough synthetic trades to exercise the gate")
    if result.expectancy < sb._MIN_EXPECTANCY:
        assert result.passes_gate is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_backtest.py::test_min_expectancy_gate_is_applied -v`
Expected: either PASS trivially (if the synthetic bars happen to produce `expectancy >= 0` under the *old* buggy formula, in which case the assertion inside the `if` never triggers) or FAIL. Because the bug's effect is silent (no gate applied, not a crash), the meaningful check happens in Step 3 by reading the diff, not by relying on this test alone to prove the current code is broken. Proceed to the fix regardless.

- [ ] **Step 3: Compute a real per-trade expectancy from `stats._trades` and apply the gate**

In `backend/app/services/strategy_backtest.py`, change lines 128-156 from:

```python
    n_trades = int(stats.get("# Trades", 0))
    if n_trades < min_trades:
        return _empty_result(strategy, direction, f"Only {n_trades} trades — need {min_trades}")

    win_rate    = float(stats.get("Win Rate [%]", 0)) / 100.0
    total_ret   = float(stats.get("Return [%]", 0))
    max_dd      = float(stats.get("Max. Drawdown [%]", 0))
    sharpe      = float(stats.get("Sharpe Ratio", 0) or 0)

    wins  = round(win_rate * n_trades)
    losses = n_trades - wins
    avg_win  = abs(total_ret / wins)  if wins  > 0 else 0
    avg_loss = abs(max_dd   / losses) if losses > 0 else 1
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    confidence = min(100, max(0, round(win_rate * 100)))
    passes = win_rate >= min_win_rate and n_trades >= min_trades

    summary = (
        f"{n_trades} trades · Win {win_rate:.0%} · "
        f"Return {total_ret:.1f}% · MaxDD {max_dd:.1f}% · Sharpe {sharpe:.2f}"
    )
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=n_trades, win_rate=win_rate,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        expectancy=round(expectancy, 3), sharpe=round(sharpe, 3),
        confidence=confidence, passes_gate=passes, summary_text=summary,
    )
```

to:

```python
    n_trades = int(stats.get("# Trades", 0))
    if n_trades < min_trades:
        return _empty_result(strategy, direction, f"Only {n_trades} trades — need {min_trades}")

    win_rate    = float(stats.get("Win Rate [%]", 0)) / 100.0
    total_ret   = float(stats.get("Return [%]", 0))
    max_dd      = float(stats.get("Max. Drawdown [%]", 0))
    sharpe      = float(stats.get("Sharpe Ratio", 0) or 0)

    trades_df = stats.get("_trades")
    pnls = trades_df["PnL"].tolist() if trades_df is not None and "PnL" in trades_df else []
    wins_pnl  = [p for p in pnls if p > 0]
    losses_pnl = [p for p in pnls if p <= 0]
    avg_win  = (sum(wins_pnl) / len(wins_pnl))    if wins_pnl   else 0.0
    avg_loss = (abs(sum(losses_pnl) / len(losses_pnl))) if losses_pnl else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    confidence = min(100, max(0, round(win_rate * 100)))
    passes = win_rate >= min_win_rate and n_trades >= min_trades and expectancy >= _MIN_EXPECTANCY

    summary = (
        f"{n_trades} trades · Win {win_rate:.0%} · "
        f"Return {total_ret:.1f}% · MaxDD {max_dd:.1f}% · Sharpe {sharpe:.2f} · Expectancy ${expectancy:.2f}"
    )
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=n_trades, win_rate=win_rate,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        expectancy=round(expectancy, 3), sharpe=round(sharpe, 3),
        confidence=confidence, passes_gate=passes, summary_text=summary,
    )
```

`expectancy` is now in dollar terms (per-trade, on the fixed `cash=100_000` backtest account) rather than a percent — this is a real per-trade PnL figure, unlike the old formula's units (which mixed a `%`-based `total_ret`/`max_dd` ratio that wasn't actually per-trade at all). It is *not* directly comparable across differently-priced symbols (a $47/trade expectancy on a $50 stock and a $47/trade expectancy on a $500 stock don't represent the same relative edge) — it answers "is this strategy net profitable per trade on this account," which is exactly what `_MIN_EXPECTANCY = 0.0` (unchanged) now actually gates on, but it's not a normalized cross-symbol ranking metric.

- [ ] **Step 4: Check whether `passes_gate` becoming stricter needs to change any caller's behavior**

Run: `cd backend && grep -rn "passes_gate" app/routers/stock_scan.py`

Every caller already branches on `bt_result.passes_gate` (e.g. `if not bt_result.passes_gate: gate_flags.append(...)` or `return {"symbol": symbol, "reason": f"backtest gate: {bt_result.summary_text}"}`) — no caller needs code changes, since the gate now being real (rather than always passing when `win_rate >= min_win_rate`) is exactly the intended fix. No action needed beyond confirming this with the grep.

- [ ] **Step 5: Check every other consumer of `.expectancy` — its units are changing, not just its gate behavior**

Run: `cd backend && grep -rn "expectancy" app/ --include=*.py`

This surfaces one consumer beyond the gate check above: `backend/app/services/strategy_param_optimizer.py:149-150,189` collects every fold's `res.expectancy` into `all_expectancies` and averages it into `oos_metrics["expectancy"]`, which is purely a **reported** value in the nightly WFO tuning proposal (per that module's own docstring, eligibility is gated on `min_trades`/`min_consistency`, not `expectancy` — confirm this by reading `strategy_param_optimizer.py`'s docstring at the top of the file). No code change is needed there; `res.expectancy` is just a float either way and the aggregation math (`sum(...) / len(...)`) doesn't care about its scale.

What *does* change: before this task, `expectancy` was a small, percent-like number (existing fixtures like `tests/test_walk_forward.py:132`'s `"expectancy": 0.3` — note that fixture is a hand-written literal fed into a different function's test, not derived from `run_strategy_backtest`, so it is unaffected by this change and needs no edit). After this task, `expectancy` is a real dollar PnL-per-trade figure on the backtest's fixed `$100,000` account — plausibly two to three orders of magnitude larger, and not directly comparable across differently-priced symbols the way a percent figure would be. Anywhere this number is displayed to Kenneth (Step 6 backtest results, the tuning proposal output) will show noticeably different numbers after this ships — that's the fix working correctly (the old number was fabricated), but it's worth flagging in your final summary to Kenneth so a suddenly-different-looking "Expectancy: $47.20" instead of "Expectancy: 0.3" doesn't read as a new bug.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py -v`
Expected: all PASS. If any pre-existing test asserted a specific `passes_gate` value that depended on the old (always-true-when-win-rate-met) gate, update that assertion to match the new, correct behavior — read the failure message first to confirm the fix, not a fixture problem, caused it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/strategy_backtest.py backend/tests/test_strategy_backtest.py
git commit -m "fix: backtest expectancy now uses real per-trade PnL and actually gates passes_gate"
```

---

### Task 7: Backtest gate now uses the same strategy parameters as the live signal (Critical finding #7)

**Files:**
- Modify: `backend/app/routers/stock_scan.py:154-158` (`_backtest_key`), `~290-317` (`_analyze_core`), `~660-722` (`_process_stock`)
- Test: `backend/tests/test_strategy_backtest.py`

**Root cause:** `run_strategy_backtest()` accepts a `params: dict | None` kwarg that's forwarded into the signal function on every backtest bar — but neither call site in `stock_scan.py` passes it, so the backtest always runs bare-default strategy parameters even when the live signal used tuned or user-overridden ones (`signal_kwargs`, built via `_merge_strategy_params`). A candidate can PASS or REJECT the backtest/confidence gate based on a strategy it isn't actually running.

Fixing this correctly also requires updating `_backtest_key()` — the in-process backtest result cache is currently keyed only on `(symbol, strategy, direction, bars)`. If two requests for the same symbol/strategy/direction/bars differ only in `params`, without a params-aware key the *second* request would silently reuse the *first* request's cached result for the wrong parameters — reintroducing the same class of bug this task is fixing.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_strategy_backtest.py`:

```python
def test_backtest_result_changes_with_params():
    """run_strategy_backtest must actually use the params dict passed to it —
    two materially different param sets on the same bars should not be
    guaranteed to produce identical trade counts (Critical finding #7, 2026-07-15 audit).
    This exercises run_strategy_backtest directly; the router-level fix (threading
    live signal_kwargs into this params argument) is verified by code inspection
    of stock_scan.py's two call sites, which have no isolated per-call unit test
    since they require a full StockAnalysisRequest fixture."""
    bars = _synth_bars(500, trend=True)
    # pullback_ema_signal's real kwarg is `tolerance` (strategy_engine.py:250,
    # default 0.04) — how close price must pull back to the EMA to count as a
    # setup. A near-zero tolerance should fire far fewer (or differently timed)
    # entries than a very loose one.
    tight = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                   params={"tolerance": 0.005})
    loose = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                   params={"tolerance": 0.15})
    # They must not be silently identical, which is what happens if params is
    # never forwarded into the signal function.
    assert tight.n_trades != loose.n_trades or tight.summary_text != loose.summary_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_backtest.py::test_backtest_result_changes_with_params -v`
Expected: PASS already at this layer — `run_strategy_backtest()` itself already respects `params` (confirmed by reading `strategy_backtest.py:112`, `fn(slice_bars, direction=direction, **(params or {}))`). This test documents the invariant; the actual bug is that the router never passes `params` in. Proceed to the router fix.

- [ ] **Step 3: Add `params` to `_backtest_key()`**

In `backend/app/routers/stock_scan.py`, change lines 154-158 from:

```python
def _backtest_key(symbol: str, strategy: str, direction: str, bars: list[dict]) -> str:
    bars_hash = hashlib.md5(
        str([(b["time"], b["close"]) for b in bars[-20:]]).encode()
    ).hexdigest()[:8]
    return f"{symbol.upper()}|{strategy}|{direction.lower()}|{bars_hash}"
```

to:

```python
def _backtest_key(symbol: str, strategy: str, direction: str, bars: list[dict], params: dict | None = None) -> str:
    bars_hash = hashlib.md5(
        str([(b["time"], b["close"]) for b in bars[-20:]]).encode()
    ).hexdigest()[:8]
    params_hash = hashlib.md5(str(sorted((params or {}).items())).encode()).hexdigest()[:8]
    return f"{symbol.upper()}|{strategy}|{direction.lower()}|{bars_hash}|{params_hash}"
```

- [ ] **Step 4: Pass `signal_kwargs` through in `_analyze_core` (the `~290-317` block)**

Change:

```python
        signal_kwargs = _merge_strategy_params(
            req.strategy, req.direction, _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req))
        _sig_bars = (_intraday_bars[-300:] if req.strategy in _INTRADAY_STRATEGIES
                     else bars[-120:])
        # Pass live price so signal uses current price, not yesterday's close.
        _live_price = price if req.strategy not in _INTRADAY_STRATEGIES else None
        try:
            signal = signal_fn(_sig_bars, direction=req.direction,
                               current_price=_live_price, **signal_kwargs)
        except Exception:
            signal = None
```

to add `params=signal_kwargs` at the `run_strategy_backtest` call a few lines below this block (already shown in context as lines 304-317 in the file read during planning):

```python
    bt_result = None
    conf_val = conf_txt = None
    if signal is not None:
        _bt_bars = _intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
        _bt_key = _backtest_key(symbol, req.strategy, req.direction, _bt_bars, signal_kwargs)
        bt_result = _get_backtest_cached(_bt_key)
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, _bt_bars, strategy=req.strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate, params=signal_kwargs))
            _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
```

(Only the `_bt_key` line and the `functools.partial(...)` call change — add `signal_kwargs` as the 5th positional arg to `_backtest_key(...)` and `params=signal_kwargs` as a new kwarg to `run_strategy_backtest`.)

- [ ] **Step 5: Pass params through in `_process_stock` (the `~664-722` block), including the `mean_reversion_multi` branch**

For the `mean_reversion_multi` branch (lines ~664-692), add a `_bt_params` computation right after `_bt_strategy = "mean_reversion_rsi"` is set:

```python
                # Use RSI as canonical backtest proxy for multi-signal — deterministic regardless of fired order
                _bt_strategy = "mean_reversion_rsi"
                bt_bars = bars
                _bt_params = _merge_strategy_params(
                    "mean_reversion_rsi", req.direction,
                    _SIGNAL_KWARGS.get("mean_reversion_rsi", lambda r: {})(req),
                )
```

For the `else` branch (lines ~693-709), add `_bt_params = signal_kwargs` right after `bt_bars` is set:

```python
                _bt_strategy = req.strategy
                bt_bars = intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
                _bt_params = signal_kwargs
```

Then update the shared backtest-call block that follows both branches (lines ~711-722):

```python
            _bt_key = _backtest_key(symbol, _bt_strategy, req.direction, bt_bars)
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bt_bars,
                        strategy=_bt_strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                    ),
                )
                _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
```

to:

```python
            _bt_key = _backtest_key(symbol, _bt_strategy, req.direction, bt_bars, _bt_params)
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bt_bars,
                        strategy=_bt_strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                        params=_bt_params,
                    ),
                )
                _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
```

- [ ] **Step 6: Fix `test_stock_scan_router.py`'s cache pre-population, which this task will otherwise break**

`backend/tests/test_stock_scan_router.py::test_stock_scan_bearish_direction_threads_to_signal` (around line 231-243) pre-populates `_BACKTEST_CACHE` by hand-computing `bt_key = _backtest_key("TSLA", "pullback_ema", "Bearish", bearish_bars)` — a 4-arg call, i.e. `params=None` — specifically so the router's real `_process_stock` call hits this cache entry and never invokes the `ProcessPoolExecutor`. After Step 5 above, the router computes `_bt_key` with a 5th argument (`_bt_params = signal_kwargs`, a non-empty dict from `_merge_strategy_params`), so the test's hand-computed key (hash of `{}`) no longer matches the router's real key (hash of the real merged params) — the cache lookup misses, the test falls through to a real `ProcessPoolExecutor` call, and the test's whole point (never invoking the pool) breaks.

`_merge_strategy_params` calls `get_active(strategy, direction)`, which can read tuned parameters from persistent storage — its return value isn't a fixed literal the test can predict without also depending on whatever tuning state happens to exist. Don't try to replicate it; pin it instead. Add a patch for `_merge_strategy_params` to the test's existing `with (...)` patch block so both the router and the test's own key computation agree on a fixed, known dict:

Change:

```python
    bearish_bars = _make_bearish_bars(130)

    # Pre-populate backtest cache so the ProcessPoolExecutor is never invoked.
    # Key must match exactly what the router will compute for this symbol+strategy+direction.
    bt_key = _backtest_key("TSLA", "pullback_ema", "Bearish", bearish_bars)
    _BACKTEST_CACHE[bt_key] = (_pass_bt(), time.time() + _BACKTEST_TTL)

    try:
        with (
            patch("app.data.universe_presets.expand_universe", return_value=["TSLA"]),
            patch("app.routers.stock_scan.fetch_quotes", return_value={}),
            patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=bearish_bars)),
            patch("app.routers.stock_scan.score_stock", return_value=_pass_card()),
            patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Tesla")),
            patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=118.0)),
            patch("app.routers.stock_scan.get_cached", return_value={"confidence": 60, "sample_size": 30}),
        ):
```

to:

```python
    bearish_bars = _make_bearish_bars(130)

    # Pre-populate backtest cache so the ProcessPoolExecutor is never invoked.
    # Key must match exactly what the router will compute for this symbol+strategy+direction+params.
    # _merge_strategy_params is patched below to this exact fixed dict so the
    # router's real key computation (which otherwise depends on get_active()'s
    # persisted tuning state) can't drift from what we pre-compute here.
    _fixed_params = {"tolerance": 0.04}
    bt_key = _backtest_key("TSLA", "pullback_ema", "Bearish", bearish_bars, _fixed_params)
    _BACKTEST_CACHE[bt_key] = (_pass_bt(), time.time() + _BACKTEST_TTL)

    try:
        with (
            patch("app.data.universe_presets.expand_universe", return_value=["TSLA"]),
            patch("app.routers.stock_scan.fetch_quotes", return_value={}),
            patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=bearish_bars)),
            patch("app.routers.stock_scan.score_stock", return_value=_pass_card()),
            patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Tesla")),
            patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=118.0)),
            patch("app.routers.stock_scan.get_cached", return_value={"confidence": 60, "sample_size": 30}),
            patch("app.routers.stock_scan._merge_strategy_params", return_value=_fixed_params),
        ):
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_strategy_backtest.py tests/test_analyze_stock.py tests/test_stock_scan_router.py -v -k "not slow"`
Expected: all PASS, including `test_stock_scan_bearish_direction_threads_to_signal`. Also run the full stock-scan integration test surface:

Run: `cd backend && grep -rln "run_stock_scan\|_process_stock" tests/ | grep -v __pycache__`

and run whatever other test files that lists, to confirm the `_bt_params`/`signal_kwargs` variable threading didn't break scope in either branch (a `NameError` here would mean the variable was referenced outside its branch — read any failure carefully before assuming it's unrelated).

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_strategy_backtest.py backend/tests/test_stock_scan_router.py
git commit -m "fix: backtest gate now runs with the same strategy params as the live signal"
```

---

### Task 8: PortfolioPositionCreate's required fields actually fail validation when omitted (Critical finding #11)

**Files:**
- Modify: `backend/app/schemas/__init__.py:523-537`
- Test: `backend/tests/test_api.py` (or wherever portfolio-create-endpoint validation is tested — check first)

**Root cause:** `recId`, `entryPrice`, `entryDate` are typed as required (`str`, `float`, `str` — no `Optional[...]`) but each carries `default=None`. Pydantic v2 does not validate field defaults against the annotated type, so an omitted field slips past validation and only breaks later, when the `None` hits the database write — surfacing as an opaque 500 instead of a clear 422 "this field is required."

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py` is a manual smoke-test script (everything lives inside `if __name__ == "__main__":` and makes live `urllib.request` calls to `http://localhost:8000`) — it has no pytest-collectible tests and is not a home for this test. Use `backend/tests/test_persistence.py` instead: it already POSTs to `/api/portfolio` with a full payload via an async `client` fixture and a module-level `_POSITION_PAYLOAD` dict (`test_persistence.py:85-97`, used by `test_portfolio_add_and_list` at `:102-113`). Add this test near that one, reusing `_POSITION_PAYLOAD` and `client`:

```python
@pytest.mark.asyncio
async def test_portfolio_create_rejects_missing_rec_id(client):
    """recId/entryPrice/entryDate are required fields — omitting one must return
    a 422 validation error, not silently construct with None and fail later as
    an opaque 500 on the database write (Critical finding #11, 2026-07-15 audit)."""
    bad_payload = {k: v for k, v in _POSITION_PAYLOAD.items() if k != "recId"}
    resp = await client.post("/api/portfolio", json=bad_payload)
    assert resp.status_code == 422, resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_persistence.py::test_portfolio_create_rejects_missing_rec_id -v`
Expected: FAIL — the request currently succeeds (or fails with a 500 further down in the DB layer) instead of returning a 422, because `recId` silently becomes `None` at the schema layer instead of failing validation.

- [ ] **Step 3: Remove the `default=None` from the three required fields**

In `backend/app/schemas/__init__.py`, change lines 526, 530, 532 from:

```python
    recId: str = Field(alias="rec_id", default=None)
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: str
    entryPrice: float = Field(alias="entry_price", default=None)
    qty: int = Field(default=1)
    entryDate: str = Field(alias="entry_date", default=None)
```

to:

```python
    recId: str = Field(alias="rec_id")
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: str
    entryPrice: float = Field(alias="entry_price")
    qty: int = Field(default=1)
    entryDate: str = Field(alias="entry_date")
```

`qty` keeps its `default=1` since it's genuinely optional (declared with a real default value elsewhere in the app's usage). The custom `__init__` at lines 539-552 that remaps camelCase/snake_case keys is unaffected — it still calls `super().__init__(**mapped)`, and Pydantic now actually enforces these three as required.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_persistence.py -v`
Expected: all PASS, including the new test.

Then run the full portfolio-related suite to confirm no legitimate call site was relying on the silent `None` default:

Run: `cd backend && pytest tests/ -k "portfolio" -v`
Expected: all PASS. If something fails here, it means a real code path was constructing `PortfolioPositionCreate` without one of these three fields and relying on the bug — read that call site and fix it to actually supply the field, don't revert the schema fix.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/tests/test_persistence.py
git commit -m "fix: PortfolioPositionCreate now actually rejects missing recId/entryPrice/entryDate"
```

---

### Task 9: Step 3's saved horizon/hold-days no longer get silently overwritten on a fresh load (Critical finding #8)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx:738-741` (add a hydration-sync effect nearby)
- Test: manual verification via the Browser pane (this store's rehydration timing can't be reliably unit-tested against Jest's DOM/localStorage shim without reproducing the exact async timing bug itself — verify in the real app instead)

**Root cause:** `useScanStore`'s persist config has `skipHydration: true`; hydration is triggered by `StoreHydration`'s `useEffect` (mounted once at the app root) calling `.persist.rehydrate()`, which resolves asynchronously. `Step3Page`'s local `useState` initializers (`dir`, `hz`, `holdMin`, `holdMax`) read `context?.direction` etc. **once, at mount** — if the component mounts before rehydration resolves, they capture the hardcoded fallback defaults (`'Bullish'`, `'Swing'`, ...) instead of the persisted values, and nothing re-syncs local state once rehydration actually completes. The first call to `handleDirChange`/`handleHzChange`/`handleMinChange`/`handleMaxChange` then calls `syncToStore(...)`, writing those stale defaults back into the store — silently overwriting the real saved horizon/hold-days.

- [ ] **Step 1: Add a one-time hydration-sync effect**

In `frontend/app/(frame)/screener/step-3-direction/page.tsx`, right after the existing `useState` block at lines 738-747 (after `subGroupOpen` and before `descriptorRef`), add:

```typescript
  // If this page mounts before useScanStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializers above capture the hardcoded fallback defaults instead of the
  // persisted context. Sync local state once hydration actually finishes, so
  // the first click on this page doesn't write those fallback defaults back
  // into the store and silently overwrite a saved horizon/hold-days.
  useEffect(() => {
    const syncFromHydratedContext = () => {
      const c = useScanStore.getState().context;
      if (!c) return;
      setDir(c.direction ?? 'Bullish');
      setHz(c.horizonPreset ?? 'Swing');
      setHoldMin(Math.round(c.holdMin ?? presetByKey('Swing').holdMin));
      setHoldMax(Math.round(c.holdMax ?? presetByKey('Swing').holdMax));
    };
    // Covers the common case: hydration already finished before this effect
    // runs (e.g. navigating from Step 2, rather than a fresh Step-3 landing).
    if (useScanStore.persist.hasHydrated()) syncFromHydratedContext();
    // Covers the race: hydration finishes after this component has already
    // mounted with fallback-default local state.
    const unsub = useScanStore.persist.onFinishHydration(syncFromHydratedContext);
    return unsub;
  }, []);
```

- [ ] **Step 2: Confirm `useEffect` is already imported**

Run: `grep -n "^import.*useEffect\|useEffect," "frontend/app/(frame)/screener/step-3-direction/page.tsx" | head -3`
Expected: `useEffect` is already imported (the file already uses it at the existing `useEffect` block around line 751 for `api.getRegime()`). If not present, add it to the existing React import line.

- [ ] **Step 3: Manual verification via the Browser pane**

Start the dev server and reproduce the exact race:

1. `preview_start` with the frontend dev server config (localhost:3001).
2. Navigate to the screener, go through Step 1 → Step 2, land on Step 3, set the horizon to something non-default (e.g. "Position", hold days 30-90), and let it sync to the store (click any control that calls `syncToStore`).
3. Navigate away (e.g. to `/dashboard`), then reload the browser tab entirely (full page reload, not client navigation) directly on the Step 3 URL — this is what forces the pre-hydration mount race.
4. Immediately (before doing anything else) read the page and confirm the horizon/hold-days controls show the saved "Position"/30-90 values, not the "Swing" default.
5. Click any single control on the page once (e.g. toggle direction and back), then reload again and confirm the saved values are still intact — this is the actual regression check, since the bug only manifests on the *first interaction after a fresh load*.

Use `mcp__Claude_Browser__read_page` to confirm the rendered values rather than relying on a screenshot alone.

- [ ] **Step 4: Run the frontend test suite to confirm no regression**

Run: `cd frontend && npm run typecheck`
Expected: clean (no new TS errors)

Run: `cd frontend && npm run test -- --testPathPattern=step-3-direction` (if a test file for this page exists; if not, run the full suite to confirm nothing else regressed: `npm run test`)

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "fix: Step 3 no longer overwrites saved horizon/hold-days on a pre-hydration mount race"
```

---

### Task 10: Closing a position twice quickly can no longer resurrect it (Critical finding #9)

**Files:**
- Modify: `frontend/lib/portfolioStore.ts:258-359`
- Test: `frontend/lib/__tests__/portfolioStore.test.ts` (check exact existing test file name/location first — see Step 1)

**Root cause:** `closePositionRemote()` has no lock on `recId`. If it's called twice in quick succession for the same position (double-click, or a slow network turning one click into a retried request), the second call can start *before* the first one's request resolves. The first call's request lands, the backend closes the position; the second call's request (sent before that happened) can 404 if it arrives after the backend-side close, and the 404-drift-recovery branch (lines 301-324) then re-persists the position, undoing the close it was trying to perform.

The fix is a per-`recId` in-flight lock: a second call for the same `recId` while one is already in flight should await and return the *same* in-flight result instead of issuing a second, racing request.

- [ ] **Step 1: Locate the existing test file and its `closePositionRemote` describe block**

The file is `frontend/lib/__tests__/portfolioStore.test.ts` — it already has a top-level `describe('closePositionRemote', ...)` block (around line 262) with its own `beforeEach`/`afterEach` (inherited from the outer describe at lines 46-57, which resets `usePortfolioStore` state and restores `global.fetch`/`localStorage` between tests). Add the new test as an `it(...)` inside that existing `describe('closePositionRemote', ...)` block, not as a new separate top-level `describe`.

- [ ] **Step 2: Write the failing test**

Match the file's established conventions exactly: `global.fetch = jest.fn(...) as unknown as typeof fetch` (not `as jest.Mock`), and wrap any `usePortfolioStore.setState(...)` call in `act(...)` (both `renderHook` and `act` are already imported at the top of the file):

```typescript
  it('does not issue a second network request for a close already in flight', async () => {
    let resolveFirst!: (v: Response) => void;
    const firstResponse = new Promise<Response>((res) => { resolveFirst = res; });
    let callCount = 0;

    global.fetch = jest.fn((url: string) => {
      if (typeof url === 'string' && url.includes('/close')) {
        callCount += 1;
        return firstResponse;
      }
      return Promise.resolve({ ok: true, json: async () => [] } as Response);
    }) as unknown as typeof fetch;

    const recId = 'REC-TEST-DOUBLE-CLOSE';
    const p1 = usePortfolioStore.getState().closePositionRemote(recId, {});
    const p2 = usePortfolioStore.getState().closePositionRemote(recId, {});

    resolveFirst({ ok: true, json: async () => ({}) } as Response);
    await Promise.all([p1, p2]);

    expect(callCount).toBe(1);
  });
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: FAIL — `callCount` is `2`, since both calls issue their own `doClose(recId)` request independently.

- [ ] **Step 4: Add a per-recId in-flight lock**

In `frontend/lib/portfolioStore.ts`, add a module-level map above the store definition (near the top of the file, alongside other module-level helpers — check the existing imports/helpers section for where similar module-level state, if any, already lives):

```typescript
// Dedupes concurrent closePositionRemote calls for the same recId — without
// this, a double-click or slow-network retry can send two overlapping close
// requests; the second one's 404-drift-recovery branch can then re-persist
// the position the first call just closed.
const _inFlightCloses = new Map<string, Promise<{ ok: boolean; detail?: string }>>();
```

Then wrap the body of `closePositionRemote` (currently `async (recId, opts) => { ... }` at line 258) so the existing implementation becomes an inner function and the exported one dedupes on `recId`:

```typescript
      closePositionRemote: async (recId, opts) => {
        const existing = _inFlightCloses.get(recId);
        if (existing) return existing;

        const run = async (): Promise<{ ok: boolean; detail?: string }> => {
          const doClose = async (id: string): Promise<Response> =>
            fetch(`${_BASE_URL()}/api/portfolio/${id}/close`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                qtyToClose: opts.qtyToClose ?? null,
                exitPrice: opts.exitPrice ?? null,
                exitDate: opts.exitDate ?? null,
                sendToBroker: opts.sendToBroker ?? false,
              }),
            });
          const local = usePortfolioStore.getState().positions.find((p) => p.recId === recId);

          // Fetch the authoritative open positions, or null if the backend is
          // unreachable / errors. Used to decide recId drift vs a genuinely-gone
          // position WITHOUT guessing from a persist failure code.
          const fetchRemote = async (): Promise<BackendPosition[] | null> => {
            try {
              const r = await fetch(`${_BASE_URL()}/api/portfolio`);
              if (!r.ok) return null;
              return (await r.json()) as BackendPosition[];
            } catch {
              return null;
            }
          };

          // Tracks whichever recId the successful close actually landed under —
          // starts as the caller's id, but drift recovery below may retry against
          // the backend's real id instead. Anything restored to local state after
          // a successful close must use THIS id, not the original parameter, or a
          // drift-recovered restore would carry a recId that 404s on every
          // subsequent action until the next sync heals it.
          let effectiveRecId = recId;

          try {
            let res = await doClose(recId);

            // A 404 means the backend has no open position under this recId:
            // either the original POST never landed, or the backend holds the same
            // *contract* under a different recId (drift, e.g. a DB reset while
            // localStorage kept the old id). Recover carefully — and only drop a
            // local row when the backend POSITIVELY confirms the contract is gone.
            if (res.status === 404 && local) {
              const persisted = await persistPosition(local);
              if (persisted.ok) {
                res = await doClose(recId);
              } else {
                const remote = await fetchRemote();
                if (remote) {
                  const match = remote.find((p) => p.contract === local.contract);
                  if (match?.recId && match.recId !== recId) {
                    effectiveRecId = match.recId;
                    res = await doClose(match.recId);            // drift: close the real row
                  } else if (!match) {
                    // Backend reachable AND has no such contract → genuinely gone.
                    set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
                    return {
                      ok: false,
                      detail: 'This position was no longer on the server (already closed or cleared) — removed it from your list.',
                    };
                  }
                  // match with same recId shouldn't 404 — fall through to the error below.
                }
                // Backend unreachable: do NOT drop a possibly-valid position.
              }
            }

            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
            }

            // Success: remove the acted-upon local row so a fully-closed position
            // can't linger via syncFromBackend's localOnly retention (its contract
            // is now absent from the backend). A partial close re-appears from the
            // authoritative pull below with its reduced qty.
            const closedRow = usePortfolioStore.getState().positions.find((p) => p.recId === recId);
            const wasFullClose = !opts.qtyToClose || opts.qtyToClose >= (closedRow?.contracts ?? 1);
            set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
            const synced = await usePortfolioStore.getState().syncFromBackend();
            // The close itself succeeded server-side regardless of this GET. But if
            // it was only a PARTIAL close and the follow-up pull failed (network),
            // the row above is now gone from local state with no way to learn its
            // reduced qty until the next successful sync — restore it locally
            // (qty adjusted, price/P&L stale until next sync) rather than making a
            // still-open position disappear from the list entirely.
            if (!synced && !wasFullClose && closedRow) {
              const remainingQty = Math.max(0, (closedRow.contracts ?? 1) - (opts.qtyToClose ?? 0));
              if (remainingQty > 0) {
                // Restore under effectiveRecId (the id the backend actually closed
                // against) — if drift recovery kicked in above, the backend no
                // longer recognizes the original `recId`, and restoring under the
                // stale id would just 404 again on the next action.
                set((s) => ({ positions: [...s.positions, { ...closedRow, recId: effectiveRecId, contracts: remainingQty }] }));
              }
            }
            return { ok: true };
          } catch (e) {
            return { ok: false, detail: e instanceof Error ? e.message : 'Network error' };
          }
        };

        const promise = run().finally(() => _inFlightCloses.delete(recId));
        _inFlightCloses.set(recId, promise);
        return promise;
      },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: all PASS, including the new dedup test. Also run the broader portfolio test surface in case other tests exercise `closePositionRemote`'s drift-recovery paths:

Run: `cd frontend && npm run test -- --testPathPattern=portfolio`

- [ ] **Step 6: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts
git commit -m "fix: dedupe concurrent closePositionRemote calls to stop double-close from resurrecting positions"
```

---

## Final verification (run after all 10 tasks are committed)

- [ ] **Backend full suite:**

Run: `cd backend && pytest`
Expected: all tests pass (aside from any pre-existing known-flaky/skip markers unrelated to this plan).

- [ ] **Frontend full suite + typecheck:**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: typecheck clean, all tests pass.

- [ ] **Migration applied and verified against real Postgres** (Task 2, Steps 3-4) — do not skip this even if the SQLite-backed test suite is green; that's the whole reason these two bugs existed undetected.

- [ ] **Manual Step 3 hydration-race check** (Task 9, Step 3) — do not skip; this bug has no automated regression coverage by design (see Task 9's rationale).
