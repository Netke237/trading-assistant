# Implementation Plan — Tier 1: Money/Risk-Control & Backend Safety

Status: DRAFT — pending adversarial review.

Scope: findings #1, #4, #6, #18, #20, #24 from `CODE_REVIEW_FINDINGS.md`. These are grouped
together because each is either a live financial-risk-control gap or a backend correctness/safety
issue with real (if usually low-probability) consequences. Review rigor here should approach what
`SELL_CLOSE_SEMANTICS_PLAN.md` used, since #1 in particular is the same class of bug (a
silently-inert safety control) as the ones that plan fixed.

---

## 1. "Max single position %" setting is never enforced (CRITICAL)

**Current state (re-verified against live code, not the original audit):**
- `backend/app/routers/risk_settings.py:118,141-142` reads/writes `risk_rules.yaml`'s
  `portfolio.max_single_position_pct` key, exposed to the frontend as `maxSinglePositionPct`.
- `backend/app/services/portfolio_risk.py:88` (`check_position_risk`, the function actually
  called by `auto_trader.py`'s `_check_exposure`) reads a **different** key,
  `max_single_trade_exposure_pct` — confirmed still hardcoded at `0.05` in
  `backend/config/risk_rules.yaml:4,11` (both keys exist side by side in the yaml today, at 0.05
  each, coincidentally equal — which is exactly what makes this bug currently invisible: a user
  who has never touched the Settings slider from its default sees no discrepancy).

**Fix:** make `check_position_risk` read the setting the UI actually controls. Two designs:
- **(A) Rename/consolidate:** delete `max_single_trade_exposure_pct` from `risk_rules.yaml` and
  `portfolio_risk.py`, have `portfolio_risk.py:88` read `max_single_position_pct` instead. Simpler,
  but a rename of a config key read by `portfolio_risk.py` and written by `risk_settings.py`.
- **(B) Alias:** keep both keys, but have `risk_settings.py`'s save path also write
  `max_single_trade_exposure_pct` alongside `max_single_position_pct` (or vice versa), keeping
  them in lockstep.

**Recommendation: (A).** Two keys meaning the same thing is exactly the kind of duplication that
caused this bug; a single source of truth is more robust than keeping two keys synchronized
forever. Rename `max_single_trade_exposure_pct` → `max_single_position_pct` everywhere:
- `backend/config/risk_rules.yaml` — remove the `max_single_trade_exposure_pct` line, keep
  `max_single_position_pct: 0.05`.
- `backend/app/services/portfolio_risk.py:88` — `rules["max_single_trade_exposure_pct"]` →
  `rules["max_single_position_pct"]`.
- `backend/app/routers/risk_settings.py` — no change needed to the read/write logic itself (it
  already targets the correct key name); just confirm the default fallback
  (`portfolio.get('max_single_position_pct', 0.05)`) still makes sense post-rename.
- Grep the whole backend for any other reader of `max_single_trade_exposure_pct` before deleting
  it (test fixtures, other services) — do not delete blind.

**Test plan:** a test that sets `maxSinglePositionPct` via the settings endpoint, then confirms
`check_position_risk` actually enforces the new value (currently: setting it would have zero
effect on the enforcement path — the missing regression coverage that let this ship). Also update
any existing test referencing `max_single_trade_exposure_pct` by name (grep first).

---

## 2. Blocking sync I/O inside async route handlers (HIGH)

**Confirmed sites** (from the original audit, re-verify line numbers before editing since this
file wasn't touched by the SELL_CLOSE work):
- `backend/app/routers/contracts.py` — `get_contracts` calls sync `fetch_option_chain(...)` /
  `fetch_price(...)` where the same file already has async-safe equivalents
  (`fetch_price_async`, `fetch_candles_async`) used elsewhere in the file.
- `backend/app/routers/watchlist.py` — `get_watchlist` calls sync `fetch_price`/
  `fetch_company_name` in a per-symbol loop.
- `backend/app/routers/regime.py` — sync `fetch_price('VIX')` inside an async handler.

**Fix:** swap each sync call for its async-safe counterpart already present in
`backend/app/data/market.py` (`fetch_price_async`, `fetch_candles_async`, or equivalent —
confirm exact async function names/signatures exist for each sync call before swapping;
`fetch_company_name_async` and an async option-chain fetcher may not exist yet and might need to
be added, mirroring the pattern of the ones that do exist).

**Scope guard:** if an async equivalent doesn't already exist for a given call (e.g., possibly
`fetch_company_name`), adding one is in scope (mirror the existing async pattern in the same
module) — but do not restructure `market.py`'s broader architecture; this is a mechanical
call-site swap, not a redesign.

**Test plan:** existing tests for these routers should still pass with async-safe calls (mock the
async function instead of the sync one). Add a test asserting the route doesn't call the sync
variant (or a lightweight concurrency test proving two simultaneous requests to a slow endpoint
don't serialize — optional, lower priority given the mock-based test suite's usual style).

---

## 3. Live strategy param outside its own WFO search grid (MEDIUM)

`backend/config/strategy_params.yaml`: `pullback_ema.active.bearish.ema_period: 35` is not in
`search.ema_period: [20, 50]`.

**Fix — two options, pick based on what the value should actually be:**
- **(A)** If `35` was a deliberate hand-tuned override that the team wants to keep as the live
  default despite it falling outside the auto-search grid, widen `search.ema_period` to include
  it (e.g. `[20, 35, 50]` or a continuous range covering 35), so the WFO optimizer can validate it.
- **(B)** If `35` was a typo/drift and the intended live value was meant to come from the grid,
  reset it to the nearest/best grid value (needs a WFO run or historical tuning-job output to
  determine which grid value the optimizer would have actually picked — check
  `tuning_scheduler.py`'s history/output if available).

**Recommendation:** default to (A) unless investigation turns up evidence the value is a stray
typo (e.g., a mismatched commit, a tuning-job log showing a different value was intended). This is
a config-only change — no code changes required, just editing the yaml with a clear commit
message explaining which of (A)/(B) was chosen and why.

**Test plan:** add/extend a config-sanity test (if one exists, e.g. a test that walks all
`strategy_params.yaml` active values and asserts each falls within its own `search` range) — if no
such test exists, this is a good place to add one, since it directly prevents this class of drift
recurring for any of the other strategies in the file.

---

## 4. `/auto-trade/arm` has no quantity validation (HIGH)

`backend/app/routers/auto_trade.py:20` — `ArmRequest.quantity: int` has no `Field(ge=1)`, unlike
`broker.py`'s equivalent fields.

**Fix:** `quantity: int = Field(..., ge=1)` — one-line change, matching the existing pattern in
`broker.py:20,31`.

**Test plan:** a test posting `quantity: 0` (or negative) to `/auto-trade/arm` expects `422`.

---

## 5. Live-broker safety is an incomplete block-list (MEDIUM)

`backend/app/services/broker_router.py:5` — `_LIVE_BROKERS = {"ibkr_live", "alpaca_live",
"tastytrade_live"}` omits `"tradier_live"`, and is a block-list rather than an allow-list.

**Fix:** invert to an explicit allow-list of paper-only broker keys, so a newly-added live adapter
is blocked by default rather than requiring someone to remember to add it to a block-list:
```python
_PAPER_BROKERS = {"ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"}

class BrokerRouter:
    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        if broker_key not in _PAPER_BROKERS:
            raise ValueError(
                f"'{broker_key}' is not an enabled paper-trading broker. "
                "Live trading is not yet activated."
            )
        ...
```
This changes the ValueError message slightly — check `test_broker_router.py`'s
`test_router_raises_for_inactive_live` and `test_tastytrade_live_is_blocked` for exact string
matches on the error message (`match="not yet activated"`) and keep that substring in the new
message so those tests keep passing without needing to be rewritten (or update them if the
message text changes materially — either is fine, just keep it intentional).

**Test plan:** add a case proving `tradier_live` (or any broker key not in the allow-list,
including a made-up one) is blocked the same way `ibkr_live`/`tastytrade_live` are today — this is
the exact gap: today there's no test proving a *hypothetical* live broker is blocked by default,
only that the 3 explicitly-named ones are.

---

## 6. Auto-trade daily-loss blocks leave no audit trail (LOW, but grouped here since it's the
   same file/subsystem as #4)

`backend/app/services/auto_trader.py:222` — `self._check_daily_loss(strategy, _history_snapshot,
pv)` is called unguarded; `_check_daily_loss` (defined at line 335) raises `RuntimeError` directly
with no surrounding try/except, so a fire blocked by the daily-loss circuit breaker leaves no
`AutoTradeState.history` entry, unlike the `_check_exposure` cap-blocked path immediately above it
(lines 200-212), which does append a `"cap_blocked"` history entry before re-raising.

**Fix:** wrap the `_check_daily_loss` call the same way the exposure check above it already is:
```python
try:
    self._check_daily_loss(strategy, _history_snapshot, pv)
except RuntimeError:
    with self._lock:
        self._state.history.append({
            "order_id":        None,
            "status":          "daily_loss_blocked",
            "broker":          strategy.broker,
            "symbol":          strategy.symbol,
            "option":          strategy.option_symbol,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "premium_at_risk": 0.0,
        })
    raise
```
Mirrors the existing `cap_blocked` pattern exactly (same file, ~15 lines above) — low risk,
small diff.

**Test plan:** a test that triggers the daily-loss limit and asserts
`AutoTradeService.get_state().history[-1]["status"] == "daily_loss_blocked"`.

---

## Sequencing

1. #1 first (highest stakes, smallest diff — a config key rename plus one line in
   `portfolio_risk.py`).
2. #4 and #6 (same file, `auto_trader.py`, do together).
3. #5 (small, self-contained).
4. #2 (blocking I/O — largest diff of this group, touches 3 router files).
5. #3 (config-only, needs a judgment call on (A) vs (B) — flag for user confirmation before
   picking a specific replacement value if evidence for (B) doesn't turn up cleanly; default to
   (A) otherwise per the recommendation above).

All are independent of each other — no ordering dependency, listed roughly by risk/simplicity.
