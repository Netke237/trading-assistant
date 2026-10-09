"""Fix #4: with no protective order a long option can lose 100% of premium,
so the premium cap must not exceed max_loss_per_trade_pct (3.75% < 5%)."""
from app.services import portfolio_risk as pr


def _cfg(monkeypatch, single=0.05, loss=0.0375):
    cfg = {
        "portfolio": {"max_total_exposure_pct": 0.25, "max_concurrent_positions": 10,
                      "max_daily_recommendations": 5, "max_same_symbol_positions": 1,
                      "min_portfolio_value": 5000.0, "max_single_position_pct": single,
                      "max_loss_per_trade_pct": loss},
        "sizing": {"max_contracts_per_trade": 50},
    }
    monkeypatch.setattr(pr, "_load_config", lambda: cfg)


def test_option_premium_clamped_to_loss_limit(monkeypatch):
    _cfg(monkeypatch)
    # $4.50 premium x 100 = $450/contract; 10 contracts = $4,500 = 4.5% of 100k
    r = pr.check_position_risk("AAPL", "AAPL|185|2026-11-20|C", 10, 4.50, 4.50, [], 100_000)
    assert r.adjusted_size == 8           # 8 x 450 = 3,600 <= 3,750
    assert "size_reduced_to_fit_exposure_limit" in r.reasons
    assert r.approved


def test_option_one_contract_over_loss_limit_refused(monkeypatch):
    _cfg(monkeypatch)
    r = pr.check_position_risk("AAPL", "AAPL|185|2026-11-20|C", 1, 40.0, 40.0, [], 100_000)
    assert not r.approved and "single_trade_exposure_too_high" in r.reasons


def test_stock_unaffected_by_option_loss_cap(monkeypatch):
    _cfg(monkeypatch)
    r = pr.check_position_risk("AAPL", "AAPL|STOCK", 100, 180.0, 180.0, [], 100_000)
    assert r.approved and r.adjusted_size is None


def test_looser_loss_limit_leaves_single_position_cap_binding(monkeypatch):
    """min(), not the loss limit alone: a loss limit above the 5% cap changes nothing."""
    _cfg(monkeypatch, single=0.05, loss=0.10)
    # $400/contract; 14 = $5,600 > 5,000 (5%); 12 x 400 = 4,800 fits
    r = pr.check_position_risk("AAPL", "AAPL|185|2026-11-20|C", 14, 4.0, 4.0, [], 100_000)
    assert r.adjusted_size == 12
