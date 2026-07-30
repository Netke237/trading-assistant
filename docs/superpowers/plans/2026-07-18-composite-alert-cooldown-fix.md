# Composite Chart Alert Cooldown Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop composite chart alert rules from sending duplicate emails/Telegram messages when the live (open-chart) evaluation path and the background scheduler both evaluate the same newly-closed candle within moments of each other.

**Architecture:** One gate, reusing existing logic. Standard (non-composite) chart alert rules already refuse to re-fire within `cooldown_minutes` of their last trigger, via `_is_cooldown_passed()` in `alert_evaluator.py`. The composite-rule branch of `evaluate_and_notify_for_symbol` (`chart_alerts.py`) never calls that function at all — it fires unconditionally whenever its trigger condition is true. The fix adds one `if not _is_cooldown_passed(...): continue` check to the composite branch, in the same position (after the sustain-state bookkeeping resolves `_fired`, before the notification is built and sent) that the standard-rule path already uses conceptually. `AlertRuleModel` (the SQLAlchemy row already in scope as `_row`) exposes `cooldown_minutes` and `last_triggered_at` with the exact attribute names `_is_cooldown_passed` expects, so it can be called directly on the ORM row — no adapter object needed.

**Tech Stack:** FastAPI + SQLAlchemy async (backend, pytest/pytest-asyncio). Tests use an in-memory SQLite engine, matching the existing pattern in `tests/test_chart_alerts_composite_ws.py`.

**Root cause (verified against the running code, not assumed):**
- `chart_alerts.py`'s composite-rule loop (currently `chart_alerts.py:611-689`) evaluates `_fired`, runs sustain-window bookkeeping, and — once `_fired` is true and sustain (if any) has elapsed — unconditionally builds and dispatches a notification. It never reads `_row.cooldown_minutes` or `_row.last_triggered_at` to decide whether to skip.
- Two independent callers evaluate the same rule for the same closed candle: the live WebSocket handler (`chart.py:90-93`, fires the instant a candle closes on an open chart) and `chart_alert_scheduler.py`'s background loop (polls every `alert_delivery.checkIntervalSeconds`, default 60s, unconfigured in `settings.yaml` so it is running on that default). The scheduler's own docstring (`chart_alert_scheduler.py:78-81`) explicitly documents this as a "known limitation," relying on `cooldown_minutes` to make a duplicate "rare and low-cost" — but that reliance is broken for composite rules, which have no cooldown check at all, so every double-evaluation of a composite rule produces a duplicate.
- Standard (non-composite) rules do NOT have this bug: `evaluate_rules()` (called for the standard-rule branch, `chart_alerts.py:534`) already calls `_is_cooldown_passed()` internally (`alert_evaluator.py:342`).
- `_is_cooldown_passed(rule, now)` (`alert_evaluator.py:75-82`) only reads `rule.last_triggered_at` and `rule.cooldown_minutes` — both are real columns on `AlertRuleModel` (`app/models/alert.py:18,21`) with those exact names, so the ORM row `_row` already in scope in the composite loop satisfies this function's expected interface without modification.

---

## Branch setup (do this first)

- [ ] **Step 0: Create a working branch off a clean `main`**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant"
git status --short          # confirm no unrelated uncommitted work is sitting here
git checkout main
git pull --ff-only origin main
git checkout -b fix/composite-alert-cooldown
```
Expected: branches from a clean, up-to-date `main` — `Switched to a new branch 'fix/composite-alert-cooldown'`. Branching from whatever happens to be checked out (rather than explicitly `main`) risks carrying unrelated uncommitted changes or an unrelated commit history onto this branch, which would both contaminate the diff and invalidate the "2 pre-existing failures" baseline in Task 2 Step 1 below — re-confirm that baseline on the actual starting tree if `git status --short` shows anything unexpected.

---

## Task 1: Add the cooldown gate to the composite rule path

**Files:**
- Modify: `backend/app/routers/chart_alerts.py` (import block `:20-23`; composite loop `:649-651`)
- Test: `backend/tests/test_chart_alerts_composite_ws.py` (add cases)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_chart_alerts_composite_ws.py`, after the existing `_HMM_TRIGGER_INTRADAY` constant and before the first `@pytest.mark.asyncio` test function (so the new constant is available to all tests below it):

```python
# Minimal trigger — no strategy_confirmations, so it fires without extra mocking.
_MINIMAL_TRIGGER_DEF = {"primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0}
```

This is byte-for-byte identical to the inline `trigger_def` literal already defined locally inside `test_ws_composite_path_skips_bars_fetch_when_not_needed` (currently `:133`). While adding the constant, also replace that existing inline literal with the new shared one so there is only one source of truth for it. Find (currently `:133`):

```python
    trigger_def = {"primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-3', 'AAPL', '15min', trigger_def))
```

Replace with:

```python
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-3', 'AAPL', '15min', _MINIMAL_TRIGGER_DEF))
```

Then add these three test functions at the end of the file:

```python
@pytest.mark.asyncio
async def test_ws_composite_path_suppresses_duplicate_fire_within_cooldown(monkeypatch):
    """Regression for the duplicate-email bug: the live WS path and the background
    scheduler (chart_alert_scheduler.py) can both evaluate the SAME closed candle
    within moments of each other. A composite rule with a cooldown must not fire
    twice for that — the second evaluate_and_notify_for_symbol call (simulating
    the second evaluator catching the same candle) must be suppressed."""
    from app.routers import chart_alerts

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)

    async with Session() as db:
        db.add(AlertRuleModel(
            id='rule-cooldown-1', user_id='default', name='Composite Rule',
            symbol='AAPL', interval='15min',
            enabled=True, rule_json=json.dumps({**_MINIMAL_TRIGGER_DEF, '__type': 'composite'}),
            cooldown_minutes=60, expiry_date=None,
            created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
        ))
        await db.commit()

    first = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(first) == 1

    # Simulate the second evaluator (scheduler or a second open chart tab)
    # catching the SAME closed candle moments later.
    second = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert second == [], "cooldown must suppress the duplicate fire"


@pytest.mark.asyncio
async def test_ws_composite_path_fires_again_once_cooldown_has_elapsed(monkeypatch):
    """The gate must not be permanent — once cooldown_minutes has genuinely
    elapsed since last_triggered_at, the rule must fire again."""
    from app.routers import chart_alerts

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)

    async with Session() as db:
        db.add(AlertRuleModel(
            id='rule-cooldown-2', user_id='default', name='Composite Rule',
            symbol='AAPL', interval='15min',
            enabled=True, rule_json=json.dumps({**_MINIMAL_TRIGGER_DEF, '__type': 'composite'}),
            cooldown_minutes=60, expiry_date=None,
            created_at='2024-01-01T00:00:00Z',
            last_triggered_at='2020-01-01T00:00:00',  # far beyond any cooldown
        ))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_ws_composite_path_zero_cooldown_still_fires_every_time(monkeypatch):
    """cooldown_minutes=0 (the value every other test in this file already uses via
    _make_composite_rule_row) must keep meaning 'no cooldown' — this locks in that
    the new gate doesn't change existing zero-cooldown rule behavior."""
    from app.routers import chart_alerts

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-cooldown-3', 'AAPL', '15min', _MINIMAL_TRIGGER_DEF))
        await db.commit()

    first = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    second = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(first) == 1
    assert len(second) == 1
```

- [ ] **Step 2: Run the tests to verify they fail as expected**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v`

Use `.venv/Scripts/python.exe` explicitly (not a bare `python`) — this repo's tests depend on packages (`tastytrade`, etc.) that are only installed in the project's own virtual environment.

Expected: `test_ws_composite_path_suppresses_duplicate_fire_within_cooldown` FAILS — `second` has length 1, not 0 (no cooldown gate exists yet). The other two new tests PASS already (they describe behavior that doesn't need the fix), and all pre-existing tests in the file still PASS.

- [ ] **Step 3: Add the import**

In `backend/app/routers/chart_alerts.py`, change the import block (`:20-23`):

```python
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
    _is_cooldown_passed,
)
```

- [ ] **Step 4: Add the cooldown gate**

In the composite-rule loop, find (currently `:649-651`):

```python
                if not _fired:
                    continue
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
```

Replace with:

```python
                if not _fired:
                    continue

                # Composite rules had no cooldown gate at all — unlike standard
                # rules (evaluate_rules() -> _is_cooldown_passed internally), which
                # meant a composite rule could fire and email TWICE for the same
                # closed candle whenever the live WS path (an open chart tab) and
                # the background scheduler (chart_alert_scheduler.py) both evaluated
                # it within moments of each other. Reuses the exact function the
                # standard-rule path already relies on — AlertRuleModel exposes the
                # same cooldown_minutes/last_triggered_at attributes
                # _is_cooldown_passed expects, so _row can be passed directly.
                if not _is_cooldown_passed(_row, datetime.now()):
                    # Log at debug level: without this, a cooldown-suppressed fire
                    # is indistinguishable in the logs from "the rule never fired,"
                    # which would make "why didn't I get an email" undiagnosable.
                    logger.debug(
                        'composite rule %s (%s [%s]) suppressed by cooldown_minutes=%s',
                        _row.id, symbol, interval, _row.cooldown_minutes,
                    )
                    continue

                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
```

`datetime` is already imported at the top of this file (`from datetime import date, datetime, timedelta`, line 10) — no new import needed for `datetime`. `logger` is also already defined at module level (`logger = logging.getLogger(__name__)`, line 29) — no new import needed for the log line either.

- [ ] **Step 5: Document the ORM-row duck-typing contract at its definition site**

`_is_cooldown_passed` is type-hinted for the `AlertRuleInput` dataclass, but this fix calls it with an `AlertRuleModel` ORM row instead — it works only because both expose `.last_triggered_at`/`.cooldown_minutes` under identical names, a coincidence of naming with no type-checker enforcement. Make that contract explicit where a future rename would need to see it. In `backend/app/services/alert_evaluator.py`, add a comment directly above `_is_cooldown_passed` (`:75`):

```python
def _is_cooldown_passed(rule: AlertRuleInput, now: datetime) -> bool:
    # Only reads .last_triggered_at and .cooldown_minutes — kept intentionally
    # duck-typed so chart_alerts.py's composite-rule path can call this with a
    # raw AlertRuleModel ORM row (which exposes the same two attribute names)
    # instead of constructing an AlertRuleInput. If either attribute is ever
    # renamed on ONE of these two types without the other, this silently
    # breaks with no type-checker warning — keep the names in sync.
    if not rule.last_triggered_at:
        return True
```

(Only the comment plus the existing `if not rule.last_triggered_at:` line are shown for placement — the rest of the function body is unchanged.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v`
Expected: all tests in the file PASS, including the new `test_ws_composite_path_suppresses_duplicate_fire_within_cooldown`.

- [ ] **Step 7: Run the broader chart-alert regression suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_alert_scheduler.py tests/test_chart_alerts_composite_create.py tests/test_chart_alerts_edit_resets_sustain.py tests/test_chart_alerts_sustain.py tests/test_composite_detailed_parity.py tests/test_composite_sustain.py tests/test_composite_trigger.py tests/test_composite_watch_router.py tests/test_alert_rule_disabled_cannot_fire.py -q`
Expected: all PASS — the fix only adds a new `continue` branch reachable exclusively when `cooldown_minutes > 0` AND a prior trigger is recent; it changes no other logic path.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_composite_ws.py
git commit -m "fix(chart-alerts): apply cooldown gate to composite rules

Composite rules never checked cooldown_minutes before dispatching a
notification, unlike standard rules. Combined with two independent
evaluators (the live WS path and the background scheduler) both
evaluating the same closed candle, this let a composite rule fire and
email twice for a single trigger. Reuses the same _is_cooldown_passed
check the standard-rule path already relies on."
```

---

## Task 2: Full verification pass

- [ ] **Step 1: Full backend suite via the project's venv**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: no new failures versus the pre-fix baseline (2 pre-existing, unrelated failures in `test_market_data_fixes.py` — `test_iv_enrichment_skipped_when_ibkr_returns_none` and `test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore` — are a separate, already-identified test gap and are out of scope for this fix).

- [ ] **Step 2: Report** the verification output to the user.

---

## Notes / deliberate non-goals

- **Not fixing the underlying "two evaluators can race" architecture.** The scheduler's docstring already accepts this as a known, low-cost limitation for standard rules; this fix brings composite rules up to the same accepted risk level (a rule row read-then-write across two independent DB sessions can theoretically still race within a few-hundred-millisecond window), not zero risk. That parity is the intended scope — building a distributed lock for a personal trading assistant's alert dispatch is not warranted.
- **Not changing `cooldown_minutes` defaults or exposing a composite-rule-specific cooldown UI control.** The existing `cooldown_minutes` field (already on every rule, default 60, already editable via the existing rule CRUD) is reused as-is.
- **Not touching the 60-second background poll interval.** That's a separate, working design choice (unconfigured, using its documented default) and not part of the reported bug.
