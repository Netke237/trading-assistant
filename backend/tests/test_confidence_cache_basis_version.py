"""TRADING-REVIEW-PHASE-C T2: bar-derived cache keys carry a basis version.

T1 changed the basis of every bar `_read_bars` returns (open/high/low now
scaled by adj_factor like close) and T7 changed the stock trigger's replay
(`setup_window_bars`). A confidence value cached before either change was
computed on the old basis, and the persistent confidence cache would serve it
for up to its 7-day TTL. The version token in the key makes every pre-change
row miss; old rows expire naturally.
"""
from __future__ import annotations

EXPECTED_VERSION = "b4"  # b4: PROVIDER-FALLBACK-FORMING-BAR #536 (no forming bars on the Options DB-miss fallback)

# The pre-T2 key format for cache_key("AAPL", "Bullish", "Swing", None, None,
# scoring_mode="stock"): no version suffix.
_OLD_FORMAT_KEY = "AAPL|bullish|swing|default:default|stock"


def test_cache_key_ends_with_basis_version():
    import app.data.confidence_cache as cc

    key = cc.cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="stock")
    assert key.endswith(f"|{EXPECTED_VERSION}")


async def test_old_format_key_is_not_served(monkeypatch, tmp_path):
    import app.data.confidence_cache as cc

    # Isolate from the real backend/data/confidence_cache.db and the warm L1.
    monkeypatch.setattr(cc, "_DB_PATH", str(tmp_path / "confidence_cache.db"))
    monkeypatch.setattr(cc, "_store", {})
    cc._init_db()

    await cc.set_cached(_OLD_FORMAT_KEY, {"confidence": 77, "sample_size": 120})
    assert cc.get_cached(_OLD_FORMAT_KEY) is not None  # the old row really is there

    new_key = cc.cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="stock")
    assert cc.get_cached(new_key) is None


def test_backtest_cache_key_carries_basis_version():
    from app.routers.stock_scan import _backtest_key

    bars = [{"time": f"2026-01-{d:02d}", "close": 100.0 + d} for d in range(1, 31)]
    key = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, {"a": 1},
                        commission=0.001, min_trades=5, min_win_rate=0.45)
    # A whole field, not a substring: the md5 hash fields are hex and could
    # contain the token by chance.
    assert EXPECTED_VERSION in key.split("|")

    from app.data.confidence_cache import BARS_BASIS_VERSION
    assert BARS_BASIS_VERSION == EXPECTED_VERSION
