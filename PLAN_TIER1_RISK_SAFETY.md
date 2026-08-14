# Implementation Plan — Tier 1: Money/Risk-Control & Backend Safety

Status: REVISED after 2 rounds of adversarial review. Round 1: item 2's "3 confirmed sites,
mechanical swap" framing was wrong; item 5's allow-list inversion breaks an existing test; item 1
missed a second, independent, already-broken enforcement path in the frontend. Round 2 found
round 1's own fixes for items 2 and 5 were themselves still broken — item 2's "convert to async"
design was invalid Python and would have cascaded into 3 more call sites in 2 more files; item 5's
claimed fix was never actually written despite being described as done. Both redesigned with
smaller, lower-risk approaches (`asyncio.to_thread` instead of signature changes; a one-line set
addition instead of a full allow-list architecture inversion). Item 1b's test plan was also
corrected — round 1's version already passed on unfixed code.

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

**Round 2 review narrowed and corrected this finding — the gap is real but smaller than round 1
described, and round 1's own test plan doesn't actually exercise it.**

`frontend/lib/riskStore.ts`'s `maxSingleTradeExposurePct` (the value `SendToBrokerDialog` actually
enforces before sending a trade) is not updated by the Settings page's backend-fetch effect
(`page.tsx:914-937`, which only sets local `useState`). **But** every slider's `onChange` already
calls `updateLimit()` (`page.tsx:939-943`), which does call `setLimits()` on the global store in
real time, *before* `handleSaveRisk()` (the blur/save handler) ever runs. So in the normal
"drag a slider → it blurs → it saves" flow, the global store is already correctly in sync — round
1 overstated the gap by implying a save-time divergence that doesn't actually occur in that flow.

**The real, narrower gap: page-load hydration.** If the backend holds a different value than
whatever's already in the browser's persisted `riskStore` state (e.g. the value was changed in
another session/device), the fetch effect updates the *displayed* slider position but not the
*enforced* global store — until the user next touches any slider. Between page load and that
first touch, the send-dialog gate silently enforces a stale limit that doesn't match what's shown
on screen or what's persisted on the backend.

**Fix:** the backend-fetch effect (`page.tsx:914-937`) should also call
`useRiskStore.getState().setLimits(...)` with the fetched values, closing the hydration gap
specifically — not `handleSaveRisk()`, which (per the above) isn't actually where the gap lives.

**Test plan — round 1's original plan ("save a setting, confirm the store reflects it") already
passes on unfixed code because of `updateLimit()`, and would not have caught this bug; use this
instead:** mock the backend to return a risk-limit value materially different from whatever's in
a pre-seeded `riskStore` / localStorage state, render the Settings page (triggering the
fetch-on-mount effect), and — **without simulating any slider interaction** — assert
`useRiskStore.getState().limits` matches the backend-fetched value, not the stale pre-seeded one.

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

**regime.py — NOT mechanical, and round 2 review found the round-1 "convert to async" design was
actually invalid. Redesigned below using `asyncio.to_thread` instead — no signature changes, no
cascade risk.**

Round 1 review found the real blocking-call footprint in this one file alone:
- `_spx_ndx_metric` (regime.py:38-57), a **plain sync helper**, internally calls sync
  `fetch_candles(symbol, bars=200)` — called twice (SPX, NDX) from `get_regime` at
  regime.py:122-123.
- `fetch_candles('VIX', bars=260)` at regime.py:169.
- `fetch_candles('SPX', bars=600)` at regime.py:181.
- `fetch_intraday_candles('SPY', interval='15min', days=55)` at regime.py:222, and again in the
  separate `get_intraday_hmm_series` route at regime.py:332.

**No async equivalent of `fetch_intraday_candles` exists anywhere in `market.py`.** Writing one
(~110 lines merging Tradier + IBKR + yfinance, market.py:300-409) is real design work.

**Round 1's proposed resolution — converting `_spx_ndx_metric` to `async def` and "propagating
await through... `compute_overall_regime`" — is invalid as stated, per round 2 review: a sync
`def` cannot contain `await`, so `compute_overall_regime` would ALSO need to become `async def`.
That cascades further than either round noticed: `compute_overall_regime` has three other callers
across two other files, every one of which currently wraps it in `asyncio.to_thread`/
`run_in_executor` specifically because it's sync today —**
- `backend/app/services/portfolio_alert_monitor.py:136` — `await asyncio.to_thread(compute_overall_regime)`
- `backend/app/services/regime_monitor.py:61-62` — `await loop.run_in_executor(None, compute_overall_regime)`
- `backend/app/routers/stock_scan.py:503` — `await asyncio.to_thread(compute_overall_regime)`

**If `compute_overall_regime` became `async def`, all three of these would silently break** —
`asyncio.to_thread`/`run_in_executor` would run the function body in a worker thread far enough to
construct a coroutine object and immediately return it unawaited as the "result," corrupting
regime-flip detection, the regime monitor loop, and the stock-scan market backdrop, with only a
`RuntimeWarning: coroutine was never awaited` as a hint something's wrong — not a loud failure.

**Corrected design: do not convert `_spx_ndx_metric` or `compute_overall_regime` to async at
all.** Instead, wrap the *specific blocking calls made directly inside `get_regime` and
`get_intraday_hmm_series`* (both already `async def` route handlers) in `asyncio.to_thread`,
leaving every sync helper function's signature — and every one of its other callers — completely
untouched:
```python
# inside get_regime, replacing the two _spx_ndx_metric(...) calls:
spx_metric = await asyncio.to_thread(_spx_ndx_metric, 'SPX', ...)
ndx_metric = await asyncio.to_thread(_spx_ndx_metric, 'NDX', ...)

# replacing fetch_candles('VIX', bars=260) / fetch_candles('SPX', bars=600):
vix_candles = await asyncio.to_thread(fetch_candles, 'VIX', bars=260)
spx_candles = await asyncio.to_thread(fetch_candles, 'SPX', bars=600)

# replacing both fetch_intraday_candles(...) call sites (get_regime and get_intraday_hmm_series):
intraday = await asyncio.to_thread(fetch_intraday_candles, 'SPY', interval='15min', days=55)
```
This is a strictly smaller, lower-risk change than either round's earlier framing: it fixes the
actual problem (route handlers blocking the event loop) without touching `_spx_ndx_metric`'s or
`compute_overall_regime`'s signatures, so none of the 3 external call sites are affected and no
new async function needs to be written. `contracts.py`/`watchlist.py` still use their existing
real async functions as originally planned — `asyncio.to_thread` is specifically for `regime.py`,
where no async equivalents exist and converting the shared sync helpers would cascade.

**Test-mock migration — smaller for regime.py than originally feared, still real for
contracts.py/watchlist.py:**
- **regime.py**: since the corrected design (`asyncio.to_thread`) calls the exact same sync
  functions (`_spx_ndx_metric`, `fetch_candles`, `fetch_intraday_candles`) under the hood — just
  off the event loop thread — the existing tests that patch those sync names directly
  (`test_regime_direction.py:48-54`, `test_intraday_omm_fallback.py:39-43`) should keep working
  unmodified: `unittest.mock.patch` replaces the module attribute regardless of which thread later
  reads it. **Confirm this empirically once implemented** (run these two test files immediately
  after the regime.py change) rather than assuming — `asyncio.to_thread` does add a real thread
  hop, and while `patch` is thread-safe for this pattern, verifying beats assuming for something
  this easy to check.
- **contracts.py/watchlist.py**: these DO swap to genuinely different (async) function names, so
  their mocks need real updates: `backend/tests/conftest.py:262-269` (a **shared fixture reused
  across many test files**) patches `app.routers.contracts.fetch_option_chain`/`fetch_price` —
  update this first, before touching contracts.py itself, since an unnoticed miss here turns
  unrelated tests into flaky, real-network-calling tests instead of clean, attributable failures.
  `test_contracts_scoring.py` patches contracts.py's sync names at 6 separate call sites and needs
  the same treatment.

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
"tastytrade_live"}` omits `"tradier_live"`.

**Round 2 review found the round-1 "full allow-list inversion" design breaks
`test_broker_router.py:32-37`'s `test_router_raises_for_unknown_broker`** (asserts
`pytest.raises(ValueError, match="Unknown broker")` for a bogus key against empty adapters) —
under a strict allow-list, every key not in `_PAPER_BROKERS`, bogus or not, would hit the same
"not an enabled paper-trading broker" branch, permanently losing the `"Unknown broker"` /
`f"Available: {list(self._adapters.keys())}"` diagnostic for genuinely-unrecognized keys (useful
for distinguishing "you typo'd the key" from "that broker just isn't configured here"). Round 1's
revision claimed to have addressed this and had not.

**Corrected, smaller fix — keep the existing block-list *shape*, just make it complete and
future-proof by construction, instead of inverting the architecture:**
```python
# Every recognized live broker key, whether or not an adapter exists for it yet — this way a
# newly-added live adapter (e.g. TradierLiveAdapter) is blocked automatically by already being
# in this set, rather than requiring someone to remember to add its key here separately.
_KNOWN_LIVE_BROKERS = {"ibkr_live", "tradier_live", "alpaca_live", "tastytrade_live"}

class BrokerRouter:
    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        if broker_key in _KNOWN_LIVE_BROKERS:
            raise ValueError(
                f"live trading via '{broker_key}' is not yet activated. "
                "Enable it explicitly before use."
            )
        adapter = self._adapters.get(broker_key)
        if adapter is None:
            raise ValueError(
                f"Unknown broker '{broker_key}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        return adapter.place_order(order)
```
This is a **one-line change** (`_LIVE_BROKERS` renamed to `_KNOWN_LIVE_BROKERS` with
`"tradier_live"` added) — the control flow, the "Unknown broker" branch, and every existing
error message are otherwise untouched. `test_router_raises_for_unknown_broker` keeps passing
unmodified (a bogus key still isn't in `_KNOWN_LIVE_BROKERS`, still falls through to the adapter
lookup, still gets "Unknown broker... Available: [...]"). `test_router_raises_for_inactive_live`
and `test_tastytrade_live_is_blocked` also keep passing unmodified (both test keys already in the
set, message unchanged). No test needs rewriting. This achieves the actual goal (a newly-added
live adapter is blocked by construction rather than by remembering to update a list) without the
full architectural inversion round 1 proposed, and without its test breakage.

**Still worth doing, unmentioned by either prior round:** `backend/app/routers/broker.py`'s
`broker_status()` endpoint (~lines 139-155) hardcodes its own **separate** live-broker roster for
display purposes, also missing `tradier_live` — same drift pattern, different file, display-only
(not an enforcement gate, so lower stakes, but worth fixing in the same commit since it's the
same one-line-add fix applied to a second hardcoded set).

**Test plan:** add a case proving `tradier_live` specifically is now blocked (it wasn't before);
add a case proving a genuinely bogus/unknown key still gets the "Unknown broker" message, not the
live-broker one (proving the two branches stay distinct); confirm `broker_status()`'s response
now lists `tradier_live` alongside the other three "Locked — not yet activated" entries.

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
