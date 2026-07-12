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
    """`Leg`/`LimitOrder` are strict Pydantic v2 models in the real SDK — a
    bare MagicMock() fails Pydantic validation the moment the adapter builds
    `LimitOrder(legs=[leg], price=price)`, raising pydantic_core.ValidationError
    before this test's own assertions run. Patch the `LimitOrder` class itself
    (not just its inputs) so construction never touches real Pydantic
    validation — this also lets the test assert on the exact price passed in,
    which doubles as a check on the debit/credit sign convention."""
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
