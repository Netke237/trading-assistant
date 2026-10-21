"""Unit tests for app.scoring.entry_quality.assess_entry()."""

from app.scoring.entry_quality import assess_entry, EntryConfig


# ── PASS ─────────────────────────────────────────────────────────────────────

def test_pass_normal_spread():
    """spread_pct == tolerance boundary (0.10) is not > 0.10 → PASS."""
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.quality_status == "PASS"
    assert ea.quality_reasons == []


def test_pass_limit_price():
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.limit_price == 2.00


def test_pass_max_fill():
    """max_fill = round(mid * 1.03, 2)."""
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.max_fill == 2.06


def test_pass_order_type_always_limit():
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
    assert ea.order_type == "Limit"


# ── CAUTION ──────────────────────────────────────────────────────────────────

def test_caution_elevated_spread():
    """spread_pct = 0.25 — above 1× tolerance (0.10), below 3× (0.30) → CAUTION."""
    ea = assess_entry(bid=1.75, ask=2.25, mid=2.00)
    assert ea.quality_status == "CAUTION"
    assert "elevated spread" in ea.quality_reasons


def test_caution_does_not_set_wide_spread():
    ea = assess_entry(bid=1.75, ask=2.25, mid=2.00)
    assert "wide spread" not in ea.quality_reasons


# ── REJECT ───────────────────────────────────────────────────────────────────

def test_reject_wide_spread():
    """spread_pct = 1.50 — above 3× tolerance → REJECT."""
    ea = assess_entry(bid=0.50, ask=3.50, mid=2.00)
    assert ea.quality_status == "REJECT"
    assert "wide spread" in ea.quality_reasons


def test_reject_premium_too_low():
    """mid = 0.05 < min_premium 0.10 → REJECT."""
    ea = assess_entry(bid=0.04, ask=0.06, mid=0.05)
    assert ea.quality_status == "REJECT"
    assert "premium too low" in ea.quality_reasons


def test_reject_both_reasons_present():
    """mid too low AND wide spread → both reasons in list."""
    ea = assess_entry(bid=0.04, ask=0.06, mid=0.05)
    assert "premium too low" in ea.quality_reasons
    assert "wide spread" in ea.quality_reasons


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_zero_mid_falls_back_to_reject():
    """mid = 0 → spread_pct fallback = 1.0 → wide spread + premium too low."""
    ea = assess_entry(bid=0.00, ask=0.00, mid=0.00)
    assert ea.quality_status == "REJECT"


def test_custom_config_tighter_tolerance():
    """With spread_tolerance_pct=0.05, a 10% spread (previously PASS) becomes CAUTION."""
    cfg = EntryConfig(spread_tolerance_pct=0.05)
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, config=cfg)
    assert ea.quality_status == "CAUTION"
    assert "elevated spread" in ea.quality_reasons


def test_custom_config_max_fill_uses_slippage():
    """max_fill uses config.max_slippage_pct, not the default."""
    cfg = EntryConfig(max_slippage_pct=0.10)
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, config=cfg)
    assert ea.max_fill == round(2.00 * 1.10, 2)


def test_large_premium_clears_all_checks():
    ea = assess_entry(bid=9.80, ask=10.20, mid=10.00)
    assert ea.quality_status == "PASS"
    assert ea.limit_price == 10.00


# ── M3: crossed / stale quotes ───────────────────────────────────────────────

def test_crossed_quote_rejects():
    """bid > ask (crossed/stale quote) must REJECT regardless of the resulting
    negative spread_pct — this must not silently PASS."""
    ea = assess_entry(bid=2.10, ask=1.90, mid=2.00)
    assert ea.quality_status == "REJECT"
    assert "crossed quote" in ea.quality_reasons


def test_crossed_quote_with_narrow_gap_still_rejects():
    """Even a tiny crossed gap (bid=2.01, ask=1.99) must REJECT — the bug was that
    abs(spread) could look narrow and pass."""
    ea = assess_entry(bid=2.01, ask=1.99, mid=2.00)
    assert ea.quality_status == "REJECT"
    assert "crossed quote" in ea.quality_reasons


def test_crossed_quote_combines_with_other_reject_reasons():
    """Crossed quote AND premium too low should both appear in quality_reasons."""
    ea = assess_entry(bid=0.06, ask=0.04, mid=0.05)
    assert ea.quality_status == "REJECT"
    assert "crossed quote" in ea.quality_reasons
    assert "premium too low" in ea.quality_reasons


def test_equal_bid_ask_is_not_crossed():
    """bid == ask (zero spread) is a valid, if unusual, quote — must NOT trigger
    the crossed-quote reason."""
    ea = assess_entry(bid=2.00, ask=2.00, mid=2.00)
    assert "crossed quote" not in ea.quality_reasons


# ── NO-LIVE-QUOTE (plan 3e, test T9): quote_live ────────────────────────────

_NLQ_REASON = "no live quote — entry priced off the last close"


def test_quote_live_false_caps_a_pass_entry_at_caution_with_the_reason():
    ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, quote_live=False)
    assert ea.quality_status == "CAUTION"
    assert ea.quality_reasons == [_NLQ_REASON]
    # The prices are unchanged: only the grade says the quote is not live.
    assert (ea.limit_price, ea.max_fill, ea.order_type) == (2.00, 2.06, "Limit")


def test_quote_live_none_and_true_keep_todays_behaviour():
    for ql in (None, True):
        ea = assess_entry(bid=1.90, ask=2.10, mid=2.00, quote_live=ql)
        assert ea.quality_status == "PASS"
        assert ea.quality_reasons == []
    ea = assess_entry(bid=1.75, ask=2.25, mid=2.00, quote_live=None)
    assert ea.quality_status == "CAUTION"
    assert ea.quality_reasons == ["elevated spread"]


def test_quote_live_false_never_lifts_a_reject():
    ea = assess_entry(bid=0.50, ask=3.50, mid=2.00, quote_live=False)
    assert ea.quality_status == "REJECT"
    assert "wide spread" in ea.quality_reasons
    assert _NLQ_REASON in ea.quality_reasons


def test_recompute_plan_forwards_quote_live_to_assess_entry():
    import asyncio
    from unittest.mock import patch
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    import app.scoring.trade_plan as trade_plan
    from app.routers.contracts import router as contracts_router

    app = FastAPI()
    app.include_router(contracts_router)
    payload = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
        "strike": 190.0, "dte": 30, "premium": 2.50, "delta": 0.45, "spread": 0.10,
    }
    seen = []
    real = trade_plan.assess_entry

    def _spy(*a, **k):
        res = real(*a, **k)
        seen.append((k.get("quote_live"), res.quality_status, list(res.quality_reasons)))
        return res

    async def _post(body):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/contracts/recompute-plan", json=body)
        assert r.status_code == 200, r.text

    with patch.object(trade_plan, "assess_entry", _spy):
        asyncio.run(_post(payload))
        asyncio.run(_post({**payload, "quote_live": False}))
        asyncio.run(_post({**payload, "quote_live": True}))
    assert seen == [
        (None, "PASS", []),
        (False, "CAUTION", [_NLQ_REASON]),
        (True, "PASS", []),
    ]

# ── APP-AUDIT-B-ENTRY-OVERRIDES: resolve_entry_config & overrides ────────────

def test_resolve_entry_config_defaults():
    from app.services.config_loader import resolve_entry_config
    cfg_empty = resolve_entry_config({})
    cfg_none = resolve_entry_config(None)
    assert cfg_empty.spread_tolerance_pct == 0.10
    assert cfg_empty.max_slippage_pct == 0.03
    assert cfg_empty.min_premium == 0.10
    assert cfg_none == cfg_empty


def test_resolve_entry_config_custom_values():
    from app.services.config_loader import resolve_entry_config
    overrides = {
        "entry_spread_tolerance_pct": 0.20,
        "entry_max_slippage_pct": 0.05,
        "entry_min_premium": 2.50,
    }
    cfg = resolve_entry_config(overrides)
    assert cfg.spread_tolerance_pct == 0.20
    assert cfg.max_slippage_pct == 0.05
    assert cfg.min_premium == 2.50

    # Also supports direct config keys for direct callers
    direct = {
        "spread_tolerance_pct": 0.15,
        "max_slippage_pct": 0.02,
        "min_premium": 1.0,
    }
    cfg_direct = resolve_entry_config(direct)
    assert cfg_direct.spread_tolerance_pct == 0.15
    assert cfg_direct.max_slippage_pct == 0.02
    assert cfg_direct.min_premium == 1.0


def test_resolve_entry_config_zero_values_preserved():
    from app.services.config_loader import resolve_entry_config
    # Explicit zero overrides (0% slippage, 0 spread tolerance, 0 min premium)
    overrides = {
        "entry_spread_tolerance_pct": 0,
        "entry_max_slippage_pct": 0.0,
        "entry_min_premium": 0,
    }
    cfg = resolve_entry_config(overrides)
    assert cfg.spread_tolerance_pct == 0.0
    assert cfg.max_slippage_pct == 0.0
    assert cfg.min_premium == 0.0


def test_resolve_entry_config_validation_errors():
    import pytest
    from app.services.config_loader import resolve_entry_config

    with pytest.raises(ValueError, match=r"finite number in \[0, 1.0\]"):
        resolve_entry_config({"entry_spread_tolerance_pct": -0.05})

    with pytest.raises(ValueError, match=r"finite number in \[0, 1.0\]"):
        resolve_entry_config({"entry_spread_tolerance_pct": 1.05})

    with pytest.raises(ValueError, match=r"finite number in \[0, 1.0\]"):
        resolve_entry_config({"entry_max_slippage_pct": -0.01})

    with pytest.raises(ValueError, match=r"finite number in \[0, 100.0\]"):
        resolve_entry_config({"entry_min_premium": -1.0})

    with pytest.raises(ValueError, match=r"finite number in \[0, 100.0\]"):
        resolve_entry_config({"entry_min_premium": 105.0})

    with pytest.raises(ValueError, match="finite number"):
        resolve_entry_config({"entry_spread_tolerance_pct": float("nan")})

    with pytest.raises(ValueError, match="finite number"):
        resolve_entry_config({"entry_max_slippage_pct": float("inf")})

    with pytest.raises(ValueError, match="finite number"):
        resolve_entry_config({"entry_min_premium": "not_a_number"})


def test_effective_entry_overrides():
    from app.services.config_loader import effective_entry_overrides
    assert effective_entry_overrides(None) == {}
    assert effective_entry_overrides({}) == {}
    assert effective_entry_overrides({"unrelated": 123}) == {}

    overrides = {
        "entry_spread_tolerance_pct": 0.15,
        "entry_max_slippage_pct": 0,
        "entry_min_premium": 5.0,
        "rr_target_r_multiple": 2.0,
    }
    effective = effective_entry_overrides(overrides)
    assert effective == {
        "entry_spread_tolerance_pct": 0.15,
        "entry_max_slippage_pct": 0.0,
        "entry_min_premium": 5.0,
    }

