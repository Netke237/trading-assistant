"""CORS_EXTRA_ORIGINS — opt-in LAN origins on top of the localhost dev origins.

Opening the frontend from another PC on the LAN (http://<lan-ip>:3001) makes
the browser send that Origin to the API; without it in allow_origins every
fetch fails CORS. The default must stay localhost-only, and "*" is refused
because allow_credentials=True plus a wildcard would let any site drive this
unauthenticated API from a visitor's browser.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, cors_origins, get_settings

LOCALHOST = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3003"]
LAN = "http://192.0.2.10:3001"


def test_default_is_localhost_only():
    assert cors_origins(Settings(CORS_EXTRA_ORIGINS="")) == LOCALHOST


def test_extra_origins_are_appended_trimmed_and_deduplicated():
    s = Settings(CORS_EXTRA_ORIGINS=f" {LAN}/ , ,http://localhost:3001,{LAN}")
    assert cors_origins(s) == LOCALHOST + [LAN]


def test_wildcard_is_refused():
    with pytest.raises(ValueError, match="explicit origins"):
        cors_origins(Settings(CORS_EXTRA_ORIGINS=f"{LAN},*"))


@pytest.fixture
def app_with_lan_origin(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", LAN)
    get_settings.cache_clear()
    from app.main import create_app

    yield create_app()  # TestClient without `with` never runs the lifespan
    get_settings.cache_clear()


@pytest.mark.parametrize("origin, allowed", [(LAN, True), ("http://localhost:3001", True),
                                             ("http://192.0.2.99:3001", False)])
def test_preflight_honours_configured_origin(app_with_lan_origin, origin, allowed):
    client = TestClient(app_with_lan_origin)
    r = client.options("/health", headers={"Origin": origin,
                                           "Access-Control-Request-Method": "GET"})
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed
