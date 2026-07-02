"""Tests for IBKR keep-alive: paper-gateway auth check and the scheduler wrapper."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_paper_gateway_available_true_on_authenticated():
    from app.data import ibkr_paper

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"authenticated": True}

    with patch("httpx.get", return_value=mock_resp) as mock_get, \
         patch("httpx.post") as mock_post:
        ibkr_paper._auth_cache = None  # reset module cache between tests
        result = ibkr_paper.paper_gateway_available()

    assert result is True
    mock_get.assert_called_once()
    mock_post.assert_called_once()  # tickle fired on success


def test_paper_gateway_available_false_on_connection_error():
    from app.data import ibkr_paper

    with patch("httpx.get", side_effect=Exception("connection refused")):
        ibkr_paper._auth_cache = None
        result = ibkr_paper.paper_gateway_available()

    assert result is False


def test_keepalive_scheduler_start_and_shutdown_are_idempotent():
    from app.services import ibkr_keepalive_scheduler as sched

    sched.start()
    sched.start()  # must not raise or double-register the job
    assert sched._get().running is True
    sched.shutdown()
    sched.shutdown()  # must not raise


def test_keepalive_scheduler_can_restart_after_shutdown():
    from app.services import ibkr_keepalive_scheduler as sched

    sched.start()
    sched.shutdown()
    sched.start()  # must build a fresh scheduler instance, not restart the shut-down one
    assert sched._get().running is True
    sched.shutdown()
