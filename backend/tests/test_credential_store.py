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
