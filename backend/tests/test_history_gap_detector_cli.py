"""test_history_gap_detector_cli.py — Unit tests for CLI gap detector & writer gap guard (#559).

Verifies:
1. CLI argument parsing (--symbols, --start, --end, --json-out, --no-exit-code).
2. CLI exit code behavior:
   - Exits 1 when trading day gaps are present.
   - Exits 0 when trading day gaps are present and --no-exit-code is passed.
   - Exits 0 when no gaps exist.
3. JSON output structure (total_symbols_scanned, symbols_with_gaps, total_missing_bars,
   gaps_by_date, symbol_gaps).
4. Window clamping via --start and --end.
5. Multi-symbol universe scanning when --symbols is omitted.
6. Observational warning in history_backfill._single_provider_locked on missing NYSE
   trading days without aborting the write.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M
from app.services import historical_store as hs
from app.services import history_backfill as history
from scripts.history_gap_detector import (
    build_parser,
    detect_database_gaps,
    format_summary_table,
    main,
)


@pytest_asyncio.fixture
async def test_db():
    """In-memory SQLite database populated with OhlcvDailyModel schema."""
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
    source: str = "alpaca",
) -> M:
    return M(
        symbol=symbol,
        date=bar_date,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=100_000,
        adj_factor=1.0,
        split_factor=1.0,
        div_cash=0.0,
        source=source,
        fetched_at=datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc),
    )


class TestCLIOptionsParsing:
    def test_default_arguments(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.symbols is None
        assert args.start is None
        assert args.end is None
        assert args.json_out is None
        assert args.no_exit_code is False

    def test_custom_arguments(self):
        parser = build_parser()
        args = parser.parse_args([
            "--symbols", "AAPL,MSFT",
            "--start", "2022-01-03",
            "--end", "2022-12-30",
            "--json-out", "report.json",
            "--no-exit-code",
        ])
        assert args.symbols == ["AAPL,MSFT"]
        assert args.start == date(2022, 1, 3)
        assert args.end == date(2022, 12, 30)
        assert args.json_out == "report.json"
        assert args.no_exit_code is True

    def test_multiple_symbols_space_separated(self):
        parser = build_parser()
        args = parser.parse_args(["--symbols", "AAPL", "MSFT", "GOOG"])
        assert args.symbols == ["AAPL", "MSFT", "GOOG"]


class TestCLIGapDetection:
    @pytest.mark.asyncio
    async def test_detect_gaps_finds_missing_trading_day(self, test_db):
        _, factory = test_db
        # 2022-03-08 is a Tuesday. Insert Mon 03-07, Wed 03-09, Thu 03-10 (03-08 missing)
        async with factory() as session:
            session.add_all([
                make_bar_row("SRE", date(2022, 3, 7)),
                make_bar_row("SRE", date(2022, 3, 9)),
                make_bar_row("SRE", date(2022, 3, 10)),
            ])
            await session.commit()

            report = await detect_database_gaps(session, symbols=["SRE"])
            assert report["total_symbols_scanned"] == 1
            assert report["symbols_with_gaps"] == 1
            assert report["total_missing_bars"] == 1
            assert report["gaps_by_date"] == {"2022-03-08": 1}
            assert report["symbol_gaps"] == {"SRE": ["2022-03-08"]}

    @pytest.mark.asyncio
    async def test_detect_gaps_clean_history(self, test_db):
        _, factory = test_db
        # Complete sequence for Mon 03-07 to Fri 03-11
        async with factory() as session:
            session.add_all([
                make_bar_row("SRE", date(2022, 3, 7)),
                make_bar_row("SRE", date(2022, 3, 8)),
                make_bar_row("SRE", date(2022, 3, 9)),
                make_bar_row("SRE", date(2022, 3, 10)),
                make_bar_row("SRE", date(2022, 3, 11)),
            ])
            await session.commit()

            report = await detect_database_gaps(session, symbols=["SRE"])
            assert report["total_symbols_scanned"] == 1
            assert report["symbols_with_gaps"] == 0
            assert report["total_missing_bars"] == 0
            assert report["gaps_by_date"] == {}
            assert report["symbol_gaps"] == {}

    @pytest.mark.asyncio
    async def test_window_clamping_excludes_out_of_window_gaps(self, test_db):
        _, factory = test_db
        # Missing 2022-03-08, but evaluation window clamped to [2022-03-10, 2022-03-15]
        async with factory() as session:
            session.add_all([
                make_bar_row("SRE", date(2022, 3, 7)),
                make_bar_row("SRE", date(2022, 3, 9)),
                make_bar_row("SRE", date(2022, 3, 10)),
                make_bar_row("SRE", date(2022, 3, 11)),
            ])
            await session.commit()

            report = await detect_database_gaps(
                session,
                symbols=["SRE"],
                start=date(2022, 3, 10),
                end=date(2022, 3, 11),
            )
            assert report["total_symbols_scanned"] == 1
            assert report["symbols_with_gaps"] == 0
            assert report["total_missing_bars"] == 0

    @pytest.mark.asyncio
    async def test_scans_all_symbols_when_omitted(self, test_db):
        _, factory = test_db
        async with factory() as session:
            # SRE missing 03-08
            session.add_all([
                make_bar_row("SRE", date(2022, 3, 7)),
                make_bar_row("SRE", date(2022, 3, 9)),
            ])
            # AAPL clean 03-07, 03-08, 03-09
            session.add_all([
                make_bar_row("AAPL", date(2022, 3, 7)),
                make_bar_row("AAPL", date(2022, 3, 8)),
                make_bar_row("AAPL", date(2022, 3, 9)),
            ])
            await session.commit()

            report = await detect_database_gaps(session)
            assert report["total_symbols_scanned"] == 2
            assert report["symbols_with_gaps"] == 1
            assert report["total_missing_bars"] == 1
            assert "SRE" in report["symbol_gaps"]
            assert "AAPL" not in report["symbol_gaps"]


class TestCLIMainExecution:
    @pytest.mark.asyncio
    async def test_main_exit_codes_and_json_out(self, test_db, tmp_path, monkeypatch):
        _, factory = test_db
        async with factory() as session:
            session.add_all([
                make_bar_row("SRE", date(2022, 3, 7)),
                make_bar_row("SRE", date(2022, 3, 9)),
            ])
            await session.commit()

        # Monkeypatch session factory used in main()
        monkeypatch.setattr("scripts.history_gap_detector.AsyncSessionLocal", factory)

        json_file = tmp_path / "gaps.json"

        # 1. Exit code 1 when gaps exist
        code = await main(["--symbols", "SRE", "--json-out", str(json_file)])
        assert code == 1
        assert json_file.exists()

        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert data["total_symbols_scanned"] == 1
        assert data["symbols_with_gaps"] == 1
        assert data["total_missing_bars"] == 1
        assert data["gaps_by_date"] == {"2022-03-08": 1}
        assert data["symbol_gaps"] == {"SRE": ["2022-03-08"]}

        # 2. Exit code 0 when --no-exit-code is passed even with gaps
        code_no_exit = await main(["--symbols", "SRE", "--no-exit-code"])
        assert code_no_exit == 0

    @pytest.mark.asyncio
    async def test_main_clean_exit_code_zero(self, test_db, monkeypatch):
        _, factory = test_db
        async with factory() as session:
            session.add_all([
                make_bar_row("AAPL", date(2022, 3, 7)),
                make_bar_row("AAPL", date(2022, 3, 8)),
                make_bar_row("AAPL", date(2022, 3, 9)),
            ])
            await session.commit()

        monkeypatch.setattr("scripts.history_gap_detector.AsyncSessionLocal", factory)
        code = await main(["--symbols", "AAPL"])
        assert code == 0

    def test_format_summary_table(self):
        report = {
            "total_symbols_scanned": 540,
            "symbols_with_gaps": 246,
            "total_missing_bars": 702,
            "gaps_by_date": {"2021-04-19": 240, "2021-10-25": 216, "2022-03-08": 239},
            "symbol_gaps": {"SRE": ["2021-04-19", "2021-10-25", "2022-03-08"]},
        }
        table = format_summary_table(report)
        assert "540" in table
        assert "246" in table
        assert "702" in table
        assert "2021-04-19" in table
        assert "SRE" in table


class TestHistoryBackfillWriterGapObservation:
    @pytest.mark.asyncio
    async def test_single_provider_logs_warning_on_calendar_gap_without_aborting(
        self,
        test_db,
        monkeypatch,
        caplog,
    ):
        """A 1-day trading gap (missing Tuesday 2022-03-08) is <= 7d (_MAX_GAP),

        so it should log an observational warning but proceed with the write.
        """
        _, factory = test_db
        monkeypatch.setattr(history, "AsyncSessionLocal", factory)
        monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
        monkeypatch.setattr(hs, "_utcnow", lambda: datetime(2026, 10, 25, tzinfo=timezone.utc))

        # Prepare bars with 2022-03-08 missing
        dates_with_gap = [date(2022, 3, 7), date(2022, 3, 9), date(2022, 3, 10)]
        fake_bars = [
            {
                "time": d.isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10_000,
                "adj_factor": 1.0,
                "split_factor": 1.0,
                "div_cash": 0.0,
                "source": "tiingo",
            }
            for d in dates_with_gap
        ]

        # Mock tiingo fetch
        from app.data import tiingo
        monkeypatch.setattr(
            tiingo,
            "fetch_historical_candles",
            AsyncMock(return_value=fake_bars),
        )

        async with factory() as db:
            with caplog.at_level(logging.WARNING):
                res = await history._single_provider_locked(
                    db,
                    symbol="GAPTEST",
                    start=date(2022, 3, 7),
                    end=date(2022, 3, 10),
                    providers=["tiingo"],
                )

            # Write succeeded
            assert res.rows_after == 3
            assert res.provider == "tiingo"

            # Check that observational warning was logged
            warning_records = [
                rec for rec in caplog.records
                if rec.levelno == logging.WARNING and "GAPTEST" in rec.getMessage()
            ]
            assert len(warning_records) >= 1
            msg = warning_records[0].getMessage()
            assert "missing NYSE trading day" in msg or "gap" in msg.lower()
            assert "2022-03-08" in msg
