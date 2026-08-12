"""Verify confidence cache L1/L2 behaviour."""
import time
import tempfile
import os


def test_set_and_get_in_memory():
    import app.data.confidence_cache as cc
    cc._store.clear()
    cc.set_cached("k1", {"confidence": 70, "sample_size": 100})
    result = cc.get_cached("k1")
    assert result == {"confidence": 70, "sample_size": 100}


def test_l2_survives_l1_clear():
    """After clearing L1 and re-running warm_load from SQLite, key is recovered."""
    import app.data.confidence_cache as cc
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc._store.clear()

        cc.set_cached("k_persist", {"confidence": 55, "sample_size": 42})
        assert cc.get_cached("k_persist") is not None

        # Simulate restart: clear L1, reload from DB
        cc._store.clear()
        cc._warm_load()

        result = cc.get_cached("k_persist")
        assert result == {"confidence": 55, "sample_size": 42}
    finally:
        cc._DB_PATH = original
        os.unlink(db_path)


def test_expired_entries_not_returned():
    import app.data.confidence_cache as cc
    import sqlite3
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc._store.clear()

        # Write an entry that expired 1 second ago
        expired_ts = time.time() - 1
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO confidence_cache VALUES (?, ?, ?)",
            ("expired_key", '{"confidence": 99, "sample_size": 1}', expired_ts),
        )
        conn.commit()
        conn.close()

        # Warm-load should skip expired entries
        cc._warm_load()
        assert cc.get_cached("expired_key") is None
    finally:
        cc._DB_PATH = original
        os.unlink(db_path)


# ── Preserved original tests ──────────────────────────────────────────────────

def test_set_and_get_roundtrip():
    import app.data.confidence_cache as cc
    cc.clear_cache()
    key = cc.cache_key("AAPL", "Bullish", "Swing")
    assert cc.get_cached(key) is None
    cc.set_cached(key, {"confidence": 62, "sample_size": 140})
    assert cc.get_cached(key)["confidence"] == 62


def test_cache_key_is_stable_and_distinct():
    import app.data.confidence_cache as cc
    assert cc.cache_key("AAPL", "Bullish", "Swing") == cc.cache_key("aapl", "bullish", "swing")
    assert cc.cache_key("AAPL", "Bullish", "Swing") != cc.cache_key("AAPL", "Bearish", "Swing")


def test_cache_key_includes_atr_mult():
    import app.data.confidence_cache as cc
    assert cc.cache_key("AAPL", "Bullish", "Swing", 1.5) != cc.cache_key("AAPL", "Bullish", "Swing", 2.0)
    assert cc.cache_key("AAPL", "Bullish", "Swing", 1.5) == cc.cache_key("AAPL", "Bullish", "Swing", 1.5)


def test_cache_key_default_does_not_collide_with_explicit_default_value():
    import app.data.confidence_cache as cc
    assert cc.cache_key("AAPL", "Bullish", "Swing", None) != cc.cache_key("AAPL", "Bullish", "Swing", 1.5)


def test_cache_key_omitting_atr_mult_matches_explicit_none():
    """Regression: after the atrMult-control removal, every live caller omits
    atr_mult entirely. Omitting it must produce the same 'default' sentinel as
    passing None explicitly — not silently key as the old 1.5 default."""
    import app.data.confidence_cache as cc
    assert cc.cache_key("AAPL", "Bullish", "Swing") == cc.cache_key("AAPL", "Bullish", "Swing", None)
    assert cc.cache_key("AAPL", "Bullish", "Swing") != cc.cache_key("AAPL", "Bullish", "Swing", 1.5)


def test_ttl_evicts_stale_entries(monkeypatch):
    import app.data.confidence_cache as cc

    cc.clear_cache()
    key = cc.cache_key("MSFT", "Bullish", "Swing")
    base = cc.time.time()
    cc.set_cached(key, {"confidence": 50, "sample_size": 30})
    # jump time well past the TTL relative to when it was stored
    monkeypatch.setattr(cc.time, "time", lambda: base + cc._TTL_SECONDS + 10_000)
    assert cc.get_cached(key) is None
