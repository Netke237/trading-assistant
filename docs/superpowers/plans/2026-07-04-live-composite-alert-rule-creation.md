# Live Composite Alert Rule — Creation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a supported way to create a *live* (WebSocket-checked) composite alert rule through the app, so the already-correct `evaluate_and_notify_for_symbol()` composite branch in `chart_alerts.py` becomes reachable.

**Architecture:** Extend the existing `CompositeAlertDialog` (which already builds the full composite `trigger_def` and submits it to the backend) with a **delivery-mode toggle** — "Watch (background, always on)" vs "Rule (live, only while this chart tab is open)". Watch mode keeps the current `POST /api/composite-watches/` path unchanged. Rule mode submits the same `trigger_def` to `POST /alerts/rules` tagged `__type: composite`, storing a DB `alert_rules` row that the WS candle-close evaluator already knows how to read. The standard-rule list/serialize path is taught to tolerate composite rows so the existing `chartAlertStore` (which loads `GET /alerts/rules`) does not choke.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 + React + Zustand (frontend), pytest + Jest.

**Spec reference:** `docs/superpowers/plans/2026-07-03-live-composite-alert-rule-creation-spec.md`. Note the spec's open HMM-live gap is now CLOSED — `composite_trigger_evaluator.evaluate_from_context()` handles `HMM_intraday`/`HMM_daily`. This plan covers ONLY the creation/storage/list path, not evaluation logic.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/routers/chart_alerts.py` | Modify | Accept `__type: composite` on create/replace; serialize composite rows safely in list output |
| `backend/tests/test_chart_alerts_composite_create.py` | Create | Backend tests for composite rule create + list serialization |
| `frontend/lib/api.ts` | Modify | Add `addCompositeAlertRule()` calling `POST /alerts/rules` with composite body |
| `frontend/components/organisms/CompositeAlertDialog/index.tsx` | Modify | Delivery-mode toggle, name field (rule mode), live-only warning, branched submit |
| `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css` | Modify | Styles for toggle + warning |
| `frontend/components/organisms/CompositeAlertDialog/__tests__/CompositeAlertDialog.test.tsx` | Modify | Tests for both delivery modes |

---

## Design decisions (read before coding)

1. **Storage shape.** A composite rule's `rule_json` is `{"__type": "composite", ...trigger_def}` — exactly the shape `evaluate_and_notify_for_symbol()` already reads via `composite_rows` (it strips `__type` before calling `evaluate_from_context`). No evaluator change is needed.

2. **API schema.** `AlertRuleCreate.group` is currently required. Composite rules have no `group`. Rather than overload `group`, add two optional fields: `rule_type: str = 'standard'` and `composite_def: Optional[dict] = None`. When `rule_type == 'composite'`, `composite_def` is required and `group` is ignored (default empty group allowed). This keeps standard-rule requests byte-identical to today.

3. **List serialization.** `GET /alerts/rules` → `_rule_to_dict()` currently does `json.loads(row.rule_json)` into a `group` key. For a composite row that would place the composite dict under `group`, and the frontend `chartAlertStore` would try to parse it as `AlertRule.group.conditions`. Fix: `_rule_to_dict()` detects `__type == 'composite'` and returns `{..., 'rule_type': 'composite', 'composite_def': <def-without-__type>, 'group': {'logic': 'AND', 'conditions': []}}`. The empty `group` keeps the standard-shape consumer safe; a `rule_type` marker lets any future consumer (and item 2's plan) distinguish them.

4. **Name.** Composite watches have no user-facing name; chart rules require one (`AlertRuleModel.name` is non-null, and the Rules tab shows it). In rule mode the dialog must collect a name. Default it to `"{symbol} composite"` so the field is never empty.

5. **Live-only warning.** Rule mode shows a persistent caution note: a live rule is only evaluated while that chart's stream tab is open — unlike a Watch, which the scheduler checks in the background.

---

## Task 1: Backend — accept composite rules on create

**Files:**
- Modify: `backend/app/routers/chart_alerts.py` (`AlertRuleCreate` ~line 63, `create_rule` ~line 183)
- Test: `backend/tests/test_chart_alerts_composite_create.py`

> **Test harness note (critical).** `create_rule`/`replace_rule` use `Depends(get_db)`, which in production binds to `AsyncSessionLocal` on `settings.DATABASE_URL` — unusable in tests, and the `alert_rules` table (owned by `app.database.Base`) is not created by `conftest.py` (it only creates `ScanSessionBase.metadata`). So this test file MUST spin up its own in-memory SQLite engine, create `Base.metadata`, and override the `get_db` dependency on a minimal test app that mounts only the chart-alerts router (whose prefix is already `/alerts`). This mirrors the engine setup in `tests/test_chart_alerts_composite_ws.py` combined with the `dependency_overrides[get_db]` pattern in `conftest.py`. `pytest.ini` sets `asyncio_mode = auto`, so async tests/fixtures need no explicit marker, but use `@pytest_asyncio.fixture` for the async fixture.

- [ ] **Step 1: Write the failing test (with a self-contained DB fixture)**

```python
# backend/tests/test_chart_alerts_composite_create.py
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401  (register tables)
from app.routers.chart_alerts import router as chart_alerts_router


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(chart_alerts_router)          # prefix '/alerts' is on the router
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def test_create_composite_rule_stores_typed_rule_json(client):
    body = {
        "name": "AAPL composite",
        "symbol": "aapl",
        "interval": "15m",
        "rule_type": "composite",
        "composite_def": {
            "primary": {"model": "OMM", "to_state": "Bull", "conviction_min": 60,
                        "p_stay_min": 0.7, "p_transition_min": 0.3},
            "confirmations": [], "min_confirmations": 0,
            "strategy_confirmations": [], "min_strategy_confirmations": 0,
            "horizon": "swing", "direction": "Bullish",
        },
    }
    resp = await client.post("/alerts/rules", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["rule_type"] == "composite"
    assert data["composite_def"]["primary"]["model"] == "OMM"
    # standard-shape consumers must still see an (empty) group, not the composite dict
    assert data["group"] == {"logic": "AND", "conditions": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_create.py -v`
Expected: FAIL — before Step 3, `AlertRuleCreate.group` is required and the body omits it, so the POST returns 422 (and the response has no `rule_type`). The failure is on `assert resp.status_code == 201`, NOT on the DB harness.

- [ ] **Step 3: Extend `AlertRuleCreate`**

In `chart_alerts.py`, change the `group` field to optional-with-default and add the two composite fields:

```python
class AlertRuleCreate(BaseModel):
    id: Optional[str] = None
    name: str
    symbol: str
    interval: str
    enabled: bool = True
    group: ConditionGroupIn = Field(default_factory=ConditionGroupIn)
    cooldown_minutes: int = 60
    expiry_date: Optional[str] = None
    rule_type: str = 'standard'
    composite_def: Optional[dict] = None
```

- [ ] **Step 4: Branch `create_rule` on `rule_type`**

Replace the `rule = AlertRuleModel(...)` construction in `create_rule` with:

```python
    if body.rule_type == 'composite':
        if not body.composite_def:
            raise HTTPException(status_code=422, detail='composite_def is required when rule_type is "composite"')
        rule_json = json.dumps({"__type": "composite", **body.composite_def})
    else:
        rule_json = json.dumps(body.group.model_dump())

    rule = AlertRuleModel(
        id=rule_id, user_id='default', name=body.name, symbol=body.symbol.upper(),
        interval=body.interval, enabled=body.enabled,
        rule_json=rule_json,
        cooldown_minutes=body.cooldown_minutes, expiry_date=body.expiry_date,
        created_at=now, last_triggered_at=None,
    )
```

- [ ] **Step 5: Teach `_rule_to_dict` to serialize composite rows safely**

Replace `_rule_to_dict`:

```python
def _rule_to_dict(row: AlertRuleModel) -> dict:
    parsed = json.loads(row.rule_json)
    base = {
        'id': row.id, 'name': row.name, 'symbol': row.symbol, 'interval': row.interval,
        'enabled': row.enabled,
        'cooldown_minutes': row.cooldown_minutes, 'expiry_date': row.expiry_date,
        'created_at': row.created_at, 'last_triggered_at': row.last_triggered_at,
    }
    if isinstance(parsed, dict) and parsed.get('__type') == 'composite':
        composite_def = {k: v for k, v in parsed.items() if k != '__type'}
        base['rule_type'] = 'composite'
        base['composite_def'] = composite_def
        base['group'] = {'logic': 'AND', 'conditions': []}
    else:
        base['rule_type'] = 'standard'
        base['group'] = parsed
    return base
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_create.py -v`
Expected: PASS.

- [ ] **Step 7: Regression — full backend suite still green**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q`
Expected: previously-passing count + 1 new test, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_composite_create.py
git commit -m "feat(alerts): accept __type=composite rules on POST/GET /alerts/rules"
```

---

## Task 2: Backend — composite rules survive replace (PUT) round-trip

**Files:**
- Modify: `backend/app/routers/chart_alerts.py` (`replace_rule` ~line 225)
- Test: `backend/tests/test_chart_alerts_composite_create.py` (add case)

- [ ] **Step 1: Write the failing test**

```python
async def test_replace_composite_rule_preserves_type(client):
    create = {
        "id": "cmp-put-1", "name": "n", "symbol": "MSFT", "interval": "1h",
        "rule_type": "composite",
        "composite_def": {"primary": {"model": "OMM", "to_state": "Bull"},
                          "confirmations": [], "strategy_confirmations": [],
                          "direction": "Bullish"},
    }
    await client.post("/alerts/rules", json=create)
    create["name"] = "renamed"
    resp = await client.put("/alerts/rules/cmp-put-1", json=create)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "renamed"
    assert data["rule_type"] == "composite"
    assert data["group"] == {"logic": "AND", "conditions": []}
```

(The `client` fixture from Task 1 is reused — it lives in the same test module.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_create.py::test_replace_composite_rule_preserves_type -v`
Expected: FAIL — `replace_rule` always writes `body.group.model_dump()`, discarding composite type.

- [ ] **Step 3: Branch `replace_rule` on `rule_type`**

Replace the `row.rule_json = ...` line in `replace_rule` with:

```python
    if body.rule_type == 'composite':
        if not body.composite_def:
            raise HTTPException(status_code=422, detail='composite_def is required when rule_type is "composite"')
        row.rule_json = json.dumps({"__type": "composite", **body.composite_def})
    else:
        row.rule_json = json.dumps(body.group.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_create.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_composite_create.py
git commit -m "feat(alerts): preserve composite type across PUT /alerts/rules"
```

---

## Task 3: Frontend API — `addCompositeAlertRule()`

**Files:**
- Modify: `frontend/lib/api.ts` (composite watches block ~line 498)

- [ ] **Step 1: Add the API method**

In the composite-watches section of `api.ts`, add (mirroring the existing `addCompositeWatch` signature, but posting to `/alerts/rules`):

```typescript
  // Live composite RULE (WS-checked, only while chart tab is open) — distinct from
  // a Composite Watch (scheduled/background). Stored as an alert_rules row.
  addCompositeAlertRule: (
    name: string,
    symbol: string,
    interval: string,
    triggerDef: Record<string, unknown>,
  ) =>
    post<AlertRule>('/alerts/rules', {
      name,
      symbol,
      interval,
      rule_type: 'composite',
      composite_def: triggerDef,
    }),
```

`AlertRule` is already imported/used in `api.ts` (see the existing `createAlertRule: … post<AlertRule>`), so no new import is needed.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(api): addCompositeAlertRule posts composite body to /alerts/rules"
```

---

## Task 4: Frontend — delivery-mode toggle in CompositeAlertDialog

**Files:**
- Modify: `frontend/components/organisms/CompositeAlertDialog/index.tsx`
- Modify: `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css`
- Test: `frontend/components/organisms/CompositeAlertDialog/__tests__/CompositeAlertDialog.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add to the existing test file (mock `api.addCompositeAlertRule` and `api.addCompositeWatch`):

```tsx
it('defaults to Watch mode and calls addCompositeWatch on save', async () => {
  const addWatch = jest.spyOn(api, 'addCompositeWatch').mockResolvedValue({} as never);
  render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
  await waitFor(() => expect(addWatch).toHaveBeenCalled());
});

it('in Rule mode calls addCompositeAlertRule with a name', async () => {
  const addRule = jest.spyOn(api, 'addCompositeAlertRule').mockResolvedValue({} as never);
  render(<CompositeAlertDialog symbol="AAPL" direction="Bullish" onClose={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: /Rule \(live\)/ }));
  fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
  await waitFor(() => expect(addRule).toHaveBeenCalledWith(
    expect.any(String), 'AAPL', expect.any(String), expect.any(Object),
  ));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- --testPathPattern=CompositeAlertDialog`
Expected: FAIL — no Rule button, `addCompositeAlertRule` never called.

- [ ] **Step 3: Add delivery-mode + name state**

After the existing `useState` block in `CompositeAlertDialog`, add:

```tsx
  const [deliveryMode, setDeliveryMode] = useState<'watch' | 'rule'>('watch');
  const [ruleName, setRuleName] = useState('');
```

- [ ] **Step 4: Branch `handleSave`**

Replace the `try { await api.addCompositeWatch(...) ... }` block with:

```tsx
    try {
      if (deliveryMode === 'rule') {
        const name = ruleName.trim() || `${symbol} composite`;
        await api.addCompositeAlertRule(name, symbol, interval, triggerDef);
      } else {
        await api.addCompositeWatch(symbol, triggerDef, direction, interval);
      }
      setDone(true);
      setTimeout(onClose, 1200);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
```

- [ ] **Step 5: Add the toggle + name field + warning to the JSX**

Immediately after the `<div className={styles.header}>…</div>` header block (and inside the `!done` branch, before the Model row), add:

```tsx
            <div className={styles.deliveryToggle}>
              <button
                type="button"
                className={`${styles.deliveryBtn} ${deliveryMode === 'watch' ? styles.deliveryActive : ''}`}
                onClick={() => setDeliveryMode('watch')}
              >
                Watch (background)
              </button>
              <button
                type="button"
                className={`${styles.deliveryBtn} ${deliveryMode === 'rule' ? styles.deliveryActive : ''}`}
                onClick={() => setDeliveryMode('rule')}
              >
                Rule (live)
              </button>
            </div>

            {deliveryMode === 'rule' && (
              <>
                <div className={styles.row}>
                  <Text size={16} tone="secondary">Rule name</Text>
                  <input
                    className={styles.select}
                    value={ruleName}
                    onChange={(e) => setRuleName(e.target.value)}
                    placeholder={`${symbol} composite`}
                  />
                </div>
                <div className={styles.warnBox}>
                  <Text size={16} tone="caution">
                    A live Rule is only checked while this chart tab stays open. For
                    always-on background checking, use Watch.
                  </Text>
                </div>
              </>
            )}
```

- [ ] **Step 6: Add styles**

In `CompositeAlertDialog.module.css` append:

```css
.deliveryToggle { display: flex; gap: 8px; margin-bottom: 12px; }
.deliveryBtn {
  flex: 1; padding: 8px; border: 1px solid var(--border-subtle);
  background: var(--bg-surface); color: var(--text-secondary); cursor: pointer;
  border-radius: 4px;
}
.deliveryActive { border-color: var(--accent); color: var(--text-primary); }
.warnBox {
  padding: 8px; border: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--caution) 8%, var(--bg-surface));
  border-radius: 4px; margin-bottom: 8px;
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=CompositeAlertDialog`
Expected: PASS.

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/organisms/CompositeAlertDialog/
git commit -m "feat(alerts): add Watch/Rule delivery-mode toggle to CompositeAlertDialog"
```

---

## Task 5: Manual verification (live path reachability)

- [ ] **Step 1:** Start backend + `cd frontend && npm run dev`.
- [ ] **Step 2:** Open a chart, open the Composite Alert dialog, switch to **Rule (live)**, set an OMM Bull primary, save.
- [ ] **Step 3:** Confirm a DB `alert_rules` row exists with `rule_json` beginning `{"__type": "composite"`. Run: `cd backend && venv/Scripts/python.exe -c "import sqlite3,glob; ..."` (inspect the alerts DB) OR hit `GET /alerts/rules` and confirm the new row shows `rule_type: composite`.
- [ ] **Step 4:** Confirm the Alerts page "Rules" tab still loads without error (composite row tolerated by `chartAlertStore`). If the store errors on the composite row, that is an item-2 boundary — note it; item 2's plan handles composite display explicitly.

---

## Self-review checklist (done during writing)

- Spec coverage: creation UI ✅ (Task 4), storage shape ✅ (Task 1), schema ✅ (Task 1), list-tolerance ✅ (Task 1 Step 5), replace ✅ (Task 2), live-only warning ✅ (Task 4 Step 5). Evaluation logic intentionally out of scope (already correct).
- Type consistency: `addCompositeAlertRule(name, symbol, interval, triggerDef)` used identically in api.ts (Task 3) and dialog (Task 4). Backend `rule_type`/`composite_def` names identical across `AlertRuleCreate`, `create_rule`, `replace_rule`, `_rule_to_dict`.
- Open boundary flagged: does `chartAlertStore` tolerate composite rows returned by `GET /alerts/rules`? Verified in Task 5 Step 4; if it does not, the fix belongs to the item-2 plan (which owns how composite rules/watches are displayed).
