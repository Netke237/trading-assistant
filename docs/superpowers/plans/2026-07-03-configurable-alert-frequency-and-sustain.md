# Configurable Alert Frequency + Sustain Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap where chart-drawn alert rules only evaluate while their exact symbol+interval chart is open in a browser tab, make the background check cadence configurable (default ~60s instead of the hardcoded 15 min), and add an optional "sustain for N minutes" filter to every alert condition type so noisy single-tick triggers can be smoothed out.

**Architecture:** Reuse the existing `evaluate_and_notify_for_symbol()` orchestration (already used by `chart.py`'s websocket on candle-close) from a new headless background scheduler, so chart-drawn rules fire even with no browser open. Add a `checkIntervalSeconds` knob to the existing `AlertDeliveryConfig` (`/settings/alert-delivery`) and have both the portfolio monitor and the new chart-rule scheduler read it each tick. Add `sustain_minutes` to each condition dataclass and a new `condition_state` DB column to persist per-condition "how long has this been true" clocks across ticks.

**Tech Stack:** FastAPI + SQLAlchemy v2 (async) + Alembic on the backend; Next.js/Zustand on the frontend. No new dependencies.

---

## Codebase state (verified 2026-07-04 — read before starting)

Since this plan was first drafted, several alert-related changes landed on `main`. This plan has been reconciled against them. Things an implementer must know:

- **Test command:** run backend tests with `venv/Scripts/python.exe -m pytest` (from `backend/`). `backend/tests/conftest.py` pins the suite to in-memory SQLite (`sqlite+aiosqlite:///:memory:`) so tests never touch the real Postgres/`dev.db` — do not add your own engine that points elsewhere. Every `Run:` line below that says `pytest` means `venv/Scripts/python.exe -m pytest`.
- **Current Alembic head is `a7f3e9b12c04`** (`a7f3e9b12c04_drop_orphan_kids_app_schema.py`). The two migrations this plan creates (Tasks 4 and 9) chain from it — revision ids and `down_revision`s below already reflect this. Do not reuse the ids from an earlier draft.
- **`portfolio_positions` already has `entry_stock_price`** (migration `f14c8c7e35e8`) and no longer has `updated_at` (dropped in `41919f210c18`). Task 9's model snippet matches the current model; it only adds `alert_state`.
- **`alert_evaluator.py` gained a third regime model, `HMM_directional`** (`_REGIME_MODEL_NAMES = ('OMM', 'HMM', 'HMM_directional')`), and `_evaluate_regime_condition` was refactored to loop over candidates with OMM-scoped sign-flipping. None of this changes the condition dataclasses or `evaluate_rules`' loop that Task 3 edits — Task 3's anchors still match verbatim.
- **The composite WS path in `chart_alerts.py` was rewritten** to a single `evaluate_from_context_detailed()` entry point returning `(fired, detail)`, with per-rule daily-bar selection and a `MAX_LIVE_MODEL_CANDLES` (1500) fit-window cap. Task 12's WS-path edit and its tests below already target this new shape (not the old `evaluate_from_context` + `describe_match` pair).
- **Frontend condition types already carry `id?: string`** (stable-key work landed). Task 8's `types/alerts.ts` edit below adds `sustain_minutes?` alongside that existing `id?` field.
- **`MAX_TEST_RULE_CANDLES` (1500) already guards `test_rule`.** Task 5's dry-run fix edits only the loop body below that guard — leave the guard in place.

---

### Task 1: `checkIntervalSeconds` config knob

**Files:**
- Modify: `backend/app/routers/notification_settings.py:44-111`
- Test: `backend/tests/test_notification_settings.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_notification_settings.py`:

```python
def test_alert_delivery_roundtrips_check_interval_seconds(client):
    """POST /settings/alert-delivery persists checkIntervalSeconds and GET returns it."""
    resp = client.post('/settings/alert-delivery', json={
        'masterEnabled': True,
        'enabledTypes': ['STOP_REACHED'],
        'dedupWindowMinutes': 15,
        'reminderIntervalHours': 4,
        'retentionDays': 30,
        'checkIntervalSeconds': 90,
    })
    assert resp.status_code == 200
    assert resp.json()['checkIntervalSeconds'] == 90

    get_resp = client.get('/settings/alert-delivery')
    assert get_resp.status_code == 200
    assert get_resp.json()['checkIntervalSeconds'] == 90


def test_alert_delivery_check_interval_seconds_defaults_to_60(client):
    r = client.get('/settings/alert-delivery')
    assert r.status_code == 200
    assert r.json()['checkIntervalSeconds'] == 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_notification_settings.py -k check_interval -v`
Expected: FAIL with `KeyError: 'checkIntervalSeconds'`

- [ ] **Step 3: Add the field to the schema, default, GET, and POST**

In `backend/app/routers/notification_settings.py`, update the default dict, model, and both handlers:

```python
_DEFAULT_DELIVERY = {
    'masterEnabled': True,
    'enabledTypes': _SUPPORTED_TYPES,
    'dedupWindowMinutes': 15,
    # While a condition stays true, how often email/Telegram reminds you.
    'reminderIntervalHours': 4,
    'retentionDays': 30,
    # How often background monitors (portfolio + chart-drawn rules) re-check
    # conditions. Lower = faster detection, more API/price-fetch load.
    'checkIntervalSeconds': 60,
}


class AlertDeliveryConfig(BaseModel):
    masterEnabled: bool = True
    enabledTypes: list[str] = _SUPPORTED_TYPES
    dedupWindowMinutes: int = 15
    reminderIntervalHours: int = 4
    retentionDays: int = 30
    checkIntervalSeconds: int = 60
```

```python
@router.get('/alert-delivery')
async def get_alert_delivery() -> dict:
    cfg = _load_yaml()
    d = cfg.get('alert_delivery', _DEFAULT_DELIVERY)
    return {
        'masterEnabled': bool(d.get('masterEnabled', True)),
        'enabledTypes': d.get('enabledTypes', _SUPPORTED_TYPES),
        'dedupWindowMinutes': int(d.get('dedupWindowMinutes', 15)),
        'reminderIntervalHours': int(d.get('reminderIntervalHours', 4)),
        'retentionDays': int(d.get('retentionDays', 30)),
        'checkIntervalSeconds': int(d.get('checkIntervalSeconds', 60)),
    }


@router.post('/alert-delivery')
async def save_alert_delivery(body: AlertDeliveryConfig) -> dict:
    cfg = _load_yaml()
    cfg['alert_delivery'] = {
        'masterEnabled': body.masterEnabled,
        'enabledTypes': body.enabledTypes,
        'dedupWindowMinutes': body.dedupWindowMinutes,
        'reminderIntervalHours': body.reminderIntervalHours,
        'retentionDays': body.retentionDays,
        'checkIntervalSeconds': max(15, body.checkIntervalSeconds),
    }
    _save_yaml(cfg)
    return cfg['alert_delivery']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_notification_settings.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/notification_settings.py backend/tests/test_notification_settings.py
git commit -m "feat(alerts): add configurable checkIntervalSeconds to alert-delivery settings"
```

---

### Task 2: Make the portfolio alert monitor's interval configurable

**Files:**
- Modify: `backend/app/services/portfolio_alert_monitor.py:22-23,153-161`
- Test: Create `backend/tests/test_portfolio_alert_monitor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_portfolio_alert_monitor.py`:

```python
# backend/tests/test_portfolio_alert_monitor.py
from __future__ import annotations

import app.services.portfolio_alert_monitor as monitor


def test_check_interval_seconds_uses_configured_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 90})
    assert monitor._check_interval_seconds() == 90


def test_check_interval_seconds_falls_back_to_default_when_missing(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL


def test_check_interval_seconds_enforces_floor_of_15(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 1})
    assert monitor._check_interval_seconds() == 15


def test_check_interval_seconds_handles_garbage_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 'oops'})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_portfolio_alert_monitor.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_check_interval_seconds'`

- [ ] **Step 3: Replace the hardcoded constant with a configurable helper**

In `backend/app/services/portfolio_alert_monitor.py`, replace line 23:

```python
_CHECK_INTERVAL = 15 * 60  # seconds
```

with:

```python
_DEFAULT_CHECK_INTERVAL = 60  # seconds — used until alert_delivery.checkIntervalSeconds overrides it
```

Then replace the `run_portfolio_alert_monitor` function (lines 153-161):

```python
def _check_interval_seconds() -> int:
    try:
        return max(15, int(_load_delivery_config().get('checkIntervalSeconds', _DEFAULT_CHECK_INTERVAL)))
    except (TypeError, ValueError):
        return _DEFAULT_CHECK_INTERVAL


async def run_portfolio_alert_monitor() -> None:
    """Long-running loop started in app lifespan. Interval is re-read from
    alert_delivery.checkIntervalSeconds every tick, so a settings change takes
    effect on the next cycle without a restart."""
    logger.info('Portfolio alert monitor started (default interval=%ds)', _DEFAULT_CHECK_INTERVAL)
    while True:
        try:
            await _run_once()
        except Exception:
            logger.error('Portfolio alert monitor tick failed', exc_info=True)
        await asyncio.sleep(_check_interval_seconds())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_portfolio_alert_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/portfolio_alert_monitor.py backend/tests/test_portfolio_alert_monitor.py
git commit -m "feat(alerts): read portfolio monitor check interval from alert_delivery config"
```

---

### Task 3: `sustain_minutes` on conditions + sustain evaluation logic

**Files:**
- Modify: `backend/app/services/alert_evaluator.py:11-46,238-279`
- Test: `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alert_evaluator.py`:

```python
class TestSustainMinutes:
    def test_sustain_condition_not_met_on_first_true_check(self):
        condition = PriceCondition(kind='price', operator='>', value=100, sustain_minutes=5)
        rule = make_rule(conditions=[condition])
        candle = make_candle(c=103)
        now = datetime(2024, 1, 2, 9, 30)
        results = evaluate_rules([rule], candle, [candle], {}, [], now)
        assert len(results) == 0
        assert rule.condition_state['0'] == now.isoformat()

    def test_sustain_condition_met_after_elapsed_window(self):
        condition = PriceCondition(kind='price', operator='>', value=100, sustain_minutes=5)
        rule = make_rule(conditions=[condition])
        candle = make_candle(c=103)
        t0 = datetime(2024, 1, 2, 9, 30)
        evaluate_rules([rule], candle, [candle], {}, [], t0)
        t1 = t0 + timedelta(minutes=6)
        results = evaluate_rules([rule], candle, [candle], {}, [], t1)
        assert len(results) == 1

    def test_sustain_condition_still_pending_before_window_elapses(self):
        condition = PriceCondition(kind='price', operator='>', value=100, sustain_minutes=5)
        rule = make_rule(conditions=[condition])
        candle = make_candle(c=103)
        t0 = datetime(2024, 1, 2, 9, 30)
        evaluate_rules([rule], candle, [candle], {}, [], t0)
        t1 = t0 + timedelta(minutes=2)
        results = evaluate_rules([rule], candle, [candle], {}, [], t1)
        assert len(results) == 0

    def test_sustain_condition_resets_when_no_longer_met(self):
        condition = PriceCondition(kind='price', operator='>', value=100, sustain_minutes=5)
        rule = make_rule(conditions=[condition])
        t0 = datetime(2024, 1, 2, 9, 30)
        evaluate_rules([rule], make_candle(c=103), [make_candle(c=103)], {}, [], t0)
        t1 = t0 + timedelta(minutes=2)
        evaluate_rules([rule], make_candle(c=90), [make_candle(c=90)], {}, [], t1)
        assert '0' not in rule.condition_state
        t2 = t1 + timedelta(minutes=6)
        results = evaluate_rules([rule], make_candle(c=103), [make_candle(c=103)], {}, [], t2)
        assert len(results) == 0  # clock only just restarted at t2

    def test_no_sustain_behaves_instantly_as_before(self):
        condition = PriceCondition(kind='price', operator='>', value=100)  # sustain_minutes=None
        rule = make_rule(conditions=[condition])
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_alert_evaluator.py -k Sustain -v`
Expected: FAIL with `TypeError: PriceCondition.__init__() got an unexpected keyword argument 'sustain_minutes'`

- [ ] **Step 3: Add `sustain_minutes` to each condition dataclass and `condition_state` to `AlertRuleInput`**

In `backend/app/services/alert_evaluator.py`, update the four condition dataclasses and `AlertRuleInput`:

```python
@dataclass
class PriceCondition:
    kind: Literal['price']
    operator: str
    value: float
    sustain_minutes: Optional[int] = None


@dataclass
class IndicatorCondition:
    kind: Literal['indicator']
    indicator: str
    operator: str
    value: float
    sustain_minutes: Optional[int] = None


@dataclass
class StructureCondition:
    kind: Literal['structure']
    signal_kind: str
    direction: Optional[str] = None
    min_confidence: Optional[int] = None
    sustain_minutes: Optional[int] = None


@dataclass
class RegimeCondition:
    kind: Literal['regime']
    model: str = 'OMM'        # 'OMM' | 'HMM' | 'any'
    state: str = 'Bull'       # 'Bull' | 'Bear' | 'Choppy' | 'any'
    min_conviction: Optional[float] = None
    sustain_minutes: Optional[int] = None
```

```python
@dataclass
class AlertRuleInput:
    id: str
    name: str
    symbol: str
    interval: str
    enabled: bool
    group: ConditionGroup
    cooldown_minutes: int
    expiry_date: Optional[str]
    created_at: str
    last_triggered_at: Optional[str]
    condition_state: dict = field(default_factory=dict)
```

- [ ] **Step 4: Implement sustain tracking in `evaluate_rules`**

Replace the condition-evaluation loop inside `evaluate_rules` (originally):

```python
        accumulated_trigger_values: dict = {}
        evaluations = []
        for c in rule.group.conditions:
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'], regime_by_model)
            accumulated_trigger_values.update(tv)
            evaluations.append(met)
```

with:

```python
        accumulated_trigger_values: dict = {}
        evaluations = []
        for cond_index, c in enumerate(rule.group.conditions):
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'], regime_by_model)
            accumulated_trigger_values.update(tv)

            sustain_min = getattr(c, 'sustain_minutes', None)
            if sustain_min:
                key = str(cond_index)
                if met:
                    pending_since_str = rule.condition_state.get(key)
                    if pending_since_str is None:
                        # First tick this condition is true — start the clock,
                        # but it hasn't been sustained for sustain_min yet.
                        rule.condition_state[key] = now.isoformat()
                        met = False
                    else:
                        pending_since = datetime.fromisoformat(pending_since_str)
                        elapsed_min = (now - pending_since).total_seconds() / 60.0
                        met = elapsed_min >= sustain_min
                else:
                    rule.condition_state.pop(key, None)

            evaluations.append(met)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_alert_evaluator.py -v`
Expected: PASS (all tests, existing + new)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/alert_evaluator.py backend/tests/test_alert_evaluator.py
git commit -m "feat(alerts): add optional sustain_minutes filter to alert conditions"
```

---

### Task 4: Persist per-condition sustain state (`condition_state` column)

**Files:**
- Modify: `backend/app/models/alert.py:8-26`
- Create: `backend/migrations/versions/c1d2e3f4a5b6_add_condition_state_to_alert_rules.py`

- [ ] **Step 1: Add the column to the model**

In `backend/app/models/alert.py`, add a line to `AlertRuleModel`:

```python
class AlertRuleModel(Base):
    __tablename__ = 'alert_rules'

    id = Column(String(36), primary_key=True)
    user_id = Column(String(64), nullable=False, default='default')
    name = Column(String(200), nullable=False)
    symbol = Column(String(10), nullable=False)
    interval = Column(String(10), nullable=False)
    enabled = Column(Boolean(), nullable=False, default=True)
    rule_json = Column(Text(), nullable=False)
    cooldown_minutes = Column(Integer(), nullable=False, default=60)
    expiry_date = Column(Text(), nullable=True)
    created_at = Column(Text(), nullable=False)
    last_triggered_at = Column(Text(), nullable=True)
    condition_state = Column(Text(), nullable=False, default='{}')

    __table_args__ = (
        Index('ix_alert_rules_symbol', 'symbol'),
        Index('ix_alert_rules_user_id', 'user_id'),
    )
```

- [ ] **Step 2: Write the migration**

Create `backend/migrations/versions/c1d2e3f4a5b6_add_condition_state_to_alert_rules.py`:

```python
"""add condition_state to alert_rules

Revision ID: c1d2e3f4a5b6
Revises: a7f3e9b12c04
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'a7f3e9b12c04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'alert_rules',
        sa.Column('condition_state', sa.Text(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('alert_rules', 'condition_state')
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade a7f3e9b12c04 -> c1d2e3f4a5b6, add condition_state to alert_rules`

- [ ] **Step 4: Verify the column exists**

Run: `cd backend && python -c "from sqlalchemy import inspect, create_engine; import os; e = create_engine(os.environ.get('DATABASE_URL_SYNC', 'sqlite:///./bamendjou.db')); print([c['name'] for c in inspect(e).get_columns('alert_rules')])"`
Expected: output list includes `condition_state`

(If the project's dev DB URL differs, use whatever sync connection string `alembic upgrade head` itself used — check `backend/migrations/env.py` for the exact source if the above command errors.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/alert.py backend/migrations/versions/c1d2e3f4a5b6_add_condition_state_to_alert_rules.py
git commit -m "feat(alerts): add condition_state column for sustain-minutes tracking"
```

---

### Task 5: Wire `sustain_minutes` + `condition_state` through the chart-alerts router

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:152-171,337-360,391-429`
- Test: Create `backend/tests/test_chart_alerts_sustain.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chart_alerts_sustain.py`:

```python
# backend/tests/test_chart_alerts_sustain.py
"""Integration test: sustain_minutes survives a round trip through
_deserialize_rule -> evaluate_rules -> persisted condition_state."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from app.routers.chart_alerts import _deserialize_rule
from app.services.alert_evaluator import evaluate_rules


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule_row(condition_state='{}'):
    rule_json = json.dumps({
        'logic': 'AND',
        'conditions': [{'kind': 'price', 'operator': '>', 'value': 100, 'sustain_minutes': 5}],
    })
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Sustain rule', symbol='AAPL', interval='15min',
        enabled=True, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
        condition_state=condition_state,
    )


@pytest.mark.asyncio
async def test_deserialized_rule_carries_sustain_minutes_and_condition_state():
    row = _rule_row(condition_state=json.dumps({'0': '2024-01-02T09:30:00'}))
    rule_input = _deserialize_rule(row.rule_json, row)
    assert rule_input.group.conditions[0].sustain_minutes == 5
    assert rule_input.condition_state == {'0': '2024-01-02T09:30:00'}


@pytest.mark.asyncio
async def test_sustain_state_round_trips_through_evaluate_rules():
    row = _rule_row(condition_state=json.dumps({'0': '2024-01-02T09:30:00'}))
    rule_input = _deserialize_rule(row.rule_json, row)
    candle = {'time': '2024-01-02T09:45', 'open': 100, 'high': 106, 'low': 99, 'close': 103, 'volume': 1000}
    now = datetime(2024, 1, 2, 9, 36)  # 6 minutes after the recorded pending_since
    results = evaluate_rules([rule_input], candle, [candle], {}, [], now)
    assert len(results) == 1
    # Persisting back to the row (as evaluate_and_notify_for_symbol does) must
    # reflect the mutated state.
    row.condition_state = json.dumps(rule_input.condition_state)
    assert json.loads(row.condition_state) == {'0': '2024-01-02T09:30:00'}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_chart_alerts_sustain.py -v`
Expected: FAIL — `_deserialize_rule` does not pass `sustain_minutes` or `condition_state` yet, so the first assertion fails (`sustain_minutes` is `None`, `condition_state` is `{}`)

- [ ] **Step 3: Update `_deserialize_rule` to carry `sustain_minutes` and `condition_state`**

Replace `_deserialize_rule` in `backend/app/routers/chart_alerts.py`:

```python
def _deserialize_rule(rule_json_str: str, row: AlertRuleModel) -> AlertRuleInput:
    group_data = json.loads(rule_json_str)
    conditions = []
    for c in group_data.get('conditions', []):
        kind = c.get('kind', '')
        if kind == 'price':
            conditions.append(PriceCondition(
                kind='price', operator=c['operator'], value=c['value'],
                sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'indicator':
            conditions.append(IndicatorCondition(
                kind='indicator', indicator=c['indicator'], operator=c['operator'], value=c['value'],
                sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'structure':
            conditions.append(StructureCondition(
                kind='structure', signal_kind=c['signal_kind'], direction=c.get('direction'),
                min_confidence=c.get('min_confidence'), sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'regime':
            conditions.append(RegimeCondition(
                kind='regime', model=c.get('model', 'OMM'), state=c.get('state', 'Bull'),
                min_conviction=c.get('min_conviction'), sustain_minutes=c.get('sustain_minutes'),
            ))
    return AlertRuleInput(
        id=row.id, name=row.name, symbol=row.symbol, interval=row.interval,
        enabled=bool(row.enabled),
        group=ConditionGroup(logic=group_data.get('logic', 'AND'), conditions=conditions),
        cooldown_minutes=row.cooldown_minutes, expiry_date=row.expiry_date,
        created_at=row.created_at, last_triggered_at=row.last_triggered_at,
        condition_state=json.loads(row.condition_state or '{}'),
    )
```

- [ ] **Step 4: Persist mutated `condition_state` back to the DB row after evaluation**

In `evaluate_and_notify_for_symbol`, immediately after the line:

```python
        triggered = evaluate_rules(rule_inputs, closed_candle, all_candles, indicators, signals, datetime.now(), regime_by_model)
```

add:

```python
        for _ri, _row in zip(rule_inputs, rows):
            _row.condition_state = json.dumps(_ri.condition_state)
```

- [ ] **Step 5: Fix the dry-run `/rules/{rule_id}/test` endpoint to use candle time, not wall-clock time**

This is required for `sustain_minutes` to be testable through the manual dry-run tool at all — a loop that calls `datetime.now()` on every iteration advances by microseconds in real time, so a 5-minute sustain window would never elapse no matter how many historical candles are replayed. Replace the loop body in `test_rule`:

```python
    rule_input = _deserialize_rule(row.rule_json, row)
    needs_regime = any(c.kind == 'regime' for c in rule_input.group.conditions)
    matches = []
    for i in range(len(body.candles)):
        candle = body.candles[i]
        window = body.candles[:i + 1]
        # Rebuilt every iteration (not once) so each candle's regime condition is
        # evaluated causally, matching only data available up to that point — but
        # this means compute_intraday_hmm's iterative HMM fit re-runs once per
        # candle once the window passes its 200-bar minimum. Acceptable for this
        # manual dry-run endpoint's typical candle-list sizes; a very large paste
        # would make this proportionally slower.
        regime_by_model = build_regime_snapshot(window) if needs_regime else None
        # Use the candle's own timestamp as "now" (not wall-clock time) so
        # cooldown and sustain_minutes are evaluated against simulated time —
        # replaying history in real time would make sustain windows never elapse.
        candle_time = datetime.fromisoformat(candle['time'])
        results = evaluate_rules([rule_input], candle, window, body.indicators, body.signals, candle_time, regime_by_model)
        matches.extend(results)
    return {'matches': matches}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_chart_alerts_sustain.py tests/test_alert_evaluator.py tests/test_chart_alerts_composite_ws.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_sustain.py
git commit -m "feat(alerts): wire sustain_minutes and condition_state through chart-alerts router"
```

---

### Task 6: Background scheduler for chart-drawn alert rules

**Files:**
- Create: `backend/app/services/chart_alert_scheduler.py`
- Modify: `backend/app/main.py:49-88`
- Test: Create `backend/tests/test_chart_alert_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chart_alert_scheduler.py`:

```python
# backend/tests/test_chart_alert_scheduler.py
"""Background scheduler that evaluates chart-drawn alert rules even when no
chart is open, mirroring what chart.py's websocket does on candle-close."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule_row():
    rule_json = json.dumps({'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]})
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Rule', symbol='AAPL', interval='15min',
        enabled=True, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_CANDLES_V1 = [
    {'time': f't{i}', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
    for i in range(5)
]


@pytest.mark.asyncio
async def test_tick_evaluates_each_enabled_symbol_interval_once_per_new_candle(monkeypatch):
    import app.services.chart_alert_scheduler as sched

    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_rule_row())
        await db.commit()

    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(sched, 'get_intraday', AsyncMock(return_value=_CANDLES_V1))
    monkeypatch.setattr(sched, 'compute_structure', lambda *a, **kw: [])
    mock_evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', mock_evaluate)
    sched._last_seen_candle.clear()

    await sched._tick()
    assert mock_evaluate.await_count == 1
    assert mock_evaluate.await_args.args[0] == 'AAPL'
    assert mock_evaluate.await_args.args[1] == '15min'

    # Same candles again (no new close) — must NOT re-evaluate.
    await sched._tick()
    assert mock_evaluate.await_count == 1


@pytest.mark.asyncio
async def test_tick_skips_when_no_enabled_rules(monkeypatch):
    import app.services.chart_alert_scheduler as sched

    Session = await _make_session_factory()
    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    get_intraday_mock = AsyncMock(return_value=_CANDLES_V1)
    monkeypatch.setattr(sched, 'get_intraday', get_intraday_mock)
    sched._last_seen_candle.clear()

    await sched._tick()
    get_intraday_mock.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_chart_alert_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.chart_alert_scheduler'`

- [ ] **Step 3: Create the scheduler**

Create `backend/app/services/chart_alert_scheduler.py`:

```python
# backend/app/services/chart_alert_scheduler.py
"""Background loop that evaluates chart-drawn alert rules even when no chart
is open in a browser. Mirrors the candle-close evaluation chart.py's
websocket already does, but runs unconditionally on a configurable cadence.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml
from sqlalchemy import select

from app.data.chart_cache import get_intraday
from app.database import AsyncSessionLocal
from app.models.alert import AlertRuleModel
from app.services.market_structure import compute_structure

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'
_DEFAULT_CHECK_INTERVAL = 60  # seconds

# (symbol, interval) -> last-seen closed-candle time, so a tick only
# re-evaluates once per newly-closed candle rather than on every poll.
_last_seen_candle: dict[tuple[str, str], str] = {}


def _load_check_interval_seconds() -> int:
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            return max(15, int(cfg.get('alert_delivery', {}).get('checkIntervalSeconds', _DEFAULT_CHECK_INTERVAL)))
    except (TypeError, ValueError, OSError):
        logger.debug('Could not load checkIntervalSeconds', exc_info=True)
    return _DEFAULT_CHECK_INTERVAL


async def _tick() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AlertRuleModel.symbol, AlertRuleModel.interval)
            .where(AlertRuleModel.enabled == True)  # noqa: E712
            .distinct()
        )
        pairs = result.all()

    if not pairs:
        return

    from app.routers.chart_alerts import evaluate_and_notify_for_symbol

    for symbol, interval in pairs:
        try:
            candles = await get_intraday(symbol, interval)
            if not candles or len(candles) < 2:
                continue
            closed = candles[-2]
            key = (symbol, interval)
            if _last_seen_candle.get(key) == closed['time']:
                continue  # already evaluated this closed candle
            _last_seen_candle[key] = closed['time']

            ht_candles = await get_intraday(symbol, '1D') if interval == '1h' else None
            signals = compute_structure(candles, interval, symbol, ht_candles)

            await evaluate_and_notify_for_symbol(symbol, interval, closed, candles, signals)
        except Exception:
            logger.warning('chart alert background check failed for %s [%s]', symbol, interval, exc_info=True)


async def run_chart_alert_scheduler() -> None:
    """Long-running loop started in app lifespan. Evaluates chart-drawn alert
    rules on a configurable cadence, independent of any open chart tab.

    Known limitation: if a browser also has this exact symbol+interval chart
    open at the same time, both paths may evaluate the same newly-closed
    candle within moments of each other. The rule's own cooldown_minutes
    (default 60) makes a duplicate notification rare and low-cost even so.
    """
    logger.info('Chart alert background scheduler started (default interval=%ds)', _DEFAULT_CHECK_INTERVAL)
    while True:
        try:
            await _tick()
        except Exception:
            logger.error('chart alert scheduler tick failed', exc_info=True)
        await asyncio.sleep(_load_check_interval_seconds())
```

- [ ] **Step 4: Register the scheduler in the app lifespan**

In `backend/app/main.py`, update the module-level task variables (line 49-51):

```python
_notification_worker_task: asyncio.Task | None = None
_portfolio_monitor_task: asyncio.Task | None = None
_regime_monitor_task: asyncio.Task | None = None
_chart_alert_scheduler_task: asyncio.Task | None = None
```

And in `lifespan()`, update the `global` statement and add the new task (lines 56, 87-88):

```python
    global _notification_worker_task, _portfolio_monitor_task, _regime_monitor_task, _chart_alert_scheduler_task
```

```python
    from app.services.regime_monitor import run_regime_monitor
    _regime_monitor_task = asyncio.create_task(run_regime_monitor())
    from app.services.chart_alert_scheduler import run_chart_alert_scheduler
    _chart_alert_scheduler_task = asyncio.create_task(run_chart_alert_scheduler())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_chart_alert_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/chart_alert_scheduler.py backend/app/main.py backend/tests/test_chart_alert_scheduler.py
git commit -m "feat(alerts): run chart-drawn alert rules on a background schedule, not just while a chart is open"
```

---

### Task 7: Frontend — expose `checkIntervalSeconds` in the Alerts settings UI

**Files:**
- Modify: `frontend/types/domain.ts:375-382`
- Modify: `frontend/lib/alertStore.ts:24-35`
- Modify: `frontend/app/(frame)/alerts/page.tsx:140-180,298-323`

- [ ] **Step 1: Add the field to the `AlertConfig` type**

In `frontend/types/domain.ts`, update `AlertConfig`:

```typescript
export interface AlertConfig {
  dedupWindowMinutes: number;      // default 15 — min spacing before re-reporting to backend
  reminderIntervalHours: number;   // default 4 — email/Telegram reminder gap while a condition stays true
  checkIntervalSeconds: number;    // default 60 — how often background monitors re-check conditions
  enabledTypes: AlertType[];
  soundEnabled: boolean;
  keepAlertsDays: number;          // default 10 — auto-purge after N days
  retentionDays: number;           // default 30 — backend sent-message log retention (days)
}
```

- [ ] **Step 2: Add the default value**

In `frontend/lib/alertStore.ts`, update `DEFAULT_CONFIG`:

```typescript
export const DEFAULT_CONFIG: AlertConfig = {
  dedupWindowMinutes: 15,
  reminderIntervalHours: 4,
  checkIntervalSeconds: 60,
  keepAlertsDays: 30,
  retentionDays: 30,
  enabledTypes: [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP',
    'EVENT_RISK', 'REGIME_CHANGE', 'SCAN_COMPLETE', 'SCAN_FAILED',
    'TIME_STOP_APPROACHING', 'EARNINGS_APPROACHING', 'EXPIRATION_APPROACHING',
  ],
  soundEnabled: false,
};
```

- [ ] **Step 3: Load and save it alongside the other delivery prefs**

In `frontend/app/(frame)/alerts/page.tsx`, update the load effect (originally lines 141-158):

```typescript
  useEffect(() => {
    fetch(`${BASE_URL}/settings/alert-delivery`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) {
          setConfig({
            ...config,
            enabledTypes: data.enabledTypes ?? config.enabledTypes,
            dedupWindowMinutes: data.dedupWindowMinutes ?? config.dedupWindowMinutes,
            reminderIntervalHours: data.reminderIntervalHours ?? config.reminderIntervalHours,
            retentionDays: data.retentionDays ?? config.retentionDays,
            checkIntervalSeconds: data.checkIntervalSeconds ?? config.checkIntervalSeconds,
          });
        }
        deliveryLoaded.current = true;
      })
      .catch(() => { deliveryLoaded.current = true; });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [BASE_URL]);
```

And the save effect (originally lines 161-180):

```typescript
  useEffect(() => {
    if (!deliveryLoaded.current) return;
    if (deliverySyncTimer.current) clearTimeout(deliverySyncTimer.current);
    deliverySyncTimer.current = setTimeout(() => {
      fetch(`${BASE_URL}/settings/alert-delivery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          masterEnabled: true,
          enabledTypes: config.enabledTypes,
          dedupWindowMinutes: config.dedupWindowMinutes,
          reminderIntervalHours: config.reminderIntervalHours,
          retentionDays: config.retentionDays,
          checkIntervalSeconds: config.checkIntervalSeconds,
        }),
      }).catch(() => {});
    }, 800);
    return () => {
      if (deliverySyncTimer.current) clearTimeout(deliverySyncTimer.current);
    };
  }, [BASE_URL, config.enabledTypes, config.dedupWindowMinutes, config.reminderIntervalHours, config.retentionDays, config.checkIntervalSeconds]);
```

- [ ] **Step 4: Add the input row**

In `frontend/app/(frame)/alerts/page.tsx`, add a new `SettingsRow` right after the "Deduplication window (min)" row (originally lines 298-310):

```tsx
              <SettingsRow label="Background check frequency (sec)" hint="How often the server re-checks price/portfolio/chart-rule alerts, even with the app closed. Lower = faster detection, more API calls." defaultValue="60">
                <input
                  type="number"
                  className={styles.input}
                  min={15}
                  max={900}
                  value={config.checkIntervalSeconds}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val >= 15 && val <= 900) setConfig({ ...config, checkIntervalSeconds: val });
                  }}
                />
              </SettingsRow>
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 6: Manually verify in the browser**

Run: `cd frontend && npm run dev`, open `/alerts`, confirm the new "Background check frequency (sec)" field appears under Alert Settings, change its value, reload the page, and confirm the value persisted (round-tripped through `/settings/alert-delivery`).

- [ ] **Step 7: Commit**

```bash
git add frontend/types/domain.ts frontend/lib/alertStore.ts "frontend/app/(frame)/alerts/page.tsx"
git commit -m "feat(alerts): expose background check frequency in the Alerts settings UI"
```

---

### Task 8: Frontend — `sustain_minutes` field on alert-rule conditions

**Files:**
- Modify: `frontend/types/alerts.ts:10-35`
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx:41-55,211-372`

- [ ] **Step 1: Add `sustain_minutes` to each condition type**

In `frontend/types/alerts.ts`, update the four condition interfaces (note: each already has an `id?: string` field from the stable-key work — keep it, add `sustain_minutes?` after the kind-specific fields):

```typescript
export interface PriceCondition {
  kind: 'price';
  id?: string;
  operator: ConditionOperator;
  value: number;
  sustain_minutes?: number;
}

export interface IndicatorCondition {
  kind: 'indicator';
  id?: string;
  indicator: string;
  operator: ConditionOperator;
  value: number;
  sustain_minutes?: number;
}

export interface StructureCondition {
  kind: 'structure';
  id?: string;
  signal_kind: SignalKind;
  direction?: 'bullish' | 'bearish';
  min_confidence?: number;
  sustain_minutes?: number;
}

export interface RegimeCondition {
  kind: 'regime';
  id?: string;
  model: RegimeModel;
  state: RegimeState;
  min_conviction?: number;
  sustain_minutes?: number;
}
```

- [ ] **Step 2: Add a shared "Hold for (min)" input to every condition row**

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, add the field after the kind-specific inputs and before the remove button, inside the `conditions.map(...)` block (originally right before line 362's `{conditions.length > 1 && (`):

```tsx
              <input
                className={styles.numInput}
                type="number"
                min={0}
                max={1440}
                placeholder="Hold (min)"
                title="Optional: condition must stay true for this many minutes (checked at the background poll interval) before the alert fires. Leave blank to fire instantly."
                value={c.sustain_minutes ?? ''}
                onChange={(e) =>
                  updateCondition(idx, {
                    sustain_minutes: e.target.value ? Number(e.target.value) : undefined,
                  })
                }
              />

              {conditions.length > 1 && (
                <button
                  className={styles.removeBtn}
                  onClick={() => removeCondition(idx)}
                  aria-label="Remove condition"
                >
                  &times;
                </button>
              )}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 4: Manually verify in the browser**

Run: `cd frontend && npm run dev`, open a chart, open the alert rule builder, add a Price condition, confirm the new "Hold (min)" input appears, save the rule, reopen it for editing, and confirm the value round-tripped.

- [ ] **Step 5: Commit**

```bash
git add frontend/types/alerts.ts frontend/components/organisms/AlertRuleBuilder/index.tsx
git commit -m "feat(alerts): add optional sustain-minutes hold filter to the alert rule builder"
```

---

### Task 9: Portfolio position alerts — sustain support

**Files:**
- Modify: `backend/app/models/portfolio.py:1-27`
- Create: `backend/migrations/versions/b4e91a2f7c33_add_alert_state_to_portfolio_positions.py`
- Modify: `backend/app/services/alert_generator.py:39-127`
- Modify: `backend/app/services/portfolio_alert_monitor.py` (`_run_once`)
- Modify: `backend/app/routers/notification_settings.py` (add `positionSustainMinutes`)
- Test: Create `backend/tests/test_alert_generator_sustain.py`

- [ ] **Step 1: Add the `positionSustainMinutes` config field**

In `backend/app/routers/notification_settings.py`, extend `_DEFAULT_DELIVERY`, `AlertDeliveryConfig`, `get_alert_delivery`, and `save_alert_delivery` (already touched in Task 1) with one more field:

```python
_DEFAULT_DELIVERY = {
    'masterEnabled': True,
    'enabledTypes': _SUPPORTED_TYPES,
    'dedupWindowMinutes': 15,
    'reminderIntervalHours': 4,
    'retentionDays': 30,
    'checkIntervalSeconds': 60,
    # 0 = fire the instant a stop/target/premium condition is crossed (original
    # behavior). >0 = the condition must stay true for this many minutes,
    # checked at checkIntervalSeconds granularity, before alerting.
    'positionSustainMinutes': 0,
}


class AlertDeliveryConfig(BaseModel):
    masterEnabled: bool = True
    enabledTypes: list[str] = _SUPPORTED_TYPES
    dedupWindowMinutes: int = 15
    reminderIntervalHours: int = 4
    retentionDays: int = 30
    checkIntervalSeconds: int = 60
    positionSustainMinutes: int = 0
```

```python
@router.get('/alert-delivery')
async def get_alert_delivery() -> dict:
    cfg = _load_yaml()
    d = cfg.get('alert_delivery', _DEFAULT_DELIVERY)
    return {
        'masterEnabled': bool(d.get('masterEnabled', True)),
        'enabledTypes': d.get('enabledTypes', _SUPPORTED_TYPES),
        'dedupWindowMinutes': int(d.get('dedupWindowMinutes', 15)),
        'reminderIntervalHours': int(d.get('reminderIntervalHours', 4)),
        'retentionDays': int(d.get('retentionDays', 30)),
        'checkIntervalSeconds': int(d.get('checkIntervalSeconds', 60)),
        'positionSustainMinutes': int(d.get('positionSustainMinutes', 0)),
    }


@router.post('/alert-delivery')
async def save_alert_delivery(body: AlertDeliveryConfig) -> dict:
    cfg = _load_yaml()
    cfg['alert_delivery'] = {
        'masterEnabled': body.masterEnabled,
        'enabledTypes': body.enabledTypes,
        'dedupWindowMinutes': body.dedupWindowMinutes,
        'reminderIntervalHours': body.reminderIntervalHours,
        'retentionDays': body.retentionDays,
        'checkIntervalSeconds': max(15, body.checkIntervalSeconds),
        'positionSustainMinutes': max(0, body.positionSustainMinutes),
    }
    _save_yaml(cfg)
    return cfg['alert_delivery']
```

- [ ] **Step 2: Add the `alert_state` column + migration**

In `backend/app/models/portfolio.py`, add one line (the `JSON` import already exists on line 1):

```python
class PortfolioPositionModel(Base):
    __tablename__ = "portfolio_positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rec_id = Column(String, nullable=False, unique=True, index=True)
    symbol = Column(String, nullable=False)
    contract = Column(String, nullable=False, unique=True, index=True)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    entry_date = Column(String, nullable=False)
    stop = Column(Float, nullable=True)
    targets = Column(JSON, nullable=True, default=list)
    dte_total = Column(Integer, nullable=True)
    entry_stock_price = Column(Float, nullable=True)
    alert_state = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

Create `backend/migrations/versions/b4e91a2f7c33_add_alert_state_to_portfolio_positions.py`:

```python
"""add alert_state to portfolio_positions

Revision ID: b4e91a2f7c33
Revises: c1d2e3f4a5b6
Create Date: 2026-07-04 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e91a2f7c33'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'portfolio_positions',
        sa.Column('alert_state', sa.JSON(), nullable=True, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'alert_state')
```

Run: `cd backend && venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade c1d2e3f4a5b6 -> b4e91a2f7c33, add alert_state to portfolio_positions`

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_alert_generator_sustain.py`:

```python
# backend/tests/test_alert_generator_sustain.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.services.alert_generator import generate_alerts


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _position(**overrides) -> PortfolioPositionModel:
    base = dict(
        id=uuid.uuid4(), rec_id='rec-1', symbol='AAPL', contract='AAPL|150|2099-01-01|C',
        direction='Bullish', entry_price=5.0, qty=1, entry_date='2024-01-01',
        stop=140.0, targets=[{'stock_price': 200.0}], dte_total=30,
        entry_stock_price=145.0, alert_state={},
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


@pytest.mark.asyncio
async def test_stop_reached_not_fired_on_first_sustain_check():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position())
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
    assert not any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_stop_reached_fires_after_sustain_window_elapses():
    Session = await _make_session_factory()
    async with Session() as db:
        past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        db.add(_position(alert_state={'STOP_REACHED': past}))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_stop_reached_clock_resets_when_price_recovers():
    Session = await _make_session_factory()
    async with Session() as db:
        past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        pos = _position(alert_state={'STOP_REACHED': past})
        db.add(pos)
        await db.commit()
        # Price back above the stop this check — clock must clear.
        await generate_alerts(db, {'AAPL': 150.0}, sustain_minutes=5)
        await db.commit()
        from sqlalchemy import select
        refreshed = (await db.execute(select(PortfolioPositionModel))).scalar_one()
        assert 'STOP_REACHED' not in (refreshed.alert_state or {})


@pytest.mark.asyncio
async def test_zero_sustain_minutes_fires_instantly_as_before():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position())
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0})  # sustain_minutes defaults to 0
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_alert_generator_sustain.py -v`
Expected: FAIL — `generate_alerts()` doesn't accept `sustain_minutes` yet

- [ ] **Step 5: Add sustain tracking to `generate_alerts`**

Replace `generate_alerts` in `backend/app/services/alert_generator.py`:

```python
async def generate_alerts(
    db: AsyncSession,
    current_prices: dict[str, float],
    current_option_prices: Optional[dict[str, float]] = None,
    sustain_minutes: int = 0,
) -> list[AlertItem]:
    """Generate alerts for all open portfolio positions.

    sustain_minutes: if > 0, a stop/target/premium condition must stay true
    across checks spanning at least this many minutes before it alerts (state
    persisted per-position in PortfolioPositionModel.alert_state). 0 preserves
    the original instant-fire behavior.
    """
    result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    positions = result.scalars().all()

    alerts: list[AlertItem] = []
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    counter = 0

    for pos in positions:
        symbol = pos.symbol
        price = current_prices.get(symbol)
        opt_price = (current_option_prices or {}).get(pos.contract) if current_option_prices else None
        targets = pos.targets or []
        alert_state = dict(pos.alert_state or {})

        def _sustained(alert_type: str, met: bool) -> bool:
            if not sustain_minutes:
                return met
            if not met:
                alert_state.pop(alert_type, None)
                return False
            pending_since_str = alert_state.get(alert_type)
            if pending_since_str is None:
                alert_state[alert_type] = now_iso
                return False
            pending_since = datetime.fromisoformat(pending_since_str)
            elapsed_min = (now - pending_since).total_seconds() / 60.0
            return elapsed_min >= sustain_minutes

        # TP_HIT — direction-aware: bullish targets are above current price, bearish below
        is_bearish = pos.contract.split("|")[3] == "P" if len(pos.contract.split("|")) >= 4 else False
        if targets and price is not None:
            first_target = targets[0]
            target_stock_price = (
                first_target.get("stock_price") or first_target.get("stockPrice") or 0
            )
            hit_raw = (price <= target_stock_price) if is_bearish else (price >= target_stock_price)
            if _sustained("TP_HIT", hit_raw):
                counter += 1
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Target reached — {symbol} at ${price:.2f}",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TP_HIT",
                ))

        # STOP_REACHED — direction-aware: puts are invalidated when stock rises above stop
        stop_breached_raw = (
            (price >= pos.stop) if is_bearish
            else (price <= pos.stop)
        ) if (pos.stop is not None and price is not None) else False
        if pos.stop is not None and price is not None and _sustained("STOP_REACHED", stop_breached_raw):
            counter += 1
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} below ${pos.stop:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
            ))

        # PREMIUM_STOP
        premium_hit_raw = bool(
            opt_price is not None and pos.entry_price > 0
            and opt_price <= pos.entry_price * _premium_stop_pct()
        )
        if _sustained("PREMIUM_STOP", premium_hit_raw):
            counter += 1
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Premium stop — {symbol} option at ${opt_price:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="PREMIUM_STOP",
            ))

        # TIME_STOP — day-granularity already; sustain does not apply.
        expiry = parse_expiry_from_contract(pos.contract)
        if expiry is not None:
            days_to_expiry = (expiry - date.today()).days
            if 0 <= days_to_expiry <= 3:
                counter += 1
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Time stop — {symbol} {days_to_expiry} DTE",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TIME_STOP",
                ))

        pos.alert_state = alert_state

    return alerts
```

- [ ] **Step 6: Wire the config value + commit the mutated state in the caller**

In `backend/app/services/portfolio_alert_monitor.py`, inside `_run_once`, update the block that calls `generate_alerts` (originally around the `async with AsyncSessionLocal() as db:` block under "1. Portfolio position alerts"):

```python
    try:
        import httpx

        from app.data.market import fetch_contract_quote_async, fetch_quotes
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PortfolioPositionModel))
            positions = result.scalars().all()
            current_rec_ids = {p.rec_id for p in positions if p.rec_id}
            symbols = list({p.symbol for p in positions})
            if symbols:
                quotes = await asyncio.to_thread(fetch_quotes, symbols)
                current_prices = {sym: q['last'] for sym, q in quotes.items()}

                option_prices: dict[str, float] = {}
                contracts = [p.contract for p in positions if p.contract]
                if contracts:
                    async with httpx.AsyncClient(timeout=10) as client:
                        results = await asyncio.gather(
                            *[fetch_contract_quote_async(client, c) for c in contracts],
                            return_exceptions=True,
                        )
                    for contract, quote in zip(contracts, results):
                        if isinstance(quote, dict) and quote.get('price') is not None:
                            option_prices[contract] = quote['price']

                position_sustain_minutes = int(delivery.get('positionSustainMinutes', 0))
                alerts.extend(await generate_alerts(
                    db, current_prices, option_prices or None, position_sustain_minutes))
                await db.commit()
    except Exception:
        logger.error('Portfolio alert generation failed', exc_info=True)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_alert_generator_sustain.py tests/test_notification_settings.py tests/test_portfolio_alert_monitor.py -v`
Expected: PASS (all)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/portfolio.py backend/migrations/versions/b4e91a2f7c33_add_alert_state_to_portfolio_positions.py backend/app/services/alert_generator.py backend/app/services/portfolio_alert_monitor.py backend/app/routers/notification_settings.py backend/tests/test_alert_generator_sustain.py
git commit -m "feat(alerts): add sustain-minutes filter to portfolio position alerts (TP/stop/premium)"
```

---

### Task 10: Regime-flip monitor — sustain support

**Files:**
- Modify: `backend/config/risk_rules.yaml`
- Modify: `backend/app/services/regime_monitor.py:151-222`
- Test: `backend/tests/test_regime_monitor.py`

- [ ] **Step 1: Add the config default**

In `backend/config/risk_rules.yaml`, add one line under `auto_trade:`:

```yaml
auto_trade:
  max_arm_age_minutes: 30   # disarm without firing if order was armed longer than this
  max_daily_loss_pct: 0.02     # 2% of portfolio_value = $2,000 on $100k
  premium_stop_pct: 0.60       # matches reward_risk.premium_stop_pct default
  regime_monitor_interval_minutes: 15
  regime_flip_sustain_minutes: 0   # 0 = warn on the first REJECT+open-positions tick (original behavior)
  gap_threshold_pct: 0.05       # reserved: future percentage buffer around stop; currently alerts on any stop breach
```

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_regime_monitor.py`:

```python
@pytest.mark.asyncio
async def test_reject_alert_delayed_until_sustain_window_elapses(mocker):
    """With regime_flip_sustain_minutes=5, the first REJECT+open-positions tick
    must NOT broadcast — only once 5 minutes have elapsed across ticks."""
    import app.services.regime_monitor as rm
    rm._reject_since = None  # reset module state between tests
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="REJECT"))
    mocker.patch("app.services.regime_monitor._has_open_positions", new=AsyncMock(return_value=True))
    mocker.patch("app.services.regime_monitor._load_regime_flip_sustain_minutes", new=AsyncMock(return_value=5))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_not_called()
    assert rm._reject_since is not None


@pytest.mark.asyncio
async def test_reject_alert_fires_once_sustain_window_elapses(mocker):
    import app.services.regime_monitor as rm
    from datetime import datetime, timedelta, timezone
    rm._reject_since = datetime.now(timezone.utc) - timedelta(minutes=6)
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="REJECT"))
    mocker.patch("app.services.regime_monitor._has_open_positions", new=AsyncMock(return_value=True))
    mocker.patch("app.services.regime_monitor._load_regime_flip_sustain_minutes", new=AsyncMock(return_value=5))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_called_once()


@pytest.mark.asyncio
async def test_reject_clock_resets_when_regime_recovers(mocker):
    import app.services.regime_monitor as rm
    from datetime import datetime, timezone
    rm._reject_since = datetime.now(timezone.utc)
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="PASS"))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_not_called()
    assert rm._reject_since is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_regime_monitor.py -k sustain -v`
Expected: FAIL — `module 'app.services.regime_monitor' has no attribute '_reject_since'`

- [ ] **Step 4: Implement the sustain clock**

In `backend/app/services/regime_monitor.py`, add module state near `_last_conviction` (top of file, after the existing cache-variable block):

```python
# ── Module-level REJECT-flip sustain clock ─────────────────────────────────
_reject_since: "datetime | None" = None


def _load_risk_config() -> dict:
    with open(_RISK_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


async def _load_regime_flip_sustain_minutes() -> int:
    loop = asyncio.get_running_loop()

    def _read() -> int:
        cfg = _load_risk_config()
        return int(cfg.get("auto_trade", {}).get("regime_flip_sustain_minutes", 0))

    return await loop.run_in_executor(None, _read)
```

Then replace the `_tick` function:

```python
async def _tick() -> None:
    """One monitoring cycle."""
    global _reject_since
    try:
        await _update_conviction_cache()
        await _check_overnight_gaps()

        regime = await _get_overall_regime()
        if regime != "REJECT":
            _reject_since = None
            return

        has_pos = await _has_open_positions()
        if not has_pos:
            _reject_since = None
            return

        now = datetime.now(timezone.utc)
        if _reject_since is None:
            _reject_since = now

        sustain_minutes = await _load_regime_flip_sustain_minutes()
        if sustain_minutes:
            elapsed_min = (now - _reject_since).total_seconds() / 60.0
            if elapsed_min < sustain_minutes:
                return  # REJECT hasn't held long enough yet

        payload = {
            "type": "REGIME_FLIP_WARNING",
            "regime": "REJECT",
            "message": (
                "Market regime has turned REJECT while positions are open. "
                "Consider closing positions before next session."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning("regime_monitor: REJECT regime with open positions — alert broadcast")

    except Exception as exc:
        logger.error("regime_monitor _tick failed: %s", exc)
```

Also update the module-level `_RISK_CONFIG_PATH`-reading helper already inside `run_regime_monitor` (the inline `_read_interval` function) to reuse the new `_load_risk_config()` helper instead of duplicating the `open(...)`/`yaml.safe_load(...)` logic:

```python
async def run_regime_monitor() -> None:
    """Asyncio coroutine: runs forever, ticking then sleeping."""
    while True:
        await _tick()
        try:
            loop = asyncio.get_running_loop()

            def _read_interval() -> int:
                cfg = _load_risk_config()
                return int(cfg.get("auto_trade", {}).get("regime_monitor_interval_minutes", 15))

            interval = await loop.run_in_executor(None, _read_interval)
        except Exception:
            interval = 15
        await asyncio.sleep(interval * 60)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_regime_monitor.py -v`
Expected: PASS (all, including the 3 new sustain tests and all pre-existing tests)

- [ ] **Step 6: Commit**

```bash
git add backend/config/risk_rules.yaml backend/app/services/regime_monitor.py backend/tests/test_regime_monitor.py
git commit -m "feat(alerts): add sustain-minutes filter before the REJECT-regime-flip warning fires"
```

---

### Task 11: Strategy watch (regular per-symbol) entry/exit sustain

**Files:**
- Modify: `backend/app/services/strategy_watch_store.py:35`
- Modify: `backend/app/services/strategy_watch_evaluator.py:58-158,245-254`
- Modify: `backend/app/services/strategy_watch_scheduler.py:41-110`
- Modify: `backend/app/routers/strategy_watch.py:33-37,83-85`
- Modify: `frontend/lib/api.ts:118-123`
- Modify: `frontend/app/(frame)/strategy-watch/page.tsx:94-100`
- Test: `backend/tests/test_strategy_watch_evaluator.py`, `backend/tests/test_strategy_watch_scheduler.py`

Design note: unlike the standard rule builder, regular strategy watches have no per-watch condition editor — `sustain_minutes` is added as **one global schedule-level setting** (alongside the existing `poll_hours`/`mode`), applying to every enabled watch. `evaluate_all()`/`evaluate_and_notify()` take it as an explicit parameter defaulting to `0`, so every existing test that calls them with no arguments keeps passing unchanged — the scheduler is the only caller that reads the real configured value.

- [ ] **Step 1: Add the schedule default**

In `backend/app/services/strategy_watch_store.py`, update `_DEFAULT_SCHEDULE`:

```python
_DEFAULT_SCHEDULE = {"enabled": False, "mode": "eod", "eod_time": "16:15", "poll_hours": 4, "sustain_minutes": 0}
```

(`set_schedule`'s existing `{k: cfg[k] for k in _DEFAULT_SCHEDULE if k in cfg}` filter picks up the new key automatically — no further change needed there.)

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_strategy_watch_evaluator.py`:

```python
@pytest.mark.asyncio
async def test_sustain_delays_entry_until_window_elapses():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    store.update_state.assert_called_once()
    assert "pending_entry_since" in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_sustain_fires_entry_once_window_elapsed():
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since=past)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert len(events) == 1
    assert events[0].event_type == "entry"


@pytest.mark.asyncio
async def test_sustain_clock_resets_when_signal_disappears():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since=now_iso)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    assert "pending_entry_since" not in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_zero_sustain_minutes_fires_instantly_as_before():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()  # sustain_minutes defaults to 0
    assert len(events) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_strategy_watch_evaluator.py -k sustain -v`
Expected: FAIL — `evaluate_all() got an unexpected keyword argument 'sustain_minutes'`

- [ ] **Step 4: Add the `sustain_minutes` parameter and pending-clock logic**

In `backend/app/services/strategy_watch_evaluator.py`, change the `evaluate_all` signature and the `idle`-phase branch:

```python
async def evaluate_all(sustain_minutes: int = 0) -> list[WatchEvent]:
    """Evaluate every enabled watch; return one WatchEvent per fired transition.

    sustain_minutes: if > 0, a newly-appeared entry signal must remain present
    for at least this many minutes (checked across scheduler ticks, tracked in
    each watch's last_state.pending_entry_since) before the entry event fires.
    0 preserves the original instant-fire behavior.
    """
    events: list[WatchEvent] = []
    end = date.today()
    start = end - timedelta(days=_HISTORY_DAYS)

    for w in strategy_watch_store.list_watches():
        if not w.get("enabled"):
            continue
        symbol = w["symbol"]
        key = w["strategy_key"]
        fn = _SIGNAL_FNS.get(key)
        if fn is None:
            continue
        try:
            bars = await get_bars(symbol, start, end)
        except Exception as exc:
            logger.warning("strategy-watch: get_bars failed for %s — %s", symbol, exc)
            continue
        if not bars:
            continue

        close = float(bars[-1]["close"])
        wdir = w.get("direction", "Bullish")
        try:
            adopted = get_active(key, wdir)
            params_override = w.get("params_override") or {}
            adopted.update(params_override)  # params_override wins
            signal = fn(bars, direction=wdir, **adopted)
        except Exception as exc:
            logger.warning("strategy-watch: %s signal failed for %s — %s", key, symbol, exc)
            continue

        state = dict(w["last_state"])
        phase = state.get("phase", "idle")
        event: WatchEvent | None = None

        if phase == "idle":
            if signal is not None:
                if sustain_minutes:
                    pending_since_str = state.get("pending_entry_since")
                    if pending_since_str is None:
                        strategy_watch_store.update_state(
                            w["id"], {**state, "pending_entry_since": _now_iso()},
                        )
                        continue
                    pending_since = datetime.fromisoformat(pending_since_str)
                    elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                    if elapsed_min < sustain_minutes:
                        continue
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="entry", direction=signal.direction,
                    entry=signal.entry_price, stop=signal.stop_price,
                    target=signal.target_price, rr_ratio=round(signal.rr_ratio, 2),
                    close=close,
                    reason=(f"{symbol}: {key} "
                            f"{'short' if signal.direction == 'Bearish' else 'long'} setup — "
                            f"entry {signal.entry_price}, "
                            f"stop {signal.stop_price}, target {signal.target_price} "
                            f"(R:R {round(signal.rr_ratio, 2)})"),
                )
                state = {"phase": "armed", "direction": signal.direction,
                         "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                         "target_price": signal.target_price, "last_event": "entry",
                         "last_event_at": _now_iso()}
            elif state.get("pending_entry_since"):
                # Signal disappeared before the sustain window elapsed — reset the clock.
                strategy_watch_store.update_state(
                    w["id"], {k2: v for k2, v in state.items() if k2 != "pending_entry_since"},
                )
        elif phase == "armed":
            sdir = state.get("direction", "Bullish")
            stop_price = state.get("stop_price")
            target_price = state.get("target_price")
            stop_hit = (
                (close <= stop_price) if sdir == "Bullish" else (close >= stop_price)
            ) if stop_price is not None else False
            target_hit = (
                (close >= target_price) if sdir == "Bullish" else (close <= target_price)
            ) if target_price is not None else False
            if stop_hit:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="exit_stop", direction=state.get("direction"),
                    entry=state.get("entry_price"), stop=stop_price,
                    target=target_price, rr_ratio=None, close=close,
                    reason=f"{symbol}: {key} stop hit at {close} (stop {stop_price})",
                )
                state = {"phase": "idle", "last_event": "exit_stop", "last_event_at": _now_iso()}
            elif target_hit:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="exit_target", direction=state.get("direction"),
                    entry=state.get("entry_price"), stop=stop_price,
                    target=target_price, rr_ratio=None, close=close,
                    reason=f"{symbol}: {key} target hit at {close} (target {target_price})",
                )
                state = {"phase": "idle", "last_event": "exit_target", "last_event_at": _now_iso()}
            elif signal is not None and signal.direction != state.get("direction"):
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="reversal", direction=signal.direction,
                    entry=signal.entry_price, stop=signal.stop_price,
                    target=signal.target_price, rr_ratio=round(signal.rr_ratio, 2),
                    close=close,
                    reason=f"{symbol}: {key} reversal to {signal.direction} at {close}",
                )
                state = {"phase": "armed", "direction": signal.direction,
                         "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                         "target_price": signal.target_price, "last_event": "reversal",
                         "last_event_at": _now_iso()}

        if event is not None:
            strategy_watch_store.update_state(w["id"], state)
            events.append(event)
```

(The `# ── Composite watches ──` loop and everything below it stays exactly as-is for this task — composite sustain is handled separately in Task 12.)

- [ ] **Step 5: Thread the parameter through `evaluate_and_notify`**

```python
async def evaluate_and_notify(sustain_minutes: int = 0) -> list[WatchEvent]:
    """Evaluate all watches and dispatch a notification per fired event."""
    events = await evaluate_all(sustain_minutes)
    for ev in events:
        subject, plain, html = _format_event(ev)
        try:
            notify_enabled_channels(subject, plain, html)
        except Exception:
            logger.error("strategy-watch: notify failed for %s", ev.symbol, exc_info=True)
    return events
```

- [ ] **Step 6: Have the scheduler read the schedule's `sustain_minutes` and pass it through**

In `backend/app/services/strategy_watch_scheduler.py`, update both call sites inside `_maybe_run` (the `evaluate_and_notify()` call in the `eod` branch and the one in the poll branch):

```python
    async def _maybe_run(self, now: datetime | None = None) -> bool:
        """Decide and possibly run one evaluation. Returns True if it ran."""
        now = now or datetime.now()
        cfg = self._load_schedule()
        if not cfg.get("enabled"):
            return False
        sustain_minutes = int(cfg.get("sustain_minutes", 0))

        mode = cfg.get("mode", "eod")
        if mode == "eod":
            hh, mm = (int(x) for x in str(cfg.get("eod_time", "16:15")).split(":"))
            if now.weekday() >= 5:
                return False
            if now.time() < dtime(hh, mm):
                return False
            if self._last_eod_run_date == now.date():
                return False
            await evaluate_and_notify(sustain_minutes)
            self._last_run_at = now
            self._last_eod_run_date = now.date()
            return True

        # poll mode
        if not _market_open(now):
            return False
        interval_h = float(cfg.get("poll_hours", 4))
        if self._last_run_at is not None:
            elapsed_h = (now - self._last_run_at).total_seconds() / 3600.0
            if elapsed_h < interval_h:
                return False
        await evaluate_and_notify(sustain_minutes)
        self._last_run_at = now
        return True
```

(`run_now()` stays unchanged — it already documents itself as "bypasses schedule gates," so a manual trigger fires instantly, matching its existing contract.)

- [ ] **Step 7: Expose `sustain_minutes` in the schedule API + type**

In `backend/app/routers/strategy_watch.py`:

```python
class ScheduleIn(BaseModel):
    enabled: bool
    mode: str = Field(pattern="^(eod|poll)$")
    eod_time: str = "16:15"
    poll_hours: int = Field(default=4, ge=1, le=24)
    sustain_minutes: int = Field(default=0, ge=0, le=1440)
```

- [ ] **Step 8: Frontend — type + UI**

In `frontend/lib/api.ts`:

```typescript
export interface StrategyWatchSchedule {
  enabled: boolean;
  mode: 'eod' | 'poll';
  eod_time: string;
  poll_hours: number;
  sustain_minutes: number;
}
```

In `frontend/app/(frame)/strategy-watch/page.tsx`, add a row inside the `{schedule && (...)}` block, right after the `poll_hours`/`eod_time` input:

```tsx
            <label>
              Sustain (min)
              <input className={styles.input} type="number" min={0} max={1440}
                     value={schedule.sustain_minutes}
                     onChange={(e) => updateSched({ sustain_minutes: Number(e.target.value) })}
                     title="Optional: an entry/exit signal must persist across this many minutes of checks before it fires." />
            </label>
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_strategy_watch_evaluator.py tests/test_strategy_watch_scheduler.py tests/test_strategy_watch_bearish.py tests/test_strategy_watch_router.py tests/test_strategy_watch_store.py -v`
Expected: PASS (all — the pre-existing tests are unaffected since they call `evaluate_all()`/`evaluate_and_notify()` with no arguments, defaulting `sustain_minutes` to `0`)

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/strategy_watch_store.py backend/app/services/strategy_watch_evaluator.py backend/app/services/strategy_watch_scheduler.py backend/app/routers/strategy_watch.py frontend/lib/api.ts "frontend/app/(frame)/strategy-watch/page.tsx" backend/tests/test_strategy_watch_evaluator.py
git commit -m "feat(alerts): add global sustain-minutes filter to strategy-watch entry/exit signals"
```

---

### Task 12: Composite alerts — sustain support (both composite paths)

There are two independent composite-alert mechanisms in this codebase, both driven by the same `trigger_def` dict shape from `composite_trigger_evaluator.py`:

- **A.** `AlertRuleModel` rows with `rule_json.__type == "composite"`, evaluated inside `evaluate_and_notify_for_symbol()` (already covered by the Task 6 background scheduler once that ships).
- **B.** `strategy_watch_store` composite watches (created by `CompositeAlertDialog` → `POST /api/composite-watches`), evaluated inside `strategy_watch_evaluator.py`'s `evaluate_all()` composite-watches loop.

Both get a `sustain_minutes` key read directly from their own `trigger_def` dict (no new global setting) — this fits the existing pattern where `trigger_def` already carries per-rule thresholds like `conviction_min` and `min_confirmations`.

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:493-554` (path A)
- Modify: `backend/app/services/strategy_watch_evaluator.py:159-209` (path B)
- Modify: `frontend/components/organisms/CompositeAlertDialog/index.tsx:34-133,169-177`
- Test: Create `backend/tests/test_composite_sustain.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_composite_sustain.py`:

```python
# backend/tests/test_composite_sustain.py
"""sustain_minutes on composite trigger_defs — both the AlertRuleModel/WS path
(chart_alerts.evaluate_and_notify_for_symbol) and the strategy-watch path
(strategy_watch_evaluator.evaluate_all's composite-watches loop)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _composite_rule_row(condition_state: str = '{}') -> AlertRuleModel:
    trigger_def = {
        "primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0,
        "sustain_minutes": 5, "__type": "composite",
    }
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Composite', symbol='AAPL', interval='15min',
        enabled=True, rule_json=json.dumps(trigger_def), cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state=condition_state,
    )


_FLAT_CANDLES = [
    {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for i in range(120)
]


# The WS composite path imports `evaluate_from_context_detailed` and
# `format_composite_reason` from composite_trigger_evaluator INSIDE
# evaluate_and_notify_for_symbol at call time, so patch them on that module.
# evaluate_from_context_detailed returns a (fired, detail) tuple.
_DETAIL = {'structure_matched': [], 'structure_total': 0, 'strategy_matched': [], 'strategy_total': 0}


@pytest.mark.asyncio
async def test_ws_composite_path_delays_fire_until_sustained(monkeypatch):
    from app.routers import chart_alerts
    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(
        'app.services.composite_trigger_evaluator.evaluate_from_context_detailed',
        lambda *a, **kw: (True, _DETAIL),
    )

    async with Session() as db:
        db.add(_composite_rule_row())
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []

    async with Session() as db:
        from sqlalchemy import select
        row = (await db.execute(select(AlertRuleModel).where(AlertRuleModel.id == 'rule-1'))).scalar_one()
        assert 'composite' in json.loads(row.condition_state)


@pytest.mark.asyncio
async def test_ws_composite_path_fires_once_sustained(monkeypatch):
    from app.routers import chart_alerts
    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(
        'app.services.composite_trigger_evaluator.evaluate_from_context_detailed',
        lambda *a, **kw: (True, _DETAIL),
    )

    past = (datetime.now() - timedelta(minutes=6)).isoformat()
    async with Session() as db:
        db.add(_composite_rule_row(condition_state=json.dumps({'composite': past})))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_strategy_watch_composite_delays_fire_until_sustained():
    from app.services.strategy_watch_evaluator import evaluate_all

    def _bars(close: float, n: int = 260) -> list[dict]:
        return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                 "open": close, "high": close + 1, "low": close - 1,
                 "close": close, "volume": 1_000_000} for i in range(n)]

    watch = {
        "id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
        "strategy_key": "composite", "direction": "Bullish", "enabled": True,
        "trigger_def": {"primary": {"model": "any"}, "sustain_minutes": 5},
        "last_state": {},
    }
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=True):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_called_once()
    assert "pending_entry_since" in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_strategy_watch_composite_fires_once_sustained():
    from app.services.strategy_watch_evaluator import evaluate_all

    def _bars(close: float, n: int = 260) -> list[dict]:
        return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                 "open": close, "high": close + 1, "low": close - 1,
                 "close": close, "volume": 1_000_000} for i in range(n)]

    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    watch = {
        "id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
        "strategy_key": "composite", "direction": "Bullish", "enabled": True,
        "trigger_def": {"primary": {"model": "any"}, "sustain_minutes": 5},
        "last_state": {"pending_entry_since": past},
    }
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=True), \
         patch("app.services.composite_trigger_evaluator.describe_match",
               return_value={"structure_matched": [], "strategy_matched": []}):
        events = await evaluate_all()
    assert len(events) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_composite_sustain.py -v`
Expected: FAIL — both composite paths currently fire instantly regardless of `sustain_minutes`

- [ ] **Step 3: Add the sustain gate to the AlertRuleModel/WS composite path**

In `backend/app/routers/chart_alerts.py`, inside `evaluate_and_notify_for_symbol`'s composite-rows loop, replace (this is the current post-refactor shape — single `evaluate_from_context_detailed()` returning `(fired, detail)`, with the per-rule daily-bar selection already present):

```python
            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                _direction = _td.get("direction") or "Bullish"
                _rule_needs_daily = bool(_rj.get("strategy_confirmations")) or _rj.get("primary", {}).get("model") == "HMM_daily"
                _rule_daily = _bars_daily if _rule_needs_daily else []
                try:
                    _fired, _detail = evaluate_from_context_detailed(
                        _td, _omm, signals, indicators,
                        bars_daily=_rule_daily, bars_intraday=_bars_intraday,
                        direction=_direction, symbol=symbol,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue
                if not _fired:
                    continue
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
```

with (the sustain gate is inserted between the `try/except` and the original `if not _fired: continue`):

```python
            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                _direction = _td.get("direction") or "Bullish"
                _rule_needs_daily = bool(_rj.get("strategy_confirmations")) or _rj.get("primary", {}).get("model") == "HMM_daily"
                _rule_daily = _bars_daily if _rule_needs_daily else []
                try:
                    _fired, _detail = evaluate_from_context_detailed(
                        _td, _omm, signals, indicators,
                        bars_daily=_rule_daily, bars_intraday=_bars_intraday,
                        direction=_direction, symbol=symbol,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue

                _sustain_min = _td.get("sustain_minutes")
                _composite_state = json.loads(_row.condition_state or '{}')
                if _sustain_min:
                    if _fired:
                        _pending_since_str = _composite_state.get("composite")
                        if _pending_since_str is None:
                            _composite_state["composite"] = datetime.now().isoformat()
                            _row.condition_state = json.dumps(_composite_state)
                            continue
                        _pending_since = datetime.fromisoformat(_pending_since_str)
                        _elapsed_min = (datetime.now() - _pending_since).total_seconds() / 60.0
                        if _elapsed_min < _sustain_min:
                            continue
                    elif "composite" in _composite_state:
                        _composite_state.pop("composite", None)
                        _row.condition_state = json.dumps(_composite_state)

                if not _fired:
                    continue
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
```

(Everything below `_reason = format_composite_reason(...)` — history persistence, dispatch, `triggered.append(_entry)` — stays exactly as-is. This relies on the `condition_state` column added in Task 4.)

- [ ] **Step 4: Add the sustain gate to the strategy-watch composite path**

In `backend/app/services/strategy_watch_evaluator.py`, inside the `# ── Composite watches ──` loop, replace:

```python
        try:
            from app.services.composite_trigger_evaluator import evaluate_scheduled, describe_match, format_composite_reason
            fired = evaluate_scheduled(symbol, trigger_def, bars, bars_intraday)
        except Exception as exc:
            logger.warning("composite-watch: evaluate_scheduled failed for %s — %s", symbol, exc)
            continue
        if not fired:
            continue
```

with:

```python
        try:
            from app.services.composite_trigger_evaluator import evaluate_scheduled, describe_match, format_composite_reason
            fired = evaluate_scheduled(symbol, trigger_def, bars, bars_intraday)
        except Exception as exc:
            logger.warning("composite-watch: evaluate_scheduled failed for %s — %s", symbol, exc)
            continue

        sustain_min = trigger_def.get("sustain_minutes")
        watch_state = dict(w.get("last_state") or {})
        if sustain_min:
            if fired:
                pending_since_str = watch_state.get("pending_entry_since")
                if pending_since_str is None:
                    strategy_watch_store.update_state(
                        w["id"], {**watch_state, "pending_entry_since": _now_iso()},
                    )
                    continue
                pending_since = datetime.fromisoformat(pending_since_str)
                elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                if elapsed_min < sustain_min:
                    continue
            elif watch_state.get("pending_entry_since"):
                strategy_watch_store.update_state(
                    w["id"], {k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                )

        if not fired:
            continue
```

- [ ] **Step 5: Add the UI field to `CompositeAlertDialog`**

In `frontend/components/organisms/CompositeAlertDialog/index.tsx`, add state near the other `useState` declarations (after `const [interval, setIntervalVal] = useState('1D');`):

```typescript
  const [sustainMinutes, setSustainMinutes] = useState(0);
```

Include it in the payload inside `handleSave`:

```typescript
    const triggerDef: Record<string, unknown> = {
      primary: {
        model,
        to_state: toState === 'any' ? null : toState,
        conviction_min: convictionMin,
        p_stay_min: pStayMin,
        p_transition_min: 0.3,
      },
      confirmations,
      min_confirmations: Math.min(minConf, confirmations.length),
      strategy_confirmations: strategyConfirmations,
      min_strategy_confirmations: strategyConfirmations.length > 0 ? Math.min(minMrConf, strategyConfirmations.length) : 0,
      horizon: 'swing',
      sustain_minutes: sustainMinutes,
    };
```

Add the input row right after the `{model === 'HMM_intraday' && (...)}` interval block:

```tsx
            <div className={styles.row}>
              <Text size={16} tone="secondary">Sustain (min)</Text>
              <input
                className={styles.numInput}
                type="number"
                min={0}
                max={1440}
                value={sustainMinutes}
                onChange={(e) => setSustainMinutes(Number(e.target.value))}
                title="Optional: the composite condition must stay true for this many minutes before it fires."
              />
            </div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_composite_sustain.py tests/test_chart_alerts_composite_ws.py tests/test_strategy_watch_evaluator.py -v`
Expected: PASS (all)

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 7: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -v`
Expected: PASS (all, no regressions across every task in this plan)

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/app/services/strategy_watch_evaluator.py frontend/components/organisms/CompositeAlertDialog/index.tsx backend/tests/test_composite_sustain.py
git commit -m "feat(alerts): add sustain-minutes filter to both composite-alert paths"
```

---

## Notes / explicit scope boundaries

- The known duplicate-evaluation edge case (open chart + background scheduler both catching the same candle-close) is accepted as a low-cost trade-off — see the docstring on `run_chart_alert_scheduler`. Fixing it would require cross-referencing the live Tradier stream's subscriber list, which is out of scope here.
- `checkIntervalSeconds` governs the **portfolio monitor** and the **new chart-alert scheduler**. `regime_monitor.py` (`auto_trade.regime_monitor_interval_minutes` in `risk_rules.yaml`) and `strategy_watch_scheduler.py` (`poll_hours` in `strategy_watches.yaml`) keep their own separate, pre-existing knobs — unifying all four into one setting was explicitly out of scope per the research findings (each subsystem already has its own independent interval), and this decision was reconfirmed when extending sustain to those systems (Tasks 10–12): each system's *sustain* knob is also kept separate from the others, living alongside that system's own existing config (risk_rules.yaml for the regime monitor, the strategy-watch schedule for regular watches, each composite rule's own `trigger_def` for composite alerts, alert_delivery for portfolio positions).
- Sustain is now implemented in six places total, each independently configurable and each defaulting to `0`/instant (matching prior behavior exactly until the user opts in):
  1. Standard rule-builder conditions (Task 3) — per-condition, stored in `AlertRuleModel.condition_state`.
  2. Portfolio position alerts (Task 9) — one global `positionSustainMinutes`, stored per-position in `PortfolioPositionModel.alert_state`.
  3. Regime-flip warning (Task 10) — one global `regime_flip_sustain_minutes` in `risk_rules.yaml`, tracked in an in-process module variable (resets on backend restart — acceptable since a restart also clears the REJECT-streak history it would be measuring).
  4. Regular strategy watches (Task 11) — one global `sustain_minutes` in the strategy-watch schedule, tracked per-watch in `last_state.pending_entry_since`.
  5 & 6. Both composite-alert paths (Task 12) — per-rule `sustain_minutes` inside each rule's own `trigger_def`, tracked in `AlertRuleModel.condition_state` (path A) or `last_state.pending_entry_since` (path B).
