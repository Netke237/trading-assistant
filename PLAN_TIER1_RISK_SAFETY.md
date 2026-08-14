# Implementation Plan — Tier 1: Money/Risk-Control & Backend Safety

Status: REVISED after adversarial review round 1. Findings: item 2's "3 confirmed sites, mechanical
swap" framing was wrong (regime.py undercounted ~6x, one call has no async equivalent to swap to
at all); item 5's allow-list inversion breaks an existing test the plan didn't check; item 1
missed a second, independent, already-broken enforcement path in the frontend. All addressed below.

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
any existing test referencing `max_single_trade_exposure_pct` by name (grep first — round 1
review confirmed the only remaining references outside code are numeric-value comments in
`test_portfolio_rules.py:63-88` / `test_portfolio_close_history.py:74`, which stay correct
post-rename since the number itself doesn't change).

**Round 1 review finding — a second, independent, already-broken enforcement path exists that
this fix does NOT touch, and the plan must stop calling this a "single source of truth" fix:**
`frontend/lib/riskStore.ts` has its own separate `maxSingleTradeExposurePct` field (default
`0.05`), wired into the *actual pre-flight trade-send gate* in
`frontend/components/organisms/SendToBrokerDialog/index.tsx:42,61` via `checkTradeRisk(...)`.
The Settings page's backend-fetch effect (`frontend/app/(frame)/settings/page.tsx:914-937`) only
updates a local `useState`, never `useRiskStore.setLimits(...)` — the global store the send-dialog
actually reads is only updated per-keystroke via `updateLimit()` on an `onChange` handler
(`page.tsx:939-943,1012`), and `handleSaveRisk()` doesn't touch it either. So a user can believe
they've "saved" a tightened position-size limit in Settings while the value the send dialog
actually enforces has silently diverged. **This plan's item 1 fixes only the backend half.**
Action: keep item 1 scoped to the backend fix as designed (don't scope-creep into a frontend
riskStore refactor here), but the commit/PR description must say explicitly that a second,
independent frontend enforcement path exists and is NOT covered by this fix — flag it as a new,
separate follow-up item (call it item 1b) rather than letting the fix read as more complete than
it is.

---

## 1b. (NEW — found during round 1 review) Frontend `riskStore` position-limit is disconnected
   from Settings

See item 1's note above. `frontend/lib/riskStore.ts`'s `maxSingleTradeExposurePct` (the value
`SendToBrokerDialog` actually enforces before sending a trade) is never updated when a user saves
Risk settings on the Settings page — only local component state changes.

**Fix:** `frontend/app/(frame)/settings/page.tsx`'s `handleSaveRisk()` (or the backend-fetch
effect, whichever is the more correct place — investigate which one is supposed to be the sync
point) must also call `useRiskStore.getState().setLimits(...)` with the saved values, so the
global store `SendToBrokerDialog` reads stays in sync with what's persisted to the backend.

**Test plan:** save a risk setting via the Settings page, then confirm `useRiskStore.getState()`
reflects the new value without requiring a full page reload.

---

## 2. Blocking sync I/O inside async route handlers (HIGH)

**Round 1 review substantially revised this section — the original "3 confirmed sites, mechanical
swap" framing undercounted the real scope, especially for `regime.py`. Corrected below.**

**contracts.py and watchlist.py — genuinely mechanical, confirmed by round 1 review:**
- `backend/app/routers/contracts.py` — sync `fetch_option_chain(...)` / `fetch_price(...)`;
  async equivalents `fetch_option_chain_async` (market.py:1132) and the already-used
  `fetch_price_async` **both confirmed to exist** with compatible signatures — straightforward
  swap.
- `backend/app/routers/watchlist.py` — sync `fetch_price`/`fetch_company_name`; both
  `fetch_price_async` and `fetch_company_name_async` (market.py:1344) **confirmed to exist** —
  straightforward swap.

**regime.py — NOT mechanical, substantially larger scope than originally described:**
Round 1 review found the real blocking-call footprint in this one file alone:
- `_spx_ndx_metric` (regime.py:38-57), a **plain sync helper**, internally calls sync
  `fetch_candles(symbol, bars=200)` — called twice (SPX, NDX) from `get_regime` at
  regime.py:122-123.
- `fetch_candles('VIX', bars=260)` at regime.py:169.
- `fetch_candles('SPX', bars=600)` at regime.py:181.
- `fetch_intraday_candles('SPY', interval='15min', days=55)` at regime.py:222, and again in the
  separate `get_intraday_hmm_series` route at regime.py:332.

**No async equivalent of `fetch_intraday_candles` exists anywhere in `market.py`** (confirmed by
enumerating every `async def` in the file) — this one call requires genuinely new async code, not
a swap to an existing sibling. `fetch_intraday_candles` itself is ~110 lines merging Tradier +
IBKR + yfinance (market.py:300-409) — writing `fetch_intraday_candles_async` is real design work,
not mechanical mirroring.

Additionally, `_spx_ndx_metric` being a **sync** helper called from **async** `get_regime` means
fixing this properly requires either converting `_spx_ndx_metric` to `async def` and propagating
`await` through both its callers (`get_regime` at 122-123, and `compute_overall_regime` — itself a
sync function — at 97-98), or wrapping the whole thing in `asyncio.to_thread`. This is a
signature-level refactor, not a call-site swap.

**Test-mock migration is also larger than "mock the async function instead":** existing tests
patch the sync function names directly, including a **shared fixture reused across many test
files**: `backend/tests/conftest.py:262-269` patches `app.routers.contracts.fetch_option_chain`/
`fetch_price`. Also: `test_regime_direction.py:48-54` and `test_intraday_omm_fallback.py:39-43`
each patch `app.routers.regime.fetch_price/fetch_candles/fetch_intraday_candles` directly;
`test_contracts_scoring.py` patches contracts.py's sync names at 6 separate call sites. **Update
`conftest.py`'s shared fixture FIRST, before touching contracts.py/regime.py** — an unnoticed miss
there turns unrelated tests into flaky, real-network-calling tests instead of clean, attributable
failures, which is a much worse failure mode than a loud immediate test break.

**Revised fix scope:**
1. `contracts.py`, `watchlist.py` — mechanical swap to existing async functions (as originally
   planned).
2. `regime.py` — write `fetch_intraday_candles_async` (new), convert `_spx_ndx_metric` to async
   (propagate through both callers), swap `fetch_candles`→`fetch_candles_async` at the 2 direct
   call sites, swap both `fetch_intraday_candles` call sites. Treat this file as its own
   sub-effort, separate from the other two files' quick swaps.
3. Update `conftest.py`'s shared fixture and all 3 named test files' mocks to patch the async
   function names, in the same commit as the router changes they support (not after).

**Test plan:** existing tests for these routers should still pass with async-safe calls (mock the
async function instead of the sync one, including the shared `conftest.py` fixture). Add a test
asserting the route doesn't call the sync variant.

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
