"""Step 3's "Min stock score" must not move the options contract floor.

`min_stock_score` is a Stocks-mode drop line (StockScanRequest.min_stock_score),
but it is also a contract_validator override key. Before this guard an options
scan that carried it in `overrides` replaced contract_rules.yaml's floor (55).
The frontend has stopped sending it (resolveOptionsScanRequest.ts), but two
stored copies outlive that fix: schedule entries' persisted resolved_request,
and scan results persisted client-side, which Step 6 sends back to
/api/contracts as `contract_rules`. Both are pinned here.
"""
import json

from app.routers.contracts import _parse_contract_rules
from app.schemas import ScanRequest
from app.scoring.contract_validator import effective_contract_overrides


def _req(overrides: dict) -> ScanRequest:
    # model_validate, as scan_schedule_scheduler rebuilds a stored entry.
    return ScanRequest.model_validate({
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": overrides,
    })


def test_scan_request_drops_min_stock_score_and_keeps_other_overrides():
    req = _req({"min_stock_score": 20, "min_volume": 5, "weight_trend": 30})
    assert "min_stock_score" not in req.overrides
    assert req.overrides == {"min_volume": 5, "weight_trend": 30}
    assert effective_contract_overrides(req.overrides) == {"min_volume": 5}


def test_contracts_endpoint_ignores_a_recorded_min_stock_score():
    rules = _parse_contract_rules(json.dumps({"min_stock_score": 20, "min_volume": 5}))
    assert rules == {"min_volume": 5}
