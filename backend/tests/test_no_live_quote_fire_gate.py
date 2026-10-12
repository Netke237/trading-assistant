import asyncio
import dataclasses
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import httpx
import pytest
from app.data.governor import Governor, TokenBucket
from app.services import auto_trader as at
pytestmark = pytest.mark.real_quote_gate
OCC = "AAPL261016C00185000"
@pytest.fixture
def probe(monkeypatch):
    from app.data import market, governor
    from app.services import market_session
    from app.scoring import contract_validator
    monkeypatch.setattr(market_session, "_market_session_open", lambda _: True)
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("fake", "https://api.tradier.com"))
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    monkeypatch.setattr(contract_validator, "max_quote_age_seconds", lambda: 1800)
    gov = Governor.for_testing("tradier", rate=0.0001, capacity=15, fail_threshold=1)
    monkeypatch.setattr(governor, "get_governor", lambda: gov)
    row = {"symbol": OCC, "bid": 2, "ask": 3, "bid_date": time.time()*1000, "ask_date": time.time()*1000}
    get = Mock()
    monkeypatch.setattr(httpx, "get", get)
    response(get, [row])
    return row, get, gov

def response(get, rows, status=200):
    get.return_value = httpx.Response(status, json={"options": {"option": rows}}, request=httpx.Request("GET", "https://example.test"))

@pytest.mark.parametrize("symbol", ["invalid", "AAPL|185|2026-99-16|C"])
def test_invalid_symbol_no_http(probe, symbol):
    assert at._option_quote_state(symbol) == "invalid_symbol"
    probe[1].assert_not_called()

def test_closed_no_http(probe, monkeypatch):
    from app.services import market_session
    monkeypatch.setattr(market_session, "_market_session_open", lambda _: False)
    assert at._option_quote_state(OCC) == "session_closed"
    probe[1].assert_not_called()

@pytest.mark.parametrize("rows,state", [([], "unavailable"), ([{"symbol": "AAPL261016P00185000", "ask": 3}], "unavailable"), ([{"symbol": "AAPL261023C00185000", "ask": 3}], "unavailable"), ([{"symbol": OCC, "ask": 0}], "one_sided"), ([{"symbol": OCC, "ask": 3, "bid": 0}], "one_sided"), ([{"symbol": OCC, "ask": 3, "bid": 2, "bid_date": 1}], "stale")])
def test_row_states(probe, rows, state):
    response(probe[1], rows)
    assert at._option_quote_state(OCC) == state
    assert probe[1].call_count == 1

@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failure_records_breaker(probe, status):
    response(probe[1], [], status)
    assert at._option_quote_state(OCC) == "unavailable"
    assert probe[2]._providers["tradier"].breaker.is_open

def test_timeout(probe):
    probe[1].side_effect = httpx.TimeoutException("timeout")
    assert at._option_quote_state(OCC) == "unavailable"

def test_no_token_and_open_circuit_no_http(probe, monkeypatch):
    """Site F (the NO-LIVE-QUOTE fire gate) is on the fire path: it is
    admitted by overdraft, so an empty bucket no longer refuses it
    (TRADIER-GOVERNOR plan, docs/superpowers/plans/2026-10-10-tradier-governor-plan.md
    §2 D3 "Site F joins the fire path"). A missing Tradier token and an open
    breaker still return "unavailable" without any HTTP request."""
    from app.data import market
    row, get, gov = probe
    bucket = gov._providers["tradier"].bucket
    # No bucket token left: F books an overdraft token (balance goes
    # negative) and makes its one request, classifying the mocked live row.
    for _ in range(15):
        assert gov.try_acquire("tradier")
    assert at._option_quote_state(OCC) == "live"
    assert get.call_count == 1
    assert bucket._tokens < 0
    # Missing Tradier token: refused before admission, no HTTP, no booking.
    get.reset_mock()
    bucket._tokens = 15
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("", "https://api.tradier.com"))
    assert at._option_quote_state(OCC) == "unavailable"
    get.assert_not_called()
    assert bucket._tokens == pytest.approx(15)
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("fake", "https://api.tradier.com"))
    # Open breaker (forced via record_failure; the fixture's breaker trips at
    # one failure): refused, no HTTP, even with a full bucket.
    gov.record_failure("tradier")
    assert at._option_quote_state(OCC) == "unavailable"
    get.assert_not_called()

def test_live_exact_request_and_config_lag(probe, monkeypatch):
    from app.data import market
    from app.scoring import contract_validator
    row, get, _ = probe
    row["bid_date"] = row["ask_date"] = (time.time()-1000)*1000
    response(get, row)
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 900)
    monkeypatch.setattr(contract_validator, "max_quote_age_seconds", lambda: 110)
    assert at._option_quote_state("AAPL|185|2026-10-16|C") == "live"
    assert get.call_args.kwargs["params"] == {"symbol": "AAPL", "expiration": "2026-10-16", "greeks": "false"}
    assert get.call_args.kwargs["timeout"] == 2.5
    monkeypatch.setattr(contract_validator, "max_quote_age_seconds", lambda: 90)
    assert at._option_quote_state(OCC) == "stale"

def strategy():
    return at.ArmedStrategy(broker="ibkr_paper", symbol="AAPL", option_symbol=OCC, action="BUY", direction="Bullish", quantity=1, order_type="LMT", limit_price=2.5, conid=None, entry_premium=2.5)

@pytest.mark.parametrize("state", ["unavailable", "invalid_symbol", "session_closed", "one_sided", "stale"])
def test_refusal_preserves_arm_no_history(monkeypatch, state):
    svc = at.AutoTradeService()
    armed = strategy()
    svc.arm(armed)
    monkeypatch.setattr(at, "_market_is_open", lambda _: True)
    monkeypatch.setattr(at, "_option_quote_state", lambda _: state)
    execute = Mock()
    monkeypatch.setattr(at, "execute_option_order", execute)
    with pytest.raises(at.ArmPreservedError, match=state):
        svc.fire()
    assert svc.get_state().armed
    assert svc.get_state().strategy is armed
    assert svc.get_state().history == []
    assert not svc._consumed_attempts
    execute.assert_not_called()

@pytest.mark.parametrize("same_contract", [False, True])
def test_rearm_during_probe_refuses(monkeypatch, same_contract):
    svc = at.AutoTradeService()
    armed = strategy()
    newer = dataclasses.replace(armed, option_symbol=OCC if same_contract else "AAPL261016C00190000")
    svc.arm(armed)
    monkeypatch.setattr(at, "_market_is_open", lambda _: True)
    def quote(_):
        svc.arm(newer)
        return "live"
    monkeypatch.setattr(at, "_option_quote_state", quote)
    with pytest.raises(at.ArmPreservedError, match="re-armed"):
        svc.fire()
    assert svc.get_state().strategy is newer
    assert svc.get_state().armed
    assert svc.get_state().history == []

def test_mixed_async_sync_share_budget():
    bucket = TokenBucket(rate=0.0001, capacity=1)
    asyncio.run(bucket.acquire())
    assert not bucket.try_acquire()
    bucket._tokens = 1
    with ThreadPoolExecutor(max_workers=16) as pool:
        admitted = list(pool.map(lambda _: bucket.try_acquire(), range(40)))
    assert sum(admitted) == 1


def test_live_probe_allows_fire(probe, monkeypatch):
    from app.data.ibkr_paper import OrderResult
    svc = at.AutoTradeService()
    svc.arm(strategy())
    monkeypatch.setattr(at, "_market_is_open", lambda _: True)
    monkeypatch.setattr(at, "_apply_vol_sizing", lambda armed: armed)
    execute = Mock(return_value=OrderResult(order_id="quote-live", status="PreSubmitted", broker="ibkr_paper"))
    monkeypatch.setattr(at, "execute_option_order", execute)
    fired = svc.fire()
    assert fired.result.order_id == "quote-live"
    execute.assert_called_once()
    assert not svc.get_state().armed
    assert len(svc.get_state().history) == 1

def test_future_deadline_is_three_seconds(probe, monkeypatch):
    import concurrent.futures
    future = Mock()
    future.result.side_effect = concurrent.futures.TimeoutError()
    executor = Mock()
    executor.submit.return_value = future
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", Mock(return_value=executor))
    assert at._option_quote_state(OCC) == "unavailable"
    future.result.assert_called_once_with(timeout=3.0)
    executor.shutdown.assert_called_once_with(wait=False)
    probe[1].assert_not_called()

def test_no_credentials_no_http(probe, monkeypatch):
    from app.data import market
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("", "https://api.tradier.com"))
    assert at._option_quote_state(OCC) == "unavailable"
    probe[1].assert_not_called()
