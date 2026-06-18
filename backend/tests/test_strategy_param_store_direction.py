import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app.services.strategy_param_store as store

def test_get_active_is_direction_keyed(tmp_path, monkeypatch):
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(
        "strategies:\n"
        "  pullback_ema:\n"
        "    active:\n"
        "      bullish: { ema_period: 50 }\n"
        "      bearish: { ema_period: 35 }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    assert store.get_active("pullback_ema", "Bullish")["ema_period"] == 50
    assert store.get_active("pullback_ema", "Bearish")["ema_period"] == 35

def test_get_active_migrates_legacy_flat_active(tmp_path, monkeypatch):
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(
        "strategies:\n  pullback_ema:\n    active: { ema_period: 50 }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    # legacy flat active is treated as the bullish set
    assert store.get_active("pullback_ema", "Bullish")["ema_period"] == 50
    assert store.get_active("pullback_ema", "Bearish") == {}
