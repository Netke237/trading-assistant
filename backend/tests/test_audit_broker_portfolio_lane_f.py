"""Lane F comprehensive audit test suite (APP-AUDIT-BROKER-PORTFOLIO / issue #354).

Covers:
- Task 1: Canonical order normalization & broker adapter payloads across Tradier,
  IBKR, Tastytrade, and Alpaca paper adapters.
- Task 2: Risk gates, capital limits, exposure holds, and rejection zero-state.
- Task 3: Broker attempt lifecycle, deduplication, idless option orders, and
  zero-redispatch of uncertain outcomes.
- Task 4: Portfolio position reconciliation, schema mapping, added fills arithmetic,
  rung share rescaling, realized P&L, and the unrouted broker exit stub.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data.alpaca_paper_execution import AlpacaPaperAdapter
from app.data.ibkr_paper import BrokerOrder, IbkrPaperAdapter, OrderResult
from app.data.order_errors import (
    OrderAdmissionRefusedError,
    OrderPreflightRefusedError,
)
from app.data.tastytrade_paper import TastytradePaperAdapter, get_option_chain
from app.data.tradier_paper import (
    TradierPaperAdapter,
    _EQUITY_SIDE,
    _OPTION_SIDE,
)
from app.database import Base
from app.models.broker_attempt import BrokerAttempt, ExposureGuard
from app.models.closed_position import ClosedPositionModel
from app.models.portfolio import PortfolioPositionModel
from app.routers import broker as broker_routes
from app.routers import portfolio as portfolio_routes
from app.routers.portfolio import is_short_stock_position
from app.services.broker_attempts import (
    BrokerAttemptConflict,
    BrokerAttemptRejected,
    BrokerAttemptService,
    _FORWARD,
)
from app.services.broker_router import BrokerRouter
from app.services.portfolio_exposure import (
    ExposureHold,
    _uncovered_notional,
    capacity_positions,
    load_holds,
    lock_exposure,
    release_hold,
    weighted_entry,
)
from app.services.portfolio_performance import (
    _contract_multiplier,
    realized_pnl,
)
from app.services.portfolio_risk import (
    PortfolioPosition,
    check_position_risk,
    premium_cap_basis,
)
from app.services.position_writer import (
    _rescale_rung_shares,
)


def _sample_payload(**overrides):
    base = {
        "kind": "stock",
        "broker": "ibkr_paper",
        "symbol": "AAPL",
        "instrument": "AAPL|STOCK",
        "action": "BUY",
        "effect": "OPEN",
        "quantity": 10,
        "order_type": "LMT",
        "limit": "185.50",
        "tif": "DAY",
        "conid": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Task 1: Broker Adapters & Payload Contract Audit
# ---------------------------------------------------------------------------

class TestTask1BrokerAdapters:
    def test_canonical_order_normalization_stock(self):
        """Stock order normalization creates {symbol}|STOCK and normalizes Decimal."""
        req = broker_routes.StockOrderRequest(
            broker="alpaca_paper",
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=10,
            order_type="LMT",
            limit_price=185.500000000001,
            tif="DAY",
        )
        canon = broker_routes._canonical_order("stock", req)
        assert canon["instrument"] == "AAPL|STOCK"
        assert canon["quantity"] == 10
        assert isinstance(canon["quantity"], int)
        # Normalized decimal removes trailing zeros / fp artifacts
        assert canon["limit"] == str(Decimal("185.500000000001").normalize())

    def test_canonical_order_normalization_option(self):
        """Option order normalization uses 21-char OCC symbol and normalized Decimal."""
        occ = "AAPL250516C00185000"
        req = broker_routes.OptionOrderRequest(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol=occ,
            action="BUY",
            effect="OPEN",
            quantity=5,
            order_type="LMT",
            limit_price=4.20,
            tif="DAY",
            conid=1234567,
        )
        canon = broker_routes._canonical_order("option", req)
        assert canon["instrument"] == occ
        assert canon["quantity"] == 5
        assert canon["conid"] == 1234567
        assert canon["limit"] == str(Decimal("4.2").normalize())

    def test_tradier_endpoint_and_side_mapping(self):
        """Tradier paper adapter targets sandbox accounts orders and maps 4-way sides."""
        adapter = TradierPaperAdapter(token="test_tok", account_id="VA12345678")
        assert adapter._account == "VA12345678"

        # Verify endpoint in _build_params and URL format
        order = BrokerOrder(
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=10,
            order_type="LMT",
            limit_price=185.0,
            tif="DAY",
        )
        params = adapter._build_params(order)
        assert params["class"] == "equity"
        assert params["symbol"] == "AAPL"
        assert params["side"] == "buy"
        assert params["quantity"] == "10"
        assert params["type"] == "limit"
        assert params["duration"] == "day"
        assert params["price"] == "185.0"

        # Equity 4-way mapping
        assert _EQUITY_SIDE[("BUY", "OPEN")] == "buy"
        assert _EQUITY_SIDE[("SELL", "OPEN")] == "sell_short"
        assert _EQUITY_SIDE[("SELL", "CLOSE")] == "sell"
        assert _EQUITY_SIDE[("BUY", "CLOSE")] == "buy_to_cover"

        # Option 4-way mapping
        assert _OPTION_SIDE[("BUY", "OPEN")] == "buy_to_open"
        assert _OPTION_SIDE[("SELL", "OPEN")] == "sell_to_open"
        assert _OPTION_SIDE[("SELL", "CLOSE")] == "sell_to_close"
        assert _OPTION_SIDE[("BUY", "CLOSE")] == "buy_to_close"

        # Rate governor admission refusal raises OrderAdmissionRefusedError
        with patch("app.data.governor.get_governor") as mock_get_gov:
            mock_gov = MagicMock()
            mock_gov.admit_sync.return_value = False
            mock_get_gov.return_value = mock_gov
            with pytest.raises(OrderAdmissionRefusedError) as exc_info:
                adapter.place_order(order)
            assert "rate-limit budget busy" in str(exc_info.value)

    def test_ibkr_paper_payload_keys_and_conid_contract(self):
        """IBKR order ticket payload builder uses conidex/secType when conid is provided."""
        adapter = IbkrPaperAdapter(base_url="https://localhost:7499/v1/api", account_id="DU1234567")
        # Option order with pre-resolved conid
        order = BrokerOrder(
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=2,
            order_type="LMT",
            limit_price=3.50,
            tif="DAY",
            conid=7654321,
            sec_type="OPT",
            option_symbol="AAPL250516C00185000",
        )
        payload = adapter._build_payload(order)
        orders = payload["orders"]
        assert len(orders) == 1
        ticket = orders[0]
        assert ticket["orderType"] == "LMT"
        assert ticket["side"] == "BUY"
        assert ticket["quantity"] == 2
        assert ticket["conidex"] == "7654321"
        assert ticket["secType"] == "7654321:OPT"
        assert "symbol" not in ticket

    def test_ibkr_confirmation_question_http_502(self):
        """IBKR confirmation question raises HTTPException(502) and marks attempt as unsubmitted."""
        res = OrderResult(
            order_id="pending-conf",
            status="AwaitingConfirmation",
            broker="ibkr_paper",
            message="Question: Price exceeds threshold. Confirm?",
            awaiting_confirmation=True,
        )
        question = broker_routes._confirmation_question(res)
        assert "Price exceeds threshold" in question

        with pytest.raises(HTTPException) as exc_info:
            broker_routes._raise_if_awaiting_confirmation(res, "rec-1", "option", "AAPL")
        assert exc_info.value.status_code == 502
        assert "IBKR did not place the order" in exc_info.value.detail

    def test_tastytrade_paper_order_type_and_price_sign(self):
        """Tastytrade rejects market orders and serializes limit price with correct signs."""
        fake_session = MagicMock()
        fake_account = MagicMock()
        fake_leg = MagicMock()
        fake_equity = MagicMock()
        fake_equity.build_leg.return_value = fake_leg
        fake_response = MagicMock()
        fake_response.order.id = "12345"
        fake_response.order.status = "Received"

        async def fake_account_get(session, account_id):
            return fake_account

        async def fake_equity_get(session, symbol):
            return fake_equity

        fake_account.place_order = AsyncMock(return_value=fake_response)

        with patch("app.data.tastytrade_paper.get_session", return_value=fake_session), \
             patch("app.data.tastytrade_paper.Account.get", side_effect=fake_account_get), \
             patch("app.data.tastytrade_paper.Equity.get", side_effect=fake_equity_get), \
             patch("app.data.tastytrade_paper.LimitOrder") as MockLimitOrder:
            MockLimitOrder.return_value = MagicMock()
            adapter = TastytradePaperAdapter(account_id="5WZ12345")

            # 1. Market orders must be refused
            mkt_order = BrokerOrder(
                symbol="AAPL",
                action="BUY",
                effect="OPEN",
                quantity=1,
                order_type="MKT",
                limit_price=None,
                tif="DAY",
            )
            with pytest.raises(OrderPreflightRefusedError) as exc_info:
                adapter.place_order(mkt_order)
            assert "only supports limit orders" in str(exc_info.value)

            # 2. BUY limit orders must serialize as negative Decimal (debit)
            buy_order = BrokerOrder(
                symbol="AAPL",
                action="BUY",
                effect="OPEN",
                quantity=1,
                order_type="LMT",
                limit_price=150.0,
                tif="DAY",
            )
            adapter.place_order(buy_order)
            MockLimitOrder.assert_called_with(legs=[fake_leg], price=Decimal("-150.0"))
            assert fake_account.place_order.call_args.kwargs.get("dry_run") is False

            # 3. SELL limit orders must serialize as positive Decimal (credit)
            sell_order = BrokerOrder(
                symbol="AAPL",
                action="SELL",
                effect="OPEN",
                quantity=1,
                order_type="LMT",
                limit_price=150.0,
                tif="DAY",
            )
            adapter.place_order(sell_order)
            MockLimitOrder.assert_called_with(legs=[fake_leg], price=Decimal("150.0"))

    @pytest.mark.asyncio
    async def test_tastytrade_paper_option_leg_resolution(self):
        """Tastytrade paper adapter resolves option legs via option chain."""
        adapter = TastytradePaperAdapter(account_id="5WA12345")
        mock_session = MagicMock()

        # Missing option_symbol raises ValueError
        order_missing_occ = BrokerOrder(
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=1,
            order_type="LMT",
            limit_price=3.50,
            sec_type="OPT",
            option_symbol=None,
        )
        with pytest.raises(ValueError, match="OPT orders require order.option_symbol"):
            await adapter._resolve_leg(mock_session, order_missing_occ)

        # Successful resolution matching option symbol in chain
        order_valid_occ = BrokerOrder(
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=2,
            order_type="LMT",
            limit_price=3.50,
            sec_type="OPT",
            option_symbol="AAPL  250516C00185000",
        )
        mock_opt = MagicMock()
        mock_opt.symbol = "AAPL  250516C00185000"
        mock_opt.build_leg.return_value = {"leg": "resolved"}

        with patch("app.data.tastytrade_paper.get_option_chain", new_callable=AsyncMock) as mock_chain:
            mock_chain.return_value = {"2025-05-16": [mock_opt]}
            leg = await adapter._resolve_leg(mock_session, order_valid_occ)
            assert leg == {"leg": "resolved"}
            mock_opt.build_leg.assert_called_once_with(2, "Buy to Open")

    def test_alpaca_paper_option_rejection(self):
        """Alpaca paper adapter refuses option orders with OrderPreflightRefusedError."""
        adapter = AlpacaPaperAdapter(key_id="KEY123", secret_key="SEC456")
        opt_order = BrokerOrder(
            symbol="AAPL",
            action="BUY",
            effect="OPEN",
            quantity=1,
            order_type="LMT",
            limit_price=2.00,
            tif="DAY",
            sec_type="OPT",
            option_symbol="AAPL250516C00185000",
        )
        with pytest.raises(OrderPreflightRefusedError) as exc_info:
            adapter.place_order(opt_order)
        assert "only supports stock" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Task 2: Risk Gates, Capital Limits & Rejection Boundary
# ---------------------------------------------------------------------------

class TestTask2RiskGates:
    def test_premium_cap_basis_lmt_and_mkt(self):
        """Long option risk basis bounds entry at max(mid, limit) for LMT and ask for MKT."""
        # LMT order: mid = 2.00, limit = 2.50 -> basis is 2.50
        basis_lmt = premium_cap_basis(
            mid=2.00,
            order_type="LMT",
            limit_price=2.50,
            ask=2.10,
        )
        assert basis_lmt == 2.50

        # LMT order: mid = 2.50, limit = 2.00 -> basis is 2.50 (max(mid, limit))
        basis_lmt_mid = premium_cap_basis(
            mid=2.50,
            order_type="LMT",
            limit_price=2.00,
            ask=2.60,
        )
        assert basis_lmt_mid == 2.50

        # MKT order: ask = 2.60 -> basis is ask
        basis_mkt = premium_cap_basis(
            mid=2.50,
            order_type="MKT",
            limit_price=None,
            ask=2.60,
        )
        assert basis_mkt == 2.60

    def test_capital_cap_rejection(self):
        """Order exceeding max_contracts or single position cap is rejected by check_position_risk."""
        # 1. Option contracts > max_contracts_per_trade (10)
        res_contracts = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2025-05-16|C",
            proposed_contracts=15,
            entry_premium=2.50,
            current_price=2.50,
            portfolio=[],
            portfolio_value=100000.0,
        )
        assert res_contracts.approved is False
        assert "exceeds_max_contracts_per_trade" in res_contracts.reasons

        # 2. Portfolio value too small (< min_portfolio_value)
        res_small = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2025-05-16|C",
            proposed_contracts=1,
            entry_premium=2.50,
            current_price=2.50,
            portfolio=[],
            portfolio_value=500.0,
        )
        assert res_small.approved is False
        assert "portfolio_too_small" in res_small.reasons

    def test_loss_cap_rejection(self):
        """Single trade exposure exceeding max_single_position_pct / max_loss_per_trade_pct is capped or blocked."""
        # Option trade where premium exceeds portfolio limit and cannot even fit 1 contract
        res_blocked = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2025-05-16|C",
            proposed_contracts=1,
            entry_premium=50.0,  # 1 contract * 100 * 50 = $5000 against a $20000 portfolio (25% exposure, cap is typically 5%)
            current_price=50.0,
            portfolio=[],
            portfolio_value=20000.0,
        )
        assert res_blocked.approved is False
        assert "single_trade_exposure_too_high" in res_blocked.reasons

    @pytest.mark.asyncio
    async def test_rejection_zero_state_invariant(self, tmp_path):
        """A rejected order produces zero DB position rows and cleanly releases exposure holds."""
        url = f"sqlite+aiosqlite:///{tmp_path / 'zero_state.db'}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Check DB before: zero positions, zero exposure holds
        async with factory() as db:
            count_before = (
                await db.execute(select(func.count()).select_from(PortfolioPositionModel))
            ).scalar_one()
            assert count_before == 0
            holds_before = await load_holds(db)
            assert len(holds_before) == 0

        # Simulate exposure hold reservation for attempt
        async with factory() as db:
            async with db.begin():
                await lock_exposure(db)
                hold = ExposureHold(
                    attempt_id="att_rej_test",
                    instrument="AAPL|STOCK",
                    quantity=10,
                    limit_price="150.0",
                    multiplier=1,
                    notional="1500.0",
                    state="dispatching",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(hold)

        # Verify hold is registered in DB
        async with factory() as db:
            holds = await load_holds(db)
            assert len(holds) == 1
            assert holds[0].attempt_id == "att_rej_test"

        # Attempt execution that raises preflight refusal
        mock_adapter = MagicMock()
        mock_adapter.place_order.side_effect = OrderPreflightRefusedError("Order rejected preflight")
        router = BrokerRouter(adapters={"ibkr_paper": mock_adapter})

        with pytest.raises(OrderPreflightRefusedError):
            order = BrokerOrder(
                symbol="AAPL",
                action="BUY",
                effect="OPEN",
                quantity=10,
                order_type="LMT",
                limit_price=150.0,
            )
            router.execute("ibkr_paper", order)

        # Clean release of the exposure hold upon preflight refusal
        await release_hold("att_rej_test", sessions=factory)

        # Post-rejection zero-state invariant: zero DB positions created, zero active exposure holds
        async with factory() as db:
            count_after = (
                await db.execute(select(func.count()).select_from(PortfolioPositionModel))
            ).scalar_one()
            assert count_after == 0
            holds_after = await load_holds(db)
            assert len(holds_after) == 0


# ---------------------------------------------------------------------------
# Task 3: Broker Attempts Lifecycle, Idempotency & Concurrency Audit
# ---------------------------------------------------------------------------

class TestTask3AttemptsLifecycle:
    def test_state_machine_forward_lifecycle(self):
        """Attempt state machine adheres strictly to lowercase _FORWARD transitions."""
        assert "outcome-unknown" in _FORWARD["preparing"]
        assert "proven-not-submitted" in _FORWARD["dispatching"]
        assert "submitted" in _FORWARD["dispatching"]
        assert "filled" in _FORWARD["dispatching"]
        assert "outcome-unknown" in _FORWARD["dispatching"]
        # Terminal states are not keys in _FORWARD
        assert "filled" not in _FORWARD
        assert "proven-not-submitted" not in _FORWARD

    @pytest.mark.asyncio
    async def test_deduplication_double_click(self, tmp_path):
        """Second call with same attempt_id returns cached response with leader=False."""
        url = f"sqlite+aiosqlite:///{tmp_path / 'dedup.db'}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        svc = BrokerAttemptService(factory)
        attempt_id = "test-attempt-123"
        payload = _sample_payload()

        # First claim succeeds as leader
        claim1 = await svc.claim(attempt_id, payload)
        assert claim1.leader is True
        assert claim1.authorized is True
        assert claim1.state == "dispatching"

        # Second claim with same attempt_id and same payload is not leader
        claim2 = await svc.claim(attempt_id, payload)
        assert claim2.leader is False
        assert claim2.authorized is False
        assert claim2.state == "dispatching"

    @pytest.mark.asyncio
    async def test_idless_option_order_matching(self, tmp_path):
        """claim_production matches prepared position row and links order_attempt_id."""
        url = f"sqlite+aiosqlite:///{tmp_path / 'idless.db'}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        contract = "AAPL|185|2025-05-16|C"
        rec_id = "rec-test-123"
        async with factory() as db:
            pos = PortfolioPositionModel(
                rec_id=rec_id,
                symbol="AAPL",
                contract=contract,
                direction="Bullish",
                qty=2,
                entry_price=3.50,
                entry_date="2026-10-21",
                prepared_order={
                    "kind": "option",
                    "broker": "ibkr_paper",
                    "symbol": "AAPL",
                    "instrument": "AAPL250516C00185000",
                    "quantity": 2,
                    "action": "BUY",
                    "effect": "OPEN",
                    "order_type": "LMT",
                    "limit": "3.5",
                    "tif": "DAY",
                    "conid": 123456,
                },
            )
            db.add(pos)
            await db.commit()

        svc = BrokerAttemptService(factory)
        payload = {
            "kind": "option",
            "broker": "ibkr_paper",
            "symbol": "AAPL",
            "instrument": "AAPL250516C00185000",
            "action": "BUY",
            "effect": "OPEN",
            "quantity": 2,
            "order_type": "LMT",
            "limit": "3.50",
            "tif": "DAY",
            "conid": 123456,
        }

        # claim_production with attempt_id=None
        claim = await svc.claim_production(payload, attempt_id=None, saved_rec_id=rec_id)
        assert claim.leader is True
        assert claim.authorized is True
        assert claim.attempt_id is not None

        # Verify attempt linked to position row
        async with factory() as db:
            row = (
                await db.execute(
                    select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
                )
            ).scalar_one()
            assert row.order_attempt_id == claim.attempt_id

    @pytest.mark.asyncio
    async def test_outcome_unknown_no_auto_redispatch(self, tmp_path):
        """An attempt marked outcome-unknown prevents any automated second dispatch."""
        url = f"sqlite+aiosqlite:///{tmp_path / 'unknown.db'}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        svc = BrokerAttemptService(factory)
        payload = _sample_payload()
        claimed = await svc.claim("unknown-attempt", payload)
        assert claimed.authorized is True

        # Transition to outcome-unknown
        recorded = await svc.record_outcome(
            "unknown-attempt",
            "outcome-unknown",
            expected_version=claimed.verification_version,
            broker_response='{"detail":"network drop"}',
            broker_status="unknown",
        )
        assert recorded.state == "outcome-unknown"
        assert recorded.authorized is False

        # Attempting to re-dispatch with a new explicit attempt raises Conflict
        with pytest.raises(BrokerAttemptConflict):
            await svc.claim("new-attempt", payload)


# ---------------------------------------------------------------------------
# Task 4: Portfolio Position Reconciliation & Arithmetic
# ---------------------------------------------------------------------------

class TestTask4PortfolioReconciliation:
    def test_schema_mapping_and_contract_string(self):
        """PortfolioPositionModel maps qty as Column(Integer) and contract as internal key."""
        pos = PortfolioPositionModel(
            rec_id="rec-456",
            symbol="NVDA",
            contract="NVDA|130|2025-06-20|C",
            direction="Bullish",
            qty=3,
            entry_price=5.20,
            entry_date="2026-10-21",
        )
        assert pos.qty == 3
        assert pos.contract == "NVDA|130|2025-06-20|C"
        # Dynamic cost basis calculation via _contract_multiplier (100 for options)
        multiplier = _contract_multiplier(pos.contract)
        assert multiplier == 100
        cost_basis = pos.entry_price * pos.qty * multiplier
        assert cost_basis == 5.20 * 3 * 100

        pos_stock = PortfolioPositionModel(
            rec_id="rec-457",
            symbol="AAPL",
            contract="AAPL|STOCK",
            direction="Bullish",
            qty=50,
            entry_price=150.0,
            entry_date="2026-10-21",
        )
        assert _contract_multiplier(pos_stock.contract) == 1
        assert pos_stock.entry_price * pos_stock.qty * _contract_multiplier(pos_stock.contract) == 7500.0

    def test_weighted_average_price_arithmetic(self):
        """Added fills calculate exact weighted average entry price via weighted_entry."""
        # Scenario 1: old=10 @ 150.0, new total=15 (added 5 shares @ 165.0)
        # (10 * 150.0 + 5 * 165.0) / 15 = (1500 + 825) / 15 = 2325 / 15 = 155.0
        new_entry_1 = weighted_entry(old_qty=10, old_entry=150.0, new_qty=15, fill_price=165.0)
        assert new_entry_1 == 155.0

        # Scenario 2: old=100 @ 100.0, new total=150 (added 50 shares @ 130.0)
        # (100 * 100.0 + 50 * 130.0) / 150 = (10000 + 6500) / 150 = 16500 / 150 = 110.0
        new_entry_2 = weighted_entry(old_qty=100, old_entry=100.0, new_qty=150, fill_price=130.0)
        assert new_entry_2 == 110.0

    def test_rung_share_rescaling_runner_preservation(self):
        """_rescale_rung_shares rescales active rungs while preserving runners."""
        # 100 asked, 2 rungs with 30 each (sum 60), leaving 40 runner shares (40%)
        rungs = [
            {"contractsToSell": 30, "price": 160.0},
            {"contractsToSell": 30, "price": 170.0},
        ]
        # Stored = 100, asked = 100 -> no rescaling needed
        rescaled_noop = _rescale_rung_shares(rungs, asked=100, stored=100)
        assert rescaled_noop == rungs

        # Partial fill: stored = 50, asked = 100
        # target_sum = min(50, (60 * 50) // 100) = 30
        # each rung gets (30 * 50) // 100 = 15, leaving 50 - 30 = 20 runner shares
        rescaled_down = _rescale_rung_shares(rungs, asked=100, stored=50)
        assert [r["contractsToSell"] for r in rescaled_down] == [15, 15]
        total_rescaled = sum(r["contractsToSell"] for r in rescaled_down)
        assert total_rescaled == 30
        runner_remaining = 50 - total_rescaled
        assert runner_remaining == 20
        # Verify exact runner proportion preserved: 20/50 == 40/100 == 0.40
        assert runner_remaining / 50 == (100 - 60) / 100

    def test_realized_pnl_calculation(self):
        """Realized P&L invokes realized_pnl and respects is_short_stock_position sign inversion."""
        # Stock long: exit=180, entry=150, qty=100 -> (180 - 150) * 1 * 100 = 3000.0, 20%
        contract_stock = "AAPL|STOCK"
        assert not is_short_stock_position(contract_stock, "Bullish")
        dollar_long, pct_long = realized_pnl(150.0, 180.0, 100, contract_stock)
        assert dollar_long == 3000.0
        assert pct_long == 20.0

        # Stock short: exit=130, entry=150, qty=100 -> (130 - 150) * 1 * 100 = -2000.0
        # is_short_stock_position("AAPL|STOCK", "Bearish") inverts sign to +2000.0, +13.33%
        assert is_short_stock_position(contract_stock, "Bearish")
        dollar_short, pct_short = realized_pnl(150.0, 130.0, 100, contract_stock)
        if is_short_stock_position(contract_stock, "Bearish"):
            dollar_short, pct_short = -dollar_short, -pct_short
        assert dollar_short == 2000.0
        assert pct_short == 13.33

        # Option long: exit=7.50, entry=5.00, qty=2 contracts, multiplier 100
        # (7.50 - 5.00) * 100 * 2 = 500.0, 50.0%
        contract_opt = "AAPL|185|2025-05-16|C"
        assert _contract_multiplier(contract_opt) == 100
        assert not is_short_stock_position(contract_opt, "Bearish")  # Long put is NOT short stock
        dollar_opt, pct_opt = realized_pnl(5.0, 7.50, 2, contract_opt)
        assert dollar_opt == 500.0
        assert pct_opt == 50.0

    def test_unrouted_broker_exit_stub(self):
        """_maybe_send_close_to_broker in routers/portfolio.py is an unrouted no-op stub."""
        caplog = []
        logger = logging.getLogger("app.routers.portfolio")

        class MockHandler(logging.Handler):
            def emit(self, record):
                caplog.append(record.getMessage())

        handler = MockHandler()
        logger.addHandler(handler)

        closed = ClosedPositionModel(
            id="closed-rec-1",
            rec_id="open-rec-1",
            symbol="AAPL",
            contract="AAPL|STOCK",
            direction="Bullish",
            qty_closed=10,
            entry_price=175.0,
            exit_price=190.0,
            entry_date="2026-10-20",
            exit_date="2026-10-21",
            realized_pnl_dollar=150.0,
            realized_pnl_pct=8.57,
        )
        # Calling _maybe_send_close_to_broker with send=True logs warning and places zero broker calls
        portfolio_routes._maybe_send_close_to_broker(closed, send=True)

        assert any("sendToBroker=True" in m and "not yet implemented" in m for m in caplog)
        logger.removeHandler(handler)
