"""test_backfill_alpaca_holes.py — Unit tests for Alpaca holes backfill script (#560).

Verifies:
1. Identification of target date gaps (2021-04-19, 2021-10-25, 2022-03-08) within stored date range.
2. Calculation of exact adj_factor = round(adj_close / raw_close, 8) from Alpaca SIP bars.
3. Timestamp fetched_at is pinned to match surrounding retained rows to satisfy batch_step staleness invariant.
4. --dry-run flag avoids executing database INSERTs/UPDATEs.
5. Strict single-source rule: foreign provider bars (tiingo/yfinance) are never spliced into Alpaca rows.
6. Candidate bar validation: reject bars without positive OHLCV.
7. Credential validation and error handling on 403 Forbidden / missing SIP entitlement.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M
from app.services import historical_store as hs
from scripts.backfill_alpaca_holes import (
    DEFAULT_TARGET_DATES,
    backfill_symbol,
    build_parser,
    compute_adj_factor,
    find_surrounding_retained_row,
    find_target_date_gaps,
    run_backfill,
    validate_candidate_bar,
    verify_alpaca_sip_access,
)


@pytest_asyncio.fixture
async def test_db():
    """In-memory SQLite database with OhlcvDailyModel schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


def make_bar_row(
    symbol: str,
    bar_date: date,
    close: float = 100.0,
    adj_factor: float = 1.0,
    source: str = "alpaca",
    fetched_at: datetime | None = None,
) -> M:
    return M(
        symbol=symbol,
        date=bar_date,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=100_000,
        adj_factor=adj_factor,
        split_factor=1.0,
        div_cash=0.0,
        source=source,
        fetched_at=fetched_at or datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
    )


class TestCLIOptionsParsing:
    def test_default_arguments(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.dry_run is False
        assert args.symbols is None
        assert args.limit is None
        assert args.dates == "2021-04-19,2021-10-25,2022-03-08"

    def test_custom_arguments(self):
        parser = build_parser()
        args = parser.parse_args([
            "--dry-run",
            "--symbols", "AAPL,MSFT",
            "--limit", "10",
            "--dates", "2022-03-08",
        ])
        assert args.dry_run is True
        assert args.symbols == ["AAPL,MSFT"]
        assert args.limit == 10
        assert args.dates == "2022-03-08"


class TestTargetGapIdentification:
    @pytest.mark.asyncio
    async def test_identifies_gaps_only_within_stored_date_range(self, test_db):
        _, factory = test_db
        target_dates = [date(2021, 4, 19), date(2021, 10, 25), date(2022, 3, 8)]

        # SYM1: stored 2021-01-04 to 2022-12-30, missing all 3 dates
        # SYM2: stored 2022-01-03 to 2022-12-30 (IPO in 2022), missing only 2022-03-08
        # SYM3: stored 2021-01-04 to 2022-12-30, has all 3 dates
        async with factory() as session:
            # SYM1 bars
            session.add(make_bar_row("SYM1", date(2021, 1, 4)))
            session.add(make_bar_row("SYM1", date(2021, 4, 16)))
            session.add(make_bar_row("SYM1", date(2021, 4, 20)))
            session.add(make_bar_row("SYM1", date(2022, 12, 30)))

            # SYM2 bars (started 2022-01-03)
            session.add(make_bar_row("SYM2", date(2022, 1, 3)))
            session.add(make_bar_row("SYM2", date(2022, 3, 7)))
            session.add(make_bar_row("SYM2", date(2022, 3, 9)))
            session.add(make_bar_row("SYM2", date(2022, 12, 30)))

            # SYM3 bars (has all target dates)
            session.add(make_bar_row("SYM3", date(2021, 1, 4)))
            session.add(make_bar_row("SYM3", date(2021, 4, 19)))
            session.add(make_bar_row("SYM3", date(2021, 10, 25)))
            session.add(make_bar_row("SYM3", date(2022, 3, 8)))
            session.add(make_bar_row("SYM3", date(2022, 12, 30)))
            await session.commit()

        async with factory() as session:
            gaps = await find_target_date_gaps(session, target_dates)

        assert "SYM1" in gaps
        assert gaps["SYM1"] == target_dates  # all 3

        assert "SYM2" in gaps
        assert gaps["SYM2"] == [date(2022, 3, 8)]  # 2021 dates outside SYM2 range!

        assert "SYM3" not in gaps  # No gaps


class TestExactAdjFactorCalculation:
    def test_exact_factor_preservation(self):
        # SRE on 2022-03-08: raw_close 153.39, adj_close 66.14008941
        raw_close = 153.39
        adj_close = 66.14008941
        expected = round(adj_close / raw_close, 8)
        assert expected == round(66.14008941 / 153.39, 8)

        computed = compute_adj_factor(raw_close, adj_close)
        assert computed == expected

    def test_zero_raw_close_safety(self):
        assert compute_adj_factor(0.0, 10.0) == 1.0


class TestFetchedAtPinnedSurroundingRows:
    @pytest.mark.asyncio
    async def test_fetched_at_pinned_prevents_batch_step(self, test_db):
        _, factory = test_db
        pinned_ts = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        target = date(2022, 3, 8)

        # Retained rows on 2022-03-07 and 2022-03-09 with pinned_ts
        # Step in adj_factor between 2022-03-07 and 2022-03-08 (e.g. ex-dividend)
        row_0307 = make_bar_row("AEE", date(2022, 3, 7), close=100.0, adj_factor=0.50000000, fetched_at=pinned_ts)
        row_0309 = make_bar_row("AEE", date(2022, 3, 9), close=100.0, adj_factor=0.49500000, fetched_at=pinned_ts)

        async with factory() as session:
            session.add_all([row_0307, row_0309])
            await session.commit()

        # Find surrounding row
        async with factory() as session:
            surrounding = await find_surrounding_retained_row(session, "AEE", target)
            assert surrounding is not None
            # Compare without timezone ambiguity (SQLite stores naive UTC)
            assert surrounding.fetched_at.replace(tzinfo=timezone.utc) == pinned_ts

            # Mock AlpacaClient returning bar for 2022-03-08
            mock_client = AsyncMock()
            mock_client.fetch_raw.return_value = {
                "AEE": [{"t": "2022-03-08T05:00:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 200_000}]
            }
            mock_client.fetch_adj.return_value = {
                "AEE": [{"t": "2022-03-08T05:00:00Z", "c": 49.5}]  # factor 0.495
            }

            res = await backfill_symbol(
                session=session,
                client=mock_client,
                symbol="AEE",
                missing_dates=[target],
                dry_run=False,
            )
            assert res["inserted"] == 1
            await session.commit()

        # Verify in database: backfilled row has pinned_ts
        async with factory() as session:
            stmt = select(M).where(M.symbol == "AEE").order_by(M.date)
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 3
            assert rows[1].date == target
            assert rows[1].fetched_at.replace(tzinfo=timezone.utc) == pinned_ts

            # Check stale_reasons: uniform fetch_date must NOT trigger batch_step!
            db_rows = [
                (r.date, r.close, r.adj_factor, r.split_factor, r.div_cash, r.source, r.fetched_at)
                for r in rows
            ]
            stale_report = hs.stale_reasons(db_rows)
            # Must not flag batch_step
            if stale_report:
                assert "batch_step" not in stale_report.reasons


class TestDryRunFlag:
    @pytest.mark.asyncio
    async def test_dry_run_avoids_db_writes(self, test_db):
        _, factory = test_db
        target = date(2022, 3, 8)
        row_0307 = make_bar_row("AAPL", date(2022, 3, 7))

        async with factory() as session:
            session.add(row_0307)
            await session.commit()

        mock_client = AsyncMock()
        mock_client.fetch_raw.return_value = {
            "AAPL": [{"t": "2022-03-08T05:00:00Z", "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.0, "v": 1_000_000}]
        }
        mock_client.fetch_adj.return_value = {
            "AAPL": [{"t": "2022-03-08T05:00:00Z", "c": 153.0}]
        }

        async with factory() as session:
            res = await backfill_symbol(
                session=session,
                client=mock_client,
                symbol="AAPL",
                missing_dates=[target],
                dry_run=True,
            )
            assert res["would_insert"] == 1
            assert res["inserted"] == 0
            await session.commit()

        # Ensure no row on 2022-03-08 was inserted
        async with factory() as session:
            stmt = select(M).where(M.symbol == "AAPL")
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1
            assert rows[0].date == date(2022, 3, 7)


class TestStrictSingleSourceRule:
    @pytest.mark.asyncio
    async def test_foreign_provider_series_not_spliced(self, test_db):
        _, factory = test_db
        target = date(2022, 3, 8)
        # Tiingo-sourced series
        row_tiingo = make_bar_row("XYZ", date(2022, 3, 7), source="tiingo")

        async with factory() as session:
            session.add(row_tiingo)
            await session.commit()

        mock_client = AsyncMock()
        mock_client.fetch_raw.return_value = {
            "XYZ": [{"t": "2022-03-08T05:00:00Z", "o": 50.0, "h": 51.0, "l": 49.0, "c": 50.0, "v": 500_000}]
        }
        mock_client.fetch_adj.return_value = {
            "XYZ": [{"t": "2022-03-08T05:00:00Z", "c": 50.0}]
        }

        async with factory() as session:
            res = await backfill_symbol(
                session=session,
                client=mock_client,
                symbol="XYZ",
                missing_dates=[target],
                dry_run=False,
            )
            assert res["skipped"] is True
            assert res.get("reason") == "foreign_source"
            await session.commit()

        # Table row count must remain 1
        async with factory() as session:
            stmt = select(M).where(M.symbol == "XYZ")
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1
            assert rows[0].source == "tiingo"


class TestCandidateBarValidation:
    def test_validates_positive_ohlcv(self):
        valid_bar = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 1000}
        assert validate_candidate_bar(valid_bar) is True

        # Non-positive prices
        assert validate_candidate_bar({"open": 0.0, "high": 10.0, "low": 5.0, "close": 8.0, "volume": 100}) is False
        assert validate_candidate_bar({"open": 10.0, "high": -1.0, "low": 5.0, "close": 8.0, "volume": 100}) is False
        assert validate_candidate_bar({"open": 10.0, "high": 10.0, "low": 0.0, "close": 8.0, "volume": 100}) is False
        assert validate_candidate_bar({"open": 10.0, "high": 10.0, "low": 5.0, "close": 0.0, "volume": 100}) is False

        # Non-positive volume
        assert validate_candidate_bar({"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 0}) is False
        assert validate_candidate_bar({"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": -10}) is False

        # Invalid high/low relationship
        assert validate_candidate_bar({"open": 10.0, "high": 8.0, "low": 9.0, "close": 8.5, "volume": 100}) is False


class TestCredentialValidationAndForbidden:
    @pytest.mark.asyncio
    async def test_sip_probe_success(self):
        mock_client = AsyncMock()
        mock_client.feed = "sip"
        mock_client.fetch_raw.return_value = {
            "SPY": [{"t": "2022-03-08T05:00:00Z", "c": 416.0}]
        }
        res = await verify_alpaca_sip_access(mock_client)
        assert res is True

    @pytest.mark.asyncio
    async def test_sip_probe_forbidden(self):
        mock_client = AsyncMock()
        mock_client.feed = "iex"  # Fallback to IEX due to 403 Forbidden
        mock_client.fetch_raw.side_effect = Exception("403 Forbidden")
        res = await verify_alpaca_sip_access(mock_client)
        assert res is False
