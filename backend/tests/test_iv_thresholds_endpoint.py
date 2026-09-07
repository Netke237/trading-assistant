from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_iv_thresholds_endpoint_returns_all_horizons():
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"Intraday", "Swing", "Position"}


def test_iv_thresholds_swing_matches_yaml():
    """The ABSOLUTE set carries the numbers this gate has always applied.

    34/55 judged an absolute IV before 2026-09-06 while being named for a
    percentile; the Phase A split moved them to the `abs_*` keys, so the values
    the client sees for a Tradier-only chain are unchanged.
    """
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    swing = response.json()["Swing"]
    assert swing["abs_pass_max"] == 34
    assert swing["abs_caution_max"] == 55


def test_iv_thresholds_serves_both_sets_separately():
    """Both quantities are served, and neither is offered under a bare name.

    An unqualified `pass_max` is exactly the ambiguity Phase A exists to kill:
    a client reading it cannot know whether it is allowed to judge the
    absolute IV it is holding.
    """
    swing = client.get("/api/config/iv-thresholds").json()["Swing"]
    assert set(swing.keys()) == {
        "abs_pass_max", "abs_caution_max", "rank_pass_max", "rank_caution_max",
    }
    assert "pass_max" not in swing
    assert "caution_max" not in swing
    # Seeded to match today — the split is structural, so these may diverge
    # once the percentile thresholds are actually measured.
    assert swing["rank_pass_max"] == 34
    assert swing["rank_caution_max"] == 55


def test_iv_thresholds_intraday_is_null_on_both_bases():
    """Intraday has no IV gate at all, on either quantity."""
    intraday = client.get("/api/config/iv-thresholds").json()["Intraday"]
    assert intraday["abs_pass_max"] is None
    assert intraday["abs_caution_max"] is None
    assert intraday["rank_pass_max"] is None
    assert intraday["rank_caution_max"] is None
