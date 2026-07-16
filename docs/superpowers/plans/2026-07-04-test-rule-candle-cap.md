# Test-Rule Candle Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hard cap on how many candles the `/alerts/rules/{rule_id}/test` dry-run endpoint will accept, so a very large pasted candle list can't force an unbounded number of HMM refits (one per candle, once the causal window passes 200 bars) and make the request pathologically slow or resource-heavy.

**Architecture:** `chart_alerts.py::test_rule()` loops once per candle in `body.candles`, rebuilding a growing window and — for rules with a `regime` condition — calling `build_regime_snapshot()` on that window every iteration. Each call that clears 200 bars re-fits a 3-state `GaussianHMM` from scratch (not incrementally), so cost grows with both the candle count and, quadratically in the worst case, with how many of those candles are past the 200-bar HMM threshold. Add a fixed upper bound on `len(body.candles)` and reject oversized requests with `HTTP 422` before any work begins, rather than trying to make the HMM refit itself faster (out of scope) or silently truncating the input (would produce misleading dry-run results for candles the endpoint pretended to test but didn't).

**Tech Stack:** FastAPI, pytest + pytest-asyncio, httpx `AsyncClient`.

**Related, not fixed by this plan:** this cap only bounds the dry-run `/test` endpoint. The identical unbounded-HMM-refit cost pattern also applies to the live WS path (`evaluate_and_notify_for_symbol`'s call to `build_regime_snapshot(all_candles)` on every candle close), and the sibling `2026-07-03-composite-ws-hmm-primary-support.md` plan adds a second, separate source of per-candle-close HMM refitting for composite rules. Neither live-path cost is capped or cached by any of these plans — see that plan's own "Known limitation" note. This plan closes only the dry-run instance of the problem.

---

## File Structure

- Modify: `backend/app/routers/chart_alerts.py` — add `MAX_TEST_RULE_CANDLES` constant near the top of the file, and a guard at the start of `test_rule()` (currently lines 337-360).
- Test: `backend/tests/test_alert_router.py` — new tests for the cap (rejected above it, accepted at exactly the cap).

---

## Task 1: Add the candle-count cap to `test_rule`

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:29-30` (module-level constants), `:337-360` (`test_rule`)
- Test: `backend/tests/test_alert_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alert_router.py`:

```python
@pytest.mark.asyncio
async def test_test_endpoint_rejects_too_many_candles():
    """A dry-run request with more candles than MAX_TEST_RULE_CANDLES must be
    rejected up front with 422, not accepted and left to run an unbounded number
    of per-candle HMM refits."""
    from app.routers.chart_alerts import MAX_TEST_RULE_CANDLES

    app = await _make_app()
    body = {
        'name': 'Test Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        candles = [
            {'time': f't{i}', 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1000}
            for i in range(MAX_TEST_RULE_CANDLES + 1)
        ]
        resp2 = await client.post(f'/alerts/rules/{rule_id}/test', json={
            'candles': candles, 'indicators': {}, 'signals': [],
        })
        assert resp2.status_code == 422
        assert str(MAX_TEST_RULE_CANDLES) in resp2.json()['detail']


@pytest.mark.asyncio
async def test_test_endpoint_accepts_exactly_the_cap():
    """A request with exactly MAX_TEST_RULE_CANDLES candles must still be accepted —
    the cap is a strict 'more than', not 'at least'."""
    from app.routers.chart_alerts import MAX_TEST_RULE_CANDLES

    app = await _make_app()
    body = {
        'name': 'Test Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        candles = [
            {'time': f't{i}', 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1000}
            for i in range(MAX_TEST_RULE_CANDLES)
        ]
        resp2 = await client.post(f'/alerts/rules/{rule_id}/test', json={
            'candles': candles, 'indicators': {}, 'signals': [],
        })
        assert resp2.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_router.py -v -k cap`
Expected: FAIL — `ImportError: cannot import name 'MAX_TEST_RULE_CANDLES'` (constant doesn't exist yet).

- [ ] **Step 3: Implement**

In `backend/app/routers/chart_alerts.py`, add a module-level constant after the `router = APIRouter(...)` line (currently line 30):

Before:
```python
logger = logging.getLogger(__name__)
router = APIRouter(prefix='/alerts', tags=['chart-alerts'])
```

After:
```python
logger = logging.getLogger(__name__)
router = APIRouter(prefix='/alerts', tags=['chart-alerts'])

# test_rule() re-fits a 3-state GaussianHMM from scratch on every candle once the
# causal window passes 200 bars (build_regime_snapshot() is called once per
# iteration) — an unbounded candle list makes this endpoint pathologically slow.
# 1500 comfortably covers a full intraday session's worth of 1-minute bars plus
# headroom, while still bounding worst-case per-request HMM refit count.
MAX_TEST_RULE_CANDLES = 1500
```

Then modify `test_rule()` (currently lines 337-345) to check the cap before doing any DB lookup:

Before:
```python
@router.post('/rules/{rule_id}/test')
async def test_rule(rule_id: str, body: AlertTestRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
```

After:
```python
@router.post('/rules/{rule_id}/test')
async def test_rule(rule_id: str, body: AlertTestRequest, db: AsyncSession = Depends(get_db)):
    if len(body.candles) > MAX_TEST_RULE_CANDLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f'Too many candles for a dry-run test ({len(body.candles)} > {MAX_TEST_RULE_CANDLES}). '
                'Trim the candle list — each candle re-fits regime models when the rule has a regime condition.'
            ),
        )
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_router.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_alert_router.py
git commit -m "fix(alerts): cap test_rule dry-run candle count to bound per-candle HMM refit cost"
```

---

## Final verification

- [ ] `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest -q` — expect all pass, no regressions.

## Self-Review Notes

- **Spec coverage:** directly addresses deferred item 5 — the endpoint now rejects oversized requests instead of silently running an unbounded amount of HMM-refit work.
- **No placeholders:** exact code, exact test, exact commands.
- **Design note for review:** 1500 is a judgment call, not derived from a hard constraint — flag during adversarial review if a different cap (e.g. tied to `regime_hmm.py`'s own 800-bar internal cap) would be more defensible.
