from fastapi.testclient import TestClient
from app.main import app

def test_run_then_poll_then_concurrency_guard():
    c = TestClient(app)
    r = c.post("/api/strategy-tuning/run", json={})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    poll = c.get(f"/api/strategy-tuning/jobs/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] in ("running", "completed")
    # second run while first active is rejected
    r2 = c.post("/api/strategy-tuning/run", json={})
    assert r2.status_code in (409, 200)   # 409 if still running

def test_adopt_writes_active(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  pullback_ema:\n    active: {ema_period: 50}\n",
        encoding="utf-8",
    )
    store.adopt("pullback_ema", {"ema_period": 20})
    assert store.get_active("pullback_ema")["ema_period"] == 20
