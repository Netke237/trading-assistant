from unittest.mock import patch, MagicMock

from app.data import tastytrade_session


def test_get_session_returns_none_when_unconfigured():
    with patch("app.services.credential_store.credential_store.get", return_value={
        "client_secret": "", "refresh_token": "", "account_id": "",
    }):
        tastytrade_session._SESSION_CACHE.clear()
        assert tastytrade_session.get_session("tastytrade_paper") is None


def test_get_session_builds_and_caches_session():
    tastytrade_session._SESSION_CACHE.clear()
    fake_creds = {"client_secret": "sec", "refresh_token": "ref", "account_id": "acct"}
    with patch("app.services.credential_store.credential_store.get", return_value=fake_creds), \
         patch("app.data.tastytrade_session.Session") as MockSession:
        mock_instance = MagicMock()
        MockSession.return_value = mock_instance

        first = tastytrade_session.get_session("tastytrade_paper")
        second = tastytrade_session.get_session("tastytrade_paper")

        MockSession.assert_called_once_with("sec", "ref", is_test=False)
        assert first is mock_instance
        assert second is mock_instance  # cached, not rebuilt


def test_get_session_always_uses_is_test_false_for_both_slots():
    # tastytrade's sandbox flag is independent of "paper trading account" —
    # Kenneth's tastytrade_paper slot still points at a real production OAuth
    # grant for a paper-trading *account*, not tastytrade's sandbox/cert
    # environment (which resets every 24h and is unsuitable for persistent
    # use, per the investigation in this plan's header). So is_test is always
    # False for both slots; this test locks that decision in so a future edit
    # doesn't accidentally point tastytrade_paper at the 24h-reset sandbox.
    tastytrade_session._SESSION_CACHE.clear()
    fake_creds = {"client_secret": "sec", "refresh_token": "ref", "account_id": "acct"}
    with patch("app.services.credential_store.credential_store.get", return_value=fake_creds), \
         patch("app.data.tastytrade_session.Session") as MockSession:
        tastytrade_session.get_session("tastytrade_live")
        MockSession.assert_called_once_with("sec", "ref", is_test=False)
