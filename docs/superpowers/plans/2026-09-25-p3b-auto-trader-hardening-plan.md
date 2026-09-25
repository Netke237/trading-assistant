# P3b — Auto-trader hardening: plan

Package: P3b in `docs/superpowers/plans/2026-09-25-work-packages.md`.
Branch: `claude/cool-allen-5ih4v0`, off origin/main 91e6725.
Owned files: `backend/app/services/auto_trader.py`, `backend/app/scoring/conviction_sizing.py`
(the package lists it under `services/`; the only file of that name is in `scoring/`),
`backend/app/services/notifications/alert_notifier.py`, `backend/app/data/ibkr_paper.py`,
`backend/config/scoring_rules.yaml` (comments only), `backend/tests/test_auto_trader.py`.
Plus, by Kenneth's answer below, two comment blocks in `backend/app/services/market_session.py` (P4a's file, comments only).

## New decisions (asked 2026-09-25, recorded in PROJECT_STATE.json)

- **P3B-REGIME-BARS-MISSING-REFUSES-2026-09-25** — when the fire path cannot get
  the bars it needs to measure the regime (the fetch times out, raises, or returns
  no bars), the fire is **refused** (recorded + alerted), not abstained. The fetch
  deadline goes from 8s to **25s**, so the yfinance fallback can answer after a stalled
  10s Tradier call.
- **P3B-CONTRACT-SIZING-ROUNDS-DOWN-2026-09-25** — contract sizing rounds **down**
  (floor), still with a minimum of 1 contract. This matches the stock card's `int()` share count.
- **P3B-MAY-EDIT-MARKET-SESSION-COMMENTS-2026-09-25** — P3b may fix the two stale
  comments in `market_session.py` (comments only).

## Re-check against current code (origin/main 91e6725)

All 12 entries are still open. E11's quoted entry covers two logged items. The
`stock_scan._position_size` 1% fallback item belongs to P3a because stock_scan.py is P3a's file. Only the
`round()` item is in P3b.

## Changes

### E1: IBKR reply with an id and an empty message list (`ibkr_paper.py`)
`awaiting_confirmation` becomes: no `order_id` key, a truthy `id`, and a `message` key present
(any value, including `[]` or `""`). A reply with only `{"id": ...}` still is not flagged, which
existing tests pin. The manual routes already answer an empty question with the fallback text
"IBKR asked for a confirmation". The auto-trader raises `OrderAwaitingConfirmationError`
(not_submitted). That is safer than today's result, which is "unknown status, full premium booked".
Test: `{"id":"abc","message":[]}` gives `awaiting_confirmation is True`. Mutation check: revert to `bool(data.get("message"))`.

### E2: daily-loss config fault test (`test_auto_trader.py`, phase AUTOTRADE-DAILY-LOSS-FAULT-TEST)
`test_a_daily_loss_config_fault_writes_one_risk_check_failed_row`, parametrized on
(a) a `TypeError` raised by `_check_daily_loss` and (b) the real `float()` ValueError
(`max_daily_loss_pct: "2%"` via `_risk_config`). The test drives it through `maybe_fire_on_scan` and asserts
exactly one new history row, with status `risk_check_failed`, error prefix
`daily-loss check failed:`, the attempt's id, no broker call, disarmed, and exactly one
`_alert_unclassified_refusal` call. Mutation check: delete the `except Exception` row-append in the
daily-loss block. The test must then fail.

### E3: gate-config refusal blames scoring_rules.yaml for an arm-request threshold (`auto_trader.py`)
- `_alert_regime_gate_config_refusal` lead sentence becomes source-neutral: "the regime
  configuration this trade needs could not be read or applied …". The exception text
  names the source.
- `_apply_regime_gate`'s `headwind_reject_pct` refusal names where the bad value came from.
  When `strategy.regime_headwind_reject_pct is not None`, the value came from **the Step-3 value this trade was
  armed with**, not scoring_rules.yaml. Otherwise it came from scoring_rules.yaml's regime_gate block.
- `RegimeGateConfigError`'s docstring line "This one means fix scoring_rules.yaml's
  regime_gate block" is widened to match.
Test: a strategy armed with `regime_headwind_reject_pct=nan` gives a refusal message that names the arm
request and does not say "scoring_rules.yaml's regime_gate block". The alert text does not
blame scoring_rules.yaml either. Mutation check: drop the source branch.

### E4: `_save_dedup` failures cannot reach `forget_alerts`' caller (`alert_notifier.py`)
`_save_dedup()` returns `True`/`False` (it still logs and never raises, so existing callers
are unaffected). `forget_alerts()` returns `bool`: `False` only when it changed the in-memory
state and could not persist it. The portfolio monitor ignores the return value, so its behaviour is unchanged.
auto_trader's two callers (`_alert_refusal`'s discrete clear and
`_clear_config_refusal_holds`) log an ERROR on `False` that says the on-disk hold survives a
restart. Tests: `_save_dedup` patched to fail makes `forget_alerts` return False, and `_alert_refusal` logs
the stuck-hold ERROR. Mutation check: make `forget_alerts` always return True.

### E5: four gate outcomes in prose, five in code (`auto_trader.py`)
`_apply_regime_gate` docstring and the fired-row `regime_gate` comment list all five
outcomes: disabled, abstained, caution, passed, passed:caution-band-disabled. This is prose only.

### E6: `full_conviction_pct: 0` logs ERROR on every resolve (`conviction_sizing.py`)
The ERROR is logged once per process per distinct offending value (a module-level set).
Later resolves log at DEBUG. The fallback value itself is unchanged. Test: two resolves
produce one ERROR record. Mutation check: remove the memo.

### E7: missing bars abstain instead of refusing; 8s < 10s (`auto_trader.py`, decision above)
- `_REGIME_FETCH_DEADLINE_S = 25.0`.
- New `RegimeDataUnavailableError(RuntimeError)`. `_measure_trade_regime` raises it on
  (a) fetch timeout, (b) any exception from the fetch, (c) `not bars` (empty or None).
  These cases **do not change**. They still return None and abstain: a non-empty series under
  `min_obs`, `compute_omm` failing, `compute_omm` returning None, a missing `regime.<horizon>`
  block, and a missing horizon. The scan also runs with no regime gate on a short or unmeasurable series.
- `_measure_once` memoizes the raise too. The gate and the sizer then see one outcome and fetch
  only once. It stores the exception and re-raises it.
- `fire()`: its own handler, with status `regime_data_blocked`, `premium_at_risk` 0.0, and the error text. It is
  ordered with the other named handlers, before the catch-all.
- `maybe_fire_on_scan`: its own handler that calls a new `_alert_regime_data_refusal`. That alert is per
  symbol and discrete, with alert type `AUTO_TRADE_REGIME_DATA_UNAVAILABLE`. `_alert_for_consumed_attempt`
  routes a `regime_data_blocked` row to the same alert.
- POST /auto-trade/fire (`routers/auto_trade.py`, P6's file, **not touched**) maps it through
  its existing `(ValueError, RuntimeError)` handler to a 400, the same as a headwind refusal.
- Where it bites, stated plainly:
  - The gate DISABLED with sizing ON: sizing measures, so missing bars now refuse
    instead of sizing at the floor (Kenneth's answer covers "when bars cannot be fetched").
  - The gate DISABLED with sizing OFF: nothing measures, so missing bars do not matter (unchanged).
  - INTRADAY horizon: the stock scan runs a 15-min regime-fetch failure with no gate (`regime_signal=None`),
    not a drop. The fire path now refuses there too. That is stricter than the scan, and it is the literal reading of the
    decision.
- `_fetch_scan_window_bars` returns `[]` when all bars are today's. That now refuses, and its comments are
  corrected. The two `market_session.py` comments that say an exception inside the fetch
  "abstains … fires UNGATED AT FULL ARMED QUANTITY" now say "refuses".
- Tests: a timeout (patch `_REGIME_FETCH_DEADLINE_S` small + a slow fetch), a raising fetch, and
  empty bars each produce `regime_data_blocked`, no broker call, and one `_alert_regime_data_refusal` via
  the scan trigger. A short non-empty series still abstains. Gate disabled + sizing on +
  empty bars also refuses. The deadline is pinned at > 10s (it must exceed the provider timeout).
  Mutation checks: each of the three raise sites reverted to `return None`.

### E8: stale "fires ungated at full armed quantity/full size" comments
`auto_trader.py` (Option A comment) and `market_session.py` (:60, :101) now say an abstain is sized at
the min_mult floor with regime_sizing on, and at the full armed quantity only with it off.
After E7, an exception or empty bars refuse. Comments only.

### E9: a malformed `regime.<horizon>` block escapes fire() with no row (`auto_trader.py`)
`_load_regime_cfg` validates the block's shape:
- the `regime` doc is not a mapping, or
- the horizon entry is not a mapping, or
- `min_obs` is present but not a real number (bools excluded) or is not > 0

Any of these raises `RegimeGateConfigError` with a message that names `regime.<horizon>` in
scoring_rules.yaml. A missing block or a missing horizon still returns `{}`, and the fire abstains (unchanged,
documented). Because this reuses `RegimeGateConfigError`, the existing fire() handler
(`regime_gate_config_blocked` row), the scan-trigger alert and the router's 500 all apply
unchanged. The alert's lead sentence is already source-neutral after E3. Tests: `regime` as a
list, horizon as a string, and `min_obs: "ten"` each give a `regime_gate_config_blocked` row, with the gate
enabled and also with the gate disabled + sizing on. Mutation check: remove the validation.

### E10: the comment says `_apply_regime_gate` refuses a -80 trade (`auto_trader.py`)
Reword it: the refusal applies only in a Stable regime (`require_stable_for_reject`). In a
Fragile regime, a -80 trade survives and is sized at min_mult. Comment only.

### E11: banker's rounding (`auto_trader.py`, decision above)
Both `max(1, round(q * m))` become `max(1, math.floor(q * m + 1e-9))`. The epsilon keeps
float products such as 10 × 0.7 = 6.999… from dropping a contract. Tests: 5 × 0.3 → 1 (was 2),
the floor path's 5 × min_mult 0.3 → 1, 10 × 0.7 → 7, 1 × 0.3 → 1. Mutation check: revert to round().

### E12: the YAML comment "a trade below -40 survives at min_mult" (`scoring_rules.yaml`, comments only)
The comment now says this holds on the auto-trader. On the scan card, Step 3's regime filter
(`req.regime_filter`) drops anything at or below the caution threshold first. It also says -40 is the shipped value
and Step 3 can override it per run.

## Verify
Backend `cd backend && .venv/bin/python -m pytest -q` (or `python -m pytest`). Frontend
`npx tsc --noEmit && npx jest` (unchanged by this package). `python3 scripts/state.py` exit 0.
No test writes `backend/config/*.yaml` or runs the app lifespan. Config faults are injected by
patching `_load_scoring_doc` / `_risk_config`.

## State
- One phase, `P3B-AUTOTRADER-HARDENING`, with a presence probe on `class RegimeDataUnavailableError`.
- AUTOTRADE-DAILY-LOSS-FAULT-TEST is flipped to shipped when its test lands.
- The 12 open_questions entries (13 strings, less the P3a half) move to closed_questions with evidence.
