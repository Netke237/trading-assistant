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
