# Alembic Merge-Heads Fix + Ghost-Alert Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close a divergent Alembic migration history that has left the live `TradingAssistantDB` database missing two columns the app's models already expect (`alert_rules.condition_state`, `portfolio_positions.alert_state`), causing recurring SQL errors in the backend logs — and independently confirm (with a permanent regression test, not just a one-off manual check) that no currently-deactivated alert rule can fire.

**Architecture:** One new Alembic merge migration reconciles the two divergent heads with zero schema changes of its own (both branches' real changes — `c1d2e3f4a5b6`/`b4e91a2f7c33` adding the two missing columns, and `b3f7a1c9d4e2` already applied fixing `audit_events`/`portfolio_positions` types — get applied exactly once each, in their original order, via Alembic's normal dependency resolution). A regression test guards against this specific failure mode (two heads existing silently) recurring unnoticed in the future. A second regression test proves — independent of any one-off manual query — that `evaluate_and_notify_for_symbol()` structurally cannot fire a disabled rule, by planting an enabled and a disabled rule with identical matching conditions and asserting only the enabled one fires.

**Tech Stack:** Alembic (migrations) + SQLAlchemy v2 (ORM) + PostgreSQL 15 (`tradingassistant-db` container, database `TradingAssistantDB`) + pytest/pytest-asyncio (backend tests, SQLite in-memory for unit tests).

**Working-directory convention (read this before running anything):** Every command block below starts with its own absolute `cd` and never assumes any earlier step already moved the shell there — a mistake found and fixed 8 separate times across this plan's own review process (a `cd backend` after an earlier `cd backend` fails with "No such file or directory"; a `git add backend/...` path fails with "did not match any files" once the shell is already inside `backend/`). Two anchors are used, generally along these lines:
- Repo root: `F:/Git/GitHub/Trading assistant` — most `git` commands.
- Backend dir: `F:/Git/GitHub/Trading assistant/backend` — `alembic`/`pytest` commands, and a couple of `git checkout`/`git status` calls in Task 3 that are deliberately kept in the same block as an edit→test→revert→verify sequence (git resolves relative paths correctly from any subdirectory, so this is safe, just not perfectly uniform).

Each command block is meant to be self-contained: copy-paste-run it on its own, in any order, in a fresh shell, and it should work correctly.

---

## Background (read before starting)

Two migrations were written independently, both branching off the same parent revision (`a7f3e9b12c04`, "drop orphan kids-app schema") without either accounting for the other:

- **Branch A** (dated 2026-07-04): `c1d2e3f4a5b6` (adds `alert_rules.condition_state`) → `b4e91a2f7c33` (adds `portfolio_positions.alert_state`).
- **Branch B** (dated 2026-07-15): `b3f7a1c9d4e2` ("fix audit_events and portfolio_positions schema drift" — fixes `audit_events.recommendation_id`/`.rec_id`, and `portfolio_positions.rec_id`/`.contract`/`.entry_date`).

The live database (`tradingassistant-db`, and the older `ritter-postgres` container before it) is stamped at `b3f7a1c9d4e2` — it received Branch B but never Branch A. `alembic heads` currently returns two heads (`b3f7a1c9d4e2` and `b4e91a2f7c33`) instead of one.

**Live impact (confirmed):** `backend/app/routers/chart_alerts.py:502` (`evaluate_and_notify_for_symbol`, the only code path that evaluates chart-drawn alert rules — shared by both the live-chart websocket in `chart.py` and the headless background scheduler in `chart_alert_scheduler.py`) does `select(AlertRuleModel)`, a full-entity query. Because `condition_state` doesn't exist on the real table, this query raises `UndefinedColumnError` every single time it runs — meaning **no chart-drawn alert has been able to fire since this drift was introduced**, not even the one legitimately enabled rule that exists (`DG Pre breakout`, id `mriqmjgwrifp`). Separately, `portfolio_alert_monitor.py:85` itself does its own `select(PortfolioPositionModel)` full-entity query (inside the same `try` block, and failing first, before `generate_alerts()` at line 108 is ever reached) — and `backend/app/services/alert_generator.py:52` (`generate_alerts`) does a second, independent `select(PortfolioPositionModel)` that would fail identically if it were ever reached. Either one fails on the missing `alert_state` column — Postgres validates every referenced column at query-planning time, before fetching any rows, so **this is already failing on every tick today** (default ≤60s), regardless of `portfolio_positions` currently having 0 rows; it just produces a generic `logger.error('Portfolio alert generation failed', ...)` line (the whole block at `portfolio_alert_monitor.py:80-112` is wrapped in a broad `try/except`) rather than a distinctly-worded error, which is why it can look dormant. It would silently get *worse* (start actually skipping real TP/stop alerts, not just logging noise) the moment a real position is opened, unless fixed first.

**Ghost-alert finding (already confirmed by direct investigation, formalized as a test in Task 4):** There is exactly one alert-evaluation code path (`evaluate_and_notify_for_symbol`), and its query has an unconditional `AlertRuleModel.enabled == True` filter at the SQL level — a disabled rule is structurally excluded before any condition matching happens, not filtered out afterward. Live data confirms this: `alert_history` has zero rows ever, and the one existing `alert_rules` row is `enabled = true` with `last_triggered_at` empty. **No evidence of ghost alerts exists in the current data** — the actual failure mode is the opposite (fail-closed: nothing fires, not even legitimate rules), which Task 4 turns into a permanent regression test rather than a one-time finding.

---

## File Structure

- Create: `backend/migrations/versions/d92f6a1c8e37_merge_alert_state_and_audit_heads.py` — the merge migration (no schema operations, just reconciles history).
- Create: `backend/tests/test_alembic_heads.py` — regression test: exactly one Alembic head, ever.
- Create: `backend/tests/test_alert_rule_disabled_cannot_fire.py` — regression test: a disabled rule with matching conditions never fires, an enabled one with identical conditions does.
- No application code changes — `backend/app/models/alert.py` and `backend/app/models/portfolio.py` already declare both columns correctly; the schema just needs to catch up to them.

---

### Task 1: Write the merge migration

**Files:**
- Create: `backend/migrations/versions/d92f6a1c8e37_merge_alert_state_and_audit_heads.py`

- [ ] **Step 1: Confirm the two current heads**

`alembic.ini` lives at `backend/migrations/alembic.ini`, not `backend/alembic.ini` — Alembic's CLI only auto-discovers `./alembic.ini` in the current directory, it does not search subdirectories, so every `alembic` command in this plan needs an explicit `-c migrations/alembic.ini` flag when run from `backend/`.

Run: `cd "F:/Git/GitHub/Trading assistant/backend" && alembic -c migrations/alembic.ini heads`
Expected output (order may vary):
```
b3f7a1c9d4e2 (head)
b4e91a2f7c33 (head)
```

- [ ] **Step 2: Write the merge migration file**

```python
"""merge alert_state and audit-schema-drift heads

Reconciles two migration branches that both forked from a7f3e9b12c04
without either accounting for the other:

- b3f7a1c9d4e2 (2026-07-15): fixes audit_events/portfolio_positions type
  drift. Already applied to the live database.
- b4e91a2f7c33 <- c1d2e3f4a5b6 (2026-07-04): adds alert_rules.condition_state
  and portfolio_positions.alert_state. Never applied to the live database,
  because the db's alembic_version pointer was on the other branch and
  `alembic upgrade head` had two heads to choose from with no merge point
  connecting them.

This migration makes no schema changes of its own -- it is a pure merge
point. Running `alembic upgrade head` after this migration exists will
apply whichever of the two branches' migrations the target database is
missing (for the live db: c1d2e3f4a5b6 and b4e91a2f7c33) to reach this
merge revision.

Revision ID: d92f6a1c8e37
Revises: b3f7a1c9d4e2, b4e91a2f7c33
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd92f6a1c8e37'
down_revision = ('b3f7a1c9d4e2', 'b4e91a2f7c33')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

- [ ] **Step 3: Confirm exactly one head now**

Run: `cd "F:/Git/GitHub/Trading assistant/backend" && alembic -c migrations/alembic.ini heads`
Expected output: exactly one line, `d92f6a1c8e37 (head)`.

- [ ] **Step 4: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/migrations/versions/d92f6a1c8e37_merge_alert_state_and_audit_heads.py
git commit -m "fix: merge divergent Alembic heads (alert_state/condition_state branch was never applied)"
```

---

### Task 2: Regression test — exactly one Alembic head, permanently

**Files:**
- Create: `backend/tests/test_alembic_heads.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/test_alembic_heads.py
"""Guards against a repeat of the d92f6a1c8e37 incident: two migrations
independently forked from the same parent revision, creating a second
Alembic head that `alembic upgrade head` silently never applied on the live
database (see d92f6a1c8e37's docstring for the full incident writeup).
SQLite dev/test databases bootstrap via Base.metadata.create_all() and
never run Alembic at all, so this class of drift is invisible everywhere
except this test and a real `alembic upgrade head` run against Postgres."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_DIR = Path(__file__).parent.parent


def test_exactly_one_alembic_head():
    cfg = Config(str(_BACKEND_DIR / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one Alembic head, found {len(heads)}: {heads}. "
        "Two migrations were probably written against the same down_revision "
        "independently -- add a merge migration (see d92f6a1c8e37 for the pattern)."
    )
```

- [ ] **Step 2: Run it to confirm it currently passes (after Task 1's merge migration exists)**

Run: `cd "F:/Git/GitHub/Trading assistant/backend" && pytest tests/test_alembic_heads.py -v`
Expected: `PASSED`

- [ ] **Step 3: Verify it actually catches the failure mode — temporarily remove the merge migration and confirm this test fails**

By this point Task 1 Step 4 has already committed the merge migration file, so `git stash` would find nothing to stash (it only touches uncommitted changes) and this check would silently no-op instead of proving anything. Move the file out of the way directly instead:

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
mv migrations/versions/d92f6a1c8e37_merge_alert_state_and_audit_heads.py /tmp/d92f6a1c8e37_merge_alert_state_and_audit_heads.py.bak
pytest tests/test_alembic_heads.py -v
```
Expected: `FAILED` with `Expected exactly one Alembic head, found 2: ...`

Then restore it:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
mv /tmp/d92f6a1c8e37_merge_alert_state_and_audit_heads.py.bak migrations/versions/d92f6a1c8e37_merge_alert_state_and_audit_heads.py
pytest tests/test_alembic_heads.py -v
```
Expected: `PASSED` again, and `git status` shows the migration file with no changes (other pre-existing untracked files in this repo, if any, are unrelated and not part of this check).

- [ ] **Step 4: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/tests/test_alembic_heads.py
git commit -m "test: add regression guard against divergent Alembic heads"
```

---

### Task 3: Regression test — a disabled alert rule can never fire

**Files:**
- Create: `backend/tests/test_alert_rule_disabled_cannot_fire.py`

- [ ] **Step 1: Write the test**

Follows the exact SQLite in-memory pattern already used in `backend/tests/test_chart_alert_scheduler.py`.

```python
# backend/tests/test_alert_rule_disabled_cannot_fire.py
"""Formalizes the ghost-alert audit finding: evaluate_and_notify_for_symbol's
query (chart_alerts.py:502) filters AlertRuleModel.enabled == True at the SQL
level, so a disabled rule is excluded before any condition matching happens --
not filtered out afterward. This plants an enabled and a disabled rule with
IDENTICAL matching conditions on the same symbol/interval and asserts only
the enabled one ever fires, and that no AlertHistoryModel row is ever created
for the disabled one. Live data audited 2026-07-17: alert_history had zero
rows ever, and the one real alert_rules row (enabled) had never triggered --
no evidence of a disabled rule having fired historically either."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertHistoryModel, AlertRuleModel


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule(rule_id: str, enabled: bool) -> AlertRuleModel:
    # Condition is always true (price > -1) so if the disabled rule were ever
    # evaluated, it would trigger -- this isolates "does enabled=False get
    # respected" from "does the condition happen to be false right now".
    rule_json = json.dumps({'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': -1}]})
    return AlertRuleModel(
        id=rule_id, user_id='default', name=f'Rule {rule_id}', symbol='AAPL', interval='15min',
        enabled=enabled, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_CANDLES = [
    {'time': f't{i}', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
    for i in range(3)
]


@pytest.mark.asyncio
async def test_disabled_rule_never_fires_even_with_matching_conditions(monkeypatch):
    import app.routers.chart_alerts as chart_alerts

    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_rule('enabled-rule', enabled=True))
        db.add(_rule('disabled-rule', enabled=False))
        await db.commit()

    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'build_regime_snapshot', lambda *a, **kw: None)
    monkeypatch.setattr(chart_alerts, 'compute_indicators_for_conditions', lambda *a, **kw: {})

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _CANDLES[-1], _CANDLES, [],
    )

    triggered_rule_ids = {t['rule_id'] for t in triggered}
    assert 'enabled-rule' in triggered_rule_ids
    assert 'disabled-rule' not in triggered_rule_ids

    async with Session() as db:
        history = (await db.execute(select(AlertHistoryModel))).scalars().all()
        history_rule_ids = {h.rule_id for h in history}
        assert 'enabled-rule' in history_rule_ids
        assert 'disabled-rule' not in history_rule_ids
```

- [ ] **Step 2: Run it, and confirm the guard is real**

Run: `cd "F:/Git/GitHub/Trading assistant/backend" && pytest tests/test_alert_rule_disabled_cannot_fire.py -v`
Expected: `PASSED`

The "disabled rule never fires" invariant is actually enforced by **two independent layers**, not one: the SQL-level filter `AlertRuleModel.enabled == True` in `chart_alerts.py:505`, AND a second, redundant check in `app/services/alert_evaluator.py:276-277` (`if not rule.enabled: continue`, inside `evaluate_rules()`). Removing only the SQL-level filter does **not** make this test fail — the second layer still catches it — so don't treat a `PASSED` result after deleting just line 505 as "the test is broken." That's defense in depth working as intended, not a false negative.

To see this test actually go `FAILED` (proving it isn't a tautology), both layers need defeating together — run this as one continuous block:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
# 1. Edit app/routers/chart_alerts.py:505 to remove the `AlertRuleModel.enabled == True,` line.
# 2. Edit app/services/alert_evaluator.py:276-277 to remove the `if not rule.enabled: continue` block.
# 3. Then:
pytest tests/test_alert_rule_disabled_cannot_fire.py -v
```
Expected: `FAILED`, with `disabled-rule` now appearing in `triggered_rule_ids`.

Then revert both edits and confirm clean, still from the same directory:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
git checkout app/routers/chart_alerts.py app/services/alert_evaluator.py
pytest tests/test_alert_rule_disabled_cannot_fire.py -v
git status
```
Expected: `PASSED` again, and `git status` shows the two source files with no changes (other pre-existing untracked files in this repo, if any, are unrelated and not part of this check).

- [ ] **Step 3: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/tests/test_alert_rule_disabled_cannot_fire.py
git commit -m "test: add regression guard proving disabled alert rules cannot fire"
```

---

### Task 4: Back up, apply the migration to the live database, and verify

**Files:** none (operational task against the live `tradingassistant-db` Docker container)

Note: the `DATABASE_URL="..." alembic ...` inline-env-var syntax below is bash/POSIX-sh syntax (works in the Bash tool / Git Bash). It's actually redundant here — `backend/.env` already has the identical `DATABASE_URL`, and `app/config.py`'s pydantic-settings reads it automatically — so `alembic` connects to the right database either way. If running these commands in PowerShell instead, drop the inline prefix and just run `alembic ...` directly (or `$env:DATABASE_URL = "..."; alembic ...` on its own line first).

- [ ] **Step 1: Back up the live database before touching schema**

On Git Bash / MSYS (the default for this repo's Bash tool), `/tmp/...` arguments passed to `docker exec`/`docker cp` get silently rewritten to a Windows host path before reaching Docker, which breaks both commands below (`pg_dump: error: could not open output file "C:/Users/.../Temp/pre_merge_backup.dump"`). Prefix with `MSYS_NO_PATHCONV=1` to disable that rewriting:

```bash
MSYS_NO_PATHCONV=1 docker exec tradingassistant-db pg_dump -U bamendjou -d TradingAssistantDB -F c -f /tmp/pre_merge_backup.dump
MSYS_NO_PATHCONV=1 docker cp tradingassistant-db:/tmp/pre_merge_backup.dump "F:/Git/GitHub/Trading assistant/pre_merge_backup.dump"
```
(In PowerShell this path-mangling doesn't happen — drop the `MSYS_NO_PATHCONV=1` prefix.)

Expected: `F:/Git/GitHub/Trading assistant/pre_merge_backup.dump` appears, non-zero size. **Verify this before proceeding to Step 3** — `ls -la "F:/Git/GitHub/Trading assistant/pre_merge_backup.dump"` should show a size in the tens of megabytes, not 0 bytes or a missing file. Do not continue to Step 3 (which mutates the live schema) until this backup genuinely exists.

- [ ] **Step 2: Confirm current Alembic state on the live database**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
DATABASE_URL="postgresql+asyncpg://bamendjou:devpassword@localhost:5433/TradingAssistantDB" alembic -c migrations/alembic.ini current
```
Expected: `b3f7a1c9d4e2` printed with no `(head)` marker (it stopped being a head the moment Task 1's merge migration file exists in the repo — this just confirms the *database* hasn't moved yet).

- [ ] **Step 3: Apply the merge**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
DATABASE_URL="postgresql+asyncpg://bamendjou:devpassword@localhost:5433/TradingAssistantDB" alembic -c migrations/alembic.ini upgrade head
```
Expected output includes three "Running upgrade" lines in this order: `a7f3e9b12c04 -> c1d2e3f4a5b6`, `c1d2e3f4a5b6 -> b4e91a2f7c33`, then the merge step `b3f7a1c9d4e2, b4e91a2f7c33 -> d92f6a1c8e37`.

- [ ] **Step 4: Verify the two columns now exist with correct types**

```bash
docker exec tradingassistant-db psql -U bamendjou -d TradingAssistantDB -c "\d alert_rules"
docker exec tradingassistant-db psql -U bamendjou -d TradingAssistantDB -c "\d portfolio_positions"
```
Expected: `alert_rules` now lists a `condition_state | text | not null | default '{}'::text` column; `portfolio_positions` now lists an `alert_state | json | | default '{}'::json` column — note **`json`, not `jsonb`**: both the model (`app/models/portfolio.py`, `from sqlalchemy import JSON`) and the migration (`b4e91a2f7c33`, `sa.JSON()`) use SQLAlchemy's generic `JSON` type, which Postgres renders as plain `json`. Seeing `jsonb` here would actually be the surprising/wrong outcome — don't second-guess a correct `json` result.

- [ ] **Step 5: Verify the existing alert_rules row backfilled correctly**

```bash
docker exec tradingassistant-db psql -U bamendjou -d TradingAssistantDB -c "SELECT id, condition_state FROM alert_rules;"
```
Expected: the `DG Pre breakout` row (`id = mriqmjgwrifp`) now shows `condition_state = {}` instead of erroring.

- [ ] **Step 6: Confirm `alembic current` now shows the single new head**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
DATABASE_URL="postgresql+asyncpg://bamendjou:devpassword@localhost:5433/TradingAssistantDB" alembic -c migrations/alembic.ini current
```
Expected: `d92f6a1c8e37 (head)`

- [ ] **Step 7: Restart the backend and watch the logs for the recurring errors to stop**

If the backend is running locally (`uvicorn`), restart it. Then tail its log output (or `docker logs -f tradingassistant-backend` if running the Dockerized backend) for at least 3 minutes — long enough to span both the chart-alert scheduler's default 60s tick and the portfolio monitor's default 60s tick.
Expected: zero occurrences of `column portfolio_positions.alert_state does not exist` or `column alert_rules.condition_state does not exist` in that window (previously recurring every 10-40 seconds). Also grep for `Portfolio alert generation failed` (the generic wrapper log line in `portfolio_alert_monitor.py:112` that the `alert_state` error surfaces through) — it should also stop appearing.

- [ ] **Step 8: Clean up the backup file once verified (optional, keep if you want an extra safety net)**

```bash
rm "F:/Git/GitHub/Trading assistant/pre_merge_backup.dump"
```

---

### Task 5: Run the full backend test suite to confirm no regressions

**Files:** none

- [ ] **Step 1: Run the full suite**

```bash
cd "F:/Git/GitHub/Trading assistant/backend" && pytest
```
Expected: all tests pass, including the two new ones from Tasks 2 and 3, and the existing `test_alert_evaluator.py`, `test_alert_generator_sustain.py`, `test_chart_alert_scheduler.py`, `test_portfolio_alert_monitor.py`, `test_portfolio_monitor.py` suites (these all use the SQLite in-memory pattern and were never affected by the Postgres-only drift, so they should already have been passing — this step confirms Task 1-4's changes didn't break them).

**Known pre-existing failures, unrelated to this plan** — as of 2026-07-17, the full suite has 2 failures with no connection to alerts, migrations, or anything this plan touches, always reproducing:
- `test_market_data_fixes.py::test_iv_enrichment_skipped_when_ibkr_returns_none` (IV/yfinance logic)
- `test_market_data_fixes.py::test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore` (same file)

A 3rd, `test_governor.py::test_symbol_budget_evicts_after_window`, is a real-time timing test (`window=0.05s` vs `sleep(0.06s)`) that *may* occasionally also fail under scheduler contention inside the full suite — its absence is normal, not a problem, and its presence is also not a regression from this plan.

If only these known tests fail (2 always, possibly the 3rd), that's the pre-existing baseline, not a regression from this plan — proceed to Step 2 with that understanding rather than treating it as a blocker.

- [ ] **Step 2: If any OTHER test fails (i.e. failures beyond the 3 named above), stop and diagnose before proceeding** — do not proceed to a final "done" report with new failures. If only some subset of the 3 known pre-existing failures appear (the 2 that reproduce consistently, optionally the 3rd flaky one), this step passes.

---

## Self-Review Notes

- **Spec coverage:** Alembic merge (Tasks 1, 4) ✓. Regression test preventing recurrence (Task 2) ✓. Ghost-alert check, formalized as a permanent test rather than a one-off finding (Task 3) ✓. Full-suite regression check (Task 5) ✓.
- **No placeholders:** every step has literal file paths, literal code, and literal expected command output.
- **Type/name consistency checked:** `AlertRuleModel` field names (`condition_state`, `enabled`, `rule_json`, etc.) in Task 3's test match `backend/app/models/alert.py` exactly. Migration revision IDs (`d92f6a1c8e37`, `b3f7a1c9d4e2`, `b4e91a2f7c33`, `c1d2e3f4a5b6`, `a7f3e9b12c04`) are consistent across Tasks 1, 2, and 4.
