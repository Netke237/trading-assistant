# Codebase Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 11 issues found in the June 2026 codebase audit — credentials leak, dual config systems, hardcoded risk threshold, silent errors, stale docs, and housekeeping items.

**Architecture:** Three independent workstreams: (P1) security — untrack secrets from git and read them from env vars instead; (P2) risk math — wire `premium_stop_pct` from `risk_rules.yaml` through a new API endpoint to both the backend reward/risk calculator and the frontend alert engine; (P3) housekeeping — silent errors, dead fields, stale docs, indicator comments, orphaned files.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / PyYAML · Next.js 15 App Router / TypeScript 5.7 / Zustand v5 / Jest

> ⚠ **Do P1 first and immediately** — live credentials are in the working tree.

---

## ─── P1 · Security ─────────────────────────────────────

### Task 1: Rotate the exposed credentials (MANUAL — no code)

**Why:** The Gmail app password and Telegram bot token currently in
`backend/config/settings.yaml` must be revoked before anything else. Until
they are revoked, they could be used by anyone who has a copy of the file.

**Files:** none — this is done entirely in browser/Telegram.

- [ ] **Step 1: Revoke Gmail app password**
  1. Go to <https://myaccount.google.com/apppasswords> (sign in as `lenetke@googlemail.com`).
  2. Find the app password that matches `eahv twsc qdjh naop` and delete it.
  3. Click "Create" → choose "Mail" / "Windows Computer" → copy the new 16-char password.
  4. Keep it in a safe place — you will paste it into `.env` in the next task.

- [ ] **Step 2: Revoke Telegram bot token**
  1. Open Telegram, search for `@BotFather`.
  2. Send `/revoke`, select the bot whose token starts with `8971314092:`.
  3. BotFather replies with a new token. Copy it.

---

### Task 2: Move secrets to `.env`, untrack `settings.yaml`

**Files:**
- Modify: `.env` (add five keys)
- Modify: `.env.example` (add five placeholder keys)
- Modify: `.gitignore` (add `backend/config/settings.yaml`)
- Create: `backend/config/settings.example.yaml`
- Modify: `backend/app/services/notifications/dispatch.py` (stop passing secrets to send functions)
- Modify: `backend/app/routers/notification_settings.py` (stop writing secrets to yaml)

**How it works after this task:**
- `settings.yaml` is gitignored — it still exists locally and the UI can still write to it, but git never sees it.
- `smtp_password` and `bot_token` are read from env vars by `gmail.py` / `telegram.py` (those fallbacks already exist — `os.getenv('BAMENDJOU_GMAIL_PASSWORD')` etc.).
- `dispatch.py` stops passing the secrets from yaml to the send functions (empty string → env var fallback triggers automatically).

- [ ] **Step 1: Add secret keys to `.env`**

  Open `.env` at the repo root and append:
  ```
  BAMENDJOU_GMAIL_USER=lenetke@googlemail.com
  BAMENDJOU_GMAIL_PASSWORD=<paste new app password from Task 1>
  BAMENDJOU_GMAIL_TO=bamendjou237@gmail.com
  BAMENDJOU_TELEGRAM_BOT_TOKEN=<paste new token from Task 1>
  BAMENDJOU_TELEGRAM_CHAT_ID=1521006537
  ```

- [ ] **Step 2: Add placeholder keys to `.env.example`**

  Open `.env.example` and append:
  ```
  # Notification credentials — set these manually, never commit real values
  BAMENDJOU_GMAIL_USER=
  BAMENDJOU_GMAIL_PASSWORD=
  BAMENDJOU_GMAIL_TO=
  BAMENDJOU_TELEGRAM_BOT_TOKEN=
  BAMENDJOU_TELEGRAM_CHAT_ID=
  ```

- [ ] **Step 3: Add `settings.yaml` to `.gitignore`**

  In `.gitignore`, add after the `backend/audit.log` line:
  ```
  backend/config/settings.yaml
  ```

- [ ] **Step 4: Create `backend/config/settings.example.yaml`**

  Create this new file (it IS tracked — it's the template with no real values):
  ```yaml
  # Copy this to settings.yaml and fill in non-secret values.
  # Secrets (passwords, tokens) live in .env — do NOT put them here.

  notifications:
    gmail:
      enabled: false
      smtp_host: smtp.gmail.com
      smtp_port: 465
    telegram:
      enabled: false

  scan:
    cadence_minutes: 60

  alert_delivery:
    masterEnabled: true
    enabledTypes:
      - TP_HIT
      - STOP_REACHED
      - PREMIUM_STOP
      - TIME_STOP
      - EVENT_RISK
      - REGIME_CHANGE
    dedupWindowMinutes: 15
    reminderIntervalHours: 4
    retentionDays: 30

  ibkr:
    enabled: true
    base_url: https://localhost:5000/v1/api
  ```

- [ ] **Step 5: Untrack `settings.yaml` from git**

  ```bash
  git rm --cached backend/config/settings.yaml
  ```

  Expected output:
  ```
  rm 'backend/config/settings.yaml'
  ```
  The file will still exist on disk — git just stops tracking it.

- [ ] **Step 6: Update `dispatch.py` — stop passing secrets from yaml**

  In `backend/app/services/notifications/dispatch.py`, replace the
  `notify_enabled_channels` function body with:

  ```python
  def notify_enabled_channels(subject: str, plain_body: str, html_body: str) -> None:
      """Dispatch to each channel that is enabled in settings.yaml.

      Credentials (smtp_password, bot_token) are intentionally NOT read from
      settings.yaml — they live in env vars (BAMENDJOU_GMAIL_PASSWORD,
      BAMENDJOU_TELEGRAM_BOT_TOKEN) and gmail.py / telegram.py pick them up
      automatically when the argument is empty string.
      """
      cfg = load_notification_config()
      gmail = cfg.get('gmail', {})
      tg = cfg.get('telegram', {})

      if gmail.get('enabled'):
          dispatch('gmail',
              _subject=subject,
              to=gmail.get('to', '') or os.getenv('BAMENDJOU_GMAIL_TO', ''),
              subject=subject,
              body=plain_body,
              smtp_user=gmail.get('smtp_user', '') or os.getenv('BAMENDJOU_GMAIL_USER', ''),
              smtp_password='',  # empty → gmail.py falls back to BAMENDJOU_GMAIL_PASSWORD env var
          )

      if tg.get('enabled'):
          dispatch('telegram',
              _subject=subject,
              bot_token='',      # empty → telegram.py falls back to BAMENDJOU_TELEGRAM_BOT_TOKEN
              chat_id=tg.get('chat_id', '') or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', ''),
              text=html_body,
          )
  ```

  Also add `import os` at the top of the file (after the existing imports).

- [ ] **Step 7: Update `notification_settings.py` — stop writing secrets to yaml**

  In `backend/app/routers/notification_settings.py`, replace the
  `save_notifications` function body with:

  ```python
  @router.post('/notifications')
  async def save_notifications(body: NotificationConfig) -> dict:
      cfg = _load_yaml()
      if 'notifications' not in cfg:
          cfg['notifications'] = {}

      g = cfg['notifications'].setdefault('gmail', {})
      g['enabled']   = body.gmail.enabled
      g['to']        = body.gmail.to
      g['smtp_user'] = body.gmail.smtp_user
      # smtp_password intentionally NOT written to yaml — lives in .env only.
      # Silently ignore any password sent by the client.

      t = cfg['notifications'].setdefault('telegram', {})
      t['enabled']  = body.telegram.enabled
      t['chat_id']  = body.telegram.chat_id
      # bot_token intentionally NOT written to yaml — lives in .env only.

      _save_yaml(cfg)

      return {
          'gmail': {
              'enabled':   g['enabled'],
              'to':        g['to'],
              'smtp_user': g['smtp_user'],
          },
          'telegram': {
              'enabled': t['enabled'],
              'chat_id': t['chat_id'],
          },
      }
  ```

- [ ] **Step 8: Verify notifications still work**

  Start the backend and send a test notification via the Settings UI. Check the
  backend logs — you should see `Email delivered to bamendjou237@gmail.com` and
  `Telegram message delivered to chat 1521006537`.

  If you see `Gmail not configured; skipping send`, the env vars are not being
  read. Confirm `.env` has the five new keys and that Uvicorn loads the `.env`
  file (it uses `pydantic-settings` for `Settings`, but the notification path
  uses raw `os.getenv` — Uvicorn does NOT auto-load `.env`). Fix by adding this
  to `start-backend.bat` or the terminal command:
  ```
  uvicorn app.main:app --env-file ../.env ...
  ```
  Or load `.env` explicitly at startup in `main.py`:
  ```python
  from dotenv import load_dotenv
  load_dotenv()  # at the top of main.py, before any imports that call os.getenv
  ```

- [ ] **Step 9: Commit**

  ```bash
  git add .gitignore .env.example backend/config/settings.example.yaml \
          backend/app/services/notifications/dispatch.py \
          backend/app/routers/notification_settings.py
  git commit -m "security: move notification secrets to env vars, untrack settings.yaml"
  ```

---

## ─── P2 · Risk Math ─────────────────────────────────────

### Task 3: Backend — new `/settings/risk` endpoint

This adds a GET/POST endpoint so the frontend can read and update
`premium_stop_pct` (and the other risk limits) from `risk_rules.yaml`.

**Files:**
- Create: `backend/app/routers/risk_settings.py`
- Modify: `backend/app/main.py` (register new router)
- Create: `backend/tests/test_risk_settings.py`

- [ ] **Step 1: Write the failing test**

  Create `backend/tests/test_risk_settings.py`:
  ```python
  """Tests for GET/POST /settings/risk."""
  import pytest
  from httpx import AsyncClient, ASGITransport
  from app.main import app


  @pytest.mark.asyncio
  async def test_get_risk_settings_returns_premium_stop():
      async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
          resp = await ac.get('/api/settings/risk')
      assert resp.status_code == 200
      data = resp.json()
      assert 'premiumStopPct' in data
      assert isinstance(data['premiumStopPct'], float)
      assert 0.0 < data['premiumStopPct'] <= 1.0


  @pytest.mark.asyncio
  async def test_post_risk_settings_updates_premium_stop(tmp_path, monkeypatch):
      # Point the router at a temp yaml so we don't mutate the real config.
      import backend.app.routers.risk_settings as rs
      fake_yaml = tmp_path / 'risk_rules.yaml'
      fake_yaml.write_text(
          'portfolio:\n  max_concurrent_positions: 10\n'
          'reward_risk:\n  premium_stop_pct: 0.60\n'
      )
      monkeypatch.setattr(rs, '_RISK_PATH', fake_yaml)

      async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
          resp = await ac.post('/api/settings/risk', json={'premiumStopPct': 0.50})
      assert resp.status_code == 200
      assert resp.json()['premiumStopPct'] == 0.50
  ```

- [ ] **Step 2: Run test — expect FAIL (router not yet created)**

  ```bash
  cd backend && pytest tests/test_risk_settings.py -v
  ```
  Expected: `FAILED — ImportError` or 404.

- [ ] **Step 3: Create `backend/app/routers/risk_settings.py`**

  ```python
  """GET/POST /settings/risk — read and persist premium_stop_pct from risk_rules.yaml."""
  from __future__ import annotations

  from pathlib import Path

  import yaml
  from fastapi import APIRouter, HTTPException
  from pydantic import BaseModel, Field

  router = APIRouter(prefix='/settings', tags=['settings'])

  _RISK_PATH = Path(__file__).parent.parent.parent / 'config' / 'risk_rules.yaml'


  def _load_risk() -> dict:
      if _RISK_PATH.exists():
          with open(_RISK_PATH) as f:
              return yaml.safe_load(f) or {}
      return {}


  def _save_risk(data: dict) -> None:
      _RISK_PATH.parent.mkdir(parents=True, exist_ok=True)
      with open(_RISK_PATH, 'w') as f:
          yaml.dump(data, f, default_flow_style=False, sort_keys=False)


  class RiskConfig(BaseModel):
      premiumStopPct: float = Field(default=0.60, ge=0.10, le=1.0,
                                    description='Stop out when option loses this fraction of premium (0.60 = 60% loss)')


  @router.get('/risk')
  async def get_risk_settings() -> dict:
      cfg = _load_risk()
      rr = cfg.get('reward_risk', {})
      return {'premiumStopPct': float(rr.get('premium_stop_pct', 0.60))}


  @router.post('/risk')
  async def save_risk_settings(body: RiskConfig) -> dict:
      cfg = _load_risk()
      if 'reward_risk' not in cfg:
          cfg['reward_risk'] = {}
      cfg['reward_risk']['premium_stop_pct'] = body.premiumStopPct
      _save_risk(cfg)
      return {'premiumStopPct': body.premiumStopPct}
  ```

- [ ] **Step 4: Register the router in `backend/app/main.py`**

  Find where the other routers are included (look for `app.include_router`) and
  add:
  ```python
  from app.routers.risk_settings import router as risk_settings_router
  app.include_router(risk_settings_router, prefix='/api')
  ```

- [ ] **Step 5: Run tests — expect PASS**

  ```bash
  cd backend && pytest tests/test_risk_settings.py -v
  ```
  Expected: `2 passed`.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/routers/risk_settings.py backend/app/main.py \
          backend/tests/test_risk_settings.py
  git commit -m "feat(settings): add GET/POST /settings/risk endpoint for premium_stop_pct"
  ```

---

### Task 4: Backend — align `reward_risk.py` to use `premium_stop_pct`

Currently `risk = current_premium` (assumes 100% loss). Change it to
`risk = current_premium * premium_stop_pct` so reward/risk ratios reflect the
actual stop rule from `risk_rules.yaml`.

**Files:**
- Modify: `backend/app/scoring/reward_risk.py`
- Modify: `backend/tests/test_reward_risk.py`

- [ ] **Step 1: Write the failing test**

  Open `backend/tests/test_reward_risk.py` and add this test:
  ```python
  def test_estimate_rr_uses_premium_stop_pct():
      """risk should equal premium * premium_stop_pct, not full premium."""
      from app.scoring.reward_risk import estimate_rr
      result = estimate_rr(
          stock_price=100.0,
          target_price=108.0,
          invalidation_price=97.0,
          strike=100.0,
          expiry_years=0.25,
          current_premium=2.00,
          is_call=True,
          premium_stop_pct=0.60,
      )
      # risk = 2.00 * 0.60 = 1.20; reward = exit_premium - 2.00
      # At minimum, rr_ratio > 0 and risk basis is 1.20 not 2.00
      assert result.rr_ratio > 0
      # With delta-approx: exit_premium = 2.00 + 0.5 * (108-100) = 6.00
      # reward = 6.00 - 2.00 = 4.00; risk = 1.20; rr = 4.00/1.20 ≈ 3.33
      assert abs(result.rr_ratio - round(4.00 / 1.20, 2)) < 0.01
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd backend && pytest tests/test_reward_risk.py::test_estimate_rr_uses_premium_stop_pct -v
  ```
  Expected: `FAILED — TypeError` (unexpected argument `premium_stop_pct`).

- [ ] **Step 3: Update `backend/app/scoring/reward_risk.py`**

  Add `premium_stop_pct: float = 0.60` as a parameter to `estimate_rr` and
  change the risk line:

  ```python
  def estimate_rr(
      stock_price: float,
      target_price: float,
      invalidation_price: float,
      strike: float,
      expiry_years: float,
      current_premium: float,
      is_call: bool,
      r: float = 0.05,
      heston_params: HestonParams | None = None,
      sigma_fallback: float = 0.25,
      premium_stop_pct: float = 0.60,   # ← new parameter
  ) -> RrResult:
  ```

  Then replace the two lines:
  ```python
  risk = current_premium
  reward = exit_premium - current_premium
  ```
  with:
  ```python
  risk = current_premium * premium_stop_pct   # only risk the stop-loss fraction
  reward = exit_premium - current_premium
  ```

  Also update the same default in `estimate_targets` — add the same parameter and
  pass it through:
  ```python
  def estimate_targets(
      ...
      premium_stop_pct: float = 0.60,   # ← new parameter
  ) -> list:
  ```
  And in the `rr` line inside the loop:
  ```python
  risk = current_premium * premium_stop_pct
  rr = round(reward / risk, 2) if risk > 0 and reward > 0 else 0.0
  ```

- [ ] **Step 4: Run tests — expect PASS**

  ```bash
  cd backend && pytest tests/test_reward_risk.py -v
  ```
  Expected: all reward_risk tests pass.

- [ ] **Step 5: Make callers of `estimate_rr` / `estimate_targets` pass `premium_stop_pct`**

  Find every call site:
  ```bash
  grep -rn "estimate_rr\|estimate_targets" backend/app --include=*.py
  ```
  For each call site, load the risk config and pass the value:
  ```python
  from app.scoring.reward_risk import estimate_rr
  import yaml
  from pathlib import Path

  def _load_premium_stop() -> float:
      path = Path(__file__).parent.parent.parent / 'config' / 'risk_rules.yaml'
      try:
          cfg = yaml.safe_load(path.read_text()) or {}
          return float(cfg.get('reward_risk', {}).get('premium_stop_pct', 0.60))
      except Exception:
          return 0.60

  # then in the call:
  result = estimate_rr(..., premium_stop_pct=_load_premium_stop())
  ```

- [ ] **Step 6: Run full backend test suite**

  ```bash
  cd backend && pytest -x -q
  ```
  Expected: all tests pass.

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/scoring/reward_risk.py backend/tests/test_reward_risk.py
  git commit -m "fix(scoring): use premium_stop_pct from risk_rules.yaml in reward/risk ratio"
  ```

---

### Task 5: Frontend — add `premiumStopPct` to `settingsStore`

**Files:**
- Modify: `frontend/lib/settingsStore.ts`

- [ ] **Step 1: Write the failing test**

  Open `frontend/lib/__tests__/` and create `settingsStore.test.ts` or add to the
  existing one:
  ```typescript
  import { useSettingsStore } from '@/lib/settingsStore';

  describe('settingsStore — premiumStopPct', () => {
    it('defaults to 0.60', () => {
      const state = useSettingsStore.getState();
      expect(state.premiumStopPct).toBe(0.60);
    });

    it('setPremiumStopPct updates the value', () => {
      useSettingsStore.getState().setPremiumStopPct(0.50);
      expect(useSettingsStore.getState().premiumStopPct).toBe(0.50);
      // reset
      useSettingsStore.getState().setPremiumStopPct(0.60);
    });
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd frontend && npm run test -- --testPathPattern=settingsStore
  ```
  Expected: `FAILED — premiumStopPct is undefined`.

- [ ] **Step 3: Update `frontend/lib/settingsStore.ts`**

  Add `premiumStopPct` to `SettingsState` interface:
  ```typescript
  interface SettingsState {
    // ... existing fields ...
    premiumStopPct:          number;   // fraction of premium risked at stop (0.60 = 60%)
    // ... existing setters ...
    setPremiumStopPct:       (n: number) => void;
  }
  ```

  Add the default and setter inside `create`:
  ```typescript
  premiumStopPct: 0.60,
  setPremiumStopPct: (n) => set({ premiumStopPct: n }),
  ```

  Add it to `resetToDefaults`:
  ```typescript
  resetToDefaults: () => set({
    // ... existing fields ...
    premiumStopPct: 0.60,
  }),
  ```

  Add it to `partialize`:
  ```typescript
  partialize: (state) => ({
    // ... existing fields ...
    premiumStopPct: state.premiumStopPct,
  }),
  ```

  Bump the version number from `9` to `10` and add a migration branch:
  ```typescript
  version: 10,
  migrate: (persistedState, version) => {
    const prev = (persistedState ?? {}) as Partial<SettingsState>;
    // ... existing branches ...
    if (version < 10) {
      return { ...prev, premiumStopPct: 0.60 } as unknown as SettingsState;
    }
    return prev as unknown as SettingsState;
  },
  ```

- [ ] **Step 4: Run test — expect PASS**

  ```bash
  cd frontend && npm run test -- --testPathPattern=settingsStore
  ```
  Expected: all tests pass.

- [ ] **Step 5: Typecheck**

  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: 0 errors.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/lib/settingsStore.ts
  git commit -m "feat(settings): add premiumStopPct field to settingsStore (default 0.60)"
  ```

---

### Task 6: Frontend — make PREMIUM_STOP threshold configurable

Currently `alertEngine.ts` fires `PREMIUM_STOP` at `pnlPct <= -40` (hardcoded).
Align it to `premiumStopPct`: a value of 0.60 means "loses 60% of premium",
so the threshold is `pnlPct <= -60`.

**Files:**
- Modify: `frontend/lib/alertEngine.ts`
- Modify: `frontend/lib/__tests__/alertEngine.test.ts`

- [ ] **Step 1: Update the existing PREMIUM_STOP test to use the new signature**

  Open `frontend/lib/__tests__/alertEngine.test.ts`. Find the test that checks
  `PREMIUM_STOP` and update it to:
  ```typescript
  it('fires PREMIUM_STOP when pnlPct crosses the stop threshold', () => {
    const pos = makePosition({ pnlPct: -65 });
    const results = scanPortfolio([pos], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(true);
  });

  it('does NOT fire PREMIUM_STOP when loss is below threshold', () => {
    const pos = makePosition({ pnlPct: -50 });
    const results = scanPortfolio([pos], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd frontend && npm run test -- --testPathPattern=alertEngine
  ```
  Expected: `FAILED — scanPortfolio does not accept second argument`.

- [ ] **Step 3: Update `frontend/lib/alertEngine.ts`**

  Add an options parameter to `scanPortfolio` and use it for the threshold:

  ```typescript
  export interface ScanOptions {
    premiumStopPct?: number;  // fraction of premium lost at stop; default 0.60
  }

  export function scanPortfolio(
    positions: AlertPosition[],
    options: ScanOptions = {},
  ): AlertReason[] {
    const premiumStopPct = options.premiumStopPct ?? 0.60;
    const premiumStopThreshold = -(premiumStopPct * 100);  // e.g. -60 for 0.60
    const out: AlertReason[] = [];

    for (const p of positions) {
      // TP_HIT
      const firstTarget = p.targets[0];
      if (firstTarget && p.currentPrice >= firstTarget.stockPrice) {
        out.push({
          recId: p.recId,
          kind: 'Action',
          symbol: p.symbol,
          alertType: 'TP_HIT',
          reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
        });
      }

      // STOP_REACHED
      if (p.currentPrice <= p.stop) {
        out.push({
          recId: p.recId,
          kind: 'Critical',
          symbol: p.symbol,
          alertType: 'STOP_REACHED',
          reason: `Stop breached — ${p.symbol} below $${p.stop.toFixed(2)}`,
        });
      }

      // PREMIUM_STOP — configurable via premiumStopPct
      if (p.pnlPct <= premiumStopThreshold) {
        out.push({
          recId: p.recId,
          kind: 'Critical',
          symbol: p.symbol,
          alertType: 'PREMIUM_STOP',
          reason: `Premium stop — ${p.symbol} down ${p.pnlPct.toFixed(1)}%`,
        });
      }

      // TIME_STOP — expiry within 3 days
      if (p.dteRemaining <= 3) {
        out.push({
          recId: p.recId,
          kind: 'Action',
          symbol: p.symbol,
          alertType: 'TIME_STOP',
          reason: `Time stop — ${p.symbol} ${p.dteRemaining} DTE`,
        });
      }

      // EVENT_RISK
      if (p.nextEventDays != null && p.nextEventDays <= 3) {
        out.push({
          recId: p.recId,
          kind: 'Action',
          symbol: p.symbol,
          alertType: 'EVENT_RISK',
          reason: `${p.nextEventLabel ?? 'Event'} in ${p.nextEventDays} days — ${p.symbol}`,
        });
      }
    }

    return out;
  }
  ```

- [ ] **Step 4: Find callers of `scanPortfolio` and pass `premiumStopPct` from the store**

  ```bash
  grep -rn "scanPortfolio" frontend --include="*.ts" --include="*.tsx"
  ```

  For each call site, pull `premiumStopPct` from `useSettingsStore`:
  ```typescript
  const premiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  // ...
  scanPortfolio(positions, { premiumStopPct })
  ```

- [ ] **Step 5: Run tests — expect PASS**

  ```bash
  cd frontend && npm run test -- --testPathPattern=alertEngine
  ```
  Expected: all pass.

- [ ] **Step 6: Typecheck**

  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: 0 errors.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/lib/alertEngine.ts frontend/lib/__tests__/alertEngine.test.ts
  git commit -m "fix(alerts): make PREMIUM_STOP threshold configurable via premiumStopPct"
  ```

---

### Task 7: Frontend — wire `premiumStopPct` to the backend + add Settings UI field

On mount, the Settings page fetches the current value from the backend. Saving
the Settings form PUTs it back. Also adds a number input to the Alerts/Risk
panel so Kenneth can change it from the UI.

**Files:**
- Modify: `frontend/lib/api.ts` (add getRiskSettings / saveRiskSettings)
- Modify: `frontend/app/(frame)/settings/` — risk/alerts panel (exact file path — run `find frontend/app -name "*.tsx" | xargs grep -l "premiumStop\|risk.*limit\|ivPass" | head`)

- [ ] **Step 1: Add API helpers to `frontend/lib/api.ts`**

  Append to `api.ts`:
  ```typescript
  export interface RiskSettings {
    premiumStopPct: number;
  }

  export async function getRiskSettings(): Promise<RiskSettings> {
    const res = await fetch('/api/settings/risk');
    if (!res.ok) throw new Error('Failed to load risk settings');
    return res.json();
  }

  export async function saveRiskSettings(s: RiskSettings): Promise<void> {
    const res = await fetch('/api/settings/risk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(s),
    });
    if (!res.ok) throw new Error('Failed to save risk settings');
  }
  ```

- [ ] **Step 2: Locate the settings panel that shows risk/IV thresholds**

  ```bash
  grep -rln "ivPassThreshold\|maxConcurrentPositions\|RiskLimit" frontend/app
  ```

  Open that file. Add a `premiumStopPct` input alongside the existing risk inputs.
  The pattern to follow (based on how `ivPassThreshold` is already rendered):

  ```tsx
  // At the top of the component, pull from the store:
  const { premiumStopPct, setPremiumStopPct } = useSettingsStore();

  // In useEffect (or wherever the component fetches settings on mount):
  getRiskSettings().then(s => setPremiumStopPct(s.premiumStopPct)).catch(() => {});

  // In the save handler:
  await saveRiskSettings({ premiumStopPct });

  // In the JSX — next to the other risk threshold fields:
  <label>
    <Text size={13} tone="secondary" weight={400}>Premium stop loss</Text>
    <input
      type="number"
      min={0.10}
      max={1.0}
      step={0.05}
      value={premiumStopPct}
      onChange={e => setPremiumStopPct(Number(e.target.value))}
    />
    <Text size={11} tone="dim">Fraction of premium lost before stop fires (default 0.60 = 60%)</Text>
  </label>
  ```

- [ ] **Step 3: Typecheck**

  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: 0 errors.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/lib/api.ts frontend/app/\(frame\)/settings/
  git commit -m "feat(settings): wire premiumStopPct to backend API and add UI input"
  ```

---

## ─── P3 · Housekeeping ─────────────────────────────────

### Task 8: Fix silent API errors in QuickLook and InlineChartPanel

**Files:**
- Modify: `frontend/components/organisms/ContextRail/QuickLook.tsx`
- Modify: `frontend/components/organisms/InlineChartPanel/index.tsx`

- [ ] **Step 1: Fix `QuickLook.tsx`**

  Find line 28:
  ```typescript
  api.getWatchlist().then(setWatchlist).catch(() => {});
  ```
  Replace with:
  ```typescript
  api.getWatchlist()
    .then(setWatchlist)
    .catch(() => setWatchlistError(true));
  ```

  Add the error state declaration near the top of the component:
  ```typescript
  const [watchlistError, setWatchlistError] = useState(false);
  ```

  In the JSX, where the watchlist renders, add a fallback:
  ```tsx
  {watchlistError && (
    <Text size={12} tone="dim">Could not load watchlist</Text>
  )}
  ```

- [ ] **Step 2: Fix `InlineChartPanel/index.tsx`**

  Find line 32:
  ```typescript
  api.getCandles(symbol).then(setCandles).catch(() => {});
  ```
  Replace with:
  ```typescript
  api.getCandles(symbol)
    .then(setCandles)
    .catch(() => setCandleError(true));
  ```

  Add state:
  ```typescript
  const [candleError, setCandleError] = useState(false);
  ```

  Reset on symbol change (add to the dependency-reset block):
  ```typescript
  useEffect(() => {
    setCandleError(false);
  }, [symbol]);
  ```

  In JSX:
  ```tsx
  {candleError && (
    <Text size={12} tone="dim">Chart unavailable</Text>
  )}
  ```

- [ ] **Step 3: Typecheck**

  ```bash
  cd frontend && npm run typecheck
  ```
  Expected: 0 errors.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/components/organisms/ContextRail/QuickLook.tsx \
          frontend/components/organisms/InlineChartPanel/index.tsx
  git commit -m "fix(ui): surface API errors in QuickLook and InlineChartPanel"
  ```

---

### Task 9: Fix dead `oi_score` field in `ContractScoreBreakdown`

Currently `oi_score` is always set to `0`. Populate it from the OI calculation
that already happens inside `_score_liquidity`.

**Files:**
- Modify: `backend/app/scoring/contract_validator.py`
- Modify: `backend/tests/test_contracts_scoring.py`

- [ ] **Step 1: Write the failing test**

  In `backend/tests/test_contracts_scoring.py`, add:
  ```python
  def test_oi_score_is_populated():
      contract = {
          'symbol': 'AAPL', 'strike': 185.0, 'expiry': '2025-09-19',
          'is_call': True, 'bid': 3.50, 'ask': 3.60,
          'delta': 0.45, 'volume': 500, 'open_interest': 2000,
      }
      card = validate_contract(contract, stock_score=70)
      assert card.breakdown.oi_score > 0, 'oi_score should reflect open interest'
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd backend && pytest tests/test_contracts_scoring.py::test_oi_score_is_populated -v
  ```
  Expected: `FAILED — AssertionError: oi_score should reflect open interest`.

- [ ] **Step 3: Update `_score_liquidity` to return oi_score separately**

  In `backend/app/scoring/contract_validator.py`, change `_score_liquidity` to
  also return `oi_score`:

  ```python
  def _score_liquidity(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
      """Returns (liquidity_score, oi_score, flags)."""
      sr = cfg["soft_rank"]
      flags = []
      volume = contract.get("volume") or 0
      oi = contract.get("open_interest") or 0

      vol_score = min(100, int(volume / sr["preferred_volume_min"] * 60))
      oi_score = min(100, int(oi / sr["preferred_oi_min"] * 60))
      score = (vol_score + oi_score) // 2

      if volume < sr["preferred_volume_min"]:
          flags.append("low_volume")
      if oi < sr["preferred_oi_min"]:
          flags.append("low_open_interest")
      return score, oi_score, flags
  ```

  Update the call site inside `validate_contract`:
  ```python
  liq_score, oi_score_val, liq_flags = _score_liquidity(contract, cfg)
  ```

  Update both `ContractScoreBreakdown` constructions (REJECT path and PASS path)
  to use `oi_score=oi_score_val` instead of `oi_score=0`.

- [ ] **Step 4: Run tests — expect PASS**

  ```bash
  cd backend && pytest tests/test_contracts_scoring.py -v
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/scoring/contract_validator.py backend/tests/test_contracts_scoring.py
  git commit -m "fix(scoring): populate oi_score in ContractScoreBreakdown (was always 0)"
  ```

---

### Task 10: Update `CLAUDE.md` to match current codebase

**Files:**
- Modify: `CLAUDE.md` (project root)

- [ ] **Step 1: Remove the mocks section**

  Find the `## Mocks (\`mocks/\`)` section listing `watchlist.ts`, `contracts.ts`,
  etc. Delete the entire section — the folder no longer exists and data comes
  from the backend via `frontend/lib/api.ts`.

- [ ] **Step 2: Update the stack table "Data" row**

  Find:
  ```
  | Data | Deterministic mocks in `mocks/` — no backend yet |
  ```
  Replace with:
  ```
  | Data | FastAPI backend via `frontend/lib/api.ts`; Jest mocks in `frontend/__mocks__/` |
  ```

- [ ] **Step 3: Update the folder layout section**

  Remove `mocks/` from the folder tree comment block.

- [ ] **Step 4: Add `premiumStopPct` to the Zustand stores table**

  Find the stores table and add a row:
  ```
  | `riskStore.ts` + `settingsStore.ts` | `premiumStopPct` — stop-loss fraction, default 0.60; configurable in Settings |
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add CLAUDE.md
  git commit -m "docs(claude): remove stale mocks references, reflect connected backend"
  ```

---

### Task 11: Document the intentional indicator split

There are two indicator files that both compute RSI/MACD:
- `frontend/lib/indicators.ts` — used by alert engine and chart overlays
- `frontend/lib/chart/indicators.ts` — used only by `CandlestickChart` (lightweight-charts native series)

**Files:**
- Modify: `frontend/lib/indicators.ts`
- Modify: `frontend/lib/chart/indicators.ts`

- [ ] **Step 1: Add a header comment to `frontend/lib/indicators.ts`**

  Insert at line 1:
  ```typescript
  /**
   * Core indicator library — RSI, MACD, SMA, EMA, BB, ATR, VWAP.
   *
   * Used by: alertEngine.ts, chartAlertEngine.ts, ChartPane, ChartWorkspace.
   *
   * NOTE: A second indicator file exists at lib/chart/indicators.ts.
   * That file formats data for lightweight-charts CandlestickChart's native
   * histogram/line series (different output shape). It is intentionally
   * separate. If you change RSI/MACD logic here, review chart/indicators.ts too.
   */
  ```

- [ ] **Step 2: Add a header comment to `frontend/lib/chart/indicators.ts`**

  Insert at line 1:
  ```typescript
  /**
   * Chart-specific indicator adapters for lightweight-charts (CandlestickChart).
   *
   * Output shape differs from lib/indicators.ts: values are formatted as
   * lightweight-charts HistogramData / LineData. Do NOT use in alertEngine.
   *
   * NOTE: Core logic lives in lib/indicators.ts. If you change RSI/MACD math
   * there, sync the equivalent here or add a shared pure-function extraction.
   */
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/lib/indicators.ts frontend/lib/chart/indicators.ts
  git commit -m "docs(indicators): clarify intentional split between lib/indicators and lib/chart/indicators"
  ```

---

### Task 12: Remove orphaned root `config/settings.yaml`

**Files:**
- Delete: `config/settings.yaml`
- Delete (or keep empty): `config/` directory

- [ ] **Step 1: Verify nothing loads it**

  ```bash
  grep -rn "config/settings" backend/app --include=*.py | grep -v "parent.parent.parent"
  ```
  Expected: no output (only the backend path is used).

- [ ] **Step 2: Delete the file**

  ```bash
  git rm config/settings.yaml
  ```

- [ ] **Step 3: Run backend tests to confirm nothing broke**

  ```bash
  cd backend && pytest -x -q
  ```
  Expected: all pass.

- [ ] **Step 4: Commit**

  ```bash
  git commit -m "chore: remove orphaned root config/settings.yaml (unused)"
  ```

---

### Task 13: Untrack `dev.db` and clean repo root clutter

**Files:**
- Untrack: `dev.db`
- Move: loose `.docx` and `.png` files from repo root → `docs/` or a new `assets/` folder

- [ ] **Step 1: Untrack `dev.db`**

  ```bash
  git rm --cached dev.db
  ```
  Confirm `.gitignore` already has `*.db` (it does).

- [ ] **Step 2: Move loose files**

  ```bash
  mkdir -p docs/assets
  git mv "1 Which API Provides Market news.docx" docs/assets/
  git mv "change and corrections.docx" docs/assets/
  git mv "change and corrections_2.docx" docs/assets/
  git mv "change and corrections_3.docx" docs/assets/
  git mv "Graph feedback.docx" docs/assets/
  git mv "grpah integration bamendjou.docx" docs/assets/
  git mv "grpah_copy.docx" docs/assets/
  git mv tradingview-alert.png docs/assets/
  git mv tradingview-alerts-clean.png docs/assets/
  git mv tradingview-alerts-panel.png docs/assets/
  git mv tradingview-chart.png docs/assets/
  git mv "tradingview-chart-url.png" docs/assets/
  git mv tradingview-indicators.png docs/assets/
  git mv tradingview-indicators2.png docs/assets/
  ```

- [ ] **Step 3: Commit**

  ```bash
  git commit -m "chore: untrack dev.db, move loose docs and screenshots to docs/assets/"
  ```

---

## Self-Review

**Spec coverage check:**
| Finding | Task |
|---|---|
| #1 Live secrets in tracked file | Task 1 (rotate) + Task 2 (untrack + env) |
| #2 Two config systems | Task 2 (consolidate secrets to env) |
| #3 Silent errors | Task 8 |
| #4 Stale CLAUDE.md | Task 10 |
| #5 Duplicate indicator files | Task 11 |
| #6 Risk math mismatch | Tasks 3 + 4 + 5 + 6 + 7 |
| #7 Duplicate migration names | Not tasked — migrations work and renaming risks db state (LOW) |
| #8 Dead oi_score field | Task 9 |
| #9 Redundant targetPrice/stockPrice | Not tasked — both fields consumed by different consumers; removing one is a multi-file breaking change tagged LOW |
| #10 Orphaned root config | Task 12 |
| #11 dev.db tracked + root clutter | Task 13 |

> Item #7 (migration names) and #9 (TargetLevel redundancy) are intentionally left as documentation findings. Acting on them risks breaking migration state or breaking schema consumers for no user-visible benefit.

**Placeholder scan:** No TBD/TODO/fill-in-details present.

**Type consistency:** `premiumStopPct: number` used consistently in Task 5 (store), Task 6 (alertEngine), Task 7 (api.ts + UI). `RiskConfig.premiumStopPct` (backend, Task 3) matches `RiskSettings.premiumStopPct` (frontend api.ts, Task 7).
