# Chart Phase 4 — Notifications & Backend Sync: Context Document

**Date:** 2026-05-27  
**Status:** Ready for implementation planning  
**Depends on:** Phase 1 (chart + WS), Phase 2 (market structure), Phase 3 (alert engine)  
**Branch to work from:** After Phase 3 is merged

---

## Overview

Phase 4 delivers two things:
1. **Notification delivery** — when an alert triggers, send a message via Gmail (SMTP) and/or Telegram (bot API)
2. **Backend persistence** — move alert rules and history from localStorage to PostgreSQL so they survive device switches and can be used for server-side evaluation

After Phase 4, alert rules are evaluated by the FastAPI backend on each candle-close (not just in the browser), which enables alerts to fire even when the user has the app closed.

---

## Phase 1–3 Foundation — What Already Exists

### Backend stack

```
FastAPI + Uvicorn | Pydantic v2 | SQLAlchemy v2 + Alembic | aiosqlite (dev) / AsyncPG (prod)
Config YAML: backend/config/*.yaml
Entry point: backend/app/main.py
Migrations: backend/migrations/ (Alembic)
```

### Existing WS infrastructure (Phase 1)

```python
# backend/app/routers/chart.py
WS /chart/stream/{symbol}?interval=...
# Sends: history → structure → tick (continuous)
# Backend already has the full candle stream; Phase 4 attaches server-side evaluation here
```

### Alert model (Phase 3, currently localStorage-only)

```typescript
// frontend/types/alerts.ts (already defined in Phase 3)
interface AlertRule {
  id: string; name: string; symbol: string; interval: Interval; enabled: boolean;
  group: ConditionGroup; cooldown_minutes: number; expiry_date: string | null;
  created_at: string; last_triggered_at: string | null;
}

interface AlertHistory {
  id: string; rule_id: string; symbol: string; interval: Interval;
  triggered_at: string; candle: Candle; trigger_values: Record<string, number>;
  reason: string;
}
```

### Phase 3 alert evaluation function (frontend, already implemented)

```typescript
// frontend/lib/alertEngine.ts
function evaluateRules(
  rules: AlertRule[], closedCandle: Candle, allCandles: Candle[],
  indicators: Record<string, Point[]>, signals: StructureSignal[], now: Date
): AlertHistory[]
```

### Phase 3 Zustand store (already implemented)

```typescript
// frontend/lib/chartAlertStore.ts
// Persisted to localStorage under 'bamendjou:alerts', version 1
interface AlertState {
  rules: AlertRule[]; history: AlertHistory[];
  addRule, updateRule, deleteRule, addHistory, clearHistory, dismissHistory
}
```

### Existing database migration pattern

Alembic migrations live in `backend/migrations/versions/`. Each file is named `{hash}_{slug}.py`. To create one:
```bash
cd backend && alembic revision --autogenerate -m "add alert tables"
```

### Styling conventions (mandatory)

- CSS Modules only, CSS token variables, atoms → organisms hierarchy
- See CLAUDE.md for full list of conventions

---

## Phase 4 Requirements

### 1. Database tables for alerts

Two new tables: `alert_rules` and `alert_history`.

**Alembic migration** (create via `alembic revision --autogenerate`):

```python
# backend/migrations/versions/xxxx_add_alert_tables.py
# Tables to create:

# alert_rules
# id          UUID primary key (use Python uuid4 as string for SQLite compat)
# user_id     VARCHAR(64) — placeholder for future auth; hardcode "default" for now
# name        VARCHAR(200) NOT NULL
# symbol      VARCHAR(10) NOT NULL
# interval    VARCHAR(10) NOT NULL
# enabled     BOOLEAN DEFAULT TRUE
# rule_json   TEXT NOT NULL   -- full AlertRule JSON (simpler than normalizing conditions)
# cooldown_minutes  INTEGER DEFAULT 60
# expiry_date TEXT NULL       -- ISO date string
# created_at  TEXT NOT NULL   -- ISO timestamp
# last_triggered_at TEXT NULL

# alert_history
# id              UUID primary key
# rule_id         VARCHAR(64) NOT NULL (FK → alert_rules.id, ON DELETE CASCADE)
# symbol          VARCHAR(10)
# interval        VARCHAR(10)
# triggered_at    TEXT NOT NULL
# candle_json     TEXT NOT NULL  -- Candle serialized as JSON
# trigger_values  TEXT NOT NULL  -- Record<string, number> as JSON
# reason          TEXT NOT NULL
```

**Why store rule_json as TEXT?** The condition tree (nested groups, typed conditions) maps poorly to relational tables without significant complexity. Storing the JSON avoids a 5-table join and matches the existing localStorage shape exactly, making migration trivial.

### 2. FastAPI alert CRUD endpoints

New router: `backend/app/routers/alerts.py`

```
POST   /alerts/rules                  → create rule (returns AlertRule with server-assigned id)
GET    /alerts/rules                  → list all rules for user_id="default"
GET    /alerts/rules/{id}             → get single rule
PUT    /alerts/rules/{id}             → full replace
PATCH  /alerts/rules/{id}            → partial update (enable/disable, last_triggered_at)
DELETE /alerts/rules/{id}            → delete rule + its history

GET    /alerts/history                → list history, query params: symbol, interval, limit (default 50)
DELETE /alerts/history/{id}          → dismiss single history entry
DELETE /alerts/history               → clear all history

POST   /alerts/rules/{id}/test        → dry-run evaluation against last 200 candles; returns matches without saving
```

All endpoints use Pydantic v2 models. Response shape mirrors the TypeScript types from Phase 3.

### 3. Backend alert evaluation service

`backend/app/services/alert_evaluator.py` — mirrors the frontend `alertEngine.ts` in Python. Evaluated on each candle-close on the backend.

```python
# Pydantic models matching the TypeScript types
class PriceCondition(BaseModel):
    kind: Literal['price']
    operator: Literal['>', '<', '>=', '<=', 'crosses_above', 'crosses_below']
    value: float

class IndicatorCondition(BaseModel):
    kind: Literal['indicator']
    indicator: str
    operator: Literal['>', '<', '>=', '<=', 'crosses_above', 'crosses_below']
    value: float

class StructureCondition(BaseModel):
    kind: Literal['structure']
    signal_kind: str   # 'FVG' | 'BOS' | 'CHoCH' | 'OrderBlock' | 'Divergence'
    direction: Optional[str] = None
    min_confidence: Optional[int] = None

class ConditionGroup(BaseModel):
    logic: Literal['AND', 'OR']
    conditions: list[Union[PriceCondition, IndicatorCondition, StructureCondition]]

class AlertRuleModel(BaseModel):
    id: str; name: str; symbol: str; interval: str; enabled: bool
    group: ConditionGroup; cooldown_minutes: int; expiry_date: Optional[str]
    created_at: str; last_triggered_at: Optional[str]


async def evaluate_rules_for_symbol(
    symbol: str,
    interval: str,
    closed_candle: dict,
    all_candles: list[dict],
    signals: list[dict],
    db: AsyncSession,
) -> list[dict]:
    """
    Load enabled rules for this symbol+interval from DB.
    Evaluate each rule against the closed candle.
    For triggered rules:
      - insert AlertHistory row
      - update AlertRule.last_triggered_at
      - enqueue notification (Gmail + Telegram) if configured
    Returns list of triggered AlertHistory dicts.
    """
```

This function is called from `backend/app/routers/chart.py` after each candle-close (same point where Phase 2 sends the `structure` message):

```python
# In WS /chart/stream/{symbol} handler, after sending structure message:
if new_candle_detected:
    triggered = await evaluate_rules_for_symbol(symbol, interval, closed_candle, candles, signals, db)
    for t in triggered:
        await websocket.send_json({"type": "alert_triggered", "entry": t})
```

### 4. New WS message type: `alert_triggered`

Add to the WS protocol (extend `WSMessage` in `frontend/lib/chartWS.ts`):

```typescript
{ type: 'alert_triggered'; entry: AlertHistory }
```

Frontend `ChartWorkspace` already handles `alert_triggered` by dispatching to `chartAlertStore` (Phase 3 added this for browser-side triggers; Phase 4 routes backend triggers through the same path).

### 5. Gmail notification

`backend/app/services/notifications/gmail.py`:

```python
import smtplib
from email.mime.text import MIMEText

async def send_gmail(
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
) -> None:
    """Send plain-text email via SMTP. Runs in asyncio.to_thread to avoid blocking."""
    def _send():
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = to
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    await asyncio.to_thread(_send)
```

**Message template:**
```
Subject: Bamendjou Alert — AAPL [1D]
Body:
  Symbol:    AAPL
  Interval:  1D
  Time:      2024-01-03 16:00:00
  Trigger:   RSI(14) crossed below 30 AND BOS bullish detected
  Values:    RSI(14)=28.4  close=182.50  EMA(20)=183.10
  Rule:      "Oversold + Structure" (id: abc-123)
```

**Configuration** — stored in `backend/config/settings.yaml` (already used by the app):

```yaml
notifications:
  gmail:
    enabled: false
    to: ""
    smtp_host: "smtp.gmail.com"
    smtp_port: 465
    smtp_user: ""
    smtp_password: ""   # use App Password for Gmail 2FA accounts
```

**Settings page integration:** The existing `frontend/app/(frame)/settings/page.tsx` has sub-nav for Alerts. Add a "Notifications" section there with fields for Gmail to/from and Telegram bot token/chat ID. These settings are saved via `PATCH /settings` (check if this endpoint exists; if not, add a minimal one that writes to `backend/config/settings.yaml`).

### 6. Telegram notification

`backend/app/services/notifications/telegram.py`:

```python
import httpx

TELEGRAM_API = "https://api.telegram.org"

async def send_telegram(
    bot_token: str,
    chat_id: str,           # can be a user chat ID or a group chat ID (prefixed with -)
    text: str,
) -> None:
    """Send message via Telegram Bot API. Uses httpx async."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
```

**Message template (Telegram HTML):**
```
<b>Bamendjou Alert</b> — AAPL [1D]

<b>Trigger:</b> RSI(14) crossed below 30 AND BOS bullish
<b>Time:</b> 2024-01-03 16:00
<b>Values:</b> RSI=28.4 · close=182.50 · EMA20=183.10
<b>Rule:</b> Oversold + Structure
```

**Configuration:**
```yaml
notifications:
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""            # single target; send to both personal + group by listing both comma-separated
```

### 7. Frontend sync — migrate localStorage → backend

Phase 3 used `localStorage` exclusively. Phase 4 makes the API the source of truth, with localStorage as a read-through cache.

**Migration strategy (bump chartAlertStore version):**

```typescript
// lib/chartAlertStore.ts — version bump from 1 → 2
// On first load with version 2, if localStorage has version-1 data:
//   1. POST each rule to /alerts/rules
//   2. POST each history entry to /alerts/history  
//   3. Clear old localStorage data
//   4. Write version 2 marker

// After migration, all writes go to API first, then update local state on success
// Reads come from API on mount, then cached in Zustand state
```

**New API calls in chartAlertStore.ts:**

```typescript
// Add to ChartState:
syncRules: () => Promise<void>;     // GET /alerts/rules → replace local state
pushRule: (rule: AlertRule) => Promise<void>;   // POST/PUT /alerts/rules/{id}
deleteRule: (id: string) => Promise<void>;      // DELETE /alerts/rules/{id}
```

**Conflict resolution:** API wins. If a rule exists in localStorage that isn't in the DB, push it. If a rule exists in DB that isn't in localStorage, pull it. Last-write-wins for updates (use `created_at` as tiebreaker).

### 8. Settings page additions

Extend `frontend/app/(frame)/settings/page.tsx` — existing Alerts sub-tab. Add a "Notifications" card with:

```
Notifications
  Gmail
    [ ] Enable Gmail alerts
    To address: [________________]
    SMTP User:  [________________]
    Password:   [••••••••••••••••] (type=password)
    [Send test email]
    
  Telegram
    [ ] Enable Telegram alerts
    Bot token:  [________________]
    Chat ID:    [________________]
    [Send test message]
```

On "Send test email" / "Send test message": call `POST /alerts/notifications/test` with the notification type. Backend sends a test message using the currently saved config.

---

## Architecture

### Complete notification flow (Phase 4)

```
Candle closes in Tradier stream
        │
        ▼
FastAPI chart.py — detects new candle
        │
        ├── compute_structure(candles) → signals
        ├── send {"type": "structure", ...} over WS
        │
        ├── evaluate_rules_for_symbol(symbol, interval, closed_candle, candles, signals, db)
        │       │
        │       ├── load rules from DB (only enabled, not expired, past cooldown)
        │       ├── evaluate each rule
        │       └── for each triggered rule:
        │             ├── insert AlertHistory to DB
        │             ├── update rule.last_triggered_at in DB
        │             └── enqueue notification task
        │
        ├── send {"type": "alert_triggered", "entry": {...}} over WS (for each triggered)
        │
        └── [background] notification_queue.put(notification_task)
                │
                └── notification worker (asyncio.Task):
                      ├── send_gmail() if enabled
                      └── send_telegram() if enabled

Frontend receives {"type": "alert_triggered"}
        │
        ├── chartAlertStore.addHistory(entry)
        └── show toast
```

### Notification queue

Use a simple `asyncio.Queue` singleton in `backend/app/services/notifications/queue.py` — same pattern as `TradierStreamClient`. A background task drains the queue and dispatches notifications, so failures (SMTP timeout, Telegram rate-limit) don't block the WS handler.

```python
_NOTIFY_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=500)

async def enqueue(task: dict) -> None:
    try:
        _NOTIFY_QUEUE.put_nowait(task)
    except asyncio.QueueFull:
        logger.warning("Notification queue full; dropping: %s", task)

async def worker() -> None:
    """Started once on app startup via lifespan."""
    while True:
        task = await _NOTIFY_QUEUE.get()
        try:
            if task['channel'] == 'gmail':
                await send_gmail(**task['params'])
            elif task['channel'] == 'telegram':
                await send_telegram(**task['params'])
        except Exception as exc:
            logger.error("Notification failed: %s", exc)
```

Start `worker()` in `backend/app/main.py` lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(notification_worker())
    yield
```

---

## New Backend Files

```
backend/
  app/
    routers/
      alerts.py                    # CRUD + history endpoints
    services/
      alert_evaluator.py           # Python mirror of alertEngine.ts
      notifications/
        __init__.py
        gmail.py                   # SMTP sender
        telegram.py                # Bot API sender
        queue.py                   # asyncio.Queue + worker
  migrations/
    versions/
      xxxx_add_alert_tables.py     # Alembic: alert_rules + alert_history
  tests/
    test_alert_evaluator.py        # Unit tests for Python evaluation logic
    test_alert_router.py           # CRUD endpoint tests
    test_notifications.py          # Mock SMTP + Telegram send
```

## Modified Backend Files

| File | Change |
|---|---|
| `backend/app/main.py` | Register `alerts` router; start notification worker in lifespan |
| `backend/app/routers/chart.py` | Call `evaluate_rules_for_symbol` on candle-close; send `alert_triggered` WS message |
| `backend/config/settings.yaml` | Add `notifications.gmail` and `notifications.telegram` blocks |

## New Frontend Files

```
frontend/
  lib/
    api.ts (extend)                # Add alert CRUD fetch wrappers if api.ts already exists
```

## Modified Frontend Files

| File | Change |
|---|---|
| `frontend/lib/chartAlertStore.ts` | Version 2 migration; add API sync methods |
| `frontend/lib/chartWS.ts` | Add `alert_triggered` to WSMessage union |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Handle `alert_triggered` WS message |
| `frontend/app/(frame)/settings/page.tsx` | Add Notifications card to Alerts sub-tab |

---

## Tests Required

### Backend

`backend/tests/test_alert_evaluator.py` (Python mirrors of Phase 3 JS tests):
- `test_price_condition_triggers`
- `test_crosses_above_triggers_only_on_crossing_candle`
- `test_cooldown_blocks_retrigger`
- `test_expired_rule_skipped`
- `test_structure_condition_matches_signal`
- `test_and_logic_all_must_pass`
- `test_or_logic_one_sufficient`

`backend/tests/test_alert_router.py`:
- `test_create_rule` — POST creates rule, GET returns it
- `test_update_rule` — PUT replaces rule
- `test_delete_rule_cascades_history` — history entries deleted with rule
- `test_list_history_filtered_by_symbol`

`backend/tests/test_notifications.py` (mocked, no real SMTP/Telegram calls):
- `test_gmail_send_called_with_correct_params`
- `test_telegram_send_called_with_correct_params`
- `test_queue_drops_when_full_not_raises`

### Frontend

- `npm run typecheck` — zero errors required (WSMessage union is extended, chartAlertStore version bump)

---

## Configuration Reference

All secrets are stored as environment variables, not in `settings.yaml`. The YAML only stores non-secret config:

```
BAMENDJOU_GMAIL_USER=xxx@gmail.com
BAMENDJOU_GMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx    # App Password
BAMENDJOU_GMAIL_RECIPIENT=xxx@gmail.com
BAMENDJOU_TELEGRAM_BOT_TOKEN=1234567890:xxx
BAMENDJOU_TELEGRAM_CHAT_ID=987654321
```

Read these in `backend/app/services/notifications/gmail.py` and `telegram.py` via `os.getenv()`. The settings page writes to these env vars via a secure update mechanism (or writes a `.env` file if running locally).

---

## Out of Scope (Phase 4)

- Multi-user authentication / per-user alert isolation (placeholder `user_id="default"`)
- Push notifications (browser/mobile) — would require service workers
- Webhook delivery
- Backtesting historical alerts against OHLCV data
- Alert rule versioning / audit trail
- Rate limiting on notification delivery (beyond cooldown already in Phase 3)

---

## Acceptance Criteria

1. `POST /alerts/rules` creates a rule persisted in the database (not just localStorage)
2. On candle-close, backend evaluates rules and sends `alert_triggered` WS message when triggered
3. Frontend receives `alert_triggered` and shows the history entry in ChartRightPanel Alerts tab
4. If Gmail is configured and enabled, a plain-text email is sent within 10s of the alert triggering
5. If Telegram is configured and enabled, a Telegram message is delivered within 10s
6. "Send test email" button in Settings sends an immediate test message
7. Existing Phase 3 localStorage rules are migrated to the database on first load with v2 store
8. After migration, localStorage is cleared and all reads/writes go to the API
9. `npm run typecheck` passes with zero errors
10. All new backend tests pass; no regressions in existing test suite
