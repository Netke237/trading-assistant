# Live Composite Alert Rule — Missing Creation UI (Feature Spec)

> This is a **spec/context document**, not an implementation plan. It exists so a future
> session (fresh context, no memory of this conversation) can turn it into a proper
> implementation plan using the `superpowers:writing-plans` skill. Read this doc first,
> then follow that skill's process.

## Why this doc exists

During a 2026-07-03 bug-fix session, the live (WebSocket-based) composite alert rule
evaluation logic in `backend/app/routers/chart_alerts.py` was made correct and
well-tested — but it was discovered there is currently **no way to create one** through
the app. This doc captures what exists, what's missing, and what a future session needs
to know to build the missing "Create" path.

## Background: the app's three alert mechanisms

### 1. Standard chart alerts (Price / Indicator / Structure / Regime)
- Created via: the "New Alert" panel (`AlertRuleBuilder`) on any chart.
- Storage: `alert_rules` DB table, plain (non-composite) `rule_json`.
- Checked: **live**, via WebSocket, only while that specific chart's browser tab is open
  and connected (`GET /chart/stream/{symbol}` in `backend/app/routers/chart.py`).
  Evaluated whenever the streamed data source reports a new candle close for that
  chart's interval — so roughly "every time a new candle forms" (every 15 min for a
  15-min chart, every hour for a 1h chart, etc.), but **only while the tab stays open**.
- Closing the browser tab stops checking entirely. No background fallback exists for
  this alert type.

### 2. Composite Watches
- Created via: the "Composite Alert" dialog (`CompositeAlertDialog`) on the chart.
- Storage: separate YAML-backed store (`strategy_watch_store`), via
  `POST /api/composite-watches/`.
- Checked: by a scheduled background job (`backend/app/services/strategy_watch_scheduler.py`),
  **independent of any open browser tab** — runs on the server itself.
- Default schedule: once per weekday at 16:15 ("EOD" mode), OR every `poll_hours`
  (default 4) hours during market hours 9:30–16:00 if "poll" mode is selected instead.
  The scheduler's internal loop wakes every 5 minutes just to check "is it time yet" —
  it doesn't re-evaluate that often, only on the configured cadence above.
- This is the only mechanism today that supports mean-reversion "strategy confirmations"
  and OMM/HMM regime-model primary conditions as a combined trigger, and the only one
  with a real Create button.

### 3. Composite Rules (the dormant one — subject of this spec)
- Evaluation logic exists in `chart_alerts.py`'s `evaluate_and_notify_for_symbol()`
  (added by a prior session, commit `e795f900`, made behaviorally correct by the
  2026-07-03 fix — see `docs/superpowers/plans/2026-07-03-alert-evaluator-parity-fixes.md`
  Tasks 1–2), **but**:
  - No endpoint or UI path ever creates a DB row shaped `{"__type": "composite", ...}`
    in `alert_rules`.
  - `POST /alerts/rules` (`AlertRuleCreate` Pydantic schema) only accepts
    `price | indicator | structure | regime` condition kinds — there is no `composite`
    kind in the schema at all.
  - Result: this evaluation branch is currently **100% unreachable** through the app.
  - If it were reachable, it would behave like mechanism #1 above (live,
    WebSocket-only, active only while the chart is open) — faster-reacting than a
    Composite Watch's scheduled check, at the cost of only working while that chart
    tab stays open.

## What "build the missing Create button" means

Add a way to create a **live** composite alert rule (mechanism #3) through the app.
Two plausible approaches — a future planning session should pick one:

- **(a) Extend `AlertRuleBuilder`** — add a "Composite" option to its condition-kind
  dropdown (alongside Price/Indicator/Structure/Regime), reusing the primary-model /
  confirmations / strategy-confirmations UI pieces `CompositeAlertDialog` already has.
- **(b) Extend `CompositeAlertDialog`** — add a delivery-mode toggle: "Watch
  (background, checked every few hours)" vs. "Rule (live, only while this chart is
  open)". Submit to `/api/composite-watches/` or `POST /alerts/rules` (with
  `__type: composite`) depending on the choice.

**(b) is likely the smaller change** — `CompositeAlertDialog` already has all the
trigger-definition UI (primary model, confirmations, strategy confirmations,
direction); it would mainly need a delivery-mode toggle and a second submit path.

## Backend work needed

- `AlertRuleCreate` / `AlertRulePatch` (Pydantic schemas in `chart_alerts.py`) need a
  composite-shaped variant, or the existing schema needs to explicitly support
  `__type: composite` bodies — currently `AlertRuleCreate` has no `__type` field at
  all, so there's no way to mark a whole rule as composite via the API today
  (`ConditionGroupIn.conditions: list` is loosely typed, but that's a different thing
  from tagging the whole rule as composite).
- `_deserialize_rule()` in `chart_alerts.py` already separates composite rows out
  before building `AlertRuleInput` objects (raw dict access via `composite_rows`) —
  this part likely needs no changes, it already works correctly once rows exist.

## Open questions for the future planning session

- Reuse `CompositeAlertDialog` (approach b) or extend `AlertRuleBuilder` (approach a)?
  Different UX and schema implications — worth a quick brainstorming pass before
  planning.
- Should live Rules have full feature parity with Watches? Note: `evaluate_from_context()`
  (the live-path evaluator) **cannot currently evaluate `HMM_intraday`/`HMM_daily`
  primary models at all** — it unconditionally returns `False` with a warning log for
  those. This is a separate, known, deliberately-deferred gap found during the
  2026-07-03 review (not fixed then, since nothing could reach it). If HMM composite
  rules are meant to work live too, that gap needs fixing as part of this feature —
  it's a real, non-trivial chunk of work (live HMM computation in the WS tick path has
  cost/performance implications worth designing deliberately, not bolting on).
- Should the UI clearly warn that a live Rule only fires while its chart tab stays
  open, so users don't mistake it for an always-on Watch?

## Related prior work

- `docs/superpowers/plans/2026-07-03-alert-evaluator-parity-fixes.md` — the plan that
  fixed the live composite-rule evaluator's correctness (WS/scheduled parity for
  `strategy_confirmations`, plus a separate, unrelated fix making standard chart
  alerts' Regime condition dropdown model-aware). Read this first — it explains what
  already works correctly in the evaluator, so this feature's implementation plan only
  needs to cover the creation/storage/UI path, not evaluation logic.
