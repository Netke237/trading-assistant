import os
import pytest
import tempfile
from pathlib import Path

os.environ["BAMENDJOU_CREDS_PATH"] = ""

from app.services.credential_store import CredentialStore


def test_store_sets_and_gets():
    store = CredentialStore(path=None)
    store.set("tradier_paper", {"token": "abc123", "account_id": "TA1234"})
    creds = store.get("tradier_paper")
    assert creds["token"] == "abc123"
    assert creds["account_id"] == "TA1234"


def test_store_masks_tokens():
    store = CredentialStore(path=None)
    store.set("tradier_paper", {"token": "supersecret", "account_id": "TA1234"})
    masked = store.get_masked("tradier_paper")
    assert "supersecret" not in masked["token"]
    assert masked["token"].endswith("cret")
    assert masked["token"].startswith("*")


def test_store_persists_to_and_loads_from_file():
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        store = CredentialStore(path=Path(path))
        store.set("tradier_paper", {"token": "mytoken", "account_id": "ACC"})
        store.save()
        store2 = CredentialStore(path=Path(path))
        store2.load()
        assert store2.get("tradier_paper")["token"] == "mytoken"
    finally:
        os.unlink(path)


def test_store_get_unknown_key_returns_none():
    store = CredentialStore(path=None)
    assert store.get("nonexistent") is None


def test_all_returns_masked_dict():
    store = CredentialStore(path=None)
    store.set("ibkr_paper", {"base_url": "https://localhost:7499/v1/api", "account_id": ""})
    result = store.all_masked()
    assert "ibkr_paper" in result


def test_load_ignores_unknown_broker_keys():
    """Stray/legacy keys in the YAML file must not leak into the store."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        Path(path).write_text(
            "tradier_paper:\n  token: realtok\n  account_id: ACC\n"
            "unknown_broker:\n  token: xyz\n"
        )
        store = CredentialStore(path=Path(path))  # loads on init
        assert store.get("tradier_paper")["token"] == "realtok"
        assert store.get("unknown_broker") is None
        assert "unknown_broker" not in store.all_masked()
    finally:
        os.unlink(path)


from fastapi.testclient import TestClient
from fastapi import FastAPI


def _make_app():
    from app.routers.credentials import router
    app = FastAPI()
    app.include_router(router)
    return app


def test_post_credentials_stores_and_get_returns_masked():
    client = TestClient(_make_app())
    resp = client.post("/settings/credentials", json={
        "key": "tradier_paper",
        "values": {"token": "tok_secret", "account_id": "ACC123"}
    })
    assert resp.status_code == 200, resp.text
    resp2 = client.get("/settings/credentials")
    data = resp2.json()
    assert "tradier_paper" in data
    assert "secret" not in data["tradier_paper"].get("token", "")


def test_alpaca_slots_exist_by_default(tmp_path):
    store = CredentialStore(path=tmp_path / "creds.yaml")
    assert store.get("alpaca_live") == {
        "key_id": "", "secret_key": "", "base_url": "https://api.alpaca.markets",
    }
    assert store.get("alpaca_paper") == {
        "key_id": "", "secret_key": "", "base_url": "https://paper-api.alpaca.markets",
    }


def test_secret_key_is_masked(tmp_path):
    store = CredentialStore(path=tmp_path / "creds.yaml")
    store.set("alpaca_paper", {"key_id": "PKID", "secret_key": "abcd1234SECRET"})
    masked = store.get_masked("alpaca_paper")
    assert masked["secret_key"].endswith("CRET")
    assert masked["secret_key"].startswith("*")
    assert masked["key_id"] == "PKID"  # key_id is not sensitive
