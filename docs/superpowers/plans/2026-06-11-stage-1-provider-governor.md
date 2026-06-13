# Stage 1: Provider Governor & Reliable Availability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared Provider Governor that makes exceeding any data-provider rate limit structurally impossible, and replace the unreliable data-source availability probes with real authenticated 4-state health checks.

**Architecture:** A single `app/data/governor.py` module provides a per-provider token-bucket rate limiter, a circuit breaker, a Tiingo unique-symbol budget ledger, and a 429-aware retry wrapper, exposed through one `Governor.call()` facade. The availability router (`data_sources.py`) is reworked to make a real cheap authenticated call per provider, cache results briefly, and report `connected | degraded | down | unconfigured` — with `degraded` driven by the Governor's live circuit-breaker state. Alpaca credential slots are added to the credential store (backend only) so probes and later stages can read them.

**Tech Stack:** Python 3.14, FastAPI, httpx, pytest + pytest-asyncio, `unittest.mock`. Async throughout. This stage is the foundation that Stages 2–4 depend on; it changes no data *content*.

**Source spec:** `docs/superpowers/specs/2026-06-11-data-loading-and-provider-governor-design.md` (§5.1, §5.5, §5.6 slots).

---

## File Structure

- **Create** `backend/app/data/governor.py` — Governor + TokenBucket + CircuitBreaker + SymbolBudget + RateLimited + backoff. One module, one responsibility: rate-limit/health enforcement.
- **Create** `backend/tests/test_governor.py` — unit tests for all governor pieces (no network).
- **Modify** `backend/app/services/credential_store.py` — add `alpaca_live` / `alpaca_paper` default slots and `secret_key` masking.
- **Modify** `backend/tests/test_credential_store.py` — assert new slots and masking.
- **Modify** `backend/app/routers/data_sources.py` — real authenticated 4-state probes, TTL cache, Alpaca probes, Governor-fed `degraded`.
- **Modify** `backend/tests/test_data_sources.py` — assert new probe behavior.

Run all commands from `backend/`. Test command pattern: `pytest tests/<file>::<test> -v`.

---

### Task 1: TokenBucket — async rate limiter

**Files:**
- Create: `backend/app/data/governor.py`
- Test: `backend/tests/test_governor.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_governor.py
from __future__ import annotations

import asyncio
import time

import pytest

from app.data.governor import TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity():
    # capacity 3 → first 3 acquisitions are immediate
    bucket = TokenBucket(rate=3, per=1.0, capacity=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05  # no meaningful wait


@pytest.mark.asyncio
async def test_token_bucket_throttles_beyond_capacity():
    # rate 10/sec, capacity 1 → the 2nd acquire must wait ~0.1s
    bucket = TokenBucket(rate=10, per=1.0, capacity=1)
    await bucket.acquire()                      # consumes the only token
    start = time.monotonic()
    await bucket.acquire()                      # must wait for a refill
    waited = time.monotonic() - start
    assert 0.05 < waited < 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_governor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.governor'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/data/governor.py
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Async token-bucket rate limiter.

    Refills `rate` tokens every `per` seconds, up to `capacity`. `acquire()`
    blocks until a token is available, so callers are admitted at most as fast
    as the configured rate. Admission is serialized by an internal lock, which
    is what makes strict per-provider pacing possible.
    """

    def __init__(self, rate: float, per: float = 1.0, capacity: float | None = None) -> None:
        self.rate = float(rate)
        self.per = float(per)
        self.capacity = float(capacity) if capacity is not None else float(rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._tokens = min(
                    self.capacity,
                    self._tokens + elapsed * (self.rate / self.per),
                )
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                await asyncio.sleep(deficit * (self.per / self.rate))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_governor.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): async token-bucket rate limiter"
```

---

### Task 2: CircuitBreaker — fail-fast on repeated provider errors

**Files:**
- Modify: `backend/app/data/governor.py`
- Test: `backend/tests/test_governor.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_governor.py
from app.data.governor import CircuitBreaker


def test_circuit_opens_after_threshold_failures():
    cb = CircuitBreaker(fail_threshold=3, cooldown=60.0)
    assert cb.is_open is False
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open is True


def test_circuit_closes_after_cooldown():
    cb = CircuitBreaker(fail_threshold=1, cooldown=0.05)
    cb.record_failure()
    assert cb.is_open is True
    time.sleep(0.06)
    assert cb.is_open is False  # half-open: allows a trial


def test_success_resets_failures():
    cb = CircuitBreaker(fail_threshold=2, cooldown=60.0)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.is_open is False  # counter was reset, only 1 failure since
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_governor.py -k circuit -v`
Expected: FAIL with `ImportError: cannot import name 'CircuitBreaker'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/data/governor.py
class CircuitBreaker:
    """Opens after `fail_threshold` consecutive failures, blocking calls for
    `cooldown` seconds. After cooldown it reports closed (half-open trial); a
    success resets the counter, a failure re-opens it."""

    def __init__(self, fail_threshold: int = 5, cooldown: float = 60.0) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown:
            return False  # half-open: allow a trial call through
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_threshold:
            self._opened_at = time.monotonic()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_governor.py -k circuit -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): circuit breaker with cooldown and reset"
```

---

### Task 3: SymbolBudget — Tiingo unique-symbol/hour ledger

**Files:**
- Modify: `backend/app/data/governor.py`
- Test: `backend/tests/test_governor.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_governor.py
from app.data.governor import SymbolBudget


def test_symbol_budget_counts_distinct_symbols():
    budget = SymbolBudget(max_symbols=2, window=3600.0)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("MSFT") is True
    assert budget.try_consume("GOOG") is False   # over the cap
    assert budget.remaining() == 0


def test_symbol_budget_same_symbol_is_free_within_window():
    budget = SymbolBudget(max_symbols=1, window=3600.0)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("AAPL") is True     # already counted, still allowed
    assert budget.remaining() == 0


def test_symbol_budget_evicts_after_window():
    budget = SymbolBudget(max_symbols=1, window=0.05)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("MSFT") is False
    time.sleep(0.06)
    assert budget.try_consume("MSFT") is True     # AAPL evicted, slot freed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_governor.py -k symbol_budget -v`
Expected: FAIL with `ImportError: cannot import name 'SymbolBudget'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/data/governor.py
class SymbolBudget:
    """Tracks distinct symbols fetched within a rolling time window. Used for
    Tiingo's free-tier unique-symbol/hour cap: re-fetching a symbol already
    counted this window is free; a new symbol beyond `max_symbols` is refused."""

    def __init__(self, max_symbols: int, window: float = 3600.0) -> None:
        self.max_symbols = max_symbols
        self.window = window
        self._seen: dict[str, float] = {}  # symbol -> first-seen monotonic ts

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        self._seen = {s: t for s, t in self._seen.items() if t >= cutoff}

    def try_consume(self, symbol: str) -> bool:
        now = time.monotonic()
        self._evict(now)
        if symbol in self._seen:
            return True
        if len(self._seen) >= self.max_symbols:
            return False
        self._seen[symbol] = now
        return True

    def remaining(self) -> int:
        self._evict(time.monotonic())
        return max(0, self.max_symbols - len(self._seen))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_governor.py -k symbol_budget -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): Tiingo unique-symbol budget ledger"
```

---

### Task 4: RateLimited exception + backoff helper

**Files:**
- Modify: `backend/app/data/governor.py`
- Test: `backend/tests/test_governor.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_governor.py
from app.data.governor import RateLimited, backoff_delay


def test_rate_limited_carries_retry_after():
    err = RateLimited("429", retry_after=12.5)
    assert err.retry_after == 12.5


def test_backoff_delay_grows_and_is_capped():
    d0 = backoff_delay(0, base=0.5, cap=8.0)
    d1 = backoff_delay(1, base=0.5, cap=8.0)
    d5 = backoff_delay(5, base=0.5, cap=8.0)
    assert d0 == pytest.approx(0.5)
    assert d1 == pytest.approx(1.0)
    assert d5 == 8.0  # capped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_governor.py -k "rate_limited or backoff" -v`
Expected: FAIL with `ImportError: cannot import name 'RateLimited'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/data/governor.py
class RateLimited(Exception):
    """Raised by a provider adapter when the API returns HTTP 429. Carries the
    server's Retry-After hint (seconds) when present."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Exponential backoff: base * 2**attempt, capped at `cap` seconds."""
    return min(cap, base * (2 ** attempt))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_governor.py -k "rate_limited or backoff" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): RateLimited exception and backoff helper"
```

---

### Task 5: Governor facade — call() + health() + provider registry

**Files:**
- Modify: `backend/app/data/governor.py`
- Test: `backend/tests/test_governor.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_governor.py
from app.data.governor import Governor, ProviderUnavailable, build_default_governor


@pytest.mark.asyncio
async def test_governor_call_returns_result_and_marks_connected():
    gov = Governor.for_testing(provider="alpaca", rate=100, capacity=100)

    async def _ok():
        return [1, 2, 3]

    result = await gov.call("alpaca", _ok)
    assert result == [1, 2, 3]
    assert gov.health("alpaca") == "connected"


@pytest.mark.asyncio
async def test_governor_retries_on_rate_limited_then_succeeds():
    gov = Governor.for_testing(provider="tiingo", rate=100, capacity=100)
    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("429", retry_after=0.01)
        return "ok"

    result = await gov.call("tiingo", _flaky, retries=2)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_governor_opens_circuit_and_reports_degraded():
    gov = Governor.for_testing(provider="yf", rate=100, capacity=100, fail_threshold=2)

    async def _broken():
        raise RuntimeError("network down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await gov.call("yf", _broken)
    # circuit now open → next call short-circuits with ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        await gov.call("yf", _broken)
    assert gov.health("yf") == "degraded"


def test_build_default_governor_has_all_providers():
    gov = build_default_governor()
    for name in ("alpaca", "tradier", "tiingo", "yfinance", "ibkr"):
        assert gov.health(name) == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_governor.py -k governor -v`
Expected: FAIL with `ImportError: cannot import name 'Governor'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/app/data/governor.py
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderUnavailable(Exception):
    """Raised when a provider's circuit is open, so callers can fall through to
    the next provider in their chain without making a doomed network call."""


@dataclass
class _ProviderState:
    name: str
    bucket: "TokenBucket"
    breaker: "CircuitBreaker"
    budget: "SymbolBudget | None" = None
    status: str = "unknown"  # unknown | connected | degraded | down | unconfigured


class Governor:
    """Single gate every provider call passes through. Enforces per-provider
    rate limits, retries 429s with backoff, and opens a circuit on repeated
    failures so callers fail fast to their fallback chain."""

    def __init__(self, providers: dict[str, _ProviderState]) -> None:
        self._providers = providers

    # ── Construction helpers ────────────────────────────────────────────────
    @classmethod
    def for_testing(
        cls, provider: str, rate: float, capacity: float,
        fail_threshold: int = 5,
    ) -> "Governor":
        state = _ProviderState(
            name=provider,
            bucket=TokenBucket(rate=rate, per=1.0, capacity=capacity),
            breaker=CircuitBreaker(fail_threshold=fail_threshold, cooldown=60.0),
        )
        return cls({provider: state})

    # ── Health ──────────────────────────────────────────────────────────────
    def health(self, provider: str) -> str:
        ps = self._providers.get(provider)
        if ps is None:
            return "unconfigured"
        if ps.breaker.is_open:
            return "degraded"
        return ps.status

    def set_status(self, provider: str, status: str) -> None:
        ps = self._providers.get(provider)
        if ps is not None:
            ps.status = status

    def symbol_allowed(self, provider: str, symbol: str) -> bool:
        """True if `provider` still has budget for `symbol` this window.
        Providers without a SymbolBudget are always allowed."""
        ps = self._providers.get(provider)
        if ps is None or ps.budget is None:
            return True
        return ps.budget.try_consume(symbol)

    # ── Core call ─────────────────────────────────────────────────────────────
    async def call(
        self,
        provider: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        retries: int = 3,
    ) -> T:
        ps = self._providers.get(provider)
        if ps is None:
            raise ProviderUnavailable(f"provider '{provider}' not registered")
        if ps.breaker.is_open:
            ps.status = "degraded"
            raise ProviderUnavailable(f"{provider} circuit open")

        attempt = 0
        while True:
            await ps.bucket.acquire()
            try:
                result = await coro_factory()
                ps.breaker.record_success()
                ps.status = "connected"
                return result
            except RateLimited as exc:
                ps.status = "degraded"
                ps.breaker.record_failure()
                if attempt >= retries:
                    logger.warning("%s rate-limited, retries exhausted", provider)
                    raise
                delay = exc.retry_after if exc.retry_after is not None else backoff_delay(attempt)
                await asyncio.sleep(delay)
                attempt += 1
            except Exception:
                ps.breaker.record_failure()
                ps.status = "down"
                raise


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
        "alpaca":   _state("alpaca",   rate=200 / 60, capacity=20),
        "tradier":  _state("tradier",  rate=120 / 60, capacity=15),
        # Tiingo: pace ~1 req/72s AND cap 50 unique symbols/hour.
        "tiingo":   _state("tiingo",   rate=1 / 72,  capacity=2,
                           budget=SymbolBudget(max_symbols=50, window=3600.0)),
        "yfinance": _state("yfinance", rate=2,        capacity=2),
        "ibkr":     _state("ibkr",     rate=40,       capacity=40),
    }
    return Governor(providers)


# Process-wide singleton used by adapters and routers.
_GOVERNOR: Governor | None = None


def get_governor() -> Governor:
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = build_default_governor()
    return _GOVERNOR
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_governor.py -v`
Expected: PASS (all governor tests pass)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/governor.py backend/tests/test_governor.py
git commit -m "feat(governor): call facade, health, and default provider registry"
```

---

### Task 6: Add Alpaca credential slots (backend)

**Files:**
- Modify: `backend/app/services/credential_store.py:30-35` (default `_data` dict), `:11` (`_SENSITIVE_KEYS`)
- Test: `backend/tests/test_credential_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_store.py
from app.services.credential_store import CredentialStore


def test_alpaca_slots_exist_by_default(tmp_path):
    store = CredentialStore(path=tmp_path / "creds.yaml")
    assert store.get("alpaca_live") == {
        "key_id": "", "secret_key": "", "base_url": "https://api.alpaca.markets",
    }
    assert store.get("alpaca_paper") == {
        "key_id": "", "secret_key": "", "base_url": "https://paper-api.alpaca.markets",
    }


def test_secret_key_is_masked(tmp_path):
    store = CredentialStore(path=tmp_path / "creds.yaml")
    store.set("alpaca_paper", {"key_id": "PKID", "secret_key": "abcd1234SECRET"})
    masked = store.get_masked("alpaca_paper")
    assert masked["secret_key"].endswith("CRET")
    assert masked["secret_key"].startswith("*")
    assert masked["key_id"] == "PKID"  # key_id is not sensitive
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_credential_store.py -k alpaca -v`
Expected: FAIL — `alpaca_live` slot missing (`get` returns None) / `secret_key` not masked

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/credential_store.py`, change `_SENSITIVE_KEYS` (line 11) to add `secret_key`:

```python
_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret", "secret_key"}
```

And extend the default `_data` dict (lines 30-35) to include the two Alpaca slots:

```python
        self._data: dict[str, dict] = {
            "ibkr_live":     {"base_url": "https://localhost:5000/v1/api", "account_id": ""},
            "ibkr_paper":    {"base_url": "https://localhost:7499/v1/api", "account_id": ""},
            "tradier_live":  {"token": "", "account_id": ""},
            "tradier_paper": {"token": "", "account_id": ""},
            "alpaca_live":   {"key_id": "", "secret_key": "", "base_url": "https://api.alpaca.markets"},
            "alpaca_paper":  {"key_id": "", "secret_key": "", "base_url": "https://paper-api.alpaca.markets"},
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_credential_store.py -v`
Expected: PASS (existing + new alpaca tests pass)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/credential_store.py backend/tests/test_credential_store.py
git commit -m "feat(credentials): add Alpaca live/paper slots and secret_key masking"
```

---

### Task 7: Rework availability probes — real calls, 4-state, TTL cache, Alpaca

**Files:**
- Modify: `backend/app/routers/data_sources.py` (probe functions + `get_data_sources`)
- Test: `backend/tests/test_data_sources.py`

This task replaces the fake Tradier-live env-var check with a real authenticated call, adds Alpaca probes, introduces a short TTL cache, and lets the Governor's circuit state surface `degraded`. The status `Literal` gains `connected` and `degraded` while keeping `unavailable`/`unconfigured` for back-compat in the response model.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_data_sources.py — replace/extend with these tests
from __future__ import annotations

from unittest.mock import patch

import httpx

from app.routers.data_sources import (
    _probe_tradier, _probe_alpaca, _status_for_probe, _PROBE_CACHE,
)


def _resp(status_code: int, json_body=None):
    request = httpx.Request("GET", "https://example.test")
    return httpx.Response(status_code, json=json_body or {}, request=request)


def test_tradier_probe_makes_real_call_not_env_check():
    # token present AND real call returns 200 → connected
    with (
        patch.dict("os.environ", {"TRADIER_API_TOKEN": "tok"}),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(200, {"clock": {}})) as m,
    ):
        status, _ = _probe_tradier()
    assert status == "connected"
    assert m.called  # proves it actually called the API, not just read the env var


def test_tradier_probe_reports_down_on_401():
    with (
        patch.dict("os.environ", {"TRADIER_API_TOKEN": "bad"}),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(401, {"fault": {}})),
    ):
        status, detail = _probe_tradier()
    assert status == "down"
    assert "401" in (detail or "")


def test_tradier_probe_unconfigured_without_token():
    with patch.dict("os.environ", {"TRADIER_API_TOKEN": ""}, clear=False):
        status, _ = _probe_tradier()
    assert status == "unconfigured"


def test_alpaca_probe_connected_with_keys():
    fake_creds = {"key_id": "PK", "secret_key": "SK", "base_url": "https://paper-api.alpaca.markets"}
    with (
        patch("app.routers.data_sources.credential_store.get", return_value=fake_creds),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(200, {"status": "ACTIVE"})),
    ):
        status, _ = _probe_alpaca("alpaca_paper")
    assert status == "connected"


def test_status_for_probe_prefers_governor_degraded():
    # If the Governor says the circuit is open, report degraded regardless of probe.
    with patch("app.routers.data_sources.get_governor") as gov:
        gov.return_value.health.return_value = "degraded"
        status = _status_for_probe("alpaca", probe_status="connected")
    assert status == "degraded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_sources.py -v`
Expected: FAIL with `ImportError` on `_probe_alpaca` / `_status_for_probe` (don't exist yet)

- [ ] **Step 3: Write minimal implementation**

Rewrite `backend/app/routers/data_sources.py` to this:

```python
"""GET /api/data-sources — probe each data source with a real authenticated
call and return reliable availability. Results cached briefly; the Governor's
live circuit state can override a probe to 'degraded'."""
from __future__ import annotations

import logging
import os
import time
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.credential_store import credential_store
from app.data.governor import get_governor

logger = logging.getLogger(__name__)
router = APIRouter()

_PROBE_TIMEOUT = 4.0
_CACHE_TTL = 45.0  # seconds — keep panel polling from burning rate budget
_PROBE_CACHE: dict[str, tuple[str, str | None, float]] = {}  # id -> (status, detail, expires)

ProbeStatus = Literal["connected", "degraded", "down", "unconfigured"]


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: ProbeStatus
    provides: list[str]
    detail: str | None = None


# ── Probe helpers ───────────────────────────────────────────────────────────

def _probe_tradier() -> tuple[str, str | None]:
    token = os.environ.get("TRADIER_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TRADIER_API_TOKEN not set in .env"
    base = os.environ.get("TRADIER_BASE_URL", "https://api.tradier.com")
    try:
        resp = httpx.get(
            f"{base}/v1/markets/clock",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Tradier returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_alpaca(slot: str) -> tuple[str, str | None]:
    creds = credential_store.get(slot)
    if not creds or not creds.get("key_id") or not creds.get("secret_key"):
        return "unconfigured", "Add Alpaca keys in Settings → Brokers"
    base = creds.get("base_url", "https://paper-api.alpaca.markets")
    try:
        resp = httpx.get(
            f"{base}/v2/account",
            headers={
                "APCA-API-KEY-ID": creds["key_id"],
                "APCA-API-SECRET-KEY": creds["secret_key"],
            },
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Alpaca returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_tiingo() -> tuple[str, str | None]:
    token = os.environ.get("TIINGO_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TIINGO_API_TOKEN not set in .env"
    try:
        resp = httpx.get(
            "https://api.tiingo.com/api/test/",
            headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Tiingo returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_ibkr_gateway(port: int) -> tuple[str, str | None]:
    url = f"https://localhost:{port}/v1/api/iserver/auth/status"
    try:
        resp = httpx.get(url, verify=False, timeout=_PROBE_TIMEOUT)
        resp.raise_for_status()
        if resp.json().get("authenticated"):
            return "connected", None
        return "down", f"Gateway up but not authenticated — log in at https://localhost:{port}"
    except httpx.ConnectError:
        bat = "start-gateway-paper.bat" if port == 7499 else "start-gateway.bat"
        return "down", f"Gateway not running — launch {bat}"
    except Exception as exc:
        return "down", str(exc)


def _probe_yfinance() -> tuple[str, str | None]:
    try:
        import yfinance as yf  # noqa: F401
        return "connected", None
    except ImportError:
        return "down", "yfinance not installed"


def _status_for_probe(governor_name: str | None, probe_status: str) -> str:
    """Let the Governor's live circuit state override a healthy probe to
    'degraded' — so the dot reflects real operational health during scans."""
    if governor_name is None:
        return probe_status
    gov_health = get_governor().health(governor_name)
    if gov_health == "degraded" and probe_status == "connected":
        return "degraded"
    return probe_status


# ── Route ───────────────────────────────────────────────────────────────────

@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    # (id, label, provides, probe_callable, governor_name)
    sources = [
        ("alpaca",        "Alpaca (data)",     ["daily OHLCV", "5y history"],            lambda: _probe_alpaca("alpaca_live") if credential_store.get("alpaca_live", {}).get("key_id") else _probe_alpaca("alpaca_paper"), "alpaca"),
        ("tradier",       "Tradier (live)",    ["quotes", "option chains", "calendar"],  _probe_tradier,              "tradier"),
        ("alpaca_paper",  "Alpaca (paper)",    ["paper stock orders"],                   lambda: _probe_alpaca("alpaca_paper"), None),
        ("ibkr",          "IBKR (live)",       ["IV rank", "intraday bars"],             lambda: _probe_ibkr_gateway(5000), "ibkr"),
        ("ibkr_paper",    "IBKR (paper)",      ["paper orders"],                         lambda: _probe_ibkr_gateway(7499), None),
        ("tiingo",        "Tiingo",            ["daily OHLCV fallback"],                 _probe_tiingo,               "tiingo"),
        ("yfinance",      "yfinance",          ["last-resort fallback"],                 _probe_yfinance,             "yfinance"),
    ]
    now = time.monotonic()
    results: list[DataSourceStatus] = []
    for src_id, label, provides, probe, gov_name in sources:
        cached = _PROBE_CACHE.get(src_id)
        if cached and cached[2] > now:
            status, detail = cached[0], cached[1]
        else:
            try:
                probe_status, detail = probe()
            except Exception as exc:
                logger.warning("probe failed for %s: %s", src_id, exc)
                probe_status, detail = "down", str(exc)
            status = _status_for_probe(gov_name, probe_status)
            _PROBE_CACHE[src_id] = (status, detail, now + _CACHE_TTL)
        results.append(DataSourceStatus(
            id=src_id, label=label, status=status, provides=provides, detail=detail,
        ))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_sources.py -v`
Expected: PASS (all probe tests pass)

- [ ] **Step 5: Run the full backend suite to check nothing regressed**

Run: `pytest -q`
Expected: PASS (no failures introduced; pre-existing unrelated failures, if any, unchanged)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/data_sources.py backend/tests/test_data_sources.py
git commit -m "feat(data-sources): real 4-state probes, TTL cache, Alpaca, governor-fed degraded"
```

---

## Frontend note (status string compatibility)

`frontend/lib/api.ts` `DataSourceInfo.status` is typed `'ok' | 'unavailable' | 'error' | 'unconfigured'`. This stage changes the backend to emit `'connected' | 'degraded' | 'down' | 'unconfigured'`. `frontend/components/organisms/ContextRail/QuickLook.tsx` renders `src.status === 'ok' ? 'connected' : src.status` and uses `data-status={src.status}` for the dot colour. A **follow-up frontend task (Stage 4, UI)** updates the type union and the dot CSS to the new states and adds the `degraded` colour. Until then the panel still renders (it just shows the raw new strings). This is intentionally deferred to keep Stage 1 backend-only and shippable. Do **not** change the frontend in this stage.

---

## Self-Review (completed)

- **Spec coverage (§5.1):** token bucket (T1), circuit breaker (T2), unique-symbol budget (T3), 429 backoff (T4), `call()` facade + registry sized to §3 tiers (T5). ✅
- **Spec coverage (§5.5):** real authenticated probes, 4-state, TTL cache, governor-fed `degraded`, Alpaca probe (T7). ✅
- **Spec coverage (§5.6 slots):** Alpaca credential slots + `secret_key` masking (T6). ✅
- **Placeholder scan:** no TBD/TODO; every code step is complete and runnable. ✅
- **Type consistency:** `TokenBucket(rate, per, capacity)`, `CircuitBreaker(fail_threshold, cooldown)`, `SymbolBudget(max_symbols, window)`, `RateLimited(message, retry_after)`, `backoff_delay(attempt, base, cap)`, `Governor.call/health/set_status/symbol_allowed`, `_ProviderState`, `get_governor()`, `_probe_alpaca(slot)`, `_status_for_probe(governor_name, probe_status)` — names identical across all tasks. ✅
- **Out of scope (correctly deferred):** ingestion job, Alpaca data adapter, multi-basis schema, scan-path rewrite, provenance logging, Settings UI form, execution adapter — these are Stages 2–4.
