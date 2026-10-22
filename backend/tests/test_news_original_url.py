"""#265 PB-PRES-07 — provider-supplied original article links on NewsItem.

The `url` field is additive: it is populated only from an absolute http(s)
link the provider itself supplied, never constructed from the publisher or
headline, and every pre-existing field keeps its value.
"""
from __future__ import annotations

import sys
import types

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import market
from app.schemas import NewsItem

INVALID_LINKS = [
    "javascript:alert(1)",
    "/relative/article",
    "finance.yahoo.com/news/x",
    "ftp://example.com/x",
    "data:text/html,hi",
    "mailto:a@example.com",
    "http://",
    "https:///no-host",
    "",
    "   ",
    "https://exa mple.com/space",
    None,
    123,
    {"url": "https://example.com/nested"},
]


def _install_fake_yf(monkeypatch, news_by_symbol: dict[str, list]) -> None:
    fake = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, sym):
            self.news = news_by_symbol.get(sym, [])

    fake.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def _new_shape(uid="n1", canonical=None, click=None, title="New headline"):
    content = {
        "id": uid,
        "title": title,
        "pubDate": "2026-10-01T12:00:00Z",
        "provider": {"displayName": "Reuters"},
    }
    if canonical is not ...:
        content["canonicalUrl"] = {"url": canonical} if canonical is not None else None
    if click is not ...:
        content["clickThroughUrl"] = {"url": click} if click is not None else None
    return {"id": uid, "content": content}


# ── yfinance ────────────────────────────────────────────────────────────────

def test_yf_new_shape_uses_canonical_url(monkeypatch):
    _install_fake_yf(monkeypatch, {"AAPL": [
        _new_shape(canonical="https://www.reuters.com/a", click="https://finance.yahoo.com/b"),
    ]})
    [item] = market._fetch_news_yf(["AAPL"])
    assert item["url"] == "https://www.reuters.com/a"
    # Existing fields unchanged.
    assert {k: item[k] for k in ("id", "symbol", "headline", "source", "timestamp", "sentiment")} == {
        "id": "n1", "symbol": "AAPL", "headline": "New headline", "source": "Reuters",
        "timestamp": "2026-10-01T12:00:00Z", "sentiment": "neutral",
    }


def test_yf_new_shape_falls_back_to_click_through_url(monkeypatch):
    _install_fake_yf(monkeypatch, {"AAPL": [_new_shape(canonical=None, click="http://example.com/c")]})
    [item] = market._fetch_news_yf(["AAPL"])
    assert item["url"] == "http://example.com/c"


def test_yf_new_shape_invalid_canonical_falls_back_to_valid_click(monkeypatch):
    _install_fake_yf(monkeypatch, {"AAPL": [_new_shape(canonical="javascript:alert(1)", click="https://ok.example/x")]})
    [item] = market._fetch_news_yf(["AAPL"])
    assert item["url"] == "https://ok.example/x"


def test_yf_legacy_shape_uses_top_level_link(monkeypatch):
    _install_fake_yf(monkeypatch, {"AAPL": [{
        "uuid": "u", "id": "legacy1", "title": "Legacy headline", "publisher": "Bloomberg",
        "link": "https://www.bloomberg.com/legacy", "relatedTickers": ["AAPL"],
    }]})
    [item] = market._fetch_news_yf(["AAPL"])
    assert item["url"] == "https://www.bloomberg.com/legacy"
    assert item["headline"] == "Legacy headline"
    assert item["source"] == "Bloomberg"
    assert item["timestamp"] == ""


@pytest.mark.parametrize("bad", INVALID_LINKS)
def test_yf_invalid_links_yield_no_url(monkeypatch, bad):
    _install_fake_yf(monkeypatch, {"AAPL": [
        _new_shape(uid="a", canonical=bad, click=bad),
        {"id": "b", "title": "Legacy", "publisher": "P", "link": bad},
    ]})
    items = market._fetch_news_yf(["AAPL"])
    assert len(items) == 2
    assert all(i.get("url") is None for i in items)


def test_yf_missing_link_yields_no_url_and_never_constructs_one(monkeypatch):
    _install_fake_yf(monkeypatch, {"AAPL": [_new_shape(canonical=..., click=...)]})
    [item] = market._fetch_news_yf(["AAPL"])
    assert item.get("url") is None
    assert "url" not in item  # absent, not constructed from publisher/headline


def test_yf_non_dict_url_containers_are_ignored(monkeypatch):
    item = _new_shape(canonical=..., click=...)
    item["content"]["canonicalUrl"] = "https://string-not-dict.example"
    item["content"]["clickThroughUrl"] = ["https://list.example"]
    _install_fake_yf(monkeypatch, {"AAPL": [item]})
    [out] = market._fetch_news_yf(["AAPL"])
    assert out.get("url") is None


# ── Tradier ─────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _tradier(monkeypatch, articles):
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("tok", "https://sandbox.tradier.com"))
    monkeypatch.setattr(market, "_tradier_get", lambda *a, **k: _Resp({"news": {"article": articles}}))
    monkeypatch.setattr(market, "_fetch_news_yf", lambda symbols, limit=20: [])


def test_tradier_article_url_field(monkeypatch):
    _tradier(monkeypatch, [{"id": 7, "symbols": "AAPL,MSFT", "title": "T", "source": "S",
                            "datetime": "2026-10-01T12:00:00Z", "url": "https://news.example/7"}])
    [item] = market.fetch_news(["AAPL"])
    assert item["url"] == "https://news.example/7"
    assert {k: item[k] for k in ("id", "symbol", "headline", "source", "timestamp", "sentiment")} == {
        "id": "7", "symbol": "AAPL", "headline": "T", "source": "S",
        "timestamp": "2026-10-01T12:00:00Z", "sentiment": "neutral",
    }


def test_tradier_article_link_field(monkeypatch):
    _tradier(monkeypatch, {"id": 8, "symbols": "AAPL", "title": "T", "source": "S",
                           "datetime": "", "link": "http://news.example/8"})
    [item] = market.fetch_news(["AAPL"])
    assert item["url"] == "http://news.example/8"


@pytest.mark.parametrize("bad", INVALID_LINKS)
def test_tradier_invalid_url_yields_no_url(monkeypatch, bad):
    _tradier(monkeypatch, [{"id": 9, "symbols": "AAPL", "title": "T", "source": "S",
                            "datetime": "", "url": bad, "link": bad}])
    [item] = market.fetch_news(["AAPL"])
    assert item.get("url") is None


def test_tradier_missing_url_keeps_existing_shape(monkeypatch):
    _tradier(monkeypatch, [{"id": 10, "symbols": "AAPL", "title": "T", "source": "S", "datetime": ""}])
    [item] = market.fetch_news(["AAPL"])
    assert item == {"id": "10", "symbol": "AAPL", "headline": "T", "source": "S",
                    "timestamp": "", "sentiment": "neutral"}


# ── Schema + /api/news ──────────────────────────────────────────────────────

def test_news_item_schema_url_is_optional():
    base = {"id": "1", "symbol": "AAPL", "headline": "H", "source": "S", "timestamp": ""}
    assert NewsItem(**base).url is None
    assert NewsItem(**base, url="https://x.example").url == "https://x.example"


@pytest.mark.asyncio
async def test_api_news_response_includes_url(monkeypatch):
    from app.main import app
    import app.routers.news as news_router

    monkeypatch.setattr(news_router, "fetch_news", lambda syms: [
        {"id": "1", "symbol": "AAPL", "headline": "With link", "source": "S", "timestamp": "",
         "sentiment": "neutral", "url": "https://x.example/1"},
        {"id": "2", "symbol": "AAPL", "headline": "No link", "source": "S", "timestamp": "",
         "sentiment": "neutral"},
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/news", params={"symbols": "aapl"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["url"] == "https://x.example/1"
    assert "url" in body[1] and body[1]["url"] is None
    assert body[1] == {"id": "2", "symbol": "AAPL", "headline": "No link", "source": "S",
                       "timestamp": "", "sentiment": "neutral", "url": None}
