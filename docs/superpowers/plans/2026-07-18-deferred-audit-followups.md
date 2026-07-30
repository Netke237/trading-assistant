# Deferred Audit Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the three items explicitly deferred across this session's two prior adversarial audit loops (portfolio single-source-of-truth, composite chart-alert cooldown), plus one bug surfaced but not yet fixed during the tastytrade test-environment investigation.

**Architecture:** Three independent, unrelated fixes — no shared code, safe to implement and verify in any order:
1. **ChartWorkspace local error surface** (frontend): a rejected quick-buy from the chart-click "buy" popover currently has no visible feedback on the standalone chart page (`/chart/standalone`), which sits outside the frame layout where the Portfolio page's rejection banner lives. `ChartWorkspace` already renders `<AlertToast />` (backed by `useChartAlertStore`'s `pushToast`) for chart-alert notifications — reuse that existing, already-tested mechanism instead of building a new UI surface.
2. **Rename `_is_cooldown_passed` → `is_cooldown_passed`** (backend): the composite-rule cooldown fix made this function genuinely cross-module shared API (`chart_alerts.py` imports it from `alert_evaluator.py`), but it still carries a leading-underscore "module-private" name. Rename it and update both call sites.
3. **Fix two mis-passing tests in `test_market_data_fixes.py`** (backend): both tests exercise the "IBKR unavailable" IV-enrichment path but never mock the newer `fetch_iv_metrics_tastytrade` fallback call added alongside it — so they only passed, in environments lacking the `tastytrade` package, because the unmocked import failed and was silently swallowed. In this repo's actual `.venv` (which has `tastytrade` installed), the real call executes, returns non-zero IV, and the assertions the tests exist to make (verifying the *next* fallback layer, yfinance) never get exercised. Add the missing mock.

**Tech Stack:** Next.js 15 + TypeScript + Zustand (frontend, item 1); FastAPI + Python (backend, items 2–3, pytest/pytest-asyncio). Backend tests MUST run via `backend/.venv/Scripts/python.exe -m pytest` — a bare `python` on this machine resolves to an unrelated global install without `tastytrade` and other project dependencies installed, which caused a false "7 failing tests" reading earlier this session.

**Provenance — where each item was deferred (verified against the live repo, not memory):**
- Item 1: flagged in the portfolio single-source-of-truth diff-audit round 1 ("ChartWorkspace's justification for `void addPosition(...)` is only half true... `ChartWorkspace` is also mounted at `frontend/app/chart/standalone/page.tsx`, which sits entirely outside the `(frame)` layout tree — a rejected chart-click 'buy' there has literally no path to ever show the banner"), re-confirmed in round 2, deliberately left as a documented comment rather than fixed at the time.
- Item 2: flagged in the composite-alert-cooldown diff-audit round 1 ("this is now a genuine cross-module contract... but the underscore prefix still signals 'module-private'... worth a rename"), explicitly deferred as "a separate refactor outside this bug's scope."
- Item 3: found live during the "why are 7 tests failing" investigation (commit `ea748f4`, 2026-07-12, added the tastytrade IV fallback to both `fetch_option_chain` and `fetch_option_chain_async` without updating these two pre-existing tests); offered to the user as a fix, not yet actioned.

---

## Branch setup (do this first)

- [ ] **Step 0: Create a working branch off a clean `main`**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant"
git status --short          # see what's here before branching
git checkout main
git pull --ff-only origin main
git checkout -b fix/deferred-audit-followups
```
Expected: branches from a clean, up-to-date `main` — `Switched to a new branch 'fix/deferred-audit-followups'`. `git status --short` showing only pre-existing UNTRACKED files (e.g. stray docs, `.docx`/`.zip` files, other plan `.md` files not part of this work) is fine and does not block anything — `git checkout -b` carries untracked files forward harmlessly. The check is only to catch unrelated **tracked/modified** files (an `M` prefix) that would mean someone else's in-progress work is sitting in the tree — if you see any `M` lines, stop and ask before proceeding rather than branching over them.

---

## Task 1: Surface a rejected chart-click buy locally, everywhere ChartWorkspace is mounted

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx` (the `buy` `ChartClickPopover`'s `onConfirm`, currently around `:821-833`)

**Why no new automated test:** `ChartWorkspace` has no existing test harness (`components/organisms/ChartWorkspace/__tests__/` does not exist — confirmed empty) — it depends on chart libraries, a WebSocket client, and multiple stores that would need substantial mocking infrastructure to render in isolation. The change itself adds no new logic: it calls `pushToast()`, an action on `useChartAlertStore` that already has direct unit coverage (`frontend/lib/__tests__/chartAlertStore.test.ts:189`, "pushToast adds a toast and dismissToast removes it"). This task is verified live in the browser instead (Step 3below), which is the appropriate level of rigor for a two-line UI-wiring change with a real, visible runtime surface and no pre-existing test seam to hook into.

- [ ] **Step 1: Read the current code to confirm the exact insertion point**

Run: `grep -n "onConfirm" "frontend/components/organisms/ChartWorkspace/index.tsx"` and locate the `buy` popover's block (currently `:821-835`):

```tsx
      {clickPopover && clickPopover.kind === 'buy' && (
        <ChartClickPopover
          kind="buy"
          price={clickPopover.price}
          qty={buyQty}
          onQty={setBuyQty}
          onCancel={() => setClickPopover(null)}
          onConfirm={() => {
            // Fire-and-forget: a rejection surfaces via the Portfolio page's
            // lastSyncError banner (this popover has no dedicated error slot).
            void usePortfolioStore.getState().addPosition(buildPaperStockPosition(symbol, clickPopover.price, buyQty));
            setClickPopover(null);
          }}
        />
      )}
```

- [ ] **Step 2: Surface the rejection via the existing chart toast mechanism**

Replace the `onConfirm` handler with:

```tsx
          onConfirm={() => {
            const price = clickPopover.price;
            const qty = buyQty;
            void usePortfolioStore.getState().addPosition(buildPaperStockPosition(symbol, price, qty)).then((res) => {
              if (res.status === 'rejected') {
                useChartAlertStore.getState().pushToast({
                  id: `add-position-rejected-${rid()}`,
                  message: `${symbol} was not saved: ${res.detail ?? 'rejected by the backend'}`,
                  timestamp: Date.now(),
                });
              }
            });
            setClickPopover(null);
          }}
```

`clickPopover.price` and `buyQty` are captured into local `const`s before `setClickPopover(null)` runs, because `clickPopover` is set to `null` synchronously right after — the `.then()` callback closing over `clickPopover.price` directly would still work (closures capture the variable's value at closure-creation time, not by live reference to state), but capturing into named locals makes that explicit and avoids any confusion for a future reader about whether the popover's price could have "changed out from under" the pending promise. `useChartAlertStore` is already imported in this file (`:16`); `pushToast`'s signature (`{ id: string; message: string; timestamp: number }`) matches the existing call site at `:384-388` in the same file.

The toast `id` uses `rid()`, not a bare `Date.now()` — the two existing `pushToast` call sites in this file (`:384-388`, `:433-437`) use backend-issued, guaranteed-unique domain ids (`msg.entry.id`), not a wall-clock timestamp, so neither is a template to copy directly. `dismissToast` removes *every* toast sharing an `id`, and `AlertToast` auto-dismisses each toast 5 seconds after it renders — two rejections landing in the same millisecond with a bare-`Date.now()`-based id would collide and the first one's dismiss timer would silently remove both. `rid()` (`ChartWorkspace/index.tsx:156`, `Date.now().toString(36) + Math.random().toString(36).slice(2, 6)`) is already a module-level helper in this exact file, used 6× for drawing ids — reuse it rather than introducing a new id-generation pattern (e.g. `crypto.randomUUID()`) into a file that already has a working one.

- [ ] **Step 3: Verify live in the browser**

Start the dev server and open the standalone chart page (this is the page that previously had NO error path at all):

```bash
cd frontend && npm run dev
```

Then, using the Browser pane:
1. Navigate to `http://localhost:3001/chart/standalone?symbol=AAPL` — the `?symbol=` query param is read via `useSearchParams` (`ChartWorkspace/index.tsx:159,236-238`) and picks up the symbol on mount.
2. In the `DrawingToolbar` (left side of the chart), click the **"Paper buy"** tool (the `＄` icon — `components/organisms/DrawingToolbar/index.tsx:32`, `id: 'buy'`). This sets `drawingTool = 'buy'`.
3. Left-click anywhere on the chart. This hits `if (drawingTool === 'buy') { setClickPopover({ kind: 'buy', price, time }); return; }` (`ChartWorkspace/index.tsx:677`) and opens the buy popover at that clicked price.
4. In the popover, confirm the buy at a price/qty combination you expect the backend to reject (e.g., an oversized quantity that blows the exposure cap — check current `riskStore` limits first, or temporarily lower `portfolioValue` in Settings to force a rejection deterministically).
5. Confirm a toast appears in the standalone page showing "`<symbol>` was not saved: `<reason>`" and auto-dismisses after 5 seconds (matching `AlertToast`'s existing dismiss timer).
6. Repeat on the embedded chart (mounted inside the normal `(frame)` layout at `app/(frame)/chart/page.tsx`) to confirm no regression there.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): surface a rejected quick-buy on the standalone chart page

The standalone chart page (/chart/standalone) sits outside the (frame)
layout, so it had no path to the Portfolio page's rejection banner — a
rejected chart-click buy failed completely silently there. Reuses the
chart's existing toast mechanism (already used for chart-alert
notifications) instead of building a new UI surface."
```

---

## Task 2: Rename `_is_cooldown_passed` to a public name

**Files:**
- Modify: `backend/app/services/alert_evaluator.py` (definition `:75`, internal call `:348`)
- Modify: `backend/app/routers/chart_alerts.py` (import `:23`, call `:668`, and the two comment mentions at `:654,:667`)
- No test files reference this function by name directly (verified: `grep -rn "_is_cooldown_passed" backend/tests` returns no matches) — no test changes needed for the rename itself.

- [ ] **Step 1: Rename the definition**

In `backend/app/services/alert_evaluator.py`, change:

```python
def _is_cooldown_passed(rule: AlertRuleInput, now: datetime) -> bool:
```
to:
```python
def is_cooldown_passed(rule: AlertRuleInput, now: datetime) -> bool:
```

(The comment immediately above it, added in the composite-cooldown fix, stays as-is — it already correctly refers to the function's behavior, not its old name.)

- [ ] **Step 2: Update the internal call site**

In the same file, `:348`:

```python
        if triggered and not _is_cooldown_passed(rule, now):
```
becomes:
```python
        if triggered and not is_cooldown_passed(rule, now):
```

- [ ] **Step 3: Update the import and call site in `chart_alerts.py`**

In `backend/app/routers/chart_alerts.py`, the import block (`:20-24`):

```python
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
    _is_cooldown_passed,
)
```
becomes:
```python
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
    is_cooldown_passed,
)
```

The call site (`:668`):
```python
                if not _is_cooldown_passed(_row, datetime.now()):
```
becomes:
```python
                if not is_cooldown_passed(_row, datetime.now()):
```

- [ ] **Step 4: Update the two comment mentions in the same file**

`:654` and `:667` reference the old name in prose comments — update both occurrences of `_is_cooldown_passed` to `is_cooldown_passed` so the comments still describe the real function name.

- [ ] **Step 5: Run the chart-alert and alert-evaluator test suites**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py tests/test_chart_alert_scheduler.py tests/test_chart_alerts_composite_create.py tests/test_chart_alerts_edit_resets_sustain.py tests/test_chart_alerts_sustain.py tests/test_composite_detailed_parity.py tests/test_composite_sustain.py tests/test_composite_trigger.py tests/test_composite_watch_router.py tests/test_alert_rule_disabled_cannot_fire.py -q`
Expected: all PASS — this is a pure rename with no behavior change.

- [ ] **Step 6: Grep-confirm no remaining references to the old name**

Run: `grep -rn "_is_cooldown_passed" backend/app backend/tests`
Expected: no output (the two `__pycache__/*.pyc` matches seen before this change are stale compiled bytecode and will be regenerated on next run — safe to ignore, or delete `backend/**/__pycache__` first if you want a completely clean grep).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/alert_evaluator.py backend/app/routers/chart_alerts.py
git commit -m "refactor(alerts): rename _is_cooldown_passed to is_cooldown_passed

Now genuinely shared across modules (chart_alerts.py imports it from
alert_evaluator.py) since the composite-rule cooldown fix — the
leading-underscore name signaled 'module-private,' which was no longer
accurate. Pure rename, no behavior change."
```

---

## Task 3: Fix the two tastytrade-fallback-unmocked tests

**Files:**
- Modify: `backend/tests/test_market_data_fixes.py` (`test_iv_enrichment_skipped_when_ibkr_returns_none` `:408-451`, `test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore` `:522-567`)

**Root cause recap:** `fetch_option_chain` (sync) and `fetch_option_chain_async` both do, after the IBKR IV lookup returns falsy: `from .tastytrade_iv import fetch_iv_metrics_tastytrade` (a local import) then call it. Neither test mocks this call. On a machine without the `tastytrade` package, that local import throws `ImportError`, gets silently caught by a bare `except Exception: pass`, and `ivRank` stays at its pre-tastytrade fallback value — which is what both tests currently assert, but for the wrong reason (an accidental import failure, not the intended "no IV source available" behavior). In this repo's actual `.venv` (which correctly has `tastytrade` installed — confirmed via `.venv/Scripts/python.exe -c "import tastytrade"`), the real call executes and can return a non-zero IV, breaking both assertions.

- [ ] **Step 1: Run the tests to confirm the current (wrong-reason) failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_data_fixes.py::test_iv_enrichment_skipped_when_ibkr_returns_none tests/test_market_data_fixes.py::test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore -v`
Expected: both FAIL in the correct venv (this was already confirmed live earlier this session — re-confirm here as the TDD "red" step before the fix).

- [ ] **Step 2: Fix `test_iv_enrichment_skipped_when_ibkr_returns_none`**

Find (currently `:416-443`):

```python
    try:
        with patch("app.data.market.httpx.get") as mock_get:
            exp_resp = MagicMock()
            exp_resp.raise_for_status.return_value = None
            exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

            chain_resp = MagicMock()
            chain_resp.raise_for_status.return_value = None
            chain_resp.json.return_value = {
                "options": {
                    "option": [{
                        "option_type": "call",
                        "strike": 150,
                        "bid": 3.40,
                        "ask": 3.60,
                        "volume": 500,
                        "open_interest": 1200,
                        "implied_volatility": 0.30,
                        "greeks": {"delta": 0.45, "theta": -0.05},
                    }]
                }
            }
            # Prevent yfinance fallback from making network calls
            with patch("app.data.market._yf_iv_for_chain", return_value={}):
                mock_get.side_effect = [exp_resp, chain_resp]
                result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_iv
```

Replace with (adds one `patch(...)` for the tastytrade fallback, explicitly making it "unavailable" so the test exercises the SAME code path it did unintentionally before — now on purpose):

```python
    try:
        with patch("app.data.market.httpx.get") as mock_get:
            exp_resp = MagicMock()
            exp_resp.raise_for_status.return_value = None
            exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

            chain_resp = MagicMock()
            chain_resp.raise_for_status.return_value = None
            chain_resp.json.return_value = {
                "options": {
                    "option": [{
                        "option_type": "call",
                        "strike": 150,
                        "bid": 3.40,
                        "ask": 3.60,
                        "volume": 500,
                        "open_interest": 1200,
                        "implied_volatility": 0.30,
                        "greeks": {"delta": 0.45, "theta": -0.05},
                    }]
                }
            }
            # Prevent yfinance fallback from making network calls, and make the
            # tastytrade IV fallback explicitly unavailable too (not just
            # accidentally unmocked) — this test's whole premise is "no IV
            # source besides the raw Tradier value is available."
            with (
                patch("app.data.market._yf_iv_for_chain", return_value={}),
                patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
            ):
                mock_get.side_effect = [exp_resp, chain_resp]
                result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_iv
```

- [ ] **Step 3: Fix `test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore`**

Find (currently `:559-564`):

```python
    with (
        patch("app.data.market._get_yf_sem", return_value=mock_sem) as mock_sem_getter,
        patch("app.data.market._yf_iv_for_chain", return_value={}),
        patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
    ):
        await mkt.fetch_option_chain_async(mock_client, "AAPL", option_type="C")
```

Replace with:

```python
    with (
        patch("app.data.market._get_yf_sem", return_value=mock_sem) as mock_sem_getter,
        patch("app.data.market._yf_iv_for_chain", return_value={}),
        patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
        patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
    ):
        await mkt.fetch_option_chain_async(mock_client, "AAPL", option_type="C")
```

- [ ] **Step 4: Run both tests to verify they pass for the right reason now**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_data_fixes.py::test_iv_enrichment_skipped_when_ibkr_returns_none tests/test_market_data_fixes.py::test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore -v`
Expected: both PASS.

- [ ] **Step 5: Run the full `test_market_data_fixes.py` file**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_data_fixes.py -q`
Expected: all PASS, no regressions in the other ~40 tests in this file.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_market_data_fixes.py
git commit -m "fix(tests): mock the tastytrade IV fallback in two market-data tests

Both tests exercise the 'IBKR unavailable' IV-enrichment path but never
mocked the tastytrade fallback added alongside it (commit ea748f4).
They only passed in environments lacking the tastytrade package, where
the unmocked import silently failed — in this repo's real .venv (which
has tastytrade installed), the real call executed and broke both
assertions. Now explicitly mocks tastytrade as unavailable too, so the
tests exercise what they always claimed to: no IV source available."
```

---

## Task 4: Full verification pass

- [ ] **Step 1: Backend full suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: **0 failures** — this is the first point in the session where the full suite should be completely clean; the 2 failures that were present before Task 3 are now fixed, and no other regressions were introduced.

- [ ] **Step 2: Frontend full suite + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: typecheck clean, all Jest tests PASS.

- [ ] **Step 3: Report** all verification output (backend 0-failure confirmation, frontend clean run, and the Task 1 Step 3 live-browser screenshot/confirmation) to the user.

---

## Notes / deliberate non-goals

- **Not adding a full test harness for `ChartWorkspace`.** That component has zero existing tests and building one from scratch is a much larger, separate undertaking than fixing one silent-failure path — out of scope here.
- **Not changing the underlying "two evaluators can race" architecture** referenced by Task 2's renamed function — that was already explicitly out of scope for the composite-cooldown fix and remains so here; this task is a pure rename.
- **Not auditing `test_market_data_fixes.py` for other similar unmocked-dependency gaps beyond the two identified.** The fix is scoped to the two tests already confirmed broken; a broader audit of that file is a separate task if desired later.
