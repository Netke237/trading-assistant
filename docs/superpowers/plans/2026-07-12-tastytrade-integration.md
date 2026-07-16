# Tastytrade Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tastytrade as a fourth broker/data source, following the existing IBKR/Tradier/Alpaca pattern: paper account wired as a live order-execution target, live account credential-ready but explicitly blocked from trading (mirrors the current IBKR-live/Alpaca-live lock), and tastytrade's `market-metrics` endpoint wired in as a real IV Rank/Percentile source to fill the gap left by IBKR being unavailable.

**Architecture:** Backend: a cached OAuth `Session` module (mirrors `ibkr.py`'s module-level cache pattern), an async IV-metrics fetcher Governor-paced like `alpaca.py`, a synchronous `TastytradePaperAdapter` matching the `IbkrPaperAdapter`/`AlpacaPaperAdapter` interface (wraps async SDK calls via `asyncio.run`, the same convention already used in `fundamentals_store.py:252`), and a `tastytrade_live` slot that is credential-ready but hard-blocked in `broker_router.py`, matching `ibkr_live`/`alpaca_live`. `market.py`'s existing IV fallback chain gains one new tier — tastytrade — inserted between the (currently broken) IBKR call and the raw-IV proxy fallback. Frontend: new Zustand config slices, a Settings → Brokers section, and a `BrokerPicker` entry, all mirroring the existing Tradier/Alpaca sections exactly.

**Deliberate deviation from house convention, and why:** every other broker/data adapter in this codebase (`ibkr.py`, `ibkr_paper.py`, `alpaca.py`, `alpaca_paper_execution.py`, Tradier calls in `market.py`) is hand-rolled `httpx` against directly-documented REST paths. For tastytrade, the exact raw REST endpoint paths and request/response payload shapes for OAuth token refresh, order construction, and `market-metrics` could not be independently confirmed from tastytrade's own developer site during planning (it's a JS-rendered SPA that a plain fetch can't read past the nav shell). What *is* independently verifiable, with exact quoted signatures, is the community-maintained `tastytrade` PyPI package (`tastyware/tastytrade` on GitHub, docs at tastyworks-api.readthedocs.io) — an actively maintained, typed async SDK that wraps the same API. This plan uses that SDK rather than fabricate unverified wire-protocol details. Flag this to Kenneth explicitly when executing: it is a real dependency addition, not a stylistic choice.

**Tech Stack:** FastAPI / Pydantic v2 (backend), `tastytrade` PyPI package (OAuth session, market metrics, order placement), APScheduler-adjacent Governor rate limiting (existing `app/data/governor.py`), Next.js 15 / TypeScript / Zustand (frontend).

**Out of scope (deferred by explicit decision):** tastytrade's DXLink streaming candle/chart data. Chart/candle enhancement requires a persistent WebSocket client (subscription + reconnect management), a materially larger and separate piece of work from the REST-based `market-metrics` polling this plan covers. Do not build it here — track it as its own future plan if wanted later.

---

## Investigation summary (read this before starting — do not re-derive it)

1. **Auth model, verified against SDK docs:** `Session('client_secret', 'refresh_token')` (production) or `Session('client_secret', 'refresh_token', is_test=True)` (sandbox). Refresh tokens never expire; `tastytrade>=12.0.0` auto-refreshes the 15-minute session token on every request. This is what solves the "must re-login daily" problem IBKR has — no interactive browser step needed after initial setup. Source: https://tastyworks-api.readthedocs.io/en/latest/sessions.html
2. **IV Rank/Percentile, verified against SDK docs:** `await tastytrade.metrics.get_market_metrics(session, symbols: Iterable[str]) -> list[MarketMetricInfo]`. Relevant fields on `MarketMetricInfo`: `implied_volatility_index_rank` (alias `implied-volatility-index-rank`), `implied_volatility_percentile` (alias `implied-volatility-percentile`), plus `tos_implied_volatility_index_rank` / `tw_implied_volatility_index_rank` as alternate vendor calculations. Source: https://tastyworks-api.readthedocs.io/en/latest/api/metrics.html
3. **Order placement, verified against SDK docs:** `account = await Account.get(session, account_id)`; build a leg via `instrument.build_leg(quantity, OrderAction.BUY_TO_OPEN)` (stock) or the equivalent on an `Option` instrument fetched via `get_option_chain(session, symbol)`; construct `LimitOrder(legs=[leg], price=Decimal(...))`; submit via `await account.place_order(session, order, dry_run=False)`. Source: https://tastyworks-api.readthedocs.io/en/latest/orders.html and https://tastyworks-api.readthedocs.io/en/latest/instruments.html
4. **No published production rate limit for `market-metrics` or general market-data polling.** The only documented number found anywhere is the *Paper* API's default of 5 requests/second — not confirmed as the production limit. This plan therefore configures a deliberately conservative Governor budget (well under 5 req/s) rather than assuming headroom that isn't documented.
5. **Funding requirement:** per earlier research in this conversation, tastytrade's REST market-data endpoints are described in their docs as available to funded account holders; Kenneth has confirmed he will have a funded account, so this is not a blocker, just noted for completeness.
6. **Existing patterns this plan must match exactly** (read these files before writing new code):
   - `backend/app/data/ibkr_paper.py` — the `BrokerOrder`/`OrderResult` dataclasses every paper adapter returns/consumes. Do not redefine these; import them.
   - `backend/app/data/alpaca_paper_execution.py` — the simplest existing paper adapter (no local gateway, pure REST client) — closest shape to what the tastytrade adapter will look like structurally (though it wraps an SDK instead of raw httpx).
   - `backend/app/data/alpaca.py` — the only existing adapter that actually routes calls through `get_governor().call(...)`; this is the template for Governor-paced async calls.
   - `backend/app/services/broker_router.py` — `_LIVE_BROKERS = {"ibkr_live", "alpaca_live"}` is the exact mechanism for "credential-ready but blocked." `build_router_from_credentials()` is the exact place new paper adapters get constructed from the credential store.
   - `backend/app/services/credential_store.py` — `CredentialStore.__init__`'s `self._data` dict is the fixed set of known slots; `load()` only merges keys already present there, so new slots must be added to this dict, not just written via `set()`.
   - `backend/app/routers/credentials.py` — the `CredentialUpdate.key` `Literal` must include the new slot names or the endpoint will reject them with a 422.
   - `backend/app/routers/data_sources.py` — `_probe_ibkr_gateway`/`_probe_tradier_paper` are the two probe shapes to mirror (`(status, detail)` tuples, `ProbeStatus` values).
   - `backend/app/data/market.py:558-588` and the near-duplicate at `:1191-1219` — both copies of `fetch_option_chain` (sync and async chain-fetch variants) currently do: raw-IV proxy → IBKR overwrite (best-effort, `except: pass`) → yfinance proxy if still zero. tastytrade is inserted as a new tier in the same try/except shape, between the IBKR overwrite and the yfinance fallback.
   - `backend/app/data/governor.py` — `build_default_governor()`'s `providers` dict is where a new provider's `TokenBucket`/`CircuitBreaker` sizing is registered.
   - `frontend/lib/settingsStore.ts` — current persisted version is `19`; every new config field needs a new versioned `migrate()` branch, not a bare default (see CLAUDE.md's Zustand persistence note).
   - `frontend/app/(frame)/settings/page.tsx:1279-1490` (`BrokersForm`) — the exact section-by-section pattern (`SectionIntro` + `Row` + save button) every broker section follows, including the "(Locked)" pattern used for `ibkrLive`/`alpacaLive`.
   - `frontend/lib/autoTradeStore.ts:4` — `OptionsBroker = 'ibkr_paper' | 'tradier_paper'` — the type `BrokerPicker` and the trade-card send flow key off.
   - `frontend/components/organisms/BrokerPicker/index.tsx` — the broker-selection buttons shown on the trade card; new brokers are added as one more entry in its array.

---

## Task 1: Add the `tastytrade` SDK dependency

**Found in Round 8 of this plan's audit, verified by actually running `pip install`, not just reading the SDK's declared dependencies: installing `tastytrade` as originally planned does NOT work cleanly.** Every `tastytrade` release from 12.0.0 through the current 13.0.0 requires `httpx>=0.28.1` (confirmed directly against PyPI's package metadata), which hard-conflicts with this repo's pinned `httpx==0.27.0` (`requirements.txt`). A plain `pip install -r requirements.txt` with `tastytrade` added as originally written does not "install without conflicts" as Round 1-7 assumed — it either fails resolution outright or silently upgrades httpx to 0.28.x, potentially breaking every other adapter in this codebase that depends on `httpx` (`ibkr.py`, `ibkr_paper.py`, `alpaca.py`, `alpaca_paper_execution.py`, all of `market.py`'s Tradier calls). This must be resolved deliberately, not left to pip to decide silently.

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Confirm the httpx conflict before doing anything else**

Run: `cd backend && pip index versions tastytrade` and separately check `tastytrade`'s declared `httpx` requirement (e.g. `pip download tastytrade --no-deps -d /tmp/tt-check && pip show --files /tmp/tt-check/*.whl` or simply attempt the install in Step 3 and read the resolver's own error). Confirm for yourself, on your own machine, that this conflict is real before proceeding — package constraints change over time and the exact minimum version may have shifted since this plan was written.

- [ ] **Step 2: Bump `httpx` and check for fallout across the whole codebase, not just tastytrade's own code**

Modify `backend/requirements.txt`: change `httpx==0.27.0` to `httpx>=0.28.1` (or pin to whatever exact 0.28.x/0.29.x version is current and compatible when you run this — check PyPI at execution time rather than trusting this plan's number indefinitely). Add `tastytrade>=12.0.0` after it:

```
httpx>=0.28.1
tastytrade>=12.0.0
```

`respx>=0.21.0` (this repo's httpx-mocking library used throughout the existing test suite) is already pinned loosely enough to likely tolerate this — confirmed the currently-installed `respx==0.23.1` supports `httpx==0.27.0` today, and respx's own release notes should be checked for 0.28.x compatibility before assuming it's fine.

- [ ] **Step 3: Install and run the FULL existing test suite before writing any new tastytrade code — this is the real regression gate, not an optional nicety**

Run: `cd backend && pip install -r requirements.txt`
Run: `cd backend && pytest -v` (the entire suite, not a subset)

**Found in Round 9 of this plan's audit, confirmed by actually running this exact command with the httpx bump applied: this is not hypothetical — 15 tests genuinely fail.** httpx 0.28 removed the deprecated `AsyncClient(app=app, ...)` shortcut outright (it was only deprecated-with-a-warning in 0.27, not yet removed) — three pre-existing test files still use it: `backend/tests/test_composite_watch_router.py`, `backend/tests/test_mean_reversion_multi.py`, `backend/tests/test_prebreakout_universe.py` (confirmed via `grep -rn "AsyncClient(app=app" backend/tests/`). Fix by migrating each occurrence to the explicit-transport form — the same pattern this plan's own new tests already use everywhere (Tasks 3, 9, 10, 14, 16):

```python
# Before (breaks on httpx>=0.28):
async with AsyncClient(app=app, base_url="http://test") as client:

# After:
async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
```

Each of the three files needs `ASGITransport` added to its existing `from httpx import AsyncClient` import line, and every `AsyncClient(app=app, ...)` call site in that file updated to the transport form — `test_composite_watch_router.py` alone has 5 occurrences at the time of this writing (confirmed by grep); check each file for its own count rather than assuming it matches.

Expected after this fix: `cd backend && pytest -v` shows all pre-existing tests passing (1015 passed, 1 skipped, 1 xfailed was the exact baseline confirmed during this plan's audit — your numbers may differ slightly if the codebase has moved since, but the count should match whatever `pytest -v` reported *before* the httpx bump, run that as your own baseline first if in doubt). If anything else fails beyond this specific `AsyncClient(app=app)` pattern, treat it as a separate real regression from the httpx bump and fix it before proceeding to Task 2 — do not proceed with a red suite; every subsequent task in this plan assumes a clean baseline.

- [ ] **Step 4: Verify the import surface used by this plan actually exists in the installed version**

Run:
```bash
cd backend && python -c "
from tastytrade import Session, Account
from tastytrade.metrics import get_market_metrics
from tastytrade.order import LimitOrder, OrderAction, NewOrder
from tastytrade.instruments import Equity, get_option_chain
print('ok')
"
```
Expected: prints `ok`. If any import fails, the installed SDK version's module layout has moved since these docs were read — stop and re-check https://tastyworks-api.readthedocs.io/en/latest/ for the installed version before continuing to Task 2.

- [ ] **Step 5: Verify actual call signatures, not just importability — this is load-bearing for every task from here on**

Every callable's argument order and keyword names in Tasks 5, 7, and 9 were sourced from reading tastytrade's documentation during planning, not from inspecting the installed package. A wrong argument order or renamed kwarg would still pass every mocked unit test in Tasks 5-10 (the mocks encode the same assumed shape as the real calls) and would only surface at Task 15's live paper-order test, after several tasks and commits already exist assuming the guessed shape is correct. Catch that now, before Task 5 starts:

Run:
```bash
cd backend && python -c "
import inspect
from tastytrade import Session, Account
from tastytrade.metrics import get_market_metrics
from tastytrade.order import LimitOrder

print('Session:', inspect.signature(Session.__init__))
print('Account.get:', inspect.signature(Account.get))
print('get_market_metrics:', inspect.signature(get_market_metrics))
print('LimitOrder:', inspect.signature(LimitOrder.__init__))
"
```
Expected output shapes (compare against what's printed — do not proceed to Task 5 if any of these differ from what this plan assumes):
- `Session.__init__` takes `(self, client_secret, refresh_token, is_test=False, ...)` — positional `client_secret`, `refresh_token`, keyword `is_test`.
- `Account.get` takes `(session, account_id)` (or `(cls, session, account_id)` if it's a classmethod — check that `Account.get(session, "5WX01234")` is the correct call shape, not `Account.get(account_id, session)`). Confirmed in Round 9 of this plan's audit: the real parameter is named `account_number`, not `account_id` — harmless for this plan since every call site (Task 9) passes it positionally, but don't try to call it with `account_id=...` as a keyword anywhere.
- `get_market_metrics` takes `(session, symbols)` where `symbols` accepts an iterable of strings.
- `LimitOrder.__init__` accepts `legs` and `price` as keyword arguments.

If any signature differs from what's listed above, stop and update Tasks 5, 7, and 9's code to match the real signature before proceeding — do not implement against the assumed shape once the real one is known.

**Also noted in Round 8 (lower severity, not blocking):** the signatures checked above are directionally right but may gloss over real parameter-name differences — e.g. some tastytrade SDK versions use `account_number` rather than `account_id` on `Account`-related calls, and `Equity.get` accepts either a single symbol or `symbols: Iterable[str]` depending on version. Read the actual printed signatures carefully in this step rather than pattern-matching against the plan's expected shapes loosely. Also be aware `tastytrade` pulls in a non-trivial dependency footprint beyond `httpx` (pandas, numpy, pandas-market-calendars, exchange-calendars among others) — not a problem, just larger than this plan's original investigation notes implied; confirm none of these version-conflict with anything else pinned in `requirements.txt` during Step 3's full-suite run.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): bump httpx to >=0.28.1, add tastytrade SDK for market-metrics and paper order execution"
```

---

## Task 2: Credential store slots for `tastytrade_paper` and `tastytrade_live`

**Found in Round 5 of this plan's audit — a real security gap, not a style nitpick:** `credential_store.py:12`'s `_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret", "secret_key"}` is the exact-match set `_mask_dict` uses to decide which values to redact before `GET /settings/credentials` returns them. `client_secret` and `refresh_token` — tastytrade's two credential field names — are not in that set and would not fuzzy-match anything already there (`"secret"` and `"secret_key"` are different strings from `"client_secret"`). Left unfixed, `GET /settings/credentials` would return tastytrade's OAuth client secret and its refresh token — which, per this plan's own investigation notes, **never expires** — in plaintext. A leaked never-expiring refresh token is a standing account-access risk, not a cosmetic gap, and this task is where it must be closed since it's the same edit that introduces the new field names in the first place.

**Files:**
- Modify: `backend/app/services/credential_store.py:12` (add to `_SENSITIVE_KEYS`)
- Modify: `backend/app/services/credential_store.py:31-38` (add the new slots)
- Test: `backend/tests/test_credential_store.py` (create if it does not already cover slot presence — check first)

- [ ] **Step 1: Check whether a credential_store test file already exists**

Run: `ls backend/tests/test_credential_store.py 2>/dev/null || echo "not found"`

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_credential_store.py` (create the file if it didn't exist, using this content; if it existed, append these test functions):

```python
from app.services.credential_store import CredentialStore


def test_tastytrade_slots_exist_by_default(tmp_path):
    store = CredentialStore(path=tmp_path / "creds.yaml")
    assert store.get("tastytrade_paper") == {
        "client_secret": "", "refresh_token": "", "account_id": "",
    }
    assert store.get("tastytrade_live") == {
        "client_secret": "", "refresh_token": "", "account_id": "",
    }


def test_tastytrade_credentials_are_masked(tmp_path):
    """client_secret and refresh_token must never come back in plaintext from
    get_masked()/all_masked() — a leaked refresh token is a standing account
    compromise since tastytrade refresh tokens never expire."""
    store = CredentialStore(path=tmp_path / "creds.yaml")
    store.set("tastytrade_paper", {
        "client_secret": "super-secret-value", "refresh_token": "never-expires-token",
        "account_id": "5WX01234",
    })
    masked = store.get_masked("tastytrade_paper")
    assert masked["client_secret"] != "super-secret-value"
    assert masked["client_secret"].endswith("alue")  # last-4 preserved, rest masked
    assert masked["refresh_token"] != "never-expires-token"
    assert masked["account_id"] == "5WX01234"  # not sensitive, shown as-is
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_credential_store.py -k tastytrade -v`
Expected: both FAIL — `test_tastytrade_slots_exist_by_default` because `store.get("tastytrade_paper")` returns `None` (key not in `self._data`); `test_tastytrade_credentials_are_masked` because `client_secret`/`refresh_token` aren't in `_SENSITIVE_KEYS` yet, so `masked["client_secret"] == "super-secret-value"` and the `!=` assertion fails.

- [ ] **Step 4: Add the sensitive-key names and the new slots**

In `backend/app/services/credential_store.py`, modify `_SENSITIVE_KEYS` (line 12):

```python
_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret", "secret_key", "client_secret", "refresh_token"}
```

Then modify the `self._data` dict (lines 31-38):

```python
        self._data: dict[str, dict] = {
            "ibkr_live":     {"base_url": "https://localhost:5000/v1/api", "account_id": ""},
            "ibkr_paper":    {"base_url": "https://localhost:7499/v1/api", "account_id": ""},
            "tradier_live":  {"token": "", "account_id": ""},
            "tradier_paper": {"token": "", "account_id": ""},
            "alpaca_live":   {"key_id": "", "secret_key": "", "base_url": "https://api.alpaca.markets"},
            "alpaca_paper":  {"key_id": "", "secret_key": "", "base_url": "https://paper-api.alpaca.markets"},
            "tastytrade_live":  {"client_secret": "", "refresh_token": "", "account_id": ""},
            "tastytrade_paper": {"client_secret": "", "refresh_token": "", "account_id": ""},
        }
```

Note: tastytrade OAuth applications share one `client_secret` + a per-environment `refresh_token` (production vs sandbox grants are separate tokens from the same OAuth app) — the two slots are kept separate rather than sharing one, mirroring how `ibkr_live`/`ibkr_paper` are separate slots even though the app connects to two independent gateway ports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_credential_store.py -k tastytrade -v`
Expected: both PASS

- [ ] **Step 6: Run the full credential_store test file to check for regressions**

Run: `cd backend && pytest tests/test_credential_store.py -v`
Expected: all PASS — confirms adding `client_secret`/`refresh_token` to `_SENSITIVE_KEYS` doesn't change masking behavior for any other broker's existing fields (none of them use those exact key names).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/credential_store.py backend/tests/test_credential_store.py
git commit -m "feat(credentials): add tastytrade_paper/tastytrade_live slots, mask client_secret/refresh_token"
```

---

## Task 3: Allow the new slots through the `/settings/credentials` endpoint

**Files:**
- Modify: `backend/app/routers/credentials.py:14`
- Test: `backend/tests/test_credentials_router.py` (create if not present)

- [ ] **Step 1: Write the failing test**

Create/append to `backend/tests/test_credentials_router.py`. Note the cleanup: `credential_store` is a real, disk-backed process-wide singleton (`backend/config/local_credentials.yaml`, `credential_store.py:88`), not a test double — a POST here genuinely persists a value that outlives this test. Left uncleaned, later tests (e.g. Task 8's `fetch_option_chain` tests, or any test that checks whether `tastytrade_paper` is "configured") would see these dummy credentials as real, and — since Task 7's `fetch_iv_metrics_tastytrade` only fails safely by swallowing exceptions — could trigger real, uncoordinated, Governor-bypassing network calls to tastytrade using garbage secrets. Restore the slot in a `finally` block, the same way this codebase's own `try/finally` pattern is used elsewhere for module-level monkeypatches:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.credential_store import credential_store


@pytest.mark.asyncio
async def test_post_credentials_accepts_tastytrade_paper():
    original = credential_store.get("tastytrade_paper")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/settings/credentials", json={
                "key": "tastytrade_paper",
                "values": {"client_secret": "x", "refresh_token": "y", "account_id": "z"},
            })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "key": "tastytrade_paper"}
    finally:
        credential_store.set("tastytrade_paper", original)
        credential_store.save()


@pytest.mark.asyncio
async def test_post_credentials_accepts_tastytrade_live():
    original = credential_store.get("tastytrade_live")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/settings/credentials", json={
                "key": "tastytrade_live",
                "values": {"client_secret": "x", "refresh_token": "y", "account_id": "z"},
            })
        assert resp.status_code == 200
    finally:
        credential_store.set("tastytrade_live", original)
        credential_store.save()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_credentials_router.py -v`
Expected: FAIL — 422 Unprocessable Entity, `"tastytrade_paper"` not a valid enum value for `CredentialUpdate.key`.

- [ ] **Step 3: Widen the Literal**

In `backend/app/routers/credentials.py`, modify line 14:

```python
class CredentialUpdate(BaseModel):
    key: Literal[
        "ibkr_live", "ibkr_paper",
        "tradier_live", "tradier_paper",
        "alpaca_paper", "alpaca_live",
        "tastytrade_paper", "tastytrade_live",
    ]
    values: dict
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_credentials_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/credentials.py backend/tests/test_credentials_router.py
git commit -m "feat(credentials): accept tastytrade_paper/tastytrade_live in the credentials endpoint"
```

---

## Task 4: Register tastytrade with the Governor (rate limiting)

**Files:**
- Modify: `backend/app/data/governor.py:213-231`
- Test: `backend/tests/test_governor.py` (check first; append if present)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_governor.py` (create if it doesn't exist):

```python
from app.data.governor import build_default_governor


def test_tastytrade_provider_registered_with_conservative_rate():
    gov = build_default_governor()
    ps = gov._providers.get("tastytrade")
    assert ps is not None
    # No published production rate limit exists for market-metrics; the only
    # documented number anywhere is the Paper API's 5 req/s default, which is
    # NOT confirmed as the production limit. Stay well under it.
    assert ps.bucket.rate <= 2.0
    assert ps.breaker.fail_threshold >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_governor.py::test_tastytrade_provider_registered_with_conservative_rate -v`
Expected: FAIL — `ps` is `None` (`"tastytrade"` not in `providers`).

- [ ] **Step 3: Register the provider**

In `backend/app/data/governor.py`, modify `build_default_governor()` (lines 213-231):

```python
def build_default_governor() -> Governor:
    """Production Governor sized to Kenneth's tiers (spec §3)."""
    def _state(name, rate, capacity, *, fail=5, budget=None):
        return _ProviderState(
            name=name,
            bucket=TokenBucket(rate=rate, per=1.0, capacity=capacity),
            breaker=CircuitBreaker(fail_threshold=fail, cooldown=60.0),
            budget=budget,
        )

    providers = {
        "alpaca":     _state("alpaca",     rate=200 / 60, capacity=20),
        "tradier":    _state("tradier",    rate=120 / 60, capacity=15),
        "tiingo":     _state("tiingo",     rate=1 / 72,  capacity=2,
                             budget=SymbolBudget(max_symbols=50, window=3600.0)),
        "yfinance":   _state("yfinance",   rate=2,        capacity=2),
        "ibkr":       _state("ibkr",       rate=40,       capacity=40),
        # No published production rate limit for market-metrics exists anywhere
        # in tastytrade's docs. The only documented number found is the Paper
        # API's default of 5 req/s, which is NOT confirmed to apply to
        # production or to this specific endpoint. Deliberately conservative:
        # 1 req/s, small burst capacity, trips the circuit after 3 failures
        # (not 5) so a real problem is caught faster before the account gets
        # flagged for abuse.
        "tastytrade": _state("tastytrade", rate=1.0,      capacity=2, fail=3),
    }
    return Governor(providers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_governor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): register tastytrade with a conservative rate limit"
```

---

## Task 5: OAuth session module

**Files:**
- Create: `backend/app/data/tastytrade_session.py`
- Test: `backend/tests/test_tastytrade_session.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tastytrade_session.py`:

```python
from unittest.mock import patch, MagicMock

from app.data import tastytrade_session


def test_get_session_returns_none_when_unconfigured():
    with patch("app.services.credential_store.credential_store.get", return_value={
        "client_secret": "", "refresh_token": "", "account_id": "",
    }):
        tastytrade_session._SESSION_CACHE.clear()
        assert tastytrade_session.get_session("tastytrade_paper") is None


def test_get_session_builds_and_caches_session():
    tastytrade_session._SESSION_CACHE.clear()
    fake_creds = {"client_secret": "sec", "refresh_token": "ref", "account_id": "acct"}
    with patch("app.services.credential_store.credential_store.get", return_value=fake_creds), \
         patch("app.data.tastytrade_session.Session") as MockSession:
        mock_instance = MagicMock()
        MockSession.return_value = mock_instance

        first = tastytrade_session.get_session("tastytrade_paper")
        second = tastytrade_session.get_session("tastytrade_paper")

        MockSession.assert_called_once_with("sec", "ref", is_test=False)
        assert first is mock_instance
        assert second is mock_instance  # cached, not rebuilt


def test_get_session_always_uses_is_test_false_for_both_slots():
    # tastytrade's sandbox flag is independent of "paper trading account" —
    # Kenneth's tastytrade_paper slot still points at a real production OAuth
    # grant for a paper-trading *account*, not tastytrade's sandbox/cert
    # environment (which resets every 24h and is unsuitable for persistent
    # use, per the investigation in this plan's header). So is_test is always
    # False for both slots; this test locks that decision in so a future edit
    # doesn't accidentally point tastytrade_paper at the 24h-reset sandbox.
    tastytrade_session._SESSION_CACHE.clear()
    fake_creds = {"client_secret": "sec", "refresh_token": "ref", "account_id": "acct"}
    with patch("app.services.credential_store.credential_store.get", return_value=fake_creds), \
         patch("app.data.tastytrade_session.Session") as MockSession:
        tastytrade_session.get_session("tastytrade_live")
        MockSession.assert_called_once_with("sec", "ref", is_test=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tastytrade_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.tastytrade_session'`

- [ ] **Step 3: Write the module**

Create `backend/app/data/tastytrade_session.py`:

```python
"""Cached tastytrade OAuth Session, one per credential slot.

tastytrade session tokens last 15 minutes but the SDK (tastytrade>=12.0.0)
auto-refreshes them transparently on every call using the refresh token,
which never expires. That means a Session object, once built, can be reused
for the lifetime of the process — there is no daily re-login step, unlike
IBKR's Client Portal Gateway (see backend/app/data/ibkr.py's module
docstring for that contrast).

is_test is always False here: tastytrade's sandbox/cert environment resets
every 24 hours and always serves 15-minute-delayed data (confirmed against
https://developer.tastytrade.com/sandbox/), so it is not a fit for Kenneth's
persistent paper-trading or IV-data use — "paper trading account" at
tastytrade is a real, funded-adjacent production account, distinct from the
sandbox environment.
"""
from __future__ import annotations

import threading

from tastytrade import Session

from app.services.credential_store import credential_store

_SESSION_CACHE: dict[str, Session] = {}
_lock = threading.Lock()


def get_session(slot: str) -> Session | None:
    """Return a cached Session for the given credential slot
    ("tastytrade_paper" or "tastytrade_live"), or None if unconfigured."""
    with _lock:
        cached = _SESSION_CACHE.get(slot)
        if cached is not None:
            return cached

    creds = credential_store.get(slot) or {}
    client_secret = (creds.get("client_secret") or "").strip()
    refresh_token = (creds.get("refresh_token") or "").strip()
    if not client_secret or not refresh_token:
        return None

    session = Session(client_secret, refresh_token, is_test=False)

    with _lock:
        _SESSION_CACHE[slot] = session
    return session


def clear_cache() -> None:
    """Drop cached sessions — call after credentials are updated via the
    /settings/credentials endpoint so the next call rebuilds with fresh creds."""
    with _lock:
        _SESSION_CACHE.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tastytrade_session.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Invalidate the session cache on credential update**

Modify `backend/app/routers/credentials.py`'s `set_credentials`:

```python
@router.post("/credentials")
async def set_credentials(body: CredentialUpdate) -> dict:
    """Store broker credentials in memory and persist to local (gitignored) file."""
    credential_store.set(body.key, body.values)
    credential_store.save()
    if body.key in ("tastytrade_paper", "tastytrade_live"):
        from app.data.tastytrade_session import clear_cache
        clear_cache()
    return {"ok": True, "key": body.key}
```

- [ ] **Step 6: Add a test for the invalidation**

Append to `backend/tests/test_credentials_router.py`. Same disk-backed-singleton cleanup concern as Step 1's tests applies here too:

```python
@pytest.mark.asyncio
async def test_post_tastytrade_credentials_clears_session_cache():
    from app.data import tastytrade_session
    original = credential_store.get("tastytrade_paper")
    tastytrade_session._SESSION_CACHE["tastytrade_paper"] = object()  # fake cached session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/settings/credentials", json={
                "key": "tastytrade_paper",
                "values": {"client_secret": "new", "refresh_token": "new", "account_id": "z"},
            })

        assert "tastytrade_paper" not in tastytrade_session._SESSION_CACHE
    finally:
        credential_store.set("tastytrade_paper", original)
        credential_store.save()
        tastytrade_session.clear_cache()
```

- [ ] **Step 7: Run full test file to verify it passes**

Run: `cd backend && pytest tests/test_credentials_router.py tests/test_tastytrade_session.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/data/tastytrade_session.py backend/app/routers/credentials.py backend/tests/test_tastytrade_session.py backend/tests/test_credentials_router.py
git commit -m "feat(tastytrade): add cached OAuth session module"
```

---

## Task 6: Shared event-loop bridge for sync-to-async tastytrade calls

**Why this task exists — found in Round 2 of this plan's own adversarial audit, not part of the original draft:** every other Governor-gated provider in this codebase (`alpaca`, `tradier`, `tiingo`, `yfinance`, `ibkr`) is only ever called from `async def` code running on the app's single long-lived uvicorn event loop. This plan is the first design to reach the Governor from *synchronous* code via `asyncio.run()` — from Task 7's `asyncio.to_thread`-wrapped call (a separate OS thread), from Task 8's paper adapter, and from Task 10's health probe. `TokenBucket` (`backend/app/data/governor.py:22`) holds `self._lock = asyncio.Lock()`, created **once** inside the process-wide `Governor` singleton returned by `get_governor()`. An `asyncio.Lock` binds to whichever event loop first acquires it; a second, independent `asyncio.run()` call from a different thread trying to acquire that same `Lock` instance either raises `RuntimeError: ... bound to a different event loop` or, under real contention, deadlocks outright — this was empirically reproduced (not just reasoned about) during the audit: two threads raised the binding error, a third hung forever past a 10-second join timeout. It would not show up in any of this plan's per-call unit tests (none of them call the function more than once or concurrently) — it would only surface as an intermittent hang or crash during Task 14's live concurrent-scan verification, the worst possible place to discover a concurrency bug.

**Fix:** route every sync-to-async tastytrade call through **one** persistent background event loop, started once and reused for the process lifetime, so the Governor's `asyncio.Lock` is always acquired from the same loop regardless of which thread the sync caller is on.

**Files:**
- Create: `backend/app/data/tastytrade_bridge.py`
- Test: `backend/tests/test_tastytrade_bridge.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tastytrade_bridge.py`:

```python
import asyncio
import threading

from app.data.tastytrade_bridge import run_coro


async def _return_value(x):
    return x


def test_run_coro_returns_result():
    assert run_coro(_return_value(42)) == 42


def test_run_coro_reuses_same_loop_across_calls():
    async def _current_loop_id():
        return id(asyncio.get_running_loop())

    first = run_coro(_current_loop_id())
    second = run_coro(_current_loop_id())
    assert first == second  # same bridge loop both times, not a fresh one per call


def test_run_coro_is_safe_from_multiple_threads_concurrently():
    """Reproduces the exact hazard this task exists to fix: several threads,
    each calling run_coro() concurrently, must all complete without raising
    or hanging — unlike asyncio.run() against a shared asyncio.Lock."""
    results: list[int] = []
    errors: list[Exception] = []

    def _worker(n: int) -> None:
        try:
            results.append(run_coro(_return_value(n)))
        except Exception as exc:  # noqa: BLE001 — capturing for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in threads), "a thread hung — deadlock reproduced"
    assert errors == []
    assert sorted(results) == list(range(8))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tastytrade_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.tastytrade_bridge'`

- [ ] **Step 3: Write the module**

Create `backend/app/data/tastytrade_bridge.py`:

```python
"""Persistent background event loop bridging synchronous callers into
tastytrade's async SDK and the shared async Governor.

See this task's header in the plan this was built from for the full
concurrency hazard this exists to fix: routing sync-to-async tastytrade
calls through ad-hoc asyncio.run() calls from multiple threads shares one
Governor TokenBucket's asyncio.Lock across independently-created event loops,
which raises or deadlocks under real concurrency. Every tastytrade call that
needs to reach async code from sync code (tastytrade_iv.py,
tastytrade_paper.py, data_sources.py's _probe_tastytrade) must go through
run_coro() here instead of calling asyncio.run() directly.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is not None:
            return _loop
        loop = asyncio.new_event_loop()

        def _run_forever() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        threading.Thread(target=_run_forever, daemon=True, name="tastytrade-bridge").start()
        _loop = loop
        return loop


def run_coro(coro: Awaitable[T]) -> T:
    """Schedule `coro` on the shared bridge loop and block the calling thread
    until it completes. Safe to call from any thread — including from inside
    asyncio.to_thread() — because every call lands on the same loop instead
    of spinning up a fresh one via asyncio.run()."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tastytrade_bridge.py -v`
Expected: PASS (3 tests, including the concurrency reproduction).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/tastytrade_bridge.py backend/tests/test_tastytrade_bridge.py
git commit -m "feat(tastytrade): add shared event-loop bridge to avoid cross-loop Governor lock hazard"
```

---

## Task 7: IV Rank/Percentile fetch, Governor-paced

**Files:**
- Create: `backend/app/data/tastytrade_iv.py`
- Test: `backend/tests/test_tastytrade_iv.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tastytrade_iv.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from app.data import tastytrade_iv


def _fake_metric(symbol, rank, pct):
    m = MagicMock()
    m.symbol = symbol
    m.implied_volatility_index_rank = str(rank)
    m.implied_volatility_percentile = str(pct)
    return m


def test_fetch_iv_metrics_tastytrade_returns_none_when_unconfigured():
    with patch("app.data.tastytrade_iv.get_session", return_value=None):
        assert tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"]) is None


def test_fetch_iv_metrics_tastytrade_maps_fields(monkeypatch):
    fake_session = MagicMock()

    async def fake_get_market_metrics(session, symbols):
        assert session is fake_session
        assert list(symbols) == ["AAPL"]
        return [_fake_metric("AAPL", 62.3, 58.1)]

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=fake_get_market_metrics):
        result = tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"])

    assert result == {"AAPL": {"ivRank": 62.3, "ivPercentile": 58.1}}


def test_fetch_iv_metrics_tastytrade_returns_none_on_error():
    fake_session = MagicMock()

    async def raising_get_market_metrics(session, symbols):
        raise RuntimeError("network error")

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=raising_get_market_metrics):
        assert tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tastytrade_iv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.tastytrade_iv'`

- [ ] **Step 3: Write the module**

Create `backend/app/data/tastytrade_iv.py`:

```python
"""tastytrade IV Rank/Percentile — Governor-paced, routed through the shared
event-loop bridge (Task 6's tastytrade_bridge.run_coro) rather than a raw
asyncio.run() call, so it can be called from market.py's synchronous
fetch_option_chain without risking the cross-loop Governor-lock hazard
Task 6 exists to fix.

Inserted as a fallback tier between IBKR's real IV Rank/Percentile
(backend/app/data/ibkr.py:fetch_iv_metrics_ibkr) and the raw-IV-as-proxy
fallback in market.py — see market.py's fetch_option_chain for the full
tier order.
"""
from __future__ import annotations

import logging

from tastytrade.metrics import get_market_metrics

from app.data.governor import get_governor, ProviderUnavailable
from app.data.tastytrade_bridge import run_coro
from app.data.tastytrade_session import get_session

logger = logging.getLogger(__name__)


async def _fetch_async(symbols: list[str], slot: str) -> dict[str, dict] | None:
    session = get_session(slot)
    if session is None:
        return None
    try:
        metrics = await get_governor().call(
            "tastytrade",
            lambda: get_market_metrics(session, symbols),
        )
    except ProviderUnavailable:
        logger.warning("tastytrade circuit open — skipping IV metrics fetch")
        return None
    except Exception as exc:
        logger.debug("tastytrade market-metrics fetch failed: %s", exc)
        return None

    result: dict[str, dict] = {}
    for m in metrics:
        rank = getattr(m, "implied_volatility_index_rank", None)
        pct = getattr(m, "implied_volatility_percentile", None)
        if rank is None or pct is None:
            continue
        try:
            result[m.symbol] = {"ivRank": float(rank), "ivPercentile": float(pct)}
        except (TypeError, ValueError):
            continue
    return result or None


def fetch_iv_metrics_tastytrade(
    symbols: list[str], slot: str = "tastytrade_paper"
) -> dict[str, dict] | None:
    """Sync wrapper. Returns {symbol: {"ivRank": float, "ivPercentile": float}}
    or None if unconfigured / the call failed. `slot` defaults to the paper
    account credentials since that's the one Kenneth will have funded and
    active; pass "tastytrade_live" explicitly once that account is in use
    for something other than credential storage."""
    try:
        return run_coro(_fetch_async(symbols, slot))
    except Exception as exc:
        logger.warning("fetch_iv_metrics_tastytrade failed: %s", exc)
        return None
```

- [ ] **Step 4: Update the test file's patch targets for the bridge**

The tests written in Step 1 patch `app.data.tastytrade_iv.get_session` and `app.data.tastytrade_iv.get_market_metrics` directly — those remain correct and need no change, since `run_coro` only affects *how* the coroutine gets scheduled, not what `_fetch_async` calls. No test edits needed here; this step exists only to confirm that explicitly before moving on, since it would be an easy thing to assume needs a rewrite and doesn't.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tastytrade_iv.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/data/tastytrade_iv.py backend/tests/test_tastytrade_iv.py
git commit -m "feat(tastytrade): add Governor-paced IV Rank/Percentile fetch, routed through the shared bridge"
```

---

## Task 8: Wire tastytrade into `market.py`'s IV fallback chain

**Files:**
- Modify: `backend/app/data/market.py:565-584` (sync `fetch_option_chain`)
- Modify: `backend/app/data/market.py:1198-1218` (async variant — confirm exact current line numbers before editing, they may have shifted after Task 7's changes elsewhere; the code shape is otherwise identical to the block below)
- Test: `backend/tests/test_market_data_fixes.py` (existing file — extends the existing IBKR fallback tests)

- [ ] **Step 1: Write the failing test**

Correction from an earlier draft of this plan: the real reference test in this file is `test_iv_enrichment_applied_when_ibkr_available` (line 357 of `backend/tests/test_market_data_fixes.py` as of this writing — confirm with `grep -n "def test_iv_enrichment_applied_when_ibkr_available" backend/tests/test_market_data_fixes.py` before relying on the line number). It does **not** use `monkeypatch.setattr(market, "fetch_iv_metrics_ibkr", ...)` — `market.py` never imports `fetch_iv_metrics_ibkr` at module scope (it's imported locally inside the function body, at `market.py:567` and `market.py:1200`), so there is no `market.fetch_iv_metrics_ibkr` attribute to patch and that call would raise `AttributeError` before the test body runs. The real, working pattern patches the function on the `app.data.ibkr` module directly, with manual save/restore:

```python
original_fetch_iv = ibkr_mod.fetch_iv_metrics_ibkr
ibkr_mod.fetch_iv_metrics_ibkr = lambda s: ibkr_iv
try:
    ...
finally:
    ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_iv
```

A second correction, found in Round 2 of this plan's audit: an earlier draft of this test used `_fake_chain_contract(strike=150)` as the mocked Tradier chain response body. `_fake_chain_contract` (`test_market_data_fixes.py:42`) produces this codebase's *internal output* shape (`right`, `price`, flat `delta`/`theta`, `ivRank`/`ivPercentile`) — it has no `option_type`, `bid`, `ask`, `implied_volatility`, or `greeks` keys. `fetch_option_chain`'s real parsing code (`market.py:522`, `if c.get("option_type") != tradier_type: continue`) would silently skip every contract shaped like that, and the test's own `assert len(result) == 1` would fail before ever reaching the `ivRank`/`ivPercentile` assertions. The raw Tradier chain shape actually used by `test_iv_enrichment_applied_when_ibkr_available` (verified directly from that test, `test_market_data_fixes.py:378-391`) is a plain dict with `option_type`, `strike`, `bid`, `ask`, `volume`, `open_interest`, `implied_volatility`, and a nested `greeks` dict — not `_fake_chain_contract`'s output shape. Also corrected: `fetch_option_chain`'s real signature is `fetch_option_chain(symbol, expiry=None, option_type="C", dte_bounds=None)` and the reference test calls it as `fetch_option_chain("AAPL", option_type="C")` — no positional expiry argument (an earlier draft of this test passed a hard-coded expiry string positionally, which doesn't match how the real reference test calls it and risks the chain coming back empty if that date isn't in the mocked `expirations` list).

Append to `backend/tests/test_market_data_fixes.py`, matching `test_iv_enrichment_applied_when_ibkr_available`'s mock shape and call signature exactly:

```python
def test_fetch_option_chain_falls_back_to_tastytrade_when_ibkr_unavailable():
    """When IBKR returns None, tastytrade's real IV Rank/Percentile should be
    used instead of falling straight to the raw-IV proxy."""
    from app.data.market import fetch_option_chain
    import app.data.ibkr as ibkr_mod
    import app.data.tastytrade_iv as tasty_mod

    tasty_iv = {"AAPL": {"ivRank": 47.2, "ivPercentile": 51.9}}

    original_fetch_ibkr_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: None  # IBKR unavailable

    original_fetch_tasty_iv = tasty_mod.fetch_iv_metrics_tastytrade
    tasty_mod.fetch_iv_metrics_tastytrade = lambda symbols: tasty_iv

    try:
        with patch("app.data.market.httpx.get") as mock_get:
            # Exact mock shape from test_iv_enrichment_applied_when_ibkr_available
            # (test_market_data_fixes.py:369-393) — the raw Tradier chain
            # response shape, not this file's _fake_chain_contract() helper
            # (that produces the internal output shape, not Tradier's input shape).
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

            mock_get.side_effect = [exp_resp, chain_resp]

            result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_ibkr_iv
        tasty_mod.fetch_iv_metrics_tastytrade = original_fetch_tasty_iv

    assert len(result) == 1
    assert result[0]["ivRank"] == 47.2
    assert result[0]["ivPercentile"] == 51.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_market_data_fixes.py::test_fetch_option_chain_falls_back_to_tastytrade_when_ibkr_unavailable -v`
Expected: FAIL — `ModuleNotFoundError` on `app.data.tastytrade_iv` if Task 7 hasn't landed yet (confirm Task 7 is done first); if it has, expected failure is instead the raw-IV proxy value showing through, since the market.py wiring in Step 3 below doesn't exist yet.

- [ ] **Step 3: Wire in the new tier (sync `fetch_option_chain`)**

In `backend/app/data/market.py`, modify the block at lines 565-584 (shown here with full surrounding context so the edit is unambiguous):

```python
        # Enrich with IBKR IV Rank/Percentile if available
        try:
            from .ibkr import fetch_iv_metrics_ibkr
            _ibkr_iv = fetch_iv_metrics_ibkr(symbol)
            if _ibkr_iv:
                for c in result:
                    c["ivRank"] = round(_ibkr_iv["ivRank"], 1)
                    c["ivPercentile"] = round(_ibkr_iv["ivPercentile"], 1)
        except Exception:
            pass  # keep existing fallback values

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile before
        # falling back to the raw-IV-as-proxy values set above.
        if not _ibkr_iv:
            try:
                from .tastytrade_iv import fetch_iv_metrics_tastytrade
                _tasty_iv = fetch_iv_metrics_tastytrade([symbol])
                if _tasty_iv and symbol in _tasty_iv:
                    for c in result:
                        c["ivRank"] = round(_tasty_iv[symbol]["ivRank"], 1)
                        c["ivPercentile"] = round(_tasty_iv[symbol]["ivPercentile"], 1)
            except Exception:
                pass  # keep existing fallback values

        zero_iv = sum(1 for c in result if c["ivRank"] == 0)
        if zero_iv > len(result) * 0.5 and result:
            yf_iv = _yf_iv_for_chain(symbol, target_exp, option_type == "C")
            for c in result:
                if c["ivRank"] == 0:
                    yf_val = yf_iv.get(float(c["strike"]))
                    if yf_val:
                        c["ivRank"] = int(round(yf_val * 100))
                        c["implied_volatility"] = round(yf_val, 4)
```

Note the variable `_ibkr_iv` must exist even when the `try` block raises before assignment — confirm the existing code already initializes it (it does, as `_ibkr_iv = fetch_iv_metrics_ibkr(symbol)` inside the `try`; if that line raises, `_ibkr_iv` would be undefined). Guard this explicitly:

```python
        _ibkr_iv = None
        try:
            from .ibkr import fetch_iv_metrics_ibkr
            _ibkr_iv = fetch_iv_metrics_ibkr(symbol)
            if _ibkr_iv:
                for c in result:
                    c["ivRank"] = round(_ibkr_iv["ivRank"], 1)
                    c["ivPercentile"] = round(_ibkr_iv["ivPercentile"], 1)
        except Exception:
            pass  # keep existing fallback values
```

(This `_ibkr_iv = None` initialization line is a small correctness fix uncovered while wiring in the new tier — without it, a raised exception before assignment would make the `if not _ibkr_iv:` check below reference an undefined name. Apply it as part of this task, it is in scope since the new code depends on that variable.)

- [ ] **Step 4: Apply the equivalent change to the async variant — NOT identical, the async block needs `asyncio.to_thread`**

Find the near-duplicate block in `backend/app/data/market.py` (originally around lines 1198-1218 — search for `"# Enrich with IBKR IV Rank/Percentile if available (async-safe via to_thread)"`, note the different comment wording, that's the async one). This block is **not** a plain copy of the sync one: it already wraps the synchronous `fetch_iv_metrics_ibkr` call in `await asyncio.to_thread(...)` (`market.py:1201`) because you cannot block an `async def` function's event loop with a blocking call. `fetch_iv_metrics_tastytrade` (Task 7) no longer raises in this situation — since Task 7's fix, it routes through `tastytrade_bridge.run_coro`, which is safe to call from any thread. But `run_coro` still *blocks the calling thread* until the bridge loop's future resolves, and calling it directly from the app's single main event loop (without `to_thread`) would block that entire loop for the duration of the network call — starving every other concurrent request the app is serving. Wrap it in `asyncio.to_thread` for that reason (avoiding a blocked event loop), not to avoid a `RuntimeError` (that specific hazard no longer applies once Task 6's bridge is in place):

```python
        _ibkr_iv = None
        try:
            from .ibkr import fetch_iv_metrics_ibkr
            _ibkr_iv = await asyncio.to_thread(fetch_iv_metrics_ibkr, symbol)
            if _ibkr_iv:
                for c in result:
                    c["ivRank"] = round(_ibkr_iv["ivRank"], 1)
                    c["ivPercentile"] = round(_ibkr_iv["ivPercentile"], 1)
        except Exception:
            pass  # keep existing fallback values

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile before
        # falling back to the raw-IV-as-proxy values set above. Wrapped in
        # asyncio.to_thread purely to avoid blocking this coroutine's event
        # loop while fetch_iv_metrics_tastytrade's run_coro() call blocks its
        # calling thread waiting on the shared bridge loop (Task 6).
        if not _ibkr_iv:
            try:
                from .tastytrade_iv import fetch_iv_metrics_tastytrade
                _tasty_iv = await asyncio.to_thread(fetch_iv_metrics_tastytrade, [symbol])
                if _tasty_iv and symbol in _tasty_iv:
                    for c in result:
                        c["ivRank"] = round(_tasty_iv[symbol]["ivRank"], 1)
                        c["ivPercentile"] = round(_tasty_iv[symbol]["ivPercentile"], 1)
            except Exception:
                pass  # keep existing fallback values
```

`asyncio` is already imported at the top of `market.py` (used elsewhere for the existing `asyncio.to_thread` calls at lines 961, 1016, 1083, 1241) — no new import needed.

- [ ] **Step 5: Write the matching async-path test**

Confirmed by reading `market.py` directly (`grep -n "^async def " backend/app/data/market.py`): the async chain-fetch function is `fetch_option_chain_async(client: httpx.AsyncClient, symbol, expiry=None, option_type="C", dte_bounds=None)` at `market.py:1090` — it takes a caller-supplied `httpx.AsyncClient` as its first argument and calls `await client.get(...)` (`market.py:1099, 1129`), not module-level `httpx.get`. That means this test needs an `AsyncMock`-based client double, not `patch("app.data.market.httpx.get")` — the sync test's mocking approach does not carry over unchanged.

Append to `backend/tests/test_market_data_fixes.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_fetch_option_chain_async_falls_back_to_tastytrade_when_ibkr_unavailable():
    """Same fallback as the sync test, but through fetch_option_chain_async,
    which takes a caller-supplied httpx.AsyncClient and wraps both the IBKR
    and tastytrade calls in asyncio.to_thread."""
    from app.data.market import fetch_option_chain_async
    import app.data.ibkr as ibkr_mod
    import app.data.tastytrade_iv as tasty_mod

    tasty_iv = {"AAPL": {"ivRank": 47.2, "ivPercentile": 51.9}}

    original_fetch_ibkr_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: None

    original_fetch_tasty_iv = tasty_mod.fetch_iv_metrics_tastytrade
    tasty_mod.fetch_iv_metrics_tastytrade = lambda symbols: tasty_iv

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

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    try:
        result = await fetch_option_chain_async(fake_client, "AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_ibkr_iv
        tasty_mod.fetch_iv_metrics_tastytrade = original_fetch_tasty_iv

    assert len(result) == 1
    assert result[0]["ivRank"] == 47.2
    assert result[0]["ivPercentile"] == 51.9
```

`AsyncMock` is already imported at the top of `test_market_data_fixes.py` (`from unittest.mock import AsyncMock, MagicMock, patch`, line 18) — no new import needed.

- [ ] **Step 6: Run both tests to verify they pass**

Run: `cd backend && pytest tests/test_market_data_fixes.py -k "tastytrade" -v`
Expected: both the sync and async fallback tests PASS, plus every pre-existing IBKR test in the same file still passes (verifies the `_ibkr_iv = None` guard didn't change IBKR's own behavior when it succeeds).

- [ ] **Step 7: Run the full backend suite to check for regressions**

Run: `cd backend && pytest -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_data_fixes.py
git commit -m "feat(market-data): fall back to tastytrade IV Rank/Percentile when IBKR is unavailable"
```

---

## Task 9: Paper order execution adapter

**Files:**
- Create: `backend/app/data/tastytrade_paper.py`
- Test: `backend/tests/test_tastytrade_paper.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tastytrade_paper.py`:

```python
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.data.ibkr_paper import BrokerOrder
from app.data.tastytrade_paper import TastytradePaperAdapter


def _stock_order() -> BrokerOrder:
    return BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="LMT", limit_price=150.0, sec_type="STK",
    )


def test_place_order_raises_when_session_unconfigured():
    with patch("app.data.tastytrade_paper.get_session", return_value=None):
        adapter = TastytradePaperAdapter(account_id="5WX01234")
        with pytest.raises(RuntimeError, match="not configured"):
            adapter.place_order(_stock_order())


def test_place_order_stock_success():
    """Round 8 correction: `Leg`/`LimitOrder` are strict Pydantic v2 models in
    the real SDK (confirmed by actually installing tastytrade and checking
    `Leg.model_fields`) — a bare `MagicMock()` fails Pydantic validation the
    moment the adapter builds `LimitOrder(legs=[leg], price=price)`, raising
    `pydantic_core.ValidationError` before this test's own assertions run.
    Patch the `LimitOrder` class itself (not just its inputs) so construction
    never touches real Pydantic validation — this also lets the test assert
    on the exact price passed in, which doubles as a check on the debit/credit
    sign convention noted elsewhere in this task as unverified beyond docs."""
    fake_session = MagicMock()
    fake_account = MagicMock()
    fake_leg = MagicMock()
    fake_equity = MagicMock()
    fake_equity.build_leg.return_value = fake_leg
    fake_response = MagicMock()
    fake_response.order.id = "12345"
    fake_response.order.status = "Received"

    async def fake_account_get(session, account_id):
        assert account_id == "5WX01234"
        return fake_account

    async def fake_equity_get(session, symbol):
        assert symbol == "AAPL"
        return fake_equity

    fake_account.place_order = AsyncMock(return_value=fake_response)

    with patch("app.data.tastytrade_paper.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_paper.Account.get", side_effect=fake_account_get), \
         patch("app.data.tastytrade_paper.Equity.get", side_effect=fake_equity_get), \
         patch("app.data.tastytrade_paper.LimitOrder") as MockLimitOrder:
        MockLimitOrder.return_value = MagicMock()
        adapter = TastytradePaperAdapter(account_id="5WX01234")
        result = adapter.place_order(_stock_order())

    assert result.order_id == "12345"
    assert result.status == "Received"
    assert result.broker == "tastytrade_paper"
    fake_equity.build_leg.assert_called_once()
    fake_account.place_order.assert_awaited_once()
    assert fake_account.place_order.call_args.kwargs.get("dry_run") is False
    # _stock_order() is a BUY at limit_price=150.0 — BUY must be a debit (negative).
    MockLimitOrder.assert_called_once_with(legs=[fake_leg], price=Decimal("-150.0"))


def test_place_order_wraps_sdk_exception():
    fake_session = MagicMock()

    async def raising_account_get(session, account_id):
        raise RuntimeError("account not found")

    with patch("app.data.tastytrade_paper.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_paper.Account.get", side_effect=raising_account_get):
        adapter = TastytradePaperAdapter(account_id="5WX01234")
        with pytest.raises(RuntimeError, match="tastytrade paper order failed"):
            adapter.place_order(_stock_order())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tastytrade_paper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.tastytrade_paper'`

- [ ] **Step 3: Write the adapter**

Create `backend/app/data/tastytrade_paper.py`:

```python
"""Tastytrade paper-account order execution.

Places stock (STK) and option (OPT) orders on a tastytrade paper-trading
account via the tastytrade SDK. Synchronous place_order() wraps the SDK's
async calls via tastytrade_bridge.run_coro (Task 6) rather than a raw
asyncio.run() — this adapter's calls compete for the same Governor-gated
"tastytrade" token bucket as the IV-metrics fetcher (Task 7) and the health
probe (Task 11), and routing all three through the same shared event loop
avoids the cross-loop asyncio.Lock hazard a bare asyncio.run() per call site
would reintroduce. The resulting place_order(order) -> OrderResult interface
is otherwise identical to IbkrPaperAdapter / AlpacaPaperAdapter — broker_router.py
and every caller in this codebase expects a synchronous place_order(order).

Only "tastytrade_paper" credentials are ever used here. "tastytrade_live" is
prepared in the credential store and in broker_router.py's _LIVE_BROKERS
block list, but no adapter reads tastytrade_live credentials for order
placement anywhere in this codebase — mirrors the ibkr_live/alpaca_live
pattern exactly.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from tastytrade import Account
from tastytrade.instruments import Equity, get_option_chain
from tastytrade.order import LimitOrder, OrderAction

from app.data.ibkr_paper import BrokerOrder, OrderResult
from app.data.tastytrade_bridge import run_coro
from app.data.tastytrade_session import get_session

logger = logging.getLogger(__name__)

_ACTION_MAP = {
    ("BUY", "STK"):  OrderAction.BUY_TO_OPEN,
    ("SELL", "STK"): OrderAction.SELL_TO_CLOSE,
    ("BUY", "OPT"):  OrderAction.BUY_TO_OPEN,
    ("SELL", "OPT"): OrderAction.SELL_TO_CLOSE,
}


class TastytradePaperAdapter:
    def __init__(self, account_id: str) -> None:
        self._account_id = account_id

    async def _resolve_leg(self, session, order: BrokerOrder):
        action = _ACTION_MAP.get((order.action, order.sec_type))
        if action is None:
            raise ValueError(
                f"Unsupported action/sec_type combination: {order.action}/{order.sec_type}"
            )
        if order.sec_type == "STK":
            instrument = await Equity.get(session, order.symbol)
            return instrument.build_leg(order.quantity, action)
        if order.sec_type == "OPT":
            if not order.option_symbol:
                raise ValueError("OPT orders require order.option_symbol (OCC symbol)")
            chain = await get_option_chain(session, order.symbol)
            for expiry_options in chain.values():
                for opt in expiry_options:
                    if opt.symbol == order.option_symbol:
                        return opt.build_leg(order.quantity, action)
            raise ValueError(f"Option contract not found in chain: {order.option_symbol}")
        raise ValueError(f"Unsupported sec_type: {order.sec_type}")

    async def _place_order_async(self, order: BrokerOrder) -> OrderResult:
        session = get_session("tastytrade_paper")
        if session is None:
            raise RuntimeError(
                "tastytrade paper order failed: account not configured. "
                "Add client_secret/refresh_token in Settings → Brokers."
            )
        try:
            account = await Account.get(session, self._account_id)
            leg = await self._resolve_leg(session, order)
            if order.order_type != "LMT" or order.limit_price is None:
                raise ValueError(
                    "TastytradePaperAdapter only supports limit orders "
                    "(tastytrade options orders require a price)."
                )
            # tastytrade LimitOrder price convention: negative = debit (you
            # pay), positive = credit (you receive) — a BUY is always a debit.
            # UNVERIFIED beyond documentation — this is a runtime value
            # convention, not a call signature, so Task 1 Step 4's
            # inspect.signature() check cannot catch a wrong sign here. If
            # this is backwards, every paper order this adapter places
            # carries an inverted price and nothing before Task 15's live
            # dry_run/real order would reveal it. Task 15 Step 4 must
            # explicitly confirm the placed order's price sign matches what
            # was entered, not just that an order_id came back.
            price = Decimal(str(order.limit_price))
            if order.action == "BUY":
                price = -abs(price)
            else:
                price = abs(price)
            new_order = LimitOrder(legs=[leg], price=price)
            response = await account.place_order(session, new_order, dry_run=False)
        except Exception as exc:
            # Found in Round 8 of this plan's audit, empirically reproduced:
            # an earlier draft had `except RuntimeError: raise` before this
            # clause, intended to let the "not configured" error pass through
            # unwrapped — but that check already happens above, outside this
            # try block entirely, so a bare `except RuntimeError: raise` here
            # only ever caught RuntimeErrors raised by the SDK calls inside
            # this try block and re-raised them WITHOUT the
            # "tastytrade paper order failed" prefix, breaking the uniform
            # error-wrapping contract every other adapter in this codebase
            # follows. Removed — every exception from the SDK calls above,
            # RuntimeError included, gets wrapped here.
            raise RuntimeError(f"tastytrade paper order failed: {exc}") from exc

        return OrderResult(
            order_id=str(response.order.id),
            status=str(response.order.status),
            broker="tastytrade_paper",
        )

    def place_order(self, order: BrokerOrder) -> OrderResult:
        return run_coro(self._place_order_async(order))
```

**Known limitation, documented rather than silently shipped:** `_ACTION_MAP` only covers `BUY→BUY_TO_OPEN` and `SELL→SELL_TO_CLOSE` for both STK and OPT — it assumes every trade is opening a new long position or closing one, matching the shape of every existing caller of `BrokerOrder` in this codebase today (long calls/puts, long stock). tastytrade's real `OrderAction` is a 4-way enum (`BUY_TO_OPEN`/`BUY_TO_CLOSE`/`SELL_TO_OPEN`/`SELL_TO_CLOSE`), and `BrokerOrder` (defined in `ibkr_paper.py`, shared across all adapters) has no field indicating open-vs-close intent — so there is currently no way for any caller to request "sell to open" (writing/shorting an option) through this shared interface, not just through tastytrade's adapter specifically. `settingsStore.ts` already has a `SpreadsConfig` (`shortLegDelta`, `minCredit`, `maxDebitPctOfWidth`) suggesting short-leg/credit-spread strategies are a plausible future direction — if that ever needs real execution, `BrokerOrder` itself needs a position-effect field first, and every adapter (not just tastytrade's) would need updating. Out of scope for this plan; flag it as a follow-up if credit-spread execution is ever built.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tastytrade_paper.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/tastytrade_paper.py backend/tests/test_tastytrade_paper.py
git commit -m "feat(tastytrade): add paper order execution adapter"
```

---

## Task 10: Wire into `broker_router.py` and `broker.py` (paper active, live blocked)

**Found in Round 4 of this plan's audit, added to this task's scope rather than as a separate task:** `backend/app/routers/broker.py` was missing from every prior round's file list and from this plan's own "existing patterns this plan must match" investigation summary. It defines `BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper"]` (`broker.py:13`), which gates the request body Pydantic model for the two actual order-placement endpoints — `POST /broker/stock-order` and `POST /broker/option-order` — that the frontend's trade-card send flow calls. Without widening this Literal, selecting "Tastytrade Paper" in Task 14's `BrokerPicker` and sending an order would get rejected with a 422 by FastAPI/Pydantic validation *before the request body is even parsed* — `build_router_from_credentials()` and `BrokerRouter.execute()` (this task's own work) would never run. This is exactly the flow Task 15 Step 4 exercises for live end-to-end verification, and it would fail at the first click without this fix.

**Files:**
- Modify: `backend/app/services/broker_router.py`
- Modify: `backend/app/routers/broker.py`
- Test: `backend/tests/test_broker_router.py` (check first; extend if present, create if not)

- [ ] **Step 1: Write the failing test**

Create/append to `backend/tests/test_broker_router.py`:

```python
import pytest
from unittest.mock import patch, MagicMock

from app.services.broker_router import BrokerRouter, build_router_from_credentials
from app.data.ibkr_paper import BrokerOrder


def test_tastytrade_live_is_blocked():
    router = BrokerRouter(adapters={"tastytrade_live": MagicMock()})
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                         order_type="MKT", limit_price=None, sec_type="STK")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("tastytrade_live", order)


def test_build_router_from_credentials_includes_tastytrade_paper_when_configured():
    fake_creds = {
        "ibkr_paper": None,
        "tradier_paper": {},
        "alpaca_paper": None,
        "tastytrade_paper": {"client_secret": "x", "refresh_token": "y", "account_id": "5WX01234"},
    }
    with patch("app.services.credential_store.credential_store.load"), \
         patch("app.services.credential_store.credential_store.get",
               side_effect=lambda k: fake_creds.get(k)):
        router = build_router_from_credentials()
    assert "tastytrade_paper" in router._adapters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_broker_router.py -v`
Expected: FAIL — `"tastytrade_live"` not in `_LIVE_BROKERS` (first test doesn't raise); `"tastytrade_paper"` never added to adapters (second test's assertion fails).

- [ ] **Step 3: Update `broker_router.py`**

Modify `backend/app/services/broker_router.py`:

```python
from __future__ import annotations

from app.data.ibkr_paper import BrokerOrder, OrderResult

_LIVE_BROKERS = {"ibkr_live", "alpaca_live", "tastytrade_live"}  # Blocked until manually enabled in a future release.


class BrokerRouter:
    """Routes a BrokerOrder to the correct adapter by broker key.

    broker_key values: "ibkr_paper" | "tradier_paper" | "alpaca_paper" | "tastytrade_paper"
    "ibkr_live" / "alpaca_live" / "tastytrade_live" are prepared but blocked (raises ValueError).
    """

    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters

    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        if broker_key in _LIVE_BROKERS:
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


def build_router_from_credentials() -> BrokerRouter:
    """Build a BrokerRouter using live credentials from the credential store."""
    from app.services.credential_store import credential_store
    credential_store.load()  # pick up any yaml edits without requiring a restart
    from app.data.ibkr_paper import IbkrPaperAdapter
    from app.data.tradier_paper import TradierPaperAdapter
    from app.data.alpaca_paper_execution import AlpacaPaperAdapter
    from app.data.tastytrade_paper import TastytradePaperAdapter

    adapters = {}
    ibkr = credential_store.get("ibkr_paper")
    if ibkr and ibkr.get("account_id"):
        adapters["ibkr_paper"] = IbkrPaperAdapter(
            base_url=ibkr.get("base_url", "https://localhost:7499/v1/api"),
            account_id=ibkr["account_id"],
        )
    import os as _os
    tradier = credential_store.get("tradier_paper") or {}
    tradier_token = (tradier.get("token") or "").strip() or _os.environ.get("TRADIER_PAPER_TOKEN", "").strip()
    tradier_account = (tradier.get("account_id") or "").strip() or _os.environ.get("TRADIER_PAPER_ACCOUNT_ID", "").strip()
    if tradier_token and tradier_account:
        adapters["tradier_paper"] = TradierPaperAdapter(
            token=tradier_token,
            account_id=tradier_account,
        )
    alpaca = credential_store.get("alpaca_paper")
    if alpaca and alpaca.get("key_id") and alpaca.get("secret_key"):
        adapters["alpaca_paper"] = AlpacaPaperAdapter(
            key_id=alpaca["key_id"],
            secret_key=alpaca["secret_key"],
        )
    tastytrade = credential_store.get("tastytrade_paper")
    if tastytrade and tastytrade.get("client_secret") and tastytrade.get("refresh_token") and tastytrade.get("account_id"):
        adapters["tastytrade_paper"] = TastytradePaperAdapter(account_id=tastytrade["account_id"])
    return BrokerRouter(adapters=adapters)
```

- [ ] **Step 4: Update the pre-existing blocked-live test — the message text changed and this would otherwise break it**

Found in Round 3 of this plan's audit: the real, currently-passing `backend/tests/test_broker_router.py:44` (`test_router_raises_for_inactive_live` or equivalently named) asserts `pytest.raises(ValueError, match="live IBKR")`, matching the *current* code's IBKR-specific message (`f"live IBKR trading is not yet activated..."`, `broker_router.py:20-22`). Step 3's rewrite generalizes that message to `f"live trading via '{broker_key}' is not yet activated."` so it reads sensibly for `alpaca_live`/`tastytrade_live` too — but `"live trading via 'ibkr_live' is not yet activated"` no longer contains the substring `"live IBKR"`, so the existing test would fail the moment this task lands. Find that test (`grep -n 'match="live IBKR"' backend/tests/test_broker_router.py`) and update its assertion to match the new generic message:

```python
    with pytest.raises(ValueError, match="not yet activated"):
```

This is a deliberate, in-scope update to an existing test caused by this task's own change — not an unrelated edit.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_broker_router.py -v`
Expected: PASS, including the updated pre-existing test.

- [ ] **Step 6: Widen `broker.py`'s `BrokerKey` Literal so tastytrade orders reach the router at all**

Write the failing test first. Append to `backend/tests/test_broker_router.py` (this test exercises the actual HTTP route, not just `BrokerRouter` in isolation, since that's the layer Round 4 found the real gap in):

```python
import pytest as _pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@_pytest.mark.asyncio
async def test_stock_order_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/broker/stock-order", json={
            "broker": "tastytrade_paper", "symbol": "AAPL",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
        })
    # No tastytrade credentials configured in this test environment, so the
    # expected failure is 503 (credentials unavailable) or 502 (adapter
    # error) from inside the route — NOT 422, which would mean the Literal
    # still rejects "tastytrade_paper" before the route body even runs.
    assert resp.status_code != 422, (
        f"broker.py's BrokerKey Literal still rejects 'tastytrade_paper' "
        f"(got {resp.status_code}, body: {resp.text})"
    )
```

Run: `cd backend && pytest tests/test_broker_router.py::test_stock_order_accepts_tastytrade_paper_broker_key -v`
Expected: FAIL with a 422 response, confirming the Literal is the blocker.

Modify `backend/app/routers/broker.py:13`:

```python
BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"]
```

Also update `broker_status()` (`broker.py:135-148`) for consistency with the other paper brokers it already reports, even though this endpoint is only consumed by Stocks-mode components out of this plan's scope — leaving it stale would misreport tastytrade as never-configured to anything that does read it later:

```python
@router.get("/status")
async def broker_status() -> dict:
    """Return which brokers are configured (no credentials exposed)."""
    r = build_router_from_credentials()
    ibkr_ok       = "ibkr_paper"       in r._adapters
    trad_ok       = "tradier_paper"    in r._adapters
    alpaca_ok     = "alpaca_paper"     in r._adapters
    tastytrade_ok = "tastytrade_paper" in r._adapters
    return {
        "ibkr_paper":       {"configured": ibkr_ok},
        "tradier_paper":    {"configured": trad_ok},
        "alpaca_paper":     {"configured": alpaca_ok},
        "tastytrade_paper": {"configured": tastytrade_ok},
        "ibkr_live":        {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "alpaca_live":      {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "tastytrade_live":  {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
    }
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && pytest tests/test_broker_router.py -v`
Expected: PASS, including `test_stock_order_accepts_tastytrade_paper_broker_key` now returning something other than 422 (503, since no real tastytrade credentials exist in the test environment, is the expected non-422 outcome).

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/broker_router.py backend/app/routers/broker.py backend/tests/test_broker_router.py
git commit -m "feat(broker-router): wire tastytrade_paper as an execution target, block tastytrade_live, widen broker.py's BrokerKey"
```

---

## Task 11: Data-source health probes

**Files:**
- Modify: `backend/app/routers/data_sources.py`
- Test: `backend/tests/test_data_sources.py` (check first; extend if present)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_data_sources.py` (create if it doesn't exist, matching the existing router-test style used elsewhere in this plan):

```python
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_data_sources_includes_tastytrade_entries():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data-sources")
    ids = {s["id"] for s in resp.json()}
    assert "tastytrade" in ids
    assert "tastytrade_paper" in ids


@pytest.mark.asyncio
async def test_probe_tastytrade_unconfigured_when_no_credentials():
    from app.routers.data_sources import _probe_tastytrade
    with patch("app.data.tastytrade_session.get_session", return_value=None):
        status, detail = _probe_tastytrade("tastytrade_paper")
    assert status == "unconfigured"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_data_sources.py -v`
Expected: FAIL — `"tastytrade"` not in the returned IDs; `_probe_tastytrade` doesn't exist.

- [ ] **Step 3: Add the probe function and register it — routed through the Governor, not a bare call**

`_probe_ibkr_gateway`/`_probe_tradier`/`_probe_alpaca` are all cheap, low-cost status endpoints (`/auth/status`, `/v1/markets/clock`, `/v2/account`) — none of them touch a rate-sensitive data endpoint. `market-metrics` is not cheap in the same sense: it's the exact endpoint Task 4's conservative `rate=1.0` Governor budget exists to protect, since there is no published production rate limit for it. `/api/data-sources` gets polled by the frontend (ContextRail's `QuickLook` component, per this codebase) on every mount and after every scan completion, and `_PROBE_CACHE`'s 45-second TTL (`data_sources.py:22`) means a real call fires at most every 45 seconds *from the probe's own cache* — but that cache is entirely independent of the Governor's token bucket. Calling `get_market_metrics` directly here, uncoordinated with every other caller of `fetch_iv_metrics_tastytrade` during an active scan, is exactly the kind of uncoordinated-call pattern that defeats a shared rate limit. Route it through the same `Governor.call("tastytrade", ...)` gate everything else in this plan uses — and through Task 6's `tastytrade_bridge.run_coro`, not a bare `asyncio.run()`, for the same cross-loop `asyncio.Lock` reason as every other sync-to-async tastytrade call site in this plan:

Modify `backend/app/routers/data_sources.py` — add this function near `_probe_ibkr_gateway` (after it):

```python
def _probe_tastytrade(slot: str) -> tuple[str, str | None]:
    from app.data.tastytrade_session import get_session
    session = get_session(slot)
    if session is None:
        return "unconfigured", f"Add tastytrade OAuth client_secret/refresh_token in Settings → Brokers ({slot})"
    try:
        from tastytrade.metrics import get_market_metrics
        from app.data.governor import get_governor
        from app.data.tastytrade_bridge import run_coro

        async def _check():
            await get_governor().call("tastytrade", lambda: get_market_metrics(session, ["SPY"]))

        run_coro(_check())
        return "connected", None
    except Exception as exc:
        return "down", str(exc)
```

This means a health-check poll competes for the same token bucket as real IV-fetch calls during a scan — that's intentional: it's better for the dashboard dot to occasionally show `"degraded"` (Governor circuit state, via `_status_for_probe`) under load than for the probe to silently punch a hole through the one rate-limiting mechanism this plan was built around. If this makes the dot noisy in practice (frequent `"degraded"` readings just from probe contention), the right fix is to lower `_CACHE_TTL` polling pressure or give the probe its own tiny separate token allowance in the Governor — not to bypass the Governor again.

Then modify the `sources` list inside `get_data_sources()` — add two rows (after the `ibkr_paper` row, keeping the existing table format):

```python
        ("tastytrade",       "Tastytrade (IV data)", ["IV rank", "IV percentile"], lambda: _probe_tastytrade("tastytrade_paper"), "tastytrade"),
        ("tastytrade_paper", "Tastytrade (paper)",    ["paper stock/option orders"], lambda: _probe_tastytrade("tastytrade_paper"), None),
```

Note both rows probe the same `tastytrade_paper` slot deliberately — there is one funded account behind both the IV-data role and the paper-execution role, per Kenneth's stated setup (unlike Alpaca/Tradier where "(data)" and "(paper)" can be genuinely different credentials).

- [ ] **Step 4: Register "tastytrade" with the Governor-backed health check**

This entry passes `gov_name="tastytrade"` (matching Task 4's Governor registration), so `_status_for_probe` can demote a healthy probe to `"degraded"` when the circuit breaker has tripped — same mechanism already used for `alpaca`/`tradier`/`tiingo`/`yfinance`/`ibkr`. No additional code needed beyond the tuple above; verify by reading `_status_for_probe` (lines 137-145) if unsure — it already handles any `gov_name` present in the Governor's `_providers` dict generically.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_data_sources.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/data_sources.py backend/tests/test_data_sources.py
git commit -m "feat(data-sources): add tastytrade health probes"
```

---

## Task 12: Frontend — Zustand config types, defaults, and versioned migration

**Files:**
- Modify: `frontend/lib/settingsStore.ts`

- [ ] **Step 1: Add the config interfaces and defaults**

In `frontend/lib/settingsStore.ts`, add these near the existing `AlpacaPaperConfig`/`AlpacaLiveConfig` block (after line 131, before line 138's `DEFAULT_TRADIER_PAPER`):

```typescript
export interface TastytradePaperConfig {
  clientSecret:  string;
  refreshToken:  string;
  accountId:     string;
}

export interface TastytradeLiveConfig {
  enabled: false;   // always false until manually unlocked in a future release
  note:    string;
}

export const DEFAULT_TASTYTRADE_PAPER: TastytradePaperConfig = {
  clientSecret: '',
  refreshToken: '',
  accountId:    '',
};

export const DEFAULT_TASTYTRADE_LIVE: TastytradeLiveConfig = {
  enabled: false,
  note:    'Live tastytrade trading is prepared but not yet activated.',
};
```

- [ ] **Step 2: Add to the state interface and setters**

Modify the state interface (near line 179-183):

```typescript
  tradierPaper:                TradierPaperConfig;
  tradierLive:                 TradierLiveConfig;
  ibkrLive:                    IbkrLiveConfig;
  alpacaPaper:                 AlpacaPaperConfig;
  alpacaLive:                  AlpacaLiveConfig;
  tastytradePaper:             TastytradePaperConfig;
  tastytradeLive:              TastytradeLiveConfig;
```

And the setters (near line 198-200):

```typescript
  setTradierPaper:             (c: TradierPaperConfig) => void;
  setTradierLive:              (c: TradierLiveConfig)  => void;
  setAlpacaPaper:              (c: AlpacaPaperConfig)  => void;
  setTastytradePaper:          (c: TastytradePaperConfig) => void;
```

- [ ] **Step 3: Add the versioned migration branch**

Modify the `migrateSettings` function — add a new branch after the last existing version-gated block (confirmed by reading the file directly: the highest existing branch is `if (version < 19)` near line 245, matching the persisted version of `19` this plan's own investigation notes already record — add the new branch after that one; the branch order among `if` statements doesn't affect correctness, but keep it appended in ascending order for readability):

```typescript
  if (version < 20) {
    next.tastytradePaper = { ...DEFAULT_TASTYTRADE_PAPER };
    next.tastytradeLive  = { ...DEFAULT_TASTYTRADE_LIVE };
  }
```

- [ ] **Step 4: Add to initial state, reset, and partialize**

In the store creator's initial state (near line 264-268):

```typescript
      tradierPaper:         { ...DEFAULT_TRADIER_PAPER },
      tradierLive:          { ...DEFAULT_TRADIER_LIVE },
      ibkrLive:             { ...DEFAULT_IBKR_LIVE },
      alpacaPaper:          { ...DEFAULT_ALPACA_PAPER },
      alpacaLive:           { ...DEFAULT_ALPACA_LIVE },
      tastytradePaper:      { ...DEFAULT_TASTYTRADE_PAPER },
      tastytradeLive:       { ...DEFAULT_TASTYTRADE_LIVE },
      setTradierPaper:              (c) => set({ tradierPaper: c }),
      setTradierLive:                (c) => set({ tradierLive: c }),
      setAlpacaPaper:                (c) => set({ alpacaPaper: c }),
      setTastytradePaper:            (c) => set({ tastytradePaper: c }),
```

In `resetToDefaults` (near line 297-301):

```typescript
        tradierPaper: { ...DEFAULT_TRADIER_PAPER },
        tradierLive:  { ...DEFAULT_TRADIER_LIVE },
        ibkrLive:     { ...DEFAULT_IBKR_LIVE },
        alpacaPaper:  { ...DEFAULT_ALPACA_PAPER },
        alpacaLive:   { ...DEFAULT_ALPACA_LIVE },
        tastytradePaper: { ...DEFAULT_TASTYTRADE_PAPER },
        tastytradeLive:  { ...DEFAULT_TASTYTRADE_LIVE },
```

In `partialize` (near line 314-319, add alongside the other broker fields):

```typescript
        tastytradePaper:         state.tastytradePaper,
        tastytradeLive:          state.tastytradeLive,
```

- [ ] **Step 5: Bump the persisted version**

Modify line 313: `version: 19,` → `version: 20,`

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors). This is the only verification step available for this task — Zustand config plumbing has no dedicated unit test in this codebase's existing pattern (confirmed: no `settingsStore.test.ts` exists for the other broker slices either).

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/settingsStore.ts
git commit -m "feat(settings): add tastytrade paper/live config to settingsStore (v20)"
```

---

## Task 13: Frontend — Settings → Brokers panel

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx:1281-1490` (`BrokersForm`)

- [ ] **Step 1: Add state and save handler**

In `BrokersForm` (around line 1282-1298), add to the destructured store values:

```typescript
    tastytradePaper, setTastytradePaper,
    tastytradeLive,
```

Add local state (near line 1296-1298):

```typescript
  const [tastyClientSecret, setTastyClientSecret] = useState(tastytradePaper.clientSecret);
  const [tastyRefreshToken, setTastyRefreshToken] = useState(tastytradePaper.refreshToken);
  const [tastyAccountId,    setTastyAccountId]    = useState(tastytradePaper.accountId);
```

Add sync-on-reset effects (near line 1307-1308):

```typescript
  useEffect(() => { setTastyClientSecret(tastytradePaper.clientSecret); }, [tastytradePaper.clientSecret]);
  useEffect(() => { setTastyRefreshToken(tastytradePaper.refreshToken); }, [tastytradePaper.refreshToken]);
  useEffect(() => { setTastyAccountId(tastytradePaper.accountId); },       [tastytradePaper.accountId]);
```

Add the save handler (near line 1331-1336, after `saveAlpacaPaper`):

```typescript
  async function saveTastytradePaper() {
    setSaving('tastytrade');
    setTastytradePaper({ clientSecret: tastyClientSecret, refreshToken: tastyRefreshToken, accountId: tastyAccountId });
    await api.postCredentials('tastytrade_paper', {
      client_secret: tastyClientSecret, refresh_token: tastyRefreshToken, account_id: tastyAccountId,
    });
    setSaving(null);
  }
```

- [ ] **Step 2: Add the UI section**

In the returned JSX, add this block after the existing Alpaca Paper section (after line 1467, before the "IBKR Live (Locked)" section):

```tsx
      <SectionIntro
        title="Tastytrade Paper account"
        blurb="Real IV Rank/Percentile data and paper stock/option orders via tastytrade. Create an OAuth Grant at Tastytrade → My Profile → API to get a client secret + refresh token."
      />
      <Row label="Client secret" hint="From your tastytrade OAuth application" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tastyClientSecret}
          onChange={(e) => setTastyClientSecret(e.target.value)}
        />
      </Row>
      <Row label="Refresh token" hint="Never expires — generated once via Create Grant" defaultValue="—">
        <input
          className={styles.input}
          type="password"
          placeholder="leave blank to keep saved value"
          value={tastyRefreshToken}
          onChange={(e) => setTastyRefreshToken(e.target.value)}
        />
      </Row>
      <Row label="Account ID" hint="Your tastytrade paper account number (5WX...)" defaultValue="—">
        <input
          className={styles.input}
          value={tastyAccountId}
          onChange={(e) => setTastyAccountId(e.target.value)}
        />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTastytradePaper}
            disabled={saving === 'tastytrade'}
          >
            {saving === 'tastytrade' ? 'Saving…' : 'Save Tastytrade Paper'}
          </button>
        </div>
      </div>
```

Then add a locked section alongside the existing "IBKR Live (Locked)" / "Alpaca Live (Locked)" blocks (after line 1487):

```tsx
      <SectionIntro
        title="Tastytrade Live (Locked)"
        blurb={tastytradeLive.note}
      />
      <Row label="Live trading" hint="Requires explicit activation — not yet enabled" defaultValue="Off">
        <button className={styles.btn} disabled title="Locked until manually activated">
          Activate live Tastytrade
        </button>
      </Row>
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Manual verification**

Run: `cd frontend && npm run dev` (or use the project's browser-preview workflow), navigate to Settings → Brokers, confirm the "Tastytrade Paper account" section renders with three inputs and a save button, and "Tastytrade Live (Locked)" renders with a disabled button. Enter dummy values, click Save, confirm no console errors and a network POST to `/settings/credentials` with `key: "tastytrade_paper"`.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/\(frame\)/settings/page.tsx
git commit -m "feat(settings): add Tastytrade Paper/Live sections to Brokers panel"
```

---

## Task 14: Frontend — wire `tastytrade_paper` into the broker picker, and the backend auto-trade gate it feeds

**Found in Round 6 of this plan's audit — a second, sibling gap to Round 4's `broker.py` finding, in a router none of the first five rounds ever opened:** `backend/app/routers/auto_trade.py:16`'s `ArmRequest.broker` is `Literal["ibkr_paper", "tradier_paper"]` — it doesn't even include `alpaca_paper` (a pre-existing gap, out of scope here), and obviously doesn't include `tastytrade_paper` either. This task's own `selectedBroker` (the `OptionsBroker` value from Step 1 below) flows directly into `<AutoTradeArm broker={selectedBroker} />` in `step-7-trade-card/page.tsx`, which POSTs to `/auto-trade/arm`. Once this task lands, selecting "Tastytrade Paper" and arming an auto-trade would 422 at this endpoint before `auto_trader.arm()` ever runs — the exact same failure shape as Round 4's `broker.py` finding, just in `auto_trade.py` instead. Fixed as Step 5 below, folded into this task since it's the same "make the newly-selectable broker key actually reach a backend endpoint" concern this task already owns for `BrokerPicker`.

**Files:**
- Modify: `frontend/lib/autoTradeStore.ts:4`
- Modify: `frontend/components/organisms/BrokerPicker/index.tsx`
- Modify: `backend/app/routers/auto_trade.py:16`
- Test: `backend/tests/test_auto_trade.py` (check first; create if not present)

- [ ] **Step 1: Widen the `OptionsBroker` type**

In `frontend/lib/autoTradeStore.ts`, modify line 4:

```typescript
export type OptionsBroker = 'ibkr_paper' | 'tradier_paper' | 'tastytrade_paper';
```

- [ ] **Step 2: Add the picker entry**

In `frontend/components/organisms/BrokerPicker/index.tsx`, modify:

```tsx
export function BrokerPicker({ selected, onChange }: BrokerPickerProps) {
  const { ibkrPaper, tradierPaper, tastytradePaper } = useSettingsStore();
  const ibkrOk    = !!ibkrPaper.accountId;
  const tradierOk = !!tradierPaper.token && !!tradierPaper.accountId;
  const tastyOk   = !!tastytradePaper.clientSecret && !!tastytradePaper.refreshToken && !!tastytradePaper.accountId;

  return (
    <div className={styles.wrap}>
      <Text size={11} tone="dim">Execute via</Text>
      <div className={styles.row}>
        {([
          { key: 'ibkr_paper' as OptionsBroker, label: 'IBKR Paper', ok: ibkrOk },
          { key: 'tradier_paper' as OptionsBroker, label: 'Tradier Paper', ok: tradierOk },
          { key: 'tastytrade_paper' as OptionsBroker, label: 'Tastytrade Paper', ok: tastyOk },
        ] as const).map(({ key, label, ok }) => (
          <button
            key={key}
            type="button"
            className={`${styles.btn} ${selected === key ? styles.btnActive : ''}`}
            disabled={!ok}
            onClick={() => onChange(key)}
            title={!ok ? 'Configure in Settings → Brokers' : undefined}
          >
            <Text size={12} weight={selected === key ? 600 : 400}>{label}</Text>
            {!ok && <Text size={10} tone="dim">Not configured</Text>}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Check for other `OptionsBroker` exhaustive switches**

Run: `cd frontend && grep -rn "OptionsBroker" --include=*.tsx --include=*.ts .` (or use the project's Grep tool) and confirm any `switch`/if-else chain over `OptionsBroker` values (e.g. in `broker_router`-calling code on the frontend, if any exists) has a case for `'tastytrade_paper'`. If TypeScript's `--strict` mode flags a non-exhaustive switch, add the missing case; if nothing flags, no further change is needed.

- [ ] **Step 5: Widen `auto_trade.py`'s `ArmRequest.broker` so arming a tastytrade auto-trade doesn't 422**

Write the failing test first. Check whether `backend/tests/test_auto_trade.py` already exists; create it if not, append if it does:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_arm_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
            "entry_premium": 3.50,  # required: AutoTradeService.arm() raises ValueError
                                    # if entry_premium <= 0 (auto_trader.py:139-144),
                                    # and that ValueError propagates uncaught through
                                    # the /auto-trade/arm route (no try/except there) —
                                    # omitting this makes the request error out with an
                                    # unrelated unhandled exception instead of ever
                                    # reaching the Literal validation this test exists
                                    # to check. Found by empirical reproduction during
                                    # this plan's Round 7 audit.
        })
    assert resp.status_code != 422, (
        f"auto_trade.py's ArmRequest.broker Literal still rejects 'tastytrade_paper' "
        f"(got {resp.status_code}, body: {resp.text})"
    )
    # Disarm immediately so this test doesn't leave a real armed strategy for
    # any other test in the suite to trip over.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.delete("/auto-trade/arm")
```

Run: `cd backend && pytest tests/test_auto_trade.py::test_arm_accepts_tastytrade_paper_broker_key -v`
Expected: FAIL with a 422 response, confirming the Literal is the blocker — same failure shape as Task 10's `broker.py` fix.

Modify `backend/app/routers/auto_trade.py:16`:

```python
class ArmRequest(BaseModel):
    broker:          Literal["ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"]
```

(`alpaca_paper` is added here too since it was already missing before this plan — a pre-existing gap directly adjacent to the one this task fixes, cheap to close in the same edit rather than leaving it half-fixed.)

Run: `cd backend && pytest tests/test_auto_trade.py -v`
Expected: PASS, including the disarm cleanup.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/autoTradeStore.ts frontend/components/organisms/BrokerPicker/index.tsx backend/app/routers/auto_trade.py backend/tests/test_auto_trade.py
git commit -m "feat(broker-picker): add Tastytrade Paper as an execution target, widen auto_trade.py's ArmRequest.broker"
```

---

## Task 15: End-to-end manual verification against the real funded account

**Files:** none (verification only)

- [ ] **Step 1: Configure real credentials**

In the running app, go to Settings → Brokers → Tastytrade Paper, enter the real `client_secret` / `refresh_token` / paper account ID from a tastytrade OAuth Grant (My Profile → API on tastytrade.com), click Save.

- [ ] **Step 2: Verify the data-source dot**

Navigate to wherever `/api/data-sources` is rendered (ContextRail QuickLook, per this conversation's earlier findings) and confirm both "Tastytrade (IV data)" and "Tastytrade (paper)" show green/connected, not red.

- [ ] **Step 3: Verify IV Rank/Percentile flows into a real contract scan**

Run a scan (or call `/api/contracts` directly for a liquid symbol like SPY or AAPL) with IBKR still down (its current known state per this conversation), and confirm the returned `ivPercentile` is non-zero — proof the tastytrade fallback tier is firing, not just the raw-IV proxy.

- [ ] **Step 4: Place one real (paper) test order**

From the Trade Card / send-to-broker flow, select "Tastytrade Paper" in the BrokerPicker, send one small test order, and confirm it appears as a position in the actual tastytrade paper account (log into tastytrade.com's paper dashboard to confirm) — this is the one step that proves the SDK's exact wire format (verified only from docs, not from a live call, everywhere earlier in this plan) actually works end-to-end. **Also explicitly confirm the order's price sign is correct** — check the actual limit price shown in the tastytrade paper dashboard against what was entered in the trade card. `TastytradePaperAdapter`'s debit/credit sign convention (`tastytrade_paper.py`, the price-flipping logic for BUY vs SELL) was never independently verified beyond documentation; a wrong sign here would place every future order at an inverted price and nothing before this step would catch it.

- [ ] **Step 5: Confirm the rate limiter doesn't trip under normal use**

Run a full scan across a realistic universe size (SP500+NDX100+DOW30 scope, matching `edgar_scheduler.py`'s existing prefetch universe) and check backend logs for `"tastytrade circuit open"` warnings (from `tastytrade_iv.py`'s `_fetch_async`). If it trips, the Governor's `rate=1.0` in Task 4 is too aggressive for the actual scan's calling pattern — batch the `fetch_iv_metrics_tastytrade` calls (pass multiple symbols per `get_market_metrics` call, which the SDK signature already supports — `symbols: Iterable[str]` — rather than calling once per symbol) before loosening the rate limit.

- [ ] **Step 6: Report back**

Confirm all four checks pass, or document exactly which step failed and what error/log output appeared, before considering this integration complete.

---

## Task 16: Remaining broker-label and Stocks-mode picker gaps (found in Round 5 audit)

**Why this task exists:** Round 5's audit deliberately looked outward from every file the plan already touches — the same discipline that found Round 4's `broker.py` gap — and found four more places that hardcode the same three-broker list (`ibkr_paper`/`tradier_paper`/`alpaca_paper`) this plan's other tasks already extend elsewhere, plus one stale type. None of these block Task 15's Options-mode end-to-end verification (that flow goes through `BrokerPicker`/`autoTradeStore.ts`, already fixed in Task 14), which is why this task is separate and can land after Task 15 rather than blocking it — but leaving these unfixed means tastytrade positions get mislabeled in the portfolio, and Stocks-mode users can never select tastytrade at all despite `TastytradePaperAdapter` (Task 9) fully supporting `STK` orders.

**Files:**
- Modify: `frontend/lib/api.ts:458-464` (`getBrokerStatus` return type)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:218` (`brokerLabel` ternary)
- Modify: `frontend/components/organisms/StockSendDialog/index.tsx:24,40-53,119-124`
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx:37,165-167,338-342`
- Modify: `frontend/app/(frame)/screener/step-7-position-card/page.tsx:13,51-53,160-166`
- Modify: `frontend/components/organisms/ContextRail/QuickLook.tsx:107-111`

- [ ] **Step 1: Fix `getBrokerStatus`'s stale return type**

`frontend/lib/api.ts:458-464`'s hardcoded return type is already missing `alpaca_live` (a pre-existing gap, not caused by this plan) and would now also miss `tastytrade_paper`/`tastytrade_live` once Task 10's `broker_status()` rewrite adds them to the real response. Modify:

```typescript
  getBrokerStatus: () =>
    get<{
      ibkr_paper:        { configured: boolean };
      tradier_paper:     { configured: boolean };
      alpaca_paper:      { configured: boolean };
      tastytrade_paper:  { configured: boolean };
      ibkr_live:         { configured: boolean; enabled: boolean; note: string };
      alpaca_live:       { configured: boolean; enabled: boolean; note: string };
      tastytrade_live:   { configured: boolean; enabled: boolean; note: string };
    }>('/broker/status'),
```

- [ ] **Step 2: Fix the mislabeled paper position in the Options trade card**

`step-7-trade-card/page.tsx:218` currently reads `const brokerLabel = broker === 'tradier_paper' ? 'Tradier Paper' : 'IBKR Paper';` — a two-way ternary that silently mislabels every non-Tradier, non-IBKR broker as "IBKR Paper". Once Task 14 lets `broker` be `'tastytrade_paper'`, every tastytrade-executed position would show as "IBKR Paper" in the portfolio. Replace with an explicit mapping:

```typescript
    const brokerLabel =
      broker === 'tradier_paper' ? 'Tradier Paper' :
      broker === 'tastytrade_paper' ? 'Tastytrade Paper' :
      'IBKR Paper';
```

- [ ] **Step 3: Add tastytrade to the Stocks-mode send dialog**

`StockSendDialog/index.tsx:24` — widen the type and add the picker entry:

```typescript
type BrokerMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';
```

Add state and a configured-check, mirroring the existing `alpacaConfigured` pattern (lines 40, 49-54):

```typescript
  const [tastytradeConfigured, setTastytradeConfigured] = useState(false);
  // ...alongside the existing useEffect:
  useEffect(() => {
    api
      .getBrokerStatus()
      .then((s) => {
        setAlpacaConfigured(s.alpaca_paper?.configured ?? false);
        setTastytradeConfigured(s.tastytrade_paper?.configured ?? false);
      })
      .catch(() => {});
  }, []);
```

Add the row to `brokerOptions` (line 119-124):

```typescript
  const brokerOptions: Array<[BrokerMode, string, boolean]> = [
    ['recommendation', 'Recommendation', true],
    ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
    ['tradier_paper', 'Tradier Paper',   tradierConfigured],
    ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
    ['tastytrade_paper', 'Tastytrade Paper', tastytradeConfigured],
  ];
```

- [ ] **Step 4: Add tastytrade to `StockPositionCard`**

`StockPositionCard/index.tsx:37` — same widening:

```typescript
type ExecMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';
```

Add a `tastytradeConfigured` state fetched alongside the existing `alpacaConfigured` fetch (line 165-167):

```typescript
    api.getBrokerStatus()
      .then((s) => {
        setAlpacaConfigured(s.alpaca_paper?.configured ?? false);
        setTastytradeConfigured(s.tastytrade_paper?.configured ?? false);
      })
      .catch(() => {});
```

Add the row to the options array (line 338-342):

```typescript
          ['recommendation', 'Recommendation', true],
          ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
          ['tradier_paper', 'Tradier Paper',   tradierConfigured],
          ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
          ['tastytrade_paper', 'Tastytrade Paper', tastytradeConfigured],
        ] as Array<[ExecMode, string, boolean]>).map(([mode, label, ok]) => (
```

- [ ] **Step 5: Add tastytrade to `step-7-position-card`**

`step-7-position-card/page.tsx:13` — widen `ExecutionMode`:

```typescript
type ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';
```

Add a `tastytradePaperConfigured` state fetched alongside `alpacaPaperConfigured` (line 51-53):

```typescript
    api.getBrokerStatus().then((s) => {
      setAlpacaPaperConfigured(s.alpaca_paper?.configured ?? false);
      setTastytradePaperConfigured(s.tastytrade_paper?.configured ?? false);
    }).catch(() => {/* silently ignore — button stays disabled */});
```

Add the button alongside the existing three (line 160-166):

```tsx
          <ExecutionModeButton label="Alpaca Paper" desc="Direct stock order"
            active={execMode === 'alpaca_paper'} disabled={!alpacaPaperConfigured} onClick={() => setExecMode('alpaca_paper')} />
          <ExecutionModeButton label="Tastytrade Paper" desc="Direct stock order via tastytrade"
            active={execMode === 'tastytrade_paper'} disabled={!tastytradePaperConfigured} onClick={() => setExecMode('tastytrade_paper')} />
```

- [ ] **Step 6: Group tastytrade into the ContextRail data-source display**

`QuickLook.tsx:107-111` — without this, the two tastytrade rows (Task 11's `"tastytrade"`/`"tastytrade_paper"` IDs) fall into the ungrouped "other" bucket instead of a proper grouped display, unlike every other broker:

```typescript
const BROKER_FAMILIES = [
  { prefix: 'alpaca',     ids: ['alpaca', 'alpaca_paper'] },
  { prefix: 'ibkr',       ids: ['ibkr', 'ibkr_paper'] },
  { prefix: 'tradier',    ids: ['tradier', 'tradier_paper'] },
  { prefix: 'tastytrade', ids: ['tastytrade', 'tastytrade_paper'] },
];
```

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 8: Manual verification**

Using the project's browser-preview workflow: open the Stocks-mode send dialog (`StockSendDialog`) and `StockPositionCard`/`step-7-position-card`, confirm "Tastytrade Paper" appears as a selectable option (enabled once Task 12's Brokers-panel credentials are saved), and confirm a completed Options-mode paper trade sent via tastytrade shows "Tastytrade Paper" (not "IBKR Paper") in the portfolio. Confirm the ContextRail data-source panel groups the two tastytrade rows together rather than in an "other" bucket.

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/api.ts \
        frontend/app/\(frame\)/screener/step-7-trade-card/page.tsx \
        frontend/components/organisms/StockSendDialog/index.tsx \
        frontend/components/organisms/StockPositionCard/index.tsx \
        frontend/app/\(frame\)/screener/step-7-position-card/page.tsx \
        frontend/components/organisms/ContextRail/QuickLook.tsx
git commit -m "feat(tastytrade): wire remaining Stocks-mode pickers, fix broker mislabeling, group ContextRail display"
```

---

## Self-review notes (from the plan-writing process, kept for the executor's awareness)

- **Spec coverage:** paper execution target (Task 9-10), live prepared-but-blocked (Task 2, 10), IV Rank/Percentile without IBKR (Task 7-8), rate limiting to avoid account lockout (Task 4, and Task 6's event-loop bridge added in Round 2), graph enhancement (explicitly deferred per Kenneth's own decision — see header). All four of Kenneth's requirements are covered except the deferred one.
- **The batching note in Task 15 Step 5 is a known, called-out risk, not swept under the rug:** `fetch_iv_metrics_tastytrade` as written in Task 7 is called once per symbol from `market.py` (matching the existing per-symbol call pattern for `fetch_iv_metrics_ibkr`), which under a conservative `rate=1.0` Governor budget means a 500-symbol universe would take over 8 minutes serialized through this one tier alone. This is flagged explicitly in Task 15 rather than silently shipped — if it's a problem in practice, `market.py`'s call site should be changed to batch-fetch IV metrics for the whole scan universe once upfront (the SDK already supports multi-symbol calls) rather than per-contract-chain-request; that's a follow-up, not blocking this plan's initial land.

## Round 1 adversarial audit — findings and fixes

A fresh subagent ran `bmad-review-adversarial-general` against this plan and cross-checked its claims against the real code (`market.py`, `ibkr_paper.py`, `alpaca.py`, `data_sources.py`, `test_market_data_fixes.py`, etc.), not just for internal consistency. Findings and resolutions:

1. **Fixed — Task 8's test used a monkeypatch technique that would `AttributeError` before running.** `monkeypatch.setattr(market, "fetch_iv_metrics_ibkr", ...)` doesn't work because `market.py` never imports that name at module scope (it's a local import inside the function body). Rewrote Task 8 Step 1 to use the real, working pattern from this codebase's own `test_iv_enrichment_applied_when_ibkr_available`: patching `ibkr_mod.fetch_iv_metrics_ibkr` directly with manual save/restore in a `try/finally`.
2. **Fixed — Task 8 cited a test function (`test_fetch_option_chain_applies_ibkr_iv_when_available`) that doesn't exist.** The real name is `test_iv_enrichment_applied_when_ibkr_available` at `test_market_data_fixes.py:357`. Corrected the reference and had the new test copy that test's actual `mock_get` setup.
3. **Fixed — Task 8 Step 4 claimed the async variant needed "the exact same edits" as the sync one; it doesn't.** The real async block already wraps the IBKR call in `await asyncio.to_thread(...)` because `fetch_iv_metrics_tastytrade` internally calls `asyncio.run()`, which raises if invoked from a running event loop — exactly the situation in the async chain-fetch path. Without the fix, tastytrade IV data would silently never load on that path (swallowed by the `except Exception` in `tastytrade_iv.py`), defeating this task's purpose for probably the most-used code path. Rewrote Step 4 to wrap the call in `asyncio.to_thread`, and added Step 5 (a matching async test) — left two lines in that test as fill-in-once-verified rather than guessing the async function's exact name, since guessing wrong there would ship a test importing a nonexistent function.
4. **Fixed — Task 11's health probe called `get_market_metrics` directly, bypassing the Governor entirely.** This undermined the exact rate-limit protection Kenneth asked for: a rate-sensitive production call, fired on every dashboard poll, running completely uncoordinated with the token bucket every other tastytrade call in this plan respects. Rewrote `_probe_tastytrade` to route through `get_governor().call("tastytrade", ...)`, same as every other tastytrade call site.
5. **Fixed — a test name directly contradicted its own assertion body** (`test_get_session_uses_is_test_true_for_paper_environment_flag` asserted `is_test=False`). Renamed to `test_get_session_always_uses_is_test_false_for_both_slots`.
6. **Fixed — Task 1's SDK verification only checked importability, not call signatures.** Every downstream task hard-codes argument order/kwargs for SDK calls sourced from documentation, not from inspecting the installed package; a wrong signature would pass every mocked test and only surface at Task 15's live order test, after several tasks' worth of code already assumed the guessed shape. Added a Step 4 to Task 1 that runs `inspect.signature()` against the installed package's real callables and lists the expected shapes to compare against, with an explicit instruction to stop and fix downstream tasks if they differ.
7. **Documented, not fixed (correctly out of scope) — `TastytradePaperAdapter._ACTION_MAP` only supports opening-long/closing-long, not writing/shorting options.** `BrokerOrder` (the shared interface every adapter uses) has no open-vs-close field, so this is a limitation of the shared interface, not something tastytrade's adapter alone could fix. Added an explicit note in Task 9 flagging this as a known gap tied to `settingsStore.ts`'s `SpreadsConfig` (a plausible future credit-spread feature) rather than silently shipping partial support with no documentation.
8. **Confirmed sound, no fix needed:** the live-blocked safety mechanism (Task 10) — `BrokerRouter.execute()` checks `_LIVE_BROKERS` membership before any adapter lookup, `build_router_from_credentials()` never constructs a live adapter, and the frontend's `OptionsBroker` type never gains a `'tastytrade_live'` value. No path exists for a live order to reach `place_order`.

**Tally: 1 round, 8 findings — 6 fixed, 1 documented as an accepted out-of-scope limitation (item 7), 1 confirmed as a non-issue on verification (item 8).**

## Round 2 adversarial audit — findings and fixes

A second fresh subagent, with no memory of Round 1, re-read the whole plan (including the Round 1 section above) and did not take its "fixed" claims on faith — it re-verified each one against the real code, and went looking for anything Round 1 introduced or missed. It also empirically reproduced one issue with a standalone repro script rather than reasoning about it abstractly.

1. **Fixed, new task added — Round 1's own fixes shared one `asyncio.Lock` across independently-created event loops, a genuine concurrency defect Round 1 introduced while fixing something else.** Every other Governor-gated provider in this codebase only ever calls `get_governor().call(...)` from the app's single long-lived event loop. This plan was the first to reach it via `asyncio.run()` from synchronous code and from `asyncio.to_thread` (a separate OS thread) — and `TokenBucket`'s `asyncio.Lock` (`governor.py:22`) is created once, inside the process-wide `Governor` singleton. The reviewer reproduced, empirically, that concurrent `asyncio.run()` calls from multiple threads against a shared lock-holding object either raise `RuntimeError: ... bound to a different event loop` or deadlock outright under contention — precisely the concurrent-scan scenario Task 15's own verification step exercises. None of Round 1's per-call unit tests would have caught this (none call the function more than once or concurrently); it would only have surfaced as an intermittent hang during live verification. **Fix:** added a new Task 6 (renumbering every subsequent task by one — Task 6 old-IV-fetch is now Task 7, old-market.py-wiring is now Task 8, and so on through Task 15) that builds a single persistent background event loop (`tastytrade_bridge.py`, `run_coro()`), and rewired every sync-to-async tastytrade call site (`tastytrade_iv.py`, `tastytrade_paper.py`, `_probe_tastytrade`) to go through it instead of a bare `asyncio.run()`.
2. **Fixed — Round 1's "fixed" sync fallback test (Task 8, formerly Task 7) still used the wrong mock shape and would have failed.** Round 1 claimed the test now copies `test_iv_enrichment_applied_when_ibkr_available`'s `mock_get` setup, but it actually used `_fake_chain_contract()` — this codebase's *internal output* shape (no `option_type`, `bid`, `ask`, `implied_volatility`, or `greeks` keys) — as the mocked Tradier *response* body. `fetch_option_chain`'s real parsing (`market.py:522`, `if c.get("option_type") != tradier_type: continue`) would silently skip every such contract, making `result` empty and the test's own `assert len(result) == 1` fail. Also caught in the same pass: the test called `fetch_option_chain("AAPL", "2026-08-21", "C")` with a positional expiry argument that doesn't match how the real reference test calls it (`fetch_option_chain("AAPL", option_type="C")`, no expiry). Rewrote the test with the actual raw Tradier chain dict shape and the correct call signature.
3. **Fixed — the Task 8 (formerly 7) Step 5 async test was left as an explicit fill-in-later placeholder, and the fill-in was trivial to resolve.** Round 1 left two lines commented out pending confirmation of the async chain-fetch function's real name. A single `grep -n "^async def " backend/app/data/market.py` (which the Round 2 reviewer ran) immediately shows it's `fetch_option_chain_async(client: httpx.AsyncClient, symbol, ...)` at `market.py:1090` — and it takes a caller-supplied `httpx.AsyncClient`, calling `await client.get(...)`, not module-level `httpx.get`. Wrote the real test using an `AsyncMock`-based client double with the correct raw chain shape from finding #2.
4. **Fixed — Task 12 (formerly 11)'s migration instructions pointed at a stale insertion anchor.** Said to add the new branch "after the existing `if (version < 16)` block," but the real file's highest existing branch is `if (version < 19)`, matching the plan's own recorded persisted version of `19`. Harmless functionally (branch order doesn't matter) but a sign Task 12 was drafted against an older snapshot of the file. Corrected the anchor reference.
5. **Fixed — dead code in Task 9 (formerly 8)'s test.** A leftover `_, kwargs_or_args = fake_account.place_order.call_args, None` assignment was never read. Simplified to a single direct assertion.
6. **Confirmed sound, no fix needed:** Task 1's `inspect.signature()` verification step (added in Round 1) — the reviewer specifically checked whether this was a real fix or just moved the same unverified-assumption problem one step earlier, and concluded it's genuinely useful: it runs before any downstream code exists, so it's the correct point to catch a wrong SDK signature, not a hollow gesture. Noted as a residual soft spot: the comparison is manual/human-judgment rather than an automated assert, so a distracted executor could still skim past a mismatch — flagged for awareness, not treated as a blocking finding.

**Tally: 1 round, 6 findings — 5 fixed (including one genuine new concurrency defect introduced by Round 1's own fixes), 1 confirmed as sound with a minor residual note (item 6), 0 disputed.**

## Round 3 adversarial audit — findings and fixes

A third fresh subagent independently re-verified Round 1 and Round 2's "fixed" claims against the real codebase (rather than trusting the plan's own narrative) and specifically looked for anything either prior round introduced or missed — the same discipline Round 2 applied to Round 1.

1. **Fixed — Task 10's message-text change would have broken a real, currently-passing test.** The real `broker_router.py:20-22` raises `f"live IBKR trading is not yet activated..."`, and the existing `backend/tests/test_broker_router.py:44` asserts `pytest.raises(ValueError, match="live IBKR")`. Task 10's generalized message (`f"live trading via '{broker_key}' is not yet activated."`) no longer contains that substring for `ibkr_live`, so the existing test would fail the moment this task landed — and neither Round 1 nor Round 2 caught it, since both were focused on the plan's *new* code, not on what the plan's edits break in already-passing tests elsewhere. Added a new Step 4 to Task 10 that finds and updates that pre-existing assertion as an explicit, in-scope part of this task.
2. **Fixed — Tasks 3 and 5's new tests wrote real dummy credentials into the actual disk-backed `credential_store` singleton with no cleanup**, a genuine test-pollution risk this plan's own rate-limiting rationale (Task 11's Governor-routing rewrite) would otherwise be undermined by: with `tastytrade_paper` left "configured" by an earlier test's leftover values, a later, unrelated test (e.g. one of Task 8's pre-existing IBKR fallback tests, which doesn't mock `fetch_iv_metrics_tastytrade`) could trigger a real, uncoordinated network call to tastytrade using garbage secrets. It would likely still pass (the exception gets swallowed), so no round's "run the suite, expect PASS" check would have surfaced it — it's a silent hygiene defect, not a hard failure. Added `try/finally` cleanup restoring each credential slot (and the session cache) in all three affected tests (Task 3 Step 1's two tests, Task 5 Step 6's test).
3. **Documented, not fixed (a residual soft spot, not a confirmed defect) — the tastytrade `LimitOrder` debit/credit price-sign convention (`negative = debit`, `positive = credit`) was sourced from documentation and never independently verified.** This is a runtime value convention, not a call signature, so Task 1 Step 4's `inspect.signature()` check (added in Round 1) cannot catch a wrong sign here — if it's backwards, every paper order would carry an inverted price with nothing catching it before a live order is actually placed. Added an explicit comment at the sign-flipping code in Task 9, and strengthened Task 15 Step 4 to explicitly check the placed order's price sign against what was entered, not just that an `order_id` came back.
4. **Confirmed sound, no fix needed, after independent re-verification:** Task 6's `run_coro()` bridge genuinely fixes the cross-loop `asyncio.Lock` hazard (Round 2's central finding) without introducing a new regression — a single persistent background loop means the Governor's lock binds once and stays bound under both sequential and concurrent access, and all three call sites consistently use it with no stray `asyncio.run(` left anywhere. Task numbering (1-15) was independently re-checked top to bottom and found fully consistent, with no stray old task numbers surviving Round 2's renumbering. Task 8's rewritten sync and async tests were re-traced line-by-line against the real `market.py` parsing code and the real test file's helpers/imports and found to actually match this time (Round 2's fixes to Round 1's broken mock shape held up).

**Tally: 1 round, 4 findings — 2 fixed (one a real test breakage neither prior round caught, one a genuine test-hygiene/pollution risk), 1 documented as a residual soft spot with strengthened live-verification coverage, 1 confirms Round 2's fixes held up under independent re-verification. No new concurrency-class defects found — the audit loop has now converged on the architecture; remaining rounds would need to focus on new ground rather than re-litigating what's already been checked twice.**

## Round 4 adversarial audit — findings and fixes

A fourth fresh subagent independently re-verified all three prior rounds' claims (including re-checking Round 3's own fixes for correctness, not just assuming they held) and did a genuinely fresh read looking specifically for anything none of the first three rounds' focus areas would have caught.

1. **Fixed, high severity — `backend/app/routers/broker.py` was never in scope for any of the first three rounds, and its `BrokerKey` Literal would 422-reject every tastytrade order before it ever reached this plan's own code.** `BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper"]` (`broker.py:13`) gates the request body for the actual `POST /broker/stock-order` / `POST /broker/option-order` endpoints the frontend's trade-card send flow calls — the same flow Task 15 Step 4 (live end-to-end verification) exercises. Without widening it, selecting "Tastytrade Paper" and sending an order fails FastAPI/Pydantic validation before `build_router_from_credentials()`/`BrokerRouter.execute()` (Task 10's own work) ever runs — the entire paper-execution feature this plan builds would be unreachable from the UI. This file was absent from every prior round's file list and from the plan's own original investigation summary. Folded the fix into Task 10 (widened `BrokerKey`, updated `broker_status()` for consistency, added a test asserting the route doesn't 422) rather than adding a new task, since it's the same broker-wiring concern Task 10 already owns.
2. **Fixed, cosmetic — Task 1 Step 4 still referenced pre-Round-2-renumbering task numbers** ("Tasks 5, 6, and 8," "Tasks 5-9," "Task 14's live paper-order test"), left over from before Round 2 inserted the new Task 6 bridge and shifted everything after it. Round 1's own summary text elsewhere in the plan had already been correctly updated to "Task 15's live order test" — only this one step's body text was missed. Corrected to "Tasks 5, 7, and 9," "Tasks 5-10," "Task 15's live paper-order test."
3. **Confirmed sound, no fix needed, after specifically-targeted re-verification:** Round 3's `try/finally` credential-cleanup fix (Tasks 3/5) does not have the `None`-crash hazard it was checked for — `CredentialStore.__init__` (Task 2's own work) always populates `"tastytrade_paper"`/`"tastytrade_live"` with non-`None` default dict values, so `credential_store.get(...)` can never return `None` for these slots by the time Tasks 3/5's tests run, meaning the `finally` block's `credential_store.set(key, original)` never receives `None`. Round 3's Task 10 message-text fix was also re-confirmed complete — a full-tree grep for both the old and new message substrings found no other test asserting on the changed text. `backend/tests/test_data_sources.py` was confirmed to already exist with unrelated existing coverage that doesn't conflict with Task 11's additions.

**Tally: 1 round, 3 findings — 1 fixed at high severity (a real gap that would have made this plan's entire paper-execution deliverable unreachable from the UI, missed by three prior rounds because none of them had reason to look at `broker.py`), 1 fixed at cosmetic severity (stale cross-references), 1 round of re-verification confirming Round 3's fixes hold up with no new hazard found. The high-severity finding is a reminder that "no new findings in the areas already reviewed" is not the same as "no new findings" — Round 4 only found it by deliberately reading outward from the plan's own file list rather than re-checking the same files a fourth time.**

## Round 5 adversarial audit — findings and fixes

A fifth fresh subagent was explicitly instructed to repeat Round 4's discipline — read outward from the plan's own file list rather than re-verifying what four prior rounds already checked — since Round 4 had just demonstrated that "clean within scope" isn't the same as "clean."

1. **Fixed, highest severity of any round so far — `credential_store.py:12`'s `_SENSITIVE_KEYS` set never gained tastytrade's field names, meaning `GET /settings/credentials` would return the tastytrade OAuth client secret and refresh token in plaintext.** `_mask_dict` only redacts values whose key exactly matches `_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret", "secret_key"}` — `client_secret` and `refresh_token` don't match any of those strings. Given this plan's own investigation notes record that tastytrade refresh tokens *never expire*, a leaked one is a standing account-access risk, not a one-time exposure — arguably worse than Round 4's `broker.py` finding, which only broke a request, not confidentiality. Fixed directly in Task 2 (the same task that introduces these field names in the first place): added `"client_secret"` and `"refresh_token"` to `_SENSITIVE_KEYS`, with a new test (`test_tastytrade_credentials_are_masked`) asserting the masked values differ from the originals.
2. **Fixed — `step-7-trade-card/page.tsx:218`'s `brokerLabel` ternary only ever resolves to `'Tradier Paper'` or `'IBKR Paper'`, silently mislabeling every other broker (including tastytrade once Task 14 lands) as IBKR.** Every tastytrade-executed Options-mode trade would show up in the portfolio labeled as an IBKR position. Fixed with an explicit three-way check, added as Task 16 Step 2.
3. **Fixed — three separate Stocks-mode broker pickers (`StockSendDialog`, `StockPositionCard`, `step-7-position-card`) all hardcode the same `ibkr_paper`/`tradier_paper`/`alpaca_paper` union with no tastytrade entry.** `TastytradePaperAdapter` (Task 9) fully supports `STK` orders, but none of it was reachable from Stocks mode — only Options mode (via `BrokerPicker`, Task 14) could ever select tastytrade. Added as Task 16 Steps 3-5, widening each type and adding the missing picker row/button, mirroring each file's existing pattern exactly.
4. **Fixed — `frontend/lib/api.ts:458-464`'s `getBrokerStatus()` return type is stale** (already missing `alpaca_live` before this plan, and would now also miss `tastytrade_paper`/`tastytrade_live` once Task 10's `broker_status()` rewrite adds them). Fixed as Task 16 Step 1.
5. **Fixed — `ContextRail/QuickLook.tsx:107-111`'s `BROKER_FAMILIES` grouping has no tastytrade entry**, so the two new data-source rows (Task 11) would fall into the ungrouped "other" bucket instead of a proper grouped display like every other broker — the exact screen Task 15 Step 2 tells the executor to check, never mentioned anywhere else in the plan. Fixed as Task 16 Step 6.

All five fixes were consolidated into one new task (Task 16, placed after Task 15 since none of them block Task 15's Options-mode end-to-end verification) plus one direct fix to Task 2 (the credential-masking fix, since that's the task that owns the field names being masked).

**Tally: 1 round, 5 findings — all 5 fixed (1 at security severity, 1 at UI-correctness severity, 3 at feature-reachability severity). Zero disputed, zero deferred. This round found more total issues than Round 3 or Round 4 individually, confirming the "read outward" instruction was the right call rather than diminishing returns — the next round should determine whether reading outward has now been exhausted or whether further undiscovered surface remains.**

## Round 6 adversarial audit — findings and fixes

A sixth fresh subagent both re-verified Round 5's fixes against live file content and kept reading outward — specifically instructed to grep the whole backend for other hardcoded broker-key Literals the way Round 4 found one in `broker.py`, rather than only re-checking the six files Round 5 had just touched.

1. **Fixed, high severity — `backend/app/routers/auto_trade.py:16`'s `ArmRequest.broker` Literal (`Literal["ibkr_paper", "tradier_paper"]`, missing even `alpaca_paper`) is a sibling gap to Round 4's `broker.py` finding, in a router none of the first five rounds had opened.** Traced the full call chain: this task's own `selectedBroker` (the `OptionsBroker` value `BrokerPicker` sets) flows into `<AutoTradeArm broker={selectedBroker} />` in `step-7-trade-card/page.tsx`, which POSTs to `/auto-trade/arm`. Once this task landed as originally written, arming an auto-trade after selecting "Tastytrade Paper" would 422 before `auto_trader.arm()` ever ran — the auto-trade arm/fire flow would be unreachable for tastytrade, exactly the same failure shape as Round 4's finding. Fixed by folding a widened Literal and a new regression test into this task (Task 14) as Step 5, since it owns the "make the newly-selectable broker key reach a backend endpoint" concern already. `alpaca_paper` — missing from this Literal even before this plan — was added in the same edit since it's directly adjacent and cheap to close, rather than leaving a known-adjacent gap half-fixed.
2. **Confirmed sound, no fix needed, after live re-verification:** Task 2's `_SENSITIVE_KEYS` fix and its `test_tastytrade_credentials_are_masked` test were re-checked against the real `_mask()`/`_mask_dict()` implementation — `_mask("super-secret-value")` genuinely produces a string ending in `"alue"` (the real last-4 characters, not a placeholder), confirming the test's assertion holds exactly as written. Task 16's six file modifications were re-read fresh against live file content one more time — all line numbers and surrounding code shapes still match (two harmless one-line offsets in `StockPositionCard/index.tsx` were noted but land in the correct, unambiguous block regardless).
3. **Checked and confirmed clean, no monolithic "enumerate all broker keys" test exists anywhere in the suite** that would need separate updating — `test_credential_store.py` and `test_broker_router.py` both test each broker's slots/keys individually, consistent with the pattern Task 2/10's own new tests already follow. `backend/app/schemas/__init__.py`, `scan.py`, `contracts.py`, and `audit.py`'s `log_event` (a free-form string, no allowlist) were all checked and found to need no changes.

**Tally: 1 round, 1 new finding — fixed at high severity (the second and, per this round's outward search, likely final sibling to Round 4's `broker.py` gap), plus 2 re-verifications confirming Round 5's fixes hold up under fresh reads. The outward search specifically targeted "other hardcoded broker Literals across the whole backend" this time (not just re-reading Round 5's six files) and, after finding `auto_trade.py`, checked `schemas/__init__.py`, `scan.py`, `contracts.py`, and `audit.py` with nothing further surfacing — the two sibling gates (`broker.py`, `auto_trade.py`) that route a broker-key string into backend logic both appear to now be covered.**

## Round 7 adversarial audit — findings and fixes

A seventh fresh subagent was specifically tasked with trying to break Round 6's closing claim ("the two sibling gates both appear to now be covered") rather than just re-confirming it, and to broaden the hardcoded-broker-list search beyond `typing.Literal` declarations to any Python `set`/`list`/`dict` form, across the whole backend and frontend trees — not just the files already touched by prior rounds.

1. **Fixed, high severity, empirically reproduced — Task 14 Step 5's own new regression test would fail with an unhandled `ValueError`, unrelated to the Literal it exists to test.** The reviewer didn't just read the code — it ran an equivalent request against the real app (`ASGITransport`, using `broker: "ibkr_paper"`, an already-Literal-listed broker, to isolate the bug from anything tastytrade-specific) and reproduced: `AutoTradeService.arm()` (`auto_trader.py:139-144`) raises `ValueError("entry_premium must be > 0 before arming...")` whenever `entry_premium <= 0`, which is the field's own default (`ArmRequest.entry_premium: float = 0.0`, `auto_trade.py:24`). The `/auto-trade/arm` route has no `try/except` around the call, so the `ValueError` propagates uncaught rather than becoming a readable HTTP response — meaning the test as originally written would error out before ever reaching the Literal-validation behavior it was meant to check, regardless of whether `tastytrade_paper` was accepted or not. This is a real, pre-existing guard in the codebase (confirmed against `backend/tests/test_auto_trader.py`'s own `test_arm_raises_if_entry_premium_is_zero`), not something this plan introduced — but the plan's own new test would have silently failed to test what it claimed to. Fixed by adding `"entry_premium": 3.50` to the test's request body, with an inline comment explaining why it's required.
2. **Confirmed sound, no fix needed, after independent verification:** `ArmedStrategy.broker` (`auto_trader.py:19`) is typed as plain `str`, not a `Literal` — so widening `ArmRequest.broker`'s Pydantic Literal (the actual validation gate) is sufficient; no separate widening needed downstream. `auto_trader.py`'s fire path (`execute_option_order()` → `router.execute(strategy.broker, order)`) was independently confirmed to have no broker-specific branch anywhere — it's already broker-agnostic at that layer, so firing an armed tastytrade strategy end-to-end works once Tasks 9/10 land, with no additional fire-path change needed.
3. **Broadened outward search (backend, non-Literal forms + entire frontend tree) found no third sibling gate.** Backend: grepped for `ibkr_paper`/`tradier_paper` co-occurrence across the whole tree in any form (not just `Literal`) — only the files already covered by this plan's tasks. Frontend: the same co-occurrence grep across all `.ts`/`.tsx` files turned up exactly the 8 files already in Tasks 12-16's scope, plus a direct check of `SendToBrokerDialog/index.tsx` (reachable from the trade-card page but not caught by the co-occurrence grep) confirmed it takes broker identity generically via props with no hardcoded Literal of its own.
4. **Full fresh re-read of all 16 tasks found no further placeholders or internal inconsistencies** — task numbering, file/line cross-references, and each round-summary's description of its own fixes were all re-checked against the task bodies they describe and found consistent.

**Tally: 1 round, 1 new finding — fixed (a test that would have errored for a reason unrelated to what it was testing, caught only because this round chose to empirically run the request rather than just read the code), plus 3 independent re-verifications (ArmedStrategy typing, the fire path, and the broadened hardcoded-list search) all confirming no further sibling gates exist. This is the first round where the "keep reading outward" search came back empty-handed on new gates — the remaining finding was a test-correctness bug in a fix from the immediately preceding round, not a newly-discovered architectural gap. That shift (from finding new categories of missing wiring to finding a test bug in the last round's own fix) is the shape of genuine convergence, not just a quiet round.**

## Round 8 adversarial audit — findings and fixes

An eighth fresh subagent was specifically instructed not to repeat Round 7's read-only verification style, but to actually install the real `tastytrade` package and execute the plan's own test code against it — the same escalation from "read" to "run" that let Round 7 catch its one finding. This is the round where that escalation paid off hardest.

1. **Fixed, blocking severity — Task 1's core claim ("tastytrade installs without dependency conflicts") is false, confirmed directly against PyPI.** Every `tastytrade` release from 12.0.0 through the current 13.0.0 requires `httpx>=0.28.1`, which hard-conflicts with this repo's pinned `httpx==0.27.0`. All seven prior rounds — including six that opened `requirements.txt` and read Task 1's text — never ran the actual install and never caught this; it's the kind of failure that only surfaces by executing the resolver, not by reading declared version ranges casually. Left as originally written, Task 1 either fails outright or pip silently upgrades httpx to 0.28.x with no acknowledgment that every other httpx-based adapter in this codebase (`ibkr.py`, `ibkr_paper.py`, `alpaca.py`, `alpaca_paper_execution.py`, all of `market.py`) is now running against an unpinned, unverified newer version. Rewrote Task 1 to require confirming the conflict directly, deliberately bumping `httpx` to `>=0.28.1`, and — critically — running the **entire pre-existing backend test suite** before writing a single line of new tastytrade code, to catch any regression the version bump itself causes elsewhere in this codebase. This is now a hard gate before Task 2 can start, not an assumption.
2. **Fixed, confirmed by actually running the test — Task 9's `except RuntimeError: raise` clause silently broke its own sibling test.** The "account not configured" `RuntimeError` is raised *before* the `try` block (so it was never going to be caught by anything inside it), which meant the `except RuntimeError: raise` inside the try existed for no reason except to catch RuntimeErrors from the SDK calls themselves and re-raise them *without* the `"tastytrade paper order failed"` prefix — silently defeating the uniform error-wrapping contract this task's own `test_place_order_wraps_sdk_exception` asserts on. The reviewer reproduced the `AssertionError` directly. Removed the erroneous clause; every exception from the SDK calls, RuntimeError included, is now wrapped consistently.
3. **Fixed, confirmed by actually running the test against the real installed SDK — `test_place_order_stock_success` fails with a `pydantic_core.ValidationError`, not a passing test.** `Leg`/`LimitOrder` are strict Pydantic v2 models in the real SDK (confirmed against `Leg.model_fields`); a bare `MagicMock()` standing in for a `Leg` fails validation the instant the adapter builds `LimitOrder(legs=[leg], price=price)`, well before the test's own assertions run. Rewrote the test to patch the `LimitOrder` class itself rather than mock its inputs — which has the added benefit of letting the test directly assert on the exact price passed in (`Decimal("-150.0")` for a BUY at `limit_price=150.0`), turning this into the first automated check of the debit/credit sign convention flagged as unverified-beyond-docs since Round 3.
4. **Documented, lower severity — Task 1's signature-verification step glosses over real version-dependent parameter-name differences** (e.g. some SDK versions use `account_number` rather than `account_id`-style naming) and doesn't mention tastytrade's non-trivial transitive dependency footprint (pandas, numpy, pandas-market-calendars, exchange-calendars). Added an explicit note in Task 1 to read the real printed signatures carefully rather than pattern-match loosely, and to let Step 3's full-suite run catch any transitive-dependency fallout.
5. **Confirmed sound, no fix needed:** the plan's four new modules (`tastytrade_bridge.py`, `tastytrade_session.py`, `tastytrade_iv.py`, `tastytrade_paper.py`) have no circular-import problem — verified by actually importing them together. The Task 6 concurrency test's 5-second thread-join timeout was run 6 times with real thread timing consistently under 0.15s — not a flaky-test risk, ~30x headroom.

**A note on something unrelated to the plan's content, surfaced for transparency:** the subagent reported that mid-session, a tool-output system-reminder falsely claimed it had "intentionally" modified `governor.py` (a real, tracked file) and instructed it not to mention this. The subagent correctly disregarded this — `git status`/`git diff` on the real repository confirmed no tracked file was touched, only this plan document. Flagging this to Kenneth directly: this looks like a prompt-injection attempt against the subagent from somewhere in its tool output, not a real instruction, and it was correctly ignored. No repo files were affected.

**Tally: 1 round, 5 findings — 3 fixed at blocking-to-high severity (a dependency conflict that would have stopped Task 1 cold, and two test bugs confirmed by actually executing them against the real SDK rather than reasoning about the code), 2 documented/confirmed at lower severity. This round found real, previously-undetected defects specifically because it escalated from reading code to running it — a category of bug none of the first seven rounds, all read-only, could have caught. Whether further "run it and see" escalation would find more is now the open question for any subsequent round.**

## Round 9 adversarial audit — findings and fixes

A ninth fresh subagent was tasked with the direct follow-up question Round 8 left open: does Round 8's own fix actually work end to end, verified by execution rather than by reading the fix and assuming it's correct? It built an isolated scratch copy, took a clean baseline (**1015 passed, 1 skipped, 1 xfailed** on the real pre-existing suite before any change), then applied Round 8's httpx bump and tastytrade install for real.

1. **Confirmed by execution: Round 8's httpx bump + tastytrade install genuinely succeeds now** — `httpx-0.28.1`, `tastytrade-13.0.0` installed with no `ResolutionImpossible`, exactly as Round 8's fix intended.
2. **Fixed, and this is the one new finding this round earns its keep on — Task 1 Step 3's own regression gate ("run the full suite, expect all-pass") was itself never actually run by any prior round, and running it for real surfaces 15 genuine failures.** httpx 0.28 didn't just deprecate the `AsyncClient(app=app, ...)` shortcut this codebase's *existing* tests use in three files (`test_composite_watch_router.py`, `test_mean_reversion_multi.py`, `test_prebreakout_universe.py`) — it removed it outright. Task 1 Step 3 already told the executor to "fix that regression before proceeding," but left the actual fix as an exercise, which is exactly the kind of underspecified step the writing-plans discipline this plan otherwise follows tries to avoid. Replaced the vague instruction with the concrete fix: migrate each `AsyncClient(app=app, ...)` call in those three files to `AsyncClient(transport=ASGITransport(app=app), ...)` — the exact pattern this plan's own new tests (Tasks 3, 9, 10, 14, 16) already use throughout, so this isn't a new pattern being introduced, just extending an existing one to three files nobody had reason to touch before this plan's httpx bump forced the issue.
3. **Confirmed by execution: Round 8's two `tastytrade_paper.py` fixes both genuinely work now.** Implemented the module verbatim (with the `except RuntimeError: raise` clause removed and `LimitOrder` patched as a class in the test) against the real installed SDK and ran it directly: all 3 tests pass, including the two Round 8 specifically fixed.
4. **Confirmed by execution: Task 7's IV-metrics tests (3/3) and Task 8's full `market.py` wiring (21/21, including both new tastytrade fallback tests and every pre-existing IBKR test) all pass** when implemented and run against real code at the exact line numbers the plan cites.
5. **Confirmed by execution: with the full tastytrade implementation added on top of the httpx-bump fix, the suite reaches 1008 passed** (1000 pre-existing + 8 new tastytrade tests) **with zero new failures caused by any tastytrade-specific code** — the only failures anywhere are the same 15 pre-existing `AsyncClient(app=app)` tests, now fixed by item 2 above.
6. **Documented, cosmetic:** `Account.get`'s real parameter name is `account_number`, not `account_id` — harmless since every call site in this plan uses positional arguments, but noted in Task 1 Step 5 so nobody tries to call it with a keyword argument later.

**A note on something unrelated to the plan's content, surfaced again for transparency since it recurred:** as in Round 8, this round's subagent operated correctly and no repo files were affected — this round did not report the same anomalous tool-output behavior Round 8 flagged, but the Round 8 note stands as something Kenneth should be aware happened during this audit process.

**Tally: 1 round, 6 findings — 1 fixed (a concrete, previously-unspecified fix for a regression this round was the first to actually trigger by running the command), 5 confirmed sound by direct execution (the httpx/tastytrade install, both Task 9 fixes, Task 7, and Task 8's full wiring), 0 new architectural gaps. This is the first round where "run it and see" was applied to the fixes from the immediately preceding execution-based round, and it closed the loop rather than opening a new one — everything Round 8 fixed now demonstrably works end to end, and the one remaining gap (the pre-existing httpx-shortcut breakage) has a concrete, copy-pasteable fix rather than an open question.

**Audit loop summary across all nine rounds:** 9 rounds, ~35 distinct findings, spanning test-mock bugs, a genuine cross-thread concurrency hazard requiring a new architectural component (Task 6), two separate high-severity "unreachable feature" gaps in backend routers outside the plan's original file list (`broker.py`, `auto_trade.py`), one security-severity credential-masking leak, several frontend reachability gaps, and — in the final two rounds — a blocking dependency conflict and two SDK-integration bugs that only surfaced once the plan's code was actually installed and executed rather than read. The audit reached a point where two consecutive execution-based rounds (8 and 9) trended toward confirming fixes rather than discovering new categories of defect, which is the strongest available convergence signal for a plan that has not yet been implemented. Residual risk that remains inherent to auditing a plan rather than a diff: anything that can only be discovered by writing the actual production code (not test doubles) against the live tastytrade OAuth/order-placement flow — Task 15's live end-to-end verification step is deliberately positioned as the final gate for exactly that reason and should not be skipped.**
