from app.schemas import ScanRequest
from app.services.fundamentals_gate import resolve_fundamentals_gate


def _req(**overrides) -> ScanRequest:
    base = dict(universe=["AAPL"], direction="Bearish", horizon="Swing")
    base.update(overrides)
    return ScanRequest.model_validate(base)


def test_bearish_scan_patches_caution_and_reject_above_into_gate():
    req = _req(fundamentals_caution_above=65, fundamentals_reject_above=85)
    gate = resolve_fundamentals_gate(req)
    assert gate["cautionAbove"] == 65
    assert gate["rejectAbove"] == 85


def test_bullish_scan_ignores_caution_and_reject_above():
    """The bearish-only override must not leak into bullish scans — those
    values only make sense for 'don't short a strong company' logic."""
    req = _req(direction="Bullish", fundamentals_caution_above=65, fundamentals_reject_above=85)
    gate = resolve_fundamentals_gate(req)
    assert gate.get("cautionAbove") != 65
    assert gate.get("rejectAbove") != 85


def test_absent_overrides_leave_yaml_defaults_untouched():
    req = _req()
    gate = resolve_fundamentals_gate(req)
    from app.services.config_loader import load_scoring_cfg
    default_gate = load_scoring_cfg().get("fundamentals_gate", {})
    assert gate.get("cautionAbove") == default_gate.get("cautionAbove")
    assert gate.get("rejectAbove") == default_gate.get("rejectAbove")
