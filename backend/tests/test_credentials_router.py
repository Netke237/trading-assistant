import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.credential_store import credential_store


@pytest.mark.asyncio
async def test_post_credentials_accepts_tastytrade_paper():
    original = credential_store.get("tastytrade_paper")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/settings/credentials", json={
                "key": "tastytrade_paper",
                "values": {"client_secret": "x", "refresh_token": "y", "account_id": "z"},
            })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "key": "tastytrade_paper"}
    finally:
        credential_store.set("tastytrade_paper", original)
        credential_store.save()


@pytest.mark.asyncio
async def test_post_credentials_accepts_tastytrade_live():
    original = credential_store.get("tastytrade_live")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/settings/credentials", json={
                "key": "tastytrade_live",
                "values": {"client_secret": "x", "refresh_token": "y", "account_id": "z"},
            })
        assert resp.status_code == 200
    finally:
        credential_store.set("tastytrade_live", original)
        credential_store.save()
