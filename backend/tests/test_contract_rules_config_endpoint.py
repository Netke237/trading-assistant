from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.scoring import contract_validator


@pytest.mark.asyncio
async def test_get_contract_rules_returns_min_stock_score():
    """GET /api/config/contract-rules returns min_stock_score from contract_rules.yaml."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/contract-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert "min_stock_score" in data
    # Shipped default in contract_rules.yaml is 45
    assert data["min_stock_score"] == 45
    assert isinstance(data["min_stock_score"], int)


@pytest.mark.asyncio
async def test_get_contract_rules_reflects_loaded_config(monkeypatch):
    """GET /api/config/contract-rules reflects changes in contract_rules config."""
    monkeypatch.setattr(
        contract_validator,
        "_load_config",
        lambda: {"hard_reject": {"min_stock_score": 35}},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/contract-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert data["min_stock_score"] == 35
