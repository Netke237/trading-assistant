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


@pytest.mark.asyncio
async def test_post_tastytrade_credentials_clears_session_cache():
    from app.data import tastytrade_session
    original = credential_store.get("tastytrade_paper")
    tastytrade_session._SESSION_CACHE["tastytrade_paper"] = object()  # fake cached session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/settings/credentials", json={
                "key": "tastytrade_paper",
                "values": {"client_secret": "new", "refresh_token": "new", "account_id": "z"},
            })

        assert "tastytrade_paper" not in tastytrade_session._SESSION_CACHE
    finally:
        credential_store.set("tastytrade_paper", original)
        credential_store.save()
        tastytrade_session.clear_cache()
