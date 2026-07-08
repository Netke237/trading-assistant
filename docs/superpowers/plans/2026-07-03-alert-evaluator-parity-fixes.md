# Alert Evaluator Parity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two pre-existing alert-evaluation bugs flagged (but not fixed) in the 2026-07-02 alerts/scanner/dashboard/IBKR session: (1) the WebSocket composite-alert path never gates on mean-reversion `strategy_confirmations`, unlike the scheduled watch path; (2) the generic alert panel's Regime condition Model dropdown (OMM/HMM) is silently ignored by the backend, and — more broadly — regime conditions never receive real regime data at all in production today (dead code).

**Architecture:** Both bugs live in the composite/standard alert evaluation layer (`backend/app/services/composite_trigger_evaluator.py`, `backend/app/services/alert_evaluator.py`) and their sole caller, `backend/app/routers/chart_alerts.py`. Bug 1 is fixed by threading `bars_daily`/`bars_intraday` into `evaluate_from_context()` (mirroring `evaluate_scheduled()`'s existing gate) and fetching daily bars lazily in the WS caller only when a composite rule actually needs them. Bug 2 is fixed by making `_evaluate_regime_condition()` model-aware (comparing against a `{"OMM": {...}, "HMM": {...}}` snapshot dict built from candles already in scope) and wiring that snapshot — plus a missing `RegimeCondition` deserialization branch — through both call sites in `chart_alerts.py`.

**Tech Stack:** FastAPI, SQLAlchemy v2 (async, aiosqlite for tests), pytest + pytest-asyncio.

**Line-number caution:** every task below cites line numbers against the *current, unmodified* state of each file. Task 2 edits `chart_alerts.py` before Task 4 edits it again, so Task 4's cited line numbers will have drifted by the time you reach it (new imports and a new bars-fetch block shift everything below them). Locate code by the shown "before" snippet / function name, not by trusting a stale line number once earlier tasks in the same file have already landed.

**Known adjacent inconsistency, not addressed by this plan:** `composite_trigger_evaluator.py`'s composite-trigger `primary.model` field accepts `"OMM" | "HMM_intraday" | "HMM_daily" | "any"`, while `alert_evaluator.py`'s `RegimeCondition.model` (this plan's Bug 2) accepts `"OMM" | "HMM" | "any"` — two different "regime model" vocabularies in the same codebase area, not the same enum. Do not assume they are interchangeable when touching either one in the future. Neither vocabulary's "daily" HMM variant actually reaches `backend/app/services/regime_hmm_daily.py::compute_directional_hmm` (the codebase's third regime model, labeling `Bull | Bear | Sideways` and already wired into `GET /regime/series?model=HMM` for the chart overlay) — `evaluate_scheduled`'s `HMM_daily` branch falls back to `regime_hmm.py::compute_intraday_hmm` on daily bars instead (see its own code comment), and this plan's `build_regime_snapshot()` (Task 3) doesn't consult `regime_hmm_daily.py` either. See Task 5 for why this matters for the frontend's HMM state dropdown.

---

## File Structure

- Modify: `backend/app/services/composite_trigger_evaluator.py` — add optional `bars_daily`/`bars_intraday` params to `evaluate_from_context()`, apply the same strategy-confirmations gate `evaluate_scheduled()` already has.
- Modify: `backend/app/routers/chart_alerts.py` — (Bug 1) lazily fetch daily bars and pass them into the WS composite-rule evaluation; (Bug 2) add the missing `RegimeCondition` deserialization branch, build a model-keyed regime snapshot, and pass it into both `evaluate_rules()` call sites (`test_rule` and `evaluate_and_notify_for_symbol`).
- Modify: `backend/app/services/alert_evaluator.py` — make `_evaluate_regime_condition()` branch on `condition.model`; rename the `regime` parameter to `regime_by_model` through `_evaluate_condition()`/`evaluate_rules()`; add a new public `build_regime_snapshot()` helper.
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx` — trim `REGIME_STATES_HMM` to states the backend HMM model can actually produce.
- Test: `backend/tests/test_composite_trigger.py` — new tests for the strategy-confirmations gate on `evaluate_from_context()`.
- Test: `backend/tests/test_chart_alerts_composite_ws.py` — new file; end-to-end tests of `evaluate_and_notify_for_symbol()`'s composite path proving the WS/scheduled parity gap is closed.
- Test: `backend/tests/test_alert_evaluator.py` — new `TestRegimeCondition` and `TestBuildRegimeSnapshot` classes.
- Test: `backend/tests/test_alert_router.py` — new test proving a saved regime condition survives deserialization and fires via the `/test` dry-run endpoint.

---

## Bug 1: WebSocket composite path skips `strategy_confirmations` gating

### Task 1: Add the strategy-confirmations gate to `evaluate_from_context()`

**Files:**
- Modify: `backend/app/services/composite_trigger_evaluator.py:158-199`
- Test: `backend/tests/test_composite_trigger.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_composite_trigger.py` (after `test_evaluate_from_context_any_model_skips_primary`, before `test_evaluate_scheduled_returns_bool`):

```python
def test_evaluate_from_context_strategy_confirmations_missing_bars_fails_closed():
    """strategy_confirmations configured but no bars passed → treated as not met."""
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
    }
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=[], bars_intraday=[]) is False
    # Also cover the case where the caller omits the new kwargs entirely (defaults) —
    # a plausible production call shape, distinct from explicitly passing empty lists.
    assert evaluate_from_context(trigger, None, [], {}) is False


def test_evaluate_from_context_strategy_confirmations_met_with_bars(monkeypatch):
    """strategy_confirmations configured, bars_daily supplied, strategy fn confirms → True."""
    from unittest.mock import MagicMock
    import app.services.strategy_engine as strategy_engine
    monkeypatch.setattr(
        strategy_engine, "mean_reversion_rsi_signal",
        lambda bars, direction="Bullish": MagicMock(),
    )
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
        "direction": "Bullish",
    }
    bars_daily = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
        for _ in range(70)
    ]
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars_daily, bars_intraday=[]) is True


def test_evaluate_from_context_strategy_confirmations_not_met_with_bars(monkeypatch):
    """strategy_confirmations configured, bars_daily supplied, strategy fn does not confirm → False."""
    import app.services.strategy_engine as strategy_engine
    monkeypatch.setattr(
        strategy_engine, "mean_reversion_rsi_signal",
        lambda bars, direction="Bullish": None,
    )
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
        "direction": "Bullish",
    }
    bars_daily = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
        for _ in range(70)
    ]
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars_daily, bars_intraday=[]) is False


def test_evaluate_from_context_no_strategy_confirmations_configured_unaffected():
    """No strategy_confirmations key at all — behavior identical to before this change."""
    trigger = _make_trigger(to_state="Choppy", conviction_min=50, min_confirmations=0)
    assert evaluate_from_context(trigger, _make_omm("Choppy", 75), [], {}) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_composite_trigger.py -v`
Expected: the 3 new gate tests FAIL (`evaluate_from_context() got an unexpected keyword argument 'bars_daily'` or assertion mismatch); `test_evaluate_from_context_no_strategy_confirmations_configured_unaffected` PASSES already (no behavior change needed for it).

- [ ] **Step 3: Implement the gate**

In `backend/app/services/composite_trigger_evaluator.py`, replace the `evaluate_from_context` function (lines 158-199):

```python
def evaluate_from_context(
    trigger_def: dict,
    omm_result,              # OmmResult dataclass | None
    structure_signals: list[dict],
    indicator_values: dict,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
) -> bool:
    """Alert/WebSocket path. Receives pre-computed model outputs — no I/O for the
    primary/confirmations checks. bars_daily/bars_intraday are optional and, when
    supplied by the caller, let this path apply the same strategy_confirmations
    gate evaluate_scheduled() applies — keeping WS-fired and scheduled-fired
    composite alerts behaviorally consistent.

    trigger_def: CompositeTriggerDef serialized as dict (or the Pydantic model)
    omm_result: OmmResult dataclass from compute_omm() — attribute access (.state, .conviction_pct, .p_stay)
    structure_signals: list of market structure signal dicts from market_structure.py
    indicator_values: dict of indicator name → value for momentum confirmations
    bars_daily: OHLCV daily bars, needed only if trigger_def sets strategy_confirmations
    bars_intraday: OHLCV intraday bars, needed only if trigger_def sets strategy_confirmations
    """
    if isinstance(trigger_def, dict):
        td = trigger_def
    else:
        td = trigger_def.model_dump()

    primary = td.get("primary", {})
    model = primary.get("model", "OMM")

    # Check primary Markov condition
    if model == "OMM":
        if not _check_primary_omm(td, omm_result):
            return False
    elif model in ("HMM_intraday", "HMM_daily"):
        # For the alert path, hmm result is passed via omm_result slot (caller must adapt)
        # In practice, alert path uses OMM only — HMM is for watch path
        logger.warning("evaluate_from_context: HMM model requested but only OMM result provided; skipping")
        return False
    elif model == "any":
        # 'any' means regime model doesn't matter — skip primary check
        pass

    # Count confirmations
    min_conf = td.get("min_confirmations", 1)
    if min_conf > 0:
        count = _count_confirmations(td, structure_signals, indicator_values)
        if count < min_conf:
            return False

    # Strategy confirmations — same N-of-M gate as evaluate_scheduled, so a composite
    # rule with strategy_confirmations behaves identically whether it fires via the
    # WebSocket path or the scheduled watch path. If the gate is configured but no
    # bars were supplied, _check_strategy_signals naturally returns 0 matches
    # (below any min_strategy_conf >= 1), i.e. this fails closed rather than
    # silently skipping the gate as before.
    strategy_conf_list: list[str] = td.get("strategy_confirmations", [])
    min_strategy_conf: int = td.get("min_strategy_confirmations", 1)
    if strategy_conf_list:
        direction: str = td.get("direction") or "Bullish"
        strategy_fired = _check_strategy_signals(
            strategy_conf_list, bars_daily or [], bars_intraday or [], direction=direction,
        )
        if strategy_fired < min_strategy_conf:
            return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_composite_trigger.py -v`
Expected: all tests PASS (existing tests + 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/composite_trigger_evaluator.py backend/tests/test_composite_trigger.py
git commit -m "fix(alerts): gate evaluate_from_context on strategy_confirmations like evaluate_scheduled"
```

---

### Task 2: Wire bars into the WebSocket composite-rule path in `chart_alerts.py`

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:1-27` (imports), `:379-517` (`evaluate_and_notify_for_symbol`)
- Test: `backend/tests/test_chart_alerts_composite_ws.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chart_alerts_composite_ws.py`:

```python
"""Tests for the WebSocket composite-rule path in chart_alerts.evaluate_and_notify_for_symbol.

Closes the parity gap between the WS path (evaluate_from_context) and the scheduled
watch path (evaluate_scheduled): a composite rule with strategy_confirmations must
behave the same regardless of which path evaluates it.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

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


def _make_composite_rule_row(rule_id: str, symbol: str, interval: str, trigger_def: dict) -> AlertRuleModel:
    return AlertRuleModel(
        id=rule_id, user_id='default', name='Composite Rule', symbol=symbol, interval=interval,
        enabled=True, rule_json=json.dumps({**trigger_def, '__type': 'composite'}),
        cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
    )


_TRIGGER_DEF = {
    "primary": {"model": "any"},
    "confirmations": [],
    "min_confirmations": 0,
    "strategy_confirmations": ["mean_reversion_rsi"],
    "min_strategy_confirmations": 1,
    "direction": "Bullish",
}

_FLAT_BARS = [
    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for _ in range(120)
]

_FLAT_CANDLES = [
    {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for i in range(120)
]


@pytest.mark.asyncio
async def test_ws_composite_path_gates_on_strategy_confirmations(monkeypatch):
    """A composite rule with strategy_confirmations must not fire over WS unless the
    mean-reversion strategy actually fired. Explicitly monkeypatches the signal fn to
    return None (rather than relying on insufficient bars to fail closed) so this test
    actually distinguishes "strategy did not confirm" from "not enough data to tell" —
    mirroring Task 1's test_evaluate_from_context_strategy_confirmations_not_met_with_bars."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))
    monkeypatch.setattr(
        strategy_engine, 'mean_reversion_rsi_signal',
        lambda bars, direction='Bullish': None,
    )

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-1', 'AAPL', '15min', _TRIGGER_DEF))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []


@pytest.mark.asyncio
async def test_ws_composite_path_fires_when_strategy_confirms(monkeypatch):
    """Same rule, but the mean-reversion strategy is mocked to confirm — should fire,
    and the reason text should name the matched strategy (proving describe_match
    also received bars)."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))
    monkeypatch.setattr(
        strategy_engine, 'mean_reversion_rsi_signal',
        lambda bars, direction='Bullish': MagicMock(),
    )

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-2', 'AAPL', '15min', _TRIGGER_DEF))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    assert 'mean_reversion_rsi' in triggered[0]['reason']


@pytest.mark.asyncio
async def test_ws_composite_path_skips_bars_fetch_when_not_needed(monkeypatch):
    """A composite rule with no strategy_confirmations must not trigger a bars fetch at all."""
    from app.routers import chart_alerts

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    trigger_def = {"primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-3', 'AAPL', '15min', trigger_def))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_not_called()


@pytest.mark.asyncio
async def test_ws_composite_path_passes_rule_direction_to_describe_match(monkeypatch):
    """A Bearish composite rule's reason text must reflect strategy matches computed
    with direction='Bearish', not silently fall back to describe_match's Bullish
    default — this is what keeps the WS path's reason text consistent with the
    scheduled path's (which already passes direction=wdir)."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))

    seen_directions = []

    def _fake_signal(bars, direction='Bullish'):
        seen_directions.append(direction)
        return MagicMock()

    monkeypatch.setattr(strategy_engine, 'mean_reversion_rsi_signal', _fake_signal)

    bearish_trigger_def = {**_TRIGGER_DEF, "direction": "Bearish"}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-4', 'AAPL', '15min', bearish_trigger_def))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    # describe_match() re-runs the strategy scan to build the reason text — assert
    # every call it made to the signal fn used 'Bearish', never the 'Bullish' default.
    assert seen_directions and all(d == 'Bearish' for d in seen_directions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v`
Expected: FAIL — `AttributeError: <module 'app.routers.chart_alerts'> does not have the attribute 'get_bars'` (not imported yet), and the first test's assertion would fail too once import is fixed (gate not wired yet).

- [ ] **Step 3: Wire bars into the composite block**

In `backend/app/routers/chart_alerts.py`, update the datetime import (line 10) and add a `get_bars` import next to the other service imports (lines 18-26):

```python
from datetime import date, datetime, timedelta
```

```python
from app.database import get_db, AsyncSessionLocal
from app.models.alert import AlertRuleModel, AlertHistoryModel
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    ConditionGroup, evaluate_rules,
)
from app.services.historical_store import get_bars
from app.services.indicator_compute import compute_indicators_for_conditions
from app.services.notifications.dispatch import dispatch as _dispatch, load_notification_config as _load_notification_config
from app.services.notifications.alert_notifier import _format_dt, _TZ_LABEL
```

Then replace the composite-rule block AND the function's trailing two lines (lines 451-517 — the full remainder of `evaluate_and_notify_for_symbol`, ending in `await db.commit()` / `return triggered`; do not stop at `triggered.append(_entry)`, the function continues past the composite loop) with:

```python
        # ── Composite rule evaluation ─────────────────────────────────────────
        if composite_rows:
            from app.services.composite_trigger_evaluator import evaluate_from_context, describe_match, format_composite_reason
            from app.services.regime_omm import compute_omm
            _closes = [c["close"] for c in all_candles] if all_candles else []
            _omm = compute_omm(_closes) if len(_closes) >= 100 else None

            # Only fetch daily bars if some composite rule actually needs them —
            # most composite rules have no strategy_confirmations and should not
            # pay for an extra get_bars() round-trip on every candle close.
            _needs_daily_bars = any(_rj.get("strategy_confirmations") for _, _rj in composite_rows)
            _bars_daily: list[dict] = []
            if _needs_daily_bars:
                try:
                    _end = date.today()
                    _start = _end - timedelta(days=730)
                    _bars_daily = await get_bars(symbol, _start, _end)
                except Exception as _exc:
                    logger.warning("composite rule strategy-confirmation bars fetch failed for %s: %s", symbol, _exc)
                    _bars_daily = []

            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                _direction = _td.get("direction") or "Bullish"
                try:
                    _fired = evaluate_from_context(
                        _td, _omm, signals, indicators,
                        bars_daily=_bars_daily, bars_intraday=all_candles,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue
                if not _fired:
                    continue
                # describe_match is passed the same bars (and now the rule's own
                # direction, matching evaluate_scheduled's call in
                # strategy_watch_evaluator.py) so the reason text can name matched
                # mean-reversion strategies here too — previously this path had no
                # bars at all, so strategy names never appeared in WS-fired reasons.
                _detail = describe_match(
                    _td, structure_signals=signals, indicator_values=indicators,
                    bars_daily=_bars_daily, bars_intraday=all_candles, symbol=symbol,
                    direction=_direction,
                )
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
                _now = datetime.now().isoformat()
                _entry = {
                    "id": uuid.uuid4().hex,
                    "rule_id": _row.id,
                    "symbol": symbol,
                    "interval": interval,
                    "triggered_at": _now,
                    "candle": closed_candle,
                    "trigger_values": {
                        "composite": True,
                        "omm_state": _omm.state if _omm else None,
                        "structure_matched": _detail["structure_matched"],
                        "strategy_matched": _detail["strategy_matched"],
                    },
                    "reason": _reason,
                }
                _hist = AlertHistoryModel(
                    id=_entry["id"], rule_id=_entry["rule_id"], symbol=_entry["symbol"],
                    interval=_entry["interval"], triggered_at=_entry["triggered_at"],
                    candle_json=json.dumps(_entry["candle"]),
                    trigger_values=json.dumps(_entry["trigger_values"]),
                    reason=_entry["reason"],
                )
                db.add(_hist)
                if _row.last_triggered_at is not None or True:  # always update
                    _row.last_triggered_at = _now
                _rn = (await db.execute(select(AlertRuleModel).where(AlertRuleModel.id == _row.id))).scalar_one_or_none()
                _rname = _rn.name if _rn else None
                _subj, _plain, _html = _build_notification_text(_entry, _rname)
                _ncfg = _load_notification_config()
                _gm = _ncfg.get('gmail', {})
                _tg = _ncfg.get('telegram', {})
                if _gm.get('enabled'):
                    _dispatch('gmail', to=_gm.get('to', ''), subject=_subj, body=_plain,
                              smtp_user=_gm.get('smtp_user', ''), smtp_password=_gm.get('smtp_password', ''))
                if _tg.get('enabled'):
                    _dispatch('telegram', bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=_html)
                triggered.append(_entry)

        await db.commit()
    return triggered
```

**Do not delete the trailing `await db.commit()` / `return triggered` lines** — they are the shared cleanup for the whole function (both standard and composite rule paths), not part of the composite block, and are reproduced above so the replacement is complete. This also fixes a gap the adversarial review caught: the original draft of this step omitted `direction=` on the `describe_match()` call, meaning a Bearish composite rule's fired-alert reason text would silently describe strategy matches using the "Bullish" default instead of the rule's own direction, unlike the scheduled path (`strategy_watch_evaluator.py:194-196`, which already passes `direction=wdir`). The comment block above documents the current (now correct) behavior instead of the removed stale `# NOTE:` comment, which described a limitation that no longer exists after this task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v`
Expected: all 4 tests PASS.

Run also: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_composite_trigger.py tests/test_strategy_watch_evaluator.py tests/test_alert_router.py -v`
Expected: all PASS (no regressions in the scheduled path or existing router tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_composite_ws.py
git commit -m "fix(alerts): fetch daily bars for WS composite strategy-confirmation gate"
```

---

## Bug 2: Regime condition Model dropdown (OMM/HMM) is ignored by the backend

### Task 3: Make `_evaluate_regime_condition` model-aware; add `build_regime_snapshot`

**Files:**
- Modify: `backend/app/services/alert_evaluator.py:97-106` (`_evaluate_regime_condition`), `:109-115` (`_evaluate_condition`), `:189-230` (`evaluate_rules`)
- Test: `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_alert_evaluator.py`, update the import block at the top (lines 4-7) to:

```python
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, make_history_id,
    build_regime_snapshot,
)
```

Then append these new classes at the end of the file:

```python
class TestRegimeCondition:
    def test_regime_condition_omm_state_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 60}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_wrong_state_no_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 60}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_model_selects_correct_snapshot(self):
        """model='HMM' selected but only OMM data available → condition not met,
        even though state/conviction would match if OMM data were used instead."""
        condition = RegimeCondition(kind='regime', model='HMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 90}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_hmm_state_match(self):
        condition = RegimeCondition(kind='regime', model='HMM', state='Trending')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM': {'state': 'Trending', 'conviction': 82.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_min_conviction_gate(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='any', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 50}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_no_regime_data_no_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), None)
        assert len(results) == 0

    def test_regime_condition_any_model_matches_whatever_is_available(self):
        condition = RegimeCondition(kind='regime', model='any', state='Trending')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM': {'state': 'Trending', 'conviction': 82.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_bear_state_flips_conviction_sign(self):
        """OMM conviction is Bullish-framed (negative here means 'strongly favors Bear').
        A Bear-state condition must flip the sign so min_conviction=70 is satisfied by
        a regime that strongly favors Bear, not rejected by it."""
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bear', 'conviction': -85}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_bear_state_weak_bear_conviction_not_met(self):
        """Same flip, but the regime only weakly favors Bear — must not meet a 70 threshold."""
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bear', 'conviction': -20}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0


class TestBuildRegimeSnapshot:
    def test_insufficient_bars_returns_empty_dict(self):
        candles = [{'close': 100.0 + i} for i in range(10)]
        assert build_regime_snapshot(candles) == {}

    def test_omm_populated_when_enough_bars(self):
        # Clear uptrend, 150 bars — enough for compute_omm's min_obs=100 requirement.
        candles = [{'close': 100.0 + i * 0.5} for i in range(150)]
        snapshot = build_regime_snapshot(candles)
        assert 'OMM' in snapshot
        assert snapshot['OMM']['state'] in ('Bull', 'Bear', 'Choppy')

    def test_hmm_absent_below_minimum_bars(self):
        # 50 bars is below both OMM's (100) and HMM's (200) minimums — 'HMM' must be absent
        # regardless of whether hmmlearn is installed in this environment.
        candles = [{'close': 100.0 + i} for i in range(50)]
        snapshot = build_regime_snapshot(candles)
        assert 'HMM' not in snapshot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v`
Expected: FAIL on import (`RegimeCondition`/`build_regime_snapshot` importable already for `RegimeCondition` since it exists, but `build_regime_snapshot` doesn't exist yet) and on the `TestRegimeCondition` tests (positional `regime` arg not model-aware yet).

- [ ] **Step 3: Implement model-aware regime evaluation + `build_regime_snapshot`**

In `backend/app/services/alert_evaluator.py`, replace `_evaluate_regime_condition` (lines 97-106):

```python
def _evaluate_regime_condition(condition, regime_by_model: Optional[dict]) -> tuple[bool, dict]:
    if not regime_by_model:
        return False, {}
    if condition.model == 'any':
        regime = regime_by_model.get('OMM') or regime_by_model.get('HMM')
    else:
        regime = regime_by_model.get(condition.model)
    if not regime:
        return False, {}
    state_match = condition.state == 'any' or regime.get('state') == condition.state
    conviction = regime.get('conviction')
    # build_regime_snapshot() computes OMM conviction with a fixed Bullish framing
    # (positive = model favors Bull persisting). For a condition targeting the Bear
    # state, flip the sign so min_conviction consistently means "how strongly does
    # the regime favor the selected state" — otherwise a strongly-Bear regime shows
    # up as strongly-negative conviction and can never clear a positive min_conviction
    # threshold. Other states (Choppy/any/HMM's Trending/Mean-reverting/...) have no
    # natural Bull/Bear opposite, so their conviction is left as computed.
    if conviction is not None and condition.state == 'Bear':
        conviction = -conviction
    conviction_match = (
        condition.min_conviction is None
        or (conviction is not None and conviction >= condition.min_conviction)
    )
    met = state_match and conviction_match
    return met, {'regime_state': 1} if met else {}


def build_regime_snapshot(candles: list[dict]) -> dict:
    """Compute {'OMM': {...}, 'HMM': {...}} regime data for regime-kind alert conditions.

    A missing key means that model's regime could not be computed (insufficient
    bars, or hmmlearn unavailable) — matching conditions for that model fail closed
    rather than raising.

    OMM conviction is always computed with a fixed Bullish framing (RegimeCondition
    has no direction field to pick a framing from); _evaluate_regime_condition()
    flips the sign for Bear-state conditions so min_conviction reads consistently
    regardless of which state the condition targets.
    """
    closes = [c["close"] for c in candles] if candles else []
    snapshot: dict = {}

    if len(closes) >= 100:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes)
        if omm is not None:
            snapshot['OMM'] = {'state': omm.state, 'conviction': omm.conviction_pct}

    if len(candles) >= 200:
        from app.services.regime_hmm import compute_intraday_hmm
        hmm = compute_intraday_hmm(candles)
        if hmm is not None:
            # HmmResult has no conviction score; p_stay (probability of remaining
            # in the detected state) is the closest available confidence metric —
            # the regime-snapshot endpoint already surfaces P(stay) for HMM users.
            snapshot['HMM'] = {'state': hmm.state, 'conviction': round(hmm.p_stay * 100, 1)}

    return snapshot
```

**Known limitation, deliberately not fixed here:** `RegimeCondition` has no `direction` field at all (see `frontend/types/alerts.ts`), so there is no way to know, in general, which "framing" the user intends conviction to be measured in — the Bear-flip above only handles the one unambiguous case (OMM's Bull/Bear axis). HMM states (`Trending`/`Choppy`/`Mean-reverting`) have no such axis, so their conviction (`p_stay`-derived) is not direction-sensitive to begin with — no fix needed there. Properly generalizing this would require a schema change to `RegimeCondition` (frontend + backend), which is out of scope for "the model dropdown is ignored."

Update `_evaluate_condition` (lines 109-115) to rename the `regime` parameter:

```python
def _evaluate_condition(condition, closed_candle: dict, indicators: dict,
                        signals: list[dict], candle_time: str,
                        regime_by_model: Optional[dict] = None) -> tuple[bool, dict]:
    trigger_values: dict = {}

    if condition.kind == 'regime':
        return _evaluate_regime_condition(condition, regime_by_model)
```

Update `evaluate_rules` (lines 189-230) — rename the parameter and the one call site inside it:

```python
def evaluate_rules(rules: list[AlertRuleInput], closed_candle: dict,
                   all_candles: list[dict], indicators: dict, signals: list[dict],
                   now: datetime, regime_by_model: Optional[dict] = None) -> list[dict]:
    results = []
    for rule in rules:
        if not rule.enabled:
            continue
        if not rule.group.conditions:
            continue
        if _is_expired(rule, now):
            continue
        if not _is_cooldown_passed(rule, now):
            continue

        accumulated_trigger_values: dict = {}
        evaluations = []
        for c in rule.group.conditions:
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'], regime_by_model)
            accumulated_trigger_values.update(tv)
            evaluations.append(met)
```

(The rest of `evaluate_rules` — the `AND`/`OR`/`N_OF_M` aggregation and result-building — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v`
Expected: all tests PASS (existing + new `TestRegimeCondition` + `TestBuildRegimeSnapshot`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_evaluator.py backend/tests/test_alert_evaluator.py
git commit -m "fix(alerts): make regime condition evaluation branch on OMM/HMM model"
```

---

### Task 4: Wire regime deserialization + snapshot building into `chart_alerts.py`

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:20-23` (imports), `:151-168` (`_deserialize_rule`), `:334-348` (`test_rule`), `:379-517` (`evaluate_and_notify_for_symbol`)
- Test: `backend/tests/test_alert_router.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_alert_router.py`:

```python
@pytest.mark.asyncio
async def test_regime_condition_round_trips_through_test_endpoint():
    """A saved regime condition must survive deserialization (previously silently
    dropped) and evaluate against real regime data built from the test candles."""
    app = await _make_app()
    body = {
        'name': 'Regime Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [
            {'kind': 'regime', 'model': 'OMM', 'state': 'any'},
        ]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        # 150 bars of a clear uptrend — enough for build_regime_snapshot's OMM branch to populate.
        candles = [
            {'time': f'2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T09:30',
             'open': 100 + i * 0.5, 'high': 101 + i * 0.5,
             'low': 99 + i * 0.5, 'close': 100 + i * 0.5, 'volume': 1000}
            for i in range(150)
        ]
        resp2 = await client.post(f'/alerts/rules/{rule_id}/test', json={
            'candles': candles, 'indicators': {}, 'signals': [],
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert len(data['matches']) >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_router.py::test_regime_condition_round_trips_through_test_endpoint -v`
Expected: FAIL — `data['matches']` is empty (the regime condition is silently dropped by `_deserialize_rule`, so the rule has zero conditions and `evaluate_rules` skips it via the `if not rule.group.conditions: continue` guard).

- [ ] **Step 3: Add the missing deserialization branch and wire the regime snapshot through both call sites**

In `backend/app/routers/chart_alerts.py`, update the `alert_evaluator` import (lines 20-23) to include `RegimeCondition` and `build_regime_snapshot`:

```python
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
)
```

Update `_deserialize_rule` (lines 151-168) to add the missing `regime` branch:

```python
def _deserialize_rule(rule_json_str: str, row: AlertRuleModel) -> AlertRuleInput:
    group_data = json.loads(rule_json_str)
    conditions = []
    for c in group_data.get('conditions', []):
        kind = c.get('kind', '')
        if kind == 'price':
            conditions.append(PriceCondition(kind='price', operator=c['operator'], value=c['value']))
        elif kind == 'indicator':
            conditions.append(IndicatorCondition(kind='indicator', indicator=c['indicator'], operator=c['operator'], value=c['value']))
        elif kind == 'structure':
            conditions.append(StructureCondition(kind='structure', signal_kind=c['signal_kind'], direction=c.get('direction'), min_confidence=c.get('min_confidence')))
        elif kind == 'regime':
            conditions.append(RegimeCondition(kind='regime', model=c.get('model', 'OMM'), state=c.get('state', 'Bull'), min_conviction=c.get('min_conviction')))
    return AlertRuleInput(
        id=row.id, name=row.name, symbol=row.symbol, interval=row.interval,
        enabled=bool(row.enabled),
        group=ConditionGroup(logic=group_data.get('logic', 'AND'), conditions=conditions),
        cooldown_minutes=row.cooldown_minutes, expiry_date=row.expiry_date,
        created_at=row.created_at, last_triggered_at=row.last_triggered_at,
    )
```

Update `test_rule` (lines 334-348) to build a causally-correct regime snapshot per replay step (only when needed):

```python
@router.post('/rules/{rule_id}/test')
async def test_rule(rule_id: str, body: AlertTestRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    rule_input = _deserialize_rule(row.rule_json, row)
    needs_regime = any(c.kind == 'regime' for c in rule_input.group.conditions)
    matches = []
    for i in range(len(body.candles)):
        candle = body.candles[i]
        window = body.candles[:i + 1]
        regime_by_model = build_regime_snapshot(window) if needs_regime else None
        results = evaluate_rules([rule_input], candle, window, body.indicators, body.signals, datetime.now(), regime_by_model)
        matches.extend(results)
    return {'matches': matches}
```

Update `evaluate_and_notify_for_symbol` — insert the regime snapshot computation right after `rule_inputs` is built (before the indicator-computation block), and pass it into the standard-rules `evaluate_rules` call:

```python
        rule_inputs = [_deserialize_rule(row.rule_json, row) for row in rows]

        needs_regime = any(c.kind == 'regime' for ri in rule_inputs for c in ri.group.conditions)
        regime_by_model = build_regime_snapshot(all_candles) if needs_regime else None

        # Compute indicators referenced by rule conditions
        all_conditions = []
        for ri in rule_inputs:
            all_conditions.extend(ri.group.conditions)
        indicators = compute_indicators_for_conditions(all_candles, all_conditions)

        triggered = evaluate_rules(rule_inputs, closed_candle, all_candles, indicators, signals, datetime.now(), regime_by_model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_router.py -v`
Expected: all tests PASS, including the new regime round-trip test.

Run also the full alert-related suite for regressions: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py tests/test_alert_router.py tests/test_composite_trigger.py tests/test_chart_alerts_composite_ws.py tests/test_strategy_watch_evaluator.py tests/test_alerts.py tests/test_alert_rule_id.py tests/test_alert_notifier.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_alert_router.py
git commit -m "fix(alerts): deserialize regime conditions and feed them real OMM/HMM data"
```

---

### Task 5: Fix HMM regime state options in `AlertRuleBuilder` to match backend output

**Why this belongs in Bug 2's scope:** after Task 3, selecting `model: 'HMM'` genuinely evaluates against HMM data instead of being ignored — but the frontend dropdown currently offers `Bull`/`Bear`/`Sideways` as HMM state choices, and `build_regime_snapshot()` (Task 3) only ever calls `regime_hmm.py::compute_intraday_hmm`, whose `_assign_labels` can only emit `'Trending' | 'Choppy' | 'Mean-reverting'`. Without this fix, a user who picks `HMM` + `Bull` (a state the dropdown offers but `build_regime_snapshot()` can never produce) gets a condition that silently can never fire — the exact "picking HMM has no effect" symptom originally reported, just one level deeper.

**Known limitation, deliberately not fixed here:** `Bull`/`Bear`/`Sideways` aren't nonsense values — they're exactly what `backend/app/services/regime_hmm_daily.py::compute_directional_hmm` (a third, separate, already-shipped regime model, wired into `GET /regime/series?model=HMM` for the chart overlay) produces. This step trims the dropdown to match what `build_regime_snapshot()` can *currently* produce, rather than extending `build_regime_snapshot()` to also call `compute_directional_hmm` and restore those states as reachable. Wiring the alert evaluator up to the daily-directional HMM model is a reasonable follow-up, but it's a new capability (a third branch alongside OMM/intraday-HMM, plus deciding how a `RegimeCondition` would express "daily" vs "intraday" HMM — the same `HMM` vs `HMM_daily`/`HMM_intraday` vocabulary gap noted above), not part of "the model dropdown is ignored."

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx:35`

- [ ] **Step 1: Confirm no test locks in the current values**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: 5 tests PASS (none reference `REGIME_STATES_HMM`, `Bull`, `Bear`, `Sideways`, `Trending`, `Choppy`, or `Mean-reverting` — confirmed by reading the test file; this step is a guard against unknowingly breaking a locked-in assertion, not a TDD failing-test step, since this is a pure data-correctness fix with no new user-facing behavior to unit test at the component level).

- [ ] **Step 2: Fix the state list**

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, replace line 35:

```typescript
const REGIME_STATES_HMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Sideways', 'Trending', 'Choppy', 'Mean-reverting'];
```

with:

```typescript
// Must match the state labels backend/app/services/regime_hmm.py::_assign_labels
// can actually produce — offering Bull/Bear/Sideways here would let a user save a
// condition that can never fire (the HMM model never emits those labels).
const REGIME_STATES_HMM: RegimeState[] = ['any', 'Trending', 'Choppy', 'Mean-reverting'];
```

- [ ] **Step 3: Run the typecheck and component test to verify no regression**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: both clean/PASS. (`RegimeState` in `frontend/types/alerts.ts` already includes `'Trending' | 'Choppy' | 'Mean-reverting'`, so no type changes are needed — only the options array shrinks.)

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/index.tsx
git commit -m "fix(alerts): only offer HMM regime states the backend model can produce"
```

---

## Final verification (run once, after both bugs are implemented)

```bash
cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest -v
```
Expected: `914 passed, 9 skipped, 0 failed` — 893 pre-existing + 21 new backend tests from this plan (4 in Task 1, 4 in Task 2, 12 in Task 3, 1 in Task 4); the 9 skips remain the pre-existing `hmmlearn`-related skips, unrelated to this work. Treat the exact new-test count as approximate — what matters is 0 failed and the skip count unchanged.

```bash
cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck
```
Expected: clean, no output. (Bug 2's frontend model dropdown itself already worked correctly before this plan — only the backend ignored it — but Task 5 trims the HMM state options list, so this typecheck plus Task 5's own component-test run are the frontend verification for this plan.)
