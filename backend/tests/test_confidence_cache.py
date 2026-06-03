from app.data.confidence_cache import cache_key, get_cached, set_cached, clear_cache


def test_set_and_get_roundtrip():
    clear_cache()
    key = cache_key("AAPL", "Bullish", "Swing")
    assert get_cached(key) is None
    set_cached(key, {"confidence": 62, "sample_size": 140})
    assert get_cached(key)["confidence"] == 62


def test_cache_key_is_stable_and_distinct():
    assert cache_key("AAPL", "Bullish", "Swing") == cache_key("aapl", "bullish", "swing")
    assert cache_key("AAPL", "Bullish", "Swing") != cache_key("AAPL", "Bearish", "Swing")


def test_ttl_evicts_stale_entries(monkeypatch):
    import app.data.confidence_cache as cc

    cc.clear_cache()
    key = cc.cache_key("MSFT", "Bullish", "Swing")
    base = cc.time.time()
    cc.set_cached(key, {"confidence": 50, "sample_size": 30})  # stores _ts ~= base
    # jump time well past the TTL relative to when it was stored
    monkeypatch.setattr(cc.time, "time", lambda: base + cc._TTL_SECONDS + 10_000)
    assert cc.get_cached(key) is None
