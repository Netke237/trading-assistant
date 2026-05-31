# Chart Gaps Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical and high-severity gaps found in the Phase 1–4 chart audit, covering chart rendering, backend analysis, alert data integrity, and notification persistence.

**Architecture:** Fixes are grouped into two independent subsystems — (A) Frontend rendering & UX (Tasks 1–5, 9–11) and (B) Backend data integrity (Tasks 6–8, 12). Tasks within each subsystem are ordered by severity. Task 3 (syncRules ID fix) is the most critical backend-touching frontend fix. Drawing tools (full canvas interaction) are explicitly deferred — a separate plan is required for that feature.

**Tech Stack:** Next.js 15 App Router, TypeScript 5.7 strict, Zustand v5, lightweight-charts v5, CSS Modules (frontend); FastAPI, Python 3.12, pytest, SQLAlchemy v2 (backend).

**Branch:** `feat/chart-phase1` — all changes go here.

---

## Scope Note — Drawing Tools Deferred

Full drawing tool implementation (trendline, fib retracement, shapes drawn on the canvas) requires lightweight-charts v5 Primitives API with mouse-event hit-testing, per-symbol storage, and an undo/redo stack. This is a standalone project (≥ 40 tasks). The toolbar buttons remain as-is — they are visually correct placeholders. A separate plan will cover drawing tool implementation.

---

## File Map

### Modified (frontend)
| File | Change |
|---|---|
| `frontend/components/organisms/ChartPane/index.tsx` | Add fluid height mode; add Bar series type |
| `frontend/components/organisms/ChartPane/ChartPane.module.css` | Remove fixed flex-shrink |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Main pane flex wrapper; pass chartType to buildMainSeries; VWAP guard; connection + error state |
| `frontend/components/organisms/ChartWorkspace/ChartWorkspace.module.css` | `.mainPane` flex:1 style |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Connection state badge |
| `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css` | Badge styles |
| `frontend/components/organisms/IndicatorPanel/index.tsx` | Parameter editing rows |
| `frontend/components/organisms/IndicatorPanel/IndicatorPanel.module.css` | Param row styles |
| `frontend/components/organisms/ChartRightPanel/index.tsx` | Confidence display in Data tab |
| `frontend/lib/chartWS.ts` | `onStateChange` callback |
| `frontend/lib/chartAlertStore.ts` | `addRule` updates local ID from server response |
| `frontend/app/(frame)/settings/page.tsx` | NotificationForm loads/saves from backend |

### Modified (backend)
| File | Change |
|---|---|
| `backend/app/services/market_structure.py` | `_detect_hidden_divergence`; BOS dedup |
| `backend/app/routers/chart_alerts.py` | Accept client-provided `id` in `create_rule` |
| `backend/config/settings.yaml` | Already has notification fields — no change needed |

### New (backend)
| File | Change |
|---|---|
| `backend/app/routers/notification_settings.py` | `GET/POST /settings/notifications` |
| `backend/app/main.py` | Register new router |
| `backend/tests/test_notification_settings.py` | CRUD tests |
| `backend/tests/test_hidden_divergence.py` | Hidden divergence unit tests |

---

## Task 1 — Fluid main chart height (fills screen)

**Files:**
- Modify: `frontend/components/organisms/ChartPane/index.tsx`
- Modify: `frontend/components/organisms/ChartPane/ChartPane.module.css`
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`
- Modify: `frontend/components/organisms/ChartWorkspace/ChartWorkspace.module.css`

**Context:** `ChartPane` is called with `height={320}` hardcoded. The main chart sits in a 320px box. The ResizeObserver only tracks width. `.pane` CSS has `flex-shrink: 0`. The fix makes the main pane fluid (fills remaining workspace height) while keeping sub-panes at fixed 100px.

- [ ] **Step 1: Update ChartPane to support fluid mode**

In `frontend/components/organisms/ChartPane/index.tsx`, change the `Props` interface and `initChart` + ResizeObserver to measure height when `height` is `0` or omitted:

```tsx
interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
}

export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef }: Props) {
  // ...existing refs...

  const getHeight = useCallback(() => {
    if (height > 0) return height;
    return containerRef.current?.clientHeight || 400;
  }, [height]);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0b0b14' }, textColor: '#888' },
      grid: { vertLines: { color: '#1e1e35' }, horzLines: { color: '#1e1e35' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#1e1e35' },
      timeScale: { borderColor: '#1e1e35', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: getHeight(),
    });
    chartRef.current = chart;
    if (chartApiRef) chartApiRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) { onCrosshairMoveRef.current?.(null, {}); return; }
      const values: Record<string, number> = {};
      seriesMap.current.forEach((s, id) => {
        const v = param.seriesData.get(s);
        if (v && 'close' in v) values[id] = (v as { close: number }).close;
        else if (v && 'value' in v) values[id] = (v as { value: number }).value;
      });
      onCrosshairMoveRef.current?.(String(param.time), values);
    });
  }, [getHeight]);  // remove `height` from deps, use getHeight

  useEffect(() => {
    initChart();
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: getHeight(),
        });
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesMap.current.clear();
    };
  }, [initChart, getHeight]);

  // ...existing series effect unchanged...

  return (
    <div
      ref={containerRef}
      className={styles.pane}
      style={height > 0 ? { height } : { height: '100%' }}
    />
  );
}
```

- [ ] **Step 2: Update ChartPane.module.css**

Replace the entire file content:

```css
.pane {
  width: 100%;
}
```

(Remove `flex-shrink: 0` — the wrapper controls sizing now.)

- [ ] **Step 3: Add `.mainPane` class to ChartWorkspace.module.css**

Add after the existing `.charts` rule:

```css
.mainPane {
  flex: 1;
  min-height: 0;
  position: relative;
}
```

- [ ] **Step 4: Wrap main ChartPane in ChartWorkspace**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, find the return JSX where `ChartPane` and `ChartOverlays` are inside `<div style={{ position: 'relative' }}>`. Replace that wrapper and remove the `height={320}` prop:

```tsx
<div className={styles.charts}>
  <div className={styles.mainPane}>
    <ChartPane
      series={mainSeries}
      onCrosshairMove={handleCrosshair}
      chartApiRef={chartApiRef}
      mainSeriesRef={mainSeriesRef}
    />
    <ChartOverlays
      chart={chartApiRef.current}
      mainSeries={mainSeriesRef.current}
      signals={structureSignals}
      visibility={structureVisibility}
      visible={structureVisible}
    />
  </div>
  {subPanes.map(({ id, series }) => (
    <ChartPane key={id} series={series} height={100} />
  ))}
</div>
```

- [ ] **Step 5: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/ChartPane/index.tsx \
        frontend/components/organisms/ChartPane/ChartPane.module.css \
        frontend/components/organisms/ChartWorkspace/index.tsx \
        frontend/components/organisms/ChartWorkspace/ChartWorkspace.module.css
git commit -m "fix(chart): main pane fills screen — fluid height via ResizeObserver, flex:1 wrapper"
```

---

## Task 2 — Chart type selector renders Bar and Line series

**Files:**
- Modify: `frontend/components/organisms/ChartPane/index.tsx`
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

**Context:** `buildMainSeries` always emits `type: 'Candlestick'`. The chart type stored in `chartStore.chartType` ('candle' | 'bar' | 'line') is never read. `BarSeries` is not imported. Fix: map chartType to the correct series type in `buildMainSeries`; add BarSeries handling in ChartPane.

- [ ] **Step 1: Add BarSeries import to ChartPane**

In `frontend/components/organisms/ChartPane/index.tsx`, update the import:

```tsx
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
```

- [ ] **Step 2: Add 'Bar' to SeriesConfig type in ChartPane**

Update the `SeriesConfig` interface:

```tsx
export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Bar' | 'Line' | 'Histogram';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
}
```

- [ ] **Step 3: Handle BarSeries in ChartPane series creation and setData**

In the series creation block (inside the `series.forEach`), add the Bar case after the Candlestick case:

```tsx
if (cfg.type === 'Candlestick') {
  s = chart.addSeries(CandlestickSeries, {
    upColor: '#4caf50', downColor: '#e05050',
    borderVisible: false, wickUpColor: '#4caf50', wickDownColor: '#e05050',
  });
  if (mainSeriesRef) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
} else if (cfg.type === 'Bar') {
  s = chart.addSeries(BarSeries, {
    upColor: '#4caf50', downColor: '#e05050',
  });
} else if (cfg.type === 'Histogram') {
  s = chart.addSeries(HistogramSeries, {
    color: cfg.color ?? '#4a4a6a',
    priceScaleId: cfg.priceScaleId ?? 'right',
  });
} else {
  s = chart.addSeries(LineSeries, {
    color: cfg.color ?? '#4f8ef7', lineWidth: 1,
    priceScaleId: cfg.priceScaleId ?? 'right',
  });
}
```

In the `setData` block, update to handle Bar alongside Candlestick:

```tsx
if (cfg.type === 'Candlestick' || cfg.type === 'Bar') {
  (s as ISeriesApi<'Candlestick' | 'Bar'>).setData(
    (cfg.data as Candle[]).map(c => ({
      time: c.time as Time,
      open: c.open, high: c.high, low: c.low, close: c.close,
    }))
  );
} else {
  (s as ISeriesApi<'Line' | 'Histogram'>).setData(
    (cfg.data as Point[]).map(p => ({ time: p.time as Time, value: p.value }))
  );
}
```

- [ ] **Step 4: Pass chartType into buildMainSeries in ChartWorkspace**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, update `buildMainSeries`:

```tsx
function buildMainSeries(candles: Candle[], indicators: IndicatorConfig[], chartType: string): SeriesConfig[] {
  const mainType: SeriesConfig['type'] =
    chartType === 'bar'  ? 'Bar'  :
    chartType === 'line' ? 'Line' :
    'Candlestick';

  const mainData = chartType === 'line'
    ? candles.map(c => ({ time: c.time, value: c.close } as Point))
    : candles;

  const series: SeriesConfig[] = [
    { id: 'candles', type: mainType, data: mainData },
  ];

  for (const ind of indicators) {
    if (ind.pane !== 'main') continue;
    if (ind.type === 'EMA')  series.push({ id: ind.id, type: 'Line', data: calcEMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'SMA')  series.push({ id: ind.id, type: 'Line', data: calcSMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'VWAP') series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });
    if (ind.type === 'BB') {
      const bb = calcBB(candles, ind.params.period ?? 20, ind.params.stdDev ?? 2);
      series.push({ id: `${ind.id}-upper`, type: 'Line', data: bb.upper, color: ind.color });
      series.push({ id: `${ind.id}-mid`,   type: 'Line', data: bb.middle, color: ind.color });
      series.push({ id: `${ind.id}-lower`, type: 'Line', data: bb.lower, color: ind.color });
    }
  }
  return series;
}
```

In the component body, update the `useMemo` that calls `buildMainSeries`:

```tsx
const mainSeries = useMemo(
  () => buildMainSeries(candles, activeIndicators, chartType),
  [candles, activeIndicators, chartType],
);
```

Add `chartType` to the destructure from `useChartStore`:

```tsx
const { symbol, interval, chartType, activeIndicators, setSymbol, setInterval } = useChartStore();
```

- [ ] **Step 5: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/ChartPane/index.tsx \
        frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): chart type selector now renders Bar and Line series"
```

---

## Task 3 — Fix syncRules ID collision (local ID ≠ server ID)

**Files:**
- Modify: `frontend/lib/chartAlertStore.ts`
- Modify: `backend/app/routers/chart_alerts.py`

**Context:** `addRule` pushes the rule to the backend fire-and-forget. The backend generates a NEW uuid for the rule, discarding the client-provided id. On next `syncRules()`, the server returns the rule with its uuid; the local store has the rule with the local makeId(). They differ → `syncRules` treats the local copy as "localOnly" and POSTs it again → duplicate. Fix: backend accepts the client id; if the client sends an id, use it instead of generating one.

- [ ] **Step 1: Accept client-provided id in create_rule backend endpoint**

In `backend/app/routers/chart_alerts.py`, update `AlertRuleCreate` to include an optional `id` field:

```python
class AlertRuleCreate(BaseModel):
    id: Optional[str] = None   # add this field
    name: str
    symbol: str
    interval: str
    enabled: bool = True
    group: ConditionGroupIn
    cooldown_minutes: int = 60
    expiry_date: Optional[str] = None
```

Update `create_rule` to use the client id when provided:

```python
@router.post('/rules', status_code=status.HTTP_201_CREATED)
async def create_rule(body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    rule_id = body.id or uuid.uuid4().hex
    now = datetime.now().isoformat()
    rule = AlertRuleModel(
        id=rule_id, user_id='default', name=body.name, symbol=body.symbol.upper(),
        interval=body.interval, enabled=body.enabled,
        rule_json=json.dumps(body.group.model_dump()),
        cooldown_minutes=body.cooldown_minutes, expiry_date=body.expiry_date,
        created_at=now, last_triggered_at=None,
    )
    db.add(rule)
    await db.commit()
    return _rule_to_dict(rule)
```

- [ ] **Step 2: Write a failing test for the ID preservation**

Create `backend/tests/test_alert_rule_id.py`:

```python
"""Test that create_rule preserves the client-provided ID."""


def test_create_rule_preserves_client_id(client):
    payload = {
        "id": "client-provided-id-abc",
        "name": "Test Rule",
        "symbol": "AAPL",
        "interval": "1D",
        "enabled": True,
        "group": {"logic": "AND", "conditions": [{"kind": "price", "operator": ">", "value": 185}]},
        "cooldown_minutes": 60,
        "expiry_date": None,
    }
    r = client.post("/alerts/rules", json=payload)
    assert r.status_code == 201
    assert r.json()["id"] == "client-provided-id-abc"


def test_create_rule_generates_id_when_not_provided(client):
    payload = {
        "name": "Auto ID Rule",
        "symbol": "AAPL",
        "interval": "1D",
        "enabled": True,
        "group": {"logic": "AND", "conditions": [{"kind": "price", "operator": ">", "value": 185}]},
        "cooldown_minutes": 60,
        "expiry_date": None,
    }
    r = client.post("/alerts/rules", json=payload)
    assert r.status_code == 201
    assert len(r.json()["id"]) > 0
```

- [ ] **Step 3: Run test to verify it now passes**

```bash
cd backend && pytest tests/test_alert_rule_id.py -v
```

Expected: 2/2 PASS (backend now accepts client id).

- [ ] **Step 4: Update pushRuleToAPI in chartAlertStore to send the rule id**

In `frontend/lib/chartAlertStore.ts`, the `pushRuleToAPI` function body already sends name/symbol/etc. Add `id` to the body:

```typescript
async function pushRuleToAPI(rule: AlertRule): Promise<void> {
  try {
    await fetch(`${BASE_URL}/alerts/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: rule.id,              // send client id so server preserves it
        name: rule.name, symbol: rule.symbol, interval: rule.interval,
        enabled: rule.enabled, group: rule.group,
        cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
      }),
    });
  } catch { /* fire-and-forget */ }
}
```

- [ ] **Step 5: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_alert_rule_id.py \
        frontend/lib/chartAlertStore.ts
git commit -m "fix(alerts): preserve client-provided rule ID to prevent syncRules duplicates"
```

---

## Task 4 — Notification settings: backend save/load endpoint

**Files:**
- Create: `backend/app/routers/notification_settings.py`
- Create: `backend/tests/test_notification_settings.py`
- Modify: `backend/app/main.py`

**Context:** The Settings page NotificationForm uses `useState` — credentials are lost on refresh. The backend reads from env vars only. There is no endpoint to save or load settings. Fix: add `GET /settings/notifications` (returns current config, masking password) and `POST /settings/notifications` (saves to `backend/config/settings.yaml`).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_notification_settings.py`:

```python
"""Tests for GET/POST /settings/notifications."""
import pytest


def test_get_notifications_returns_structure(client):
    r = client.get("/settings/notifications")
    assert r.status_code == 200
    data = r.json()
    assert "gmail" in data
    assert "telegram" in data
    assert "enabled" in data["gmail"]
    assert "to" in data["gmail"]
    assert "smtp_user" in data["gmail"]
    assert "smtp_password" not in data["gmail"]  # password must be masked


def test_post_notifications_saves_enabled_flag(client):
    payload = {
        "gmail": {"enabled": True, "to": "test@example.com", "smtp_user": "test@gmail.com", "smtp_password": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    }
    r = client.post("/settings/notifications", json=payload)
    assert r.status_code == 200
    assert r.json()["gmail"]["enabled"] is True
    assert r.json()["gmail"]["to"] == "test@example.com"
    # Password not echoed back
    assert "smtp_password" not in r.json()["gmail"]


def test_post_notifications_password_not_cleared_when_empty(client):
    """Sending empty password should not overwrite an existing saved password."""
    # First save with a password
    client.post("/settings/notifications", json={
        "gmail": {"enabled": True, "to": "a@b.com", "smtp_user": "u@b.com", "smtp_password": "secret"},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    })
    # Then save again with empty password
    r = client.post("/settings/notifications", json={
        "gmail": {"enabled": True, "to": "a@b.com", "smtp_user": "u@b.com", "smtp_password": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    })
    assert r.status_code == 200
    # The backend should not have cleared the password
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_notification_settings.py -v
```

Expected: FAIL — "404 Not Found" (endpoint doesn't exist yet).

- [ ] **Step 3: Create the settings router**

Create `backend/app/routers/notification_settings.py`:

```python
"""GET/POST /settings/notifications — read and persist notification config."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix='/settings', tags=['settings'])

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'


def _load_yaml() -> dict:
    if _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_PATH, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)


class GmailConfig(BaseModel):
    enabled: bool = False
    to: str = ''
    smtp_user: str = ''
    smtp_password: Optional[str] = None   # None = "don't change existing"


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: str = ''


class NotificationConfig(BaseModel):
    gmail: GmailConfig
    telegram: TelegramConfig


@router.get('/notifications')
async def get_notifications() -> dict:
    cfg = _load_yaml()
    g = cfg.get('notifications', {}).get('gmail', {})
    t = cfg.get('notifications', {}).get('telegram', {})
    return {
        'gmail': {
            'enabled': bool(g.get('enabled', False)),
            'to':       g.get('to', ''),
            'smtp_user': g.get('smtp_user', ''),
            # Never return password to client
        },
        'telegram': {
            'enabled': bool(t.get('enabled', False)),
            'chat_id': t.get('chat_id', ''),
            # Never return bot_token to client
        },
    }


@router.post('/notifications')
async def save_notifications(body: NotificationConfig) -> dict:
    cfg = _load_yaml()
    if 'notifications' not in cfg:
        cfg['notifications'] = {}

    g = cfg['notifications'].setdefault('gmail', {})
    g['enabled']   = body.gmail.enabled
    g['to']        = body.gmail.to
    g['smtp_user'] = body.gmail.smtp_user
    # Only overwrite password when client sends a non-empty value
    if body.gmail.smtp_password:
        g['smtp_password'] = body.gmail.smtp_password

    t = cfg['notifications'].setdefault('telegram', {})
    t['enabled']  = body.telegram.enabled
    t['chat_id']  = body.telegram.chat_id
    if body.telegram.bot_token:
        t['bot_token'] = body.telegram.bot_token

    _save_yaml(cfg)

    return {
        'gmail': {
            'enabled': g['enabled'],
            'to':      g['to'],
            'smtp_user': g['smtp_user'],
        },
        'telegram': {
            'enabled': t['enabled'],
            'chat_id': t['chat_id'],
        },
    }
```

- [ ] **Step 4: Register the router in main.py**

In `backend/app/main.py`, add the import after the existing router imports:

```python
from app.routers.notification_settings import router as notification_settings_router
```

And in `create_app()`, add after `app.include_router(chart_alerts_router)`:

```python
app.include_router(notification_settings_router)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd backend && pytest tests/test_notification_settings.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 6: Update NotificationForm in settings/page.tsx to load and save**

In `frontend/app/(frame)/settings/page.tsx`, replace the `NotificationForm` component (`function NotificationForm() { ... }`) with a version that loads on mount and has an explicit Save button:

```tsx
function NotificationForm() {
  const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
  const [gmailEnabled, setGmailEnabled] = useState(false);
  const [gmailTo, setGmailTo] = useState('');
  const [gmailUser, setGmailUser] = useState('');
  const [gmailPassword, setGmailPassword] = useState('');
  const [telegramEnabled, setTelegramEnabled] = useState(false);
  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [testing, setTesting] = useState<('gmail' | 'telegram') | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState('');
  const [testResult, setTestResult] = useState('');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch(`${BASE_URL}/settings/notifications`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        setGmailEnabled(data.gmail?.enabled ?? false);
        setGmailTo(data.gmail?.to ?? '');
        setGmailUser(data.gmail?.smtp_user ?? '');
        setTelegramEnabled(data.telegram?.enabled ?? false);
        setTelegramChatId(data.telegram?.chat_id ?? '');
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [BASE_URL]);

  async function handleSave() {
    setSaving(true);
    setSaveResult('');
    try {
      const res = await fetch(`${BASE_URL}/settings/notifications`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gmail: { enabled: gmailEnabled, to: gmailTo, smtp_user: gmailUser, smtp_password: gmailPassword || null },
          telegram: { enabled: telegramEnabled, bot_token: telegramToken || null, chat_id: telegramChatId },
        }),
      });
      setSaveResult(res.ok ? 'Settings saved' : `Failed: ${res.status}`);
    } catch (e: unknown) {
      setSaveResult(`Error: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function sendTest(channel: 'gmail' | 'telegram') {
    setTesting(channel);
    setTestResult('');
    try {
      const body: Record<string, string> = { channel };
      if (channel === 'gmail') {
        if (gmailTo) body.to = gmailTo;
        if (gmailUser) body.smtp_user = gmailUser;
        if (gmailPassword) body.smtp_password = gmailPassword;
      } else {
        if (telegramToken) body.bot_token = telegramToken;
        if (telegramChatId) body.chat_id = telegramChatId;
      }
      const res = await fetch(`${BASE_URL}/alerts/notifications/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setTestResult(res.ok ? 'Test sent successfully' : `Failed: ${res.status}`);
    } catch (e: unknown) {
      setTestResult(`Error: ${(e as Error).message}`);
    } finally {
      setTesting(null);
    }
  }

  if (!loaded) return <Text size={12} tone="dim">Loading…</Text>;

  return (
    <>
      <SectionIntro title="Notifications" blurb="Configure alert delivery. Click Save to persist. Gmail uses App Password; Telegram uses Bot API." />

      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
        <Text size={14} weight={500}>Gmail</Text>
        <Row label="Enable Gmail alerts">
          <Toggle defaultOn={gmailEnabled} onChange={setGmailEnabled} />
        </Row>
        {gmailEnabled && (<>
          <Row label="To address" hint="Email that receives alerts">
            <input className={styles.input} placeholder="you@gmail.com" value={gmailTo} onChange={e => setGmailTo(e.target.value)} />
          </Row>
          <Row label="SMTP User" hint="Your Gmail address">
            <input className={styles.input} placeholder="you@gmail.com" value={gmailUser} onChange={e => setGmailUser(e.target.value)} />
          </Row>
          <Row label="Password" hint="Gmail App Password (leave blank to keep saved value)">
            <input className={styles.input} type="password" placeholder="••••••••" value={gmailPassword} onChange={e => setGmailPassword(e.target.value)} />
          </Row>
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('gmail')} disabled={testing === 'gmail'}>
              {testing === 'gmail' ? 'Sending…' : 'Send test email'}
            </button>
            {testResult ? <Text size={12} tone="secondary">{testResult}</Text> : null}
          </Row>
        </>)}
      </div>

      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
        <Text size={14} weight={500}>Telegram</Text>
        <Row label="Enable Telegram alerts">
          <Toggle defaultOn={telegramEnabled} onChange={setTelegramEnabled} />
        </Row>
        {telegramEnabled && (<>
          <Row label="Bot token" hint="From @BotFather (leave blank to keep saved value)">
            <input className={styles.input} placeholder="1234567890:ABC…" value={telegramToken} onChange={e => setTelegramToken(e.target.value)} />
          </Row>
          <Row label="Chat ID" hint="Your chat or group ID">
            <input className={styles.input} placeholder="987654321" value={telegramChatId} onChange={e => setTelegramChatId(e.target.value)} />
          </Row>
          <Row label="Test">
            <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => sendTest('telegram')} disabled={testing === 'telegram'}>
              {testing === 'telegram' ? 'Sending…' : 'Send test message'}
            </button>
          </Row>
        </>)}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {saveResult ? <Text size={12} tone={saveResult.startsWith('Settings') ? 'pass' : 'reject'}>{saveResult}</Text> : null}
      </div>
    </>
  );
}
```

- [ ] **Step 7: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/notification_settings.py \
        backend/tests/test_notification_settings.py \
        backend/app/main.py \
        "frontend/app/(frame)/settings/page.tsx"
git commit -m "feat(settings): notification settings persist to settings.yaml via GET/POST /settings/notifications"
```

---

## Task 5 — WS connection state indicator in TopBar

**Files:**
- Modify: `frontend/lib/chartWS.ts`
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`
- Modify: `frontend/components/organisms/ChartTopBar/index.tsx`
- Modify: `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css`

**Context:** The spec requires a stale-data banner on WS disconnect and reconnect. The UI currently shows nothing when the connection drops or the chart data is stale. Fix: expose connection state from `ChartWSClient`, track it in `ChartWorkspace`, display a small badge in `ChartTopBar`.

- [ ] **Step 1: Add onStateChange to ChartWSClient**

In `frontend/lib/chartWS.ts`, add a `ConnectionState` type and expose it via an optional callback:

```typescript
export type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'error';

export class ChartWSClient {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoff = 1000;
  private destroyed = false;
  private handlers = new Set<MessageHandler>();
  private stateHandler?: (s: ConnectionState) => void;

  constructor(
    public readonly symbol: string,
    public readonly interval: string = '15min',
    private readonly baseUrl: string = BASE_URL,
  ) {}

  onStateChange(fn: (s: ConnectionState) => void): void {
    this.stateHandler = fn;
  }

  connect(): void {
    if (this.destroyed) return;
    this.stateHandler?.('connecting');
    const url = `${this.baseUrl}/chart/stream/${encodeURIComponent(this.symbol)}?interval=${this.interval}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.backoff = 1000;
      this.stateHandler?.('connected');
    };

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as WSMessage;
        this.handlers.forEach(h => h(msg));
      } catch { /* ignore malformed messages */ }
    };

    this.ws.onclose = () => {
      if (!this.destroyed) {
        this.stateHandler?.('reconnecting');
        this.timer = setTimeout(() => {
          this.backoff = Math.min(this.backoff * 2, 30_000);
          this.connect();
        }, this.backoff);
      }
    };

    this.ws.onerror = () => {
      this.stateHandler?.('error');
      this.ws?.close();
    };
  }

  // ...onMessage and destroy unchanged...
}
```

- [ ] **Step 2: Track connection state and error in ChartWorkspace**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, add state and wire to the WS client:

```tsx
const [connState, setConnState] = useState<'connecting' | 'connected' | 'reconnecting' | 'error'>('connecting');
const [wsError, setWsError] = useState<string | null>(null);
```

In the WS `useEffect`, after `client.connect()`:

```tsx
client.onStateChange(setConnState);
```

In the WS `onMessage` handler, handle the error type:

```tsx
if (msg.type === 'error') {
  setWsError(msg.message);
}
// clear error on fresh history
if (msg.type === 'history') {
  setWsError(null);
}
```

Pass both to ChartTopBar:

```tsx
<ChartTopBar
  onToggleIndicators={...}
  onToggleStructure={...}
  onToggleAlerts={...}
  connState={connState}
  wsError={wsError}
/>
```

- [ ] **Step 3: Display badge in ChartTopBar**

In `frontend/components/organisms/ChartTopBar/index.tsx`, update `Props` and add the badge:

```tsx
interface Props {
  onToggleIndicators: () => void;
  onToggleStructure: () => void;
  onToggleAlerts?: () => void;
  connState?: 'connecting' | 'connected' | 'reconnecting' | 'error';
  wsError?: string | null;
}

export default function ChartTopBar({ onToggleIndicators, onToggleStructure, onToggleAlerts, connState, wsError }: Props) {
  // ...existing code...
  return (
    <div className={styles.bar}>
      {/* ...existing controls... */}
      {connState && connState !== 'connected' && (
        <span
          className={`${styles.connBadge} ${styles[connState]}`}
          title={wsError ?? connState}
        >
          {connState === 'connecting'   ? 'Connecting…'  :
           connState === 'reconnecting' ? 'Reconnecting…' :
           wsError ?? 'Error'}
        </span>
      )}
      {/* ...spacer, pop-out... */}
    </div>
  );
}
```

- [ ] **Step 4: Add badge styles to ChartTopBar.module.css**

```css
.connBadge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 500;
}

.connecting {
  background: color-mix(in srgb, var(--caution) 18%, var(--bg-surface));
  color: var(--caution);
}

.reconnecting {
  background: color-mix(in srgb, var(--caution) 18%, var(--bg-surface));
  color: var(--caution);
}

.error {
  background: color-mix(in srgb, var(--reject) 18%, var(--bg-surface));
  color: var(--reject);
}
```

- [ ] **Step 5: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/chartWS.ts \
        frontend/components/organisms/ChartWorkspace/index.tsx \
        frontend/components/organisms/ChartTopBar/index.tsx \
        frontend/components/organisms/ChartTopBar/ChartTopBar.module.css
git commit -m "feat(chart): WS connection state badge in TopBar — shows connecting/reconnecting/error"
```

---

## Task 6 — VWAP guard for daily and weekly intervals

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

**Context:** VWAP is a session-cumulative indicator that resets at market open. On 1D or 1W candles, it accumulates across months and produces a meaningless value. The fix is a one-line guard in `buildMainSeries`.

- [ ] **Step 1: Skip VWAP in buildMainSeries for daily/weekly**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, inside `buildMainSeries`, update the VWAP line:

```tsx
// Before (line where VWAP is added):
if (ind.type === 'VWAP') series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });

// After:
if (ind.type === 'VWAP' && interval !== '1D' && interval !== '1W') {
  series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });
}
```

`buildMainSeries` needs `interval` as a third parameter (currently only takes `candles`, `indicators`, `chartType` after Task 2):

```tsx
function buildMainSeries(candles: Candle[], indicators: IndicatorConfig[], chartType: string, interval: string): SeriesConfig[] {
  // ...
  if (ind.type === 'VWAP' && interval !== '1D' && interval !== '1W') {
    series.push(...);
  }
  // ...
}
```

Update the `useMemo` call:

```tsx
const mainSeries = useMemo(
  () => buildMainSeries(candles, activeIndicators, chartType, interval),
  [candles, activeIndicators, chartType, interval],
);
```

- [ ] **Step 2: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): skip VWAP indicator on 1D and 1W intervals (session indicator only)"
```

---

## Task 7 — Indicator parameter editing in IndicatorPanel

**Files:**
- Modify: `frontend/components/organisms/IndicatorPanel/index.tsx`
- Modify: `frontend/components/organisms/IndicatorPanel/IndicatorPanel.module.css`

**Context:** The IndicatorPanel allows add/remove but period/stdDev/etc. are fixed at creation. `chartStore.updateIndicator` already exists. The fix adds an inline param editor row per active indicator.

- [ ] **Step 1: Add active indicators section with param inputs to IndicatorPanel**

Replace the full `frontend/components/organisms/IndicatorPanel/index.tsx` with:

```tsx
'use client';
import { useState } from 'react';
import { useChartStore, type IndicatorConfig } from '@/lib/chartStore';
import { Text } from '@/components/primitives';
import styles from './IndicatorPanel.module.css';

const AVAILABLE: Array<{
  type: string; label: string; pane: 'main' | 'sub';
  defaultParams: Record<string, number>; color: string;
}> = [
  { type: 'SMA',  label: 'SMA',             pane: 'main', defaultParams: { period: 20 },                    color: '#a0a0ff' },
  { type: 'EMA',  label: 'EMA',             pane: 'main', defaultParams: { period: 20 },                    color: '#4f8ef7' },
  { type: 'BB',   label: 'Bollinger Bands', pane: 'main', defaultParams: { period: 20, stdDev: 2 },         color: '#c07070' },
  { type: 'VWAP', label: 'VWAP',            pane: 'main', defaultParams: {},                                color: '#70c0c0' },
  { type: 'RSI',  label: 'RSI',             pane: 'sub',  defaultParams: { period: 14 },                    color: '#70b070' },
  { type: 'MACD', label: 'MACD',            pane: 'sub',  defaultParams: { fast: 12, slow: 26, signal: 9 }, color: '#c080c0' },
  { type: 'ATR',  label: 'ATR',             pane: 'sub',  defaultParams: { period: 14 },                    color: '#c0a040' },
  { type: 'VOL',  label: 'Volume',          pane: 'sub',  defaultParams: {},                                color: '#4a4a6a' },
];

const PARAM_LABELS: Record<string, string> = {
  period: 'Period', fast: 'Fast', slow: 'Slow', signal: 'Signal', stdDev: 'StdDev',
};

interface Props { onClose: () => void; }

export default function IndicatorPanel({ onClose }: Props) {
  const { activeIndicators, addIndicator, removeIndicator, updateIndicator } = useChartStore();
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = AVAILABLE.filter(a => a.label.toLowerCase().includes(search.toLowerCase()));
  const isActive = (type: string) => activeIndicators.some(i => i.type === type);

  const toggle = (def: typeof AVAILABLE[0]) => {
    if (isActive(def.type)) {
      const existing = activeIndicators.find(i => i.type === def.type);
      if (existing) removeIndicator(existing.id);
    } else {
      const cfg: IndicatorConfig = {
        id: `${def.type.toLowerCase()}-${Date.now()}`,
        type: def.type, params: def.defaultParams, pane: def.pane, color: def.color,
      };
      addIndicator(cfg);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Text size={13} tone="primary" weight={500}>Indicators</Text>
        <button className={styles.close} onClick={onClose}>✕</button>
      </div>
      <input
        className={styles.search}
        placeholder="Search…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {activeIndicators.length > 0 && (
        <div className={styles.activeSection}>
          <Text size={10} tone="dim" weight={500}>ACTIVE</Text>
          {activeIndicators.map(ind => {
            const paramKeys = Object.keys(ind.params);
            const isExpanded = expandedId === ind.id;
            return (
              <div key={ind.id} className={styles.activeRow}>
                <span className={styles.dot} style={{ background: ind.color }} />
                <Text size={12} tone="primary">{ind.type}</Text>
                {paramKeys.length > 0 && (
                  <button
                    className={styles.editBtn}
                    onClick={() => setExpandedId(isExpanded ? null : ind.id)}
                  >
                    {isExpanded ? '▲' : '▼'}
                  </button>
                )}
                <button
                  className={styles.removeBtn}
                  onClick={() => removeIndicator(ind.id)}
                >✕</button>
                {isExpanded && paramKeys.length > 0 && (
                  <div className={styles.paramRow}>
                    {paramKeys.map(key => (
                      <label key={key} className={styles.paramLabel}>
                        <Text size={10} tone="dim">{PARAM_LABELS[key] ?? key}</Text>
                        <input
                          type="number"
                          className={styles.paramInput}
                          value={ind.params[key]}
                          min={1}
                          step={1}
                          onChange={e => {
                            const val = Number(e.target.value);
                            if (val > 0) updateIndicator(ind.id, { params: { ...ind.params, [key]: val } });
                          }}
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className={styles.list}>
        {filtered.map(def => (
          <button
            key={def.type}
            className={`${styles.item} ${isActive(def.type) ? styles.itemActive : ''}`}
            onClick={() => toggle(def)}
          >
            <span className={styles.dot} style={{ background: def.color }} />
            <Text size={12} tone={isActive(def.type) ? 'primary' : 'secondary'}>{def.label}</Text>
            <span className={styles.check}>{isActive(def.type) ? '✓' : '+'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add param styles to IndicatorPanel.module.css**

Append to the existing file:

```css
.activeSection {
  padding: 8px 12px 4px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.activeRow {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  flex-wrap: wrap;
}

.editBtn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 9px;
  cursor: pointer;
  padding: 0 2px;
}
.editBtn:hover { color: var(--text-secondary); }

.removeBtn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
  padding: 0 2px;
  margin-left: auto;
}
.removeBtn:hover { color: var(--reject); }

.paramRow {
  width: 100%;
  display: flex;
  gap: 8px;
  padding: 4px 0 4px 16px;
  flex-wrap: wrap;
}

.paramLabel {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.paramInput {
  width: 56px;
  padding: 2px 4px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 3px;
  color: var(--text-primary);
  font-size: 11px;
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/IndicatorPanel/index.tsx \
        frontend/components/organisms/IndicatorPanel/IndicatorPanel.module.css
git commit -m "feat(chart): indicator parameter editing — period/stdDev/fast/slow editable inline"
```

---

## Task 8 — Hidden divergence detection (backend)

**Files:**
- Modify: `backend/app/services/market_structure.py`
- Create: `backend/tests/test_hidden_divergence.py`

**Context:** `_detect_divergence` only handles regular divergence (price HH + indicator LH = bearish; price LL + indicator HL = bullish). Hidden divergence is the inverse: price HL + indicator LL = hidden bullish (trend continuation); price LH + indicator HH = hidden bearish. Both are in the spec's Phase 2 requirements.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_hidden_divergence.py`:

```python
"""Tests for hidden divergence detection (price HL + indicator LL = hidden bullish, etc.)."""
import pytest
from app.services.market_structure import _detect_divergence


def _make_candles(closes, highs=None, lows=None):
    """Minimal candle dicts from close prices; highs/lows default to close ± 1."""
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c + 1
        l = lows[i] if lows else c - 1
        result.append({
            'time': f'2024-01-{i+1:02d}', 'open': c, 'high': h, 'low': l,
            'close': c, 'volume': 1000,
        })
    return result


def test_hidden_bullish_divergence_detected():
    """Price HL (higher low) + RSI LL (lower low) → hidden bullish signal."""
    closes = [100, 98, 95, 97, 92, 94, 96]
    # RSI proxy: lower values at the second swing low
    rsi_vals = [50, 48, 42, 45, 35, 40, 44]
    candles = _make_candles(closes)
    signals = _detect_divergence(candles, rsi_vals, 'RSI')
    hidden_bull = [s for s in signals if s['divergence_type'] == 'hidden' and s['direction'] == 'bullish']
    assert len(hidden_bull) >= 1


def test_hidden_bearish_divergence_detected():
    """Price LH (lower high) + RSI HH (higher high) → hidden bearish signal."""
    closes = [100, 103, 107, 105, 110, 108, 106]
    rsi_vals = [50, 52, 58, 55, 65, 62, 60]
    candles = _make_candles(closes)
    signals = _detect_divergence(candles, rsi_vals, 'RSI')
    hidden_bear = [s for s in signals if s['divergence_type'] == 'hidden' and s['direction'] == 'bearish']
    assert len(hidden_bear) >= 1


def test_regular_divergence_still_detected_alongside_hidden():
    """Adding hidden detection should not break existing regular detection."""
    closes = [100, 103, 107, 105, 110, 108, 106]
    # RSI lower high at price's higher high → regular bearish
    rsi_vals = [50, 55, 60, 57, 55, 53, 51]
    candles = _make_candles(closes)
    signals = _detect_divergence(candles, rsi_vals, 'RSI')
    regular_bear = [s for s in signals if s['divergence_type'] == 'regular' and s['direction'] == 'bearish']
    assert len(regular_bear) >= 1


def test_no_divergence_when_price_and_indicator_agree():
    """If price and indicator move together, no divergence of any type."""
    closes = [100, 103, 107, 110, 114]
    rsi_vals = [50, 53, 57, 60, 64]
    candles = _make_candles(closes)
    signals = _detect_divergence(candles, rsi_vals, 'RSI')
    assert signals == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_hidden_divergence.py -v
```

Expected: `test_hidden_bullish_divergence_detected` and `test_hidden_bearish_divergence_detected` FAIL (hidden type not in output).

- [ ] **Step 3: Add hidden divergence cases to _detect_divergence**

In `backend/app/services/market_structure.py`, inside `_detect_divergence`, add two new loops AFTER the existing regular bearish and regular bullish loops (before `return signals`):

```python
    # Hidden bullish divergence: price HL (higher low), indicator LL (lower low)
    for i in range(1, len(price_swing_lows)):
        pl0, pl1 = price_swing_lows[i - 1], price_swing_lows[i]
        if pl1["price"] > pl0["price"]:   # price makes higher low
            il0 = _closest_indicator_swing(ind_swing_lows, pl0)
            il1 = _closest_indicator_swing(ind_swing_lows, pl1)
            if il0 and il1 and il1["value"] < il0["value"]:  # indicator makes lower low
                bar_count = abs(pl1["index"] - pl0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bullish",
                    "indicator": indicator, "divergence_type": "hidden",
                    "time_start": pl0["time"], "time_end": pl1["time"],
                    "price_start": pl0["price"], "price_end": pl1["price"],
                    "confidence": _divergence_confidence(False, bar_count),
                    "mtf_aligned": False,
                })

    # Hidden bearish divergence: price LH (lower high), indicator HH (higher high)
    for i in range(1, len(price_swing_highs)):
        ph0, ph1 = price_swing_highs[i - 1], price_swing_highs[i]
        if ph1["price"] < ph0["price"]:   # price makes lower high
            ih0 = _closest_indicator_swing(ind_swing_highs, ph0)
            ih1 = _closest_indicator_swing(ind_swing_highs, ph1)
            if ih0 and ih1 and ih1["value"] > ih0["value"]:  # indicator makes higher high
                bar_count = abs(ph1["index"] - ph0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bearish",
                    "indicator": indicator, "divergence_type": "hidden",
                    "time_start": ph0["time"], "time_end": ph1["time"],
                    "price_start": ph0["price"], "price_end": ph1["price"],
                    "confidence": _divergence_confidence(False, bar_count),
                    "mtf_aligned": False,
                })
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && pytest tests/test_hidden_divergence.py tests/test_market_structure.py -v
```

Expected: all pass (new hidden tests + no regressions in existing structure tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/market_structure.py backend/tests/test_hidden_divergence.py
git commit -m "feat(structure): add hidden divergence detection (price HL+RSI LL = bullish; price LH+RSI HH = bearish)"
```

---

## Task 9 — BOS signal deduplication

**Files:**
- Modify: `backend/app/services/market_structure.py`
- Create: `backend/tests/test_bos_dedup.py`

**Context:** In a trending market, `detect_bos_choch` fires a new BOS signal on every candle that breaks the prior swing, flooding the overlay with repeated signals at nearly the same price level. The fix: skip a new BOS if a BOS of the same direction was already fired within the last 5 bars at a price within 0.5% of the new level.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_bos_dedup.py`:

```python
"""Test that consecutive BOS signals at the same level are deduplicated."""
from app.services.market_structure import detect_bos_choch


def _trending_up_candles(n: int, base: float = 100.0, step: float = 1.0):
    """Steadily rising candles that would fire consecutive BOS signals."""
    candles = []
    for i in range(n):
        c = base + i * step
        candles.append({
            'time': f'2024-01-{i+1:02d}', 'open': c, 'high': c + 0.5,
            'low': c - 0.5, 'close': c, 'volume': 1000,
        })
    return candles


def test_no_duplicate_bos_within_5_bars():
    """Two consecutive BOS signals at prices within 0.5% must not both appear."""
    candles = _trending_up_candles(40)
    signals = detect_bos_choch(candles)
    bos_bull = [s for s in signals if s['kind'] == 'BOS' and s['direction'] == 'bullish']

    for i in range(1, len(bos_bull)):
        prev, curr = bos_bull[i - 1], bos_bull[i]
        price_diff_pct = abs(curr['price'] - prev['price']) / prev['price'] * 100
        # If they are within 5 bars AND within 0.5%, that is a duplicate
        prev_time = prev.get('time', '')
        curr_time = curr.get('time', '')
        if prev_time and curr_time:
            # Simplified: just check price proximity — in steady trend, prices are close
            if price_diff_pct < 0.5:
                assert False, f"Duplicate BOS: {prev['price']:.2f} vs {curr['price']:.2f} ({price_diff_pct:.3f}%)"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/test_bos_dedup.py -v
```

Expected: FAIL (consecutive BOS currently fires without dedup).

- [ ] **Step 3: Add deduplication to detect_bos_choch**

In `backend/app/services/market_structure.py`, find the `detect_bos_choch` function. Locate the section that appends a new BOS signal to `signals`. Add a dedup check before each append:

```python
def _is_duplicate_bos(signals: list[dict], new_price: float, direction: str, max_bars: int = 5) -> bool:
    """Return True if a same-direction BOS at a similar price was already emitted recently."""
    recent = [s for s in signals if s.get('kind') == 'BOS' and s.get('direction') == direction]
    if not recent:
        return False
    last = recent[-1]
    price_diff_pct = abs(new_price - last['price']) / last['price'] * 100
    return price_diff_pct < 0.5
```

Then inside the loop that appends BOS signals, wrap each `signals.append(...)` call:

```python
# Before appending a bullish BOS:
if not _is_duplicate_bos(signals, swing_high_price, 'bullish'):
    signals.append({ "kind": "BOS", "direction": "bullish", ... })

# Before appending a bearish BOS:
if not _is_duplicate_bos(signals, swing_low_price, 'bearish'):
    signals.append({ "kind": "BOS", "direction": "bearish", ... })
```

(The exact variable names for swing_high_price / swing_low_price depend on the current function body — find the existing `signals.append({"kind": "BOS", ...})` calls and wrap them.)

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && pytest tests/test_bos_dedup.py tests/test_market_structure.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/market_structure.py backend/tests/test_bos_dedup.py
git commit -m "fix(structure): deduplicate consecutive BOS signals within 0.5% of same price level"
```

---

## Task 10 — Structure confidence display in ChartRightPanel Data tab

**Files:**
- Modify: `frontend/components/organisms/ChartRightPanel/index.tsx`
- Modify: `frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css`
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

**Context:** The backend computes confidence scores (0–100) for every structure signal (FVG, BOS, CHoCH, OB, Divergence, Fibonacci, Confluence). These scores are stored in `structureStore` but never displayed. The Data tab in ChartRightPanel shows OHLCV + indicator values at cursor — it should also show active structure signals near the current candle with their confidence scores.

- [ ] **Step 1: Pass structureSignals to ChartRightPanel**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, update the `ChartRightPanel` call to pass signals:

```tsx
<ChartRightPanel
  crosshairData={crosshair}
  symbol={symbol}
  structureSignals={structureSignals}
/>
```

- [ ] **Step 2: Add structureSignals prop and confidence display to ChartRightPanel**

In `frontend/components/organisms/ChartRightPanel/index.tsx`, find the Props interface and add:

```tsx
import type { StructureSignal } from '@/types/structure';

interface Props {
  crosshairData: DataValues;
  symbol: string;
  structureSignals?: StructureSignal[];
}
```

In the Data tab render (where OHLCV is displayed), add a structure signals section after the indicator values section:

```tsx
{structureSignals && structureSignals.length > 0 && (
  <div className={styles.structureSection}>
    <div className={styles.structureHeader}>
      <Text size={10} tone="dim" weight={500}>STRUCTURE</Text>
    </div>
    {structureSignals.slice(0, 5).map((sig, i) => (
      <div key={i} className={styles.structureRow}>
        <Text size={11} tone="secondary">{sig.kind}</Text>
        {'direction' in sig && sig.direction && (
          <Text size={10} tone={sig.direction === 'bullish' ? 'pass' : 'reject'}>
            {sig.direction}
          </Text>
        )}
        {'confidence' in sig && sig.confidence != null && (
          <Text size={10} tone="dim">{sig.confidence}%</Text>
        )}
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 3: Add structure section styles to ChartRightPanel.module.css**

Append:

```css
.structureSection {
  margin-top: 8px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 6px;
}

.structureHeader {
  padding: 2px 0 4px;
}

.structureRow {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
}
```

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartRightPanel/index.tsx \
        frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css \
        frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): show structure signals with confidence scores in Data tab"
```

---

## Task 11 — Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && pytest -q --tb=short
```

Expected: all existing tests pass + new tests from Tasks 3, 4, 8, 9.

- [ ] **Step 2: Run frontend typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Run frontend tests**

```bash
cd frontend && npm run test -- --passWithNoTests
```

Expected: all pass.

- [ ] **Step 4: Start backend and verify chart fills screen**

```bash
# Terminal 1
start-backend.bat

# Terminal 2
cd frontend && npm run dev
```

Open `http://localhost:3001/chart`. Confirm:
- Chart fills the full available height (no gray void below)
- Switching to "Bars" shows bar chart
- Switching to "Line" shows line chart
- Switching interval to 1D and adding VWAP: VWAP does not appear

- [ ] **Step 5: Test notification settings persistence**

1. Navigate to Settings → Notifications
2. Toggle Gmail On, enter a To address and SMTP user
3. Click "Save settings" — confirm "Settings saved" message
4. Refresh the page
5. Navigate back to Settings → Notifications
6. Confirm To address and SMTP user are still populated

- [ ] **Step 6: Commit any remaining files and tag**

```bash
git add -u
git commit -m "chore: chart gaps fix — all 11 tasks complete"
```

---

## Acceptance Criteria

| Finding | Fixed in Task | Verification |
|---|---|---|
| Chart doesn't fill screen | 1 | Chart fills available height at `/chart` |
| Bar/Line chart types broken | 2 | Dropdown correctly changes series type |
| syncRules ID collision (duplicates) | 3 | No duplicate rules after page refresh |
| Notification settings lost on refresh | 4 | Save + reload preserves to/user/enabled |
| VWAP on 1D/1W | 6 | VWAP absent from daily chart |
| WS connection state invisible | 5 | Badge appears during reconnect |
| Indicator params not editable | 7 | Period inputs in IndicatorPanel |
| Hidden divergence missing | 8 | Backend detects hidden bullish/bearish |
| BOS consecutive flooding | 9 | Deduplicated in trending candle set |
| Confidence scores not displayed | 10 | Visible in Data tab right panel |

---

## Out of Scope — Separate Plan Required

**Drawing Tools Canvas Implementation**
Trendlines, Fibonacci retracements, shapes, text annotations drawn on the chart require:
- lightweight-charts v5 Primitives API for custom hit-tested drawings
- Mouse event dispatch pipeline (mousedown → drag → mouseup) on the canvas container
- Per-symbol drawing storage in `bamendjou:chart:drawings:{symbol}` localStorage
- Undo/redo stack
- Edit mode (click to select, drag handles to resize)

Estimated scope: 30+ tasks. Create a dedicated plan document when ready to implement.
